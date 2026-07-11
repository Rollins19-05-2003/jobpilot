from app.db import SessionLocal, make_hash, upsert_job


def test_same_job_is_deduped_across_sources(client):
    with SessionLocal() as s:
        first = upsert_job(s, source="greenhouse", company="Acme", title="Backend Engineer",
                           location="Bangalore", url="u1", jd_text="jd")
        dupe = upsert_job(s, source="lever", company="Acme", title="Backend Engineer",
                          location="Bangalore", url="u2", jd_text="different jd")
        s.commit()
    assert first is not None
    assert dupe is None


def test_dedup_hash_ignores_case_and_whitespace():
    assert make_hash("Acme Corp", "SDE-1", "Bangalore") == make_hash(" acme corp", "sde-1", "BANGALORE ")


def test_different_location_is_a_different_job(client):
    with SessionLocal() as s:
        a = upsert_job(s, source="greenhouse", company="Acme", title="Backend Engineer",
                       location="Bangalore", url="u", jd_text="jd")
        b = upsert_job(s, source="greenhouse", company="Acme", title="Backend Engineer",
                       location="Pune", url="u", jd_text="jd")
        s.commit()
    assert a is not None and b is not None
