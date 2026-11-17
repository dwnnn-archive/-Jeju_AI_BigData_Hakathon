"""Short SQLite transactions for job receipts and UI snapshots; never holds the graph lock."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta


def utcnow():
    return datetime.now(UTC)


def iso_now():
    return utcnow().isoformat()


class JobRepository:
    def __init__(self, path):
        self.path = path
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT UNIQUE NOT NULL, request_json TEXT NOT NULL, scope TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued', version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL, started_at TEXT, heartbeat_at TEXT,
                    finished_at TEXT, expires_at TEXT, snapshot_json TEXT, result_token TEXT,
                    error TEXT, legacy INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(status, sequence);
                CREATE INDEX IF NOT EXISTS jobs_scope ON jobs(scope, sequence);
            """)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def insert(self, run_id, request, legacy=False):
        serialized = json.dumps(request, sort_keys=True, separators=(",", ":"))
        scope = "|".join((request["date"], request["region"], request["mode"]))
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT * FROM jobs WHERE id=?", (run_id,)).fetchone()
            if existing:
                if existing["request_json"] != serialized:
                    raise ValueError("Idempotency key already belongs to another request")
                return dict(existing)
            conn.execute(
                "UPDATE jobs SET version=version+1 WHERE scope=? AND status='awaiting_approval'",
                (scope,),
            )
            conn.execute(
                "INSERT INTO jobs(id,request_json,scope,created_at,legacy) VALUES(?,?,?,?,?)",
                (run_id, serialized, scope, iso_now(), int(legacy)),
            )
        return self.get(run_id)

    @staticmethod
    def scope_of(request):
        return "|".join((request["date"], request["region"], request["mode"]))

    def scope_rows(self, scope):
        """같은 날짜·지역·모드의 작업을 접수 순서대로."""
        with self.connection() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM jobs WHERE scope=? ORDER BY sequence", (scope,)
                )
            ]

    @staticmethod
    def is_intraday(row):
        return json.loads(row["request_json"]).get("phase") == "intraday"

    def intraday_rank(self, row):
        """이 작업이 그날 몇 번째 당일 점검인가(실패·중단된 시도는 세지 않는다)."""
        return sum(
            1
            for r in self.scope_rows(row["scope"])
            if r["sequence"] <= row["sequence"]
            and self.is_intraday(r)
            and r["status"] not in ("failed", "interrupted")
        )

    def get(self, run_id):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            return dict(row)

    def list(self, limit=20):
        with self.connection() as conn:
            return [
                dict(r)
                for r in conn.execute("SELECT * FROM jobs ORDER BY sequence DESC LIMIT ?", (limit,))
            ]

    def next_queued(self):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT id FROM jobs WHERE status='queued' ORDER BY sequence LIMIT 1"
            ).fetchone()
            return row[0] if row else None

    def start(self, run_id):
        now = iso_now()
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET status='running',started_at=?,heartbeat_at=?,version=version+1 "
                "WHERE id=? AND status='queued'",
                (now, now, run_id),
            )
            return cursor.rowcount == 1

    def heartbeat(self, run_id):
        with self.connection() as conn:
            conn.execute(
                "UPDATE jobs SET heartbeat_at=?,version=version+1 WHERE id=? AND status='running'",
                (iso_now(), run_id),
            )

    def finish(self, run_id, status, snapshot=None, token=None, ttl=3600, error=None):
        now = utcnow()
        with self.connection() as conn:
            conn.execute(
                "UPDATE jobs SET status=?,snapshot_json=?,result_token=COALESCE(?,result_token),"
                "finished_at=?,expires_at=COALESCE(expires_at,?),error=?,"
                "version=version+1 WHERE id=?",
                (
                    status,
                    json.dumps(snapshot) if snapshot else None,
                    token,
                    now.isoformat(),
                    (now + timedelta(seconds=ttl)).isoformat(),
                    error,
                    run_id,
                ),
            )

    def latest(self, row):
        with self.connection() as conn:
            latest = conn.execute(
                "SELECT MAX(sequence) FROM jobs WHERE scope=?", (row["scope"],)
            ).fetchone()[0]
            return row["sequence"] == latest

    def reserve_decision(self, run_id, decision):
        """Commit intent and non-reviewable public state before touching graph checkpoints."""
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT decision FROM decision_intents WHERE analysis_id=?", (run_id,)
            ).fetchone()
            if existing and json.loads(existing[0]) != decision:
                raise ValueError("A different decision is already reserved")
            row = conn.execute(
                "SELECT snapshot_json,expires_at FROM jobs WHERE id=?", (run_id,)
            ).fetchone()
            # BEGIN IMMEDIATE may itself wait on SQLite. Check the deadline after that wait.
            if not row["expires_at"] or utcnow() >= datetime.fromisoformat(row["expires_at"]):
                raise ValueError("Review result expired")
            snapshot = json.loads(row["snapshot_json"])
            snapshot["decision_intent"] = decision
            conn.execute(
                "INSERT OR IGNORE INTO decision_intents VALUES (?, ?, ?)",
                (run_id, json.dumps(decision), iso_now()),
            )
            conn.execute(
                "UPDATE jobs SET status='decision_pending', snapshot_json=?, version=version+1 "
                "WHERE id=?",
                (json.dumps(snapshot), run_id),
            )

    def unfinished(self):
        with self.connection() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM jobs WHERE status IN ('running','decision_pending') "
                    "OR (status='awaiting_approval' AND EXISTS "
                    "(SELECT 1 FROM decision_intents WHERE analysis_id=jobs.id))"
                )
            ]
