"""
Render the four HTML files from Jinja templates.

Inputs are dicts keyed by vertical, each with a `lead` Article and a list of
`briefings` (Articles). Produces:
    index.html, ecommerce.html, fintech.html, ai.html

The output mirrors the existing hand-written HTML so the existing CSS/JS
(filter chips, search, dark mode, scroll reveal) continues to work unchanged.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import (
    TEMPLATES_DIR, OUTPUT_FILES, SUBTOPICS, SUBTOPIC_LABELS,
)
from .ingest import Article

log = logging.getLogger(__name__)

NETLIFY_BASE = "https://coruscating-platypus-eccfd0.netlify.app"

# Page-level copy that doesn't change run-to-run.
PAGE_META = {
    "index": {
        "page_title": "The Digest — E-commerce, Fintech, AI",
        "page_description": (
            "A daily distillation of the most consequential moves across "
            "e-commerce, fintech, and AI. For operators, builders, and investors."
        ),
        "page_url": f"{NETLIFY_BASE}/",
    },
    "ecommerce": {
        "page_title": "E-commerce — The Digest",
        "page_description": (
            "Marketplaces, DTC brands, retail media, and logistics — the "
            "operators reshaping how goods move online. Daily distillation "
            "from The Digest."
        ),
        "page_url": f"{NETLIFY_BASE}/ecommerce.html",
        "hero_eyebrow_prefix": "E-commerce",
        "hero_title": "Marketplaces, brands, and the rails behind them.",
        "hero_lede": (
            "The operators, channels, and infrastructure powering global "
            "e-commerce — distilled each morning."
        ),
    },
    "fintech": {
        "page_title": "Fintech — The Digest",
        "page_description": (
            "Payments, banking, stablecoins, and embedded finance — the rails "
            "carrying the next trillion in commerce. Daily distillation from "
            "The Digest."
        ),
        "page_url": f"{NETLIFY_BASE}/fintech.html",
        "hero_eyebrow_prefix": "Fintech",
        "hero_title": "The rails carrying the next trillion in commerce.",
        "hero_lede": (
            "Payments, banking, stablecoins, and embedded finance — the "
            "platforms and policies reshaping how money moves."
        ),
    },
    "ai": {
        "page_title": "AI — The Digest",
        "page_description": (
            "Foundation models, agents, infrastructure, and enterprise — the "
            "compute curve rewriting every business. Daily distillation from "
            "The Digest."
        ),
        "page_url": f"{NETLIFY_BASE}/ai.html",
        "hero_eyebrow_prefix": "AI",
        "hero_title": "The compute curve rewriting every business.",
        "hero_lede": (
            "Foundation models, agents, infrastructure, and the products "
            "being rebuilt around capabilities that didn't exist twelve "
            "months ago."
        ),
    },
}

# Filter chips per chapter — order and labels mirror the existing pages.
FILTER_CHIPS = {
    "ecommerce": [
        {"key": "marketplaces", "label": "Marketplaces"},
        {"key": "dtc-brands", "label": "DTC & Brands"},
        {"key": "retail-media", "label": "Retail Media"},
        {"key": "logistics", "label": "Logistics"},
        {"key": "social-live", "label": "Social & Live Commerce"},
        {"key": "platforms-tech", "label": "Platforms & Tech"},
    ],
    "fintech": [
        {"key": "payments", "label": "Payments"},
        {"key": "banking-wealth", "label": "Banking & Wealth"},
        {"key": "lending-credit", "label": "Lending & Credit"},
        {"key": "stablecoins-crypto", "label": "Stablecoins & Crypto"},
        {"key": "embedded-finance", "label": "Embedded Finance"},
        {"key": "regulation", "label": "Regulation & Policy"},
    ],
    "ai": [
        {"key": "models", "label": "Models"},
        {"key": "agents", "label": "Agents"},
        {"key": "infrastructure", "label": "Infrastructure"},
        {"key": "enterprise", "label": "Enterprise"},
        {"key": "regulation", "label": "Regulation & Policy"},
        {"key": "startups-funding", "label": "Startups & Funding"},
    ],
}

def _age_label(article: Article) -> str:
    """'Today' / '1d ago' / '2d ago' style label for cards."""
    h = article.age_hours()
    if h < 24:
        return "Today"
    d = int(h // 24)
    return f"{d}d ago"


def _read_minutes(article: Article) -> int:
    """Rough read time estimate from body word count, clamped 4-10 min."""
    words = len(article.body.split())
    return max(4, min(10, words // 200 + 1))


def _decorate(article: Article) -> dict:
    """Attach view-only fields the template expects."""
    article.age_label = _age_label(article)  # type: ignore[attr-defined]
    article.read_minutes = _read_minutes(article)  # type: ignore[attr-defined]
    return article  # type: ignore[return-value]


def _make_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["j2", "html"]),
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )


def _today_str() -> str:
    """e.g. 'Wednesday, June 10, 2026'."""
    now = datetime.now(timezone.utc)
    return now.strftime("%A, %B ") + str(now.day) + now.strftime(", %Y")


def _current_year() -> int:
    return datetime.now(timezone.utc).year


def _index_snippet(lead: Article | None) -> str:
    """One-sentence teaser for an index topic card."""
    if not lead:
        return "Check back this afternoon — today's stories are still being curated."
    if lead.summary:
        # First sentence of the lead summary
        for sep in (". ", "! ", "? "):
            if sep in lead.summary:
                return lead.summary.split(sep, 1)[0] + sep.strip()
        return lead.summary
    return lead.title


def _index_lead_brief(lead: Article | None) -> dict:
    """Title + URL + one-sentence snippet for the home page topic card."""
    if not lead:
        return {
            "title": "Today's stories are still being curated.",
            "url": "#",
            "snippet": "Check back this afternoon.",
        }
    return {
        "title": lead.title,
        "url": lead.url,
        "snippet": _index_snippet(lead),
    }


def render_all(
    leads: dict[str, Article | None],
    briefings: dict[str, list[Article]],
) -> None:
    """Render and write all four HTML files."""
    env = _make_env()
    today = _today_str()
    year = _current_year()

    # Decorate articles with display-only fields
    for v, lead in leads.items():
        if lead:
            _decorate(lead)
    for v, items in briefings.items():
        for a in items:
            _decorate(a)

    # --- Chapter pages ---
    for vertical in ("ecommerce", "fintech", "ai"):
        meta = PAGE_META[vertical]
        ctx = {
            **meta,
            "active": vertical,
            "today_str": today,
            "current_year": year,
            "lead": leads.get(vertical),
            "briefings": briefings.get(vertical, []),
            "filter_chips": FILTER_CHIPS[vertical],
            "subtopic_labels": SUBTOPIC_LABELS,
        }
        tpl = env.get_template(f"{vertical}.j2")
        out = tpl.render(**ctx)
        OUTPUT_FILES[vertical].write_text(out, encoding="utf-8", newline="\n")
        log.info(
            "rendered %s: lead=%s briefings=%d chars=%d",
            vertical,
            "yes" if leads.get(vertical) else "no",
            len(briefings.get(vertical, [])),
            len(out),
        )

    # --- Index page ---
    leads_brief = {v: _index_lead_brief(leads.get(v)) for v in ("ecommerce", "fintech", "ai")}
    idx_ctx = {
        **PAGE_META["index"],
        "active": "index",
        "today_str": today,
        "current_year": year,
        "leads_brief": leads_brief,
    }
    tpl = env.get_template("index.j2")
    out = tpl.render(**idx_ctx)
    OUTPUT_FILES["index"].write_text(out, encoding="utf-8", newline="\n")
    log.info("rendered index: chars=%d", len(out))
