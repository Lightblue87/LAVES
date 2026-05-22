"""Session-scoped pytest fixture: builds a fresh labeling.sqlite
from scripts/build_labeling_db.py into a temporary directory before any
test run.

All DB-dependent test classes receive the open connection via their own
``@pytest.fixture(autouse=True) def _db(self, fresh_db)`` method.
The connection is safe for concurrent reads (all tests only SELECT).
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_BUILD_SCRIPT = Path(__file__).parent.parent / "scripts" / "build_labeling_db.py"

# Columns that MUST exist for the current schema version.
# Any locally-cached DB that lacks these triggers a clear, actionable error
# instead of a confusing AttributeError or OperationalError later.
_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "labeling_rule_patterns": {"pattern_language"},
    "labeling_rules": {"id", "feed_type_id", "severity"},
    "labeling_metadata": {"key", "value"},
}


def _check_schema(con: sqlite3.Connection, label: str) -> None:
    """Raise ValueError with a clear message if any required column is missing."""
    for table, required in _REQUIRED_COLUMNS.items():
        existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
        missing = required - existing
        if missing:
            raise ValueError(
                f"Testdatenbank veraltet – bitte neu generieren. "
                f"[{label}] Tabelle '{table}' fehlt Spalte(n): "
                f"{', '.join(sorted(missing))}"
            )


@pytest.fixture(scope="session")
def fresh_db(tmp_path_factory: pytest.TempPathFactory) -> sqlite3.Connection:
    """Build a fresh labeling.sqlite and return an open connection.

    Fails the entire test session with a clear message if:
    - the build script is missing
    - the build script exits non-zero
    - the resulting schema is outdated
    """
    if not _BUILD_SCRIPT.exists():
        pytest.fail(
            f"Build-Skript nicht gefunden: {_BUILD_SCRIPT}\n"
            "Stelle sicher, dass das Repository vollständig ausgecheckt ist."
        )

    out = tmp_path_factory.mktemp("feedlabelcheck_db") / "labeling.sqlite"
    proc = subprocess.run(
        [sys.executable, str(_BUILD_SCRIPT), "--out", str(out)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not out.exists():
        pytest.fail(
            f"build_labeling_db.py fehlgeschlagen (exit {proc.returncode}):\n"
            f"--- STDOUT ---\n{proc.stdout}\n"
            f"--- STDERR ---\n{proc.stderr}"
        )

    con = sqlite3.connect(str(out))
    try:
        _check_schema(con, "frisch erzeugte Datenbank")
    except ValueError as exc:
        con.close()
        pytest.fail(str(exc))

    yield con  # type: ignore[misc]
    con.close()
