from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.services.llm_client import LLMClient, build_llm_client
from app.services.matching import AnalysisResult, RoleResult
from app.services.storage import cache_get, cache_put

log = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You rewrite single resume bullet points to better match a target role, "
    "but you must never invent skills, employers, dates, titles, certifications, or metrics. "
    "Only reorder, rephrase, or emphasize facts that are already present in the source bullet. "
    "If the source bullet does not support the required skill, respond with a one-line gap note "
    "starting with 'GAP:' and do not produce a rewrite."
)


@dataclass(frozen=True)
class TailoredRewrite:
    role_title: str
    role_url: str
    skill_name: str
    original_bullet: str
    rewritten_bullet: str
    is_gap: bool
    note: str
    provider: str = ""


def generate_tailored_rewrites(
    analysis: AnalysisResult,
    resume_text: str,
    max_rewrites: int = 5,
) -> list[dict]:
    """Generate at most `max_rewrites` source-backed bullet rewrites."""
    if not resume_text or not analysis.top_role:
        return []

    client = build_llm_client()
    if client is None:
        log.info("No LLM provider configured; skipping rewrites.")
        return []

    bullets = _extract_bullets(resume_text)
    if not bullets:
        return []

    rewrites: list[TailoredRewrite] = []
    target = analysis.top_role

    for action in target.tailoring_actions:
        if action.kind != "highlight":
            continue
        if len(rewrites) >= max_rewrites:
            break

        anchor_quote = action.source_quote
        bullet = _pick_bullet_for_quote(bullets, anchor_quote) or anchor_quote
        if not bullet:
            continue

        skill_name = _extract_skill_from_title(action.title)
        cache_key = _cache_key(client.provider, bullet, target.title, skill_name)

        cached = cache_get(cache_key)
        if cached is not None:
            rewrites.append(_from_cache(cached, target, skill_name, bullet, client.provider))
            continue

        try:
            llm_text = client.complete(SYSTEM_PROMPT, _user_prompt(bullet, target, skill_name))
        except Exception as exc:  # noqa: BLE001 - surface integration failures clearly.
            log.warning("LLM (%s) rewrite failed: %s", client.provider, exc)
            continue

        rewrite = _build_rewrite(llm_text, target, skill_name, bullet, client.provider)
        cache_put(cache_key, _to_cache(rewrite))
        rewrites.append(rewrite)

    return [_to_dict(item) for item in rewrites]


def _user_prompt(bullet: str, target: RoleResult, skill_name: str) -> str:
    return (
        f"Target role: {target.title}\n"
        f"Skill to make more visible (without inventing facts): {skill_name}\n"
        f"Source bullet from the candidate CV:\n\"{bullet}\"\n\n"
        "Rewrite this single bullet so it surfaces the target skill, keeping the same facts. "
        "Return the rewritten bullet only, one line, no commentary."
    )


def _build_rewrite(
    llm_text: str,
    target: RoleResult,
    skill_name: str,
    bullet: str,
    provider: str,
) -> TailoredRewrite:
    is_gap = llm_text.upper().startswith("GAP:")
    rewritten = "" if is_gap else _clean_bullet(llm_text)
    note = llm_text[4:].strip() if is_gap else ""
    return TailoredRewrite(
        role_title=target.title,
        role_url=target.url,
        skill_name=skill_name,
        original_bullet=bullet,
        rewritten_bullet=rewritten,
        is_gap=is_gap,
        note=note,
        provider=provider,
    )


def _clean_bullet(text: str) -> str:
    line = text.strip()
    # Drop common preambles emitted by chatty local models.
    line = re.sub(r"^(here(?:'s| is)|rewritten bullet|rewrite):\s*", "", line, flags=re.IGNORECASE)
    # Take just the first non-empty line; bullet-style output should be one line.
    for candidate in line.splitlines():
        candidate = candidate.strip()
        if candidate:
            line = candidate
            break
    if line.startswith('"') and line.endswith('"'):
        line = line[1:-1]
    return re.sub(r"^[-•*]\s*", "", line).strip()


def _extract_bullets(resume_text: str) -> list[str]:
    raw = re.split(r"\n+|[•○]|(?<=[.!?])\s+(?=[A-Z])", resume_text)
    return [" ".join(part.strip(" -").split()) for part in raw if len(part.strip()) >= 25]


def _pick_bullet_for_quote(bullets: list[str], quote: str) -> str:
    if not quote:
        return ""
    needle = re.sub(r"\s+", " ", quote).strip()[:80]
    if not needle:
        return ""
    for bullet in bullets:
        if needle in bullet:
            return bullet
    needle_lower = needle.lower()
    for bullet in bullets:
        if needle_lower in bullet.lower():
            return bullet
    return ""


def _extract_skill_from_title(title: str) -> str:
    match = re.match(r"Make (.+?) more visible", title)
    if match:
        return match.group(1)
    return title


def _cache_key(provider: str, bullet: str, role_title: str, skill: str) -> str:
    raw = f"{provider}|{role_title}|{skill}|{bullet}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _to_cache(rewrite: TailoredRewrite) -> dict:
    return {
        "rewritten_bullet": rewrite.rewritten_bullet,
        "is_gap": rewrite.is_gap,
        "note": rewrite.note,
        "provider": rewrite.provider,
    }


def _from_cache(
    cached: dict,
    target: RoleResult,
    skill_name: str,
    bullet: str,
    provider: str,
) -> TailoredRewrite:
    return TailoredRewrite(
        role_title=target.title,
        role_url=target.url,
        skill_name=skill_name,
        original_bullet=bullet,
        rewritten_bullet=cached.get("rewritten_bullet", ""),
        is_gap=bool(cached.get("is_gap")),
        note=cached.get("note", ""),
        provider=cached.get("provider") or provider,
    )


def _to_dict(rewrite: TailoredRewrite) -> dict:
    return {
        "role_title": rewrite.role_title,
        "role_url": rewrite.role_url,
        "skill_name": rewrite.skill_name,
        "original_bullet": rewrite.original_bullet,
        "rewritten_bullet": rewrite.rewritten_bullet,
        "is_gap": rewrite.is_gap,
        "note": rewrite.note,
        "provider": rewrite.provider,
    }
