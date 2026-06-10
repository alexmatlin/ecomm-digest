# The Digest — project context

A daily news aggregator covering E-commerce, Fintech, and AI. Static site,
auto-refreshed once daily by a GitHub Actions pipeline that ingests RSS
feeds, dedupes/routes/scores them, summarizes via Anthropic Haiku 4.5, and
commits regenerated HTML back to the repo.

**Live**: https://coruscating-platypus-eccfd0.netlify.app/
**Repo**: https://github.com/alexmatlin/ecomm-digest
**Owner**: SG-based; site copy and source mix biased toward APAC + global majors.

---

## How the site is updated

```
Cron (07:00 SGT daily) ───┐
                          ├─→ GitHub Actions runs `python -m backend.pipeline`
Manual workflow_dispatch ─┘   → digest-bot commits new HTML → Netlify redeploys
```

**Cost**: ~$0.10–0.13 per run (~$3/month at 1 run/day). Haiku 4.5 with
prompt caching enabled.

---

## Critical mental model: two separate layers

```
PIPELINE LAYER (runs occasionally, costs money)
   ↓ writes HTML once per run
HTML FILES (static, sit in repo root)
   ↓ loaded by browser
STYLE/SCRIPT LAYER (style.css + script.js — read fresh on every page load)
```

**This dictates the dev workflow:**

| What changed | What to run |
|---|---|
| `style.css` / `script.js` / image assets | Nothing. Just refresh the browser. |
| Templates (`templates/*.j2`) | `python -m backend.pipeline --no-llm` (free) |
| Routing/scoring (`backend/*.py`) | `python -m backend.pipeline --no-llm` (free) |
| Prompt/voice (`summarize.py`) | Full run, ~$0.10. **Always ask user first.** |
| Just want fresh content on live site | Push to GitHub, trigger workflow_dispatch |

**Never commit HTML generated locally with `--no-llm`.** It contains raw RSS
text instead of polished summaries. Standard local-test pattern:

```bash
rm -f state/seen.json                                    # reset cross-run dedup
python -m backend.pipeline --no-llm                       # regenerate
# inspect HTML
git checkout -- index.html ecommerce.html fintech.html ai.html state/seen.json
```

---

## File map

```
backend/
  config.py        Paths, scoring weights, selection caps, model names.
  ingest.py        RSS fetch via feedparser. ftfy fixes em-dash mojibake from
                   feeds with wrong Content-Type charset. Filters non-news
                   URLs (/event-info/, /webinar/, /podcast/, …) at ingest.
  dedup.py         canonical_url() = aggressive normalize for dedup key;
                   display_url() = strip UTM only, keep host/scheme.
                   rapidfuzz token_set_ratio ≥88 for in-run title clustering.
  router.py        18 keyword-rule buckets across 3 verticals. Source vertical
                   is SICKY unless cross-vertical keyword evidence is ≥2x.
                   Unmatched → fallback bucket (logged, never displayed).
  scorer.py        Two formulas:
                     score()      = tier_base × keyword_density × recency_decay
                                    (used for briefings, vertical ordering)
                     lead_score() = score × tier_mult × (1+bonus) × (1−penalty)
                                    (event-driven: action verbs + dollar figs;
                                     penalizes hedging + Why/How/Inside prefixes;
                                     T1 majors get 1.4x lead-only multiplier)
  state.py         Cross-run dedup. state/seen.json maps canonical URL → ISO ts.
                   14-day TTL. Bot commits state/seen.json each run.
  summarize.py     Anthropic SDK calls. Prompt caching enabled. JSON output.
                   System prompts capture editorial voice (see "Voice" below).
                   Token caps: 200/250/300 input, 220 output briefings,
                   400 output leads. Longform sources (Import AI, Latent Space)
                   get larger input cap.
  render.py        Jinja2 → 4 HTML files. PAGE_META has the static hero copy
                   per chapter. FILTER_CHIPS defines order/labels of filter bar.
                   _index_lead_brief() builds the title+URL+snippet for home cards.
  pipeline.py      Orchestrator. Three-pass select():
                     pass 1: hard cap 3/subtopic, target 14 briefings
                     pass 2: spread-aware overflow to 14
                     pass 3: burst — extras up to 6/subtopic and 18 total,
                             quality-gated by median score
                   --no-llm flag skips Anthropic step entirely.

templates/
  index.j2         Home: 3 topic cards, each with today's lead headline + snippet.
  ecommerce.j2 fintech.j2 ai.j2   Just include partials/_chapter.j2.
  partials/
    _meta.j2       <head> meta tags incl. OG/Twitter
    _header.j2     Top nav with active-link highlighting
    _footer.j2     Brand mark + footer nav + ©
    _subscribe.j2  Form (currently no-op — preventDefault())
    _chapter.j2   Hero + Today's lead + Briefings grid (with filter chips)
    _story_card.j2  Single briefing card

data/sources.json   22 validated RSS sources + failed[] list with reasons.
                    Schema: tier (major|core|specialist), vertical, subtopics,
                    content_type (full|summary), token_cap, status.

state/seen.json     Cross-run dedup state. Bot-managed. .gitkeep prevents the
                    folder from being empty when state file doesn't exist.

.github/workflows/digest.yml   Cron + workflow_dispatch + auto-commit logic.
                               Requires ANTHROPIC_API_KEY repo secret.

style.css           ~700 lines. CSS custom properties for light/dark theming.
                    Phase 1 design polish (date size, sticky filter, subtopic
                    colors via --topic-h custom property) lives at the bottom.
script.js           initTheme + initScrollShrink + initScrollReveal +
                    initFilters + initSearchToggle. Single IIFE.
date.js             Updates .hero-eyebrow-date span on every page load.
favicon.svg         Terracotta ◐ mark.
```

---

## Taxonomy

**3 verticals**: `ecommerce`, `fintech`, `ai` (+ `cross_cutting` for sources
that span verticals, e.g. TechCrunch, Straits Times).

**18 subtopics** (6 per vertical):
- E-commerce: `marketplaces`, `dtc-brands`, `retail-media`, `logistics`, `social-live`, `platforms-tech`
- Fintech: `payments`, `banking-wealth`, `lending-credit`, `stablecoins-crypto`, `embedded-finance`, `regulation`
- AI: `models`, `agents`, `infrastructure`, `enterprise`, `regulation` (shared), `startups-funding`

**3 source tiers**:
- `major` (T1): broad business outlets, salience oracle. Currently 1: Straits Times Business.
- `core` (T2): trade-spine specialists (Banking Dive, Supply Chain Dive, etc.)
- `specialist` (T3): niche specialists (deBanked, Latent Space, etc.)

`_TIER_BASE` in scorer.py: major=0.5, core=0.5, specialist=0.3. T1 boost comes
from the lead-only multiplier (1.4×) in `lead_score()`, not from briefing-time
salience — keeps specialists competitive in briefings.

---

## Editorial voice (for summarize.py prompts)

**Tone**: confident, dry, slightly understated. Senior trade-publication editor
who's been on the beat a decade. Assumes reader is smart and short on time.

**Briefing structure**: exactly 2 sentences.
1. WHAT happened (concrete, specific)
2. WHY it matters (implication or signal)

**Lead structure**: single paragraph, 2-3 sentences, max 80 words.

**Hard rules** (enforced in system prompt):
- No hedging language ("may", "could", "potentially") unless source uses it
- No marketing fluff. No "in a bold move", "game-changer", "revolutionary"
- Preserve names, dollar figures, percentages exactly as given
- Don't invent specifics not in the source

---

## Selection logic (per vertical, per run)

1. **Lead**: max by `lead_score()` — favors action verbs (acquires/raises/files
   S-1/launches/cuts/partners), dollar figures ($XM/$XB), T1 sources.
   Penalizes hedging and Why/How/Inside title prefixes.
2. **Briefings**: ranked by `score()`, then three-pass selection:
   - Pass 1: hard cap of `SUBTOPIC_CAP_BASE` (3) per subtopic, target `BRIEFINGS_PER_VERTICAL` (14)
   - Pass 2: spread-aware overflow to 14 if under target
   - Pass 3: burst extras up to `SUBTOPIC_CAP_BURST` (6) per subtopic and
     `BRIEFINGS_HARD_CAP` (18) total, score ≥ median quality bar

The grid renders as 3 columns of cards. So 14 briefings = ~4–5 rows;
18 briefings = 6 rows.

---

## Decisions log (so future sessions don't re-litigate)

- **No T1 majors in v1, added one (ST) in v1.5**. More can be added without
  changing scoring math.
- **No Batch API** for v1 — simpler synchronous flow, cost acceptable.
- **Fuzzy clustering only** (no embeddings) for in-run dedup — revisit if
  duplicate misses become visible.
- **Fallback bucket is log-only, never displayed**. It's a diagnostic tool —
  if it grows large, tune router keywords rather than show untagged content.
- **"Lead = biggest news event"** (event-driven), not "most consequential read"
  (analysis-driven). Drives the action-verb / dollar-figure weighting.
- **No lead quality threshold**: always show something, even if mediocre, to
  preserve layout.
- **T1 lead-only multiplier** (Option B): T1 boost on lead selection only,
  not on briefings, so specialists don't get crowded out of briefings.
- **Subtopic cap = 3 default, 6 burst**, total briefings = 14 default, 18 max.
  Burst adds slots, never displaces other subtopics.
- **"Week in numbers" deleted** (was fictional). Could be restored later with
  a real stats source.
- **Subscribe button is a no-op** (`event.preventDefault()`). Held.
- **About footer link points to `#`** (broken). Held.

---

## Deferred / backlog

Captured in conversation but explicitly held for now:

1. **Cross-source salience clustering** (Q4 deferred). Highest-leverage signal
   for lead selection — when same story appears in 2+ sources, boost score.
   Requires modifying dedup to track sources instead of discarding duplicates.
2. **APAC AI source** — currently no APAC-specific AI source (Tech in Asia
   helps but is broad). Worth a feed-hunt session.
3. **More T1 majors** (CNA Business, SCMP Business) — strengthens
   cross-validation signal.
4. **Router keyword tuning** — ~35–78 fallback items per run; some are
   genuine noise, some are real misses. Sift periodically.
5. **Editor's note in chapter hero** — replace static brand copy with
   LLM-generated 1-line preview of the day. ~+3¢ per run.
6. **Real "Week in numbers"** — pull from a stats API, hand-curate weekly, or
   leave deleted.
7. **Subscribe form wiring** — connect to an email service.
8. **About page** — write content or hide the link.
9. **Favicon dark-mode variant**.

---

## Failure modes & known fixes

- **`â` in summaries** → ftfy not running. Already wired; if it returns, check
  ingest.py `_strip_html()`.
- **Finextra "events" as briefings** → `_NON_NEWS_URL_PATTERNS` in ingest.py
  drops them. Don't remove.
- **Misrouted articles** (e.g. Modern Retail story → Fintech because
  "Bank of America" mentioned) → router.py source-vertical-sticky rule with
  2× threshold. Don't loosen below 2×.
- **Logistics dominating ecomm grid** → was a subtopic cap bug in pass-2.
  Pass-3 now spread-aware. Don't merge pass-2 and pass-3.
- **Bot run fails / no commit** → check Actions logs. Most common: a feed
  returns 503 (bot block). Pipeline continues with other sources; not fatal.
- **Line-ending CRLF warnings on Windows** → cosmetic, ignore.

---

## Environment specifics

- **Dev**: Windows, OneDrive path. Python 3.14 locally.
- **CI**: Ubuntu, Python 3.12. Same code runs on both.
- **Anthropic key**: set as repo secret `ANTHROPIC_API_KEY`. Local debug uses
  a gitignored `.env` file (NEVER commit it).
- **feedparser** needs a browser UA (`Mozilla/5.0 (compatible; TheDigestBot/1.0…)`)
  or some feeds 403/503.
- **rapidfuzz** for fuzzy title matching (faster than fuzzywuzzy, MIT license).
- **ftfy** for fixing UTF-8/Latin-1 mojibake in feed text.

---

## Working pattern with the user

- User leads design and editorial decisions; agent executes.
- User typically asks for a plan/options before code changes that touch
  multiple files or change behavior meaningfully.
- Commits happen only when user says "commit" or "let's commit". Never
  proactively.
- CSS-only tweaks: agent does them silently. No need to ask.
- LLM-cost work: ALWAYS ask before triggering a real run.
- Honest tradeoffs over false certainty — flag when a fix is approximate,
  when a heuristic might break, when a number is fictional.
