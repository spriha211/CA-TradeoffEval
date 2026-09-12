from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .generate import ROOT, RUN_ROOT, atomic_json

STUDY1_ROOTS = [
    ROOT / "prompts", ROOT / "data/reference_inventories", ROOT / "data/freeze_manifests",
    ROOT / "runs/raw", ROOT / "runs/blinded", ROOT / "runs/locked",
    ROOT / "analysis/model_assisted_scoring", ROOT / "results/post_lock_analysis",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect() -> dict[str, str]:
    result = {}
    for base in STUDY1_ROOTS:
        if not base.exists():
            continue
        for path in sorted(value for value in base.rglob("*") if value.is_file()):
            lowered = {part.lower() for part in path.parts}
            if "private_mappings" in lowered or "sealed_private_mappings" in lowered or "mapping" in path.name.lower():
                continue
            result[str(path.relative_to(ROOT))] = digest(path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["before", "after"], required=True)
    args = parser.parse_args()
    target = RUN_ROOT / "audits" / f"study1_artifact_hashes_{args.phase}.json"
    files = collect()
    if args.phase == "after":
        before_path = RUN_ROOT / "audits/study1_artifact_hashes_before.json"
        before = json.loads(before_path.read_text(encoding="utf-8"))["files"]
        if before != files:
            changed = sorted(set(before) | set(files))
            changed = [path for path in changed if before.get(path) != files.get(path)]
            raise RuntimeError(f"Study 1 artifact snapshot changed: {changed[:20]}")
    atomic_json(target, {"schema_version": "1.0", "created_at_utc": datetime.now(timezone.utc).isoformat(),
                         "phase": args.phase, "private_mapping_paths_excluded": True, "file_count": len(files), "files": files})
    print(target)


if __name__ == "__main__":
    main()
