from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app.services.encryption import EncryptionService
from app.services.matching import AnalysisResult

log = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "app.sqlite"
_DB_LOCK = Lock()
_DB_PATH: Path | None = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    cv_sha256 TEXT NOT NULL,
    cv_filename TEXT NOT NULL,
    cv_ciphertext BLOB NOT NULL,
    payload_json TEXT NOT NULL,
    rewrites_json TEXT NOT NULL,
    top_score INTEGER NOT NULL,
    top_title TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analyses_user_created
    ON analyses(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    analysis_id INTEGER NOT NULL,
    job_url TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_applications_user_status
    ON applications(user_id, status);

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


VALID_APPLICATION_STATUSES = (
    "queued",
    "manual_confirmation_required",
    "manual_intervention_required",
    "sent",
    "failed",
    "expired",
    "response_received",
    "no_response",
    "withdrawn",
)


@dataclass
class StoredAnalysis:
    id: int
    user_id: str
    created_at: str
    cv_sha256: str
    cv_filename: str
    payload: dict
    rewrites: list[dict]
    cv_ciphertext: bytes
    top_score: int
    top_title: str


def init_database(path: Path) -> None:
    global _DB_PATH
    _DB_PATH = Path(path)
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def _connect() -> sqlite3.Connection:
    if _DB_PATH is None:
        raise RuntimeError("Database is not initialized. Call init_database() first.")
    conn = sqlite3.connect(str(_DB_PATH), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def persist_analysis(
    user_id: str,
    analysis: AnalysisResult,
    resume_text: str,
    encryptor: EncryptionService,
    rewrites: list[dict] | None = None,
) -> int | None:
    if not resume_text:
        return None
    cv_sha = hashlib.sha256(resume_text.encode("utf-8")).hexdigest()
    payload = _analysis_to_dict(analysis)
    rewrites_json = json.dumps(rewrites or [], ensure_ascii=False)
    payload_json = json.dumps(payload, ensure_ascii=False)
    top_score = analysis.top_role.current_score if analysis.top_role else 0
    top_title = analysis.top_role.title if analysis.top_role else ""

    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO analyses
                (user_id, created_at, cv_sha256, cv_filename,
                 cv_ciphertext, payload_json, rewrites_json, top_score, top_title)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                _utc_now(),
                cv_sha,
                analysis.resume_filename or "",
                encryptor.encrypt(resume_text),
                payload_json,
                rewrites_json,
                top_score,
                top_title,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_analyses(user_id: str, limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, cv_filename, top_score, top_title
            FROM analyses
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_analysis(analysis_id: int) -> StoredAnalysis | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM analyses WHERE id = ?",
            (analysis_id,),
        ).fetchone()
    if row is None:
        return None
    return StoredAnalysis(
        id=row["id"],
        user_id=row["user_id"],
        created_at=row["created_at"],
        cv_sha256=row["cv_sha256"],
        cv_filename=row["cv_filename"],
        payload=json.loads(row["payload_json"]),
        rewrites=json.loads(row["rewrites_json"]),
        cv_ciphertext=row["cv_ciphertext"],
        top_score=row["top_score"],
        top_title=row["top_title"],
    )


def delete_user_data(user_id: str) -> int:
    """Hard-delete every row tied to this user. Required by Rule 14."""
    with _DB_LOCK, _connect() as conn:
        deleted = conn.execute("DELETE FROM analyses WHERE user_id = ?", (user_id,)).rowcount
        conn.execute("DELETE FROM applications WHERE user_id = ?", (user_id,))
        conn.commit()
    return deleted


def create_application(
    user_id: str,
    analysis_id: int,
    job_url: str,
    company: str,
    title: str,
    status: str = "manual_confirmation_required",
    note: str = "",
) -> int:
    if status not in VALID_APPLICATION_STATUSES:
        raise ValueError(f"Invalid application status: {status}")
    now = _utc_now()
    with _DB_LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO applications
                (user_id, analysis_id, job_url, company, title, status, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, analysis_id, job_url, company, title, status, note, now, now),
        )
        conn.commit()
        return int(cursor.lastrowid)


def update_application_status(application_id: int, status: str, note: str = "") -> None:
    if status not in VALID_APPLICATION_STATUSES:
        raise ValueError(f"Invalid application status: {status}")
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            UPDATE applications
            SET status = ?, note = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, note, _utc_now(), application_id),
        )
        conn.commit()


def list_applications(user_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, analysis_id, job_url, company, title, status, note, created_at, updated_at
            FROM applications
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def cache_get(cache_key: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT response_json FROM llm_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["response_json"])
    except json.JSONDecodeError:
        return None


def cache_put(cache_key: str, response: dict) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO llm_cache (cache_key, response_json, created_at)
            VALUES (?, ?, ?)
            """,
            (cache_key, json.dumps(response, ensure_ascii=False), _utc_now()),
        )
        conn.commit()


def _analysis_to_dict(analysis: AnalysisResult) -> dict:
    return {
        "roles": [_role_to_dict(role) for role in analysis.roles],
        "source_statuses": [dataclasses.asdict(status) for status in analysis.source_statuses],
        "warnings": list(analysis.warnings),
        "parsed_preview": analysis.parsed_preview,
        "skill_inventory": list(analysis.skill_inventory),
        "average_current": analysis.average_current,
        "average_tailored": analysis.average_tailored,
        "confidence_score": analysis.confidence_score,
        "has_resume": analysis.has_resume,
        "resume_uploaded": analysis.resume_uploaded,
        "resume_filename": analysis.resume_filename,
    }


def _role_to_dict(role: Any) -> dict:
    data = dataclasses.asdict(role)
    data["requirement_matches"] = [dataclasses.asdict(item) for item in role.requirement_matches]
    data["tailoring_actions"] = [dataclasses.asdict(item) for item in role.tailoring_actions]
    return data


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
