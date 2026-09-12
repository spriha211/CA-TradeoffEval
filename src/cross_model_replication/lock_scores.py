from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from src.cross_model_replication.generate import MEASURES, ROOT, atomic_json, atomic_text, sha256_file
from src.cross_model_replication.review_app import latest_reviews
from src.cross_model_replication.scoring import ANALYSIS_ROOT, PROMPT_PATH, PROMPT_SHA256

LOCK_ROOT = ROOT / "results/cross_model_replication/claude_sonnet_5/locked_scoring"


def lock_measure(measure: str) -> Path:
    if measure not in MEASURES:
        raise ValueError("Measure is outside the frozen Study 2 selection")
    jobs_manifest_path = ANALYSIS_ROOT / "jobs" / measure / "manifest.json"
    jobs_manifest = json.loads(jobs_manifest_path.read_text(encoding="utf-8"))
    suggestions_path = ANALYSIS_ROOT / "preannotations" / measure / f"{measure}_suggestions.csv"
    review_log_path = ANALYSIS_ROOT / "reviews" / f"{measure}_review_log.jsonl"
    with suggestions_path.open(newline="", encoding="utf-8") as stream:
        suggestions = list(csv.DictReader(stream))
    latest = latest_reviews(review_log_path)
    keys = [(row["blind_id"], row["component_id"]) for row in suggestions]
    if len(keys) != jobs_manifest["expected_rows"] or len(set(keys)) != len(keys):
        raise RuntimeError("Suggestion rows are missing or duplicated")
    if len({row["blind_id"] for row in suggestions}) != 16:
        raise RuntimeError("Expected exactly 16 blinded outputs")
    if set(latest) != set(keys):
        raise RuntimeError("Latest human reviews do not exactly match suggestion rows")
    locked = []
    for row in suggestions:
        review = latest[(row["blind_id"], row["component_id"])]
        if review.get("human_reviewed") is not True:
            raise RuntimeError("Every scoring row must be human reviewed")
        if review.get("flagged") is True:
            raise RuntimeError("Cannot lock with unresolved flags")
        preservation = review.get("preservation_score")
        distortion = review.get("distortion_score")
        if type(preservation) is not int or preservation not in (0, 1):
            raise RuntimeError("Invalid preservation score")
        if type(distortion) is not int or distortion not in (0, 1, 2):
            raise RuntimeError("Invalid distortion score")
        if distortion == 2 and preservation != 0:
            raise RuntimeError("Distortion 2 requires preservation 0")
        locked.append({
            "blind_id": row["blind_id"], "component_id": row["component_id"],
            "preservation_score": preservation, "distortion_score": distortion,
            "flagged": False, "human_note": review.get("human_note", ""),
            "human_reviewed": True, "review_timestamp_utc": review["timestamp_utc"],
        })
    out_dir = LOCK_ROOT / measure
    csv_path = out_dir / f"{measure}_locked_scoring.csv"
    manifest_path = out_dir / f"{measure}_scoring_lock_manifest.json"
    if csv_path.exists() or manifest_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing Study 2 lock for {measure}")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(locked[0]))
    writer.writeheader(); writer.writerows(locked)
    atomic_text(csv_path, buffer.getvalue())
    guide_path = ROOT / "data/reference_inventories/SCORING_GUIDE.md"
    inventory_path = ROOT / "data/reference_inventories" / f"{measure}_components.csv"
    atomic_json(manifest_path, {
        "schema_version": "1.0", "study": "Study 2",
        "locked_at_utc": datetime.now(timezone.utc).isoformat(), "measure_id": measure,
        "row_count": len(locked), "blind_output_count": 16,
        "all_rows_human_reviewed": True, "unresolved_flag_count": 0,
        "locked_scoring_csv": str(csv_path.relative_to(ROOT)),
        "locked_scoring_sha256": sha256_file(csv_path),
        "review_log": str(review_log_path.relative_to(ROOT)),
        "review_log_sha256": sha256_file(review_log_path),
        "suggestions": str(suggestions_path.relative_to(ROOT)),
        "suggestions_sha256": sha256_file(suggestions_path),
        "scoring_jobs_manifest": str(jobs_manifest_path.relative_to(ROOT)),
        "scoring_jobs_manifest_sha256": sha256_file(jobs_manifest_path),
        "inventory_sha256": sha256_file(inventory_path),
        "scoring_guide_sha256": sha256_file(guide_path),
        "scoring_prompt": str(PROMPT_PATH.relative_to(ROOT)),
        "scoring_prompt_sha256": PROMPT_SHA256,
    })
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Lock complete blinded Study 2 human scores")
    parser.add_argument("--measure", required=True, choices=MEASURES)
    args = parser.parse_args()
    print(lock_measure(args.measure))


if __name__ == "__main__":
    main()
