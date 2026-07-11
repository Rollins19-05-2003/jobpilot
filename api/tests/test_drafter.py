from app.outreach import drafter

PROFILE = {"name": "Sourav Deb", "highlights": ["cut cost 83%"]}
CONTACT = {"first_name": "Priya", "role_title": "TA Partner", "persona": "recruiter",
           "hook": "hiring for the payments platform team"}
COMPANY = {"name": "Razorpay", "tier_label": "Unicorn", "hq_location": "Bangalore",
           "why_target": "payments-scale backend"}


def test_draft_returns_valid_structure_and_resolves_placeholders(client, mock_gemini):
    result = drafter.draft(PROFILE, CONTACT, COMPANY, version="A")
    assert set(result) == {"subject", "body"}
    assert result["subject"]
    assert "{{" not in result["body"]
    assert "Priya" in result["body"] and "Razorpay" in result["body"]


def test_draft_returns_none_without_api_key(client, monkeypatch):
    monkeypatch.setattr("app.config.GEMINI_API_KEY", "")
    assert drafter.draft(PROFILE, CONTACT, COMPANY, version="A") is None


def test_followup_prompt_includes_original(client, mock_gemini):
    drafter.draft(PROFILE, CONTACT, COMPANY, version="followup",
                  original={"subject": "orig subject", "body": "orig body"})
    assert "orig subject" in mock_gemini[-1]
    assert "ORIGINAL EMAIL" in mock_gemini[-1]


def _make_contact(client, hook="payments team is hiring"):
    client.post("/companies/seed")
    return client.post("/contacts", json={
        "company": "Razorpay", "first_name": "Priya", "persona": "recruiter", "hook": hook,
    }).json()["id"]


def test_draft_endpoint_stores_draft_and_advances_status(client, mock_gemini):
    cid = _make_contact(client)
    r = client.post(f"/outreach/draft/{cid}")
    assert r.status_code == 200
    body = r.json()
    assert body["template_version"] == "A"  # recruiter persona -> A
    assert body["subject"] and body["body"]
    assert client.get("/contacts").json()[0]["status"] == "drafted"
    assert len(client.get("/outreach/drafts").json()) == 1


def test_draft_endpoint_requires_hook(client, mock_gemini):
    cid = _make_contact(client, hook="")
    assert client.post(f"/outreach/draft/{cid}").status_code == 400


def test_followup_requires_an_original_draft(client, mock_gemini):
    cid = _make_contact(client)
    assert client.post(f"/outreach/draft/{cid}?version=followup").status_code == 400
    client.post(f"/outreach/draft/{cid}?version=A")
    assert client.post(f"/outreach/draft/{cid}?version=followup").status_code == 200
