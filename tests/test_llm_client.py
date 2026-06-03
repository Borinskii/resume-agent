"""Unit tests for the provider abstraction in app/services/llm_client.py."""

from __future__ import annotations

import os
import unittest
from unittest import mock

import httpx

from app.services import llm_client
from app.services.llm_client import (
    FireworksClient,
    OllamaClient,
    build_llm_client,
    describe_llm_status,
)


class _Resp:
    def __init__(self, status: int = 200, body: object | None = None) -> None:
        self.status_code = status
        self._body = body or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=request, response=response,
            )

    def json(self) -> object:
        return self._body


def _fake_client_factory(get_responses: dict[str, _Resp] | None = None,
                          post_responses: dict[str, _Resp] | None = None):
    get_responses = get_responses or {}
    post_responses = post_responses or {}

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, url, **kwargs):
            return get_responses.get(url, _Resp(404, {}))

        def post(self, url, **kwargs):
            return post_responses.get(url, _Resp(404, {}))

    return _FakeClient


@mock.patch.dict(os.environ, {}, clear=True)
class ProviderSelectionTests(unittest.TestCase):
    def test_no_env_returns_none(self) -> None:
        with mock.patch("app.services.llm_client.httpx.Client",
                         _fake_client_factory()):
            self.assertIsNone(build_llm_client())

    def test_fireworks_forced_without_key_is_none(self) -> None:
        os.environ["LLM_PROVIDER"] = "fireworks"
        self.assertIsNone(build_llm_client())
        status = describe_llm_status()
        self.assertEqual(status.provider, "fireworks")
        self.assertEqual(status.status, "missing_key")

    def test_fireworks_forced_with_key(self) -> None:
        os.environ["LLM_PROVIDER"] = "fireworks"
        os.environ["FIREWORKS_API_KEY"] = "fw_test"
        client = build_llm_client()
        self.assertIsInstance(client, FireworksClient)
        self.assertEqual(client.provider, "fireworks")

    def test_ollama_forced_unreachable_is_none(self) -> None:
        os.environ["LLM_PROVIDER"] = "ollama"
        with mock.patch("app.services.llm_client.httpx.Client",
                         _fake_client_factory()):
            self.assertIsNone(build_llm_client())
        with mock.patch("app.services.llm_client.httpx.Client",
                         _fake_client_factory()):
            self.assertEqual(describe_llm_status().status, "unreachable")

    def test_ollama_forced_model_not_pulled(self) -> None:
        os.environ["LLM_PROVIDER"] = "ollama"
        os.environ["OLLAMA_MODEL"] = "missing-model:latest"
        tags = {"models": [{"name": "llama3.1:8b"}]}
        with mock.patch("app.services.llm_client.httpx.Client",
                         _fake_client_factory(get_responses={
                             "http://127.0.0.1:11434/api/tags": _Resp(200, tags),
                         })):
            self.assertIsNone(build_llm_client())
            status = describe_llm_status()
        self.assertEqual(status.status, "model_not_pulled")
        self.assertIn("llama3.1:8b", status.detail)

    def test_ollama_forced_happy_path(self) -> None:
        os.environ["LLM_PROVIDER"] = "ollama"
        os.environ["OLLAMA_MODEL"] = "llama3.1:8b"
        tags = {"models": [{"name": "llama3.1:8b"}, {"name": "gemma4:e2b-it-q4_K_M"}]}
        with mock.patch("app.services.llm_client.httpx.Client",
                         _fake_client_factory(get_responses={
                             "http://127.0.0.1:11434/api/tags": _Resp(200, tags),
                         })):
            client = build_llm_client()
            self.assertIsInstance(client, OllamaClient)
            status = describe_llm_status()
        self.assertEqual(status.provider, "ollama")
        self.assertEqual(status.status, "connected")

    def test_auto_prefers_ollama_when_reachable(self) -> None:
        os.environ["FIREWORKS_API_KEY"] = "fw_test"
        os.environ["OLLAMA_MODEL"] = "llama3.1:8b"
        tags = {"models": [{"name": "llama3.1:8b"}]}
        with mock.patch("app.services.llm_client.httpx.Client",
                         _fake_client_factory(get_responses={
                             "http://127.0.0.1:11434/api/tags": _Resp(200, tags),
                         })):
            client = build_llm_client()
        self.assertIsInstance(client, OllamaClient)

    def test_auto_falls_back_to_fireworks(self) -> None:
        os.environ["FIREWORKS_API_KEY"] = "fw_test"
        with mock.patch("app.services.llm_client.httpx.Client",
                         _fake_client_factory()):
            client = build_llm_client()
        self.assertIsInstance(client, FireworksClient)

    def test_auto_with_nothing_configured(self) -> None:
        with mock.patch("app.services.llm_client.httpx.Client",
                         _fake_client_factory()):
            self.assertIsNone(build_llm_client())
            status = describe_llm_status()
        self.assertEqual(status.provider, "none")
        self.assertEqual(status.status, "not_configured")


class ResponseParsingTests(unittest.TestCase):
    def test_fireworks_message_extracted(self) -> None:
        client = FireworksClient("fw_test", "model")
        post_url = "https://api.fireworks.ai/inference/v1/chat/completions"
        body = {"choices": [{"message": {"content": "  rewritten bullet  "}}]}
        with mock.patch("app.services.llm_client.httpx.Client",
                         _fake_client_factory(post_responses={post_url: _Resp(200, body)})):
            text = client.complete("sys", "user")
        self.assertEqual(text, "rewritten bullet")

    def test_ollama_message_extracted(self) -> None:
        client = OllamaClient("http://127.0.0.1:11434", "llama3.1:8b")
        body = {"message": {"role": "assistant", "content": "  rewritten bullet  "}}
        with mock.patch("app.services.llm_client.httpx.Client",
                         _fake_client_factory(post_responses={
                             "http://127.0.0.1:11434/api/chat": _Resp(200, body),
                         })):
            text = client.complete("sys", "user")
        self.assertEqual(text, "rewritten bullet")

    def test_ollama_falls_back_to_response_field(self) -> None:
        client = OllamaClient("http://127.0.0.1:11434", "llama3.1:8b")
        body = {"response": "  from generate field  "}
        with mock.patch("app.services.llm_client.httpx.Client",
                         _fake_client_factory(post_responses={
                             "http://127.0.0.1:11434/api/chat": _Resp(200, body),
                         })):
            text = client.complete("sys", "user")
        self.assertEqual(text, "from generate field")


class TailoringIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        # Each test gets its own temp DB so storage globals never leak.
        import tempfile
        from pathlib import Path
        from app.services.storage import init_database

        self._tmpdir = tempfile.mkdtemp()
        init_database(Path(self._tmpdir) / "app.sqlite")

    def tearDown(self) -> None:
        import gc
        import shutil
        from app.services.storage import DEFAULT_DB_PATH, init_database

        # Make sure no sqlite handle is alive when we rmtree on Windows.
        gc.collect()
        try:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
        finally:
            init_database(DEFAULT_DB_PATH)

    def test_no_provider_yields_empty_rewrites(self) -> None:
        from app.services.matching import analyze_resume
        from app.services.tailoring import generate_tailored_rewrites

        resume = "Backend Engineer. Built REST APIs with Python and FastAPI."
        analysis = analyze_resume(resume_text=resume)

        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("app.services.llm_client.httpx.Client",
                         _fake_client_factory()):
            rewrites = generate_tailored_rewrites(analysis, resume)

        self.assertEqual(rewrites, [])

    def test_ollama_path_returns_rewrites(self) -> None:
        from app.services.matching import analyze_resume
        from app.services.tailoring import generate_tailored_rewrites

        resume = (
            "Backend Engineer.\n"
            "Built REST APIs with Python and FastAPI.\n"
            "Used SQL queries, PostgreSQL, Git in delivery workflows.\n"
            "Some pytest tests and Docker.\n"
        )
        analysis = analyze_resume(resume_text=resume)

        tags = {"models": [{"name": "llama3.1:8b"}]}
        chat_body = {"message": {"content": "Refactored Python and FastAPI APIs with PostgreSQL persistence."}}
        env = {"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "llama3.1:8b"}

        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("app.services.llm_client.httpx.Client",
                         _fake_client_factory(
                             get_responses={"http://127.0.0.1:11434/api/tags": _Resp(200, tags)},
                             post_responses={"http://127.0.0.1:11434/api/chat": _Resp(200, chat_body)},
                         )):
            rewrites = generate_tailored_rewrites(analysis, resume)

        self.assertGreater(len(rewrites), 0)
        self.assertTrue(all(item["provider"] == "ollama" for item in rewrites))
        self.assertTrue(any(item["rewritten_bullet"] for item in rewrites))


if __name__ == "__main__":
    unittest.main()
