"""Ingestion from free, public ATS APIs (no keys, no scraping, no ToS drama).

Greenhouse: https://boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true
Lever:      https://api.lever.co/v0/postings/<slug>?mode=json
"""
import html
import logging
import re

import httpx

log = logging.getLogger("jobpilot.ingest")

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
LEVER_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"

TAG_RE = re.compile(r"<[^>]+>")


def _clean(raw_html: str) -> str:
    """Strip HTML tags/entities from a JD so we feed clean text to the LLM."""
    text = html.unescape(raw_html or "")
    text = TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _matches(title: str, location: str, targets: dict) -> bool:
    t, l = title.lower(), location.lower()
    title_ok = any(k in t for k in targets.get("keywords_title", [])) or not targets.get("keywords_title")
    loc_ok = any(k in l for k in targets.get("keywords_location", [])) or not targets.get("keywords_location")
    return title_ok and loc_ok


def fetch_greenhouse(slug: str, targets: dict, client: httpx.Client) -> list[dict]:
    out = []
    try:
        r = client.get(GREENHOUSE_URL.format(slug=slug), timeout=20)
        r.raise_for_status()
        for j in r.json().get("jobs", []):
            title = j.get("title", "")
            location = (j.get("location") or {}).get("name", "")
            if not _matches(title, location, targets):
                continue
            out.append({
                "source": "greenhouse",
                "company": slug.title(),
                "title": title,
                "location": location,
                "url": j.get("absolute_url", ""),
                "jd_text": _clean(j.get("content", "")),
            })
    except Exception as e:  # noqa: BLE001 — one bad board must not kill the run
        log.warning("greenhouse:%s failed: %s", slug, e)
    return out


def fetch_lever(slug: str, targets: dict, client: httpx.Client) -> list[dict]:
    out = []
    try:
        r = client.get(LEVER_URL.format(slug=slug), timeout=20)
        r.raise_for_status()
        for j in r.json():
            title = j.get("text", "")
            location = (j.get("categories") or {}).get("location", "") or ""
            if not _matches(title, location, targets):
                continue
            out.append({
                "source": "lever",
                "company": slug.title(),
                "title": title,
                "location": location,
                "url": j.get("hostedUrl", ""),
                "jd_text": _clean(j.get("descriptionPlain") or j.get("description", "")),
            })
    except Exception as e:  # noqa: BLE001
        log.warning("lever:%s failed: %s", slug, e)
    return out


def fetch_all(targets: dict) -> list[dict]:
    jobs: list[dict] = []
    with httpx.Client(headers={"User-Agent": "JobPilot/0.1"}) as client:
        for slug in targets.get("greenhouse", []):
            jobs.extend(fetch_greenhouse(slug, targets, client))
        for slug in targets.get("lever", []):
            jobs.extend(fetch_lever(slug, targets, client))
    log.info("fetched %d matching jobs", len(jobs))
    return jobs
