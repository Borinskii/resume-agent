# CV-Job Match Agent - Resource Research

Research date: 2026-04-27

This document maps the external resources, APIs, libraries, and constraints that
matter for the first product decisions. It is not an architecture decision
record. Per Rule 15 in `AGENTS.md`, scaffolding still requires explicit user
confirmation.

## Executive Summary

- First safe provider targets should be official ATS/careers sources, not social
  job boards.
- LinkedIn, Indeed, and Glassdoor should remain disabled for automation unless
  official partner/API access is confirmed.
- The first implementation should separate read-only job discovery from apply
  submission. Submission has higher ToS, captcha, duplicate-apply, and PII risk.
- CV parsing must include a user-visible parsed-text review step before LLM use.
- LLM calls need cost tracking and `(CV-hash, job-URL)` caching from day one.

## Job Provider Research

| Provider/source | Use case | Current risk posture | Notes | Official source |
|---|---|---:|---|---|
| Greenhouse Job Board API | Read public jobs from company boards | Low for read-only | Good first candidate for job discovery. Company-specific boards expose public endpoints. Apply flow still needs separate handling. | [Greenhouse Job Board API](https://developers.greenhouse.io/job-board.html) |
| Lever Postings API | Read public postings | Low for read-only | Good first candidate. Designed for public postings and company job pages. | [Lever Postings API](https://github.com/lever/postings-api) |
| Ashby public postings/API | Read public job postings | Low/medium for read-only | Useful ATS target. Confirm exact endpoint behavior per company before implementation. | [Ashby API docs](https://developers.ashbyhq.com/) |
| Workable API | Jobs/applicant workflows for Workable accounts | Medium | Public careers pages exist, but API access and apply behavior may depend on account permissions. | [Workable API documentation](https://help.workable.com/hc/en-us/articles/115013356548-Workable-API-Documentation) |
| SmartRecruiters API | Jobs and candidate workflows | Medium | Viable ATS candidate, but submission flows and auth need provider-specific review. | [SmartRecruiters Developers](https://developers.smartrecruiters.com/) |
| Workday tenants | Company-specific careers pages | Medium/high | No universal simple public API for all tenants. JS-heavy and fragile. Use only with explicit user approval and manual-intervention handling. | [Workday developer resources](https://developer.workday.com/) |
| LinkedIn | Read-only reference at most | High | Automation/scraping/apply simulation should stay disabled unless official approved access exists. | [LinkedIn User Agreement](https://www.linkedin.com/legal/user-agreement), [LinkedIn API Terms](https://www.linkedin.com/legal/l/api-terms-of-use) |
| Indeed | Read-only reference at most | High | Direct scraping/auto-submit should stay disabled unless official partner API access is confirmed. | [Indeed Terms](https://www.indeed.com/legal), [Indeed Apply docs](https://docs.indeed.com/) |
| Glassdoor | Read-only reference at most | High | Treat as lower-trust listing source. Do not automate interactions without confirming allowed official access. | [Glassdoor Terms](https://www.glassdoor.com/about/terms.htm) |

## Provider Integration Order To Discuss

These are research-backed options, not final decisions.

1. Greenhouse first
   - Pros: straightforward public job board API, many companies use it, lower
     ToS risk for read-only discovery.
   - Cons: company-specific apply forms still vary.

2. Lever first
   - Pros: public postings API is simple and common.
   - Cons: similar apply-flow limitations; each company may customize questions.

3. Ashby / Workable / SmartRecruiters next
   - Pros: useful ATS coverage.
   - Cons: more provider-specific behavior to validate.

4. Workday later
   - Pros: common at large companies.
   - Cons: JS-heavy, tenant-specific, fragile, captcha/manual-intervention risk.

5. LinkedIn / Indeed / Glassdoor
   - Recommendation: keep automation disabled. Use only as manual/read-only
     reference sources unless official approved integration is available.

## Core Technical Resources

| Area | Candidate resources | Research notes | Official source |
|---|---|---|---|
| Backend API | FastAPI | Strong default for async scraping/LLM workflows and built-in OpenAPI docs. Requires user confirmation before scaffolding. | [FastAPI docs](https://fastapi.tiangolo.com/) |
| Server-rendered UI | Jinja2 + HTMX | Good fit for a dashboard with fewer moving parts. React/Next.js remains an option if product scope needs richer client state. | [Jinja docs](https://jinja.palletsprojects.com/), [HTMX docs](https://htmx.org/docs/) |
| Database ORM | SQLAlchemy | Good default for SQLite dev and Postgres prod with one ORM layer. | [SQLAlchemy docs](https://docs.sqlalchemy.org/) |
| Migrations | Alembic | Standard SQLAlchemy migration tool. | [Alembic docs](https://alembic.sqlalchemy.org/) |
| Scheduling | APScheduler | Good simple default for local/single-process scheduling. Celery + Redis should be discussed if horizontal scaling is needed. | [APScheduler docs](https://apscheduler.readthedocs.io/), [Celery docs](https://docs.celeryq.dev/) |
| HTTP client | httpx | Good default for async HTTP and explicit timeout/retry handling. | [HTTPX docs](https://www.python-httpx.org/) |
| HTML parsing | selectolax or BeautifulSoup | selectolax is fast for static HTML; BeautifulSoup is familiar and forgiving. | [selectolax project](https://github.com/rushter/selectolax), [Beautiful Soup docs](https://www.crummy.com/software/BeautifulSoup/bs4/doc/) |
| JS-heavy pages | Playwright | Use for rendering pages and captcha detection, not ToS evasion. | [Playwright Python docs](https://playwright.dev/python/) |
| PDF parsing | pypdf or pdfplumber | Must show parsed text to the user before trusting it. pdfplumber is often better for layout inspection; pypdf is lighter. | [pypdf docs](https://pypdf.readthedocs.io/), [pdfplumber project](https://github.com/jsvine/pdfplumber) |
| LLM provider | Fireworks AI | Use chat-completions style API. Re-check current model IDs and pricing before implementation. Track cost per user/run. | [Fireworks docs](https://docs.fireworks.ai/), [Fireworks pricing](https://fireworks.ai/pricing) |
| Secrets/config | `.env`, pydantic-settings | Keep secrets outside git. Use typed settings rather than reading environment variables ad hoc. | [pydantic-settings docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) |
| CV encryption | cryptography/Fernet or stronger app-level encryption | Rule 14 requires encryption at rest beyond filesystem permissions. Key management must be designed before storing real CVs. | [cryptography Fernet docs](https://cryptography.io/en/latest/fernet/) |

## Data And Safety Requirements To Build Around

- Store a source CV hash and job URL hash so cached analyses are keyed by stable
  source inputs without exposing raw CV text in logs.
- Keep parsed CV text reviewable by the user before any tailoring step.
- Keep provider capability flags explicit, for example:
  - `supports_read_jobs`
  - `supports_official_apply`
  - `requires_manual_apply`
  - `automation_disabled_by_policy`
- Keep application states strict:
  - `queued`
  - `manual_confirmation_required`
  - `manual_intervention_required`
  - `sent`
  - `failed`
  - `expired`
  - `response_received`
  - `no_response`
- Treat captcha, rate limits, closed jobs, malformed provider forms, and changed
  DOMs as first-class states, not exceptions to hide.

## Decisions Needed From User Before Scaffolding

1. Backend/UI shape:
   - FastAPI + Jinja2/HTMX
   - FastAPI + React/Next.js
   - other

2. First read-only provider:
   - Greenhouse
   - Lever
   - Ashby

3. Apply behavior for v1:
   - manual-only apply queue
   - semi-automatic apply with per-row confirmation
   - auto-send toggle, off by default

4. Storage/security baseline:
   - local-only encrypted SQLite prototype
   - Postgres-ready schema from day one

5. LLM model policy:
   - cheap model for extraction, stronger model for tailoring
   - one model for all tasks initially

## Re-Check Before Implementation

These sources and ToS documents can change. Before implementing a provider,
re-check:

- provider API docs
- provider Terms of Service
- rate limits
- auth requirements
- whether apply submission is officially supported
- captcha/manual-intervention behavior
- current Fireworks model IDs and pricing

