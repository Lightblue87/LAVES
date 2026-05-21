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


def main() -> int:
    parser = argparse.ArgumentParser(description="Build LAVES data manifest.")
    parser.add_argument("--sqlite", type=Path, default=Path("dist/laves.sqlite"))
    parser.add_argument("--json", type=Path, default=Path("Data/zusatzstoffe.json"))
    parser.add_argument("--out", type=Path, default=Path("dist/manifest.json"))
    args = parser.parse_args()

    with args.json.open("r", encoding="utf-8") as handle:
        records = json.load(handle)

    manifest = {
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

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
