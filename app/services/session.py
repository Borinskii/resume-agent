from __future__ import annotations

import os
import secrets
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware


def install_session_middleware(app: FastAPI, secret_path: Path) -> None:
    secret = os.environ.get("SESSION_SECRET", "").strip()
    if not secret:
        if secret_path.exists():
            secret = secret_path.read_text(encoding="utf-8").strip()
        else:
            secret = secrets.token_urlsafe(48)
            secret_path.parent.mkdir(parents=True, exist_ok=True)
            secret_path.write_text(secret, encoding="utf-8")
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie="cvjm_session",
        same_site="lax",
        https_only=False,
        max_age=60 * 60 * 24 * 30,
    )


def attach_session(request: Request) -> dict:
    """Ensure the request has a stable user_id. Returns the session dict."""
    session = request.session
    if not session.get("user_id"):
        session["user_id"] = uuid.uuid4().hex
    session.setdefault("display_name", "")
    return session


def get_session(request: Request) -> dict:
    return request.session
