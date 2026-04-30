import json
import hashlib
import os
import shutil
import sqlite3
from contextlib import suppress
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "sqlite_schema.sql"
DEFAULT_RENDER_DATA_DIR = Path("/opt/render/project/src/data")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")


def resolve_data_dir():
    explicit = os.getenv("DATA_DIR")
    if explicit:
        return Path(explicit)
    if os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"):
        return DEFAULT_RENDER_DATA_DIR
    return ROOT


DATA_DIR = resolve_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "audicare_center.db")))
LEGACY_DB_PATH = ROOT / "audicare_center.db"
BACKUP_DB_PATH = DATA_DIR / "audicare_center.backup.db"
DEFAULT_ADMIN_EMAIL = "admin"
DEFAULT_ADMIN_MOBILE = "9999999999"
DEFAULT_ADMIN_PASSWORD = "admin@123"

JOB_COLUMNS = {
    "status": "TEXT NOT NULL DEFAULT 'published'",
    "post_date": "TEXT",
    "apply_date": "TEXT",
    "updated_at": "TEXT",
}


def dict_factory(cursor, row):
    return {cursor.description[idx][0]: row[idx] for idx in range(len(cursor.description))}


class DBResult:
    def __init__(self, cursor, lastrowid=None):
        self._cursor = cursor
        self.lastrowid = lastrowid

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class DBConnection:
    def __init__(self, conn, kind):
        self._conn = conn
        self.kind = kind

    def _sql(self, sql):
        if self.kind == "postgres":
            return sql.replace("?", "%s")
        return sql

    def execute(self, sql, params=()):
        prepared = self._sql(sql)
        cursor = self._conn.cursor()
        auto_return_id = False
        if self.kind == "postgres" and prepared.lstrip().upper().startswith("INSERT") and "RETURNING" not in prepared.upper():
            prepared = prepared.rstrip().rstrip(";") + " RETURNING id"
            auto_return_id = True
        cursor.execute(prepared, params)
        lastrowid = None
        if self.kind == "sqlite" and prepared.lstrip().upper().startswith("INSERT"):
            lastrowid = getattr(cursor, "lastrowid", None)
        elif auto_return_id:
            with suppress(Exception):
                row = cursor.fetchone()
                if row is not None:
                    lastrowid = row["id"] if isinstance(row, dict) else row[0]
        return DBResult(cursor, lastrowid)

    def executescript(self, script):
        if self.kind == "sqlite":
            return self._conn.executescript(script)
        statements = [stmt.strip() for stmt in script.split(";") if stmt.strip()]
        cursor = self._conn.cursor()
        for stmt in statements:
            cursor.execute(self._sql(stmt))
        return cursor

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def postgres_dsn():
    if "sslmode=" in DATABASE_URL:
        return DATABASE_URL
    sep = "&" if "?" in DATABASE_URL else "?"
    return f"{DATABASE_URL}{sep}sslmode=require"


def get_db():
    if USE_POSTGRES:
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
        except ImportError as exc:
            raise RuntimeError("psycopg2-binary is required when DATABASE_URL is set") from exc
        conn = psycopg2.connect(postgres_dsn(), cursor_factory=RealDictCursor)
        conn.autocommit = False
        return DBConnection(conn, "postgres")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = FULL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return DBConnection(conn, "sqlite")


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def hash_password(password):
    return hashlib.sha256((password or "").encode("utf-8")).hexdigest()


def table_columns(conn, table):
    if USE_POSTGRES:
        rows = conn.execute(
            """
            SELECT column_name AS name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = ?
            """,
            (table,),
        ).fetchall()
        return {row["name"] for row in rows}
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def ensure_column(conn, table, name, ddl):
    if name not in table_columns(conn, table):
        if USE_POSTGRES:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {ddl}")
        else:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def bootstrap_db_files():
    if USE_POSTGRES:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists() and DB_PATH.stat().st_size > 0:
        return
    for candidate in (LEGACY_DB_PATH, BACKUP_DB_PATH):
        if candidate.exists() and candidate.stat().st_size > 0:
            shutil.copy2(candidate, DB_PATH)
            return


def backup_db(conn):
    if USE_POSTGRES:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = BACKUP_DB_PATH.with_suffix(".tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    backup_conn = sqlite3.connect(tmp_path)
    try:
        conn.backup(backup_conn)
        backup_conn.commit()
    finally:
        backup_conn.close()
    tmp_path.replace(BACKUP_DB_PATH)


def commit_db(conn):
    conn.commit()
    if USE_POSTGRES:
        return
    try:
        backup_db(conn)
    except Exception as exc:
        print(f"Backup warning: {exc}")


def setup_postgres_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS centers (
          id SERIAL PRIMARY KEY,
          center_code TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          address TEXT,
          city TEXT,
          contact TEXT,
          created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
          id SERIAL PRIMARY KEY,
          public_id TEXT NOT NULL UNIQUE,
          role TEXT NOT NULL CHECK (role IN ('admin', 'audiologist', 'operator')),
          name TEXT NOT NULL,
          username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          mobile TEXT,
          license_no TEXT,
          center_id INTEGER,
          created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
          FOREIGN KEY (center_id) REFERENCES centers(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS children (
          id SERIAL PRIMARY KEY,
          child_id TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          age INTEGER NOT NULL,
          father_name TEXT NOT NULL,
          mobile TEXT NOT NULL,
          gender TEXT,
          dob TEXT,
          mother_name TEXT,
          address TEXT,
          referred_by TEXT,
          enrolled_by INTEGER NOT NULL,
          center_id INTEGER,
          created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
          FOREIGN KEY (enrolled_by) REFERENCES users(id),
          FOREIGN KEY (center_id) REFERENCES centers(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tests (
          id SERIAL PRIMARY KEY,
          test_id TEXT NOT NULL UNIQUE,
          child_ref INTEGER NOT NULL,
          operator_ref INTEGER NOT NULL,
          right_ear_json TEXT NOT NULL,
          left_ear_json TEXT NOT NULL,
          pta_right REAL,
          pta_left REAL,
          classification_right TEXT,
          classification_left TEXT,
          duration_sec INTEGER,
          summary_text TEXT,
          recommendation_text TEXT,
          hearing_aid_guidance TEXT,
          audiogram_svg TEXT,
          status TEXT NOT NULL DEFAULT 'submitted',
          created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
          FOREIGN KEY (child_ref) REFERENCES children(id),
          FOREIGN KEY (operator_ref) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS thresholds (
          id SERIAL PRIMARY KEY,
          test_ref INTEGER NOT NULL,
          ear TEXT NOT NULL CHECK (ear IN ('right', 'left')),
          frequency_hz INTEGER NOT NULL,
          threshold_dbhl TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
          UNIQUE (test_ref, ear, frequency_hz),
          FOREIGN KEY (test_ref) REFERENCES tests(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
          id SERIAL PRIMARY KEY,
          report_id TEXT NOT NULL UNIQUE,
          test_ref INTEGER NOT NULL UNIQUE,
          audiologist_ref INTEGER NOT NULL,
          classification_right TEXT,
          classification_left TEXT,
          remarks TEXT,
          recommendation TEXT,
          summary_text TEXT,
          hearing_aid_guidance TEXT,
          audiogram_svg TEXT,
          status TEXT NOT NULL DEFAULT 'verified',
          verified_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
          FOREIGN KEY (test_ref) REFERENCES tests(id),
          FOREIGN KEY (audiologist_ref) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
          id SERIAL PRIMARY KEY,
          title TEXT NOT NULL,
          org TEXT NOT NULL,
          cat TEXT NOT NULL DEFAULT 'govt',
          edu TEXT NOT NULL DEFAULT 'N/A',
          loc TEXT NOT NULL DEFAULT 'N/A',
          sal TEXT NOT NULL DEFAULT 'N/A',
          status TEXT NOT NULL DEFAULT 'published',
          post_date TEXT,
          apply_date TEXT,
          deadline TEXT NOT NULL DEFAULT 'Open',
          link TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
          created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_items (
          id SERIAL PRIMARY KEY,
          text TEXT NOT NULL,
          type TEXT NOT NULL DEFAULT 'new',
          updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
          created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS site_users (
          id SERIAL PRIMARY KEY,
          role TEXT NOT NULL CHECK (role IN ('admin', 'student')),
          name TEXT NOT NULL,
          email TEXT NOT NULL UNIQUE,
          mobile TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          course TEXT,
          created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
          updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS site_saved_jobs (
          id SERIAL PRIMARY KEY,
          student_id INTEGER NOT NULL,
          job_id INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
          UNIQUE(student_id, job_id),
          FOREIGN KEY (student_id) REFERENCES site_users(id) ON DELETE CASCADE,
          FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS site_meta (
          id SERIAL PRIMARY KEY,
          key TEXT NOT NULL UNIQUE,
          value TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
          updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
        )
        """
    )


def seed_postgres_defaults(conn):
    if not conn.execute("SELECT 1 AS ok FROM site_users WHERE role = 'admin' LIMIT 1").fetchone():
        conn.execute(
            """
            INSERT INTO site_users (role, name, email, mobile, password_hash, course, created_at, updated_at)
            VALUES ('admin', ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                "Administrator",
                DEFAULT_ADMIN_EMAIL,
                DEFAULT_ADMIN_MOBILE,
                hash_password(DEFAULT_ADMIN_PASSWORD),
                now_iso(),
                now_iso(),
            ),
        )

    if conn.execute("SELECT 1 AS ok FROM site_meta WHERE key = 'seeded_defaults' LIMIT 1").fetchone():
        return

    jobs_count = conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"]
    news_count = conn.execute("SELECT COUNT(*) AS c FROM news_items").fetchone()["c"]

    if jobs_count == 0 and news_count == 0:
        today = now_iso()[:10]

        default_jobs = [
            ("Railway Group D Recruitment 2026 (10,000+ Posts)", "RRB / Indian Railways", "railway", "10th Pass", "All India", "₹18,000–₹56,900", "30 April 2026", "https://indianrailways.gov.in"),
            ("Bihar Police Constable Bharti 2026 (21,391 Posts)", "Bihar Police", "defence", "12th Pass", "Bihar", "₹21,700+", "10 May 2026", "https://csbc.bihar.gov.in"),
            ("Bihar SSC Inter Level Recruitment 2026", "Bihar Staff Selection Commission", "govt", "12th Pass", "Bihar", "₹20,000–₹60,000", "15 May 2026", "https://bssc.bihar.gov.in"),
            ("IBPS PO Recruitment 2026", "Institute of Banking Personnel", "bank", "Graduate", "All India", "₹36,000–₹63,840", "20 May 2026", "https://ibps.in"),
            ("Indian Army Agniveer Recruitment 2026", "Indian Army", "defence", "10th/12th Pass", "All India", "₹30,000–₹40,000", "25 April 2026", "https://joinindianarmy.nic.in"),
            ("SBI Clerk (Junior Associate) Bharti 2026", "State Bank of India", "bank", "Graduate", "All India", "₹26,000–₹35,000", "12 May 2026", "https://sbi.co.in"),
            ("SSC CHSL (10+2 Level) Exam 2026", "Staff Selection Commission", "govt", "12th Pass", "All India", "₹25,500–₹81,100", "3 May 2026", "https://ssc.nic.in"),
            ("Data Entry Operator - Work From Home", "Various Companies", "private", "10th/12th Pass", "Bihar / Remote", "₹12,000–₹25,000", "Open", ""),
            ("BSEB Inter Admission 2026-28 Online", "Bihar School Examination Board", "admission", "10th Pass", "Bihar", "N/A", "18 April 2026", "http://ofssbihar.org"),
        ]
        for title, org, cat, edu, loc, sal, deadline, link in default_jobs:
            conn.execute(
                """
                INSERT INTO jobs (title, org, cat, edu, loc, sal, status, post_date, apply_date, deadline, link, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'published', ?, ?, ?, ?, ?)
                """,
                (title, org, cat, edu, loc, sal, today, deadline, deadline, link, now_iso()),
            )

        default_news = [
            ("BSEB INTER ADMISSION SESSION 2026-28 ONLINE — Last Date: 18 April", "urgent"),
            ("Bihar PE PM PMM Entrance Form Online 2026 — Last Date: 21.04.2026", "new"),
            ("Bihar ITI CAT Entrance Form Online 2026 — Last Date: 14.04.2026", "new"),
            ("Agniveer Army Form Online 2026 — Last Date: 10-04-2026", "urgent"),
            ("CBSE 10th Board Result 2026 — Check Karein Abhi", "info"),
            ("BPSC AEDO Admit Card 2026 Released", "new"),
            ("DELE.d Application Form 2026 — Last Date: 09 January 2026", "info"),
            ("UP Police Constable Bharti 2026 — Online Form Open", "new"),
        ]
        for text, kind in default_news:
            conn.execute(
                "INSERT INTO news_items (text, type, updated_at) VALUES (?, ?, ?)",
                (text, kind, now_iso()),
            )

    conn.execute(
        "INSERT INTO site_meta (key, value, created_at, updated_at) VALUES ('seeded_defaults', '1', ?, ?)",
        (now_iso(), now_iso()),
    )


def migrate_db(conn):
    if USE_POSTGRES:
        setup_postgres_schema(conn)
        for name, ddl in JOB_COLUMNS.items():
            ensure_column(conn, "jobs", name, ddl)
        ensure_column(conn, "news_items", "updated_at", "TEXT")
        seed_postgres_defaults(conn)
        conn.execute("UPDATE jobs SET status = COALESCE(status, 'published')")
        conn.execute(
            """
            UPDATE jobs
            SET post_date = COALESCE(post_date, substr(created_at, 1, 10)),
                apply_date = COALESCE(apply_date, deadline),
                updated_at = COALESCE(updated_at, created_at)
            """
        )
        conn.execute("UPDATE news_items SET updated_at = COALESCE(updated_at, created_at)")
        return

    for name, ddl in JOB_COLUMNS.items():
        ensure_column(conn, "jobs", name, ddl)

    ensure_column(conn, "news_items", "updated_at", "TEXT")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS site_users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          role TEXT NOT NULL CHECK (role IN ('admin', 'student')),
          name TEXT NOT NULL,
          email TEXT NOT NULL UNIQUE,
          mobile TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          course TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS site_saved_jobs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          student_id INTEGER NOT NULL,
          job_id INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(student_id, job_id),
          FOREIGN KEY (student_id) REFERENCES site_users(id) ON DELETE CASCADE,
          FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO site_users (id, role, name, email, mobile, password_hash, course)
        VALUES (?, 'admin', 'Administrator', ?, ?, ?, NULL)
        """,
        (1, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_MOBILE, hash_password(DEFAULT_ADMIN_PASSWORD)),
    )
    conn.execute("UPDATE jobs SET status = COALESCE(status, 'published')")
    conn.execute(
        """
        UPDATE jobs
        SET post_date = COALESCE(post_date, substr(created_at, 1, 10)),
            apply_date = COALESCE(apply_date, deadline),
            updated_at = COALESCE(updated_at, created_at)
        """
    )
    conn.execute("UPDATE news_items SET updated_at = COALESCE(updated_at, created_at)")


def init_db():
    conn = get_db()
    try:
        if USE_POSTGRES:
            migrate_db(conn)
        else:
            bootstrap_db_files()
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            migrate_db(conn)
        commit_db(conn)
    finally:
        conn.close()


def fetch_jobs(conn, include_all=False):
    where = "" if include_all else " WHERE COALESCE(status, 'published') = 'published'"
    return conn.execute(f"SELECT * FROM jobs{where} ORDER BY id DESC").fetchall()


def fetch_news(conn):
    return conn.execute("SELECT * FROM news_items ORDER BY id DESC").fetchall()


def fetch_students(conn):
    if USE_POSTGRES:
        rows = conn.execute(
            """
            SELECT
              u.id, u.role, u.name, u.email, u.mobile, u.course, u.created_at, u.updated_at,
              COALESCE(STRING_AGG(sj.job_id::text, ','), '') AS saved_ids
            FROM site_users u
            LEFT JOIN site_saved_jobs sj ON sj.student_id = u.id
            WHERE u.role = 'student'
            GROUP BY u.id
            ORDER BY u.id DESC
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT
              u.id, u.role, u.name, u.email, u.mobile, u.course, u.created_at, u.updated_at,
              COALESCE(GROUP_CONCAT(sj.job_id), '') AS saved_ids
            FROM site_users u
            LEFT JOIN site_saved_jobs sj ON sj.student_id = u.id
            WHERE u.role = 'student'
            GROUP BY u.id
            ORDER BY u.id DESC
            """
        ).fetchall()
    for row in rows:
        saved_ids = [int(x) for x in row.pop("saved_ids", "").split(",") if x]
        row["saved_job_ids"] = saved_ids
        row["saved_count"] = len(saved_ids)
    return rows


def fetch_user_by_identifier(conn, identifier):
    identifier = (identifier or "").strip().lower()
    if identifier == "admin":
        return conn.execute("SELECT * FROM site_users WHERE role = 'admin' LIMIT 1").fetchone()
    return conn.execute(
        "SELECT * FROM site_users WHERE lower(email) = ? OR mobile = ? LIMIT 1",
        (identifier, identifier),
    ).fetchone()


def fetch_saved_ids(conn, student_id):
    rows = conn.execute(
        "SELECT job_id FROM site_saved_jobs WHERE student_id = ? ORDER BY id DESC",
        (student_id,),
    ).fetchall()
    return [row["job_id"] for row in rows]


def user_payload(row, conn=None):
    if not row:
        return None
    payload = {
        "id": row["id"],
        "role": row["role"],
        "name": row["name"],
        "email": row["email"],
        "mobile": row["mobile"],
        "course": row.get("course"),
    }
    if conn and row["role"] == "student":
        saved_ids = fetch_saved_ids(conn, row["id"])
        payload["saved_job_ids"] = saved_ids
        payload["saved_count"] = len(saved_ids)
    return payload


def job_payload(row):
    post_date = row.get("post_date") or (row.get("created_at") or "")[:10] or ""
    apply_date = row.get("apply_date") or row.get("deadline") or "Open"
    status = row.get("status") or "published"
    return {
        "id": row["id"],
        "title": row.get("title", ""),
        "org": row.get("org", ""),
        "cat": row.get("cat", "govt"),
        "edu": row.get("edu", "N/A"),
        "loc": row.get("loc", "N/A"),
        "sal": row.get("sal", "N/A"),
        "status": status,
        "post_date": post_date,
        "apply_date": apply_date,
        "deadline": apply_date,
        "link": row.get("link", ""),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def news_payload(row):
    return {
        "id": row["id"],
        "text": row.get("text", ""),
        "type": row.get("type", "new"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


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
        qs = parse_qs(parsed.query)
        if parsed.path == "/api/health":
            if USE_POSTGRES:
                parsed_db = urlparse(DATABASE_URL)
                return self._json({
                    "ok": True,
                    "db_kind": "postgres",
                    "database": (parsed_db.path or "").lstrip("/"),
                    "database_host": parsed_db.hostname or "",
                    "data_dir": str(DATA_DIR),
                    "persistent_disk": False,
                })
            return self._json({
                "ok": True,
                "db_kind": "sqlite",
                "database": str(DB_PATH),
                "data_dir": str(DATA_DIR),
                "backup": str(BACKUP_DB_PATH),
                "db_exists": DB_PATH.exists(),
                "db_size": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
                "legacy_db_exists": LEGACY_DB_PATH.exists(),
                "persistent_disk": str(DB_PATH).startswith(str(DEFAULT_RENDER_DATA_DIR)),
            })
        if parsed.path == "/api/site-content":
            include_all = qs.get("all", ["0"])[0] == "1"
            conn = get_db()
            try:
                payload = {
                    "jobs": [job_payload(row) for row in fetch_jobs(conn, include_all=include_all)],
                    "news": [news_payload(row) for row in fetch_news(conn)],
                }
                if include_all:
                    payload["students"] = fetch_students(conn)
                return self._json(payload)
            finally:
                conn.close()
        if parsed.path == "/api/jobs":
            include_all = qs.get("all", ["0"])[0] == "1"
            job_id = qs.get("id", [""])[0]
            conn = get_db()
            try:
                if job_id.isdigit():
                    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (int(job_id),)).fetchone()
                    if not row:
                        return self._json({"error": "Job not found"}, 404)
                    return self._json(job_payload(row))
                return self._json([job_payload(row) for row in fetch_jobs(conn, include_all=include_all)])
            finally:
                conn.close()
        if parsed.path == "/api/news":
            conn = get_db()
            try:
                return self._json([news_payload(row) for row in fetch_news(conn)])
            finally:
                conn.close()
        if parsed.path == "/api/students":
            conn = get_db()
            try:
                return self._json(fetch_students(conn))
            finally:
                conn.close()
        if parsed.path == "/api/centers":
            return self._json(self._table("centers"))
        if parsed.path == "/api/users":
            role = qs.get("role", [""])[0]
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
                post_date = payload.get("post_date") or now_iso()[:10]
                apply_date = payload.get("apply_date") or payload.get("deadline") or "Open"
                cursor = conn.execute(
                    """
                    INSERT INTO jobs (title, org, cat, edu, loc, sal, status, post_date, apply_date, deadline, link, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload.get("title"),
                        payload.get("org"),
                        payload.get("cat", "govt"),
                        payload.get("edu", "N/A"),
                        payload.get("loc", "N/A"),
                        payload.get("sal", "N/A"),
                        payload.get("status", "draft"),
                        post_date,
                        apply_date,
                        apply_date,
                        payload.get("link", ""),
                        now_iso(),
                    ),
                )
                row = conn.execute("SELECT * FROM jobs WHERE id = ?", (cursor.lastrowid,)).fetchone()
                commit_db(conn)
                return self._json(job_payload(row), 201)
            if parsed.path == "/api/news":
                cursor = conn.execute(
                    "INSERT INTO news_items (text, type, updated_at) VALUES (?, ?, ?)",
                    (
                        payload.get("text"),
                        payload.get("type", "new"),
                        now_iso(),
                    ),
                )
                row = conn.execute("SELECT * FROM news_items WHERE id = ?", (cursor.lastrowid,)).fetchone()
                commit_db(conn)
                return self._json(news_payload(row), 201)
            if parsed.path in {"/api/auth/register", "/api/students"}:
                name = (payload.get("name") or payload.get("full_name") or "").strip()
                email = (payload.get("email") or "").strip().lower()
                mobile = (payload.get("mobile") or payload.get("phone") or "").strip()
                password = (payload.get("password") or "").strip()
                course = (payload.get("course") or payload.get("class") or "").strip()
                if not name or not email or not mobile or not password:
                    return self._json({"error": "Name, email, mobile, and password are required"}, 400)
                cursor = conn.execute(
                    """
                    INSERT INTO site_users (role, name, email, mobile, password_hash, course, created_at, updated_at)
                    VALUES ('student', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        email,
                        mobile,
                        hash_password(password),
                        course or None,
                        now_iso(),
                        now_iso(),
                    ),
                )
                row = conn.execute("SELECT * FROM site_users WHERE id = ?", (cursor.lastrowid,)).fetchone()
                commit_db(conn)
                return self._json(user_payload(row, conn), 201)
            if parsed.path == "/api/auth/login":
                identifier = (payload.get("identifier") or payload.get("email") or payload.get("mobile") or "").strip()
                password = (payload.get("password") or "").strip()
                if not identifier or not password:
                    return self._json({"error": "Identifier and password are required"}, 400)
                row = fetch_user_by_identifier(conn, identifier)
                if not row or row["password_hash"] != hash_password(password):
                    return self._json({"error": "Invalid credentials"}, 401)
                return self._json(user_payload(row, conn))
            if parsed.path == "/api/saved-jobs":
                student_id = payload.get("student_id")
                job_id = payload.get("job_id")
                if not str(student_id).isdigit() or not str(job_id).isdigit():
                    return self._json({"error": "student_id and job_id are required"}, 400)
                conn.execute(
                    "INSERT INTO site_saved_jobs (student_id, job_id) VALUES (?, ?) ON CONFLICT (student_id, job_id) DO NOTHING",
                    (int(student_id), int(job_id)),
                )
                commit_db(conn)
                row = conn.execute("SELECT * FROM site_users WHERE id = ? AND role = 'student'", (int(student_id),)).fetchone()
                return self._json(user_payload(row, conn))
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
                commit_db(conn)
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
                commit_db(conn)
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
                commit_db(conn)
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
                            """
                            INSERT INTO thresholds (test_ref, ear, frequency_hz, threshold_dbhl)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT (test_ref, ear, frequency_hz)
                            DO UPDATE SET threshold_dbhl = EXCLUDED.threshold_dbhl
                            """,
                            (test_pk, ear_key, int(freq), str(value)),
                        )
                commit_db(conn)
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
                commit_db(conn)
                return self._json({"id": cursor.lastrowid, "ok": True}, 201)
            return self._json({"error": "Unsupported endpoint"}, 404)
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            return self._json({"error": str(exc)}, 400)
        finally:
            conn.close()

    def do_PUT(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        payload = self._read_json()
        conn = get_db()
        try:
            if parsed.path == "/api/jobs":
                job_id = qs.get("id", [""])[0]
                if not job_id.isdigit():
                    return self._json({"error": "Valid id is required"}, 400)
                row = conn.execute("SELECT * FROM jobs WHERE id = ?", (int(job_id),)).fetchone()
                if not row:
                    return self._json({"error": "Job not found"}, 404)
                merged = {
                    "title": payload.get("title", row["title"]),
                    "org": payload.get("org", row["org"]),
                    "cat": payload.get("cat", row["cat"]),
                    "edu": payload.get("edu", row["edu"]),
                    "loc": payload.get("loc", row["loc"]),
                    "sal": payload.get("sal", row["sal"]),
                    "status": payload.get("status", row.get("status", "published")),
                    "post_date": payload.get("post_date", row.get("post_date") or (row.get("created_at") or "")[:10]),
                    "apply_date": payload.get("apply_date", payload.get("deadline", row.get("apply_date") or row.get("deadline") or "Open")),
                    "link": payload.get("link", row["link"]),
                }
                conn.execute(
                    """
                    UPDATE jobs
                    SET title = ?, org = ?, cat = ?, edu = ?, loc = ?, sal = ?, status = ?,
                        post_date = ?, apply_date = ?, deadline = ?, link = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        merged["title"],
                        merged["org"],
                        merged["cat"],
                        merged["edu"],
                        merged["loc"],
                        merged["sal"],
                        merged["status"],
                        merged["post_date"],
                        merged["apply_date"],
                        merged["apply_date"],
                        merged["link"],
                        now_iso(),
                        int(job_id),
                    ),
                )
                commit_db(conn)
                updated = conn.execute("SELECT * FROM jobs WHERE id = ?", (int(job_id),)).fetchone()
                return self._json(job_payload(updated))
            if parsed.path == "/api/students":
                student_id = qs.get("id", [""])[0]
                if not student_id.isdigit():
                    return self._json({"error": "Valid id is required"}, 400)
                row = conn.execute("SELECT * FROM site_users WHERE id = ? AND role = 'student'", (int(student_id),)).fetchone()
                if not row:
                    return self._json({"error": "Student not found"}, 404)
                updates = []
                params = []
                for key, column in (("name", "name"), ("email", "email"), ("mobile", "mobile"), ("course", "course")):
                    if key in payload:
                        updates.append(f"{column} = ?")
                        params.append(payload.get(key))
                if "password" in payload and payload.get("password"):
                    updates.append("password_hash = ?")
                    params.append(hash_password(payload.get("password")))
                if not updates:
                    return self._json({"error": "No fields to update"}, 400)
                updates.append("updated_at = ?")
                params.append(now_iso())
                params.append(int(student_id))
                conn.execute(f"UPDATE site_users SET {', '.join(updates)} WHERE id = ?", params)
                commit_db(conn)
                updated = conn.execute("SELECT * FROM site_users WHERE id = ?", (int(student_id),)).fetchone()
                return self._json(user_payload(updated, conn))
            return self._json({"error": "Unsupported endpoint"}, 404)
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            return self._json({"error": str(exc)}, 400)
        finally:
            conn.close()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        conn = get_db()
        try:
            if parsed.path == "/api/jobs":
                row_id = qs.get("id", [""])[0]
                if not row_id.isdigit():
                    return self._json({"error": "Valid id is required"}, 400)
                deleted = conn.execute("DELETE FROM jobs WHERE id = ?", (int(row_id),)).rowcount
                commit_db(conn)
                return self._json({"ok": deleted > 0, "deleted": deleted})
            if parsed.path == "/api/news":
                row_id = qs.get("id", [""])[0]
                if not row_id.isdigit():
                    return self._json({"error": "Valid id is required"}, 400)
                deleted = conn.execute("DELETE FROM news_items WHERE id = ?", (int(row_id),)).rowcount
                commit_db(conn)
                return self._json({"ok": deleted > 0, "deleted": deleted})
            if parsed.path == "/api/students":
                row_id = qs.get("id", [""])[0]
                if not row_id.isdigit():
                    return self._json({"error": "Valid id is required"}, 400)
                deleted = conn.execute("DELETE FROM site_users WHERE id = ? AND role = 'student'", (int(row_id),)).rowcount
                commit_db(conn)
                return self._json({"ok": deleted > 0, "deleted": deleted})
            if parsed.path == "/api/saved-jobs":
                student_id = qs.get("student_id", [""])[0]
                job_id = qs.get("job_id", [""])[0]
                if not student_id.isdigit() or not job_id.isdigit():
                    return self._json({"error": "student_id and job_id are required"}, 400)
                deleted = conn.execute(
                    "DELETE FROM site_saved_jobs WHERE student_id = ? AND job_id = ?",
                    (int(student_id), int(job_id)),
                ).rowcount
                commit_db(conn)
                return self._json({"ok": deleted > 0, "deleted": deleted})
            return self._json({"error": "Unsupported endpoint"}, 404)
        finally:
            conn.close()


if __name__ == "__main__":
    init_db()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    if USE_POSTGRES:
        parsed_db = urlparse(DATABASE_URL)
        print(f"Database backend: postgres ({parsed_db.hostname or ''}/{(parsed_db.path or '').lstrip('/')})")
    else:
        print(f"Database backend: sqlite ({DB_PATH})")
    server = ThreadingHTTPServer((host, port), PTAHandler)
    print(f"Shivanshu Cafe server running at http://{host}:{port}/")
    server.serve_forever()
