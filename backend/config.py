"""Shared constants and configuration for the digest pipeline."""
from pathlib import Path

# === Paths ===
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STATE_DIR = ROOT / "state"
TEMPLATES_DIR = ROOT / "templates"
SOURCES_FILE = DATA_DIR / "sources.json"
SEEN_FILE = STATE_DIR / "seen.json"

# === Output files (written to repo root) ===
OUTPUT_FILES = {
    "index": ROOT / "index.html",
    "ecommerce": ROOT / "ecommerce.html",
    "fintech": ROOT / "fintech.html",
    "ai": ROOT / "ai.html",
}

# === Verticals & subtopics (must mirror filter chips in the HTML) ===
VERTICALS = ["ecommerce", "fintech", "ai"]

SUBTOPICS = {
    "ecommerce": [
        "marketplaces",
        "dtc-brands",
        "retail-media",
        "logistics",
        "social-live",
        "platforms-tech",
    ],
    "fintech": [
        "payments",
        "banking-wealth",
        "lending-credit",
        "stablecoins-crypto",
        "embedded-finance",
        "regulation",
    ],
    "ai": [
        "models",
        "agents",
        "infrastructure",
        "enterprise",
        "regulation",
        "startups-funding",
    ],
}

# Display labels for tag chips on cards
SUBTOPIC_LABELS = {
    "marketplaces": "Marketplaces",
    "dtc-brands": "DTC & Brands",
    "retail-media": "Retail Media",
    "logistics": "Logistics",
    "social-live": "Social & Live Commerce",
    "platforms-tech": "Platforms & Tech",
    "payments": "Payments",
    "banking-wealth": "Banking & Wealth",
    "lending-credit": "Lending & Credit",
    "stablecoins-crypto": "Stablecoins & Crypto",
    "embedded-finance": "Embedded Finance",
    "regulation": "Regulation & Policy",
    "models": "Models",
    "agents": "Agents",
    "infrastructure": "Infrastructure",
    "enterprise": "Enterprise",
    "startups-funding": "Startups & Funding",
}

# === Scoring weights ===
# v1.5: T1 majors (Straits Times) contribute via higher tier_base in
# _vertical_salience (see scorer._TIER_BASE). W_GENERAL is reserved for a
# future cross-source clustering signal ("appeared in N T1 outlets"); not
# implemented yet, keep at 0.
W_GENERAL = 0.0
W_VERTICAL = 1.0
RECENCY_HALFLIFE_HOURS = 36.0  # signal halves every 36h

# === Selection caps ===
LEAD_PER_VERTICAL = 1
BRIEFINGS_PER_VERTICAL = 14  # target — 4-5 rows of 3, fills most days
BRIEFINGS_HARD_CAP = 18      # upper bound for burst days (6x3 grid)
SUBTOPIC_CAP_BASE = 3        # default cap per subtopic in pass 1
SUBTOPIC_CAP_BURST = 6       # max if subtopic dominates a news cycle (e.g. M&A spike)

# === Dedup thresholds ===
TITLE_FUZZY_THRESHOLD = 88  # rapidfuzz token_set_ratio cutoff for "same story"
SEEN_TTL_DAYS = 14  # how long a URL stays in seen.json before being eligible again

# === LLM config ===
MODEL = "claude-haiku-4-5"
LEAD_MODEL = "claude-haiku-4-5"  # v1: use Haiku for lead too; can upgrade to Sonnet later
MAX_OUTPUT_TOKENS_BRIEFING = 220
MAX_OUTPUT_TOKENS_LEAD = 400
INPUT_TOKEN_CAP_DEFAULT = 800  # truncate article body before sending
INPUT_TOKEN_CAP_LONGFORM = 1200  # for Import AI / Latent Space style longreads

# === Recency cutoff: articles older than this are dropped ===
MAX_AGE_HOURS = 48
