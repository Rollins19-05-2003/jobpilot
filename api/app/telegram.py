"""Telegram delivery: the daily morning digest.

Setup (2 minutes, free):
1. Message @BotFather on Telegram -> /newbot -> copy the token
2. Message your new bot anything, then open
   https://api.telegram.org/bot<TOKEN>/getUpdates to find your chat_id
3. Put both in .env
"""
import logging

import httpx

from . import config

log = logging.getLogger("jobpilot.telegram")

SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _fmt_job(rank: int, j: dict) -> str:
    skills = ", ".join(j.get("matched_skills") or [])[:120]
    gaps = ", ".join(j.get("gaps") or [])[:120]
    return (
        f"<b>{rank}. {j['title']}</b> @ {j['company']} — <b>{j['fit_score']}%</b>\n"
        f"{j['verdict']}\n"
        f"✅ {skills}\n"
        f"⚠️ {gaps or 'no notable gaps'}\n"
        f"<a href=\"{j['url']}\">Apply / JD</a>\n"
    )


def build_digest(jobs: list[dict], new_count: int) -> str:
    strong = [j for j in jobs if (j.get("fit_score") or 0) >= config.STRONG_FIT]
    header = (
        f"☀️ <b>JobPilot Daily</b>\n"
        f"Scanned targets, found <b>{new_count}</b> new matching roles, "
        f"<b>{len(strong)}</b> strong fits (≥{config.STRONG_FIT}%).\n\n"
    )
    if not jobs:
        return header + "Nothing worth your time today. Go build something instead 💪"
    body = "\n".join(_fmt_job(i + 1, j) for i, j in enumerate(jobs[:8]))
    return header + body


def send(text: str) -> bool:
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        log.error("Telegram not configured — printing digest instead:\n%s", text)
        return False
    try:
        r = httpx.post(
            SEND_URL.format(token=config.TELEGRAM_BOT_TOKEN),
            json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": text[:4000],  # Telegram hard limit 4096
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        log.error("telegram send failed: %s", e)
        return False
