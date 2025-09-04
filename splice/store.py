from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .paths import find_splice_directory


def _ensure_parent_dir(path: Path) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)


def _now_ts() -> float:
    return time.time()


def _parse_ttl(ttl: str) -> float:
    s = ttl.strip().lower()
    if s.endswith("ms"):
        return max(0.0, float(s[:-2]) / 1000.0)
    if s.endswith("s"):
        return max(0.0, float(s[:-1]))
    if s.endswith("m"):
        return max(0.0, float(s[:-1]) * 60.0)
    if s.endswith("h"):
        return max(0.0, float(s[:-1]) * 3600.0)
    if s.endswith("d"):
        return max(0.0, float(s[:-1]) * 86400.0)
    # default seconds if bare number
    try:
        return max(0.0, float(s))
    except Exception:
        return 86400.0


def _sha256_hex(text: str) -> str:
    h = hashlib.sha256()
    h.update(text.encode("utf-8", errors="ignore"))
    return h.hexdigest()


@dataclass(frozen=True)
class ArtifactKey:
    session_id: str
    function_name: str
    prompt_hash: str
    spec_hash: str
    context_hash: str
    config_hash: str


@dataclass
class Artifact:
    key: ArtifactKey
    code: str
    created_ts: float
    last_used_ts: float


class ArtifactStore:
    """SQLite-backed store for session-scoped generated code artifacts (Phase 5)."""

    def __init__(self, database_path: Path | None = None, start_path: Path | None = None) -> None:
        if database_path is None:
            base = find_splice_directory(start_path)
            database_path = base / "db.sqlite"
        _ensure_parent_dir(database_path)
        self._db_path = database_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            c = conn.cursor()
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_ts REAL NOT NULL
                )
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    session_id TEXT NOT NULL,
                    function_name TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    spec_hash TEXT NOT NULL,
                    context_hash TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    code TEXT NOT NULL,
                    created_ts REAL NOT NULL,
                    last_used_ts REAL NOT NULL,
                    PRIMARY KEY (session_id, function_name, prompt_hash, spec_hash, context_hash, config_hash),
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    ts REAL NOT NULL,
                    kind TEXT NOT NULL,
                    session_id TEXT,
                    function_name TEXT,
                    message TEXT
                )
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def ensure_session(self, session_id: str) -> None:
        with self._connect() as conn:
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO sessions(id, created_ts) VALUES(?, ?)", (session_id, _now_ts()))
            conn.commit()

    def write_event(self, kind: str, session_id: Optional[str], function_name: Optional[str], message: str) -> None:
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO events(ts, kind, session_id, function_name, message) VALUES(?, ?, ?, ?, ?)",
                (_now_ts(), kind, session_id, function_name, message),
            )
            conn.commit()

    def list_events(self) -> list[tuple[float, str, str | None, str | None, str]]:
        with self._connect() as conn:
            c = conn.cursor()
            c.execute("SELECT ts, kind, session_id, function_name, message FROM events ORDER BY ts ASC")
            rows = c.fetchall()
            return [(float(ts), str(kind), str(sid) if sid is not None else None, str(fn) if fn is not None else None, str(msg)) for ts, kind, sid, fn, msg in rows]

    def get(self, key: ArtifactKey) -> Optional[Artifact]:
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                """
                SELECT code, created_ts, last_used_ts
                FROM artifacts
                WHERE session_id = ? AND function_name = ? AND prompt_hash = ? AND spec_hash = ? AND context_hash = ? AND config_hash = ?
                """,
                (
                    key.session_id,
                    key.function_name,
                    key.prompt_hash,
                    key.spec_hash,
                    key.context_hash,
                    key.config_hash,
                ),
            )
            row = c.fetchone()
            if not row:
                return None
            code, created_ts, last_used_ts = row
            c.execute(
                """
                UPDATE artifacts SET last_used_ts = ?
                WHERE session_id = ? AND function_name = ? AND prompt_hash = ? AND spec_hash = ? AND context_hash = ? AND config_hash = ?
                """,
                (
                    _now_ts(),
                    key.session_id,
                    key.function_name,
                    key.prompt_hash,
                    key.spec_hash,
                    key.context_hash,
                    key.config_hash,
                ),
            )
            conn.commit()
            return Artifact(key=key, code=str(code), created_ts=float(created_ts), last_used_ts=float(last_used_ts))

    def get_fresh(self, key: ArtifactKey, ttl_spec: str) -> Optional[Artifact]:
        ttl_seconds = _parse_ttl(ttl_spec)
        cutoff = _now_ts() - ttl_seconds
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                """
                SELECT code, created_ts, last_used_ts
                FROM artifacts
                WHERE session_id = ? AND function_name = ? AND prompt_hash = ? AND spec_hash = ? AND context_hash = ? AND config_hash = ?
                """,
                (
                    key.session_id,
                    key.function_name,
                    key.prompt_hash,
                    key.spec_hash,
                    key.context_hash,
                    key.config_hash,
                ),
            )
            row = c.fetchone()
            if not row:
                return None
            code, created_ts, last_used_ts = row
            if float(last_used_ts) <= cutoff or float(created_ts) <= cutoff:
                # Expired: delete and return None
                c.execute(
                    """
                    DELETE FROM artifacts
                    WHERE session_id = ? AND function_name = ? AND prompt_hash = ? AND spec_hash = ? AND context_hash = ? AND config_hash = ?
                    """,
                    (
                        key.session_id,
                        key.function_name,
                        key.prompt_hash,
                        key.spec_hash,
                        key.context_hash,
                        key.config_hash,
                    ),
                )
                conn.commit()
                return None
            # Fresh: touch
            c.execute(
                """
                UPDATE artifacts SET last_used_ts = ?
                WHERE session_id = ? AND function_name = ? AND prompt_hash = ? AND spec_hash = ? AND context_hash = ? AND config_hash = ?
                """,
                (
                    _now_ts(),
                    key.session_id,
                    key.function_name,
                    key.prompt_hash,
                    key.spec_hash,
                    key.context_hash,
                    key.config_hash,
                ),
            )
            conn.commit()
            return Artifact(key=key, code=str(code), created_ts=float(created_ts), last_used_ts=float(last_used_ts))

    def get_latest_for_session(
        self,
        *,
        session_id: str,
        function_name: str,
        spec_hash: str,
        context_hash: str,
        config_hash: str,
    ) -> Optional[Artifact]:
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                """
                SELECT prompt_hash, code, created_ts, last_used_ts
                FROM artifacts
                WHERE session_id = ? AND function_name = ? AND spec_hash = ? AND context_hash = ? AND config_hash = ?
                ORDER BY last_used_ts DESC
                LIMIT 1
                """,
                (session_id, function_name, spec_hash, context_hash, config_hash),
            )
            row = c.fetchone()
            if not row:
                return None
            prompt_hash, code, created_ts, last_used_ts = row
            key = ArtifactKey(
                session_id=session_id,
                function_name=function_name,
                prompt_hash=str(prompt_hash),
                spec_hash=spec_hash,
                context_hash=context_hash,
                config_hash=config_hash,
            )
            # Touch last_used_ts
            c.execute(
                """
                UPDATE artifacts SET last_used_ts = ?
                WHERE session_id = ? AND function_name = ? AND prompt_hash = ? AND spec_hash = ? AND context_hash = ? AND config_hash = ?
                """,
                (
                    _now_ts(),
                    session_id,
                    function_name,
                    prompt_hash,
                    spec_hash,
                    context_hash,
                    config_hash,
                ),
            )
            conn.commit()
            return Artifact(key=key, code=str(code), created_ts=float(created_ts), last_used_ts=float(last_used_ts))

    def put(self, key: ArtifactKey, code: str) -> None:
        with self._connect() as conn:
            c = conn.cursor()
            now = _now_ts()
            c.execute(
                """
                INSERT OR REPLACE INTO artifacts(
                    session_id, function_name, prompt_hash, spec_hash, context_hash, config_hash, code, created_ts, last_used_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_ts FROM artifacts WHERE session_id=? AND function_name=? AND prompt_hash=? AND spec_hash=? AND context_hash=? AND config_hash=?), ?), ?)
                """,
                (
                    key.session_id,
                    key.function_name,
                    key.prompt_hash,
                    key.spec_hash,
                    key.context_hash,
                    key.config_hash,
                    code,
                    key.session_id, key.function_name, key.prompt_hash, key.spec_hash, key.context_hash, key.config_hash,
                    now,
                    now,
                ),
            )
            conn.commit()

    def purge_expired(self, ttl_spec: str) -> int:
        ttl_seconds = _parse_ttl(ttl_spec)
        cutoff = _now_ts() - ttl_seconds
        with self._connect() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM artifacts WHERE last_used_ts < ?", (cutoff,))
            deleted = c.rowcount if c.rowcount is not None else 0
            conn.commit()
            return int(deleted)

    def purge_all(self) -> int:
        with self._connect() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM artifacts")
            deleted = c.rowcount if c.rowcount is not None else 0
            conn.commit()
            return int(deleted)

    @staticmethod
    def hash_prompt(prompt: str) -> str:
        return _sha256_hex(prompt)

    @staticmethod
    def hash_spec_yaml(spec_yaml_text: str) -> str:
        return _sha256_hex(spec_yaml_text)

    @staticmethod
    def hash_context_docs(merged_docs_text: str) -> str:
        return _sha256_hex(merged_docs_text)

    @staticmethod
    def hash_config_yaml(config_yaml_text: str) -> str:
        return _sha256_hex(config_yaml_text)


