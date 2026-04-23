import json
import os
import sqlite3
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "sqlite_schema.sql"
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "audicare_center.db")))


def dict_factory(cursor, row):
    return {cursor.description[idx][0]: row[idx] for idx in range(len(cursor.description))}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    conn = get_db()
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


class PTAHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _json(self, payload, status=200):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length or 0)
        return json.loads(raw.decode("utf-8") or "{}")

    def _table(self, name):
        conn = get_db()
        try:
            rows = conn.execute(f"SELECT * FROM {name} ORDER BY id DESC").fetchall()
            return rows
        finally:
            conn.close()

    def _row(self, name, row_id):
        conn = get_db()
        try:
            row = conn.execute(f"SELECT * FROM {name} WHERE id = ?", (row_id,)).fetchone()
            return row
        finally:
            conn.close()

    def do_OPTIONS(self):
        self._json({"ok": True})

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            return self._json({"ok": True, "database": str(DB_PATH)})
        if parsed.path == "/api/site-content":
            return self._json(
                {
                    "jobs": self._table("jobs"),
                    "news": self._table("news_items"),
                }
            )
        if parsed.path == "/api/jobs":
            return self._json(self._table("jobs"))
        if parsed.path == "/api/news":
            return self._json(self._table("news_items"))
        if parsed.path == "/api/centers":
            return self._json(self._table("centers"))
        if parsed.path == "/api/users":
            role = parse_qs(parsed.query).get("role", [""])[0]
            rows = self._table("users")
            if role:
                rows = [row for row in rows if row["role"] == role]
            return self._json(rows)
        if parsed.path == "/api/children":
            return self._json(self._table("children"))
        if parsed.path == "/api/tests":
            return self._json(self._table("tests"))
        if parsed.path == "/api/reports":
            return self._json(self._table("reports"))
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        payload = self._read_json()
        conn = get_db()
        try:
            if parsed.path == "/api/jobs":
                cursor = conn.execute(
                    """
                    INSERT INTO jobs (title, org, cat, edu, loc, sal, deadline, link)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload.get("title"),
                        payload.get("org"),
                        payload.get("cat", "govt"),
                        payload.get("edu", "N/A"),
                        payload.get("loc", "N/A"),
                        payload.get("sal", "N/A"),
                        payload.get("deadline", "Open"),
                        payload.get("link", ""),
                    ),
                )
                row = conn.execute("SELECT * FROM jobs WHERE id = ?", (cursor.lastrowid,)).fetchone()
                conn.commit()
                return self._json(row, 201)
            if parsed.path == "/api/news":
                cursor = conn.execute(
                    "INSERT INTO news_items (text, type) VALUES (?, ?)",
                    (
                        payload.get("text"),
                        payload.get("type", "new"),
                    ),
                )
                row = conn.execute("SELECT * FROM news_items WHERE id = ?", (cursor.lastrowid,)).fetchone()
                conn.commit()
                return self._json(row, 201)
            if parsed.path == "/api/centers":
                cursor = conn.execute(
                    "INSERT INTO centers (center_code, name, address, city, contact) VALUES (?, ?, ?, ?, ?)",
                    (
                        payload.get("center_code"),
                        payload.get("name"),
                        payload.get("address"),
                        payload.get("city"),
                        payload.get("contact"),
                    ),
                )
                conn.commit()
                return self._json({"id": cursor.lastrowid, "ok": True}, 201)
            if parsed.path == "/api/users":
                cursor = conn.execute(
                    """
                    INSERT INTO users (public_id, role, name, username, password_hash, mobile, license_no, center_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload.get("public_id"),
                        payload.get("role"),
                        payload.get("name"),
                        payload.get("username"),
                        payload.get("password_hash"),
                        payload.get("mobile"),
                        payload.get("license_no"),
                        payload.get("center_id"),
                    ),
                )
                conn.commit()
                return self._json({"id": cursor.lastrowid, "ok": True}, 201)
            if parsed.path == "/api/children":
                cursor = conn.execute(
                    """
                    INSERT INTO children (
                      child_id, name, age, father_name, mobile, gender, dob, mother_name,
                      address, referred_by, enrolled_by, center_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload.get("child_id"),
                        payload.get("name"),
                        payload.get("age"),
                        payload.get("father_name"),
                        payload.get("mobile"),
                        payload.get("gender"),
                        payload.get("dob"),
                        payload.get("mother_name"),
                        payload.get("address"),
                        payload.get("referred_by"),
                        payload.get("enrolled_by"),
                        payload.get("center_id"),
                    ),
                )
                conn.commit()
                return self._json({"id": cursor.lastrowid, "ok": True}, 201)
            if parsed.path == "/api/tests":
                cursor = conn.execute(
                    """
                    INSERT INTO tests (
                      test_id, child_ref, operator_ref, right_ear_json, left_ear_json, pta_right, pta_left,
                      classification_right, classification_left, duration_sec, summary_text, recommendation_text,
                      hearing_aid_guidance, audiogram_svg, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload.get("test_id"),
                        payload.get("child_ref"),
                        payload.get("operator_ref"),
                        json.dumps(payload.get("right_ear_json", {})),
                        json.dumps(payload.get("left_ear_json", {})),
                        payload.get("pta_right"),
                        payload.get("pta_left"),
                        payload.get("classification_right"),
                        payload.get("classification_left"),
                        payload.get("duration_sec"),
                        payload.get("summary_text"),
                        payload.get("recommendation_text"),
                        payload.get("hearing_aid_guidance"),
                        payload.get("audiogram_svg"),
                        payload.get("status", "submitted"),
                    ),
                )
                test_pk = cursor.lastrowid
                for ear_key in ("right", "left"):
                    ear_values = payload.get(f"{ear_key}_ear_json", {}) or {}
                    for freq, value in ear_values.items():
                        conn.execute(
                            "INSERT OR REPLACE INTO thresholds (test_ref, ear, frequency_hz, threshold_dbhl) VALUES (?, ?, ?, ?)",
                            (test_pk, ear_key, int(freq), str(value)),
                        )
                conn.commit()
                return self._json({"id": test_pk, "ok": True}, 201)
            if parsed.path == "/api/reports":
                cursor = conn.execute(
                    """
                    INSERT INTO reports (
                      report_id, test_ref, audiologist_ref, classification_right, classification_left,
                      remarks, recommendation, summary_text, hearing_aid_guidance, audiogram_svg, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload.get("report_id"),
                        payload.get("test_ref"),
                        payload.get("audiologist_ref"),
                        payload.get("classification_right"),
                        payload.get("classification_left"),
                        payload.get("remarks"),
                        payload.get("recommendation"),
                        payload.get("summary_text"),
                        payload.get("hearing_aid_guidance"),
                        payload.get("audiogram_svg"),
                        payload.get("status", "verified"),
                    ),
                )
                conn.commit()
                return self._json({"id": cursor.lastrowid, "ok": True}, 201)
            return self._json({"error": "Unsupported endpoint"}, 404)
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            return self._json({"error": str(exc)}, 400)
        finally:
            conn.close()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        row_id = parse_qs(parsed.query).get("id", [""])[0]
        if not row_id.isdigit():
            return self._json({"error": "Valid id is required"}, 400)
        conn = get_db()
        try:
            if parsed.path == "/api/jobs":
                deleted = conn.execute("DELETE FROM jobs WHERE id = ?", (int(row_id),)).rowcount
                conn.commit()
                return self._json({"ok": deleted > 0, "deleted": deleted})
            if parsed.path == "/api/news":
                deleted = conn.execute("DELETE FROM news_items WHERE id = ?", (int(row_id),)).rowcount
                conn.commit()
                return self._json({"ok": deleted > 0, "deleted": deleted})
            return self._json({"error": "Unsupported endpoint"}, 404)
        finally:
            conn.close()


if __name__ == "__main__":
    init_db()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), PTAHandler)
    print(f"Shivanshu Cafe server running at http://{host}:{port}/")
    server.serve_forever()
