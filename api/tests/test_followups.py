from datetime import datetime, timedelta, timezone

from app.db import Company, Contact, SessionLocal


def _sow(days_ago: int | None, status: str = "sent", follow_up_sent: bool = False,
         name: str = "C") -> None:
    """Insert a contact directly — faster than 2 API calls per row."""
    with SessionLocal() as s:
        company = s.query(Company).first()
        if not company:
            company = Company(name="TestCo", tier=4)
            s.add(company)
            s.flush()
        s.add(Contact(
            company_id=company.id, first_name=name, hook="x", status=status,
            follow_up_sent=follow_up_sent,
            date_sent=(datetime.now(timezone.utc) - timedelta(days=days_ago))
            if days_ago is not None else None,
        ))
        s.commit()


def test_followups_due_only_after_five_quiet_days(client):
    _sow(7, name="Due7")
    _sow(5, name="Due5")
    _sow(3, name="TooFresh")
    _sow(None, status="identified", name="NeverSent")
    _sow(8, status="replied", name="TheyReplied")
    _sow(9, follow_up_sent=True, name="AlreadyFollowedUp")
    due = client.get("/outreach/followups-due").json()
    assert sorted(c["first_name"] for c in due) == ["Due5", "Due7"]


def test_opened_but_unanswered_counts_as_due(client):
    _sow(6, status="opened", name="Opened")
    assert [c["first_name"] for c in client.get("/outreach/followups-due").json()] == ["Opened"]


def test_stats_reply_rate_and_hook_advice(client):
    for i in range(30):
        _sow(2, name=f"S{i}")
    stats = client.get("/outreach/stats").json()
    assert stats["sent"] == 30
    assert stats["reply_rate_pct"] == 0.0
    assert "rewrite" in stats["advice"]

    # one reply clears the alarm
    _sow(2, status="replied", name="R")
    stats = client.get("/outreach/stats").json()
    assert stats["replies"] == 1
    assert "advice" not in stats
    assert stats["reply_rate_pct"] == round(100 * 1 / 31, 1)


def test_no_advice_below_thirty_sends(client):
    for i in range(29):
        _sow(2, name=f"S{i}")
    assert "advice" not in client.get("/outreach/stats").json()


def test_digest_includes_outreach_section(client):
    _sow(6, name="Anita")
    r = client.post("/digest")
    assert r.status_code == 200
    assert r.json()["followups_due"] == 1
