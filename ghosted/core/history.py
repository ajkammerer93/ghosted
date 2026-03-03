"""Scan history and removal tracking via SQLite."""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from ghosted.models import (
    BrokerMethod,
    RemovalRequest,
    RemovalStatus,
    ScanReport,
    ScanResult,
)


class HistoryDB:
    """SQLite-backed storage for scan history and removal status."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Path.home() / ".ghosted" / "scan_history.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            is_new = not self.db_path.exists()
            self._conn = sqlite3.connect(str(self.db_path))
            if is_new:
                os.chmod(self.db_path, 0o600)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def init_db(self) -> None:
        """Create tables if they don't already exist."""
        conn = self._connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scans (
                id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                total_brokers INTEGER NOT NULL DEFAULT 0,
                brokers_with_data INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS scan_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id TEXT NOT NULL,
                broker_name TEXT NOT NULL,
                found INTEGER NOT NULL DEFAULT 0,
                profile_url TEXT,
                info_found_json TEXT,
                error TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (scan_id) REFERENCES scans(id)
            );

            CREATE TABLE IF NOT EXISTS removals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broker_name TEXT NOT NULL,
                profile_url TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                method TEXT NOT NULL DEFAULT 'web_form',
                submitted_at TEXT,
                verified_at TEXT,
                confirmed_at TEXT,
                notes TEXT DEFAULT '',
                error TEXT
            );
        """)
        conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def save_scan(self, report: ScanReport) -> None:
        """Insert a scan report and all its results."""
        conn = self._connect()
        conn.execute(
            "INSERT INTO scans (id, started_at, completed_at, total_brokers, brokers_with_data, errors) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                report.scan_id,
                report.started_at.isoformat(),
                report.completed_at.isoformat() if report.completed_at else None,
                report.total_brokers,
                report.brokers_with_data,
                report.errors,
            ),
        )
        for result in report.results:
            conn.execute(
                "INSERT INTO scan_results (scan_id, broker_name, found, profile_url, info_found_json, error, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    report.scan_id,
                    result.broker_name,
                    1 if result.found else 0,
                    result.profile_url,
                    json.dumps(result.info_found),
                    result.error,
                    result.timestamp.isoformat(),
                ),
            )
        conn.commit()

    def save_removal(self, request: RemovalRequest) -> None:
        """Insert or update a removal request (upserts by broker_name)."""
        conn = self._connect()
        existing = conn.execute(
            "SELECT id FROM removals WHERE broker_name = ?", (request.broker_name,)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE removals SET status=?, method=?, submitted_at=?, verified_at=?, "
                "confirmed_at=?, notes=?, error=?, profile_url=? WHERE id=?",
                (
                    request.status.value,
                    request.method.value,
                    request.submitted_at.isoformat() if request.submitted_at else None,
                    request.verified_at.isoformat() if request.verified_at else None,
                    request.confirmed_at.isoformat() if request.confirmed_at else None,
                    request.notes,
                    request.error,
                    request.profile_url,
                    existing["id"],
                ),
            )
        else:
            conn.execute(
                "INSERT INTO removals (broker_name, profile_url, status, method, submitted_at, "
                "verified_at, confirmed_at, notes, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request.broker_name,
                    request.profile_url,
                    request.status.value,
                    request.method.value,
                    request.submitted_at.isoformat() if request.submitted_at else None,
                    request.verified_at.isoformat() if request.verified_at else None,
                    request.confirmed_at.isoformat() if request.confirmed_at else None,
                    request.notes,
                    request.error,
                ),
            )
        conn.commit()

    def get_latest_scan(self) -> Optional[ScanReport]:
        """Return the most recent scan report with all results."""
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM scans ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return self._build_scan_report(row)

    def get_scan_history(self, limit: int = 10) -> list[ScanReport]:
        """Return recent scan reports."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM scans ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._build_scan_report(r) for r in rows]

    def get_removal_status(self, broker_name: str) -> Optional[RemovalRequest]:
        """Get the removal record for a specific broker."""
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM removals WHERE broker_name = ?", (broker_name,)
        ).fetchone()
        if not row:
            return None
        return self._build_removal(row)

    def get_all_removals(self) -> list[RemovalRequest]:
        """Return all removal requests."""
        conn = self._connect()
        rows = conn.execute("SELECT * FROM removals ORDER BY submitted_at DESC").fetchall()
        return [self._build_removal(r) for r in rows]

    def _build_scan_report(self, row: sqlite3.Row) -> ScanReport:
        conn = self._connect()
        result_rows = conn.execute(
            "SELECT * FROM scan_results WHERE scan_id = ?", (row["id"],)
        ).fetchall()

        results = []
        for r in result_rows:
            results.append(
                ScanResult(
                    broker_name=r["broker_name"],
                    found=bool(r["found"]),
                    profile_url=r["profile_url"],
                    info_found=json.loads(r["info_found_json"]) if r["info_found_json"] else [],
                    error=r["error"],
                    timestamp=datetime.fromisoformat(r["timestamp"]),
                )
            )

        return ScanReport(
            scan_id=row["id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            total_brokers=row["total_brokers"],
            brokers_with_data=row["brokers_with_data"],
            errors=row["errors"],
            results=results,
        )

    def _build_removal(self, row: sqlite3.Row) -> RemovalRequest:
        return RemovalRequest(
            broker_name=row["broker_name"],
            profile_url=row["profile_url"],
            status=RemovalStatus(row["status"]),
            method=BrokerMethod(row["method"]),
            submitted_at=datetime.fromisoformat(row["submitted_at"]) if row["submitted_at"] else None,
            verified_at=datetime.fromisoformat(row["verified_at"]) if row["verified_at"] else None,
            confirmed_at=datetime.fromisoformat(row["confirmed_at"]) if row["confirmed_at"] else None,
            notes=row["notes"] or "",
            error=row["error"],
        )
