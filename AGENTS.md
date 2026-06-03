# CV-Job Match Agent — Agent Rules

This file is the operating manual for any AI coding agent working in this
repository (Codex CLI, Claude Code, Cursor, etc.). Read it before touching
code, answering codebase questions, or proposing architecture.

---

## Project Context (Sane Defaults — Confirm With User Before Scaffolding)

The product is a web dashboard where a candidate uploads a CV, picks job
providers and vacancies, and the system auto-tailors the CV per vacancy and
manages the apply queue with honest status tracking.

Suggested defaults (each requires explicit user confirmation per Rule 15
before being scaffolded):

- **Language**: Python 3.10+
- **Backend**: FastAPI (async, fits LLM + scrape workloads, OpenAPI built-in)
  — alternatives: Flask, Django
- **Frontend**: Jinja2 + HTMX (server-rendered, fewer moving parts)
  — alternative: React/Next.js
- **Database**: SQLite (dev) → Postgres (prod), via SQLAlchemy + Alembic
- **Queue / scheduler**: APScheduler (in-process, simple)
  — alternative: Celery + Redis
- **LLM**: Fireworks AI (DeepSeek V3.2 / Kimi K2.5 — pick per task type)
- **PDF parsing**: pypdf or pdfplumber
- **Scraping**: httpx + selectolax for static HTML, playwright for JS-heavy

---

## Rule 1: Prime Directive — Do Not Get The User Banned

The highest-priority rule in this project is to protect the user's accounts,
reputation, and job-search credibility.

- Do not scrape, automate, auto-apply, or simulate user actions on LinkedIn,
  Indeed, Glassdoor, or similar platforms when their Terms of Service prohibit it.
- LinkedIn automation is disabled by default. Use only official/approved APIs
  or partner programs.
- Indeed automation is disabled by default unless using official partner APIs
  such as Indeed Apply.
- Never build stealth scraping, captcha bypassing, browser fingerprint evasion,
  fake-user behavior, or aggressive retry logic.
- If a provider forbids automation, stop and warn the user clearly before
  implementing anything.
- If the user explicitly accepts risk, dangerous integrations still remain
  disabled by default and require explicit opt-in per provider.

## Rule 2: CV Truthfulness Is Non-Negotiable

- Never invent skills, titles, employers, dates, responsibilities,
  certifications, education, awards, publications, or metrics.
- Tailored CV output may only reorder, rephrase, or emphasize facts already
  present in the source CV.
- If a job requires a skill that is not in the CV, mark it as a gap. Do not
  add it to the CV.
- If support for a claim is uncertain, remove the claim or show the exact
  source quote for user review.
- Accuracy is more important than making the CV sound impressive.

## Rule 3: Every CV Claim Must Be Traceable

- Every tailored-CV claim must trace back to explicit text in the source CV
  or a truth-preserving transformation of it.
- Every job-posting claim in a gap report must trace back to scraped job text.
- No source means no inclusion.
- After generating a tailored CV, re-read every line and remove anything that
  is unsupported or unclear.

## Rule 4: Parse CVs Conservatively

- CV PDFs are messy: columns swap, bullets break, dates merge with company names.
- Always show parsed CV text to the user before treating it as the trusted source.
- Never silently "fix" parsed CV text with an LLM.
- If parsing looks wrong, ask the user to approve corrections before tailoring.

## Rule 5: Codebase Questions — Read First, Never Guess

When the user asks how the system works, whether something is implemented, or
what a route/model/provider does:

- Read the actual source files before answering.
- Use search first if the relevant file is unclear.
- State exact file and line number for every claim about code behavior.
- If something is not present, say `NOT FOUND in codebase`.
- Never answer from memory or prior context when the codebase can be checked.

## Rule 6: Verify Before Stating, And Be Honest About Partial Work

- Run the code, read the file, or check the output before saying behavior is correct.
- Do not say "I'm sure", "this works", "confirmed", "that's expected", or
  equivalent phrases without a preceding tool check that proves it.
- Wrong confident answers are worse than saying verification is needed.
- **If a task is partially complete, clearly state what's done and what's not.**
  Do not silently submit half-finished work or pretend a TODO is finished.

## Rule 7: No Silent Failures

- If a scrape fails, say `scrape failed`; do not silently use stale cached data.
- If LLM JSON is malformed, log and surface the error; do not replace it with
  empty defaults.
- If a provider rate-limits us, back off; do not burn retries.
- If an application submission fails, mark it `failed` with the actual error.

## Rule 8: Captcha Means Manual Intervention

- Do not bypass, solve, outsource, or evade captchas.
- Detect captcha pages using provider-specific DOM markers where possible.
- Mark the application as `manual_intervention_required`.
- Surface the captcha to the user and stop automated submission for that row.
- Do not put the row back into blind retry loops.

## Rule 9: Job Source Safety (Source Hierarchy)

Trustworthiness ranking — auto-apply allowed only at tier 1–2 unless the user
explicitly approves a lower tier per row:

1. Company career pages (greenhouse.io, lever.co, ashbyhq.com,
   workable.com, smartrecruiters.com, workday tenants) — highest
2. Official ATS APIs (Greenhouse Job Board API, Lever postings API,
   Ashby public API)
3. LinkedIn / Indeed / Glassdoor (read-only listing data, no auto-apply)
4. Recruiter-posted boards / aggregators — frequently stale or fake
5. Email lists, Telegram channels — verify against tier 1–2 first

Flag suspicious, stale, fake, spammy, or phishing-looking postings instead of
applying. Never auto-apply based only on a tier 3+ listing without confirming
the role exists on a tier 1–2 source.

## Rule 10: Job Postings Expire Silently

- Most job boards do not push a reliable "closed" signal.
- A scraped job can be 30+ days old while the role is already gone.
- Re-fetch the job posting before applying.
- If the page returns 404, 410, "no longer available", or equivalent
  closed-role text, mark it `expired` and do not submit.

## Rule 11: Application Tracking Must Be Honest

- `sent` means the provider accepted the submission and returned a clear
  confirmation.
- `failed` means failed. Do not record failures as `sent`.
- `response_received` means a real recruiter/ATS response, not a generic receipt.
- Never retry an already-sent application automatically.
- Default auto-apply must be OFF.

## Rule 12: Rate Limits And Anti-Spam

- Default cap: no more than 5 auto-apply submissions per candidate per day.
- Default per-company cap: no more than 1 application per company per 90 days.
- Respect provider rate limits with a safety buffer.
- Any apply queue must require explicit user confirmation unless the user has
  intentionally enabled auto-send.

## Rule 13: Track LLM Cost From Day One

- LLM cost will dominate at scale.
- Track cost per user and per tailoring run from day one.
- Cache gap analysis by `(CV-hash, job-URL)` so repeated analysis of the same
  pair is not paid for twice.
- Do not re-run expensive LLM steps when source inputs have not changed.

## Rule 14: Candidate Data Protection

CVs contain sensitive PII (full name, address, phone, employment history).

- Do not log CV text in plaintext to shared storage (stdout, log files,
  third-party log aggregators, error trackers).
- **Encrypt CV content at rest in the database** (Fernet, age, or
  sqlite-encryption — NOT just relying on filesystem permissions).
- Keep API keys and secrets in `.env`, never in commits.
- Do not use real candidate data in test fixtures, examples, or seed data.
- **Right-to-delete must be a hard delete** — physically remove source CVs,
  tailored variants, application records, and cached LLM outputs. Do not
  just flag `is_deleted=true`.

## Rule 15: Ask Before Major Product Decisions

Stop and present options with pros/cons before choosing:

- backend/frontend architecture
- database choice
- queue/scheduler choice
- provider integration order
- scraping a provider with unclear or hostile Terms of Service
- auto-apply aggressiveness
- pricing, launch readiness, or feature scope

The user decides, not the agent.

## Rule 16: No Commit Or Push Without Approval

- Do not run `git commit` or `git push` without explicit user approval in the
  current message.
- Writing code, running tests, and staging files (`git add`) are allowed.
- Commit or push requires explicit approval every time.

## Rule 17: Never Store Secrets In Git

- API keys, OAuth tokens, passwords, real CVs, and application credentials go
  in `.env` or secure storage only.
- Verify `.env` is gitignored before the first commit.
- If a real secret is committed, rotate it immediately and scrub history with
  an appropriate history-rewrite tool (`git filter-repo` or BFG).

## Rule 18: SYSTEM_CRITICAL.md For Non-Obvious Fixes

- When a non-obvious fix lands, document it in `.claude/SYSTEM_CRITICAL.md`
  (or `.codex/SYSTEM_CRITICAL.md` if you prefer; the location is conventional,
  not enforced).
- Include what the bug was, why the fix works, and file/line references.
- Read this file at the start of every coding turn once it exists.
- This is for fixes future agents are likely to accidentally undo.

## Rule 19: Local Development Rules

- Use Python 3.10+.
- Always use `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on
  Unix-like systems. Never use global Python.
- (Test fixture rule lives in Rule 14.)

## Rule 20: No Emojis By Default

Do not use emojis in code, logs, docs, commit messages, or agent responses
unless the user explicitly asks for them.

