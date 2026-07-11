"""Test setup: point DATABASE_URL at a throwaway SQLite file BEFORE the app
imports config (config reads the env at import time)."""
import os
import tempfile

_db_path = os.path.join(tempfile.gettempdir(), "jobpilot_test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    """Fresh schema per test + a TestClient."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


FAKE_GEMINI_DRAFT = (
    '{"subject": "Backend engineer, GCP pipelines",'
    ' "body": "Hi {{First Name}}, saw {{Company}} is hiring for the payments team..."}'
)


class FakeResponse:
    def __init__(self, text: str):
        self._text = text

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"candidates": [{"content": {"parts": [{"text": self._text}]}}]}


@pytest.fixture()
def mock_gemini(monkeypatch):
    """Patch the drafter's Gemini call; returns a list capturing each prompt sent."""
    prompts: list[str] = []

    def fake_post(url, json=None, timeout=None):
        prompts.append(json["contents"][0]["parts"][0]["text"])
        return FakeResponse(FAKE_GEMINI_DRAFT)

    monkeypatch.setattr("app.config.GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("app.outreach.drafter.httpx.post", fake_post)
    return prompts
