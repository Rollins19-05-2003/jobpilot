"""Outreach Engine endpoints: tiered target companies + real-human contacts.

The subsystem is deliberately draft-only: JobPilot researches, drafts and
tracks, but a human presses Send. That keeps it inside every platform's ToS
and every mail provider's good graces.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import config, telegram
from ..db import (COMPANY_STATUSES, CONTACT_STATUSES, EMAIL_SOURCES, PERSONAS,
                  PRIORITIES, TEMPLATE_VERSIONS, Company, Contact,
                  OutreachDraft, SessionLocal)
from . import drafter

log = logging.getLogger("jobpilot.outreach")

router = APIRouter(tags=["outreach"])


# ---------------------------------------------------------------- companies

@router.post("/companies/seed")
def seed_companies() -> dict:
    """Load profile/companies.json into the DB. Idempotent — matches by name,
    never overwrites rows you have started working (status/notes survive)."""
    entries = config.load_companies()
    if not entries:
        raise HTTPException(400, "profile/companies.json missing or empty")
    seeded = skipped = 0
    with SessionLocal() as s:
        for e in entries:
            if s.query(Company).filter(Company.name == e["name"]).first():
                skipped += 1
                continue
            notes = "⚠️ verify company still exists / is hiring before outreach" if e.get("verify") else ""
            s.add(Company(
                name=e["name"], tier=e.get("tier"), tier_label=e.get("tier_label", ""),
                hq_location=e.get("hq_location", ""), why_target=e.get("why_target", ""),
                linkedin_people_url=e.get("linkedin_people_url", ""),
                careers_url=e.get("careers_url", ""),
                priority=e.get("priority", "med"), notes=notes,
            ))
            seeded += 1
        s.commit()
    return {"seeded": seeded, "skipped_existing": skipped, "total_in_file": len(entries)}


@router.get("/companies")
def list_companies(
    tier: int | None = Query(default=None, ge=1, le=5),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
) -> list[dict]:
    with SessionLocal() as s:
        q = s.query(Company)
        if tier:
            q = q.filter(Company.tier == tier)
        if status:
            q = q.filter(Company.status == status)
        if priority:
            q = q.filter(Company.priority == priority)
        return [c.as_dict() for c in q.order_by(Company.tier, Company.name).all()]


class CompanyUpdate(BaseModel):
    status: str | None = None
    priority: str | None = None
    notes: str | None = None


@router.patch("/companies/{company_id}")
def update_company(company_id: int, body: CompanyUpdate) -> dict:
    if body.status and body.status not in COMPANY_STATUSES:
        raise HTTPException(400, f"status must be one of {COMPANY_STATUSES}")
    if body.priority and body.priority not in PRIORITIES:
        raise HTTPException(400, f"priority must be one of {PRIORITIES}")
    with SessionLocal() as s:
        company = s.get(Company, company_id)
        if not company:
            raise HTTPException(404, "company not found")
        for field in ("status", "priority", "notes"):
            value = getattr(body, field)
            if value is not None:
                setattr(company, field, value)
        s.commit()
        return company.as_dict()


# ----------------------------------------------------------------- contacts

class ContactIn(BaseModel):
    company_id: int | None = None
    company: str | None = None          # convenience: resolve by name instead
    first_name: str
    last_name: str = ""
    role_title: str = ""
    linkedin_url: str = ""
    email: str = ""
    email_source: str = "manual"
    email_verified: bool = False
    persona: str = "recruiter"
    hook: str = ""
    notes: str = ""


@router.post("/contacts")
def create_contact(body: ContactIn) -> dict:
    if body.persona not in PERSONAS:
        raise HTTPException(400, f"persona must be one of {PERSONAS}")
    if body.email_source not in EMAIL_SOURCES:
        raise HTTPException(400, f"email_source must be one of {EMAIL_SOURCES}")
    with SessionLocal() as s:
        company = None
        if body.company_id:
            company = s.get(Company, body.company_id)
        elif body.company:
            company = s.query(Company).filter(Company.name.ilike(body.company)).first()
        if not company:
            raise HTTPException(404, "company not found — pass a valid company_id or company name (seed companies first)")
        contact = Contact(
            company_id=company.id, first_name=body.first_name, last_name=body.last_name,
            role_title=body.role_title, linkedin_url=body.linkedin_url,
            email=body.email, email_source=body.email_source,
            email_verified=body.email_verified, persona=body.persona,
            hook=body.hook, notes=body.notes,
        )
        s.add(contact)
        if company.status == "not_started":
            company.status = "researching"
        s.commit()
        return contact.as_dict()


@router.get("/contacts")
def list_contacts(
    status: str | None = Query(default=None),
    company_id: int | None = Query(default=None),
    persona: str | None = Query(default=None),
) -> list[dict]:
    with SessionLocal() as s:
        q = s.query(Contact)
        if status:
            q = q.filter(Contact.status == status)
        if company_id:
            q = q.filter(Contact.company_id == company_id)
        if persona:
            q = q.filter(Contact.persona == persona)
        return [c.as_dict() for c in q.order_by(Contact.created_at.desc()).limit(500).all()]


class ContactUpdate(BaseModel):
    status: str | None = None
    email: str | None = None
    email_source: str | None = None
    email_verified: bool | None = None
    hook: str | None = None
    outcome: str | None = None
    notes: str | None = None
    follow_up_sent: bool | None = None


@router.patch("/contacts/{contact_id}")
def update_contact(contact_id: int, body: ContactUpdate) -> dict:
    if body.status and body.status not in CONTACT_STATUSES:
        raise HTTPException(400, f"status must be one of {CONTACT_STATUSES}")
    if body.email_source and body.email_source not in EMAIL_SOURCES:
        raise HTTPException(400, f"email_source must be one of {EMAIL_SOURCES}")
    with SessionLocal() as s:
        contact = s.get(Contact, contact_id)
        if not contact:
            raise HTTPException(404, "contact not found")
        for field in ("status", "email", "email_source", "email_verified",
                      "hook", "outcome", "notes", "follow_up_sent"):
            value = getattr(body, field)
            if value is not None:
                setattr(contact, field, value)
        now = datetime.now(timezone.utc)
        # Stamp the clock the moment you mark a contact sent — follow-up
        # discipline depends on date_sent being reliable.
        if body.status == "sent" and contact.date_sent is None:
            contact.date_sent = now
        if body.follow_up_sent and contact.follow_up_date is None:
            contact.follow_up_date = now
        if body.status == "sent" and contact.company and contact.company.status in ("not_started", "researching"):
            contact.company.status = "outreaching"
        s.commit()
        return contact.as_dict()


# ------------------------------------------------------------------- drafts

@router.post("/outreach/draft/{contact_id}")
def draft_outreach(contact_id: int, version: str | None = Query(default=None)) -> dict:
    """Generate an outreach draft for a contact. version=A|B|followup;
    if omitted, picked from persona (eng_manager -> B, everyone else -> A).
    Drafts are stored and returned — sending is always manual."""
    with SessionLocal() as s:
        contact = s.get(Contact, contact_id)
        if not contact:
            raise HTTPException(404, "contact not found")
        if not (contact.hook or "").strip():
            raise HTTPException(
                400,
                "contact has no hook — add one specific line about them/their team first "
                "(PATCH /contacts/{id}). Hook-less emails are generic spam and burn contacts.",
            )
        if version is None:
            version = "B" if contact.persona == "eng_manager" else "A"
        if version not in TEMPLATE_VERSIONS:
            raise HTTPException(400, f"version must be one of {TEMPLATE_VERSIONS}")

        original = None
        if version == "followup":
            last = (
                s.query(OutreachDraft)
                .filter(OutreachDraft.contact_id == contact_id,
                        OutreachDraft.template_version != "followup")
                .order_by(OutreachDraft.generated_at.desc()).first()
            )
            if not last:
                raise HTTPException(400, "no original draft to follow up on — draft version A or B first")
            original = {"subject": last.subject, "body": last.body}

        company = contact.company.as_dict() if contact.company else {}
        result = drafter.draft(
            profile=config.load_profile(), contact=contact.as_dict(),
            company=company, version=version, original=original,
        )
        if result is None:
            raise HTTPException(502, "drafting failed — check GEMINI_API_KEY and API logs")

        row = OutreachDraft(
            contact_id=contact_id, template_version=version,
            subject=result["subject"], body=result["body"],
        )
        s.add(row)
        if contact.status == "identified":
            contact.status = "drafted"
        s.commit()
        return row.as_dict()


@router.get("/outreach/drafts")
def list_drafts(contact_id: int | None = Query(default=None)) -> list[dict]:
    with SessionLocal() as s:
        q = s.query(OutreachDraft)
        if contact_id:
            q = q.filter(OutreachDraft.contact_id == contact_id)
        return [d.as_dict() for d in q.order_by(OutreachDraft.generated_at.desc()).limit(200).all()]


class DraftUpdate(BaseModel):
    subject: str | None = None
    body: str | None = None


@router.patch("/outreach/drafts/{draft_id}")
def update_draft(draft_id: int, body: DraftUpdate) -> dict:
    """Save your manual edits back so the tracker/export reflects what you actually sent."""
    with SessionLocal() as s:
        row = s.get(OutreachDraft, draft_id)
        if not row:
            raise HTTPException(404, "draft not found")
        if body.subject is not None:
            row.subject = body.subject
        if body.body is not None:
            row.body = body.body
        row.edited = True
        s.commit()
        return row.as_dict()


# ----------------------------------------------- follow-up discipline + stats

def due_followups(session) -> list[Contact]:
    """Sent (or opened) >= FOLLOW_UP_AFTER_DAYS days ago, no reply, no follow-up yet.
    'opened' counts too — an opened-but-unanswered email is prime follow-up material."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.FOLLOW_UP_AFTER_DAYS)
    return (
        session.query(Contact)
        .filter(
            Contact.status.in_(["sent", "opened"]),
            Contact.follow_up_sent.is_(False),
            Contact.date_sent.isnot(None),
            Contact.date_sent <= cutoff,
        )
        .order_by(Contact.date_sent)
        .all()
    )


@router.get("/outreach/followups-due")
def followups_due() -> list[dict]:
    with SessionLocal() as s:
        return [c.as_dict() for c in due_followups(s)]


@router.get("/outreach/stats")
def outreach_stats() -> dict:
    with SessionLocal() as s:
        total = s.query(Contact).count()
        sent = s.query(Contact).filter(Contact.date_sent.isnot(None)).count()
        follow_ups_sent = s.query(Contact).filter(Contact.follow_up_sent.is_(True)).count()
        replies = s.query(Contact).filter(Contact.status.in_(["replied", "meeting"])).count()
        meetings = s.query(Contact).filter(Contact.status == "meeting").count()
        by_status = {
            status: s.query(Contact).filter(Contact.status == status).count()
            for status in CONTACT_STATUSES
        }
        companies_touched = (
            s.query(Contact.company_id).filter(Contact.date_sent.isnot(None)).distinct().count()
        )
        stats = {
            "contacts_total": total,
            "sent": sent,
            "follow_ups_sent": follow_ups_sent,
            "replies": replies,
            "meetings": meetings,
            "reply_rate_pct": round(100 * replies / sent, 1) if sent else 0.0,
            "followups_due": len(due_followups(s)),
            "companies_touched": companies_touched,
            "by_status": by_status,
        }
    # The one rule that matters: volume without replies means the MESSAGE is
    # broken, not the market. Surface it loudly instead of letting sends pile up.
    if sent >= 30 and replies == 0:
        stats["advice"] = "0% reply rate after 30+ sends — STOP sending and rewrite your hook."
    return stats


@router.post("/outreach/weekly-review")
def weekly_review() -> dict:
    """Monday-morning Telegram summary — n8n hits this weekly."""
    stats = outreach_stats()
    text = telegram.build_weekly_review(stats)
    sent = telegram.send(text)
    return {"sent": sent, "stats": stats}
