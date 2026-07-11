# 🛩️ JobPilot — Your AI Job-Hunt Copilot

Every morning at 8 AM, JobPilot scans the career boards of your target companies, scores every new opening against your resume with an LLM, and sends you a Telegram digest: **which roles to apply to today, why you fit, what your gaps are, and a ready-to-use pitch line.**

Built end-to-end at **Rs. 0/month**: self-hosted n8n + FastAPI + Gemini free tier + Telegram + free public ATS APIs.

## Architecture

```
n8n (cron, 8 AM IST)
   │
   ├─► POST /ingest   ── Greenhouse & Lever public APIs ──► dedup ──► DB
   ├─► POST /score    ── Gemini 2.0 Flash (structured JSON) ──► fit %, gaps, pitch
   └─► POST /digest   ── Telegram Bot API ──► your phone ☀️
```

- **n8n** — orchestration (schedule, retries, observability)
- **FastAPI** — ingestion, scoring, pipeline-tracking API
- **Gemini Flash (free tier)** — recruiter-grade JD-vs-profile scoring with a strict rubric and structured JSON output
- **SQLite → Supabase Postgres** — jobs table with dedup hashing and a status pipeline (`found → shortlisted → applied → replied → interview → offer`)
- **Zero scraping** — only official public JSON endpoints (Greenhouse/Lever boards), so it never breaks and never violates ToS

## Quick start

```bash
cp .env.example .env        # fill in GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
docker compose up --build   # starts API (:8000) and n8n (:5678)
```

Then:
1. Open n8n at `http://localhost:5678` → import `n8n/daily_pipeline.json` → activate.
2. Edit `profile/profile.json` (your resume, structured) and `profile/targets.json` (company board slugs — find them in careers-page URLs: `boards.greenhouse.io/<slug>`, `jobs.lever.co/<slug>`).
3. Trigger a run manually to test: `curl -X POST http://localhost:8000/pipeline/run`

### Getting the free keys (5 minutes)
- **Gemini:** https://aistudio.google.com/apikey → create key (free tier: 1,500 req/day)
- **Telegram:** message `@BotFather` → `/newbot` → copy token. Message your bot once, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `chat_id`.

## API

| Method | Route | What it does |
|---|---|---|
| POST | `/pipeline/run` | Full daily run: ingest → score → digest |
| POST | `/ingest` | Pull + dedup fresh jobs from all target boards |
| POST | `/score` | Gemini-score all unscored jobs |
| POST | `/digest` | Send today's Telegram briefing |
| GET | `/jobs?status=&min_score=` | Browse the pipeline |
| PATCH | `/jobs/{id}` | Move a job through the pipeline (`applied`, `replied`, ...) |

## Roadmap

- [ ] **Phase 3:** auto-drafted outreach messages per strong-fit role; Telegram `/apply` commands via webhook; Streamlit pipeline dashboard
- [ ] **Phase 4:** deploy — API on Cloud Run (free tier), n8n on a GCP e2-micro always-free VM, DB on Supabase; weekly analytics ("applications sent, reply rate")
- [ ] Model cascade: cheap model triages, stronger model deep-scores finalists

## Why this exists

I was spending 60–90 minutes a day manually checking job boards and judging fit. Now a pipeline does it before I wake up. Building the tool that runs your own life is the best kind of dogfooding.
