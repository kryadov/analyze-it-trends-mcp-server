import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv
import yaml

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context

# Local modules
from tools.reddit_analyzer import RedditAnalyzer
from tools.report_generator import ReportGenerator
from tools.trends_searcher import TrendsSearcher
from tools.freelance_analyzer import FreelanceAnalyzer
from utils.cache_manager import CacheManager
from utils.data_processor import DataProcessor
from utils.api_clients import get_reddit_client

# -------------------------
# Bootstrap & configuration
# -------------------------
BASE_DIR = Path(__file__).parent
REPORTS_DIR = BASE_DIR / "reports"
CACHE_DIR = BASE_DIR / ".cache"
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"
CONFIG_PATH = BASE_DIR / "config.yaml"

REPORTS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(override=False)

# Structured logging setup
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("it-trends-mcp-server")
START_TIME = time.time()


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        logger.warning("Config file not found at %s, using defaults", path)
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


CONFIG = load_config(CONFIG_PATH)

# Initialize helpers
cache_cfg = CONFIG.get("cache", {"enabled": True, "ttl": 3600, "storage": "file", "redis_url": os.getenv("REDIS_URL")})
cache = CacheManager(cache_cfg, default_dir=str(CACHE_DIR))

data_processor = DataProcessor(CONFIG.get("analysis", {}))

# Init clients and analyzers lazily when used

server_meta = CONFIG.get("server", {"name": "IT Trends MCP Server", "version": "1.0.0"})

# Optionally start lightweight HTTP health server
try:
    srv_cfg = CONFIG.get("server", {})
    http_host = srv_cfg.get("host", "localhost")
    http_port = int(srv_cfg.get("port", 0) or 0)
except Exception:
    http_host, http_port = "localhost", 0

# Log startup to stderr (safe for MCP stdio) so users see confirmation on launch
try:
    pid = os.getpid()
except Exception:
    pid = None
logger.info(
    "MCP server successfully started | name=%s version=%s transport=stdio pid=%s",
    server_meta.get("name"),
    server_meta.get("version"),
    pid
)

server = FastMCP(server_meta.get("name", "IT Trends MCP Server"), host=http_host, port=http_port, streamable_http_path="/")


# -------------------------
# Prompts
# -------------------------
@server.prompt("analysis_prompt")
def analysis_prompt() -> str:
    return (
        "You are an expert analyst specializing in software engineering and tech market trends. "
        "Analyze the provided multi-source signals (Reddit mentions + sentiment, pricing and demand from freelance markets, "
        "and search popularity), highlight the top technologies, summarize drivers, and point to credible signals. "
        "Keep it concise and actionable."
    )


@server.prompt("forecast_prompt")
def forecast_prompt() -> str:
    return (
        "You are a forecasting assistant. Based on past trend trajectories and current momentum, estimate the short-term (1-3 months) "
        "and medium-term (6-12 months) outlook for each technology. State assumptions and confidence levels." 
    )


# -------------------------
# Resources
# -------------------------
@server.resource("cache://trends/{date}")
def read_cached_trends(date: str) -> bytes:
    """Expose cached daily trends as an MCP resource.

    Example URI: cache://trends/2025-10-21
    """
    logger.info("resource access: cache://trends/%s", date)
    key = f"trends:{date}"
    data = cache.get(key)
    if data is None:
        return json.dumps({"error": "not_found", "key": key}).encode("utf-8")
    return json.dumps(data).encode("utf-8")


@server.resource("history://technology/{name}")
def read_technology_history(name: str) -> bytes:
    """Expose historical data for a technology from local DB/file as MCP resource.
    For now, returns a stub that looks into cache first and then the data directory.
    """
    logger.info("resource access: history://technology/%s", name)
    # First try cache
    cached = cache.get(f"history:{name}")
    if cached is not None:
        return json.dumps(cached).encode("utf-8")

    # Then try file fallback
    file_path = DATA_DIR / f"history_{name}.json"
    if file_path.exists():
        try:
            return file_path.read_bytes()
        except Exception as e:
            logger.error("Failed reading history file %s: %s", file_path, e)
    return json.dumps({"technology": name, "history": [], "note": "no data"}).encode("utf-8")


# -------------------------
# Tools
# -------------------------
@server.tool()
async def analyze_reddit(subreddits: List[str], lookback_days: int, keywords: List[str], ctx: Context = None) -> Dict[str, Any]:
    """Analyze Reddit for technology mentions and sentiment.

    Args:
      subreddits: list of subreddit names without the r/ prefix
      lookback_days: how many days back to fetch posts
      keywords: list of technology keywords to track (case-insensitive)

    Returns:
      JSON with top technologies, mentions, and sentiment summary
    """
    start_ts = time.perf_counter()
    client_id = getattr(ctx, "client_id", None) if ctx else None
    request_id = getattr(ctx, "request_id", None) if ctx else None
    logger.info(
        "incoming request: analyze_reddit | client_id=%s request_id=%s | subreddits=%s lookback=%s days keywords=%s",
        client_id,
        request_id,
        subreddits,
        lookback_days,
        keywords,
    )

    # validate
    if not isinstance(subreddits, list) or not all(isinstance(s, str) for s in subreddits):
        raise ValueError("subreddits must be a list[str]")
    if not isinstance(lookback_days, int) or lookback_days <= 0:
        raise ValueError("lookback_days must be a positive int")
    if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
        raise ValueError("keywords must be a list[str]")

    reddit_cfg = CONFIG.get("data_sources", {}).get("reddit", {})
    # Build analyzer lazily
    reddit_client = await asyncio.to_thread(get_reddit_client, reddit_cfg)
    analyzer = RedditAnalyzer(reddit_client=reddit_client, logger=logger, cache=cache)

    # caching key
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cache_key = f"reddit:{today}:{','.join(sorted(subreddits))}:{lookback_days}:{','.join(sorted([k.lower() for k in keywords]))}"

    async def fetch() -> Dict[str, Any]:
        posts = await analyzer.fetch_posts(subreddits=subreddits, lookback_days=lookback_days)
        technologies = await analyzer.extract_technologies(posts=posts, keywords=keywords)
        sentiment = await analyzer.calculate_sentiment(posts=posts, keywords=keywords)
        ranked = await analyzer.rank_by_popularity(technologies)

        result = {
            "date": today,
            "subreddits": subreddits,
            "lookback_days": lookback_days,
            "top_technologies": ranked,
            "sentiment": sentiment,
            "stats": {
                "posts_analyzed": len(posts),
                "unique_tech_count": len(ranked),
            },
        }
        return result

    result = await cache.get_or_fetch_async(cache_key, fetch, ttl=CONFIG.get("cache", {}).get("ttl", 3600))
    elapsed = time.perf_counter() - start_ts
    logger.info(
        "analyze_reddit finished | client_id=%s request_id=%s | posts=%s unique_tech=%s | duration=%.3fs",
        client_id,
        request_id,
        result.get("stats", {}).get("posts_analyzed"),
        result.get("stats", {}).get("unique_tech_count"),
        elapsed,
    )
    return result


@server.tool()
async def generate_report(data: Dict[str, Any], format: str = "html", include_charts: bool = True, ctx: Context = None) -> Dict[str, Any]:
    """Generate a report from analysis results.

    Args:
      data: dict of aggregated analysis data
      format: one of pdf, excel, html
      include_charts: whether to include charts

    Returns:
      JSON with path to generated report file
    """
    start_ts = time.perf_counter()
    client_id = getattr(ctx, "client_id", None) if ctx else None
    request_id = getattr(ctx, "request_id", None) if ctx else None
    logger.info(
        "incoming request: generate_report | client_id=%s request_id=%s | format=%s include_charts=%s",
        client_id,
        request_id,
        format,
        include_charts,
    )

    if not isinstance(data, dict):
        raise ValueError("data must be a dict")
    fmt = (format or "html").strip().lower()
    if fmt not in {"pdf", "excel", "html"}:
        raise ValueError("format must be one of: pdf, excel, html")

    generator = ReportGenerator(output_dir=str(REPORTS_DIR), templates_dir=str(TEMPLATES_DIR), logger=logger)
    charts = None
    if include_charts:
        charts = await generator.create_visualizations(data)

    if fmt == "html":
        out_path = await generator.generate_html(data, charts)
    elif fmt == "pdf":
        out_path = await generator.generate_pdf(data, charts)
    else:
        out_path = await generator.generate_excel(data)

    elapsed = time.perf_counter() - start_ts
    logger.info(
        "generate_report finished | client_id=%s request_id=%s | path=%s | duration=%.3fs",
        client_id,
        request_id,
        out_path,
        elapsed,
    )
    return {"path": out_path}


# ---- Tools implemented for freelance and trends ----
@server.tool()
async def analyze_freelance(platforms: List[str], categories: Optional[List[str]] = None, ctx: Context = None) -> Dict[str, Any]:
    """Analyze freelance market demand from public sources (Upwork/Freelancer).

    Args:
      platforms: list including any of: upwork, freelancer, all
      categories: optional keywords to filter results (best-effort)
    """
    start_ts = time.perf_counter()
    client_id = getattr(ctx, "client_id", None) if ctx else None
    request_id = getattr(ctx, "request_id", None) if ctx else None
    logger.info(
        "incoming request: analyze_freelance | client_id=%s request_id=%s | platforms=%s categories=%s",
        client_id,
        request_id,
        platforms,
        categories,
    )

    if not isinstance(platforms, list) or not all(isinstance(p, str) for p in platforms):
        raise ValueError("platforms must be a list[str]")
    categories_lc: Optional[List[str]] = None
    if categories is not None:
        if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
            raise ValueError("categories must be a list[str] if provided")
        categories_lc = [c.strip().lower() for c in categories if isinstance(c, str) and c.strip()]

    normalized = {p.strip().lower() for p in platforms if p and isinstance(p, str)}
    if not normalized or "all" in normalized:
        normalized = {"upwork", "freelancer"}
    valid = {"upwork", "freelancer"}
    chosen = sorted(list(normalized & valid))
    if not chosen:
        raise ValueError("platforms must include at least one of: upwork, freelancer, all")

    # caching key (per-day)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cache_key = f"freelance:{today}:{','.join(chosen)}:{','.join(categories_lc or [])}"

    async def fetch() -> Dict[str, Any]:
        analyzer = FreelanceAnalyzer(logger=logger)
        tasks = []
        if "upwork" in chosen:
            tasks.append(analyzer.scrape_upwork())
        if "freelancer" in chosen:
            tasks.append(analyzer.scrape_freelancer())
        results = await asyncio.gather(*tasks) if tasks else []
        jobs = []
        for r in results:
            jobs.extend(r or [])

        # optional filtering by categories (keyword contains in title/skills)
        if categories_lc:
            def _match(job: Dict[str, Any]) -> bool:
                text = (str(job.get("title") or "") + " " + str(job.get("description") or "")).lower()
                skills = [str(s).lower() for s in (job.get("skills") or [])]
                return any((kw in text) or any(kw in s for s in skills) for kw in categories_lc or [])
            jobs = [j for j in jobs if _match(j)]

        skills = await analyzer.parse_job_requirements(jobs)
        avg_rate = await analyzer.calculate_avg_rates(jobs)
        ranked = sorted(
            ({"technology": k, "mentions": float(v)} for k, v in skills.items()),
            key=lambda x: x["mentions"],
            reverse=True,
        )
        status = "ok" if ranked else "not_available"
        if ranked and avg_rate == 0.0:
            status = "partial"
        return {
            "date": today,
            "source": "freelance_markets",
            "platforms": chosen,
            "top_technologies": ranked,
            "avg_hourly_rate": float(avg_rate),
            "stats": {"jobs_count": len(jobs), "unique_skill_count": len(ranked)},
            "status": status,
        }

    result = await cache.get_or_fetch_async(cache_key, fetch, ttl=CONFIG.get("cache", {}).get("ttl", 3600))
    elapsed = time.perf_counter() - start_ts
    logger.info(
        "analyze_freelance finished | client_id=%s request_id=%s | platforms=%s jobs=%s skills=%s | duration=%.3fs",
        client_id,
        request_id,
        ",".join(chosen),
        result.get("stats", {}).get("jobs_count"),
        result.get("stats", {}).get("unique_skill_count"),
        elapsed,
    )
    return result


@server.tool()
async def search_trends(keywords: List[str], timeframe: str = "now 7-d", region: str = "US", ctx: Context = None) -> Dict[str, Any]:
    """Search technology trends from multiple public sources (Google Trends, GitHub, StackOverflow).

    Args:
      keywords: list of keywords for Google Trends (optional; can be empty)
      timeframe: timeframe hint (currently informational)
      region: region hint (currently informational)
    """
    start_ts = time.perf_counter()
    client_id = getattr(ctx, "client_id", None) if ctx else None
    request_id = getattr(ctx, "request_id", None) if ctx else None
    logger.info(
        "incoming request: search_trends | client_id=%s request_id=%s | keywords=%s timeframe=%s region=%s",
        client_id,
        request_id,
        keywords,
        timeframe,
        region,
    )

    if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
        raise ValueError("keywords must be a list[str]")
    tf = str(timeframe or "now 7-d")
    reg = str(region or "US")

    # caching key (per-day)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    kw_norm = [k.strip().lower() for k in keywords if isinstance(k, str) and k.strip()]
    cache_key = f"trends:{today}:{','.join(sorted(kw_norm))}:{tf}:{reg}"

    async def fetch() -> Dict[str, Any]:
        searcher = TrendsSearcher(logger=logger)
        google, github, stackoverflow = await asyncio.gather(
            searcher.search_google_trends(kw_norm),
            searcher.search_github_trends(),
            searcher.search_stackoverflow(),
        )
        combined = await searcher.aggregate_results([google, github, stackoverflow])
        return {
            "date": today,
            "inputs": {"keywords": kw_norm, "timeframe": tf, "region": reg},
            "sources": {
                "google_trends": google,
                "github_trending": github,
                "stackoverflow": stackoverflow,
            },
            "top_technologies": combined.get("top_technologies", []),
        }

    result = await cache.get_or_fetch_async(cache_key, fetch, ttl=CONFIG.get("cache", {}).get("ttl", 3600))
    elapsed = time.perf_counter() - start_ts
    logger.info(
        "search_trends finished | client_id=%s request_id=%s | keywords=%s unique_tech=%s | duration=%.3fs",
        client_id,
        request_id,
        ",".join(kw_norm),
        len(result.get("top_technologies", []) or []),
        elapsed,
    )
    # also store per-day cache resource
    cache.set(f"trends:{today}", result, ttl=CONFIG.get("cache", {}).get("ttl", 3600))
    return result


@server.tool()
async def get_historical_comparison(technology: str, days_back: int = 30) -> Dict[str, Any]:
    logger.warning("get_historical_comparison called but not implemented yet")
    return {"status": "not_implemented", "message": "Historical comparison will be added in a future version."}


if __name__ == "__main__":

    # Run MCP server (stdio by default)
    server.run(transport="streamable-http")
