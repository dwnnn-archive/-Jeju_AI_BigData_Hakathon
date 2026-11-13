import json
import sqlite3
from datetime import UTC, datetime


def now_iso():
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, request TEXT NOT NULL, created_at TEXT NOT NULL,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS audit (
                analysis_id TEXT PRIMARY KEY, decision TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox (
                id TEXT PRIMARY KEY, analysis_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                detail TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
        """)

    def create(self, run_id, request):
        with self.conn:
            self.conn.execute(
                "INSERT INTO runs VALUES (?, ?, ?, NULL)", (run_id, json.dumps(request), now_iso())
            )

    def run(self, run_id):
        row = self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return dict(row)

    def runs(self, limit):
        return [
            r[0]
            for r in self.conn.execute(
                "SELECT id FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        ]

    def fail(self, run_id, code):
        with self.conn:
            self.conn.execute("UPDATE runs SET error=? WHERE id=?", (code, run_id))

    def record_decision(self, run_id, decision, state):
        # Atomic, replay-safe audit and outbox; graph checkpoint follows this commit.
        with self.conn:
            existing = self.conn.execute(
                "SELECT decision FROM audit WHERE analysis_id=?", (run_id,)
            ).fetchone()
            if existing and json.loads(existing[0]) != decision:
                raise ValueError("Decision already recorded")
            self.conn.execute(
                "INSERT OR IGNORE INTO audit VALUES (?, ?, ?)",
                (run_id, json.dumps(decision), now_iso()),
            )
            if decision["action"] == "approve":
                payload = {
                    "analysis_id": run_id,
                    "draft": state["draft"],
                    "result": state["result"],
                    "allocation": state["allocation"],
                    "sources": state["sources"],
                    "decision": decision,
                }
                self.conn.execute(
                    "INSERT OR IGNORE INTO outbox "
                    "(id,analysis_id,payload,created_at,updated_at) VALUES (?,?,?,?,?)",
                    (run_id, run_id, json.dumps(payload), now_iso(), now_iso()),
                )

    def notification(self, run_id):
        row = self.conn.execute("SELECT * FROM outbox WHERE analysis_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result

    def update_notification(self, run_id, status, detail=None, increment=False):
        with self.conn:
            self.conn.execute(
                "UPDATE outbox SET status=?,detail=?,attempts=attempts+?,updated_at=? WHERE id=?",
                (status, detail, int(increment), now_iso(), run_id),
            )

    def audit(self, run_id):
        self.run(run_id)
        return [
            {"decision": json.loads(r["decision"]), "created_at": r["created_at"]}
            for r in self.conn.execute("SELECT * FROM audit WHERE analysis_id=?", (run_id,))
        ]

    def close(self):
        self.conn.close()
