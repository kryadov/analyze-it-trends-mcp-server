import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

try:
    import praw  # type: ignore
except Exception:  # pragma: no cover
    praw = None  # type: ignore


@dataclass
class RedditPost:
    id: str
    title: str
    selftext: str
    created_utc: float
    score: int
    subreddit: str
    url: str


class RedditAnalyzer:
    def __init__(self, reddit_client: Optional[Any], logger, cache) -> None:
        self.reddit = reddit_client
        self.logger = logger
        self.cache = cache

    async def _retry(self, func, *args, retries: int = 3, base_delay: float = 0.5, **kwargs):
        last_exc = None
        for attempt in range(retries):
            try:
                return await asyncio.to_thread(func, *args, **kwargs)
            except Exception as e:  # pragma: no cover - network dependent
                last_exc = e
                delay = base_delay * (2 ** attempt)
                self.logger.warning("Reddit API call failed: %s | retry in %.2fs", e, delay)
                await asyncio.sleep(delay)
        raise last_exc  # type: ignore

    async def fetch_posts(self, subreddits: List[str], lookback_days: int, limit_per_sub: int = 200) -> List[RedditPost]:
        """Fetch recent posts from given subreddits within the lookback window.
        Uses .new() listing due to search limitations for fresh content.
        """
        if not self.reddit:
            self.logger.warning("Reddit client is not configured. Returning empty post list.")
            return []
        threshold = datetime.utcnow() - timedelta(days=lookback_days)
        posts: List[RedditPost] = []

        async def fetch_sub(sub: str):
            try:
                subreddit = self.reddit.subreddit(sub)
                count = 0
                for submission in subreddit.new(limit=limit_per_sub):
                    created_dt = datetime.utcfromtimestamp(getattr(submission, "created_utc", time.time()))
                    if created_dt < threshold:
                        break
                    posts.append(
                        RedditPost(
                            id=str(submission.id),
                            title=submission.title or "",
                            selftext=submission.selftext or "",
                            created_utc=float(getattr(submission, "created_utc", time.time())),
                            score=int(getattr(submission, "score", 0)),
                            subreddit=sub,
                            url=f"https://reddit.com{submission.permalink}",
                        )
                    )
                    count += 1
                self.logger.info("Fetched %s posts from r/%s", count, sub)
            except Exception as e:  # pragma: no cover - external dependency
                self.logger.warning("Failed to fetch from r/%s: %s", sub, e)

        await asyncio.gather(*(fetch_sub(s) for s in subreddits))
        return posts

    async def extract_technologies(self, posts: List[RedditPost], keywords: List[str]) -> Dict[str, int]:
        if not posts:
            return {}
        counts: Dict[str, int] = {}
        normalized = [k.strip().lower() for k in keywords if k and isinstance(k, str)]
        for p in posts:
            text = f"{p.title} {p.selftext}".lower()
            for kw in normalized:
                if kw and kw in text:
                    counts[kw] = counts.get(kw, 0) + text.count(kw)
        return counts

    async def calculate_sentiment(self, posts: List[RedditPost], keywords: List[str]) -> Dict[str, Dict[str, float]]:
        """Very simple lexicon-based sentiment by keyword.
        Scores: positive_words +1, negative_words -1, normalized per mention.
        """
        if not posts:
            return {}
        positive_words = {"great", "awesome", "love", "fast", "good", "win", "best", "cool"}
        negative_words = {"bad", "hate", "slow", "bug", "issue", "problem", "worst"}
        result: Dict[str, Dict[str, float]] = {}
        normalized = [k.strip().lower() for k in keywords if k and isinstance(k, str)]

        for kw in normalized:
            total_score = 0
            mentions = 0
            for p in posts:
                text = f"{p.title} {p.selftext}".lower()
                if kw in text:
                    # naive tokenization
                    tokens = [t.strip(".,!?:;()[]{}\"'") for t in text.split()]
                    score = 0
                    for t in tokens:
                        if t in positive_words:
                            score += 1
                        elif t in negative_words:
                            score -= 1
                    total_score += score
                    mentions += 1
            if mentions > 0:
                result[kw] = {
                    "avg_sentiment": total_score / max(1, mentions),
                    "mentions": mentions,
                }
        return result

    async def rank_by_popularity(self, technologies: Dict[str, int]) -> List[Dict[str, Any]]:
        ranked = sorted(
            (
                {"technology": tech, "mentions": count}
                for tech, count in technologies.items()
            ),
            key=lambda x: x["mentions"],
            reverse=True,
        )
        # return top N if needed later, for now full list
        return ranked
