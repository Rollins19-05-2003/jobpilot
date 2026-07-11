"""Ingestion from free, public ATS APIs (no keys, no scraping, no ToS drama).

Greenhouse:      https://boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true
Lever:           https://api.lever.co/v0/postings/<slug>?mode=json
Ashby:           https://api.ashbyhq.com/posting-api/job-board/<slug>
SmartRecruiters: https://api.smartrecruiters.com/v1/companies/<slug>/postings
Workable:        https://apply.workable.com/api/v1/widget/accounts/<slug>?details=true

Plus one keyed aggregator, JSearch (RapidAPI free tier, ~200 req/month) which
surfaces Google-for-Jobs results — including LinkedIn/Naukri/Indeed postings —
without scraping anyone. Runs only when RAPIDAPI_KEY is set, one request per
query per day, so ~6 queries stays inside the free tier.
"""
import html
import logging
import re

import httpx

from .. import config

log = logging.getLogger("jobpilot.ingest")

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
LEVER_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"
SMARTRECRUITERS_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
SMARTRECRUITERS_DETAIL_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings/{post_id}"
WORKABLE_URL = "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"
JSEARCH_URL = "https://jsearch.p.rapidapi.com/search"

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


def fetch_ashby(slug: str, targets: dict, client: httpx.Client) -> list[dict]:
    out = []
    try:
        r = client.get(ASHBY_URL.format(slug=slug), timeout=20)
        r.raise_for_status()
        for j in r.json().get("jobs", []):
            title = j.get("title", "")
            location = j.get("location", "") or ""
            if not _matches(title, location, targets):
                continue
            out.append({
                "source": "ashby",
                "company": slug.title(),
                "title": title,
                "location": location,
                "url": j.get("jobUrl") or j.get("applyUrl", ""),
                "jd_text": _clean(j.get("descriptionHtml", "")),
            })
    except Exception as e:  # noqa: BLE001
        log.warning("ashby:%s failed: %s", slug, e)
    return out


def fetch_smartrecruiters(slug: str, targets: dict, client: httpx.Client) -> list[dict]:
    """List postings, then fetch full JDs only for title/location matches —
    the list endpoint has no description, and per-posting calls add up."""
    out = []
    try:
        r = client.get(SMARTRECRUITERS_URL.format(slug=slug), params={"limit": 100}, timeout=20)
        r.raise_for_status()
        for j in r.json().get("content", [])[:100]:
            title = j.get("name", "")
            loc = j.get("location") or {}
            location = ", ".join(x for x in (loc.get("city"), loc.get("country")) if x)
            if not _matches(title, location, targets):
                continue
            jd_text = ""
            try:
                detail = client.get(
                    SMARTRECRUITERS_DETAIL_URL.format(slug=slug, post_id=j.get("id")), timeout=20
                )
                detail.raise_for_status()
                sections = (detail.json().get("jobAd") or {}).get("sections") or {}
                jd_text = _clean(" ".join(s.get("text", "") for s in sections.values() if isinstance(s, dict)))
            except Exception as e:  # noqa: BLE001 — a missing JD is fine, the job still counts
                log.warning("smartrecruiters:%s detail %s failed: %s", slug, j.get("id"), e)
            out.append({
                "source": "smartrecruiters",
                "company": j.get("company", {}).get("name") or slug.title(),
                "title": title,
                "location": location,
                "url": f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}",
                "jd_text": jd_text,
            })
    except Exception as e:  # noqa: BLE001
        log.warning("smartrecruiters:%s failed: %s", slug, e)
    return out


def fetch_workable(slug: str, targets: dict, client: httpx.Client) -> list[dict]:
    out = []
    try:
        r = client.get(WORKABLE_URL.format(slug=slug), timeout=20)
        r.raise_for_status()
        for j in r.json().get("jobs", []):
            title = j.get("title", "")
            location = ", ".join(x for x in (j.get("city"), j.get("country")) if x)
            if not _matches(title, location, targets):
                continue
            out.append({
                "source": "workable",
                "company": slug.title(),
                "title": title,
                "location": location,
                "url": j.get("url", ""),
                "jd_text": _clean(j.get("description", "")),
            })
    except Exception as e:  # noqa: BLE001
        log.warning("workable:%s failed: %s", slug, e)
    return out


def fetch_jsearch(query: str, targets: dict, client: httpx.Client) -> list[dict]:
    """Google-for-Jobs via JSearch (RapidAPI). Surfaces LinkedIn/Naukri/Indeed
    postings through an official API instead of scraping. Free tier is ~200
    requests/month — one page per query per day keeps us safely inside it."""
    out = []
    if not config.RAPIDAPI_KEY:
        return out
    try:
        r = client.get(
            JSEARCH_URL,
            params={"query": query, "num_pages": 1, "date_posted": "3days"},
            headers={
                "X-RapidAPI-Key": config.RAPIDAPI_KEY,
                "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
            },
            timeout=30,
        )
        r.raise_for_status()
        for j in r.json().get("data", []):
            title = j.get("job_title", "")
            location = ", ".join(x for x in (j.get("job_city"), j.get("job_country")) if x)
            if not _matches(title, location, targets):
                continue
            out.append({
                "source": "jsearch",
                "company": j.get("employer_name", "") or "Unknown",
                "title": title,
                "location": location,
                "url": j.get("job_apply_link", ""),
                "jd_text": _clean(j.get("job_description", "")),
            })
    except Exception as e:  # noqa: BLE001
        log.warning("jsearch:%r failed: %s", query, e)
    return out


def fetch_all(targets: dict) -> list[dict]:
    jobs: list[dict] = []
    with httpx.Client(headers={"User-Agent": "JobPilot/0.1"}) as client:
        for slug in targets.get("greenhouse", []):
            jobs.extend(fetch_greenhouse(slug, targets, client))
        for slug in targets.get("lever", []):
            jobs.extend(fetch_lever(slug, targets, client))
        for slug in targets.get("ashby", []):
            jobs.extend(fetch_ashby(slug, targets, client))
        for slug in targets.get("smartrecruiters", []):
            jobs.extend(fetch_smartrecruiters(slug, targets, client))
        for slug in targets.get("workable", []):
            jobs.extend(fetch_workable(slug, targets, client))
        for query in targets.get("jsearch_queries", []):
            jobs.extend(fetch_jsearch(query, targets, client))
    log.info("fetched %d matching jobs", len(jobs))
    return jobs
