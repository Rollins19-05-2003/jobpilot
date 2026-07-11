"""Storage: SQLAlchemy models + dedup. SQLite locally, Postgres in prod.

Tables: jobs (Phase 1), companies / contacts / outreach_drafts (Outreach Engine).
No Alembic — new tables/columns appear via Base.metadata.create_all on startup;
for column changes on an existing SQLite file, delete data/jobpilot.db and re-run.
"""
import hashlib
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, Column, DateTime, ForeignKey, Integer,
                        String, Text, create_engine)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from . import config

engine = create_engine(config.DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)
Base = declarative_base()

# Pipeline statuses, in order
STATUSES = ["found", "shortlisted", "applied", "replied", "interview", "offer", "rejected", "skipped"]

# Outreach enums (validated at the API layer, stored as plain strings)
COMPANY_STATUSES = ["not_started", "researching", "outreaching", "paused", "done"]
PRIORITIES = ["high", "med", "low"]
CONTACT_STATUSES = ["identified", "drafted", "sent", "opened", "replied", "meeting", "closed"]
PERSONAS = ["recruiter", "ta", "eng_manager"]
EMAIL_SOURCES = ["hunter", "snov", "rocketreach", "apollo", "findthatlead", "manual"]
TEMPLATE_VERSIONS = ["A", "B", "followup"]


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    dedup_hash = Column(String(64), unique=True, index=True, nullable=False)
    source = Column(String(32))            # greenhouse | lever | manual
    company = Column(String(128))
    title = Column(String(256))
    location = Column(String(256))
    url = Column(String(512))
    jd_text = Column(Text)

    # Scoring results (filled by Gemini)
    fit_score = Column(Integer, nullable=True)
    verdict = Column(String(512), nullable=True)
    matched_skills = Column(JSON, nullable=True)
    gaps = Column(JSON, nullable=True)
    pitch_line = Column(Text, nullable=True)

    status = Column(String(32), default="found", index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    scored_at = Column(DateTime, nullable=True)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "company": self.company,
            "title": self.title,
            "location": self.location,
            "url": self.url,
            "fit_score": self.fit_score,
            "verdict": self.verdict,
            "matched_skills": self.matched_skills,
            "gaps": self.gaps,
            "pitch_line": self.pitch_line,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), unique=True, index=True, nullable=False)
    tier = Column(Integer)                     # 1..5
    tier_label = Column(String(64))            # "Big Tech", "Unicorn", ...
    hq_location = Column(String(128))
    why_target = Column(Text)                  # one specific line, tied to my stack
    linkedin_people_url = Column(String(512))  # pre-built recruiter people-search
    careers_url = Column(String(512))
    priority = Column(String(8), default="med")            # high | med | low
    status = Column(String(32), default="not_started", index=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    contacts = relationship("Contact", back_populates="company")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "tier": self.tier,
            "tier_label": self.tier_label,
            "hq_location": self.hq_location,
            "why_target": self.why_target,
            "linkedin_people_url": self.linkedin_people_url,
            "careers_url": self.careers_url,
            "priority": self.priority,
            "status": self.status,
            "notes": self.notes,
            "contacts": len(self.contacts),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True, nullable=False)
    first_name = Column(String(64), nullable=False)
    last_name = Column(String(64), default="")
    role_title = Column(String(128), default="")
    linkedin_url = Column(String(512), default="")
    email = Column(String(256), default="")
    email_source = Column(String(32), default="manual")   # hunter | snov | ... | manual
    email_verified = Column(Boolean, default=False)
    persona = Column(String(32), default="recruiter")     # recruiter | ta | eng_manager
    hook = Column(Text, default="")                       # ONE specific line about them/their team
    status = Column(String(32), default="identified", index=True)
    date_sent = Column(DateTime, nullable=True)
    follow_up_sent = Column(Boolean, default=False)
    follow_up_date = Column(DateTime, nullable=True)
    outcome = Column(Text, default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    company = relationship("Company", back_populates="contacts")
    drafts = relationship("OutreachDraft", back_populates="contact")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "company_id": self.company_id,
            "company": self.company.name if self.company else None,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "role_title": self.role_title,
            "linkedin_url": self.linkedin_url,
            "email": self.email,
            "email_source": self.email_source,
            "email_verified": self.email_verified,
            "persona": self.persona,
            "hook": self.hook,
            "status": self.status,
            "date_sent": self.date_sent.isoformat() if self.date_sent else None,
            "follow_up_sent": self.follow_up_sent,
            "follow_up_date": self.follow_up_date.isoformat() if self.follow_up_date else None,
            "outcome": self.outcome,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class OutreachDraft(Base):
    __tablename__ = "outreach_drafts"

    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), index=True, nullable=False)
    template_version = Column(String(16))      # A | B | followup
    subject = Column(String(256))
    body = Column(Text)
    generated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    edited = Column(Boolean, default=False)

    contact = relationship("Contact", back_populates="drafts")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "contact_id": self.contact_id,
            "template_version": self.template_version,
            "subject": self.subject,
            "body": self.body,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "edited": self.edited,
        }


def init_db() -> None:
    Base.metadata.create_all(engine)


def make_hash(company: str, title: str, location: str) -> str:
    raw = f"{company}|{title}|{location}".lower().strip()
    return hashlib.sha256(raw.encode()).hexdigest()


def upsert_job(session, *, source, company, title, location, url, jd_text) -> Job | None:
    """Insert a job if unseen. Returns the new Job, or None if duplicate."""
    h = make_hash(company, title, location)
    if session.query(Job).filter_by(dedup_hash=h).first():
        return None
    job = Job(
        dedup_hash=h, source=source, company=company, title=title,
        location=location, url=url, jd_text=jd_text[:20000],
    )
    session.add(job)
    session.flush()  # make it visible to dedup checks within the same batch
    return job
