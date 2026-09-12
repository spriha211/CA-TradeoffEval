from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from src.scoring.integrity import (
    EXPECTED_COMPONENTS, IntegrityError, atomic_write_json, read_text,
    require_unique, sha256_file, validate_blind_id, validate_measure,
)

ROOT = Path(__file__).resolve().parents[2]


def load_components(root: Path, measure: str) -> tuple[Path, list[dict[str, str]]]:
    path = root / "data/reference_inventories" / f"{measure}_components.csv"
    rows = list(csv.DictReader(io.StringIO(read_text(root, path))))
    required = {"component_id", "claim_id", "component_text", "binary_scoring_rule"}
    if not rows or not required.issubset(rows[0]):
        raise IntegrityError(f"Malformed active component inventory: {path}")
    if len(rows) != EXPECTED_COMPONENTS[measure]:
        raise IntegrityError(
            f"{measure}: expected {EXPECTED_COMPONENTS[measure]} components; found {len(rows)}"
        )
    require_unique((row["component_id"] for row in rows), "component_id")
    for row in rows:
        if not all(row[field].strip() for field in required):
            raise IntegrityError(f"Empty required component field in {row!r}")
        if not row["component_id"].startswith(measure + "-"):
            raise IntegrityError(f"Cross-measure component ID: {row['component_id']}")
    return path, rows


def build_jobs(root: Path, measure: str) -> Path:
    measure = validate_measure(measure)
    component_path, components = load_components(root, measure)
    guide_path = root / "data/reference_inventories/SCORING_GUIDE.md"
    guide_text = read_text(root, guide_path)
    blinded_dir = root / "runs/blinded" / measure
    outputs = sorted(blinded_dir.glob(f"{measure}-B*.txt"))
    if len(outputs) != 16:
        raise IntegrityError(f"{measure}: expected exactly 16 blinded outputs; found {len(outputs)}")
    blind_ids = [path.stem for path in outputs]
    for blind_id in blind_ids:
        validate_blind_id(blind_id, measure)
    require_unique(blind_ids, "blind_id")

    out_dir = root / "analysis/model_assisted_scoring/jobs" / measure
    input_records = [
        {"path": str(component_path.relative_to(root)), "sha256": sha256_file(root, component_path)},
        {"path": str(guide_path.relative_to(root)), "sha256": sha256_file(root, guide_path)},
    ]
    job_records = []
    for output_path, blind_id in zip(outputs, blind_ids):
        answer = read_text(root, output_path)
        if not answer.strip():
            raise IntegrityError(f"Empty blinded output: {output_path}")
        job = {
            "schema_version": "1.0",
            "measure_id": measure,
            "blind_id": blind_id,
            "blinded_answer": answer,
            "scoring_guide": guide_text,
            "components": [
                {key: row[key] for key in (
                    "component_id", "claim_id", "component_text", "binary_scoring_rule"
                )}
                for row in components
            ],
        }
        job_path = out_dir / f"{blind_id}.json"
        atomic_write_json(root, job_path, job)
        job_records.append({"path": str(job_path.relative_to(root)), "blind_id": blind_id})
        input_records.append({
            "path": str(output_path.relative_to(root)),
            "sha256": sha256_file(root, output_path),
        })

    for record in job_records:
        record["sha256"] = sha256_file(root, root / record["path"])
    manifest = {
        "schema_version": "1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "measure_id": measure,
        "blind_output_count": len(outputs),
        "component_count": len(components),
        "expected_scoring_rows": len(outputs) * len(components),
        "inputs": input_records,
        "jobs": job_records,
    }
    manifest_path = out_dir / "manifest.json"
    atomic_write_json(root, manifest_path, manifest)
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build condition-blind component scoring jobs")
    parser.add_argument("--measure", required=True)
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args()
    print(build_jobs(args.root.resolve(), args.measure))


if __name__ == "__main__":
    main()
