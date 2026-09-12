from __future__ import annotations

import argparse
import csv
import io
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.scoring.integrity import (
    IntegrityError, atomic_write_json, atomic_write_text, read_text,
    require_unique, sha256_file, validate_measure,
)
from src.scoring.review_app import load_reviews, resolve_review_paths

ROOT = Path(__file__).resolve().parents[2]


def pilot_calibration(root: Path, measure: str, suggestions_file: Path) -> Path:
    measure = validate_measure(measure)
    suggestions_path, review_log_path = resolve_review_paths(root, measure, suggestions_file)
    suggestions = list(csv.DictReader(read_text(root, suggestions_path).splitlines()))
    reviews = load_reviews(root, review_log_path)
    keys = [(row["blind_id"], row["component_id"]) for row in suggestions]
    require_unique(("\x1f".join(key) for key in keys), "pilot suggestion row")
    if len(keys) != 128 or len({key[0] for key in keys}) != 2:
        raise IntegrityError(f"M05 two-output pilot must contain 128 rows across 2 blind IDs; found {len(keys)} rows")
    if set(reviews) != set(keys):
        missing, extra = set(keys) - set(reviews), set(reviews) - set(keys)
        raise IntegrityError(f"Pilot review incomplete or mismatched: {len(missing)} missing, {len(extra)} extra")

    confusion = {f"model_{m}_human_{h}": 0 for m in (0, 1) for h in (0, 1)}
    distortion_matches = 0
    flagged = 0
    disagreements: list[dict] = []
    by_component: Counter[str] = Counter()
    by_blind: Counter[str] = Counter()
    for model in suggestions:
        key = (model["blind_id"], model["component_id"])
        human = reviews[key]
        if human.get("human_reviewed") is not True:
            raise IntegrityError(f"Pilot row is not human reviewed: {key}")
        mp, hp = int(model["suggested_preservation"]), human.get("preservation_score")
        md, hd = int(model["distortion_severity"]), human.get("distortion_score")
        if type(hp) is not int or hp not in (0, 1):
            raise IntegrityError(f"Invalid human preservation score: {key}")
        if type(hd) is not int or hd not in (0, 1, 2):
            raise IntegrityError(f"Invalid human distortion score: {key}")
        if hd == 2 and hp != 0:
            raise IntegrityError(f"Material distortion requires preservation 0: {key}")
        confusion[f"model_{mp}_human_{hp}"] += 1
        distortion_matches += md == hd
        flagged += human.get("flagged") is True
        if mp != hp or md != hd:
            by_component[key[1]] += 1; by_blind[key[0]] += 1
            disagreements.append({
                "blind_id": key[0], "component_id": key[1],
                "model_preservation": mp, "human_preservation": hp,
                "model_distortion": md, "human_distortion": hd,
                "model_evidence_quote": model["exact_evidence_quote"],
                "model_reason": model["short_reason"],
                "human_flagged": human.get("flagged", False),
                "human_note": human.get("human_note", ""),
            })

    total = len(suggestions)
    matches = confusion["model_0_human_0"] + confusion["model_1_human_1"]
    pilot_slug = re.sub(r"_suggestions\.csv$", "", suggestions_path.name)
    out_dir = root / "analysis/model_assisted_scoring/calibration" / pilot_slug
    summary_path = out_dir / "calibration_summary.json"
    disagreement_path = out_dir / "disagreements.csv"
    summary = {
        "schema_version": "1.0", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "measure_id": measure, "pilot": True, "blinded": True, "row_count": total,
        "blind_output_count": len({key[0] for key in keys}),
        "preservation_agreement_count": matches,
        "preservation_agreement_rate": matches / total,
        "model_1_human_0_count": confusion["model_1_human_0"],
        "model_0_human_1_count": confusion["model_0_human_1"],
        "preservation_confusion_matrix": confusion,
        "distortion_agreement_count": distortion_matches,
        "distortion_agreement_rate": distortion_matches / total,
        "flagged_rows": flagged,
        "disagreement_count": len(disagreements),
        "disagreements_by_component_id": dict(by_component.most_common()),
        "disagreements_by_blind_id": dict(by_blind.most_common()),
        "input_hashes": {
            "suggestions": sha256_file(root, suggestions_path),
            "review_log": sha256_file(root, review_log_path),
        },
    }
    atomic_write_json(root, summary_path, summary)
    fields = [
        "blind_id", "component_id", "model_preservation", "human_preservation",
        "model_distortion", "human_distortion", "model_evidence_quote", "model_reason",
        "human_flagged", "human_note",
    ]
    stream = io.StringIO(newline=""); writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader(); writer.writerows(disagreements)
    atomic_write_text(root, disagreement_path, stream.getvalue())
    return summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Blinded calibration for a reviewed pilot subset")
    parser.add_argument("--measure", required=True)
    parser.add_argument("--suggestions-file", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args()
    print(pilot_calibration(args.root.resolve(), args.measure, args.suggestions_file))


if __name__ == "__main__":
    main()
