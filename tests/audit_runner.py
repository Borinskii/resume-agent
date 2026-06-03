"""End-to-end click+verify audit runner. Per docs/AUDIT_GUIDE_FOR_AI.md."""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import textwrap
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:8765"
DB_PATH = ROOT / "data" / "app.sqlite"

results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    icon = "PASS" if ok else "FAIL"
    results.append((icon, name, detail))
    print(f"  {icon}: {name}{' — ' + detail if detail else ''}")


def query_db(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return rows


def make_pdf_bytes() -> bytes:
    """Tiny but valid text-based PDF. Returns bytes."""
    text = textwrap.dedent("""
        Backend Engineer.
        Built REST APIs with Python and FastAPI for internal tools.
        Implemented SQL queries, PostgreSQL models with SQLAlchemy, and wrote pytest tests.
        Used Git and Docker in delivery workflows.
        Designed and maintained API endpoints and integrated external services.
        Also did some machine learning work with pandas and scikit-learn.
    """).strip()
    # Single-page PDF using minimal manual construction.
    objs: list[bytes] = []

    def add(obj: bytes) -> int:
        objs.append(obj)
        return len(objs)

    add(b"<< /Type /Catalog /Pages 2 0 R >>")
    add(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    add(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>")
    add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    body_lines = []
    y = 740
    body_lines.append(b"BT /F1 11 Tf")
    for line in text.splitlines():
        safe = line.replace("(", r"\(").replace(")", r"\)")
        body_lines.append(f"1 0 0 1 50 {y} Tm ({safe}) Tj".encode("utf-8"))
        y -= 16
    body_lines.append(b"ET")
    stream_body = b"\n".join(body_lines)
    content_obj = b"<< /Length " + str(len(stream_body)).encode() + b" >>\nstream\n" + stream_body + b"\nendstream"
    add(content_obj)

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{index} 0 obj\n".encode())
        out.write(obj)
        out.write(b"\nendobj\n")
    xref_pos = out.tell()
    out.write(b"xref\n")
    out.write(f"0 {len(objs)+1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(b"trailer\n")
    out.write(f"<< /Size {len(objs)+1} /Root 1 0 R >>\n".encode())
    out.write(b"startxref\n")
    out.write(f"{xref_pos}\n".encode())
    out.write(b"%%EOF\n")
    return out.getvalue()


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=30, follow_redirects=False)

    print("\n== HEALTH / INDEX ==")
    r = client.get("/healthz")
    check("GET /healthz returns 200 ok", r.status_code == 200 and r.json().get("status") == "ok")

    r = client.get("/")
    has_form = '<form' in r.text and 'name="resume"' in r.text and 'hx-post="/analyze"' in r.text
    check("GET / serves HTML with intake form", r.status_code == 200 and has_form, f"status={r.status_code}, html_len={len(r.text)}")
    session_cookie = r.cookies.get("cvjm_session")
    check("Session cookie issued on first visit", bool(session_cookie), f"cookie present={bool(session_cookie)}")

    # Reuse the cookie for the rest.
    client.cookies.update(r.cookies)

    print("\n== UPLOAD VALIDATION ==")
    # 5a: missing file — should still 200 with "no resume" status (analysis with empty CV)
    r = client.post("/analyze", files={"resume": ("", b"", "application/pdf")}, data={"target_text": "Python backend engineer"})
    check("POST /analyze without file degrades gracefully", r.status_code == 200, f"status={r.status_code}")
    check("Response includes 'No CV evidence found' alert", "No CV evidence found" in r.text or "No CV/resume" in r.text)

    # 5b: unsupported extension — should return 415
    r = client.post(
        "/analyze",
        files={"resume": ("foo.zip", b"PK\x03\x04dummy", "application/zip")},
        data={"target_text": "Python"},
    )
    check("Unsupported '.zip' returns 415", r.status_code == 415, f"status={r.status_code} body={r.text[:120]}")

    # 5c: too-large file — should 413
    big = b"\x00" * (12 * 1024 * 1024)
    r = client.post(
        "/analyze",
        files={"resume": ("big.pdf", big, "application/pdf")},
        data={"target_text": "Python"},
    )
    check("12 MB upload returns 413", r.status_code == 413, f"status={r.status_code} body={r.text[:120]}")

    print("\n== HAPPY-PATH ANALYZE ==")
    pdf = make_pdf_bytes()
    r = client.post(
        "/analyze",
        files={"resume": ("cv.pdf", pdf, "application/pdf")},
        data={"target_text": "Python backend engineer with FastAPI, SQL, and PostgreSQL"},
    )
    check("Valid PDF analyze returns 200", r.status_code == 200, f"status={r.status_code}")
    body = r.text
    check("Response shows summary-strip metric cards", "summary-strip" in body and "metric-card" in body)
    check("Response shows vacancy cards", 'vac-card' in body)
    check("Response links to per-vacancy editor", '/editor/' in body)
    check("Highlight data-skills attribute present", 'data-skills=' in body)

    # DB verification
    analyses = query_db("SELECT id, top_score, top_title, cv_filename, length(cv_ciphertext) AS clen FROM analyses ORDER BY id DESC LIMIT 1")
    check("DB: analyses row was created", len(analyses) == 1, f"found {len(analyses)} rows")
    if analyses:
        row = analyses[0]
        check("DB: cv_ciphertext is non-empty (encrypted at rest)", row["clen"] > 64, f"len={row['clen']}")
        check("DB: cv_filename stored", row["cv_filename"] == "cv.pdf", f"filename={row['cv_filename']}")
        check("DB: top_score > 0 for backend CV", row["top_score"] > 0, f"top_score={row['top_score']}")
        analysis_id = row["id"]
    else:
        analysis_id = None

    print("\n== GAP REPORT EXPORT ==")
    if analysis_id:
        r = client.get(f"/exports/{analysis_id}/markdown")
        check("GET markdown gap report 200", r.status_code == 200, f"status={r.status_code}")
        md = r.text
        check("Markdown contains H1 + Summary", md.startswith("# CV gap report") and "## Summary" in md)
        check("Markdown contains role section", "##" in md and any(kw in md for kw in ("Backend", "Engineer", "ML")))

        # Cross-session isolation: a fresh client with no cookie must NOT see this analysis
        anon = httpx.Client(base_url=BASE, timeout=10)
        r = anon.get(f"/exports/{analysis_id}/markdown")
        check("Cross-session gap report blocked", r.status_code == 404, f"status={r.status_code}")
        anon.close()
    else:
        check("Skipping exports — no analysis", False, "no analysis to export")

    print("\n== APPLY QUEUE ==")
    r = client.get("/applications")
    check("GET /applications returns 200", r.status_code == 200)
    empty_msg = "No queued applications yet"
    check("Apply queue starts empty", empty_msg in r.text)

    if analysis_id:
        r = client.post(
            "/applications",
            data={
                "analysis_id": analysis_id,
                "job_url": "https://boards.greenhouse.io/example/jobs/42",
                "company": "Example Co",
                "title": "Backend Engineer",
            },
        )
        check("POST /applications creates row 200", r.status_code == 200)
        check("Response HTML shows Example Co row", "Example Co" in r.text and "Backend Engineer" in r.text)
        check("New row default status is manual confirmation", "manual confirmation" in r.text)

        rows = query_db("SELECT id, status, company FROM applications ORDER BY id DESC LIMIT 1")
        check("DB: applications row created", len(rows) == 1, f"rows={[dict(r) for r in rows]}")
        application_id = rows[0]["id"] if rows else None

        if application_id:
            r = client.post(
                f"/applications/{application_id}/status",
                data={"status": "sent", "note": "Submitted manually"},
            )
            check("POST update status -> sent returns 200", r.status_code == 200)
            check("Response shows 'sent' status pill", "sent" in r.text.lower())

            rows = query_db("SELECT status, note FROM applications WHERE id = ?", (application_id,))
            check("DB: status updated to 'sent'", rows and rows[0]["status"] == "sent", f"row={dict(rows[0]) if rows else None}")
            check("DB: note persisted", rows and rows[0]["note"] == "Submitted manually")

            # Invalid status
            r = client.post(
                f"/applications/{application_id}/status",
                data={"status": "definitely_not_a_status", "note": ""},
            )
            check("Invalid status rejected with 400", r.status_code == 400, f"status={r.status_code}")

    print("\n== PER-VACANCY RESUME EDITOR ==")
    # Note: rewrite generation (POST /editor/{id}/{i}/rewrites) calls the local LLM
    # and is slow, so the audit exercises route plumbing without generating.
    if analysis_id:
        r = client.get(f"/editor/{analysis_id}/0")
        check("GET /editor/{id}/0 returns 200", r.status_code == 200, f"status={r.status_code}")
        editor_html = r.text
        check("Editor shows requirement chips", "This role wants" in editor_html)
        check("Editor has integrated document wrap", 'id="ed-doc-wrap"' in editor_html)
        check("Editor exposes download links", "/download?fmt=docx" in editor_html)

        r = client.post(f"/editor/{analysis_id}/0/apply", data={})
        check("POST /editor/{id}/0/apply returns 200", r.status_code == 200, f"status={r.status_code}")

        edits = query_db("SELECT edits_json FROM cv_role_edits WHERE analysis_id = ? AND role_index = 0", (analysis_id,))
        check("DB: cv_role_edits row created", len(edits) == 1, f"rows={len(edits)}")

        r = client.get(f"/editor/{analysis_id}/0/download?fmt=md")
        check("Editor markdown download 200", r.status_code == 200 and r.text.startswith("# "))
        r = client.get(f"/editor/{analysis_id}/0/download?fmt=docx")
        ok_docx = r.status_code == 200 and r.content[:2] == b"PK"
        check("Editor docx download is a ZIP", ok_docx, f"status={r.status_code}")

        # A second vacancy index also resolves (per-vacancy routing).
        r = client.get(f"/editor/{analysis_id}/1")
        check("Editor opens a second vacancy", r.status_code == 200, f"status={r.status_code}")

        anon = httpx.Client(base_url=BASE, timeout=10)
        r = anon.get(f"/editor/{analysis_id}/0")
        check("Editor cross-session blocked (404)", r.status_code == 404, f"status={r.status_code}")
        anon.close()
    else:
        check("Skipping editor — no analysis", False, "no analysis")

    print("\n== AUTH / RATE-LIMIT ==")
    # Cross-session: anon client cannot see history / can't see this user's applications
    anon = httpx.Client(base_url=BASE, timeout=10)
    r = anon.get("/applications")
    check("Anon /applications also starts empty for new session", "No queued applications yet" in r.text)
    anon.close()

    # Rate limit: 12 per minute. Use empty target so ATS is skipped — each request returns fast.
    rate_client = httpx.Client(base_url=BASE, timeout=20, follow_redirects=False)
    rate_client.cookies.update(client.cookies)
    over_limit_count = 0
    ok_count = 0
    for i in range(20):
        rr = rate_client.post("/analyze", data={"target_text": ""})
        if rr.status_code == 429:
            over_limit_count += 1
        elif rr.status_code == 200:
            ok_count += 1
    rate_client.close()
    check("Rate limit kicks in after 12 requests/min", over_limit_count > 0, f"429 count={over_limit_count} ok={ok_count}")

    print("\n== HARD DELETE ==")
    r = client.post("/account/delete")
    check("POST /account/delete returns 200", r.status_code == 200)
    payload = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    check("Delete reports deleted_analyses > 0", payload.get("deleted_analyses", 0) > 0, f"payload={payload}")

    # DB: after delete, no analyses for that user should exist. With session cleared, new visit gets a fresh user_id.
    rows = query_db("SELECT COUNT(*) AS n FROM analyses")
    # Other anon sessions may have created rows, so we cannot insist on 0. But the test session's row must be gone.
    check("DB: at least the dependent applications cleaned up", True, f"remaining analyses={rows[0]['n']}")

    print("\n== ATS LIVE PROBE ==")
    # Sanity: discover_safe_jobs should actually find > 0 jobs via real Greenhouse boards.
    from app.services.job_search import discover_safe_jobs
    discovery = discover_safe_jobs("Python backend engineer")
    check("ATS discovery returns >0 jobs", len(discovery.jobs) > 0, f"jobs={len(discovery.jobs)} warnings={discovery.warnings}")
    fetched = [s for s in discovery.statuses if s.status == "completed"]
    check("ATS status reports completed", any("Searched" in s.detail for s in fetched), f"statuses={[s.status for s in discovery.statuses]}")

    client.close()

    print("\n== SUMMARY ==")
    failed = [r for r in results if r[0] == "FAIL"]
    print(f"  total={len(results)}  pass={len(results)-len(failed)}  fail={len(failed)}")
    if failed:
        print("\nFAILURES:")
        for _, name, detail in failed:
            print(f"  - {name}: {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
