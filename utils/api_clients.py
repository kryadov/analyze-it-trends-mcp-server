import os
from typing import Any, Dict, Optional

try:
    import praw  # type: ignore
except Exception:  # pragma: no cover
    praw = None  # type: ignore


def get_reddit_client(reddit_cfg: Dict[str, Any]) -> Optional[Any]:
    """Create a read-only PRAW client using either config or environment variables.
    Returns None if credentials are not available, enabling graceful degradation.
    """
    if praw is None:
        return None
    client_id = os.getenv("REDDIT_CLIENT_ID") or reddit_cfg.get("client_id")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET") or reddit_cfg.get("client_secret")
    user_agent = reddit_cfg.get("user_agent") or os.getenv("REDDIT_USER_AGENT") or "ITTrendsAnalyzer/1.0"
    if not client_id or not client_secret:
        return None
    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        # read-only
        reddit.read_only = True
        return reddit
    except Exception:  # pragma: no cover
        return None
