"""Small durable local session store; each update is a SQLite transaction."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)")
            columns = {column[1] for column in conn.execute("PRAGMA table_info(sessions)")}
            # Remove content retained by older versions' recycle bin. Keep the
            # nullable legacy column so rolling restarts can still open the DB.
            purged = conn.execute("DELETE FROM sessions WHERE deleted_at IS NOT NULL").rowcount if "deleted_at" in columns else 0
        if purged:
            self._compact()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=20)
        connection.execute("PRAGMA secure_delete = ON")
        try:
            with connection:
                yield connection
        finally:
            # sqlite3.Connection.__exit__ commits but does not release the file.
            connection.close()

    def get(self, session_id):
        with self.lock, self._connect() as conn:
            row = conn.execute("SELECT payload FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, session):
        with self.lock, self._connect() as conn:
            session["updated_at"] = now_iso()
            conn.execute("INSERT INTO sessions (id, payload, updated_at) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                         (session["session_id"], json.dumps(session, ensure_ascii=False), session["updated_at"]))

    def update(self, session):
        """Persist an existing session; delayed work cannot recreate deleted data."""
        with self.lock, self._connect() as conn:
            session["updated_at"] = now_iso()
            changed = conn.execute("UPDATE sessions SET payload = ?, updated_at = ? WHERE id = ?",
                                   (json.dumps(session, ensure_ascii=False), session["updated_at"], session["session_id"]))
            return changed.rowcount > 0

    def list(self):
        with self.lock, self._connect() as conn:
            rows = conn.execute("SELECT payload FROM sessions ORDER BY updated_at DESC LIMIT 100").fetchall()
        return [{"session_id": s["session_id"], "topic": s["req"]["topic"], "status": s["status"], "updated_at": s["updated_at"]}
                for s in (json.loads(row[0]) for row in rows)]

    def delete(self, session_id):
        """Permanently remove the payload and return freed database pages to disk."""
        with self.lock:
            with self._connect() as conn:
                changed = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,)).rowcount
            if changed:
                self._compact()
            return changed > 0

    def _compact(self):
        # VACUUM must run after the DELETE transaction has committed.
        with self.lock, self._connect() as conn:
            conn.execute("VACUUM")

    def recover_interrupted(self):
        # Recovery must not use the paginated/recent sidebar listing.
        with self.lock, self._connect() as conn:
            rows = conn.execute("SELECT payload FROM sessions").fetchall()
        for row in rows:
            session = json.loads(row[0])
            if session["status"] in {"researching", "writing", "patching"}:
                session["status"] = "failed"
                session["error_message"] = "Máy chủ đã dừng khi tác vụ đang chạy. Hồ sơ đã lưu được giữ lại; hãy thử lại thao tác."
                self.update(session)
