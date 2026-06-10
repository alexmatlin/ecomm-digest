"""
Score articles by recency × vertical relevance signal.

v1 formula (T2/T3 sources only, no T1 majors yet):
    score = w_vertical * vertical_salience * recency_decay

vertical_salience proxies (in absence of T1 majors as a salience oracle):
    - core source (+0.5 baseline) vs specialist (+0.3)
    - keyword density: how many bucket-specific terms appeared in the article
    - title length sanity (very short titles can be navigational stubs)

recency_decay is exponential with RECENCY_HALFLIFE_HOURS.
"""
from __future__ import annotations

import logging
import math
import re

from .config import W_VERTICAL, RECENCY_HALFLIFE_HOURS
from .ingest import Article
from .router import _COMPILED

log = logging.getLogger(__name__)


_TIER_BASE = {
    "major": 0.7,        # T1 broad business outlets (Straits Times) — salience oracle
    "core": 0.5,         # T2 trade spine (Supply Chain Dive, Banking Dive, etc.)
    "specialist": 0.3,   # T3 specialists (deBanked, Latent Space, etc.)
}


def _vertical_salience(article: Article) -> float:
    """0..1-ish score for how relevant/strong this article is for its bucket."""
    base = _TIER_BASE.get(article.source_tier, 0.3)

    # Keyword-hit density inside the assigned bucket
    bucket_patterns = _COMPILED.get((article.vertical, article.subtopic), [])
    if bucket_patterns:
        text = f"{article.title}\n{article.body}"
        hits = sum(1 for p in bucket_patterns if p.search(text))
        # Cap contribution at 0.4
        base += min(0.4, hits * 0.08)

    # Penalize very short titles (e.g. navigation stubs slipped through)
    word_count = len(re.findall(r"\w+", article.title))
    if word_count < 4:
        base *= 0.6

    # Modest bump for articles where the title strongly matches a "today's
    # big move" pattern (numbers, named entities, action verbs).
    if re.search(r"\$\d|\b(?:raises?|launches?|acquires?|files?|unveils?|partners?)\b",
                 article.title, re.IGNORECASE):
        base += 0.05

    return min(base, 1.0)


def _recency_decay(article: Article) -> float:
    """Exponential decay: 1.0 at t=0, 0.5 at half-life."""
    h = article.age_hours()
    return math.pow(0.5, h / RECENCY_HALFLIFE_HOURS)


def score(article: Article) -> float:
    if not article.vertical or not article.subtopic:
        return 0.0
    s = W_VERTICAL * _vertical_salience(article) * _recency_decay(article)
    return round(s, 4)


def score_all(articles: list[Article]) -> list[Article]:
    for a in articles:
        a.score = score(a)
    articles.sort(key=lambda a: a.score, reverse=True)
    if articles:
        log.info(
            "score: n=%d top=%.3f median=%.3f bottom=%.3f",
            len(articles),
            articles[0].score,
            articles[len(articles) // 2].score,
            articles[-1].score,
        )
    return articles
