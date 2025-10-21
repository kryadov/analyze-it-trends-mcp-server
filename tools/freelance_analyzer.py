import asyncio
import re
from typing import Any, Dict, List, Optional, Set


class FreelanceAnalyzer:
    """
    Analyze freelance market demand using lightweight, network-tolerant scrapers
    and simple NLP heuristics.

    Goals:
    - Provide best-effort signals from public, non-auth pages (no credentials).
    - Run blocking I/O in threads; never crash on missing deps or network.
    - Normalize output to align with other analyzers: top_technologies + stats.
    """

    def __init__(self, logger) -> None:
        self.logger = logger

    # -----------------
    # Helper utilities
    # -----------------
    async def _to_thread(self, func, *args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    def _normalize_skill(self, s: Optional[str]) -> str:
        return (s or "").strip().lower()

    def _extract_rate_from_text(self, text: Optional[str]) -> Optional[float]:
        """Extract an hourly rate like $25/hr, $40 per hour, 30 USD/hour.
        Returns first matched numeric value as float or None.
        """
        if not text:
            return None
        t = str(text)
        # Common patterns
        patterns = [
            r"\$\s*(\d+(?:[.,]\d{1,2})?)\s*/\s*hr",
            r"\$\s*(\d+(?:[.,]\d{1,2})?)\s*(?:per|/)?\s*hour",
            r"(\d+(?:[.,]\d{1,2})?)\s*(?:usd|eur|gbp)?\s*/\s*hour",
        ]
        for p in patterns:
            m = re.search(p, t, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1).replace(",", "."))
                except Exception:
                    continue
        return None

    def _extract_skills_from_text(self, text: Optional[str]) -> List[str]:
        """Very simple keyword-based skill extraction from text.
        Uses a small built-in vocabulary to avoid external deps.
        """
        if not text:
            return []
        vocab: Set[str] = {
            # languages
            "python","java","javascript","typescript","c#","c++","go","golang","rust","php","ruby","swift","kotlin",
            # frameworks
            ".net","asp.net","spring","django","flask","rails","laravel","react","vue","angular","next.js","nuxt","svelte",
            # data / ml
            "sql","postgres","mysql","mongodb","redis","hadoop","spark","pandas","numpy","tensorflow","pytorch","scikit-learn",
            # devops / cloud
            "aws","azure","gcp","docker","kubernetes","terraform","ansible","jenkins","ci/cd","gitlab","github actions",
            # web / cms / commerce
            "wordpress","shopify","woocommerce","magento","drupal",
            # blockchain
            "solidity","web3",
        }
        t = text.lower()
        found = {kw for kw in vocab if kw and kw in t}
        return sorted(found)

    # -----------------------------
    # Scrapers (best-effort, safe)
    # -----------------------------
    async def scrape_upwork(self) -> List[Dict[str, Any]]:  # pragma: no cover - network dependent
        """Scrape a public Upwork resource page listing in-demand skills.
        No authentication; returns job-like items with skills only.
        """
        try:
            import requests  # type: ignore
            from bs4 import BeautifulSoup  # type: ignore
        except Exception as e:  # pragma: no cover - environment dependent
            self.logger.warning("Upwork scraper unavailable (deps missing): %s", e)
            return []

        def _fetch() -> List[Dict[str, Any]]:
            urls = [
                "https://www.upwork.com/resources/most-in-demand-tech-skills",
                "https://www.upwork.com/resources/most-in-demand-skills",
            ]
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            items: List[Dict[str, Any]] = []
            for url in urls:
                try:
                    resp = requests.get(url, headers=headers, timeout=15)
                    if resp.status_code != 200 or not resp.text:
                        continue
                    soup = BeautifulSoup(resp.text, "html.parser")
                    # Collect list items that look like skills
                    candidates = []
                    for li in soup.select("li"):
                        txt = (li.get_text(" ") or "").strip()
                        if 1 <= len(txt.split()) <= 4 and 2 <= len(txt) <= 40:  # short skill-like tokens
                            candidates.append(txt)
                    # Fallback: headings/spans
                    for el in soup.select("h2, h3, span, a"):
                        txt = (el.get_text(" ") or "").strip()
                        if 1 <= len(txt.split()) <= 3 and 2 <= len(txt) <= 30:
                            candidates.append(txt)
                    # Normalize and filter duplicates
                    seen: Set[str] = set()
                    for c in candidates:
                        skill = self._normalize_skill(c)
                        if not skill or len(skill) > 30:
                            continue
                        if any(ch.isdigit() for ch in skill):
                            continue
                        if skill in seen:
                            continue
                        seen.add(skill)
                        items.append({
                            "title": f"Upwork demand skill: {c}",
                            "skills": [skill],
                            "rate": None,
                            "source": "upwork",
                        })
                    if items:
                        break  # stop after first successful page
                except Exception as e:  # pragma: no cover - network dependent
                    self.logger.warning("Upwork scrape failed for %s: %s", url, e)
                    continue
            return items

        return await self._to_thread(_fetch)

    async def scrape_freelancer(self) -> List[Dict[str, Any]]:  # pragma: no cover - network dependent
        """Scrape Freelancer public pages to extract popular skills/categories.
        Returns job-like items with skills only; no auth.
        """
        try:
            import requests  # type: ignore
            from bs4 import BeautifulSoup  # type: ignore
        except Exception as e:  # pragma: no cover - environment dependent
            self.logger.warning("Freelancer scraper unavailable (deps missing): %s", e)
            return []

        def _fetch() -> List[Dict[str, Any]]:
            urls = [
                "https://www.freelancer.com/jobs/",   # categories and popular skills/keywords
                "https://www.freelancer.com/job/",    # alt path (redirects)
            ]
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            items: List[Dict[str, Any]] = []
            for url in urls:
                try:
                    resp = requests.get(url, headers=headers, timeout=15)
                    if resp.status_code != 200 or not resp.text:
                        continue
                    soup = BeautifulSoup(resp.text, "html.parser")
                    candidates = []
                    # Common skill/tag containers
                    for a in soup.select("a, span"):
                        txt = (a.get_text(" ") or "").strip()
                        if 1 <= len(txt.split()) <= 3 and 2 <= len(txt) <= 30:
                            candidates.append(txt)
                    seen: Set[str] = set()
                    for c in candidates:
                        skill = self._normalize_skill(c)
                        if not skill or len(skill) > 30:
                            continue
                        if any(ch.isdigit() for ch in skill):
                            continue
                        if skill in seen:
                            continue
                        seen.add(skill)
                        items.append({
                            "title": f"Freelancer category/skill: {c}",
                            "skills": [skill],
                            "rate": None,
                            "source": "freelancer",
                        })
                    if items:
                        break
                except Exception as e:  # pragma: no cover
                    self.logger.warning("Freelancer scrape failed for %s: %s", url, e)
                    continue
            return items

        return await self._to_thread(_fetch)

    # ------------------------------
    # Basic processing primitives
    # ------------------------------
    async def parse_job_requirements(self, jobs: List[Dict[str, Any]]) -> Dict[str, int]:
        skills: Dict[str, int] = {}
        for job in jobs:
            # explicit skills list
            for skill in job.get("skills", []) or []:
                s = self._normalize_skill(skill)
                if not s:
                    continue
                skills[s] = skills.get(s, 0) + 1
            # try to extract from text fields
            text = " ".join(str(job.get(k, "")) for k in ("title", "description", "tags"))
            for s in self._extract_skills_from_text(text):
                skills[s] = skills.get(s, 0) + 1
        return skills

    async def calculate_avg_rates(self, jobs: List[Dict[str, Any]]) -> float:
        """Calculate average hourly rate from structured or inferred fields.
        Accepts numeric `rate` or parses from `rate_text`/text fields.
        """
        vals: List[float] = []
        for j in jobs:
            rate = j.get("rate")
            if isinstance(rate, (int, float)):
                vals.append(float(rate))
                continue
            # parse from text fields
            for key in ("rate_text", "title", "description"):
                val = self._extract_rate_from_text(j.get(key))
                if val is not None:
                    vals.append(val)
                    break
        if not vals:
            return 0.0
        return sum(vals) / len(vals)

    # ------------------------------
    # High-level aggregation output
    # ------------------------------
    async def identify_demand_trends(self) -> Dict[str, Any]:  # pragma: no cover - network dependent
        """Fetch best-effort signals from multiple freelance sources and
        aggregate into a normalized summary.
        """
        upwork_jobs, freelancer_jobs = await asyncio.gather(
            self.scrape_upwork(),
            self.scrape_freelancer(),
        )
        jobs = (upwork_jobs or []) + (freelancer_jobs or [])
        skills = await self.parse_job_requirements(jobs)
        avg_rate = await self.calculate_avg_rates(jobs)
        ranked = sorted(
            ({"technology": k, "mentions": float(v)} for k, v in skills.items()),
            key=lambda x: x["mentions"],
            reverse=True,
        )
        status = "ok" if ranked else "not_available"
        if ranked and avg_rate == 0.0:
            status = "partial"
        return {
            "source": "freelance_markets",
            "platforms": ["upwork", "freelancer"],
            "top_technologies": ranked,
            "avg_hourly_rate": float(avg_rate),
            "stats": {
                "jobs_count": len(jobs),
                "unique_skill_count": len(ranked),
            },
            "status": status,
        }
