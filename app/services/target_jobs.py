from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import urlparse

import httpx


URL_RE = re.compile(r"https?://[^\s)>\]]+")
BLOCKED_JOB_DOMAINS = ("linkedin.com", "indeed.com", "glassdoor.com")
SUPPORTED_JOB_DOMAINS = (
    "greenhouse.io",
    "boards.greenhouse.io",
    "lever.co",
    "jobs.lever.co",
    "ashbyhq.com",
    "workable.com",
    "smartrecruiters.com",
)


@dataclass(frozen=True)
class TargetStatus:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class TargetResolution:
    text: str
    statuses: list[TargetStatus]
    warnings: list[str]


def resolve_target_input(value: str) -> TargetResolution:
    raw = value.strip()
    if not raw:
        return TargetResolution(text="", statuses=[], warnings=[])

    urls = extract_urls(raw)
    text_without_urls = remove_urls(raw).strip()
    fetched_texts: list[str] = []
    statuses: list[TargetStatus] = []
    warnings: list[str] = []

    for url in urls:
        status, text = fetch_supported_job_url(url)
        statuses.append(status)
        if text:
            fetched_texts.append(text)
        elif status.status in {"blocked_by_policy", "unsupported_url", "network_unavailable"}:
            warnings.append(status.detail)

    combined = "\n\n".join(part for part in [text_without_urls, *fetched_texts] if part)
    return TargetResolution(text=combined, statuses=statuses, warnings=warnings)


def extract_urls(value: str) -> list[str]:
    return [url.rstrip(".,;") for url in URL_RE.findall(value)]


def remove_urls(value: str) -> str:
    return URL_RE.sub(" ", value)


def fetch_supported_job_url(url: str) -> tuple[TargetStatus, str]:
    domain = normalized_domain(url)
    if not domain:
        return TargetStatus("Target URL", "invalid_url", f"Invalid target URL: {url}"), ""

    if domain_matches(domain, BLOCKED_JOB_DOMAINS):
        return (
            TargetStatus(
                "Target URL",
                "blocked_by_policy",
                f"{domain} is not fetched automatically. Paste the job text or use an official ATS/company URL.",
            ),
            "",
        )

    if not domain_matches(domain, SUPPORTED_JOB_DOMAINS):
        return (
            TargetStatus(
                "Target URL",
                "unsupported_url",
                f"{domain} is not an approved read-only ATS source yet.",
            ),
            "",
        )

    try:
        with httpx.Client(timeout=8, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": "cv-job-match-agent-local-prototype"})
            response.raise_for_status()
    except httpx.RequestError:
        return (
            TargetStatus(
                "Target URL",
                "network_unavailable",
                f"{domain} is approved for read-only fetches, but the URL is not reachable from this runtime.",
            ),
            "",
        )
    except httpx.HTTPStatusError as exc:
        return (
            TargetStatus(
                "Target URL",
                "fetch_failed",
                f"{domain} returned HTTP {exc.response.status_code}; job text was not imported.",
            ),
            "",
        )

    text = extract_job_text(response)
    if not text:
        return TargetStatus("Target URL", "parse_failed", f"{domain} fetched, but no usable job text was found."), ""
    return TargetStatus("Target URL", "fetched", f"Fetched job text from approved source {domain}."), text


def extract_job_text(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            return ""
        return trim_text("\n".join(extract_strings_from_json(payload)))

    return trim_text(strip_html(response.text))


def extract_strings_from_json(value: object) -> list[str]:
    wanted_keys = {"title", "content", "description", "requirements", "responsibilities", "location", "department"}
    strings: list[str] = []

    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in wanted_keys and isinstance(item, str):
                strings.append(strip_html(item))
            else:
                strings.extend(extract_strings_from_json(item))
    elif isinstance(value, list):
        for item in value:
            strings.extend(extract_strings_from_json(item))

    return strings


def strip_html(value: str) -> str:
    text = unescape(value or "")
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?is)<br\s*/?>|</p>|</li>|</h[1-6]>", "\n", text)
    text = re.sub(r"(?is)<.*?>", " ", text)
    return unescape(text)


def trim_text(value: str, limit: int = 12000) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", value)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]


def normalized_domain(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.netloc or "").lower().removeprefix("www.")


def domain_matches(domain: str, allowed: tuple[str, ...]) -> bool:
    return any(domain == item or domain.endswith(f".{item}") for item in allowed)
