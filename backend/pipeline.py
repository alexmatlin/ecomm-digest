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
    Per vertical: top-scoring article → lead; next N → briefings.

    Subtopic spread (two-pass):
      Pass 1 — hard cap of 3 per subtopic. Walk score-ordered candidates;
               skip any whose subtopic is already at 3.
      Pass 2 — if we ended pass 1 below target, fill remaining slots from
               leftover candidates (over-cap allowed) to avoid sparse pages.
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
        picked_ids: set[int] = set()

        # Pass 1: hard cap 3-per-subtopic
        for cand in remaining:
            if len(picks) >= BRIEFINGS_PER_VERTICAL:
                break
            if subtopic_counts[cand.subtopic] >= 3:
                continue
            picks.append(cand)
            picked_ids.add(id(cand))
            subtopic_counts[cand.subtopic] += 1

        # Pass 2: overflow fill if still below target.
        # Prefer under-represented subtopics first to preserve spread; within
        # each subtopic, still score-order. This stops one dominant source
        # (e.g. FreightWaves) from flooding the page when leftovers are biased.
        if len(picks) < BRIEFINGS_PER_VERTICAL:
            overflow_before = len(picks)
            leftover = [c for c in remaining if id(c) not in picked_ids]
            # Sort leftover by (current subtopic count, -score) — lowest count + highest score wins
            leftover.sort(key=lambda c: (subtopic_counts[c.subtopic], -c.score))
            for cand in leftover:
                if len(picks) >= BRIEFINGS_PER_VERTICAL:
                    break
                picks.append(cand)
                picked_ids.add(id(cand))
                subtopic_counts[cand.subtopic] += 1
            if len(picks) > overflow_before:
                logging.info(
                    "select %s: pass-2 overflow added %d (spread-aware)",
                    v, len(picks) - overflow_before,
                )

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
