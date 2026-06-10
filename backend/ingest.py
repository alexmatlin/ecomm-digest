"""Fetch RSS/Atom feeds and normalize into Article dataclasses."""
from __future__ import annotations

import html
import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

import feedparser
from dateutil import parser as dateparser

from .config import SOURCES_FILE, MAX_AGE_HOURS

log = logging.getLogger(__name__)

# Pretend to be a normal browser. Many feeds 403 on default UAs.
USER_AGENT = (
    "Mozilla/5.0 (compatible; TheDigestBot/1.0; "
    "+https://coruscating-platypus-eccfd0.netlify.app/)"
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class Article:
    """Normalized representation of one item from an RSS/Atom feed."""

    source_id: str
    source_name: str
    source_tier: str  # "core" or "specialist"
    source_vertical: str  # "ecommerce" | "fintech" | "ai" | "cross_cutting"
    source_subtopics: list[str]
    content_type: str  # "full" or "summary"
    token_cap: int

    url: str
    title: str
    body: str  # raw description / content
    published_at: Optional[datetime]  # UTC

    # Filled in later by pipeline stages
    vertical: Optional[str] = None
    subtopic: Optional[str] = None
    score: float = 0.0
    summary: Optional[str] = None  # editorial 2-sentence summary
    is_lead: bool = False

    def age_hours(self, now: Optional[datetime] = None) -> float:
        if self.published_at is None:
            return 9999.0
        now = now or datetime.now(timezone.utc)
        return max(0.0, (now - self.published_at).total_seconds() / 3600.0)

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.published_at:
            d["published_at"] = self.published_at.isoformat()
        return d


def _strip_html(s: str) -> str:
    if not s:
        return ""
    # Strip tags
    s = _HTML_TAG_RE.sub(" ", s)
    # Decode entities (&rsquo; → ’ etc). Run twice to catch double-encoded inputs.
    s = html.unescape(s)
    s = html.unescape(s)
    # Collapse whitespace
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


def _parse_date(entry) -> Optional[datetime]:
    """Try every common date field; return UTC-aware datetime or None."""
    # feedparser pre-parses some date fields into struct_time
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        st = entry.get(key)
        if st:
            try:
                return datetime.fromtimestamp(time.mktime(st), tz=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                pass
    # Fall back to string fields
    for key in ("published", "updated", "created", "pubDate", "date"):
        s = entry.get(key)
        if s:
            try:
                dt = dateparser.parse(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except (ValueError, TypeError):
                continue
    return None


def load_sources() -> list[dict]:
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [s for s in data["sources"] if s.get("status") == "ok"]


def fetch_one(source: dict) -> list[Article]:
    """Fetch and parse one source. Returns [] on failure (logs the error)."""
    url = source["feed_url"]
    log.info("fetch start source=%s url=%s", source["id"], url)

    try:
        # feedparser supports the agent kwarg
        parsed = feedparser.parse(url, agent=USER_AGENT)
    except Exception as e:
        log.error("fetch error source=%s err=%s", source["id"], e)
        return []

    if parsed.bozo and not parsed.entries:
        log.warning(
            "fetch bozo source=%s err=%s entries=0",
            source["id"],
            getattr(parsed, "bozo_exception", "unknown"),
        )
        return []

    articles: list[Article] = []
    for entry in parsed.entries:
        title = _strip_html(entry.get("title", "")).strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue

        # Body can live in several fields depending on feed flavor
        body_raw = (
            entry.get("content", [{}])[0].get("value")
            if entry.get("content")
            else None
        )
        body_raw = body_raw or entry.get("summary") or entry.get("description") or ""
        body = _strip_html(body_raw)

        published_at = _parse_date(entry)

        # Lazy import to avoid circular dep at module load
        from .dedup import display_url
        article = Article(
            source_id=source["id"],
            source_name=source["name"],
            source_tier=source.get("tier", "specialist"),
            source_vertical=source.get("vertical", "cross_cutting"),
            source_subtopics=list(source.get("subtopics", [])),
            content_type=source.get("content_type", "summary"),
            token_cap=source.get("token_cap", 200),
            url=display_url(link),
            title=title,
            body=body,
            published_at=published_at,
        )
        articles.append(article)

    log.info(
        "fetch done source=%s entries=%d", source["id"], len(articles)
    )
    return articles


def filter_by_age(articles: list[Article], max_age_hours: float = MAX_AGE_HOURS) -> list[Article]:
    """Drop articles older than max_age_hours (and ones with no date)."""
    kept = [a for a in articles if a.age_hours() <= max_age_hours]
    log.info(
        "age filter: in=%d out=%d dropped=%d cutoff=%.0fh",
        len(articles),
        len(kept),
        len(articles) - len(kept),
        max_age_hours,
    )
    return kept


def ingest_all() -> list[Article]:
    """Fetch all configured sources, age-filter, return combined list."""
    sources = load_sources()
    log.info("ingest start sources=%d", len(sources))
    all_articles: list[Article] = []
    for src in sources:
        all_articles.extend(fetch_one(src))
    log.info("ingest raw_total=%d", len(all_articles))
    return filter_by_age(all_articles)
