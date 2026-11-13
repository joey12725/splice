"""SQLite-backed, session-scoped cache of generated code plus an event log."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import astuple, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import ConfigError
from .paths import require_splice_directory

if TYPE_CHECKING:
    from .config import SpliceConfig

_TTL_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
_KEY_WHERE = (
    "session_id = ? AND function_name = ? AND prompt_hash = ? AND spec_hash = ? "
    "AND context_hash = ? AND config_hash = ?"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_ts REAL NOT NULL
);
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
);
CREATE TABLE IF NOT EXISTS events (
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    session_id TEXT,
    function_name TEXT,
    message TEXT
);
"""


def parse_ttl(ttl: str) -> float:
    """Parse ``"500ms"``, ``"30s"``, ``"15m"``, ``"24h"``, ``"7d"`` or bare seconds."""

    s = str(ttl).strip().lower()
    for suffix in ("ms", "s", "m", "h", "d"):
        if s.endswith(suffix):
            number, scale = s[: -len(suffix)], _TTL_UNITS[suffix]
            break
    else:
        number, scale = s, 1.0
    try:
        return max(0.0, float(number) * scale)
    except ValueError as exc:
        raise ConfigError(f"Invalid TTL {ttl!r}; use forms like 30s, 15m, 24h, 7d") from exc


_parse_ttl = parse_ttl  # backwards-compatible alias


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def resolve_database_path(cfg: SpliceConfig, base: Path) -> Path:
    """Resolve ``logging.database`` for the workspace at ``base`` (the ``.splice`` dir).

    Paths starting with ``.splice/`` are relative to the project root; other
    relative paths are relative to the ``.splice`` directory.
    """

    db_path = Path(cfg.logging.database)
    if db_path.is_absolute():
        return db_path
    if db_path.parts and db_path.parts[0] == ".splice":
        return (base.parent / db_path).resolve()
    return (base / db_path).resolve()


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
    """Session-scoped store for generated code artifacts."""

    def __init__(self, database_path: Path | None = None, start_path: Path | None = None) -> None:
        if database_path is None:
            database_path = require_splice_directory(start_path) / "db.sqlite"
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = database_path
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @property
    def path(self) -> Path:
        return self._db_path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # Sessions and events ---------------------------------------------------------

    def ensure_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions(id, created_ts) VALUES(?, ?)",
                (session_id, time.time()),
            )

    def write_event(
        self, kind: str, session_id: str | None, function_name: str | None, message: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO events(ts, kind, session_id, function_name, message) "
                "VALUES(?, ?, ?, ?, ?)",
                (time.time(), kind, session_id, function_name, message),
            )

    def list_events(self) -> list[tuple[float, str, str | None, str | None, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ts, kind, session_id, function_name, message FROM events ORDER BY ts ASC"
            ).fetchall()
        return [(float(ts), str(kind), sid, fn, str(msg)) for ts, kind, sid, fn, msg in rows]

    # Artifacts -----------------------------------------------------------------

    def _fetch(self, conn: sqlite3.Connection, key: ArtifactKey) -> Artifact | None:
        row = conn.execute(
            f"SELECT code, created_ts, last_used_ts FROM artifacts WHERE {_KEY_WHERE}",
            astuple(key),
        ).fetchone()
        if not row:
            return None
        code, created_ts, last_used_ts = row
        return Artifact(
            key=key, code=str(code), created_ts=float(created_ts), last_used_ts=float(last_used_ts)
        )

    def _touch(self, conn: sqlite3.Connection, key: ArtifactKey) -> None:
        conn.execute(
            f"UPDATE artifacts SET last_used_ts = ? WHERE {_KEY_WHERE}",
            (time.time(), *astuple(key)),
        )

    def get(self, key: ArtifactKey) -> Artifact | None:
        with self._connect() as conn:
            art = self._fetch(conn, key)
            if art is not None:
                self._touch(conn, key)
            return art

    def get_fresh(self, key: ArtifactKey, ttl_spec: str) -> Artifact | None:
        """Return the artifact if it is younger than ``ttl_spec``; delete it otherwise."""

        cutoff = time.time() - parse_ttl(ttl_spec)
        with self._connect() as conn:
            art = self._fetch(conn, key)
            if art is None:
                return None
            if art.last_used_ts <= cutoff or art.created_ts <= cutoff:
                conn.execute(f"DELETE FROM artifacts WHERE {_KEY_WHERE}", astuple(key))
                return None
            self._touch(conn, key)
            return art

    def get_latest_for_session(
        self,
        *,
        session_id: str,
        function_name: str,
        spec_hash: str,
        context_hash: str,
        config_hash: str,
    ) -> Artifact | None:
        """Most recently used artifact for this function in this session, any prompt."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT prompt_hash FROM artifacts WHERE session_id = ? AND function_name = ? "
                "AND spec_hash = ? AND context_hash = ? AND config_hash = ? "
                "ORDER BY last_used_ts DESC LIMIT 1",
                (session_id, function_name, spec_hash, context_hash, config_hash),
            ).fetchone()
            if not row:
                return None
            key = ArtifactKey(
                session_id, function_name, str(row[0]), spec_hash, context_hash, config_hash
            )
            art = self._fetch(conn, key)
            self._touch(conn, key)
            return art

    def put(self, key: ArtifactKey, code: str) -> None:
        """Insert or replace an artifact, preserving its original creation time."""

        now = time.time()
        with self._connect() as conn:
            existing = self._fetch(conn, key)
            created = existing.created_ts if existing else now
            conn.execute(
                "INSERT OR REPLACE INTO artifacts(session_id, function_name, prompt_hash, "
                "spec_hash, context_hash, config_hash, code, created_ts, last_used_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*astuple(key), code, created, now),
            )

    def purge_expired(self, ttl_spec: str) -> int:
        cutoff = time.time() - parse_ttl(ttl_spec)
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM artifacts WHERE last_used_ts < ?", (cutoff,))
            return int(cur.rowcount or 0)

    def purge_all(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM artifacts")
            return int(cur.rowcount or 0)

    # Hashing -------------------------------------------------------------------

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
