# 🛩️ JobPilot — Your AI Job-Hunt Copilot

Every morning at 8 AM, JobPilot scans the career boards of your target companies, scores every new opening against your resume with an LLM, and sends you a Telegram digest: **which roles to apply to today, why you fit, what your gaps are, and a ready-to-use pitch line.**

And when applying isn't enough, the **Outreach Engine** turns cold email into a tracked pipeline: 50 tiered target companies, real-human contacts with hooks, LLM-drafted personalized emails (A/B templates + follow-ups), follow-up discipline, weekly reply-rate reviews, and a styled Excel tracker generated from the live DB.

Built end-to-end at **Rs. 0/month**: self-hosted n8n + FastAPI + Gemini free tier + Telegram + free public ATS APIs.

## Architecture

```
n8n (cron)
   ├─ daily 8 AM ──► POST /pipeline/run
   │                   ├─► /ingest   Greenhouse · Lever · Ashby · SmartRecruiters
   │                   │             · Workable · JSearch* ──► dedup ──► DB
   │                   ├─► /score    Gemini 2.0 Flash (structured JSON) ──► fit %, gaps, pitch
   │                   └─► /digest   Telegram: today's roles + follow-ups due ☀️
   │
   └─ Monday 9 AM ──► POST /outreach/weekly-review ──► Telegram: sends, replies, reply-rate 📊

you (manually, ~30 min/day)
   └─ find contacts ──► POST /contacts (with a hook) ──► POST /outreach/draft/{id}
        ──► review, send from YOUR inbox ──► PATCH status=sent ──► follow-ups surface in 5 days
```

- **n8n** — orchestration (schedule, retries, observability)
- **FastAPI** — ingestion, scoring, outreach tracking, exports
- **Gemini Flash (free tier)** — JD-vs-profile scoring + outreach drafting, plain httpx REST
- **SQLite → Supabase Postgres** — jobs, companies, contacts, drafts; dedup hashing; status pipelines
- **Zero scraping** — official public JSON endpoints only. *JSearch (RapidAPI free tier, ~200 req/month) optionally adds Google-for-Jobs results — which include LinkedIn/Naukri/Indeed postings — through an API, not a scraper. Skipped unless `RAPIDAPI_KEY` is set.

## Quick start

```bash
cp .env.example .env        # fill in GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
docker compose up --build   # starts API (:8000) and n8n (:5678)
```

Then:
1. Open n8n at `http://localhost:5678` → import `n8n/daily_pipeline.json` **and** `n8n/weekly_outreach_review.json` → activate both.
2. Edit `profile/profile.json` (your resume, structured), `profile/targets.json` (board slugs + JSearch queries) and `profile/companies.json` (your 50 outreach targets).
3. Seed and test:

```bash
curl -X POST http://localhost:8000/companies/seed     # load the 50 target companies
curl -X POST http://localhost:8000/pipeline/run       # full daily run, right now
```

### Getting the free keys (5 minutes)
- **Gemini:** https://aistudio.google.com/apikey (free tier: 1,500 req/day)
- **Telegram:** message `@BotFather` → `/newbot` → copy token. Message your bot once, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `chat_id`.
- **JSearch (optional):** subscribe to the free tier at rapidapi.com → `RAPIDAPI_KEY`.

## API

### Jobs (Phase 1)
| Method | Route | What it does |
|---|---|---|
| POST | `/pipeline/run` | Full daily run: ingest → score → digest |
| POST | `/ingest` | Pull + dedup fresh jobs from all target boards |
| POST | `/score` | Gemini-score all unscored jobs |
| POST | `/digest` | Telegram briefing: top roles + outreach follow-ups due |
| GET | `/jobs?status=&min_score=` | Browse the pipeline |
| PATCH | `/jobs/{id}` | Move a job through the pipeline (`applied`, `replied`, ...) |

### Outreach Engine
| Method | Route | What it does |
|---|---|---|
| POST | `/companies/seed` | Load `profile/companies.json` (idempotent, never overwrites your edits) |
| GET | `/companies?tier=&status=&priority=` | Browse target companies |
| PATCH | `/companies/{id}` | Update status / priority / notes |
| POST | `/contacts` | Add a human (requires a company; hook strongly encouraged) |
| GET | `/contacts?status=&company_id=&persona=` | Browse contacts |
| PATCH | `/contacts/{id}` | Update status etc. — `status=sent` auto-stamps `date_sent` |
| POST | `/outreach/draft/{contact_id}?version=A\|B\|followup` | Gemini-draft an email (stored, returned, **never sent**) |
| GET | `/outreach/drafts?contact_id=` | Browse drafts |
| PATCH | `/outreach/drafts/{id}` | Save your manual edits (marks `edited`) |
| GET | `/outreach/followups-due` | Sent ≥5 days ago, no reply, no follow-up yet |
| GET | `/outreach/stats` | Sent / replies / reply-rate + the "rewrite your hook" alarm |
| POST | `/outreach/weekly-review` | Compute stats + send the Monday Telegram summary |
| GET | `/export/tracker.xlsx` | The full 4-tab styled workbook, fresh from the DB |

## The outreach workflow (30 min/day)

1. Read the Telegram digest — new roles + follow-ups due.
2. Apply to strong fits.
3. Pick 1–2 companies (`GET /companies?priority=high&status=not_started`); open their pre-built LinkedIn recruiter search.
4. Add 2–3 contacts **with a specific hook** — one line about *them* (their team, their JD, their blog post). The drafter refuses hook-less contacts by design.
5. Draft: `curl -X POST 'localhost:8000/outreach/draft/1'` — template A for recruiters/TA, B ("ask for advice, not a job") for eng managers, `?version=followup` after 5 quiet days.
6. Review, personalize, send **from your own inbox** 9–11 AM recipient time. Mark it: `curl -X PATCH localhost:8000/contacts/1 -H 'content-type: application/json' -d '{"status":"sent"}'`.
7. Reply came in? `{"status":"replied"}`. Follow-up went out? `{"follow_up_sent":true}`.
8. `curl -o tracker.xlsx localhost:8000/export/tracker.xlsx` whenever you want the spreadsheet view (README tab inside has the full playbook + free email-finder stack).

## Ethics & safety rails

- **Drafts only, forever.** There is deliberately no email-sending integration and none should be added. Every message is reviewed and sent by a human, from a human inbox, at human volume (≤10/day).
- **Zero scraping.** Only official public JSON APIs. LinkedIn/Naukri coverage comes via JSearch's licensed aggregation, not bots.
- **Respect free tiers.** `/score` caps its batch; JSearch runs ≤1 page per query per day; email finders (Hunter 25/mo, Snov 50/mo, RocketReach 5/mo) are listed with their limits in the tracker's README tab.
- **Never fabricate.** The drafter's prompt hard-bans inventing experience beyond `profile/profile.json`, and bans buzzwords while it's at it.

## Testing

```bash
cd api && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -q
```

Covers: dedup, drafter structure + placeholder resolution (Gemini mocked), hook enforcement, follow-up date logic, the 30-sends-no-replies alarm, xlsx structure/formula scan (plus a LibreOffice recalc test that auto-skips if `soffice` is absent), and the new ingest parsers (httpx MockTransport).

## Migrations (there aren't any)

Tables are created with `Base.metadata.create_all` on startup — new **tables** appear automatically. If a future change alters **columns** of an existing table, either `ALTER TABLE` by hand or (locally) delete `data/jobpilot.db` and re-run + re-seed. Alembic is overkill at this size.

## Roadmap

- [ ] Telegram `/apply` + `/sent` commands via webhook; Streamlit pipeline dashboard
- [ ] **Phase 4:** deploy — API on Cloud Run (free tier), n8n on a GCP e2-micro always-free VM, DB on Supabase; weekly analytics
- [ ] Model cascade: cheap model triages, stronger model deep-scores finalists
- [ ] Contact-finding assist: rank a company's public team pages for likely hiring managers

## Why this exists

I was spending 60–90 minutes a day manually checking job boards and judging fit. Now a pipeline does it before I wake up — and the part of job hunting that actually moves the needle (warm, specific outreach to real humans) has a system behind it instead of a guilt-ridden spreadsheet. Building the tool that runs your own life is the best kind of dogfooding.
