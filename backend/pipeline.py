"""
End-to-end pipeline orchestrator.

Stages:
  1. Ingest        — fetch all configured RSS feeds.
  2. Dedup         — URL canonical + fuzzy title match (in-run).
  3. Route         — keyword rules → (vertical, subtopic) or fallback.
  4. Cross-run     — drop URLs we've already shipped in the last N days.
  5. Score         — vertical_salience × recency_decay.
  6. Select        — pick 1 lead + N briefings per vertical.
  7. Summarize     — Haiku 4.5 calls (with prompt caching).
  8. Render        — Jinja2 → 4 HTML files.
  9. Persist state — append selected URLs to seen.json.

Run from repo root:
    python -m backend.pipeline
    python -m backend.pipeline --dry-run     # skip LLM + write to /tmp
    python -m backend.pipeline --no-llm      # use raw RSS descriptions instead of LLM
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict

from .config import (
    LEAD_PER_VERTICAL, BRIEFINGS_PER_VERTICAL, VERTICALS,
)
from .ingest import Article, ingest_all
from .dedup import dedupe
from .router import route_all
from .scorer import score_all
from .state import load_seen, filter_unseen, save_seen
from .render import render_all


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def select(
    articles: list[Article],
) -> tuple[dict[str, Article | None], dict[str, list[Article]]]:
    """
    Per vertical: top-scoring article → lead; next N (with subtopic spread) → briefings.

    Subtopic spread: we try not to fill a chapter with the same subtopic. We
    walk the score-ordered list and skip a candidate if its subtopic already
    has 3 picks (when total slots ≥ 6) so that no single subtopic dominates.
    """
    by_vertical: dict[str, list[Article]] = defaultdict(list)
    for a in articles:
        if a.vertical:
            by_vertical[a.vertical].append(a)

    leads: dict[str, Article | None] = {}
    briefings: dict[str, list[Article]] = {}

    for v in VERTICALS:
        candidates = sorted(by_vertical.get(v, []), key=lambda x: x.score, reverse=True)
        if not candidates:
            leads[v] = None
            briefings[v] = []
            logging.warning("select: %s has 0 candidates", v)
            continue

        lead = candidates[0]
        lead.is_lead = True
        leads[v] = lead

        remaining = candidates[LEAD_PER_VERTICAL:]
        picks: list[Article] = []
        subtopic_counts: dict[str, int] = defaultdict(int)
        for cand in remaining:
            if len(picks) >= BRIEFINGS_PER_VERTICAL:
                break
            # Soft cap: max 3 per subtopic if we have enough variety to spare
            if subtopic_counts[cand.subtopic] >= 3 and len(picks) >= 6:
                continue
            picks.append(cand)
            subtopic_counts[cand.subtopic] += 1
        briefings[v] = picks

        logging.info(
            "select %s: lead='%s...' briefings=%d (subtopic spread: %s)",
            v, lead.title[:50], len(picks), dict(subtopic_counts),
        )

    return leads, briefings


def run(use_llm: bool = True, verbose: bool = False) -> int:
    _setup_logging(verbose)
    log = logging.getLogger("pipeline")
    log.info("=== Digest pipeline start ===")

    # 1. Ingest
    articles = ingest_all()
    if not articles:
        log.error("No articles ingested — aborting")
        return 1

    # 2. In-run dedup
    articles = dedupe(articles)

    # 3. Route
    routed, fallback = route_all(articles)
    log.info("fallback bucket size=%d (log only, not displayed)", len(fallback))

    # 4. Cross-run dedup
    seen = load_seen()
    routed = filter_unseen(routed, seen)

    # 5. Score
    score_all(routed)

    # 6. Select
    leads, briefings = select(routed)

    # 7. Summarize (LLM)
    if use_llm:
        from .summarize import run_summaries
        flat_briefings = [a for items in briefings.values() for a in items]
        flat_leads = [a for a in leads.values() if a]
        run_summaries(flat_briefings, flat_leads)
    else:
        log.info("--no-llm: skipping LLM step, using truncated body as summary")
        for items in briefings.values():
            for a in items:
                a.summary = _fallback_summary(a)
        for a in leads.values():
            if a:
                a.summary = _fallback_summary(a)

    # 8. Render
    render_all(leads, briefings)

    # 9. Persist seen state
    selected = [a for items in briefings.values() for a in items]
    selected += [a for a in leads.values() if a]
    save_seen(selected, seen)

    log.info("=== Digest pipeline done ===")
    return 0


def _fallback_summary(article: Article) -> str:
    body = (article.body or "").strip()
    if not body:
        return article.title
    # Take first ~280 chars at a sentence break
    if len(body) <= 280:
        return body
    cut = body[:280]
    dot = cut.rfind(". ")
    return (cut[: dot + 1] if dot > 100 else cut).strip()


def main() -> int:
    p = argparse.ArgumentParser(description="Run The Digest pipeline.")
    p.add_argument("--no-llm", action="store_true",
                   help="Skip Anthropic calls; use raw RSS descriptions.")
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    args = p.parse_args()
    return run(use_llm=not args.no_llm, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
