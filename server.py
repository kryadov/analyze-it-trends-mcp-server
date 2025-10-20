import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from threading import Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv
import yaml

try:
    # FastMCP is a high-level helper for building MCP servers easily
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.server import Context
except Exception:  # pragma: no cover - fallback if fastmcp path changes
    from mcp import FastMCP  # type: ignore
    try:
        from mcp.server.fastmcp.server import Context  # type: ignore
    except Exception:  # pragma: no cover - last resort
        Context = Any  # type: ignore

# Local modules
from tools.reddit_analyzer import RedditAnalyzer
from tools.report_generator import ReportGenerator
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
server = FastMCP(server_meta.get("name", "IT Trends MCP Server"))


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


# ---- Stubs for future tools (graceful degradation) ----
@server.tool()
async def analyze_freelance(platforms: List[str], categories: Optional[List[str]] = None) -> Dict[str, Any]:
    logger.warning("analyze_freelance called but not implemented yet")
    return {"status": "not_implemented", "message": "Freelance analysis will be added in a future version."}


@server.tool()
async def search_trends(keywords: List[str], timeframe: str = "now 7-d", region: str = "US") -> Dict[str, Any]:
    logger.warning("search_trends called but not implemented yet")
    return {"status": "not_implemented", "message": "Trends search will be added in a future version."}


@server.tool()
async def get_historical_comparison(technology: str, days_back: int = 30) -> Dict[str, Any]:
    logger.warning("get_historical_comparison called but not implemented yet")
    return {"status": "not_implemented", "message": "Historical comparison will be added in a future version."}


# -------------------------
# HTTP Health Endpoint (optional)
# -------------------------
class HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # type: ignore[override]
        try:
            logger.debug("health_http | " + (format % args))
        except Exception:
            pass

    def _write_json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            # Ignore broken pipe on client disconnects
            pass

    def do_GET(self) -> None:  # type: ignore[override]
        path = self.path.split("?", 1)[0]
        if path in ("/health", "/healthz", "/ready", "/readiness"):
            now = time.time()
            uptime = max(0, now - START_TIME)
            payload = {
                "status": "ok",
                "name": server_meta.get("name", "IT Trends MCP Server"),
                "version": server_meta.get("version", "1.0.0"),
                "time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "uptime_seconds": round(uptime, 3),
            }
            self._write_json(200, payload)
        else:
            self._write_json(404, {"error": "not_found"})


def start_http_health_server(host: str, port: int) -> Optional[Thread]:
    if not port or port <= 0:
        return None

    def run_server() -> None:
        try:
            httpd = ThreadingHTTPServer((host, port), HealthHandler)
            logger.info("Health HTTP server listening on http://%s:%s", host, port)
            httpd.serve_forever(poll_interval=0.5)
        except OSError as e:
            logger.error("Failed to start health HTTP server on %s:%s: %s", host, port, e)
        except Exception as e:
            logger.exception("Health HTTP server crashed: %s", e)

    t = Thread(target=run_server, name="health-http", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    # Optionally start lightweight HTTP health server
    try:
        srv_cfg = CONFIG.get("server", {})
        http_host = srv_cfg.get("host", "127.0.0.1")
        http_port = int(srv_cfg.get("port", 0) or 0)
    except Exception:
        http_host, http_port = "127.0.0.1", 0
    if http_port:
        start_http_health_server(http_host, http_port)

    # Log startup to stderr (safe for MCP stdio) so users see confirmation on launch
    try:
        pid = os.getpid()
    except Exception:
        pid = None
    logger.info(
        "MCP server successfully started | name=%s version=%s transport=stdio pid=%s health_http=%s:%s",
        server_meta.get("name"),
        server_meta.get("version"),
        pid,
        http_host,
        http_port,
    )

    # Run MCP server (stdio by default)
    server.run()
