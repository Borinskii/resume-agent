from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from app.services.github import GitHubEvidence
from app.services.job_search import JobPosting
from app.services.sample_jobs import ROLE_BENCHMARKS, SKILL_ALIASES, RoleBenchmark, SkillRequirement


ACTION_VERBS = {
    "built",
    "build",
    "created",
    "create",
    "designed",
    "design",
    "developed",
    "develop",
    "implemented",
    "implement",
    "maintained",
    "maintain",
    "migrated",
    "migrate",
    "optimized",
    "optimize",
    "deployed",
    "deploy",
    "tested",
    "test",
    "automated",
    "automate",
    "integrated",
    "integrate",
    "analyzed",
    "analyze",
    "led",
    "lead",
}

STOPWORDS = {
    "and",
    "with",
    "from",
    "into",
    "that",
    "this",
    "your",
    "their",
    "will",
    "work",
    "build",
    "using",
    "role",
    "team",
    "data",
    "services",
}

IMPORTANCE_WEIGHT = {
    "required": 1.0,
    "preferred": 0.52,
    "nice_to_have": 0.28,
}

LEVEL_MULTIPLIER = {
    0: 0.0,
    1: 0.35,
    2: 0.7,
    3: 1.0,
    4: 1.0,
}


@dataclass(frozen=True)
class RequirementMatch:
    name: str
    category: str
    importance: str
    evidence_level: int
    source: str
    quote: str
    matched_alias: str

    @property
    def status(self) -> str:
        if self.evidence_level == 0:
            return "missing"
        if self.source == "github":
            return "portfolio"
        if self.evidence_level == 1:
            return "mentioned"
        return "demonstrated"


@dataclass(frozen=True)
class TailoringAction:
    kind: str
    title: str
    detail: str
    source_quote: str = ""


@dataclass(frozen=True)
class RoleResult:
    title: str
    company_type: str
    summary: str
    current_score: int
    tailored_score: int
    skill_score: int
    responsibility_score: int
    portfolio_score: int
    confidence_score: int
    matched_required: int
    total_required: int
    matched_total: int
    total_requirements: int
    requirement_matches: list[RequirementMatch]
    missing_required: list[str]
    tailoring_actions: list[TailoringAction]
    provider: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    updated_at: str = ""
    source_kind: str = "benchmark"

    @property
    def gap_count(self) -> int:
        return len(self.missing_required)


@dataclass(frozen=True)
class SourceStatus:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class AnalysisResult:
    roles: list[RoleResult]
    source_statuses: list[SourceStatus]
    warnings: list[str]
    parsed_preview: str
    skill_inventory: list[str]
    average_current: int
    average_tailored: int
    confidence_score: int
    has_resume: bool
    resume_uploaded: bool
    resume_filename: str

    @property
    def top_role(self) -> RoleResult | None:
        return self.roles[0] if self.roles else None


def analyze_resume(
    resume_text: str,
    target_text: str = "",
    github_evidence: GitHubEvidence | None = None,
    linkedin_url: str = "",
    linkedin_text: str = "",
    resume_uploaded: bool = False,
    resume_filename: str = "",
    parse_warnings: list[str] | None = None,
    target_statuses: list[tuple[str, str, str]] | None = None,
    linkedin_cleaning_detail: str = "",
    job_postings: list[JobPosting] | None = None,
) -> AnalysisResult:
    parse_warnings = parse_warnings or []
    target_statuses = target_statuses or []
    job_postings = job_postings or []
    resume_text = clean_text(resume_text)
    linkedin_text = clean_text(linkedin_text)
    candidate_text = clean_text("\n\n".join(part for part in (resume_text, linkedin_text) if part))

    if job_postings:
        benchmarks = [job_posting_to_role(job) for job in job_postings]
        custom_target = None
    else:
        custom_target = build_custom_target(target_text)
    if custom_target is not None:
        benchmarks = [custom_target]
    elif not job_postings:
        benchmarks = list(ROLE_BENCHMARKS)

    roles = [
        score_role(role, candidate_text, github_evidence)
        for role in benchmarks
    ]
    roles.sort(
        key=lambda role: (
            role.title == "Custom target from pasted job",
            role.tailored_score,
            role.current_score,
            -role.gap_count,
        ),
        reverse=True,
    )

    inventory = extract_skill_inventory(candidate_text, github_evidence)
    average_current = rounded_average([role.current_score for role in roles])
    average_tailored = rounded_average([role.tailored_score for role in roles])
    confidence_score = rounded_average([role.confidence_score for role in roles[:3]]) if roles else 0

    statuses = build_source_statuses(
        resume_text=resume_text,
        resume_uploaded=resume_uploaded or bool(resume_text),
        resume_filename=resume_filename,
        linkedin_url=linkedin_url,
        linkedin_text=linkedin_text,
        github_evidence=github_evidence,
        custom_target=custom_target,
        target_text=target_text,
        target_statuses=target_statuses,
        linkedin_cleaning_detail=linkedin_cleaning_detail,
        job_posting_count=len(job_postings),
    )

    return AnalysisResult(
        roles=roles,
        source_statuses=statuses,
        warnings=parse_warnings,
        parsed_preview=resume_text[:1600],
        skill_inventory=inventory,
        average_current=average_current,
        average_tailored=average_tailored,
        confidence_score=confidence_score,
        has_resume=bool(resume_text),
        resume_uploaded=resume_uploaded or bool(resume_text),
        resume_filename=resume_filename,
    )


def score_role(
    role: RoleBenchmark,
    candidate_text: str,
    github_evidence: GitHubEvidence | None,
) -> RoleResult:
    requirement_matches = [
        score_requirement(requirement, candidate_text, github_evidence)
        for requirement in role.requirements
    ]

    skill_score = compute_skill_score(requirement_matches)
    responsibility_score = compute_responsibility_score(role.responsibilities, candidate_text)
    portfolio_score = compute_portfolio_score(requirement_matches)
    current_score = clamp_score(skill_score * 0.72 + responsibility_score * 0.2 + portfolio_score * 0.08)
    tailored_score = clamp_score(current_score + compute_tailoring_uplift(requirement_matches))
    confidence_score = compute_confidence(requirement_matches, candidate_text, github_evidence)

    total_required = sum(1 for item in requirement_matches if item.importance == "required")
    matched_required = sum(
        1 for item in requirement_matches
        if item.importance == "required" and item.evidence_level > 0
    )
    matched_total = sum(1 for item in requirement_matches if item.evidence_level > 0)
    missing_required = [
        item.name for item in requirement_matches
        if item.importance == "required" and item.evidence_level == 0
    ]

    return RoleResult(
        title=role.title,
        company_type=role.company_type,
        summary=role.summary,
        current_score=current_score,
        tailored_score=tailored_score,
        skill_score=skill_score,
        responsibility_score=responsibility_score,
        portfolio_score=portfolio_score,
        confidence_score=confidence_score,
        matched_required=matched_required,
        total_required=total_required,
        matched_total=matched_total,
        total_requirements=len(requirement_matches),
        requirement_matches=requirement_matches,
        missing_required=missing_required,
        tailoring_actions=build_tailoring_actions(requirement_matches),
        provider=role.provider,
        company=role.company,
        location=role.location,
        url=role.url,
        updated_at=role.updated_at,
        source_kind=role.source_kind,
    )


def score_requirement(
    requirement: SkillRequirement,
    candidate_text: str,
    github_evidence: GitHubEvidence | None,
) -> RequirementMatch:
    quote, alias = find_quote_for_requirement(candidate_text, requirement)
    if quote:
        level = evidence_level_from_quote(quote, alias, candidate_text)
        return RequirementMatch(
            name=requirement.name,
            category=requirement.category,
            importance=requirement.importance,
            evidence_level=level,
            source="candidate_profile",
            quote=safe_quote(quote, alias),
            matched_alias=alias,
        )

    if github_skill_match(requirement, github_evidence):
        return RequirementMatch(
            name=requirement.name,
            category=requirement.category,
            importance=requirement.importance,
            evidence_level=1,
            source="github",
            quote=f"Public GitHub evidence mentions {requirement.name}. User approval required before adding to CV.",
            matched_alias=requirement.name,
        )

    return RequirementMatch(
        name=requirement.name,
        category=requirement.category,
        importance=requirement.importance,
        evidence_level=0,
        source="none",
        quote="",
        matched_alias="",
    )


def find_quote_for_requirement(text: str, requirement: SkillRequirement) -> tuple[str, str]:
    if not text:
        return "", ""

    sentences = split_sentences(text)
    for alias in requirement.aliases:
        pattern = alias_pattern(alias)
        for sentence in sentences:
            if pattern.search(sentence):
                return sentence.strip(), alias
    return "", ""


def evidence_level_from_quote(quote: str, alias: str, text: str) -> int:
    normalized_quote = normalize(quote)
    normalized_text = normalize(text)
    alias_count = len(alias_pattern(alias).findall(normalized_text))
    has_action = any(verb in normalized_quote for verb in ACTION_VERBS)

    if alias_count >= 2 and has_action:
        return 3
    if has_action:
        return 2
    if alias_count >= 2:
        return 2
    return 1


def compute_skill_score(matches: list[RequirementMatch]) -> int:
    if not matches:
        return 0
    earned = 0.0
    possible = 0.0
    for item in matches:
        weight = IMPORTANCE_WEIGHT[item.importance]
        possible += weight
        earned += weight * LEVEL_MULTIPLIER[item.evidence_level]
    return clamp_score((earned / possible) * 100 if possible else 0)


def compute_responsibility_score(responsibilities: tuple[str, ...], text: str) -> int:
    if not responsibilities or not text:
        return 0

    hits = 0.0
    normalized_text = normalize(text)
    for responsibility in responsibilities:
        terms = content_terms(responsibility)
        if not terms:
            continue
        matched_terms = sum(1 for term in terms if term in normalized_text)
        ratio = matched_terms / len(terms)
        if ratio >= 0.5 or matched_terms >= 2:
            hits += 1
        elif matched_terms == 1:
            hits += 0.35

    return clamp_score((hits / len(responsibilities)) * 100)


def compute_portfolio_score(matches: list[RequirementMatch]) -> int:
    if not matches:
        return 0
    github_hits = sum(1 for item in matches if item.source == "github")
    return clamp_score((github_hits / len(matches)) * 100)


def compute_tailoring_uplift(matches: list[RequirementMatch]) -> int:
    uplift = 0.0
    possible = sum(IMPORTANCE_WEIGHT[item.importance] for item in matches) or 1.0

    for item in matches:
        if item.evidence_level == 0:
            continue
        if item.source == "github":
            uplift += IMPORTANCE_WEIGHT[item.importance] * 0.12
            continue
        if item.evidence_level == 1:
            uplift += IMPORTANCE_WEIGHT[item.importance] * 0.42
        elif item.evidence_level == 2:
            uplift += IMPORTANCE_WEIGHT[item.importance] * 0.18

    return min(18, clamp_score((uplift / possible) * 100))


def compute_confidence(
    matches: list[RequirementMatch],
    candidate_text: str,
    github_evidence: GitHubEvidence | None,
) -> int:
    if not candidate_text:
        return 0
    if not matches:
        return 30

    matched = [item for item in matches if item.evidence_level > 0]
    if not matched:
        return 38

    contextual = sum(1 for item in matched if item.evidence_level >= 2 and item.source != "github")
    github_only = sum(1 for item in matched if item.source == "github")

    coverage = len(matched) / len(matches)
    contextual_ratio = contextual / len(matched)
    github_penalty = min(15, github_only * 3)
    github_bonus = 4 if github_evidence and github_evidence.status == "connected" else 0

    return clamp_score(42 + coverage * 35 + contextual_ratio * 20 + github_bonus - github_penalty)


def build_tailoring_actions(matches: list[RequirementMatch]) -> list[TailoringAction]:
    actions: list[TailoringAction] = []

    for item in matches:
        if item.evidence_level in {1, 2} and item.source == "candidate_profile":
            actions.append(
                TailoringAction(
                    kind="highlight",
                    title=f"Make {item.name} more visible",
                    detail=(
                        f"{item.name} is supported by the source CV/profile, but the evidence is not strong. "
                        "Move it into a relevant project or experience bullet without adding new facts."
                    ),
                    source_quote=item.quote,
                )
            )
        elif item.source == "github":
            actions.append(
                TailoringAction(
                    kind="confirm",
                    title=f"Confirm GitHub evidence for {item.name}",
                    detail=(
                        "GitHub suggests this skill, but it should not enter the tailored CV "
                        "until the user confirms it reflects real experience."
                    ),
                    source_quote=item.quote,
                )
            )
        elif item.importance == "required" and item.evidence_level == 0:
            actions.append(
                TailoringAction(
                    kind="gap",
                    title=f"Keep {item.name} as a gap",
                    detail=(
                        f"The role requires {item.name}, but no supporting candidate evidence was found. "
                        "Do not claim it in the CV."
                    ),
                )
            )

    return actions[:5]


def build_custom_target(target_text: str) -> RoleBenchmark | None:
    text = clean_text(target_text)
    if not text or looks_like_url_only(text):
        return None

    title_target = build_title_target(text)
    if title_target is not None:
        return title_target

    requirements: list[SkillRequirement] = []
    for name, aliases in SKILL_ALIASES.items():
        temp = SkillRequirement(name=name, category="custom", aliases=aliases)
        quote, _ = find_quote_for_requirement(text, temp)
        if quote:
            importance = "required" if requirement_looks_required(quote) else "preferred"
            requirements.append(
                SkillRequirement(
                    name=name,
                    category="custom",
                    importance=importance,
                    aliases=aliases,
                )
            )

    if not requirements:
        return None

    requirements.sort(key=lambda item: (item.importance != "required", item.name))
    return RoleBenchmark(
        title="Custom target from pasted job",
        company_type="User-provided job text",
        summary="Parsed from the job description pasted into the dashboard.",
        requirements=tuple(requirements[:18]),
        responsibilities=tuple(extract_candidate_responsibilities(text)),
        source_kind="custom",
    )


def job_posting_to_role(job: JobPosting) -> RoleBenchmark:
    parsed = build_custom_target(job.description)
    title_fallback = build_title_target(job.title)

    if parsed is not None and parsed.requirements:
        requirements = parsed.requirements
        responsibilities = parsed.responsibilities
    elif title_fallback is not None:
        requirements = title_fallback.requirements
        responsibilities = title_fallback.responsibilities
    else:
        requirements = (
            SkillRequirement("Python", "language", "preferred", SKILL_ALIASES["Python"]),
            SkillRequirement("SQL", "data", "preferred", SKILL_ALIASES["SQL"]),
            SkillRequirement("Git", "workflow", "nice_to_have", SKILL_ALIASES["Git"]),
        )
        responsibilities = tuple(extract_candidate_responsibilities(job.description or job.title))

    return RoleBenchmark(
        title=job.title or "Untitled role",
        company_type=f"{job.company} via {job.provider}",
        summary=safe_quote(job.description or "No job description was available.", limit=260),
        requirements=requirements,
        responsibilities=responsibilities,
        provider=job.provider,
        company=job.company,
        location=job.location,
        url=job.url,
        updated_at=job.updated_at,
        source_kind="job",
    )


def build_title_target(text: str) -> RoleBenchmark | None:
    title = " ".join(text.split())
    if not looks_like_title_only(title):
        return None

    normalized = normalize(title)
    if any(marker in normalized for marker in ("ml", "machine learning", "ai engineer")):
        return RoleBenchmark(
            title=title,
            company_type="User target role title",
            summary="Inferred from the role title. Paste a full job description for company-specific requirements.",
            requirements=(
                SkillRequirement("Python", "language", "required", SKILL_ALIASES["Python"]),
                SkillRequirement("Machine Learning", "ai", "required", SKILL_ALIASES["Machine Learning"]),
                SkillRequirement("SQL", "data", "required", SKILL_ALIASES["SQL"]),
                SkillRequirement("Statistics", "analytics", "preferred", SKILL_ALIASES["Statistics"]),
                SkillRequirement("Pandas", "data", "preferred", SKILL_ALIASES["Pandas"]),
                SkillRequirement("NumPy", "data", "preferred", SKILL_ALIASES["NumPy"]),
                SkillRequirement("scikit-learn", "ai", "preferred", SKILL_ALIASES["scikit-learn"]),
                SkillRequirement("PyTorch", "ai", "preferred", SKILL_ALIASES["PyTorch"]),
                SkillRequirement("Deep Learning", "ai", "nice_to_have", SKILL_ALIASES["Deep Learning"]),
                SkillRequirement("Forecasting", "ai", "nice_to_have", SKILL_ALIASES["Forecasting"]),
                SkillRequirement("Git", "workflow", "nice_to_have", SKILL_ALIASES["Git"]),
            ),
            responsibilities=(
                "train and evaluate machine learning models",
                "prepare datasets and features",
                "communicate model performance and tradeoffs",
                "ship ML outputs into product or analytical workflows",
            ),
            source_kind="custom_title",
        )

    if "data analyst" in normalized:
        return RoleBenchmark(
            title=title,
            company_type="User target role title",
            summary="Inferred from the role title. Paste a full job description for company-specific requirements.",
            requirements=(
                SkillRequirement("SQL", "data", "required", SKILL_ALIASES["SQL"]),
                SkillRequirement("Excel", "data", "required", SKILL_ALIASES["Excel"]),
                SkillRequirement("Data Visualization", "analytics", "required", SKILL_ALIASES["Data Visualization"]),
                SkillRequirement("Statistics", "analytics", "preferred", SKILL_ALIASES["Statistics"]),
                SkillRequirement("Python", "language", "preferred", SKILL_ALIASES["Python"]),
                SkillRequirement("Pandas", "data", "preferred", SKILL_ALIASES["Pandas"]),
            ),
            responsibilities=(
                "analyze business or product metrics",
                "write SQL queries for datasets",
                "build dashboards and recurring reports",
                "communicate findings to stakeholders",
            ),
            source_kind="custom_title",
        )

    if "backend" in normalized and "python" in normalized:
        return RoleBenchmark(
            title=title,
            company_type="User target role title",
            summary="Inferred from the role title. Paste a full job description for company-specific requirements.",
            requirements=(
                SkillRequirement("Python", "language", "required", SKILL_ALIASES["Python"]),
                SkillRequirement("REST APIs", "backend", "required", SKILL_ALIASES["REST APIs"]),
                SkillRequirement("SQL", "data", "required", SKILL_ALIASES["SQL"]),
                SkillRequirement("Testing", "quality", "preferred", SKILL_ALIASES["Testing"]),
                SkillRequirement("FastAPI", "backend", "preferred", SKILL_ALIASES["FastAPI"]),
                SkillRequirement("PostgreSQL", "data", "preferred", SKILL_ALIASES["PostgreSQL"]),
            ),
            responsibilities=(
                "design and maintain API endpoints",
                "write tests for backend behavior",
                "work with relational databases",
                "integrate external services",
            ),
            source_kind="custom_title",
        )

    return None


def looks_like_title_only(text: str) -> bool:
    terms = content_terms(text)
    if not terms or len(terms) > 7:
        return False
    return not any(marker in text for marker in (".", "\n", ";", ":"))


def build_source_statuses(
    resume_text: str,
    resume_uploaded: bool,
    resume_filename: str,
    linkedin_url: str,
    linkedin_text: str,
    github_evidence: GitHubEvidence | None,
    custom_target: RoleBenchmark | None,
    target_text: str,
    target_statuses: list[tuple[str, str, str]],
    linkedin_cleaning_detail: str,
    job_posting_count: int,
) -> list[SourceStatus]:
    if resume_text:
        resume_status = SourceStatus(
            name="CV / Resume",
            status="approved_for_preview",
            detail="Parsed text is available for review.",
        )
    elif resume_uploaded:
        filename = resume_filename or "The uploaded CV"
        resume_status = SourceStatus(
            name="CV / Resume",
            status="text_unavailable",
            detail=(
                f"{filename} was uploaded, but no extractable text was found. "
                "Use OCR, upload a text-based PDF, or paste the CV text."
            ),
        )
    else:
        resume_status = SourceStatus(
            name="CV / Resume",
            status="missing",
            detail="Upload a CV or resume to run evidence-based matching.",
        )

    statuses = [resume_status]

    if github_evidence is None:
        statuses.append(SourceStatus("GitHub", "not_connected", "No GitHub profile provided."))
    else:
        statuses.append(
            SourceStatus(
                "GitHub",
                github_evidence.status,
                github_evidence.message or "GitHub public API enrichment attempted.",
            )
        )

    if linkedin_text:
        statuses.append(
            SourceStatus(
                "LinkedIn",
                "manual_text",
                linkedin_cleaning_detail or "Manual LinkedIn text is used as user-provided evidence.",
            )
        )
    elif linkedin_url.strip():
        statuses.append(SourceStatus("LinkedIn", "url_only", "URL stored as a pointer only. LinkedIn scraping is disabled."))
    else:
        statuses.append(SourceStatus("LinkedIn", "not_provided", "No LinkedIn source provided."))

    if job_posting_count:
        statuses.append(SourceStatus("Target jobs", "jobs_found", f"Scored {job_posting_count} real vacancies from approved ATS sources."))
    elif custom_target is not None:
        statuses.append(SourceStatus("Target job", "custom_parsed", "A custom benchmark was parsed from pasted job text."))
    elif target_text.strip():
        statuses.append(SourceStatus("Target job", "not_parsed", "Target text was provided, but no role requirements were detected."))
    else:
        statuses.append(SourceStatus("Target job", "benchmarks", "Role benchmarks are used for discovery."))

    for name, status, detail in target_statuses:
        statuses.append(SourceStatus(name, status, detail))

    return statuses


def extract_skill_inventory(text: str, github_evidence: GitHubEvidence | None) -> list[str]:
    found: set[str] = set()
    for name, aliases in SKILL_ALIASES.items():
        temp = SkillRequirement(name=name, category="inventory", aliases=aliases)
        quote, _ = find_quote_for_requirement(text, temp)
        if quote:
            found.add(name)

    if github_evidence and github_evidence.status == "connected":
        for skill in github_evidence.skills:
            for name, aliases in SKILL_ALIASES.items():
                if normalize(skill) in {normalize(alias) for alias in aliases} or normalize(skill) == normalize(name):
                    found.add(name)

    return sorted(found)


def github_skill_match(requirement: SkillRequirement, github_evidence: GitHubEvidence | None) -> bool:
    if github_evidence is None or github_evidence.status != "connected":
        return False
    github_skills = {normalize(skill) for skill in github_evidence.skills}
    for alias in requirement.aliases + (requirement.name,):
        if normalize(alias) in github_skills:
            return True
    return False


def extract_candidate_responsibilities(text: str) -> list[str]:
    sentences = split_sentences(text)
    action_sentences = [
        sentence for sentence in sentences
        if any(verb in normalize(sentence) for verb in ACTION_VERBS)
    ]
    return action_sentences[:4] or sentences[:4]


def requirement_looks_required(quote: str) -> bool:
    normalized = normalize(quote)
    required_terms = ("required", "must", "need", "needs", "minimum", "hands-on", "strong")
    return any(term in normalized for term in required_terms)


def looks_like_url_only(text: str) -> bool:
    chunks = [chunk.strip() for chunk in text.splitlines() if chunk.strip()]
    if not chunks:
        return False
    return all(chunk.startswith(("http://", "https://")) for chunk in chunks)


def split_sentences(text: str) -> list[str]:
    if not text.strip():
        return []
    raw_parts = re.split(r"\n+|[•○]|(?<=[.!?])\s+|\s+\|\s+", text.strip())
    parts = [" ".join(part.strip(" -").split()) for part in raw_parts]
    return [part for part in parts if part]


def content_terms(text: str) -> list[str]:
    return [
        word for word in re.findall(r"[a-zA-Z][a-zA-Z+#.-]{3,}", normalize(text))
        if word not in STOPWORDS
    ]


def alias_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(normalize(alias))
    escaped = escaped.replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.IGNORECASE)


def clean_text(text: str) -> str:
    value = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t\f\v]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def safe_quote(quote: str, alias: str = "", limit: int = 230) -> str:
    value = redact_sensitive(" ".join((quote or "").split()))
    if alias and len(value) > limit:
        match = alias_pattern(alias).search(value)
        if match:
            half = limit // 2
            start = max(0, match.start() - half)
            end = min(len(value), match.end() + half)
            value = value[start:end].strip()
            if start > 0:
                value = f"... {value}"
            if end < len(quote):
                value = f"{value} ..."
    if len(value) > limit:
        value = f"{value[: limit - 4].rstrip()} ..."
    return value


def redact_sensitive(value: str) -> str:
    value = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[email]", value)
    value = re.sub(r"\+?\d[\d\s().-]{7,}\d", "[phone]", value)
    return value


def normalize(text: str) -> str:
    return (text or "").lower().replace("_", " ").strip()


def clamp_score(value: float) -> int:
    if math.isnan(value):
        return 0
    return max(0, min(100, int(round(value))))


def rounded_average(values: list[int]) -> int:
    if not values:
        return 0
    return clamp_score(sum(values) / len(values))
