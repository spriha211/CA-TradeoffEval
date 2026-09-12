from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from src.scoring.integrity import (
    IntegrityError, atomic_write_json, atomic_write_text, read_text,
    require_unique, sha256_file, validate_measure,
)
from src.scoring.review_app import load_reviews

ROOT = Path(__file__).resolve().parents[2]


def lock_scores(root: Path, measure: str) -> Path:
    measure = validate_measure(measure)
    base = root / f"analysis/model_assisted_scoring/preannotations/{measure}"
    suggestions_path = base / f"{measure}_suggestions.csv"
    log_path = root / f"analysis/model_assisted_scoring/reviews/{measure}_review_log.jsonl"
    rows = list(csv.DictReader(read_text(root, suggestions_path).splitlines()))
    reviews = load_reviews(root, log_path)
    keys = [(row["blind_id"], row["component_id"]) for row in rows]
    require_unique(("\x1f".join(key) for key in keys), "suggestion row")
    if set(reviews) != set(keys):
        missing = set(keys) - set(reviews)
        extra = set(reviews) - set(keys)
        raise IntegrityError(f"Human review incomplete or mismatched: {len(missing)} missing, {len(extra)} extra")

    locked = []
    for row in rows:
        review = reviews[(row["blind_id"], row["component_id"])]
        if review.get("human_reviewed") is not True:
            raise IntegrityError(f"Row is not human reviewed: {row['blind_id']} {row['component_id']}")
        preservation, distortion = review.get("preservation_score"), review.get("distortion_score")
        if type(preservation) is not int or preservation not in (0, 1):
            raise IntegrityError("Invalid human preservation score")
        if type(distortion) is not int or distortion not in (0, 1, 2):
            raise IntegrityError("Invalid human distortion score")
        if distortion == 2 and preservation != 0:
            raise IntegrityError("Material distortion must have preservation 0")
        locked.append({
            "blind_id": row["blind_id"],
            "component_id": row["component_id"],
            "preservation_score": preservation,
            "distortion_score": distortion,
            "flagged": review.get("flagged", False),
            "human_note": review.get("human_note", ""),
            "human_reviewed": True,
            "review_timestamp_utc": review["timestamp_utc"],
        })

    out_dir = root / "results/locked_scoring" / measure
    csv_path = out_dir / f"{measure}_locked_scoring.csv"
    manifest_path = out_dir / f"{measure}_scoring_lock_manifest.json"
    if csv_path.exists() or manifest_path.exists():
        raise FileExistsError(f"Refusing to overwrite an existing scoring lock for {measure}")
    fields = list(locked[0])
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader(); writer.writerows(locked)
    atomic_write_text(root, csv_path, stream.getvalue())
    guide_path = root / "data/reference_inventories/SCORING_GUIDE.md"
    jobs_manifest = root / f"analysis/model_assisted_scoring/jobs/{measure}/manifest.json"
    manifest = {
        "schema_version": "1.0",
        "locked_at_utc": datetime.now(timezone.utc).isoformat(),
        "measure_id": measure,
        "row_count": len(locked),
        "all_rows_human_reviewed": True,
        "locked_scoring_csv": str(csv_path.relative_to(root)),
        "locked_scoring_sha256": sha256_file(root, csv_path),
        "review_log": str(log_path.relative_to(root)),
        "review_log_sha256": sha256_file(root, log_path),
        "suggestions_sha256": sha256_file(root, suggestions_path),
        "scoring_jobs_manifest_sha256": sha256_file(root, jobs_manifest),
        "scoring_guide_sha256": sha256_file(root, guide_path),
    }
    atomic_write_json(root, manifest_path, manifest)
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Lock fully human-reviewed blinded scores")
    parser.add_argument("--measure", required=True)
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args()
    print(lock_scores(args.root.resolve(), args.measure))


if __name__ == "__main__":
    main()
