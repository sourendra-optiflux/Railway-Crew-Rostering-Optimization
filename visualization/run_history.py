"""SQLite persistence for dashboard What-If, Disruption, and Pipeline runs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HISTORY_DB = ROOT / "CP-SAT" / "outputs" / "dashboard_history.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DEFAULT_HISTORY_DB) -> None:
    """Create the run_history table if it does not already exist."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                run_type TEXT NOT NULL,
                preset TEXT NOT NULL,
                strategy TEXT NOT NULL,
                rule_toggles_json TEXT NOT NULL,
                total_demand INTEGER NOT NULL,
                assigned_demand INTEGER NOT NULL,
                unfilled_demand INTEGER NOT NULL,
                coverage_pct REAL NOT NULL,
                total_cost REAL NOT NULL
            )
            """
        )
        conn.commit()


def record_run(
    *,
    run_type: str,
    preset: str,
    strategy: str,
    rule_toggles: dict[str, Any],
    total_demand: int,
    assigned_demand: int,
    unfilled_demand: int,
    coverage_pct: float,
    total_cost: float,
    db_path: Path = DEFAULT_HISTORY_DB,
) -> int:
    """Insert a completed run record and return its row id."""
    init_db(db_path)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    toggles_json = json.dumps(rule_toggles, sort_keys=True)
    with _connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO run_history (
                timestamp,
                run_type,
                preset,
                strategy,
                rule_toggles_json,
                total_demand,
                assigned_demand,
                unfilled_demand,
                coverage_pct,
                total_cost
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                run_type,
                preset,
                strategy,
                toggles_json,
                int(total_demand),
                int(assigned_demand),
                int(unfilled_demand),
                round(float(coverage_pct), 2),
                round(float(total_cost), 2),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid or 0)


def list_runs(
    limit: int = 100,
    db_path: Path = DEFAULT_HISTORY_DB,
) -> list[dict[str, Any]]:
    """Return recent run history records ordered newest first."""
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                timestamp,
                run_type,
                preset,
                strategy,
                rule_toggles_json,
                total_demand,
                assigned_demand,
                unfilled_demand,
                coverage_pct,
                total_cost
            FROM run_history
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["rule_toggles"] = json.loads(item.get("rule_toggles_json", "{}"))
        except json.JSONDecodeError:
            item["rule_toggles"] = {}
        result.append(item)
    return result


def clear_runs(db_path: Path = DEFAULT_HISTORY_DB) -> None:
    """Delete all saved run history rows."""
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM run_history")
        conn.commit()
