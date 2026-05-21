#!/usr/bin/env python3
"""Build the LAVES SQLite database from Data/zusatzstoffe.json."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS additives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kennnummer TEXT NOT NULL,
    schema TEXT,
    name TEXT NOT NULL,
    tierarten TEXT,
    hoechstalter_tage REAL,
    min_mg_kg REAL,
    max_mg_kg REAL,
    charakteristika TEXT,
    geltung_bis TEXT,
    rechtsgrundlage TEXT,
    source_file TEXT,
    source_page INTEGER,
    tierart_kategorie TEXT,
    tierart_spezifisch INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_additives_kennnummer ON additives(kennnummer);
CREATE INDEX IF NOT EXISTS idx_additives_name ON additives(name);
CREATE INDEX IF NOT EXISTS idx_additives_category ON additives(tierart_kategorie);
CREATE INDEX IF NOT EXISTS idx_additives_source ON additives(source_file);
"""


def _bool_int(value: Any) -> int:
    return 1 if bool(value) else 0


def build_sqlite(json_path: Path, sqlite_path: Path) -> None:
    with json_path.open("r", encoding="utf-8") as handle:
        records = json.load(handle)

    if not isinstance(records, list):
        raise ValueError(f"Expected a JSON list in {json_path}")

    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    if sqlite_path.exists():
        sqlite_path.unlink()

    con = sqlite3.connect(sqlite_path)
    try:
        con.executescript(SCHEMA)
        con.execute("DELETE FROM metadata")
        con.execute("DELETE FROM additives")
        con.execute("INSERT INTO metadata(key, value) VALUES (?, ?)", ("record_count", str(len(records))))
        con.execute("INSERT INTO metadata(key, value) VALUES (?, ?)", ("source_json", str(json_path)))

        rows = []
        for record in records:
            if not isinstance(record, dict):
                continue
            rows.append(
                (
                    str(record.get("kennnummer") or ""),
                    record.get("schema"),
                    str(record.get("name") or ""),
                    record.get("tierarten"),
                    record.get("hoechstalter_tage"),
                    record.get("min_mg_kg"),
                    record.get("max_mg_kg"),
                    record.get("charakteristika"),
                    record.get("geltung_bis"),
                    record.get("rechtsgrundlage"),
                    record.get("source_file"),
                    record.get("source_page"),
                    record.get("tierart_kategorie"),
                    _bool_int(record.get("tierart_spezifisch")),
                    json.dumps(record, ensure_ascii=False, sort_keys=True),
                )
            )

        con.executemany(
            """
            INSERT INTO additives (
                kennnummer, schema, name, tierarten, hoechstalter_tage,
                min_mg_kg, max_mg_kg, charakteristika, geltung_bis,
                rechtsgrundlage, source_file, source_page, tierart_kategorie,
                tierart_spezifisch, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        con.commit()
        con.execute("PRAGMA wal_checkpoint(FULL)")
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build LAVES SQLite database from JSON.")
    parser.add_argument("--json", type=Path, default=Path("Data/zusatzstoffe.json"))
    parser.add_argument("--out", type=Path, default=Path("dist/laves.sqlite"))
    args = parser.parse_args()

    build_sqlite(args.json, args.out)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
