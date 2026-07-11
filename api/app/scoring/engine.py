"""Gemini scoring engine (free tier). Compares a JD to the profile,
returns structured JSON: fit_score, verdict, matched_skills, gaps, pitch_line.
Plain REST via httpx — no heavy SDK, easy to swap providers later.
"""
import json
import logging

import httpx

from .. import config

log = logging.getLogger("jobpilot.scoring")

SYSTEM_PROMPT = """You are a razor-sharp technical recruiter helping a candidate \
triage job openings. You are honest: a bad fit gets a low score even if the \
company is famous. Score fit ONLY against the candidate profile provided.

Scoring rubric (0-100):
- 85-100: apply today — skills, seniority and location all align
- 70-84: strong fit — 1 minor gap at most
- 50-69: partial fit — worth applying only if pipeline is thin
- <50: skip — seniority mismatch, wrong stack, or wrong location

Hard rules:
- If the role requires clearly more experience than the candidate has (e.g. 5+ years), cap the score at 45.
- matched_skills and gaps must reference concrete items from the JD.
- pitch_line: ONE sentence the candidate could use in outreach, weaving in one \
of their headline metrics if genuinely relevant. Warm, humble, no buzzwords.

Respond with ONLY a JSON object, no markdown, using exactly these keys:
{"fit_score": int, "verdict": "one-line honest summary", \
"matched_skills": ["..."], "gaps": ["..."], "pitch_line": "..."}
"""


def build_prompt(profile: dict, job: dict) -> str:
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"CANDIDATE PROFILE:\n{json.dumps(profile, indent=1)}\n\n"
        f"JOB OPENING:\nCompany: {job['company']}\nTitle: {job['title']}\n"
        f"Location: {job['location']}\n\nJOB DESCRIPTION:\n{job['jd_text'][:8000]}"
    )


def score_job(profile: dict, job: dict) -> dict | None:
    """Returns the parsed scoring dict, or None on failure (job stays unscored)."""
    if not config.GEMINI_API_KEY:
        log.error("GEMINI_API_KEY not set — cannot score")
        return None
    url = config.GEMINI_URL.format(model=config.GEMINI_MODEL, key=config.GEMINI_API_KEY)
    body = {
        "contents": [{"parts": [{"text": build_prompt(profile, job)}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    try:
        r = httpx.post(url, json=body, timeout=60)
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(text)
        # Minimal validation
        data["fit_score"] = max(0, min(100, int(data.get("fit_score", 0))))
        for key in ("verdict", "pitch_line"):
            data.setdefault(key, "")
        for key in ("matched_skills", "gaps"):
            if not isinstance(data.get(key), list):
                data[key] = []
        return data
    except Exception as e:  # noqa: BLE001 — a single bad response must not kill the batch
        log.warning("scoring failed for %s @ %s: %s", job["title"], job["company"], e)
        return None
