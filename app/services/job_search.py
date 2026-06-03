from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from html import unescape
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed

import httpx

from app.services.target_jobs import TargetStatus, strip_html, trim_text

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderBoard:
    provider: str
    company: str
    token: str


@dataclass(frozen=True)
class JobPosting:
    provider: str
    company: str
    external_id: str
    title: str
    location: str
    url: str
    updated_at: str
    description: str
    department: str = ""


@dataclass(frozen=True)
class JobDiscoveryResult:
    jobs: list[JobPosting]
    statuses: list[TargetStatus]
    warnings: list[str]
    query: str


DEFAULT_GREENHOUSE_BOARDS: tuple[ProviderBoard, ...] = (
    ProviderBoard("greenhouse", "Anthropic", "anthropic"),
    ProviderBoard("greenhouse", "Stripe", "stripe"),
    ProviderBoard("greenhouse", "Databricks", "databricks"),
    ProviderBoard("greenhouse", "Datadog", "datadog"),
    ProviderBoard("greenhouse", "Airbnb", "airbnb"),
    ProviderBoard("greenhouse", "Figma", "figma"),
    ProviderBoard("greenhouse", "GitLab", "gitlab"),
    ProviderBoard("greenhouse", "Reddit", "reddit"),
    ProviderBoard("greenhouse", "Pinterest", "pinterest"),
    ProviderBoard("greenhouse", "Cloudflare", "cloudflare"),
    ProviderBoard("greenhouse", "Twilio", "twilio"),
    ProviderBoard("greenhouse", "Elastic", "elastic"),
    ProviderBoard("greenhouse", "Asana", "asana"),
    ProviderBoard("greenhouse", "Instacart", "instacart"),
    ProviderBoard("greenhouse", "Robinhood", "robinhood"),
    ProviderBoard("greenhouse", "Discord", "discord"),
    ProviderBoard("greenhouse", "Vercel", "vercel"),
    ProviderBoard("greenhouse", "Dropbox", "dropbox"),
    ProviderBoard("greenhouse", "Mercury", "mercury"),
    ProviderBoard("greenhouse", "Scale AI", "scaleai"),
)

DEFAULT_LEVER_BOARDS: tuple[ProviderBoard, ...] = (
    ProviderBoard("lever", "Mistral AI", "mistral"),
    ProviderBoard("lever", "Spotify", "spotify"),
)


def _parse_env_boards(value: str, provider: str) -> tuple[ProviderBoard, ...]:
    boards: list[ProviderBoard] = []
    for chunk in (value or "").split(","):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        company, token = chunk.split(":", 1)
        company = company.strip()
        token = token.strip()
        if company and token:
            boards.append(ProviderBoard(provider, company, token))
    return tuple(boards)


def _load_boards() -> tuple[tuple[ProviderBoard, ...], tuple[ProviderBoard, ...]]:
    gh_extra = _parse_env_boards(os.environ.get("EXTRA_GREENHOUSE_BOARDS", ""), "greenhouse")
    lv_extra = _parse_env_boards(os.environ.get("EXTRA_LEVER_BOARDS", ""), "lever")
    return DEFAULT_GREENHOUSE_BOARDS + gh_extra, DEFAULT_LEVER_BOARDS + lv_extra


GREENHOUSE_BOARDS, LEVER_BOARDS = _load_boards()

QUERY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "ml": ("machine learning", "ml", "ai", "model", "forecasting", "data scientist"),
    "machine": ("machine learning", "ml", "ai", "model"),
    "learning": ("machine learning", "ml", "ai", "model"),
    "engineer": ("engineer", "developer", "software"),
    "intern": ("intern", "internship", "student"),
    "backend": ("backend", "back end", "api", "server"),
    "data": ("data", "analytics", "analyst"),
}


def discover_safe_jobs(query: str, limit: int = 10) -> JobDiscoveryResult:
    search_query = build_search_query(query)
    if not search_query:
        return JobDiscoveryResult(jobs=[], statuses=[], warnings=[], query="")

    board_statuses: list[TargetStatus] = []
    warnings: list[str] = []
    postings: list[JobPosting] = []
    tasks = [
        *[(fetch_greenhouse_board, board) for board in GREENHOUSE_BOARDS],
        *[(fetch_lever_board, board) for board in LEVER_BOARDS],
    ]

    executor = ThreadPoolExecutor(max_workers=6)
    futures = [
        executor.submit(fetch_board, fetcher, board)
        for fetcher, board in tasks
    ]
    try:
        for future in as_completed(futures, timeout=12):
            status, jobs = future.result()
            board_statuses.append(status)
            postings.extend(jobs)
    except TimeoutError:
        warnings.append("Job search timed out on some ATS boards; showing results fetched so far.")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    ranked = rank_jobs(postings, search_query)
    if not ranked:
        warnings.append(f"No safe ATS jobs matched '{search_query}' in the configured company boards.")

    provider_counts = count_ok_sources(board_statuses)
    statuses: list[TargetStatus] = []
    if provider_counts:
        statuses.append(
            TargetStatus(
                "Job search",
                "completed",
                f"Searched {provider_counts} approved ATS boards; showing top {min(limit, len(ranked))} matches.",
            )
        )
    else:
        statuses.append(
            TargetStatus(
                "Job search",
                "unavailable",
                f"No approved ATS boards were reachable from this runtime for query '{search_query}'.",
            )
        )

    return JobDiscoveryResult(
        jobs=ranked[:limit],
        statuses=statuses,
        warnings=warnings,
        query=search_query,
    )


def fetch_board(fetcher: object, board: ProviderBoard) -> tuple[TargetStatus, list[JobPosting]]:
    with httpx.Client(timeout=5, follow_redirects=True) as client:
        return fetcher(client, board)  # type: ignore[misc]


def fetch_greenhouse_board(client: httpx.Client, board: ProviderBoard) -> tuple[TargetStatus, list[JobPosting]]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board.token}/jobs?content=true"
    try:
        response = client.get(url, headers={"User-Agent": "cv-job-match-agent-local-prototype"})
        response.raise_for_status()
        payload = response.json()
    except httpx.RequestError:
        return TargetStatus(board.company, "network_unavailable", f"{board.company} Greenhouse board is unreachable."), []
    except (httpx.HTTPStatusError, ValueError) as exc:
        return TargetStatus(board.company, "fetch_failed", f"{board.company} Greenhouse board failed: {exc}"), []

    jobs = []
    for item in payload.get("jobs", []):
        if not isinstance(item, dict):
            continue
        jobs.append(
            JobPosting(
                provider="Greenhouse",
                company=board.company,
                external_id=str(item.get("id") or ""),
                title=str(item.get("title") or ""),
                location=extract_greenhouse_location(item),
                url=str(item.get("absolute_url") or ""),
                updated_at=str(item.get("updated_at") or ""),
                description=trim_text(strip_html(str(item.get("content") or ""))),
                department=extract_greenhouse_department(item),
            )
        )

    return TargetStatus(board.company, "fetched", f"Fetched {len(jobs)} Greenhouse jobs."), jobs


def fetch_lever_board(client: httpx.Client, board: ProviderBoard) -> tuple[TargetStatus, list[JobPosting]]:
    url = f"https://api.lever.co/v0/postings/{board.token}?mode=json"
    try:
        response = client.get(url, headers={"User-Agent": "cv-job-match-agent-local-prototype"})
        response.raise_for_status()
        payload = response.json()
    except httpx.RequestError:
        return TargetStatus(board.company, "network_unavailable", f"{board.company} Lever board is unreachable."), []
    except (httpx.HTTPStatusError, ValueError) as exc:
        return TargetStatus(board.company, "fetch_failed", f"{board.company} Lever board failed: {exc}"), []

    jobs = []
    if not isinstance(payload, list):
        return TargetStatus(board.company, "parse_failed", f"{board.company} Lever response was not a list."), []

    for item in payload:
        if not isinstance(item, dict):
            continue
        categories = item.get("categories") if isinstance(item.get("categories"), dict) else {}
        jobs.append(
            JobPosting(
                provider="Lever",
                company=board.company,
                external_id=str(item.get("id") or ""),
                title=str(item.get("text") or ""),
                location=str(categories.get("location") or ""),
                url=str(item.get("hostedUrl") or item.get("applyUrl") or ""),
                updated_at=str(item.get("createdAt") or ""),
                description=trim_text(strip_html(str(item.get("descriptionPlain") or item.get("description") or ""))),
                department=str(categories.get("team") or ""),
            )
        )

    return TargetStatus(board.company, "fetched", f"Fetched {len(jobs)} Lever jobs."), jobs


def rank_jobs(jobs: list[JobPosting], query: str) -> list[JobPosting]:
    ranked = [
        (job_relevance_score(job, query), job)
        for job in dedupe_jobs(jobs)
    ]
    ranked = [(score, job) for score, job in ranked if score > 0]
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [job for _, job in ranked]


def job_relevance_score(job: JobPosting, query: str) -> int:
    query_terms = expanded_query_terms(query)
    title = normalize(job.title)
    haystack = normalize(" ".join([job.title, job.department, job.location, job.description]))

    score = 0
    for term in query_terms:
        if term in title:
            score += 12
        elif term in haystack:
            score += 4

    if "intern" in query_terms and "intern" in title:
        score += 12
    if any(term in query_terms for term in ("ml", "machine learning", "ai")) and any(
        term in haystack for term in ("machine learning", " ml ", " ai ", "model", "forecast")
    ):
        score += 18
    if "engineer" in query_terms and any(term in title for term in ("engineer", "developer")):
        score += 8

    return score


def expanded_query_terms(query: str) -> set[str]:
    terms = set(content_terms(query))
    for term in list(terms):
        terms.update(QUERY_SYNONYMS.get(term, ()))
    normalized = normalize(query)
    if "machine learning" in normalized:
        terms.update(("machine learning", "ml", "ai", "model"))
    return {term for term in terms if len(term) > 1}


ROLE_TITLE_KEYWORDS = (
    "engineer",
    "developer",
    "scientist",
    "analyst",
    "manager",
    "designer",
    "architect",
    "researcher",
    "lead",
    "intern",
    "consultant",
    "specialist",
    "director",
    "officer",
    "administrator",
)


def build_search_query(value: str) -> str:
    """Pull a focused search query from short text or a long job description.

    Short input (single title): keep as-is. Long input: extract the line that
    looks most like a role title, then fall back to top content terms so we
    never lose all signal past the first line.
    """
    without_urls = re.sub(r"https?://\S+", " ", value or "")
    lines = [line.strip() for line in without_urls.splitlines() if line.strip()]
    if not lines:
        return ""

    if len(lines) == 1 and len(lines[0]) <= 100:
        return lines[0].strip()

    title_line = _pick_title_line(lines)
    if title_line and len(title_line) <= 100:
        return title_line

    keywords = _top_keywords(without_urls, max_terms=10)
    if keywords:
        return " ".join(keywords)

    return lines[0][:100].strip()


def _pick_title_line(lines: list[str]) -> str:
    for line in lines[:6]:
        normalized = normalize(line)
        if any(kw in normalized for kw in ROLE_TITLE_KEYWORDS) and len(line) <= 100:
            return line
    return ""


def _top_keywords(text: str, max_terms: int) -> list[str]:
    stop = {"and", "the", "for", "with", "from", "you", "your", "our", "are", "this", "that", "have", "will", "into", "any", "all", "but", "not"}
    seen: dict[str, int] = {}
    for term in content_terms(text):
        if term in stop:
            continue
        seen[term] = seen.get(term, 0) + 1
    ranked = sorted(seen.items(), key=lambda item: (-item[1], item[0]))
    return [term for term, _ in ranked[:max_terms]]


def extract_greenhouse_location(item: dict[str, object]) -> str:
    location = item.get("location")
    if isinstance(location, dict):
        return str(location.get("name") or "")
    return ""


def extract_greenhouse_department(item: dict[str, object]) -> str:
    departments = item.get("departments")
    if isinstance(departments, list):
        names = [str(dep.get("name") or "") for dep in departments if isinstance(dep, dict)]
        return ", ".join(name for name in names if name)
    return ""


def dedupe_jobs(jobs: list[JobPosting]) -> list[JobPosting]:
    seen: set[str] = set()
    unique: list[JobPosting] = []
    for job in jobs:
        key = job.url or f"{job.provider}:{job.company}:{job.external_id}:{job.title}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def count_ok_sources(statuses: list[TargetStatus]) -> int:
    return sum(1 for status in statuses if status.status == "fetched")


def content_terms(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z+#.-]{1,}", normalize(text))


def normalize(text: str) -> str:
    return unescape(text or "").lower().replace("_", " ").strip()
