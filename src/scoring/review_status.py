from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.scoring.integrity import IntegrityError, MEASURES, read_text
from src.scoring.review_app import load_reviews

ROOT = Path(__file__).resolve().parents[2]


def measure_status(root: Path, measure: str) -> dict:
    suggestions_path = root / f"analysis/model_assisted_scoring/preannotations/{measure}/{measure}_suggestions.csv"
    review_log_path = root / f"analysis/model_assisted_scoring/reviews/{measure}_review_log.jsonl"
    rows = list(csv.DictReader(read_text(root, suggestions_path).splitlines()))
    keys = [(row["blind_id"], row["component_id"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise IntegrityError(f"Duplicate suggestion rows for {measure}")
    reviews = load_reviews(root, review_log_path)
    extra = set(reviews) - set(keys)
    if extra:
        raise IntegrityError(f"Review log has {len(extra)} rows outside {measure} suggestions")
    reviewed = {key for key, event in reviews.items() if event.get("human_reviewed") is True}
    blind_order = list(dict.fromkeys(key[0] for key in keys))
    components_by_blind = {
        blind_id: {key for key in keys if key[0] == blind_id} for blind_id in blind_order
    }
    reviewed_blinds = [
        blind_id for blind_id in blind_order if components_by_blind[blind_id].issubset(reviewed)
    ]
    remaining_blinds = [blind_id for blind_id in blind_order if blind_id not in reviewed_blinds]
    unresolved_flags = sum(
        event.get("human_reviewed") is True and event.get("flagged") is True
        for event in reviews.values()
    )
    return {
        "measure_id": measure,
        "expected_component_rows": len(keys),
        "reviewed_latest_rows": len(reviewed),
        "remaining_rows": len(keys) - len(reviewed),
        "reviewed_blind_outputs": len(reviewed_blinds),
        "remaining_blind_outputs": len(remaining_blinds),
        "unresolved_flags": unresolved_flags,
        "first_unreviewed_blind_id": remaining_blinds[0] if remaining_blinds else None,
    }


def all_status(root: Path) -> list[dict]:
    return [measure_status(root, measure) for measure in MEASURES]


def main() -> None:
    parser = argparse.ArgumentParser(description="Condition-blind human review status")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args()
    rows = all_status(args.root.resolve())
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    headers = ("Measure", "Rows", "Reviewed", "Remaining", "Outputs done", "Outputs left", "Flags", "Resume")
    print("\t".join(headers))
    for row in rows:
        print("\t".join(str(value) for value in (
            row["measure_id"], row["expected_component_rows"], row["reviewed_latest_rows"],
            row["remaining_rows"], row["reviewed_blind_outputs"],
            row["remaining_blind_outputs"], row["unresolved_flags"],
            row["first_unreviewed_blind_id"] or "complete",
        )))


if __name__ == "__main__":
    main()
