"""SQLite habit store via plugin_db (or any sqlite3 connection for tests)."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional

RETENTION_SECONDS = 30 * 24 * 3600

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at REAL NOT NULL,
        session_id TEXT NOT NULL DEFAULT '',
        command TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        pattern_key TEXT NOT NULL DEFAULT '',
        choice TEXT NOT NULL,
        decided_by TEXT NOT NULL DEFAULT '',
        never_auto INTEGER NOT NULL DEFAULT 0,
        reason TEXT NOT NULL DEFAULT '',
        scope TEXT NOT NULL DEFAULT 'owner',
        generalized TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS decisions_fp ON decisions(fingerprint, created_at)",
    "CREATE INDEX IF NOT EXISTS decisions_gen ON decisions(generalized, scope, created_at)",
    """CREATE TABLE IF NOT EXISTS promotions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fingerprint TEXT NOT NULL,
        command TEXT NOT NULL,
        allowlist_entry TEXT NOT NULL,
        pattern TEXT NOT NULL DEFAULT '',
        promoted_at REAL NOT NULL,
        approve_count INTEGER NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        scope TEXT NOT NULL DEFAULT 'owner',
        undone INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS promotions_entry ON promotions(allowlist_entry)",
    """CREATE TABLE IF NOT EXISTS proposals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at REAL NOT NULL,
        fingerprint TEXT NOT NULL,
        command TEXT NOT NULL,
        pattern_key TEXT NOT NULL DEFAULT '',
        proposed_entry TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        approve_count INTEGER NOT NULL DEFAULT 0,
        scope TEXT NOT NULL DEFAULT 'owner',
        status TEXT NOT NULL DEFAULT 'pending'
    )""",
    "CREATE INDEX IF NOT EXISTS proposals_status ON proposals(status, created_at)",
    """CREATE TABLE IF NOT EXISTS last_event (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        kind TEXT NOT NULL,
        fingerprint TEXT NOT NULL DEFAULT '',
        command TEXT NOT NULL DEFAULT '',
        pattern_key TEXT NOT NULL DEFAULT '',
        choice TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT '',
        pattern TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL
    )""",
)


@dataclass
class Decision:
    command: str
    fingerprint: str
    pattern_key: str
    choice: str
    decided_by: str = ""
    never_auto: bool = False
    reason: str = ""
    session_id: str = ""
    created_at: float = 0.0
    scope: str = "owner"
    generalized: str = ""


class HabitStore:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = threading.Lock()
        with self._lock, self._conn:
            for ddl in _SCHEMA:
                self._conn.execute(ddl)
            self._migrate()
            cutoff = time.time() - RETENTION_SECONDS
            self._conn.execute("DELETE FROM decisions WHERE created_at < ?", (cutoff,))

    def _migrate(self) -> None:
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(decisions)")}
        if "scope" not in cols:
            self._conn.execute("ALTER TABLE decisions ADD COLUMN scope TEXT NOT NULL DEFAULT 'owner'")
        if "generalized" not in cols:
            self._conn.execute("ALTER TABLE decisions ADD COLUMN generalized TEXT NOT NULL DEFAULT ''")
        # promotions may be old shape
        try:
            pcols = {r[1] for r in self._conn.execute("PRAGMA table_info(promotions)")}
        except Exception:
            pcols = set()
        if pcols and "allowlist_entry" not in pcols:
            # rebuild lightly: add columns if missing
            for col, ddl in (
                ("allowlist_entry", "ALTER TABLE promotions ADD COLUMN allowlist_entry TEXT NOT NULL DEFAULT ''"),
                ("pattern", "ALTER TABLE promotions ADD COLUMN pattern TEXT NOT NULL DEFAULT ''"),
                ("scope", "ALTER TABLE promotions ADD COLUMN scope TEXT NOT NULL DEFAULT 'owner'"),
                ("undone", "ALTER TABLE promotions ADD COLUMN undone INTEGER NOT NULL DEFAULT 0"),
            ):
                if col not in pcols:
                    try:
                        self._conn.execute(ddl)
                    except Exception:
                        pass
        lcols = {r[1] for r in self._conn.execute("PRAGMA table_info(last_event)")}
        if "pattern" not in lcols:
            try:
                self._conn.execute("ALTER TABLE last_event ADD COLUMN pattern TEXT NOT NULL DEFAULT ''")
            except Exception:
                pass

    def record_decision(self, d: Decision) -> None:
        now = d.created_at or time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO decisions(created_at, session_id, command, fingerprint, pattern_key, "
                "choice, decided_by, never_auto, reason, scope, generalized) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (now, d.session_id, d.command, d.fingerprint, d.pattern_key or "",
                 d.choice, d.decided_by or "", int(d.never_auto), d.reason or "",
                 d.scope or "owner", d.generalized or ""),
            )
            self._set_last(
                "decision", d.fingerprint, d.command, d.pattern_key or "", d.choice,
                d.reason or "", d.generalized or "", now,
            )

    def _set_last(self, kind, fp, command, pattern_key, choice, detail, pattern, now):
        self._conn.execute(
            "INSERT INTO last_event(id, kind, fingerprint, command, pattern_key, choice, detail, pattern, created_at) "
            "VALUES (1,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "kind=excluded.kind, fingerprint=excluded.fingerprint, command=excluded.command, "
            "pattern_key=excluded.pattern_key, choice=excluded.choice, detail=excluded.detail, "
            "pattern=excluded.pattern, created_at=excluded.created_at",
            (kind, fp, command, pattern_key, choice, detail, pattern, now),
        )

    def approve_count(self, fingerprint: str) -> int:
        if not fingerprint:
            return 0
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE fingerprint=? AND choice IN ('once','session','always')",
                (fingerprint,),
            ).fetchone()
        return int(row[0]) if row else 0

    def deny_count(self, fingerprint: str) -> int:
        if not fingerprint:
            return 0
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE fingerprint=? AND choice='deny'",
                (fingerprint,),
            ).fetchone()
        return int(row[0]) if row else 0

    def pattern_approve_count(self, pattern: str, scope: str = "owner") -> int:
        if not pattern:
            return 0
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE generalized=? AND scope=? "
                "AND choice IN ('once','session','always')",
                (pattern, scope),
            ).fetchone()
        return int(row[0]) if row else 0

    def pattern_deny_count(self, pattern: str, scope: str = "owner") -> int:
        if not pattern:
            return 0
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE generalized=? AND scope=? AND choice='deny'",
                (pattern, scope),
            ).fetchone()
        return int(row[0]) if row else 0

    def is_promoted(self, fingerprint: str) -> bool:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT 1 FROM promotions WHERE fingerprint=? AND undone=0", (fingerprint,)
            ).fetchone()
        return bool(row)

    def is_pattern_promoted(self, pattern: str) -> bool:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT 1 FROM promotions WHERE (allowlist_entry=? OR pattern=?) AND undone=0",
                (pattern, pattern),
            ).fetchone()
        return bool(row)

    def mark_promoted(
        self,
        *,
        fingerprint: str,
        command: str,
        allowlist_entry: str,
        approve_count: int,
        reason: str,
        scope: str = "owner",
        pattern: str = "",
    ) -> None:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO promotions(fingerprint, command, allowlist_entry, pattern, "
                "promoted_at, approve_count, reason, scope, undone) "
                "VALUES (?,?,?,?,?,?,?,?,0)",
                (fingerprint, command, allowlist_entry, pattern or allowlist_entry,
                 now, approve_count, reason, scope),
            )
            self._set_last(
                "promoted", fingerprint, command, "", "always", reason, allowlist_entry, now,
            )

    def last_event(self) -> Optional[dict]:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT kind, fingerprint, command, pattern_key, choice, detail, pattern, created_at "
                "FROM last_event WHERE id=1"
            ).fetchone()
        if not row:
            return None
        keys = ("kind", "fingerprint", "command", "pattern_key", "choice", "detail", "pattern", "created_at")
        return dict(zip(keys, row))

    def list_promotions(self, limit: int = 50) -> list[dict]:
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT fingerprint, command, allowlist_entry, promoted_at, approve_count, reason, pattern "
                "FROM promotions WHERE undone=0 ORDER BY promoted_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "fingerprint": r[0], "command": r[1], "allowlist_entry": r[2],
                "promoted_at": r[3], "approve_count": r[4], "reason": r[5], "pattern": r[6],
            }
            for r in rows
        ]

    def habit_allowlist_entries(self) -> list[str]:
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT DISTINCT allowlist_entry FROM promotions WHERE undone=0 AND allowlist_entry!=''"
            ).fetchall()
        return [r[0] for r in rows]

    def forget(self, target: str) -> list[str]:
        """Forget promotions matching pattern/fingerprint/command; return allowlist entries removed from tracking."""
        target = (target or "").strip()
        if not target:
            return []
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT id, allowlist_entry FROM promotions WHERE undone=0 AND "
                "(allowlist_entry=? OR pattern=? OR fingerprint=? OR command=?)",
                (target, target, target, target),
            ).fetchall()
            # also substring match on allowlist_entry
            if not rows:
                rows = self._conn.execute(
                    "SELECT id, allowlist_entry FROM promotions WHERE undone=0 AND "
                    "(allowlist_entry LIKE ? OR pattern LIKE ?)",
                    (f"%{target}%", f"%{target}%"),
                ).fetchall()
            ids = [r[0] for r in rows]
            entries = [r[1] for r in rows if r[1]]
            if ids:
                self._conn.executemany(
                    "UPDATE promotions SET undone=1 WHERE id=?",
                    [(i,) for i in ids],
                )
            now = time.time()
            self._set_last("forget", "", target, "", "", f"forgot {entries}", "", now)
        return entries

    def undo_last_promotion(self) -> Optional[str]:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT id, allowlist_entry FROM promotions WHERE undone=0 "
                "ORDER BY promoted_at DESC, id DESC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            self._conn.execute("UPDATE promotions SET undone=1 WHERE id=?", (row[0],))
            now = time.time()
            self._set_last("undo", "", row[1], "", "", "undo last promotion", row[1], now)
            return row[1]

    def clear_promotions(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE promotions SET undone=1 WHERE undone=0")


    def add_proposal(self, **kwargs) -> int:
        """Create a pending proposal (or return the pending one). Does NOT write command_allowlist."""
        return self.create_proposal(**kwargs)[0]

    def create_proposal(
        self,
        *,
        fingerprint: str,
        command: str,
        pattern_key: str,
        proposed_entry: str,
        reason: str,
        approve_count: int,
        scope: str = "owner",
    ) -> tuple[int, bool]:
        """(id, created): created is False when the same entry was already pending. No allowlist write."""
        now = time.time()
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT id FROM proposals WHERE status='pending' AND proposed_entry=? AND scope=?",
                (proposed_entry, scope),
            ).fetchone()
            if row:
                self._set_last(
                    "proposed", fingerprint, command, pattern_key or "", "",
                    f"already pending #{row[0]}: {proposed_entry}", proposed_entry, now,
                )
                return int(row[0]), False
            cur = self._conn.execute(
                "INSERT INTO proposals(created_at, fingerprint, command, pattern_key, "
                "proposed_entry, reason, approve_count, scope, status) "
                "VALUES (?,?,?,?,?,?,?,?, 'pending')",
                (now, fingerprint, command, pattern_key or "", proposed_entry,
                 reason or "", approve_count, scope or "owner"),
            )
            pid = int(cur.lastrowid)
            self._set_last(
                "proposed", fingerprint, command, pattern_key or "", "",
                f"proposed #{pid}: {proposed_entry} — /habit accept {pid}",
                proposed_entry, now,
            )
            return pid, True

    def list_proposals(self, status: str = "pending", limit: int = 50) -> list[dict]:
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT id, created_at, fingerprint, command, pattern_key, proposed_entry, "
                "reason, approve_count, scope, status FROM proposals "
                "WHERE status=? ORDER BY id ASC LIMIT ?",
                (status, limit),
            ).fetchall()
        keys = ("id", "created_at", "fingerprint", "command", "pattern_key",
                "proposed_entry", "reason", "approve_count", "scope", "status")
        return [dict(zip(keys, r)) for r in rows]

    def get_proposal(self, proposal_id: int) -> Optional[dict]:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT id, created_at, fingerprint, command, pattern_key, proposed_entry, "
                "reason, approve_count, scope, status FROM proposals WHERE id=?",
                (proposal_id,),
            ).fetchone()
        if not row:
            return None
        keys = ("id", "created_at", "fingerprint", "command", "pattern_key",
                "proposed_entry", "reason", "approve_count", "scope", "status")
        return dict(zip(keys, row))

    def is_entry_proposed(self, entry: str, scope: str = "owner") -> bool:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT 1 FROM proposals WHERE status='pending' AND proposed_entry=? AND scope=?",
                (entry, scope),
            ).fetchone()
        return bool(row)

    def set_proposal_status(self, proposal_id: int, status: str) -> Optional[dict]:
        now = time.time()
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT id, fingerprint, command, pattern_key, proposed_entry, reason, "
                "approve_count, scope, status FROM proposals WHERE id=?",
                (proposal_id,),
            ).fetchone()
            if not row:
                return None
            self._conn.execute(
                "UPDATE proposals SET status=? WHERE id=?", (status, proposal_id)
            )
            keys = ("id", "fingerprint", "command", "pattern_key", "proposed_entry",
                    "reason", "approve_count", "scope", "status")
            d = dict(zip(keys, row))
            d["status"] = status
            self._set_last(
                status, d["fingerprint"], d["command"], d["pattern_key"], "",
                f"{status} #{proposal_id}: {d['proposed_entry']}", d["proposed_entry"], now,
            )
            return d

    def find_pending_for_command(self, command: str, project_root: str) -> Optional[str]:
        from .patterns import exact_entry, matches_learned, generalize
        from .normalize import fingerprint as make_fp
        fp = make_fp(command)
        for p in self.list_proposals("pending"):
            entry = p["proposed_entry"]
            if entry == fp or entry == command or entry == exact_entry(command):
                return entry
            if matches_learned(command, entry, project_root):
                return entry
            gen = generalize(command, project_root)
            if gen and gen.pattern == entry:
                return entry
        return None

    def find_matching_pattern(self, command: str, project_root: str) -> Optional[str]:
        from .patterns import matches_learned
        for p in self.list_promotions():
            entry = p["allowlist_entry"]
            if matches_learned(command, entry, project_root):
                return entry
        return None
