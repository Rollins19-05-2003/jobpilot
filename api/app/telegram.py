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


def build_outreach_section(followups: list[dict], replies_pending: int) -> str:
    """The outreach block appended to the daily digest. Empty string if quiet."""
    if not followups and not replies_pending:
        return ""
    lines = ["", "📮 <b>Outreach</b>"]
    if followups:
        lines.append(f"<b>{len(followups)}</b> follow-ups due today:")
        for c in followups[:10]:
            name = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
            lines.append(f"  • {name} — {c.get('company') or '?'}")
        if len(followups) > 10:
            lines.append(f"  …and {len(followups) - 10} more")
    if replies_pending:
        lines.append(f"🎉 <b>{replies_pending}</b> replies waiting on YOUR next move")
    return "\n".join(lines) + "\n"


def build_digest(jobs: list[dict], new_count: int, outreach_section: str = "") -> str:
    strong = [j for j in jobs if (j.get("fit_score") or 0) >= config.STRONG_FIT]
    header = (
        f"☀️ <b>JobPilot Daily</b>\n"
        f"Scanned targets, found <b>{new_count}</b> new matching roles, "
        f"<b>{len(strong)}</b> strong fits (≥{config.STRONG_FIT}%).\n\n"
    )
    if not jobs:
        body = "Nothing worth your time today. Go build something instead 💪"
    else:
        body = "\n".join(_fmt_job(i + 1, j) for i, j in enumerate(jobs[:8]))
    # send() hard-truncates at 4000 chars; jobs cap at 8 and follow-ups at 10,
    # which keeps a full digest comfortably inside Telegram's 4096 limit.
    return header + body + outreach_section


def build_weekly_review(stats: dict) -> str:
    pipeline = " · ".join(
        f"{status} <b>{count}</b>"
        for status, count in (stats.get("by_status") or {}).items() if count
    )
    lines = [
        "📊 <b>JobPilot Weekly Outreach Review</b>",
        f"Sent: <b>{stats.get('sent', 0)}</b> first emails, "
        f"<b>{stats.get('follow_ups_sent', 0)}</b> follow-ups, "
        f"across <b>{stats.get('companies_touched', 0)}</b> companies",
        f"Replies: <b>{stats.get('replies', 0)}</b> "
        f"(reply rate <b>{stats.get('reply_rate_pct', 0)}%</b>) | "
        f"Meetings: <b>{stats.get('meetings', 0)}</b>",
        f"Follow-ups due now: <b>{stats.get('followups_due', 0)}</b>",
    ]
    if pipeline:
        lines.append(f"Pipeline: {pipeline}")
    if stats.get("advice"):
        lines.append(f"\n⚠️ <b>{stats['advice']}</b>")
    lines.append("\nKeep it human: ≤10 sends/day, 9–11 AM recipient time, hooks first.")
    return "\n".join(lines)


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
