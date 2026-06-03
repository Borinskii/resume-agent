# CV/Resume Matching Criteria Research

Research date: 2026-04-27

This document defines a research-backed scoring model for matching a candidate
profile to a job posting. It also defines how the dashboard may accept extra
candidate sources such as GitHub and LinkedIn without violating the project
rules in `AGENTS.md`.

This is not an implementation decision. Any architecture, provider, or product
flow still needs explicit confirmation under Rule 15.

## Core Principle

The system should score evidence, not vibes.

Every match result should answer four questions:

1. What did the job require?
2. Where is the candidate evidence?
3. How strong is that evidence?
4. What should the candidate change in the CV, without inventing facts?

The dashboard should show both:

- `match_score`: how well the candidate appears to fit the job
- `confidence_score`: how well-supported the score is by source evidence

Low confidence must not be hidden behind a high match score.

## Source Hierarchy For Candidate Evidence

| Source | Use | Trust level | Notes |
|---|---|---:|---|
| User-approved parsed CV text | Primary CV tailoring source | Highest | Must be shown to user before use because PDF parsing can distort text. |
| User-entered profile facts | Candidate profile enrichment | High | Ask for structured fields and keep source timestamps. |
| Uploaded LinkedIn data export or profile PDF | Candidate profile enrichment | High after user approval | Safe alternative to scraping LinkedIn pages. Must be treated as sensitive PII. |
| Official LinkedIn API data | Candidate profile enrichment | High if officially approved | Use only permitted scopes and member consent. Do not scrape LinkedIn content outside APIs. |
| GitHub public API data | Technical evidence | Medium | Good supporting signal for engineering roles. Do not over-interpret repo activity as job experience. |
| Portfolio/personal website | Supporting evidence | Medium | Use only if user owns it or explicitly authorizes it. Respect robots/ToS. |
| Public LinkedIn URL only | Identity/reference pointer | Low | Do not scrape. A URL alone is not enough to extract claims. |

Important product rule: if GitHub or LinkedIn data reveals facts not present in
the original CV, the system may suggest adding them only after user approval.
The tailored CV must cite the approved source used for each added claim.

## Job Requirement Extraction

Parse every job posting into structured requirements:

| Requirement group | Examples | Matching behavior |
|---|---|---|
| Hard constraints | work authorization, location, remote/hybrid, required language, license, certification, degree, clearance | Can gate or sharply cap score if missing. |
| Role title and seniority | backend engineer, senior data analyst, staff ML engineer | Match title family and seniority separately. |
| Must-have technical skills | Python, FastAPI, Postgres, React, AWS | Highest weighted skill evidence. |
| Nice-to-have skills | Kubernetes, Terraform, GraphQL | Lower weight; should not dominate must-have gaps. |
| Responsibilities | build APIs, maintain ETL, lead incidents, write tests | Match against CV bullets/projects, not only keywords. |
| Domain knowledge | fintech, healthcare, recruiting, B2B SaaS | Evidence can come from employers, projects, or product context. |
| Scale and scope | team size, traffic, revenue, data volume, ownership level | Only match if explicit in source. Never infer missing metrics. |
| Education and credentials | CS degree, AWS cert, CPA, RN license | Treat strictly when listed as required. |
| Transversal skills | communication, teamwork, leadership, critical thinking | Require behavioral evidence, not a bare keyword. |

## Evidence Strength Levels

Use an evidence ladder for each requirement:

| Level | Meaning | Example |
|---:|---|---|
| 0 | Not found | Job requires Kubernetes; no source mentions it. |
| 1 | Keyword only | `Kubernetes` appears in a skills list with no context. |
| 2 | Contextual use | CV says candidate deployed services with Kubernetes. |
| 3 | Recent/professional use | Recent role includes Kubernetes in responsibilities. |
| 4 | Strong ownership/outcome | Candidate owned Kubernetes platform, incidents, migrations, or measurable outcomes, with source evidence. |

Do not treat Level 1 as equivalent to real experience. The report should
separate `mentioned` from `demonstrated`.

## Suggested Initial Score Dimensions

These weights are a starting point for discussion, not final product policy.

| Dimension | Weight | Notes |
|---|---:|---|
| Hard constraints | gate/cap | Missing legal/logistical requirements should cap or block fit. |
| Must-have skills | 25 | Exact or strongly evidenced matches matter most. |
| Responsibilities and task overlap | 20 | Compare job duties to CV bullets/projects. |
| Seniority and scope | 15 | Years, ownership, leadership, autonomy, system scale. |
| Domain and product context | 10 | Industry and problem-space overlap. |
| Tooling/platform depth and recency | 10 | Recent, contextual, repeated use beats old keyword mentions. |
| Education/certification/license | 7 | More important when legally or explicitly required. |
| Outcomes and impact evidence | 7 | Only source-backed metrics or outcomes. No generated metrics. |
| Transversal skills | 4 | Use NACE-style behavioral competencies where relevant. |
| Portfolio/GitHub support | 2 | Supporting signal, not a substitute for professional evidence. |

The score should also include:

- `hard_blockers`: requirements that prevent a safe recommendation
- `major_gaps`: important missing or weak requirements
- `hidden_strengths`: source-backed facts present in the candidate profile but
  under-emphasized in the CV
- `tailoring_actions`: concrete rewrite suggestions with source citations

## Confidence Score

Confidence should be separate from match quality.

Inputs that increase confidence:

- exact source quote exists for the candidate evidence
- exact source quote exists for the job requirement
- requirement is matched by normalized skill aliases or taxonomy IDs
- evidence is recent and contextual
- multiple independent user-approved sources agree

Inputs that reduce confidence:

- evidence comes only from a skills list
- evidence comes only from GitHub language statistics
- source text is parser-noisy
- job posting is stale, duplicated, or low-trust
- match relies on semantic similarity without exact evidence

## Skill Normalization And Taxonomies

Use structured taxonomies to reduce brittle keyword matching:

- O*NET: useful for occupations, tasks, skills, knowledge, abilities, work
  activities, education, job zones, and technology skills.
- ESCO: useful for multilingual skills/occupations and cross-border matching.
- NACE: useful for broad career readiness competencies such as communication,
  critical thinking, professionalism, teamwork, leadership, and technology.

Implementation guidance:

- Normalize aliases: `PostgreSQL` == `Postgres`; `JS` == `JavaScript`.
- Keep exact raw text and normalized concept separate.
- Track whether a match is exact, alias-based, taxonomy-related, or semantic.
- Never use a related skill to claim the exact skill.
  Example: `Docker` does not prove `Kubernetes`.

## GitHub Enrichment

The dashboard can accept a GitHub URL or username with explicit user consent.
Use the official GitHub REST API for public data.

Potentially useful signals:

- public profile basics: username, bio, public repos, public email if exposed
- repositories: name, description, topics, README, primary language
- language breakdown per repository
- recent public activity where available and rate-limit safe
- evidence of tests, docs, CI config, package manifests, examples, issues/PRs

Signals to avoid or downweight:

- stars and followers as a proxy for skill
- raw commit count as a proxy for seniority
- old toy repos as current professional ability
- private-work assumptions based on public repos
- employer or job-title inference from GitHub org membership

GitHub-derived skills should be classified as:

- `observed_in_code`: language/framework appears in repo code or manifests
- `observed_in_docs`: README or docs mention it
- `weak_signal`: language stats or repo topic only
- `user_confirmed`: user approved it for the candidate profile

Only `user_confirmed` facts should be eligible for generated CV content.

## LinkedIn Enrichment

LinkedIn needs special handling because account safety is a prime directive.

Allowed safe patterns:

- user uploads LinkedIn data export
- user uploads a LinkedIn profile PDF they generated
- user pastes profile sections manually
- official LinkedIn API access with proper scopes and member consent

Disallowed default pattern:

- user pastes a LinkedIn URL and the system scrapes the profile page

A LinkedIn URL can be stored as a pointer, but not scraped or used as an
evidence source by itself. If the product wants richer LinkedIn import, the
safe v1 is upload/paste, not scraping.

## Dashboard Views To Support This Model

Recommended dashboard sections:

1. Candidate sources
   - CV parsed text status: `needs_review`, `approved`, `parse_failed`
   - GitHub status: `not_connected`, `connected`, `rate_limited`, `failed`
   - LinkedIn status: `not_provided`, `manual_upload`, `official_api`, `url_only`

2. Job requirements matrix
   - requirement text from job
   - category and importance
   - candidate evidence quote
   - evidence source
   - evidence strength level
   - action: highlight, reword, gap, ask user, ignore

3. Match summary
   - match score
   - confidence score
   - hard blockers
   - major gaps
   - strongest matches

4. CV tailoring recommendations
   - exact CV section to edit
   - suggested wording
   - source quote that supports it
   - warning if the suggestion needs user confirmation

5. Profile enrichment suggestions
   - "GitHub suggests possible Python evidence in repo X"
   - "LinkedIn export includes certification Y"
   - "Approve adding this to canonical profile?"

## Data Model Notes

A future implementation should preserve source traceability:

- `candidate_sources`
  - type: `cv`, `manual`, `github`, `linkedin_export`, `linkedin_pdf`
  - trust level
  - ingestion timestamp
  - source hash
  - user approval status

- `candidate_claims`
  - claim text
  - normalized concepts
  - source id
  - source quote
  - approval status
  - confidence

- `job_requirements`
  - raw text
  - normalized concepts
  - importance: `required`, `preferred`, `nice_to_have`
  - source quote

- `match_evidence`
  - requirement id
  - candidate claim id
  - match type: `exact`, `alias`, `taxonomy_related`, `semantic`
  - evidence strength level
  - explanation

## Open Product Decisions

1. Should GitHub be enabled in v1, or after CV/job matching works end-to-end?
2. Should LinkedIn enrichment v1 support upload/paste only, or also official API
   if access is available?
3. Should the match score be a single score, or should we show separate scores
   for `requirements_fit`, `evidence_quality`, and `cv_tailoring_potential`?
4. Should the user approve each new non-CV claim individually before it can
   enter the canonical profile?
5. Should GitHub evidence be used only for engineering roles, or any role where
   the job explicitly asks for public technical portfolio evidence?

## Sources

- O*NET Content Model: https://www.onetcenter.org/content.html
- O*NET Web Services: https://services.onetcenter.org/about
- ESCO API: https://esco.ec.europa.eu/en/use-esco/use-esco-services-api
- NACE Career Readiness Competencies: https://www.naceweb.org/career-readiness/competencies/career-readiness-defined
- GitHub REST API users: https://docs.github.com/rest/users/users
- GitHub REST API repository contents: https://docs.github.com/en/rest/repos/contents
- GitHub REST API rate limits: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
- GitHub Terms/API terms: https://docs.github.com/en/site-policy/github-terms/github-terms-of-service
- GitHub Acceptable Use Policies: https://docs.github.com/site-policy/acceptable-use-policies/github-acceptable-use-policies
- LinkedIn download your data: https://www.linkedin.com/help/linkedin/answer/a1339364
- LinkedIn API Terms: https://www.linkedin.com/legal/l/api-terms-of-use
- NIST AI Risk Management Framework: https://www.nist.gov/itl/ai-risk-management-framework
- ADA.gov AI hiring guidance: https://www.ada.gov/resources/ai-guidance

