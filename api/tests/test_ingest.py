import httpx

from app.ingest import sources

TARGETS = {"keywords_title": ["backend", "engineer"], "keywords_location": ["bangalore", "remote"]}


def _client_returning(payload: dict) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))


def test_ashby_parses_and_filters():
    payload = {"jobs": [
        {"title": "Backend Engineer", "location": "Remote", "jobUrl": "https://x/1",
         "descriptionHtml": "<p>Build &amp; scale</p>"},
        {"title": "Sales Lead", "location": "Remote", "jobUrl": "https://x/2", "descriptionHtml": ""},
        {"title": "Backend Engineer", "location": "New York", "jobUrl": "https://x/3", "descriptionHtml": ""},
    ]}
    with _client_returning(payload) as c:
        jobs = sources.fetch_ashby("acme", TARGETS, c)
    assert len(jobs) == 1
    assert jobs[0]["source"] == "ashby"
    assert jobs[0]["jd_text"] == "Build & scale"  # HTML stripped, entity unescaped


def test_workable_parses_city_country():
    payload = {"jobs": [{"title": "Backend Engineer", "city": "Bangalore", "country": "India",
                         "url": "https://x", "description": "<b>go</b>"}]}
    with _client_returning(payload) as c:
        jobs = sources.fetch_workable("acme", TARGETS, c)
    assert jobs[0]["location"] == "Bangalore, India"


def test_jsearch_skipped_without_api_key(monkeypatch):
    monkeypatch.setattr("app.config.RAPIDAPI_KEY", "")
    with _client_returning({"data": [{"job_title": "Backend Engineer"}]}) as c:
        assert sources.fetch_jsearch("backend bangalore", TARGETS, c) == []


def test_jsearch_parses_when_keyed(monkeypatch):
    monkeypatch.setattr("app.config.RAPIDAPI_KEY", "k")
    payload = {"data": [{"job_title": "Backend Engineer", "employer_name": "Naukri Co",
                         "job_city": "Bangalore", "job_country": "IN",
                         "job_apply_link": "https://x", "job_description": "desc"}]}
    with _client_returning(payload) as c:
        jobs = sources.fetch_jsearch("backend bangalore", TARGETS, c)
    assert jobs[0]["company"] == "Naukri Co"
    assert jobs[0]["source"] == "jsearch"


def test_one_bad_board_does_not_kill_the_run():
    def boom(request):
        raise httpx.ConnectError("down")
    with httpx.Client(transport=httpx.MockTransport(boom)) as c:
        assert sources.fetch_ashby("acme", TARGETS, c) == []
        assert sources.fetch_workable("acme", TARGETS, c) == []
        assert sources.fetch_smartrecruiters("acme", TARGETS, c) == []
