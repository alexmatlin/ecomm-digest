"""
Cross-run deduplication state.

Stored in state/seen.json. Each entry maps canonical_url -> ISO timestamp
of when it was last selected for display. Entries older than SEEN_TTL_DAYS
are pruned on load.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from .config import SEEN_FILE, SEEN_TTL_DAYS
from .dedup import canonical_url
from .ingest import Article

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_seen() -> dict[str, str]:
    """Load seen.json, prune expired entries, return canonical_url -> iso ts."""
    if not SEEN_FILE.exists():
        return {}
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("seen.json load failed: %s (starting fresh)", e)
        return {}

    cutoff = _now() - timedelta(days=SEEN_TTL_DAYS)
    pruned = {}
    for url, ts in data.items():
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                pruned[url] = ts
        except (ValueError, TypeError):
            continue

    log.info(
        "seen state: loaded=%d kept=%d expired=%d",
        len(data), len(pruned), len(data) - len(pruned),
    )
    return pruned


def filter_unseen(articles: list[Article], seen: dict[str, str]) -> list[Article]:
    """Drop articles whose canonical URL is in seen state."""
    fresh = []
    dropped = 0
    for a in articles:
        cu = canonical_url(a.url)
        if cu in seen:
            dropped += 1
            continue
        fresh.append(a)
    log.info(
        "cross-run dedup: in=%d out=%d dropped=%d",
        len(articles), len(fresh), dropped,
    )
    return fresh


def save_seen(selected: list[Article], existing: dict[str, str]) -> None:
    """Add selected articles' canonical URLs to seen with current timestamp."""
    ts = _now().isoformat()
    out = dict(existing)
    for a in selected:
        out[canonical_url(a.url)] = ts

    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
    log.info("seen state: saved entries=%d added=%d", len(out), len(out) - len(existing))
