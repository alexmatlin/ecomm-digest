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
    "major": 0.5,        # T1 broad business outlets — equal to core for briefings
    "core": 0.5,         # T2 trade spine
    "specialist": 0.3,   # T3 specialists
}

# Lead-only tier multiplier — T1 stories surface as lead candidates without
# crowding specialists out of briefing positions.
_LEAD_TIER_MULTIPLIER = {
    "major": 1.4,
    "core": 1.0,
    "specialist": 0.9,
}

# === Event-driven lead patterns (Q2: lead = biggest news event) ===

# Strong positive signals: action verbs that indicate a discrete news event.
_LEAD_ACTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bacquir(?:e|es|ed|ing)\b",
        r"\bacquisition\b",
        r"\bmerger\b",
        r"\b(?:agrees? to )?buy(?:s|out)?\b.*\b(?:stake|shares?|company|firm)\b",
        r"\braises?\s+\$",
        r"\braised\s+\$",
        r"\bsecures?\s+\$",
        r"\bfiles?\s+(?:for\s+)?(?:an?\s+)?ipo\b",
        r"\bfiles?\s+(?:draft\s+)?s-?1\b",
        r"\blaunches?\b",
        r"\bunveils?\b",
        r"\brolls?\s+out\b",
        r"\bdeploys?\b",
        r"\bpartners?\s+(?:with|to)\b",
        r"\bsigns?\s+deal\b",
        r"\bcuts?\s+(?:jobs?|workforce|staff|hundreds?|thousands?)\b",
        r"\blays?\s+off\b",
        r"\bshuts?\s+down\b",
        r"\bappoints?\b",
        r"\bsteps?\s+down\b",
        r"\bgoes?\s+(?:public|global)\b",
        r"\bbans?\b",
        r"\bsues?\b",
        r"\bcharged\s+with\b",
    ]
]

# Dollar amounts: $30M, $2.7bn, $500 million, 1.5 billion deal
_LEAD_DOLLAR_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\$\d+(?:\.\d+)?\s*[mbk]\b",
        r"\$\d+(?:\.\d+)?\s*(?:million|billion|trillion)\b",
        r"\b\d+(?:\.\d+)?\s*(?:million|billion|trillion)\b.*(?:deal|round|valuation|raise)",
    ]
]

# Negative signals — hedging language disqualifies lead status.
_LEAD_HEDGE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\b(?:considers?|considering)\b",
        r"\bexplor(?:es?|ing)\b",
        r"\b(?:could|may|might|potentially|reportedly)\b",
        r"\?",  # question marks → speculation
        r"\brumor(?:ed|s)?\b",
    ]
]

# Explainer prefixes — great briefings, but not lead material.
_LEAD_EXPLAINER_PREFIX_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^\s*why\b",
        r"^\s*how\b",
        r"^\s*what\b",
        r"^\s*inside\b",
        r"^\s*the\s+(?:messy|future|state)\s+of\b",
    ]
]


def _count_hits(patterns, text: str) -> int:
    return sum(1 for p in patterns if p.search(text))


def lead_score(article: Article) -> float:
    """
    Event-driven lead-worthiness score. Higher = more lead-worthy.

    Layered on top of regular score() — only used for picking THE LEAD,
    not for ordering briefings. Briefings still use score().

    Formula:
        lead_score = score × tier_multiplier × (1 + bonuses) × (1 − penalties)
    """
    base = score(article)
    if base <= 0:
        return 0.0

    title = article.title or ""

    # Tier multiplier (T1 majors get the lead boost)
    tier_mult = _LEAD_TIER_MULTIPLIER.get(article.source_tier, 1.0)

    # Positive signals (cap each contribution so one pattern can't dominate)
    action_hits = _count_hits(_LEAD_ACTION_PATTERNS, title)
    dollar_hits = _count_hits(_LEAD_DOLLAR_PATTERNS, title)
    bonus = min(0.4, action_hits * 0.2) + min(0.3, dollar_hits * 0.3)

    # Negative signals (cap penalty at -0.5)
    hedge_hits = _count_hits(_LEAD_HEDGE_PATTERNS, title)
    explainer_hits = _count_hits(_LEAD_EXPLAINER_PREFIX_PATTERNS, title)
    penalty = min(0.5, hedge_hits * 0.3 + explainer_hits * 0.3)

    return round(base * tier_mult * (1 + bonus) * (1 - penalty), 4)


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
