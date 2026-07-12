"""JobPilot configuration. Everything is env-driven — zero-cost, zero-hardcoding."""
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # repo root

# --- LLM (Gemini free tier) ---
# Model cascade: the lite model bulk-scores ~30 JDs/day (high free-tier RPD);
# the stronger flash model only writes outreach drafts (a handful/day —
# gemini-3.5-flash free tier is just 20 req/day, so it can't do both).
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
DRAFT_MODEL = os.getenv("DRAFT_MODEL", "gemini-3.5-flash")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={key}"
)

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- JSearch via RapidAPI (optional; free tier ~200 req/month) ---
# Aggregates Google-for-Jobs (LinkedIn/Naukri/Indeed postings) legally.
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")

# --- Database: SQLite locally, swap DATABASE_URL for Supabase Postgres later ---
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'jobpilot.db'}")

# --- Scoring thresholds ---
STRONG_FIT = int(os.getenv("STRONG_FIT_THRESHOLD", "75"))
MIN_FIT_TO_KEEP = int(os.getenv("MIN_FIT_TO_KEEP", "40"))

# Pause between Gemini calls — free tier allows ~10 req/min and bursts get 429s.
# 6s ≈ 10/min. The daily run is a cron job; nobody is waiting on it.
SCORE_DELAY_SECONDS = float(os.getenv("SCORE_DELAY_SECONDS", "6"))

# --- Target companies (Greenhouse / Lever board slugs) ---
# Find a company's slug from its careers page URL:
#   boards.greenhouse.io/<slug>   |   jobs.lever.co/<slug>
TARGETS_FILE = BASE_DIR / "profile" / "targets.json"
PROFILE_FILE = BASE_DIR / "profile" / "profile.json"
COMPANIES_FILE = BASE_DIR / "profile" / "companies.json"

# --- Outreach ---
FOLLOW_UP_AFTER_DAYS = int(os.getenv("FOLLOW_UP_AFTER_DAYS", "5"))


def load_profile() -> dict:
    return json.loads(PROFILE_FILE.read_text())


def load_companies() -> list[dict]:
    if COMPANIES_FILE.exists():
        return json.loads(COMPANIES_FILE.read_text()).get("companies", [])
    return []


def load_targets() -> dict:
    if TARGETS_FILE.exists():
        return json.loads(TARGETS_FILE.read_text())
    return {"greenhouse": [], "lever": []}
