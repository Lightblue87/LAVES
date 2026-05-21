#!/usr/bin/env python3
"""Build a small public manifest for LAVES data downloads."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def labeling_metadata(labeling_sqlite: Path) -> dict:
    """Read metadata from the labeling SQLite database."""
    import sqlite3
    try:
        con = sqlite3.connect(labeling_sqlite)
        meta = dict(con.execute("SELECT key, value FROM labeling_metadata").fetchall())
        rule_count = con.execute("SELECT COUNT(*) FROM labeling_rules").fetchone()[0]
        con.close()
        return {
            "file": labeling_sqlite.name,
            "version": meta.get("labeling_db_version", ""),
            "regulation": meta.get("labeling_source_regulation", "VO (EG) Nr. 767/2009"),
            "celex": meta.get("labeling_source_celex", ""),
            "sha256": sha256(labeling_sqlite),
            "rule_count": rule_count,
            "bytes": labeling_sqlite.stat().st_size,
            "created_at": meta.get("labeling_created_at", ""),
        }
    except Exception as exc:
        return {"error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build LAVES data manifest.")
    parser.add_argument("--sqlite", type=Path, default=Path("dist/laves.sqlite"))
    parser.add_argument("--labeling-sqlite", type=Path, default=Path("dist/laves_labeling.sqlite"))
    parser.add_argument("--json", type=Path, default=Path("Data/zusatzstoffe.json"))
    parser.add_argument("--out", type=Path, default=Path("dist/manifest.json"))
    args = parser.parse_args()

    with args.json.open("r", encoding="utf-8") as handle:
        records = json.load(handle)

    manifest: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "record_count": len(records),
        "files": {
            "sqlite": {
                "name": args.sqlite.name,
                "sha256": sha256(args.sqlite),
                "bytes": args.sqlite.stat().st_size,
            },
            "json": {
                "name": args.json.name,
                "sha256": sha256(args.json),
                "bytes": args.json.stat().st_size,
            },
        },
    }

    if args.labeling_sqlite.exists():
        manifest["labeling_db"] = labeling_metadata(args.labeling_sqlite)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
