from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.scoring.integrity import (
    IntegrityError, append_jsonl_batch, atomic_write_json, read_text,
    sha256_file,
)
from src.scoring.review_app import load_reviews

ROOT = Path(__file__).resolve().parents[2]
MEASURE = "M05"
PILOT_LOG_REL = "analysis/model_assisted_scoring/reviews/M05_pilot_first_2_review_log.jsonl"
PRODUCTION_LOG_REL = "analysis/model_assisted_scoring/reviews/M05_review_log.jsonl"
PILOT_SUGGESTIONS_REL = "analysis/model_assisted_scoring/preannotations/M05/M05_pilot_first_2_suggestions.csv"
FULL_SUGGESTIONS_REL = "analysis/model_assisted_scoring/preannotations/M05/M05_suggestions.csv"
AUDIT_REL = "runs/audits/model_assisted_scoring/M05_pilot_review_import_manifest.json"


def _csv_map(root: Path, path: Path) -> dict[tuple[str, str], dict[str, str]]:
    rows = list(csv.DictReader(read_text(root, path).splitlines()))
    result = {(row["blind_id"], row["component_id"]): row for row in rows}
    if len(result) != len(rows):
        raise IntegrityError(f"Duplicate suggestion rows in {path}")
    return result


def import_pilot_reviews(root: Path) -> Path:
    pilot_log = root / PILOT_LOG_REL
    production_log = root / PRODUCTION_LOG_REL
    pilot_suggestions_path = root / PILOT_SUGGESTIONS_REL
    full_suggestions_path = root / FULL_SUGGESTIONS_REL
    audit_path = root / AUDIT_REL
    if audit_path.exists():
        raise FileExistsError(f"Pilot import audit already exists; refusing duplicate import: {audit_path}")

    pilot_hash = sha256_file(root, pilot_log)
    pilot_rows = _csv_map(root, pilot_suggestions_path)
    full_rows = _csv_map(root, full_suggestions_path)
    latest: dict[tuple[str, str], tuple[int, dict]] = {}
    for line_number, line in enumerate(read_text(root, pilot_log).splitlines(), start=1):
        event = json.loads(line)
        latest[(event["blind_id"], event["component_id"])] = (line_number, event)
    if len(latest) != 128:
        raise IntegrityError(f"Expected exactly 128 latest pilot decisions; found {len(latest)}")
    expected_blinds = {"M05-B001", "M05-B002"}
    if {key[0] for key in latest} != expected_blinds:
        raise IntegrityError("Pilot decisions are not restricted to M05-B001 and M05-B002")
    if set(latest) != set(pilot_rows) or not set(latest).issubset(full_rows):
        raise IntegrityError("Pilot review keys do not exactly match pilot/full suggestion rows")

    existing = load_reviews(root, production_log)
    overlap = set(existing).intersection(latest)
    if overlap:
        raise IntegrityError(f"Production decisions already exist for {len(overlap)} pilot rows")

    compare_fields = (
        "suggested_preservation", "exact_evidence_quote", "short_reason", "confidence",
        "distortion_severity", "distortion_explanation", "needs_human_review",
    )
    imported_at = datetime.now(timezone.utc).isoformat()
    new_events = []
    for key in sorted(latest):
        line_number, source = latest[key]
        if source.get("human_reviewed") is not True:
            raise IntegrityError(f"Pilot decision is not human reviewed: {key}")
        preservation, distortion = source.get("preservation_score"), source.get("distortion_score")
        if type(preservation) is not int or preservation not in (0, 1):
            raise IntegrityError(f"Invalid pilot preservation value: {key}")
        if type(distortion) is not int or distortion not in (0, 1, 2):
            raise IntegrityError(f"Invalid pilot distortion value: {key}")
        if distortion == 2 and preservation != 0:
            raise IntegrityError(f"Material pilot distortion requires preservation 0: {key}")
        if source.get("flagged") is True:
            raise IntegrityError(f"Refusing to import unresolved flagged decision: {key}")
        if any(pilot_rows[key][field] != full_rows[key][field] for field in compare_fields):
            raise IntegrityError(f"Pilot and full suggestions differ for {key}")
        if int(full_rows[key]["suggested_preservation"]) != source.get("model_suggested_preservation"):
            raise IntegrityError(f"Pilot event model preservation provenance mismatch: {key}")
        if int(full_rows[key]["distortion_severity"]) != source.get("model_distortion_severity"):
            raise IntegrityError(f"Pilot event model distortion provenance mismatch: {key}")
        new_events.append({
            "schema_version": "1.0", "timestamp_utc": imported_at,
            "measure_id": MEASURE, "blind_id": key[0], "component_id": key[1],
            "human_reviewed": True, "preservation_score": preservation,
            "distortion_score": distortion, "flagged": False,
            "human_note": source.get("human_note", ""),
            "model_suggested_preservation": int(full_rows[key]["suggested_preservation"]),
            "model_distortion_severity": int(full_rows[key]["distortion_severity"]),
            "provenance": {
                "import_type": "latest_pilot_review_decision",
                "source_review_log": PILOT_LOG_REL,
                "source_review_log_sha256": pilot_hash,
                "source_event_line": line_number,
                "source_event_timestamp_utc": source.get("timestamp_utc"),
            },
        })

    if len(new_events) != 128:
        raise IntegrityError("Internal import row-count failure")
    append_jsonl_batch(root, production_log, new_events)
    production_latest = load_reviews(root, production_log)
    if not set(latest).issubset(production_latest):
        raise IntegrityError("Post-import production log verification failed")
    manifest = {
        "schema_version": "1.0", "imported_at_utc": imported_at,
        "measure_id": MEASURE, "imported_decision_count": 128,
        "source_review_log": PILOT_LOG_REL, "source_review_log_sha256": pilot_hash,
        "source_pilot_suggestions_sha256": sha256_file(root, pilot_suggestions_path),
        "full_suggestions_sha256": sha256_file(root, full_suggestions_path),
        "production_review_log": PRODUCTION_LOG_REL,
        "production_review_log_sha256_after_import": sha256_file(root, production_log),
        "unresolved_flags_imported": 0,
    }
    atomic_write_json(root, audit_path, manifest)
    return audit_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Import resolved M05 pilot reviews into production")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args()
    print(import_pilot_reviews(args.root.resolve()))


if __name__ == "__main__":
    main()
