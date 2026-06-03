"""Provider-agnostic LLM client.

Two adapters: Fireworks (hosted) and Ollama (local). Selection is driven by
env vars so the rest of the app stays free of provider conditionals.

LLM_PROVIDER values:
    "fireworks" — force Fireworks, fail closed if FIREWORKS_API_KEY missing
    "ollama"    — force Ollama, fail closed if /api/tags unreachable
    ""/"auto"   — prefer Ollama if reachable, else Fireworks if key set, else None
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
DEFAULT_FIREWORKS_MODEL = "accounts/fireworks/models/deepseek-v3p1"
FIREWORKS_URL = "https://api.fireworks.ai/inference/v1/chat/completions"


@dataclass(frozen=True)
class LLMStatus:
    """Surface-able diagnostic for the source-status tile."""

    provider: str
    status: str  # connected, missing_key, unreachable, model_not_pulled, not_configured
    detail: str


class LLMClient(Protocol):
    """Tiny chat-completion surface. Implementations raise on hard errors."""

    provider: str

    def complete(self, system: str, user: str) -> str: ...


class FireworksClient:
    provider = "fireworks"

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self._model,
            "max_tokens": 220,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        with httpx.Client(timeout=20) as client:
            response = client.post(FIREWORKS_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        return _openai_style_message(data)


class OllamaClient:
    provider = "ollama"

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self._model,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 220},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        with httpx.Client(timeout=90) as client:
            response = client.post(f"{self._base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        return _ollama_chat_message(data)


def build_llm_client() -> LLMClient | None:
    """Return a client per LLM_PROVIDER env, or None if nothing is configured."""
    provider = os.environ.get("LLM_PROVIDER", "auto").strip().lower() or "auto"
    api_key = os.environ.get("FIREWORKS_API_KEY", "").strip()
    fireworks_model = os.environ.get("FIREWORKS_MODEL", "").strip() or DEFAULT_FIREWORKS_MODEL
    ollama_base = os.environ.get("OLLAMA_BASE_URL", "").strip() or DEFAULT_OLLAMA_BASE_URL
    ollama_model = os.environ.get("OLLAMA_MODEL", "").strip() or DEFAULT_OLLAMA_MODEL

    if provider == "fireworks":
        if not api_key:
            log.info("LLM_PROVIDER=fireworks but FIREWORKS_API_KEY missing.")
            return None
        return FireworksClient(api_key, fireworks_model)

    if provider == "ollama":
        if not _ollama_reachable(ollama_base, ollama_model):
            return None
        return OllamaClient(ollama_base, ollama_model)

    # auto: prefer local Ollama (free), fall back to Fireworks
    if _ollama_reachable(ollama_base, ollama_model):
        return OllamaClient(ollama_base, ollama_model)
    if api_key:
        return FireworksClient(api_key, fireworks_model)
    return None


def describe_llm_status() -> LLMStatus:
    """Cheap status for the UI source-status grid. Returns the *active* provider
    that build_llm_client() would return, plus a human note."""
    provider = os.environ.get("LLM_PROVIDER", "auto").strip().lower() or "auto"
    api_key = os.environ.get("FIREWORKS_API_KEY", "").strip()
    ollama_base = os.environ.get("OLLAMA_BASE_URL", "").strip() or DEFAULT_OLLAMA_BASE_URL
    ollama_model = os.environ.get("OLLAMA_MODEL", "").strip() or DEFAULT_OLLAMA_MODEL
    fireworks_model = os.environ.get("FIREWORKS_MODEL", "").strip() or DEFAULT_FIREWORKS_MODEL

    if provider == "fireworks":
        if api_key:
            return LLMStatus("fireworks", "connected", f"Forced Fireworks ({fireworks_model}).")
        return LLMStatus("fireworks", "missing_key", "LLM_PROVIDER=fireworks but FIREWORKS_API_KEY is empty.")

    if provider == "ollama":
        tags, err = _ollama_tags(ollama_base)
        if err:
            return LLMStatus("ollama", "unreachable", f"Ollama at {ollama_base} unreachable: {err}")
        if not _model_in_tags(ollama_model, tags):
            installed = ", ".join(_tag_names(tags)) or "(none)"
            return LLMStatus(
                "ollama",
                "model_not_pulled",
                f"Model '{ollama_model}' not pulled. Installed: {installed}. Run: ollama pull {ollama_model}",
            )
        return LLMStatus("ollama", "connected", f"Local Ollama ({ollama_model}) at {ollama_base}.")

    # auto
    tags, err = _ollama_tags(ollama_base)
    if err is None and _model_in_tags(ollama_model, tags):
        return LLMStatus("ollama", "connected", f"Auto-selected local Ollama ({ollama_model}).")
    if api_key:
        return LLMStatus("fireworks", "connected", f"Auto-selected Fireworks ({fireworks_model}).")
    if err is None:
        installed = ", ".join(_tag_names(tags)) or "(none)"
        return LLMStatus(
            "none",
            "not_configured",
            f"Ollama running but '{ollama_model}' not pulled (have: {installed}); FIREWORKS_API_KEY not set.",
        )
    return LLMStatus(
        "none",
        "not_configured",
        "No LLM configured. Set FIREWORKS_API_KEY or run Ollama with a pulled model.",
    )


def _ollama_reachable(base_url: str, model: str) -> bool:
    tags, err = _ollama_tags(base_url)
    if err is not None:
        log.info("Ollama unreachable at %s: %s", base_url, err)
        return False
    if not _model_in_tags(model, tags):
        log.info("Ollama model %s not pulled; available: %s", model, _tag_names(tags))
        return False
    return True


def _ollama_tags(base_url: str) -> tuple[list[dict[str, Any]], str | None]:
    url = base_url.rstrip("/") + "/api/tags"
    try:
        with httpx.Client(timeout=2) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()
    except httpx.RequestError as exc:
        return [], f"network: {exc.__class__.__name__}"
    except (httpx.HTTPStatusError, ValueError) as exc:
        return [], f"http: {exc}"
    models = data.get("models") if isinstance(data, dict) else None
    return (models if isinstance(models, list) else []), None


def _tag_names(tags: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("name") or item.get("model") or "") for item in tags if isinstance(item, dict)]


def _model_in_tags(model: str, tags: list[dict[str, Any]]) -> bool:
    needle = model.strip().lower()
    if not needle:
        return False
    for name in _tag_names(tags):
        n = name.strip().lower()
        if n == needle:
            return True
        # Ollama lists "llama3.1:8b" — treat "llama3.1" as a match for "llama3.1:latest"
        if ":" in needle and ":" not in n and n == needle.split(":", 1)[0]:
            return True
        if ":" in n and ":" not in needle and needle == n.split(":", 1)[0]:
            return True
    return False


def _openai_style_message(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message") or {}
    content = message.get("content") if isinstance(message, dict) else ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [block.get("text", "") for block in content if isinstance(block, dict)]
        return " ".join(parts).strip()
    return ""


def _ollama_chat_message(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    message = data.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
    # Fallback for /api/generate style
    response = data.get("response")
    if isinstance(response, str):
        return response.strip()
    return ""
