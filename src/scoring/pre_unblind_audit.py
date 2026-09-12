from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from src.scoring.integrity import (
    EXPECTED_COMPONENTS, IntegrityError, MEASURES, atomic_write_json,
    read_text, sha256_file,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_REL = "runs/audits/model_assisted_scoring/PRE_UNBLIND_INTEGRITY_MANIFEST.json"


def _true(value: str) -> bool:
    return value.strip().lower() == "true"


def audit_measure(root: Path, measure: str) -> dict:
    expected_rows = EXPECTED_COMPONENTS[measure] * 16
    locked_rel = f"results/locked_scoring/{measure}/{measure}_locked_scoring.csv"
    lock_manifest_rel = f"results/locked_scoring/{measure}/{measure}_scoring_lock_manifest.json"
    locked_path, lock_manifest_path = root / locked_rel, root / lock_manifest_rel
    checks: dict[str, bool] = {}
    errors: list[str] = []

    def check(name: str, condition: bool, message: str) -> None:
        checks[name] = bool(condition)
        if not condition:
            errors.append(message)

    check("locked_csv_exists", locked_path.is_file(), f"Missing locked CSV: {locked_rel}")
    check("lock_manifest_exists", lock_manifest_path.is_file(), f"Missing lock manifest: {lock_manifest_rel}")
    if errors:
        return {
            "measure_id": measure, "status": "FAIL", "checks": checks,
            "errors": errors, "expected_row_count": expected_rows,
            "row_count": None, "unresolved_flags": None,
            "locked_csv_path": locked_rel, "locked_csv_sha256": None,
            "scoring_lock_manifest_path": lock_manifest_rel,
            "scoring_lock_manifest_sha256": None,
        }

    manifest = json.loads(read_text(root, lock_manifest_path))
    rows = list(csv.DictReader(read_text(root, locked_path).splitlines()))
    keys = [(row["blind_id"], row["component_id"]) for row in rows]
    locked_hash = sha256_file(root, locked_path)
    manifest_hash = sha256_file(root, lock_manifest_path)
    unresolved_flags = sum(_true(row.get("flagged", "")) for row in rows)

    check("manifest_measure_matches", manifest.get("measure_id") == measure, "Manifest measure mismatch")
    check("expected_row_count", len(rows) == expected_rows, f"Expected {expected_rows} rows; found {len(rows)}")
    check("manifest_row_count", manifest.get("row_count") == len(rows), "Manifest row count mismatch")
    check("unique_blind_component_pairs", len(keys) == len(set(keys)), "Duplicate blind/component pairs")
    check("all_rows_human_reviewed", all(_true(row.get("human_reviewed", "")) for row in rows), "Unreviewed locked rows")
    check("manifest_all_rows_human_reviewed", manifest.get("all_rows_human_reviewed") is True, "Manifest human-review assertion is false")
    check("zero_unresolved_flags", unresolved_flags == 0, f"Found {unresolved_flags} unresolved flags")
    check("valid_preservation_values", all(row.get("preservation_score") in {"0", "1"} for row in rows), "Invalid preservation value")
    check("valid_distortion_values", all(row.get("distortion_score") in {"0", "1", "2"} for row in rows), "Invalid distortion value")
    check(
        "material_distortion_implies_zero_preservation",
        all(row.get("distortion_score") != "2" or row.get("preservation_score") == "0" for row in rows),
        "Distortion 2 paired with nonzero preservation",
    )
    check("locked_csv_path_matches", manifest.get("locked_scoring_csv") == locked_rel, "Locked CSV path mismatch")
    check("locked_csv_hash_matches", manifest.get("locked_scoring_sha256") == locked_hash, "Locked CSV changed after lock")

    hash_inputs = (
        ("review_log", "review_log_sha256", "review_log_hash_matches"),
        (None, "suggestions_sha256", "suggestions_hash_matches"),
        (None, "scoring_jobs_manifest_sha256", "scoring_jobs_manifest_hash_matches"),
        (None, "scoring_guide_sha256", "scoring_guide_hash_matches"),
    )
    review_rel = manifest.get("review_log")
    suggestions_path = root / f"analysis/model_assisted_scoring/preannotations/{measure}/{measure}_suggestions.csv"
    jobs_path = root / f"analysis/model_assisted_scoring/jobs/{measure}/manifest.json"
    guide_path = root / "data/reference_inventories/SCORING_GUIDE.md"
    paths = {
        "review_log_hash_matches": root / review_rel if isinstance(review_rel, str) else None,
        "suggestions_hash_matches": suggestions_path,
        "scoring_jobs_manifest_hash_matches": jobs_path,
        "scoring_guide_hash_matches": guide_path,
    }
    for _, manifest_key, check_name in hash_inputs:
        recorded = manifest.get(manifest_key)
        path = paths[check_name]
        present = isinstance(recorded, str) and len(recorded) == 64 and path is not None and path.is_file()
        current = sha256_file(root, path) if present and path is not None else None
        check(check_name, present and current == recorded, f"{check_name} failed")

    check(
        "locked_artifact_content_unchanged",
        checks["locked_csv_hash_matches"] and all(
            checks[name] for name in (
                "review_log_hash_matches", "suggestions_hash_matches",
                "scoring_jobs_manifest_hash_matches", "scoring_guide_hash_matches",
            )
        ),
        "Locked artifact or a lock-recorded input changed after creation",
    )
    return {
        "measure_id": measure,
        "status": "PASS" if not errors else "FAIL",
        "checks": checks, "errors": errors,
        "expected_row_count": expected_rows, "row_count": len(rows),
        "unresolved_flags": unresolved_flags,
        "locked_csv_path": locked_rel, "locked_csv_sha256": locked_hash,
        "scoring_lock_manifest_path": lock_manifest_rel,
        "scoring_lock_manifest_sha256": manifest_hash,
        "locked_at_utc": manifest.get("locked_at_utc"),
    }


def run_audit(root: Path) -> Path:
    output_path = root / OUTPUT_REL
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing pre-unblind manifest: {output_path}")
    measures = [audit_measure(root, measure) for measure in MEASURES]
    total_rows = sum(row["row_count"] or 0 for row in measures)
    unresolved_flags = sum(row["unresolved_flags"] or 0 for row in measures)
    locked_count = sum(
        row["checks"].get("locked_csv_exists", False)
        and row["checks"].get("lock_manifest_exists", False)
        for row in measures
    )
    all_pass = (
        locked_count == 10 and total_rows == 5_872 and unresolved_flags == 0
        and all(row["status"] == "PASS" for row in measures)
    )
    if not all_pass:
        failures = {row["measure_id"]: row["errors"] for row in measures if row["status"] != "PASS"}
        raise IntegrityError(
            "PRE-UNBLIND AUDIT FAILED; manifest not written: "
            + json.dumps({
                "locked_count": locked_count, "total_rows": total_rows,
                "unresolved_flags": unresolved_flags, "failures": failures,
            }, sort_keys=True)
        )
    value = {
        "schema_version": "1.0",
        "manifest_type": "PRE_UNBLIND_INTEGRITY_MANIFEST",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "condition_blind": True,
        "measure_ids": list(MEASURES),
        "requirements": {
            "locked_measures_required": 10, "total_locked_rows_required": 5_872,
            "unresolved_flags_required": 0,
        },
        "summary": {
            "status": "PASS", "locked_measures": locked_count,
            "total_locked_rows": total_rows, "unresolved_flags": unresolved_flags,
            "measures_passed": 10, "measures_failed": 0,
        },
        "measures": measures,
    }
    atomic_write_json(root, output_path, value)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Final condition-blind pre-unblind integrity audit")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args()
    print(run_audit(args.root.resolve()))


if __name__ == "__main__":
    main()
