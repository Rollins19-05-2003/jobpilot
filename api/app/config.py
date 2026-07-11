"""JobPilot configuration. Everything is env-driven — zero-cost, zero-hardcoding."""
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # repo root

# --- LLM (Gemini free tier) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={key}"
)

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Database: SQLite locally, swap DATABASE_URL for Supabase Postgres later ---
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'jobpilot.db'}")

# --- Scoring thresholds ---
STRONG_FIT = int(os.getenv("STRONG_FIT_THRESHOLD", "75"))
MIN_FIT_TO_KEEP = int(os.getenv("MIN_FIT_TO_KEEP", "40"))

# --- Target companies (Greenhouse / Lever board slugs) ---
# Find a company's slug from its careers page URL:
#   boards.greenhouse.io/<slug>   |   jobs.lever.co/<slug>
TARGETS_FILE = BASE_DIR / "profile" / "targets.json"
PROFILE_FILE = BASE_DIR / "profile" / "profile.json"


def load_profile() -> dict:
    return json.loads(PROFILE_FILE.read_text())


def load_targets() -> dict:
    if TARGETS_FILE.exists():
        return json.loads(TARGETS_FILE.read_text())
    return {"greenhouse": [], "lever": []}
