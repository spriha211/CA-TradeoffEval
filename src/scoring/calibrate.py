from __future__ import annotations

import argparse
import csv
import io
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.scoring.integrity import (
    IntegrityError, atomic_write_json, atomic_write_text, read_text,
    require_unique, sha256_file, validate_measure,
)

ROOT = Path(__file__).resolve().parents[2]


def _rows(root: Path, path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(read_text(root, path).splitlines()))


def calibration_report(root: Path, measure: str) -> Path:
    measure = validate_measure(measure)
    suggestions_path = root / f"analysis/model_assisted_scoring/preannotations/{measure}/{measure}_suggestions.csv"
    locked_path = root / f"results/locked_scoring/{measure}/{measure}_locked_scoring.csv"
    lock_manifest_path = root / f"results/locked_scoring/{measure}/{measure}_scoring_lock_manifest.json"
    suggestions, locked = _rows(root, suggestions_path), _rows(root, locked_path)
    lock_manifest = json.loads(read_text(root, lock_manifest_path))
    if lock_manifest.get("all_rows_human_reviewed") is not True:
        raise IntegrityError("Calibration requires a fully human-reviewed scoring lock")

    suggestion_map = {(r["blind_id"], r["component_id"]): r for r in suggestions}
    locked_map = {(r["blind_id"], r["component_id"]): r for r in locked}
    require_unique(("\x1f".join(k) for k in suggestion_map), "suggestion row")
    require_unique(("\x1f".join(k) for k in locked_map), "locked row")
    if len(suggestion_map) != len(suggestions) or len(locked_map) != len(locked):
        raise IntegrityError("Duplicate calibration rows")
    if set(suggestion_map) != set(locked_map):
        raise IntegrityError("Suggestion and locked row keys do not match")

    confusion = {f"model_{m}_human_{h}": 0 for m in (0, 1) for h in (0, 1)}
    distortion_matches = 0
    disagreements = []
    by_component: Counter[str] = Counter()
    by_blind: Counter[str] = Counter()
    for key in sorted(suggestion_map):
        model, human = suggestion_map[key], locked_map[key]
        mp, hp = int(model["suggested_preservation"]), int(human["preservation_score"])
        md, hd = int(model["distortion_severity"]), int(human["distortion_score"])
        confusion[f"model_{mp}_human_{hp}"] += 1
        distortion_matches += md == hd
        if mp != hp or md != hd:
            by_component[key[1]] += 1
            by_blind[key[0]] += 1
            disagreements.append({
                "blind_id": key[0], "component_id": key[1],
                "model_preservation": mp, "human_preservation": hp,
                "model_distortion": md, "human_distortion": hd,
                "model_evidence_quote": model["exact_evidence_quote"],
                "model_reason": model["short_reason"],
                "model_confidence": model["confidence"],
                "model_needs_human_review": model["needs_human_review"],
                "human_flagged": human["flagged"], "human_note": human["human_note"],
            })

    total = len(locked)
    preservation_matches = confusion["model_0_human_0"] + confusion["model_1_human_1"]
    flagged = sum(r["flagged"].lower() == "true" for r in locked)
    summary = {
        "schema_version": "1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "measure_id": measure,
        "blinded": True,
        "row_count": total,
        "exact_preservation_agreement_count": preservation_matches,
        "exact_preservation_agreement_rate": preservation_matches / total,
        "model_1_human_0_count": confusion["model_1_human_0"],
        "model_0_human_1_count": confusion["model_0_human_1"],
        "preservation_confusion_matrix": confusion,
        "distortion_agreement_count": distortion_matches,
        "distortion_agreement_rate": distortion_matches / total,
        "any_score_disagreement_count": len(disagreements),
        "remaining_flagged_rows": flagged,
        "disagreements_by_component_id": dict(by_component.most_common()),
        "disagreements_by_blind_id": dict(by_blind.most_common()),
        "input_hashes": {
            "suggestions": sha256_file(root, suggestions_path),
            "locked_scoring": sha256_file(root, locked_path),
            "lock_manifest": sha256_file(root, lock_manifest_path),
        },
    }
    out_dir = root / f"analysis/model_assisted_scoring/calibration/{measure}"
    summary_path = out_dir / "calibration_summary.json"
    disagreement_path = out_dir / "disagreements.csv"
    component_path = out_dir / "disagreements_by_component.csv"
    blind_path = out_dir / "disagreements_by_blind_id.csv"
    atomic_write_json(root, summary_path, summary)

    disagreement_fields = [
        "blind_id", "component_id", "model_preservation", "human_preservation",
        "model_distortion", "human_distortion", "model_evidence_quote", "model_reason",
        "model_confidence", "model_needs_human_review", "human_flagged", "human_note",
    ]
    def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
        stream = io.StringIO(newline=""); writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows); atomic_write_text(root, path, stream.getvalue())
    write_csv(disagreement_path, disagreement_fields, disagreements)
    write_csv(component_path, ["component_id", "disagreement_count"], [
        {"component_id": key, "disagreement_count": value} for key, value in by_component.most_common()
    ])
    write_csv(blind_path, ["blind_id", "disagreement_count"], [
        {"blind_id": key, "disagreement_count": value} for key, value in by_blind.most_common()
    ])
    return summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Blinded model-versus-human calibration report")
    parser.add_argument("--measure", required=True)
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args()
    print(calibration_report(args.root.resolve(), args.measure))


if __name__ == "__main__":
    main()
