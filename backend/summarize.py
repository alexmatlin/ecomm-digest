"""
Generate editorial summaries via Anthropic Haiku 4.5.

Each summary is exactly 2 sentences. We use the system prompt as a cacheable
prefix (loaded once per run, charged at 10% for repeat hits in the same
prompt-cache TTL).

Inputs are token-capped: we truncate body text to roughly INPUT_TOKEN_CAP_DEFAULT
characters * 4 chars/token before sending. (We don't tokenize precisely — the
character heuristic is good enough for budgeting.)
"""
from __future__ import annotations

import json
import logging
import os
import re

from anthropic import Anthropic

from .config import (
    MODEL,
    LEAD_MODEL,
    MAX_OUTPUT_TOKENS_BRIEFING,
    MAX_OUTPUT_TOKENS_LEAD,
    INPUT_TOKEN_CAP_DEFAULT,
    INPUT_TOKEN_CAP_LONGFORM,
)
from .ingest import Article

log = logging.getLogger(__name__)

# Long-form sources (their feeds carry 1000-8000 word essays). We allow a larger
# input window but still cap aggressively.
_LONGFORM_SOURCES = {"import-ai", "latent-space", "crunchbase-news", "freightwaves"}


SYSTEM_PROMPT = """You are the editor of The Digest, a daily distillation of \
the most consequential moves across e-commerce, fintech, and AI for operators, \
builders, and investors.

Your voice: confident, dry, slightly understated. Like a senior trade-publication \
editor who has been on the beat for a decade. You assume the reader is smart and \
short on time.

For each article you are given, write a SUMMARY that is exactly 2 sentences:
  - Sentence 1: WHAT happened (the news), concrete and specific.
  - Sentence 2: WHY it matters (the implication, signal, or context).

Hard rules:
  - Output strictly JSON: {"summary": "<two sentences>"}.
  - No hedging language ("may", "could", "potentially") unless the source uses it.
  - No marketing fluff. No "in a bold move". No "game-changer".
  - Names matter: keep companies, dollar figures, percentages exactly as given.
  - If the article is thin (just a headline), do your best with what's there \
but never invent specifics that aren't in the source."""


LEAD_SYSTEM_PROMPT = """You are the editor of The Digest. You are writing the \
TODAY'S LEAD summary — the single most important story in a vertical for the day.

Your voice: confident, dry, slightly understated. Like a senior trade editor.

Write a LEAD summary as a single paragraph of 2-3 sentences:
  - Sentence 1: WHAT happened, concretely.
  - Sentence 2: The structural or strategic implication.
  - Sentence 3 (optional): A pointed observation about what to watch next, or \
the second-order effect.

Hard rules:
  - Output strictly JSON: {"summary": "<paragraph>"}.
  - No hedging unless the source uses it. No marketing language.
  - Keep names, numbers, and percentages exactly as given.
  - Maximum 80 words."""


def _truncate(text: str, char_budget: int) -> str:
    """Trim to char_budget at the nearest sentence/word boundary."""
    if len(text) <= char_budget:
        return text
    cut = text[:char_budget]
    # Prefer sentence boundary
    m = re.search(r"[.!?]\s+[^.!?]*$", cut)
    if m and m.start() > char_budget * 0.6:
        return cut[: m.start() + 1]
    # Fall back to word boundary
    sp = cut.rfind(" ")
    if sp > 0:
        return cut[:sp] + "…"
    return cut + "…"


def _budget_chars(article: Article) -> int:
    if article.source_id in _LONGFORM_SOURCES:
        return INPUT_TOKEN_CAP_LONGFORM * 4
    return min(article.token_cap, INPUT_TOKEN_CAP_DEFAULT) * 4


def _build_user_message(article: Article) -> str:
    body = _truncate(article.body, _budget_chars(article))
    return (
        f"Source: {article.source_name}\n"
        f"Vertical / subtopic: {article.vertical} / {article.subtopic}\n"
        f"Title: {article.title}\n"
        f"URL: {article.url}\n\n"
        f"Article body:\n{body}"
    )


def _parse_json_summary(text: str) -> str | None:
    """Extract {'summary': '...'} from model output. Tolerates light noise."""
    # Try direct JSON first
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "summary" in obj:
            return str(obj["summary"]).strip()
    except json.JSONDecodeError:
        pass
    # Look for {"summary": "..."} embedded in prose
    m = re.search(r'\{\s*"summary"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}', text, re.DOTALL)
    if m:
        return m.group(1).encode("utf-8").decode("unicode_escape").strip()
    return None


def _make_client() -> Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY env var not set. "
            "In GH Actions: set a repository secret named ANTHROPIC_API_KEY."
        )
    return Anthropic(api_key=api_key)


def summarize_briefings(client: Anthropic, articles: list[Article]) -> None:
    """Fill article.summary for each briefing. Mutates in place."""
    for a in articles:
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=MAX_OUTPUT_TOKENS_BRIEFING,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {"role": "user", "content": _build_user_message(a)},
                ],
            )
            text = "".join(b.text for b in resp.content if hasattr(b, "text"))
            summary = _parse_json_summary(text)
            if not summary:
                log.warning(
                    "summarize: failed to parse JSON for %s (%s)",
                    a.source_id, a.title[:60],
                )
                # Fall back to using the source body's first sentence
                summary = _first_two_sentences(a.body) or a.title
            a.summary = summary
            log.info(
                "summarize briefing: %s/%s input~%dc output=%d tok",
                a.vertical, a.subtopic,
                len(_build_user_message(a)),
                resp.usage.output_tokens,
            )
        except Exception as e:
            log.error("summarize error for %s: %s", a.source_id, e)
            a.summary = _first_two_sentences(a.body) or a.title


def summarize_leads(client: Anthropic, leads: list[Article]) -> None:
    """Same as summarize_briefings but with the LEAD prompt + larger max_tokens."""
    for a in leads:
        try:
            resp = client.messages.create(
                model=LEAD_MODEL,
                max_tokens=MAX_OUTPUT_TOKENS_LEAD,
                system=[
                    {
                        "type": "text",
                        "text": LEAD_SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {"role": "user", "content": _build_user_message(a)},
                ],
            )
            text = "".join(b.text for b in resp.content if hasattr(b, "text"))
            summary = _parse_json_summary(text) or _first_two_sentences(a.body) or a.title
            a.summary = summary
            log.info(
                "summarize lead: %s output=%d tok",
                a.vertical, resp.usage.output_tokens,
            )
        except Exception as e:
            log.error("lead summarize error for %s: %s", a.source_id, e)
            a.summary = _first_two_sentences(a.body) or a.title


def _first_two_sentences(text: str) -> str | None:
    if not text:
        return None
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:2]) if parts else None


def run_summaries(briefings: list[Article], leads: list[Article]) -> None:
    """Top-level entry — call this after selection."""
    client = _make_client()
    log.info("summarize: leads=%d briefings=%d", len(leads), len(briefings))
    summarize_leads(client, leads)
    summarize_briefings(client, briefings)
