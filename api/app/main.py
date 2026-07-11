"""JobPilot API — the brains. n8n calls these endpoints on a schedule.

Endpoints:
  POST /ingest          pull fresh jobs from all target boards (deduped)
  POST /score           score all unscored jobs with Gemini
  POST /digest          send today's Telegram digest
  POST /pipeline/run    ingest -> score -> digest in one call (n8n's main hook)
  GET  /jobs            list jobs (filter: ?status=&min_score=)
  PATCH /jobs/{id}      update status (shortlisted/applied/replied/...)
  GET  /health
"""
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from . import config, telegram
from .db import STATUSES, Contact, Job, SessionLocal, init_db, upsert_job
from .ingest.sources import fetch_all
from .outreach.router import router as outreach_router
from .scoring.engine import score_job

logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
log = logging.getLogger("jobpilot")

app = FastAPI(title="JobPilot", version="0.2.0")
app.include_router(outreach_router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "model": config.GEMINI_MODEL}


@app.post("/ingest")
def ingest() -> dict:
    targets = config.load_targets()
    fetched = fetch_all(targets)
    new = 0
    with SessionLocal() as s:
        for j in fetched:
            if upsert_job(s, **j):
                new += 1
        s.commit()
    return {"fetched": len(fetched), "new": new}


@app.post("/score")
def score(limit: int = 30) -> dict:
    """Score unscored jobs. `limit` keeps us well inside Gemini's free tier."""
    profile = config.load_profile()
    scored = failed = 0
    with SessionLocal() as s:
        pending = (
            s.query(Job).filter(Job.fit_score.is_(None), Job.status == "found")
            .order_by(Job.created_at.desc()).limit(limit).all()
        )
        for job in pending:
            result = score_job(profile, {
                "company": job.company, "title": job.title,
                "location": job.location, "jd_text": job.jd_text or "",
            })
            if result is None:
                failed += 1
                continue
            job.fit_score = result["fit_score"]
            job.verdict = result["verdict"]
            job.matched_skills = result["matched_skills"]
            job.gaps = result["gaps"]
            job.pitch_line = result["pitch_line"]
            job.scored_at = datetime.now(timezone.utc)
            if job.fit_score < config.MIN_FIT_TO_KEEP:
                job.status = "skipped"
            scored += 1
        s.commit()
    return {"scored": scored, "failed": failed}


@app.post("/digest")
def digest() -> dict:
    from .outreach.router import due_followups

    with SessionLocal() as s:
        today = (
            s.query(Job)
            .filter(Job.fit_score.isnot(None), Job.status == "found")
            .order_by(Job.fit_score.desc()).limit(8).all()
        )
        new_count = s.query(Job).filter(Job.status == "found").count()
        jobs = [j.as_dict() for j in today]
        followups = [c.as_dict() for c in due_followups(s)]
        replies_pending = s.query(Contact).filter(Contact.status == "replied").count()
    outreach = telegram.build_outreach_section(followups, replies_pending)
    text = telegram.build_digest(jobs, new_count, outreach)
    sent = telegram.send(text)
    return {"sent": sent, "jobs_in_digest": len(jobs), "followups_due": len(followups)}


@app.post("/pipeline/run")
def pipeline_run() -> dict:
    """One-shot daily run — this is what n8n (or Cloud Scheduler) hits."""
    i = ingest()
    sc = score()
    d = digest()
    return {"ingest": i, "score": sc, "digest": d}


@app.get("/jobs")
def list_jobs(
    status: str | None = Query(default=None),
    min_score: int = Query(default=0),
) -> list[dict]:
    with SessionLocal() as s:
        q = s.query(Job).filter((Job.fit_score >= min_score) | (Job.fit_score.is_(None)))
        if status:
            q = q.filter(Job.status == status)
        return [j.as_dict() for j in q.order_by(Job.fit_score.desc().nullslast()).limit(100)]


class StatusUpdate(BaseModel):
    status: str


@app.patch("/jobs/{job_id}")
def update_status(job_id: int, body: StatusUpdate) -> dict:
    if body.status not in STATUSES:
        raise HTTPException(400, f"status must be one of {STATUSES}")
    with SessionLocal() as s:
        job = s.get(Job, job_id)
        if not job:
            raise HTTPException(404, "job not found")
        job.status = body.status
        s.commit()
        return job.as_dict()
