import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Storage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,          
                    text TEXT NOT NULL,             
                    due_at TEXT NOT NULL,           
                    status TEXT NOT NULL DEFAULT 'pending', 
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    sent_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, due_at);
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    tool_name TEXT,
                    tool_call_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    due_text TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_user_id
                    ON sessions(user_id);

                CREATE INDEX IF NOT EXISTS idx_messages_session_id
                    ON messages(session_id);

                CREATE INDEX IF NOT EXISTS idx_notes_user_id
                    ON notes(user_id);

                CREATE INDEX IF NOT EXISTS idx_tasks_user_id_status
                    ON tasks(user_id, status);
                """
            )

    def upsert_user(self, user_id: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO users (id)
                VALUES (?)
                ON CONFLICT(id) DO NOTHING
                """,
                (user_id,),
            )

    def get_or_create_active_session(self, user_id: str) -> int:
        self.upsert_user(user_id)

        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT id
                FROM sessions
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()

            if row:
                return int(row["id"])

            cur = conn.execute(
                """
                INSERT INTO sessions (user_id)
                VALUES (?)
                """,
                (user_id,),
            )
            return int(cur.lastrowid)

    def reset_session(self, user_id: str) -> int:
        self.upsert_user(user_id)

        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO sessions (user_id)
                VALUES (?)
                """,
                (user_id,),
            )
            return int(cur.lastrowid)

    def add_message(
        self,
        session_id: int,
        role: str,
        content: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO messages (session_id, role, content, tool_name, tool_call_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content, tool_name, tool_call_id),
            )

    def get_recent_messages(self, session_id: int, limit: int = 20) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT role, content, tool_name, tool_call_id
                FROM messages
                WHERE session_id = ? AND role IN ('user', 'assistant')
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()

        messages = []
        for row in reversed(rows):
            msg = {"role": row["role"]}
            if row["content"] is not None:
                msg["content"] = row["content"]
            messages.append(msg)

        return messages