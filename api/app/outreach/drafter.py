"""Gemini outreach drafter (free tier). Personalized cold-outreach emails from
my profile + the contact's hook + company context. Plain httpx REST, same
pattern as scoring/engine.py.

DRAFTS ONLY — JobPilot never sends email and deliberately has no sending
integration. Drafts are reviewed and sent manually (mail-merge), which keeps
volume human, deliverability safe, and every message accountable.

Template A (recruiters / TA): short and credential-forward with a soft ask.
Template B (eng managers): "ask for advice, not a job". B consistently
outperforms A with managers because:
  - it asks for nothing they must say "no" to — no role request means no
    reflex to forward you to HR (lower threat),
  - it flatters expertise: people enjoy being asked how they built something,
  - "15 minutes of advice" is a much easier yes than "refer this stranger",
    and the referral often follows anyway once they've talked to you.
Follow-up: 2-3 lines, references the original, adds ONE new piece of value,
never guilt-trips.
"""
import json
import logging

import httpx

from .. import config

log = logging.getLogger("jobpilot.drafter")

RUBRIC = """\
Writing rules (non-negotiable):
- Natural Indian English — warm, direct, specific. Like a sharp engineer \
writing to a busy human, not a template.
- BANNED words/phrases: "passionate", "synergy", "esteemed", "kindly do the \
needful", "rockstar", "ninja", "I hope this email finds you well", "avid".
- NEVER invent experience, employers, projects or numbers that are not in the \
CANDIDATE PROFILE. Fabrication is disqualifying.
- Use the contact's first name and the company's name naturally. Weave the \
HOOK in as the reason for writing — it must not read like a mail-merge field.
- No links, no attachments, and no mention of resumes/attachments (first-touch \
deliverability: links and attachments trip spam filters).
- Resolve everything — the output must contain no placeholders like \
{{First Name}} or [Company].

Respond with ONLY a JSON object, no markdown: {"subject": "...", "body": "..."}
"""

TEMPLATE_A = """\
Write a cold email to a RECRUITER / talent-acquisition person.

Structure:
- Subject: under 7 words, concrete (role + one credibility token), no clickbait.
- Body: UNDER 120 words. One line on who the candidate is (current role + \
years). One or two lines on why THIS company, built on the HOOK. At most ONE \
metric from the profile — pick the single most relevant one, skip the rest. \
Close with a soft ask along the lines of "would you be open to pointing me at \
open roles that might fit?" — never demand a call. Sign off with first name only.
"""

TEMPLATE_B = """\
Write a cold email to an ENGINEERING MANAGER — ask for advice, NOT a job.

Structure:
- Subject: a genuine, specific question in under 8 words.
- Body: UNDER 130 words. Open with the specific thing their team works on \
(from the HOOK / company context) and why it caught the candidate's attention \
as an engineer. Ask ONE genuine technical question about their stack or a \
problem they must be facing. Mention ONE metric of the candidate's as context \
for why they care about this problem (peer curiosity, not a brag). Ask for 15 \
minutes of advice. Do NOT mention job openings, applications or referrals \
anywhere. Sign off with first name only.
"""

TEMPLATE_FOLLOWUP = """\
Write a FOLLOW-UP to the ORIGINAL EMAIL below, as if ~5 days passed with no reply.

Structure:
- Subject: "Re: " + the original subject, verbatim.
- Body: 2-3 sentences TOTAL. Briefly reference the earlier note (one clause, \
not a summary). Add ONE NEW piece of value that was NOT in the original — a \
different metric from the profile, or a relevant thing the candidate built. \
End light and pressure-free (a graceful out like "if now's not the right \
time, no stress" is fine). NO guilt-tripping, no "just bumping this up", no \
"did you get my email".
"""

TEMPLATES = {"A": TEMPLATE_A, "B": TEMPLATE_B, "followup": TEMPLATE_FOLLOWUP}


def build_prompt(profile: dict, contact: dict, company: dict,
                 version: str, original: dict | None = None) -> str:
    parts = [
        TEMPLATES[version],
        RUBRIC,
        f"CANDIDATE PROFILE:\n{json.dumps(profile, indent=1)}",
        (
            "CONTACT:\n"
            f"First name: {contact.get('first_name', '')}\n"
            f"Role: {contact.get('role_title', '')}\n"
            f"Persona: {contact.get('persona', '')}\n"
            f"HOOK (the specific reason to write to them): {contact.get('hook', '')}"
        ),
        (
            "COMPANY:\n"
            f"Name: {company.get('name', '')}\n"
            f"What they are: {company.get('tier_label', '')}, {company.get('hq_location', '')}\n"
            f"Why the candidate targets them: {company.get('why_target', '')}"
        ),
    ]
    if original:
        parts.append(
            "ORIGINAL EMAIL:\n"
            f"Subject: {original.get('subject', '')}\n\n{original.get('body', '')}"
        )
    return "\n\n".join(parts)


def _resolve_leftover_placeholders(text: str, contact: dict, company: dict) -> str:
    """Belt-and-braces: if the model still emitted mail-merge fields, resolve them."""
    replacements = {
        "{{First Name}}": contact.get("first_name", ""),
        "{{FirstName}}": contact.get("first_name", ""),
        "{{Company}}": company.get("name", ""),
        "{{Hook}}": contact.get("hook", ""),
    }
    for needle, value in replacements.items():
        text = text.replace(needle, value)
    return text


def draft(profile: dict, contact: dict, company: dict,
          version: str, original: dict | None = None) -> dict | None:
    """Returns {"subject": ..., "body": ...} or None on failure."""
    if version not in TEMPLATES:
        raise ValueError(f"version must be one of {sorted(TEMPLATES)}")
    if not config.GEMINI_API_KEY:
        log.error("GEMINI_API_KEY not set — cannot draft")
        return None
    url = config.GEMINI_URL.format(model=config.GEMINI_MODEL, key=config.GEMINI_API_KEY)
    body = {
        "contents": [{"parts": [{"text": build_prompt(profile, contact, company, version, original)}]}],
        "generationConfig": {
            "temperature": 0.7,  # emails need voice; scoring runs at 0.2
            "responseMimeType": "application/json",
        },
    }
    try:
        r = httpx.post(url, json=body, timeout=60)
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(text)
        subject = str(data.get("subject", "")).strip()
        email_body = str(data.get("body", "")).strip()
        if not subject or not email_body:
            log.warning("draft came back empty for contact %s", contact.get("first_name"))
            return None
        subject = _resolve_leftover_placeholders(subject, contact, company)
        email_body = _resolve_leftover_placeholders(email_body, contact, company)
        if len(email_body.split()) > 180:
            log.warning("draft for %s is long (%d words) — review before sending",
                        contact.get("first_name"), len(email_body.split()))
        return {"subject": subject, "body": email_body}
    except Exception as e:  # noqa: BLE001 — a failed draft must not 500 the whole flow upstream
        log.warning("drafting failed for contact %s @ %s: %s",
                    contact.get("first_name"), company.get("name"), e)
        return None
