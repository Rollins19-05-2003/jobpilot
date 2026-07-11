"""Job storage: SQLAlchemy models + dedup. SQLite locally, Postgres in prod."""
import hashlib
from datetime import datetime, timezone

from sqlalchemy import (JSON, Column, DateTime, Integer, String, Text,
                        create_engine)
from sqlalchemy.orm import declarative_base, sessionmaker

from . import config

engine = create_engine(config.DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)
Base = declarative_base()

# Pipeline statuses, in order
STATUSES = ["found", "shortlisted", "applied", "replied", "interview", "offer", "rejected", "skipped"]


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
