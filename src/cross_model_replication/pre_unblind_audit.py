from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.cross_model_replication.generate import PROTOCOL, PROTOCOL_SHA256, ROOT, RUN_ROOT, atomic_json, sha256_file
from src.cross_model_replication.lock_scores import LOCK_ROOT
from src.cross_model_replication.scoring import ANALYSIS_ROOT

MEASURES = ["M03", "M08", "M02", "M09", "M05"]
EXPECTED_ROWS = {"M03": 928, "M08": 448, "M02": 1040, "M09": 400, "M05": 1024}
OUTPUT = ROOT / "runs/audits/cross_model_replication/STUDY2_PRE_UNBLIND_INTEGRITY_MANIFEST.json"


def audit() -> Path:
    if sha256_file(PROTOCOL) != PROTOCOL_SHA256:
        raise RuntimeError("Frozen Study 2 protocol hash mismatch")
    measures = []
    total_rows = total_outputs = total_flags = 0
    for measure in MEASURES:
        lock_manifest_path = LOCK_ROOT / measure / f"{measure}_scoring_lock_manifest.json"
        if not lock_manifest_path.exists():
            raise RuntimeError(f"Missing Study 2 lock: {measure}")
        lock = json.loads(lock_manifest_path.read_text(encoding="utf-8"))
        locked_csv = ROOT / lock["locked_scoring_csv"]
        review_log = ROOT / lock["review_log"]
        suggestions = ROOT / lock["suggestions"]
        jobs_manifest = ROOT / lock["scoring_jobs_manifest"]
        inventory = ROOT / "data/reference_inventories" / f"{measure}_components.csv"
        guide = ROOT / "data/reference_inventories/SCORING_GUIDE.md"
        checks = {
            "locked_csv_hash_matches": sha256_file(locked_csv) == lock["locked_scoring_sha256"],
            "review_log_hash_matches": sha256_file(review_log) == lock["review_log_sha256"],
            "suggestions_hash_matches": sha256_file(suggestions) == lock["suggestions_sha256"],
            "jobs_manifest_hash_matches": sha256_file(jobs_manifest) == lock["scoring_jobs_manifest_sha256"],
            "inventory_hash_matches": sha256_file(inventory) == lock["inventory_sha256"],
            "scoring_guide_hash_matches": sha256_file(guide) == lock["scoring_guide_sha256"],
            "scoring_prompt_hash_matches": lock["scoring_prompt_sha256"] == "32097fee8cf8f7a3bc2e70ba1e3079b275763e9cc966e5d2d13e47981e7919d8",
        }
        with locked_csv.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        keys = [(row["blind_id"], row["component_id"]) for row in rows]
        valid = all(
            row["human_reviewed"] == "True" and row["flagged"] == "False"
            and row["preservation_score"] in ("0", "1")
            and row["distortion_score"] in ("0", "1", "2")
            and not (row["distortion_score"] == "2" and row["preservation_score"] != "0")
            for row in rows
        )
        outputs = sorted((RUN_ROOT / "blinded" / measure).glob(f"{measure}-C*.txt"))
        checks.update({
            "expected_row_count": len(rows) == EXPECTED_ROWS[measure] == lock["row_count"],
            "unique_blind_component_pairs": len(set(keys)) == len(rows),
            "all_rows_valid_and_reviewed": valid,
            "zero_unresolved_flags": lock["unresolved_flag_count"] == 0 and all(row["flagged"] == "False" for row in rows),
            "sixteen_blinded_outputs": len(outputs) == 16 and len({row["blind_id"] for row in rows}) == 16,
        })
        passed = all(checks.values())
        if not passed:
            raise RuntimeError(f"Study 2 pre-unblind audit failed for {measure}: {checks}")
        total_rows += len(rows); total_outputs += len(outputs)
        measures.append({
            "measure_id": measure, "status": "PASS", "row_count": len(rows),
            "blind_output_count": len(outputs), "unresolved_flag_count": 0,
            "locked_scoring_csv": str(locked_csv.relative_to(ROOT)),
            "locked_scoring_sha256": sha256_file(locked_csv),
            "scoring_lock_manifest": str(lock_manifest_path.relative_to(ROOT)),
            "scoring_lock_manifest_sha256": sha256_file(lock_manifest_path),
            "review_log": str(review_log.relative_to(ROOT)),
            "review_log_sha256": sha256_file(review_log),
            "blinded_outputs": [{"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)} for path in outputs],
            "checks": checks,
        })
    requirements = {
        "five_of_five_measures_locked": len(measures) == 5,
        "eighty_of_eighty_final_outputs": total_outputs == 80,
        "three_thousand_eight_hundred_forty_locked_rows": total_rows == 3840,
        "zero_unresolved_flags": total_flags == 0,
        "frozen_protocol_hash_matches": sha256_file(PROTOCOL) == PROTOCOL_SHA256,
        "all_measure_checks_pass": all(item["status"] == "PASS" for item in measures),
    }
    if not all(requirements.values()):
        raise RuntimeError(f"Study 2 pre-unblind requirements failed: {requirements}")
    atomic_json(OUTPUT, {
        "schema_version": "1.0", "study": "Study 2",
        "audit_phase": "PRE_UNBLIND", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS", "mapping_accessed": False,
        "protocol": {"path": str(PROTOCOL.relative_to(ROOT)), "sha256": PROTOCOL_SHA256},
        "measure_count": len(measures), "total_blinded_outputs": total_outputs,
        "total_locked_scoring_rows": total_rows, "unresolved_flag_count": total_flags,
        "measures": measures, "requirements": requirements,
    })
    return OUTPUT


if __name__ == "__main__":
    print(audit())
