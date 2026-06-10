"""
Route each article to a (vertical, subtopic) bucket using keyword rules.

Strategy:
  - Source's declared vertical + subtopics give us strong priors.
  - We confirm or refine via keyword hits against title + body.
  - cross_cutting sources (TechCrunch, Crunchbase) MUST be routed via keywords.
  - Anything we can't confidently place goes to the fallback bucket
    (logged only, never displayed).
"""
from __future__ import annotations

import logging
import re
from collections import Counter

from .ingest import Article

log = logging.getLogger(__name__)

# === Keyword rules per (vertical, subtopic) ===
# Each entry is a list of regex word-boundary patterns. Case-insensitive.
RULES: dict[tuple[str, str], list[str]] = {
    # ----- E-COMMERCE -----
    ("ecommerce", "marketplaces"): [
        r"marketplace", r"amazon", r"shopee", r"lazada", r"mercadolibre",
        r"flipkart", r"meesho", r"temu", r"shein", r"alibaba", r"taobao",
        r"tmall", r"jd\.com", r"jumia", r"ebay", r"etsy", r"zepto",
        r"blinkit", r"instacart", r"q-?commerce", r"quick commerce",
    ],
    ("ecommerce", "dtc-brands"): [
        r"\bdtc\b", r"direct-to-consumer", r"brand substack",
        r"\bdtc brands?\b", r"shopify (?:brand|merchant|store)",
        r"warby parker", r"glossier", r"allbirds", r"away luggage",
        r"private label",
    ],
    ("ecommerce", "retail-media"): [
        r"retail media", r"sponsored products?", r"amazon ads?",
        r"walmart connect", r"target roundel", r"\brmn\b",
        r"retail network", r"shopper marketing", r"\bcpc\b", r"\bcpm\b",
    ],
    ("ecommerce", "logistics"): [
        r"logistics", r"supply chain", r"warehous(?:e|ing)",
        r"last[- ]mile", r"fulfill?ment", r"freight", r"shipping",
        r"trucking", r"3pl\b", r"\bdrayage\b", r"port (?:of|congestion)",
        r"ocean carrier", r"parcel", r"delivery (?:network|provider)",
        r"cold chain",
    ],
    ("ecommerce", "social-live"): [
        r"live(?:stream)? commerce", r"tiktok shop", r"social commerce",
        r"creator commerce", r"shoppable video", r"livestream selling",
        r"influencer (?:shop|store|commerce)",
    ],
    ("ecommerce", "platforms-tech"): [
        r"shopify", r"\bbigcommerce\b", r"woocommerce", r"magento",
        r"checkout (?:flow|button)", r"headless commerce", r"\bpwa\b",
        r"shelf label", r"electronic shelf", r"ai crawler", r"bot block",
        r"licensing deal.*content", r"ai (?:training|crawl)",
    ],
    # ----- FINTECH -----
    ("fintech", "payments"): [
        r"payments?", r"\bcard network\b", r"visa", r"mastercard",
        r"\bach\b", r"\bsepa\b", r"\bupi\b", r"\bpix\b", r"interchange",
        r"merchant (?:acquir|service)", r"payment processor",
        r"checkout", r"point of sale", r"\bpos\b", r"\bb2b payments\b",
        r"cross-?border payments?",
    ],
    ("fintech", "banking-wealth"): [
        r"\bbank\b", r"banks?\b", r"wealth management", r"private bank",
        r"deposit", r"\bfdic\b", r"\bocc\b", r"\bcfpb\b",
        r"federal reserve", r"\bthe fed\b", r"\becb\b",
        r"capital requirements?", r"basel", r"net interest margin",
        r"\bmonte (?:dei )?paschi\b", r"intesa", r"banco bpm",
    ],
    ("fintech", "lending-credit"): [
        r"lending", r"loan", r"credit card", r"merchant cash advance",
        r"\bmca\b", r"\bbnpl\b", r"buy now pay later", r"klarna",
        r"affirm", r"afterpay", r"underwriting", r"credit risk",
        r"installment", r"\bapr\b",
    ],
    ("fintech", "stablecoins-crypto"): [
        r"stablecoin", r"\busdc\b", r"\busdt\b", r"tether",
        r"crypto", r"bitcoin", r"ethereum", r"defi", r"coinbase",
        r"circle\b", r"\bweb3\b", r"\bdao\b", r"\bnft\b",
        r"on-?chain", r"blockchain payment",
    ],
    ("fintech", "embedded-finance"): [
        r"embedded finance", r"embedded (?:payments?|lending|banking)",
        r"banking[- ]as[- ]a[- ]service", r"\bbaas\b", r"banking api",
        r"stripe.*(?:capital|treasury|connect)", r"adyen",
    ],
    ("fintech", "regulation"): [
        r"regulation", r"\bregulator\b", r"\bregulators\b",
        r"\bfincen\b", r"\bcfpb\b", r"\bocc\b", r"\bsec\b",
        r"compliance", r"sanctions?", r"anti-?money", r"\baml\b",
        r"\bkyc\b", r"executive order", r"rulemaking", r"\bfca\b",
    ],
    # ----- AI -----
    ("ai", "models"): [
        r"foundation model", r"frontier model", r"large language model",
        r"\bllm\b", r"\bgpt-?\d", r"\bclaude\b", r"\bgemini\b",
        r"llama\b", r"mistral", r"\bdeepseek\b", r"qwen",
        r"pretrain", r"fine-?tune", r"scaling law", r"benchmark",
        r"\bmmlu\b", r"\bswe-?bench\b", r"multimodal", r"model release",
    ],
    ("ai", "agents"): [
        r"\bagent\b", r"\bagents\b", r"agentic", r"tool use",
        r"computer use", r"browser agent", r"coding agent",
        r"autonomous (?:agent|system)", r"agent framework",
    ],
    ("ai", "infrastructure"): [
        r"\bgpu\b", r"\btpu\b", r"data ?cent(?:er|re)", r"hyperscaler",
        r"nvidia", r"\bh100\b", r"\bh200\b", r"\bb100\b",
        r"chip (?:capacity|shortage)", r"semiconductor",
        r"inference (?:cost|stack)", r"training (?:run|cluster)",
        r"capex", r"compute (?:capacity|spend)", r"vector (?:db|database)",
    ],
    ("ai", "enterprise"): [
        r"enterprise (?:ai|deployment|adoption)", r"\bcio\b", r"\bcto\b",
        r"\bcaio\b", r"chief (?:ai|technology|information)",
        r"in production", r"ai rollout", r"ai pilot", r"ai transformation",
        r"fortune 500.*ai", r"enterprise software",
    ],
    ("ai", "regulation"): [
        r"ai (?:policy|regulation|safety|oversight|governance|act)",
        r"eu ai act", r"executive order.*ai", r"ai bill",
        r"ai (?:risk|red[- ]team)", r"existential risk",
    ],
    ("ai", "startups-funding"): [
        r"raises? \$\d", r"raised \$\d", r"series [a-z]\b",
        r"funding round", r"seed round", r"valuation",
        r"venture (?:round|capital)", r"\bipo\b", r"draft s-?1",
        r"\bs-?1\b", r"acquir(?:e|es|ed)\s", r"acquisition (?:of|by)",
        r"\bm&a\b", r"megaround",
    ],
}

# Pre-compile patterns
_COMPILED: dict[tuple[str, str], list[re.Pattern]] = {
    key: [re.compile(rf"\b{p}\b" if not p.startswith("\\b") and not p.startswith("(?:") else p, re.IGNORECASE)
          for p in pats]
    for key, pats in RULES.items()
}


def _score_buckets(text: str) -> Counter:
    """Return a counter of (vertical, subtopic) -> keyword hit count."""
    scores: Counter = Counter()
    if not text:
        return scores
    for bucket, patterns in _COMPILED.items():
        hits = sum(1 for p in patterns if p.search(text))
        if hits:
            scores[bucket] = hits
    return scores


# Threshold: cross-vertical score must be at least this many times the
# source-vertical score for us to override the source's declared vertical.
# Higher = stickier source vertical. Set to 2.0 (need 2x evidence).
_CROSS_VERTICAL_OVERRIDE_RATIO = 2.0


def route(article: Article) -> Article:
    """
    Mutates article.vertical and article.subtopic, or leaves them None
    (which means: fallback bucket — log only, never displayed).

    Rules:
      1. For cross_cutting sources (TechCrunch, Crunchbase, T1 majors),
         pick the bucket with the most keyword hits — no vertical bias.
      2. For sources with a declared vertical, restrict to that vertical's
         buckets UNLESS another vertical has 2x+ stronger keyword evidence.
         This stops single-mention misfires like "Bank of America" pulling
         a Modern Retail article into Fintech.
      3. Boost source-declared subtopics within the chosen vertical.
    """
    text = f"{article.title}\n{article.body}"
    scores = _score_buckets(text)

    if article.source_vertical and article.source_vertical != "cross_cutting":
        own = {k: v for k, v in scores.items() if k[0] == article.source_vertical}
        other = {k: v for k, v in scores.items() if k[0] != article.source_vertical}
        own_max = max(own.values(), default=0)
        other_max = max(other.values(), default=0)

        # Stay in source vertical unless cross-vertical evidence is overwhelming.
        if own_max == 0 and other_max == 0:
            # No keyword hits anywhere — fall through to last-resort logic below.
            scores = Counter()
        elif other_max < own_max * _CROSS_VERTICAL_OVERRIDE_RATIO:
            scores = Counter(own)
        # else: other vertical wins by a wide margin — keep full scores (don't filter)

        # Boost source-declared subtopics within the kept buckets.
        for st in article.source_subtopics:
            key = (article.source_vertical, st)
            if key in scores:
                scores[key] += 2

    if not scores:
        # Last resort: if source has a single declared (vertical, subtopic),
        # accept it without keyword evidence (only for non-cross-cutting).
        if (
            article.source_vertical
            and article.source_vertical != "cross_cutting"
            and len(article.source_subtopics) == 1
        ):
            article.vertical = article.source_vertical
            article.subtopic = article.source_subtopics[0]
            return article
        return article  # fallback

    (vertical, subtopic), _ = scores.most_common(1)[0]
    article.vertical = vertical
    article.subtopic = subtopic
    return article


def route_all(articles: list[Article]) -> tuple[list[Article], list[Article]]:
    """Returns (routed, fallback). Fallback list is for logging only."""
    routed: list[Article] = []
    fallback: list[Article] = []
    bucket_counts: Counter = Counter()
    for a in articles:
        route(a)
        if a.vertical and a.subtopic:
            routed.append(a)
            bucket_counts[f"{a.vertical}/{a.subtopic}"] += 1
        else:
            fallback.append(a)

    log.info(
        "router: in=%d routed=%d fallback=%d",
        len(articles), len(routed), len(fallback),
    )
    for bucket, n in bucket_counts.most_common():
        log.info("  bucket %s: %d", bucket, n)
    if fallback:
        log.info("fallback titles (log-only, not displayed):")
        for a in fallback[:10]:
            log.info("  - [%s] %s", a.source_id, a.title[:90])
        if len(fallback) > 10:
            log.info("  ... and %d more", len(fallback) - 10)

    return routed, fallback
