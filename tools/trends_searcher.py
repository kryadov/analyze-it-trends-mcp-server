import asyncio
from typing import Any, Dict, List, Optional


class TrendsSearcher:
    """
    Search trends across multiple sources with graceful fallbacks.
    Sources:
    - Google Trends (pytrends)
    - GitHub Trending (scrape public page)
    - Stack Overflow tags (StackExchange API)

    All methods are async-friendly and run blocking I/O in a thread.
    Return format is normalized to: { "source": str, "top_technologies": [{"technology": str, "mentions": float}], ... }
    """

    def __init__(self, logger) -> None:
        self.logger = logger

    # ---------------
    # Helper methods
    # ---------------
    async def _to_thread(self, func, *args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    def _normalize_tech(self, name: Optional[str]) -> str:
        return (name or "").strip().lower()

    # ------------------------------
    # Google Trends via pytrends
    # ------------------------------
    async def search_google_trends(self, keywords: List[str]) -> Dict[str, Any]:  # pragma: no cover - network dependent
        """Fetch interest over time for keywords from Google Trends.

        Notes:
        - Uses default timeframe "now 7-d" and global region.
        - Sums interest over the timeframe as "mentions" proxy.
        - Returns empty results if pytrends is not available or call fails.
        """
        # sanitize
        kw_list = [k.strip() for k in (keywords or []) if isinstance(k, str) and k.strip()]
        if not kw_list:
            return {"source": "google_trends", "top_technologies": [], "status": "ok"}

        try:
            from pytrends.request import TrendReq  # type: ignore
        except Exception as e:  # pragma: no cover - environment dependent
            self.logger.warning("pytrends not available: %s", e)
            return {"source": "google_trends", "top_technologies": [], "status": "not_available"}

        def _fetch() -> Dict[str, float]:
            mentions: Dict[str, float] = {}
            try:
                tr = TrendReq(hl="en-US", tz=0)
                # timeframe and geo kept simple to avoid config dependency
                tr.build_payload(kw_list=kw_list, timeframe="now 7-d", geo="")
                df = tr.interest_over_time()
                if df is None or getattr(df, "empty", True):
                    return {}
                # sum interest as mentions proxy
                for kw in kw_list:
                    if kw in df.columns:
                        series = df[kw].fillna(0)
                        mentions[self._normalize_tech(kw)] = float(series.sum())
            except Exception as inner:  # pragma: no cover - network dependent
                self.logger.warning("Google Trends fetch failed: %s", inner)
            return mentions

        data = await self._to_thread(_fetch)
        ranked = sorted(
            ({"technology": k, "mentions": v} for k, v in data.items()),
            key=lambda x: x["mentions"],
            reverse=True,
        )
        return {"source": "google_trends", "top_technologies": ranked, "status": "ok"}

    # ------------------------------
    # GitHub Trending (scraping)
    # ------------------------------
    async def search_github_trends(self) -> Dict[str, Any]:  # pragma: no cover - network dependent
        """Scrape GitHub Trending and aggregate by language and topic tags.

        Returns technologies as languages and repository topics, ranked by frequency.
        """
        try:
            import requests  # type: ignore
            from bs4 import BeautifulSoup  # type: ignore
        except Exception as e:  # pragma: no cover - environment dependent
            self.logger.warning("requests/bs4 not available: %s", e)
            return {"source": "github_trending", "top_technologies": [], "status": "not_available"}

        def _fetch() -> Dict[str, int]:
            url = "https://github.com/trending?since=daily"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            counts: Dict[str, int] = {}
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                # Each repo entry
                for article in soup.select("article.Box-row"):
                    # language
                    lang_el = article.select_one("span[itemprop='programmingLanguage']")
                    if lang_el and lang_el.text:
                        tech = self._normalize_tech(lang_el.text)
                        if tech:
                            counts[tech] = counts.get(tech, 0) + 1
                    # topics
                    for t in article.select("a.topic-tag"):
                        tech = self._normalize_tech(t.text)
                        if tech:
                            counts[tech] = counts.get(tech, 0) + 1
            except Exception as inner:  # pragma: no cover
                self.logger.warning("GitHub Trending fetch failed: %s", inner)
            return counts

        data = await self._to_thread(_fetch)
        ranked = sorted(
            ({"technology": k, "mentions": float(v)} for k, v in data.items()),
            key=lambda x: x["mentions"],
            reverse=True,
        )
        return {"source": "github_trending", "top_technologies": ranked, "status": "ok"}

    # ---------------------------------
    # Stack Overflow (StackExchange API)
    # ---------------------------------
    async def search_stackoverflow(self) -> Dict[str, Any]:  # pragma: no cover - network dependent
        """Fetch popular Stack Overflow tags via StackExchange API.

        Uses /tags?sort=popular as a lightweight signal. Mentions = tag usage count.
        """
        try:
            import requests  # type: ignore
        except Exception as e:  # pragma: no cover
            self.logger.warning("requests not available: %s", e)
            return {"source": "stackoverflow", "top_technologies": [], "status": "not_available"}

        def _fetch() -> Dict[str, int]:
            base = "https://api.stackexchange.com/2.3/tags"
            params = {
                "order": "desc",
                "sort": "popular",
                "site": "stackoverflow",
                "pagesize": 100,
            }
            counts: Dict[str, int] = {}
            try:
                resp = requests.get(base, params=params, timeout=20)
                resp.raise_for_status()
                payload = resp.json() or {}
                for item in payload.get("items", []):
                    tag = self._normalize_tech(item.get("name"))
                    count = int(item.get("count", 0) or 0)
                    if tag:
                        counts[tag] = counts.get(tag, 0) + count
            except Exception as inner:  # pragma: no cover
                self.logger.warning("StackOverflow tags fetch failed: %s", inner)
            return counts

        data = await self._to_thread(_fetch)
        ranked = sorted(
            ({"technology": k, "mentions": float(v)} for k, v in data.items()),
            key=lambda x: x["mentions"],
            reverse=True,
        )
        return {"source": "stackoverflow", "top_technologies": ranked, "status": "ok"}

    # - aggregate_results() - агрегация результатов из всех источников
    async def aggregate_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        agg: Dict[str, float] = {}
        for r in results:
            for item in r.get("top_technologies", []):
                tech = (item.get("technology") or "").strip().lower()
                agg[tech] = agg.get(tech, 0.0) + float(item.get("mentions", 0))
        ranked = sorted(
            ({"technology": k, "mentions": v} for k, v in agg.items()),
            key=lambda x: x["mentions"],
            reverse=True,
        )
        return {"top_technologies": ranked}
