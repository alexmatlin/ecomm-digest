"""In-run deduplication: URL canonicalization + fuzzy title clustering."""
from __future__ import annotations

import logging
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from rapidfuzz import fuzz

from .config import TITLE_FUZZY_THRESHOLD
from .ingest import Article

log = logging.getLogger(__name__)

# UTM and other tracking params that don't change the destination story
_TRACKING_PARAM_PREFIXES = (
    "utm_",
    "mc_",
    "fbclid",
    "gclid",
    "yclid",
    "ref",
    "ref_src",
    "ref_url",
    "trk",
    "source",
)


def _strip_tracking_params(query: str) -> str:
    kept = [
        (k, v)
        for (k, v) in parse_qsl(query, keep_blank_values=False)
        if not any(k.lower().startswith(p) for p in _TRACKING_PARAM_PREFIXES)
    ]
    return urlencode(kept)


def display_url(url: str) -> str:
    """User-visible URL: strip tracking params + fragment. Keep host/scheme intact."""
    try:
        u = urlparse(url.strip())
    except ValueError:
        return url
    query = _strip_tracking_params(u.query)
    return urlunparse((u.scheme, u.netloc, u.path, u.params, query, ""))


def canonical_url(url: str) -> str:
    """Dedup key: strip tracking params + www + trailing slash + lowercase host."""
    try:
        u = urlparse(url.strip())
    except ValueError:
        return url

    scheme = (u.scheme or "https").lower()
    host = (u.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]

    query = _strip_tracking_params(u.query)

    path = u.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return urlunparse((scheme, host, path, "", query, ""))


def _norm_title(t: str) -> str:
    """Lowercase + collapse whitespace for fuzzy matching."""
    return " ".join(t.lower().split())


def _merge_clusters(a: Article, b: Article) -> list[str]:
    """Return the deduped union of two articles' source clusters, preserving order."""
    seen = set()
    out: list[str] = []
    for src in a.cluster_sources + b.cluster_sources:
        if src not in seen:
            seen.add(src)
            out.append(src)
    return out


def dedupe(articles: list[Article]) -> list[Article]:
    """
    Two-pass dedup that ALSO tracks cross-source clustering:
      1. Exact match on canonical URL.
      2. Fuzzy title match (rapidfuzz token_set_ratio >= threshold).

    When duplicates are found:
      - Keep the "best" article (longest body; tie-break: core tier wins, then newer).
      - Merge `cluster_sources` from both onto the surviving article so we
        retain the salience signal of "this story was covered by N sources."
    """
    if not articles:
        return []

    # Pass 1: URL dedup. Group by canonical URL, keep the best per group,
    # but union the cluster_sources of all merged duplicates.
    by_url: dict[str, Article] = {}
    for a in articles:
        cu = canonical_url(a.url)
        existing = by_url.get(cu)
        if existing is None:
            by_url[cu] = a
        else:
            merged_sources = _merge_clusters(existing, a)
            winner = a if _is_better(a, existing) else existing
            winner.cluster_sources = merged_sources
            winner.cluster_size = len(merged_sources)
            by_url[cu] = winner

    after_url = list(by_url.values())
    log.info(
        "dedup url: in=%d out=%d removed=%d",
        len(articles),
        len(after_url),
        len(articles) - len(after_url),
    )

    # Pass 2: fuzzy title dedup. Greedy clustering — O(n²) but n is small.
    kept: list[Article] = []
    for candidate in after_url:
        cand_norm = _norm_title(candidate.title)
        merged = False
        for i, k in enumerate(kept):
            if fuzz.token_set_ratio(cand_norm, _norm_title(k.title)) >= TITLE_FUZZY_THRESHOLD:
                # Same story. Merge clusters AND keep whichever article is "better".
                merged_sources = _merge_clusters(candidate, k)
                if _is_better(candidate, k):
                    candidate.cluster_sources = merged_sources
                    candidate.cluster_size = len(merged_sources)
                    kept[i] = candidate
                else:
                    k.cluster_sources = merged_sources
                    k.cluster_size = len(merged_sources)
                merged = True
                break
        if not merged:
            kept.append(candidate)

    log.info(
        "dedup fuzzy: in=%d out=%d removed=%d threshold=%d",
        len(after_url),
        len(kept),
        len(after_url) - len(kept),
        TITLE_FUZZY_THRESHOLD,
    )

    # Diagnostic: log top clusters by size (signal of cross-source salience).
    multi_source = [a for a in kept if a.cluster_size >= 2]
    if multi_source:
        multi_source.sort(key=lambda a: -a.cluster_size)
        log.info(
            "cluster signal: %d multi-source stories (of %d total). top:",
            len(multi_source), len(kept),
        )
        for a in multi_source[:5]:
            log.info(
                "  cluster_size=%d sources=%s title=%s",
                a.cluster_size,
                ",".join(a.cluster_sources),
                a.title[:80],
            )
    else:
        log.info("cluster signal: no multi-source stories this run")

    return kept


def _is_better(a: Article, b: Article) -> bool:
    """Return True if a should beat b when they're duplicates."""
    # Prefer richer body
    if len(a.body) != len(b.body):
        return len(a.body) > len(b.body)
    # Prefer core over specialist
    tier_rank = {"core": 0, "specialist": 1}
    if tier_rank.get(a.source_tier, 9) != tier_rank.get(b.source_tier, 9):
        return tier_rank.get(a.source_tier, 9) < tier_rank.get(b.source_tier, 9)
    # Prefer newer
    if a.published_at and b.published_at:
        return a.published_at > b.published_at
    return False
