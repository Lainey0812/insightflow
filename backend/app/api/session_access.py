"""Local V1 session capabilities; this is not an account/tenant identity system."""
import json
import hashlib
import secrets
from contextlib import closing
from fastapi import Request
from app.domain.errors import AppError


def issue_session_token(database, session_id):
    token = secrets.token_urlsafe(32)
    with closing(database.connect()) as conn, conn:
        conn.execute("INSERT INTO session_access VALUES (?, ?)",
                     (session_id, hashlib.sha256(token.encode()).hexdigest()))
    return token


def session_guard(database):
    async def guard(request: Request):
        sid = request.path_params.get("session_id")
        with closing(database.connect()) as conn:
            if sid is None and request.url.path.startswith("/api/v1/executions"):
                if request.method == "POST" and not request.path_params.get("execution_id"):
                    try:
                        sid = (await request.json()).get("session_id")
                    except (ValueError, AttributeError):
                        return  # Request schema reports malformed bodies.
                else:
                    row = conn.execute("SELECT session_id FROM executions WHERE id=?",
                        (request.path_params.get("execution_id"),)).fetchone()
                    sid = row["session_id"] if row else None
            is_report = request.url.path.startswith("/api/v1/reports/")
            if sid is None and is_report:
                row = conn.execute("SELECT audit FROM analysis_reports WHERE id=?", (request.path_params.get("report_id"),)).fetchone()
                sid = json.loads(row['audit']).get('session_id') if row else None
            if not isinstance(sid, str):
                return
            row = conn.execute("SELECT token_hash FROM session_access WHERE session_id=?", (sid,)).fetchone()
        if row:
            token = request.headers.get("X-Session-Token", "")
            if is_report and not token:
                try:
                    keys = json.loads(request.headers.get("X-Session-Keys", "{}"))
                    token = keys.get(sid, "") if isinstance(keys, dict) else ""
                    if not isinstance(token, str):
                        token = ""
                except ValueError:
                    token = ""
            if not secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(), row["token_hash"]):
                raise AppError("SESSION_ACCESS_DENIED", "缺少此会话的访问凭证，不能读取、修改、批准或执行。", 403)
    return guard


def visible_sessions(database, items, request):
    """Do not leak protected session titles through the shared history list."""
    import json
    try:
        supplied = json.loads(request.headers.get("X-Session-Keys", "{}"))
        if not isinstance(supplied, dict):
            supplied = {}
    except ValueError:
        supplied = {}
    single = request.headers.get("X-Session-Token", "")
    with closing(database.connect()) as conn:
        hashes = {r["session_id"]: r["token_hash"] for r in conn.execute("SELECT * FROM session_access")}
    def allowed(item):
        expected = hashes.get(item["id"])
        token = supplied.get(item["id"], single)
        return expected is None or (isinstance(token, str) and secrets.compare_digest(
            hashlib.sha256(token.encode()).hexdigest(), expected))
    return [item for item in items if allowed(item)]
