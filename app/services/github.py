from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9-]+)(?:[/?#].*)?$", re.IGNORECASE)
RESERVED_GITHUB_PATHS = {"about", "apps", "blog", "collections", "events", "explore", "features", "marketplace", "orgs", "pricing", "settings", "topics"}


@dataclass(frozen=True)
class GitHubEvidence:
    username: str
    status: str
    skills: set[str] = field(default_factory=set)
    repositories: list[str] = field(default_factory=list)
    message: str = ""


def parse_github_username(value: str) -> str:
    value = value.strip().rstrip("/")
    if value.startswith("@"):
        value = value[1:]
    if not value:
        return ""
    match = GITHUB_RE.search(value)
    if match:
        username = match.group(1)
        return "" if username.lower() in RESERVED_GITHUB_PATHS else username
    if re.fullmatch(r"[A-Za-z0-9-]{1,39}", value):
        return "" if value.lower() in RESERVED_GITHUB_PATHS else value
    return ""


def fetch_github_evidence(username: str) -> GitHubEvidence:
    if not username:
        return GitHubEvidence(username="", status="not_connected")

    url = f"https://api.github.com/users/{username}/repos?per_page=20&sort=updated"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "cv-job-match-agent-local-prototype",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            repos = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            status = "rate_limited"
        elif exc.code == 404:
            status = "not_found"
        else:
            status = "failed"
        return GitHubEvidence(username=username, status=status, message=str(exc))
    except urllib.error.URLError as exc:
        return GitHubEvidence(
            username=username,
            status="network_unavailable",
            message=(
                "GitHub username was parsed, but the official GitHub API is not reachable "
                "from this runtime."
            ),
        )
    except Exception as exc:  # noqa: BLE001 - surface integration failures clearly.
        return GitHubEvidence(username=username, status="failed", message=f"GitHub API request failed: {exc}")

    skills: set[str] = set()
    repo_names: list[str] = []

    if not isinstance(repos, list):
        return GitHubEvidence(username=username, status="failed", message="Unexpected GitHub API response.")

    for repo in repos:
        if not isinstance(repo, dict):
            continue
        name = str(repo.get("name") or "")
        if name:
            repo_names.append(name)
        language = repo.get("language")
        if isinstance(language, str) and language:
            skills.add(language)
        for topic in _extract_topics(repo):
            skills.add(topic)

    return GitHubEvidence(
        username=username,
        status="connected",
        skills=skills,
        repositories=repo_names[:8],
        message=f"Read {len(repo_names)} public repositories through the official GitHub API.",
    )


def _extract_topics(repo: dict[str, Any]) -> list[str]:
    topics = repo.get("topics")
    if isinstance(topics, list):
        return [str(topic) for topic in topics if topic]
    return []
