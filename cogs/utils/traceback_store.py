"""Local traceback groups, caller paths, and occurrences, following Rai's archive."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import traceback


ROOT = Path(__file__).resolve().parents[2]

SCHEMA = """
CREATE TABLE IF NOT EXISTS error_groups (
    id INTEGER PRIMARY KEY,
    exception_class TEXT,
    failure_site TEXT NOT NULL,
    signature TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS caller_paths (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES error_groups(id),
    frames TEXT NOT NULL,
    sample_traceback TEXT,
    UNIQUE(group_id, frames)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    caller_path_id INTEGER NOT NULL REFERENCES caller_paths(id),
    occurred_at TEXT NOT NULL,
    origin TEXT NOT NULL,
    context TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS event_path ON events(caller_path_id);
CREATE VIEW IF NOT EXISTS group_summary AS
    SELECT g.id, g.exception_class, g.failure_site, COUNT(*) AS occurrences,
           COUNT(DISTINCT p.id) AS caller_paths, MIN(e.occurred_at) AS first_seen,
           MAX(e.occurred_at) AS last_seen
    FROM error_groups g JOIN caller_paths p ON p.group_id = g.id
    JOIN events e ON e.caller_path_id = p.id
    GROUP BY g.id;
"""


class TracebackStore:
    def __init__(self, filename=ROOT / "tracebacks.db"):
        self.filename = filename

    def _connect(self):
        db = sqlite3.connect(self.filename, timeout=10)
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def initialize(self):
        # Exception diagnostics can contain private report details.
        os.close(os.open(self.filename, os.O_CREAT | os.O_RDWR, 0o600))
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(SCHEMA)

    async def record_exception(self, error, ctx_or_event, sample):
        origin = ctx_or_event if isinstance(ctx_or_event, str) else getattr(
            getattr(ctx_or_event, "command", None), "qualified_name", type(ctx_or_event).__name__
        )
        occurred_at = datetime.now(timezone.utc).isoformat()
        return await asyncio.to_thread(self._record_exception, error, origin, sample, occurred_at)

    def _record_exception(self, error, origin, sample, occurred_at):
        # Discord wraps failures from prefix and application commands.
        original = getattr(error, "original", error)
        if not isinstance(original, BaseException):
            original = error
        exception_class = f"{type(original).__module__}.{type(original).__qualname__}"
        frames = []
        site = None
        for frame in traceback.extract_tb(original.__traceback__):
            path = Path(frame.filename)
            if path.is_absolute() and path.is_relative_to(ROOT):
                path = path.relative_to(ROOT)
            location = (path.as_posix(), frame.name, frame.lineno)
            frames.append(location)
            if location[0].startswith("cogs/") or location[0] == "Modbot.py":
                site = location
        failure_site = origin
        if frames:
            filename, function, line = site or frames[-1]
            failure_site = f"{filename}:{line} in {function}"
        diagnostics = {name: value for name in ("status", "code", "errno")
                       if isinstance(value := getattr(original, name, None), (int, str))}
        signature = [exception_class, failure_site, diagnostics]
        context = list(getattr(error, "__notes__", ()))
        if original is not error:
            context.extend(getattr(original, "__notes__", ()))
        return self._insert(exception_class, failure_site, signature, frames, sample,
                            occurred_at, origin, context)

    async def record_notice(self, origin, reason, detail):
        occurred_at = datetime.now(timezone.utc).isoformat()
        return await asyncio.to_thread(self._insert, None, reason, [origin, reason], [], None,
                                       occurred_at, origin, [detail])

    def _insert(self, exception_class, failure_site, signature, frames, sample,
                occurred_at, origin, context):
        key = json.dumps(signature)
        stack = json.dumps(frames)
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO error_groups(exception_class, failure_site, signature) VALUES (?,?,?) "
                       "ON CONFLICT(signature) DO NOTHING", (exception_class, failure_site, key))
            group_id, = db.execute("SELECT id FROM error_groups WHERE signature=?", (key,)).fetchone()
            db.execute("INSERT INTO caller_paths(group_id, frames, sample_traceback) VALUES (?,?,?) "
                       "ON CONFLICT(group_id, frames) DO NOTHING", (group_id, stack, sample))
            path_id, = db.execute("SELECT id FROM caller_paths WHERE group_id=? AND frames=?",
                                  (group_id, stack)).fetchone()
            return db.execute(
                "INSERT INTO events(caller_path_id, occurred_at, origin, context) VALUES (?,?,?,?)",
                (path_id, occurred_at, origin, json.dumps(context)),
            ).lastrowid
