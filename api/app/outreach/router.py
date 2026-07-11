"""Outreach Engine endpoints: tiered target companies + real-human contacts.

The subsystem is deliberately draft-only: JobPilot researches, drafts and
tracks, but a human presses Send. That keeps it inside every platform's ToS
and every mail provider's good graces.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import config
from ..db import (COMPANY_STATUSES, CONTACT_STATUSES, EMAIL_SOURCES, PERSONAS,
                  PRIORITIES, Company, Contact, SessionLocal)

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
