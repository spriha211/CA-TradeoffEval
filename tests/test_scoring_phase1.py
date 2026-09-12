from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.scoring.build_jobs import build_jobs
from src.scoring.calibrate import calibration_report
from src.scoring.calibrate_pilot import pilot_calibration
from src.scoring.integrity import (
    IntegrityError, atomic_write_text, authorize_write, reject_mapping_path,
)
from src.scoring.import_pilot_reviews import import_pilot_reviews
from src.scoring.lock_scores import lock_scores
from src.scoring.preannotate import (
    ComponentSuggestion, SuggestionBatch, fail_closed_invalid_quotes,
    run_preannotation, validate_batch,
)
from src.scoring.review_app import load_reviews, resolve_review_paths
from src.scoring.review_status import measure_status


def synthetic_root(tmp_path: Path) -> Path:
    root = tmp_path
    inventory = root / "data/reference_inventories"
    inventory.mkdir(parents=True)
    (inventory / "SCORING_GUIDE.md").write_text("Score explicit preservation only.\n")
    fields = ["component_id", "claim_id", "category", "component_text", "binary_scoring_rule", "source_page", "source_section"]
    with (inventory / "M04_components.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for i in range(1, 13):
            writer.writerow({
                "component_id": f"M04-T01-C{i:02d}", "claim_id": "M04-T01", "category": "test",
                "component_text": f"Fact {i}", "binary_scoring_rule": f"Score 1 if Fact {i} is stated.",
                "source_page": "1", "source_section": "Test",
            })
    blinded = root / "runs/blinded/M04"; blinded.mkdir(parents=True)
    for i in range(1, 17):
        (blinded / f"M04-B{i:03d}.txt").write_text("Fact 1 is stated.\n")
    return root


def valid_job() -> dict:
    return {
        "measure_id": "M04", "blind_id": "M04-B001", "blinded_answer": "Fact 1 is stated.",
        "components": [{"component_id": "M04-T01-C01"}],
    }


def valid_batch() -> SuggestionBatch:
    return SuggestionBatch(suggestions=[ComponentSuggestion(
        blind_id="M04-B001", component_id="M04-T01-C01", suggested_preservation=1,
        exact_evidence_quote="Fact 1", short_reason="Explicitly stated.", confidence=0.9,
        distortion_severity=0, distortion_explanation="", needs_human_review=False,
    )])


def test_forbidden_mapping_access(tmp_path: Path) -> None:
    with pytest.raises(IntegrityError):
        reject_mapping_path(tmp_path / "runs/scored/private_mappings/anything.json")
    with pytest.raises(IntegrityError):
        reject_mapping_path(tmp_path / "analysis/model_assisted_scoring/blind_mapping.csv")
    allowed = tmp_path / "runs/audits/model_assisted_scoring/PRE_UNBLIND_INTEGRITY_MANIFEST.json"
    assert authorize_write(tmp_path, allowed) == allowed.resolve()


def test_malformed_model_response() -> None:
    with pytest.raises(ValidationError):
        SuggestionBatch.model_validate({"suggestions": [{"blind_id": "M04-B001"}]})


def test_invalid_exact_quote() -> None:
    batch = valid_batch()
    batch.suggestions[0].exact_evidence_quote = "not present"
    with pytest.raises(IntegrityError, match="not exact"):
        validate_batch(batch, valid_job())


def test_invalid_quote_fail_closed_correction() -> None:
    batch = valid_batch()
    batch.suggestions[0].exact_evidence_quote = "not present"
    corrected, changed = fail_closed_invalid_quotes(batch, valid_job())
    assert changed == ["M04-T01-C01"]
    assert corrected.suggestions[0].suggested_preservation == 0
    assert corrected.suggestions[0].exact_evidence_quote == ""
    assert corrected.suggestions[0].needs_human_review is True
    assert batch.suggestions[0].suggested_preservation == 1
    validate_batch(corrected, valid_job())


@pytest.mark.parametrize("mode", ["missing", "duplicate"])
def test_missing_or_duplicate_model_rows(mode: str) -> None:
    batch = valid_batch()
    job = valid_job()
    if mode == "missing":
        batch.suggestions = []
    else:
        batch.suggestions.append(batch.suggestions[0].model_copy())
    with pytest.raises(IntegrityError):
        validate_batch(batch, job)


def prepare_lock_inputs(root: Path, reviewed_count: int) -> None:
    manifest = build_jobs(root, "M04")
    del manifest
    out = root / "analysis/model_assisted_scoring/preannotations/M04"
    out.mkdir(parents=True)
    fields = list(ComponentSuggestion.model_fields)
    stream = io.StringIO(newline=""); writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
    rows = []
    for blind in range(1, 17):
        for comp in range(1, 13):
            rows.append({
                "blind_id": f"M04-B{blind:03d}", "component_id": f"M04-T01-C{comp:02d}",
                "suggested_preservation": 0, "exact_evidence_quote": "", "short_reason": "Absent.",
                "confidence": 0.9, "distortion_severity": 0, "distortion_explanation": "",
                "needs_human_review": False,
            })
    writer.writerows(rows)
    atomic_write_text(root, out / "M04_suggestions.csv", stream.getvalue())
    log = root / "analysis/model_assisted_scoring/reviews/M04_review_log.jsonl"
    log.parent.mkdir(parents=True)
    with log.open("w") as handle:
        for row in rows[:reviewed_count]:
            handle.write(json.dumps({
                "timestamp_utc": "2026-01-01T00:00:00+00:00", "blind_id": row["blind_id"],
                "component_id": row["component_id"], "human_reviewed": True,
                "preservation_score": 0, "distortion_score": 0,
            }) + "\n")


def test_incomplete_human_review(tmp_path: Path) -> None:
    root = synthetic_root(tmp_path); prepare_lock_inputs(root, reviewed_count=191)
    with pytest.raises(IntegrityError, match="incomplete"):
        lock_scores(root, "M04")


def test_overwrite_refusal(tmp_path: Path) -> None:
    root = synthetic_root(tmp_path)
    build_jobs(root, "M04")
    with pytest.raises(FileExistsError):
        build_jobs(root, "M04")


def test_review_resume_uses_latest_and_leaves_unreviewed(tmp_path: Path) -> None:
    root = synthetic_root(tmp_path)
    log = root / "analysis/model_assisted_scoring/reviews/M04_review_log.jsonl"
    log.parent.mkdir(parents=True)
    events = [
        {"blind_id": "M04-B001", "component_id": "M04-T01-C01", "preservation_score": 0},
        {"blind_id": "M04-B001", "component_id": "M04-T01-C01", "preservation_score": 1},
    ]
    log.write_text("".join(json.dumps(event) + "\n" for event in events))
    latest = load_reviews(root, log)
    assert len(latest) == 1
    assert latest[("M04-B001", "M04-T01-C01")]["preservation_score"] == 1
    assert ("M04-B001", "M04-T01-C02") not in latest


def test_lock_and_second_lock_refusal(tmp_path: Path) -> None:
    root = synthetic_root(tmp_path); prepare_lock_inputs(root, reviewed_count=192)
    assert lock_scores(root, "M04").exists()
    with pytest.raises(FileExistsError):
        lock_scores(root, "M04")


def test_blinded_calibration_report(tmp_path: Path) -> None:
    root = synthetic_root(tmp_path); prepare_lock_inputs(root, reviewed_count=192)
    lock_scores(root, "M04")
    summary_path = calibration_report(root, "M04")
    summary = json.loads(summary_path.read_text())
    assert summary["blinded"] is True
    assert summary["row_count"] == 192
    assert summary["exact_preservation_agreement_rate"] == 1.0
    assert (summary_path.parent / "disagreements.csv").exists()


def test_preannotation_limit_resumes_checkpoint_without_api(tmp_path: Path) -> None:
    root = synthetic_root(tmp_path); build_jobs(root, "M04")
    job = json.loads((root / "analysis/model_assisted_scoring/jobs/M04/M04-B001.json").read_text())
    batch = SuggestionBatch(suggestions=[])
    for component in job["components"]:
        batch.suggestions.append(ComponentSuggestion(
            blind_id="M04-B001", component_id=component["component_id"],
            suggested_preservation=0, exact_evidence_quote="", short_reason="Absent.",
            confidence=0.9, distortion_severity=0, distortion_explanation="",
            needs_human_review=False,
        ))
    parsed = root / "analysis/model_assisted_scoring/preannotations/M04/parsed/M04-B001.json"
    atomic_write_text(root, parsed, batch.model_dump_json())
    output = run_preannotation(root, "M04", client=None, model="unused", limit=1)  # type: ignore[arg-type]
    assert output.name == "M04_pilot_first_1_suggestions.csv"
    assert len(list(csv.DictReader(output.open()))) == 12


def synthetic_pilot_files(tmp_path: Path, reviewed: int = 128) -> tuple[Path, Path]:
    root = tmp_path
    suggestions = root / "analysis/model_assisted_scoring/preannotations/M05/M05_pilot_first_2_suggestions.csv"
    suggestions.parent.mkdir(parents=True)
    fields = list(ComponentSuggestion.model_fields)
    stream = io.StringIO(newline=""); writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
    rows = []
    for blind in range(1, 3):
        for comp in range(1, 65):
            rows.append({
                "blind_id": f"M05-B{blind:03d}", "component_id": f"M05-T01-C{comp:02d}",
                "suggested_preservation": 0, "exact_evidence_quote": "", "short_reason": "Absent.",
                "confidence": 0.9, "distortion_severity": 0, "distortion_explanation": "",
                "needs_human_review": False,
            })
    writer.writerows(rows); suggestions.write_text(stream.getvalue())
    _, log = resolve_review_paths(root, "M05", suggestions)
    log.parent.mkdir(parents=True)
    with log.open("w") as handle:
        for row in rows[:reviewed]:
            handle.write(json.dumps({
                "blind_id": row["blind_id"], "component_id": row["component_id"],
                "human_reviewed": True, "preservation_score": 0, "distortion_score": 0,
                "flagged": False, "human_note": "", "timestamp_utc": "2026-01-01T00:00:00Z",
                "model_suggested_preservation": 0, "model_distortion_severity": 0,
            }) + "\n")
    full = suggestions.parent / "M05_suggestions.csv"
    full.write_bytes(suggestions.read_bytes())
    return suggestions, log


def test_pilot_review_path_is_isolated(tmp_path: Path) -> None:
    suggestions, log = synthetic_pilot_files(tmp_path)
    assert log.name == "M05_pilot_first_2_review_log.jsonl"
    assert log.name != "M05_review_log.jsonl"


def test_pilot_calibration_and_incomplete_refusal(tmp_path: Path) -> None:
    suggestions, _ = synthetic_pilot_files(tmp_path / "complete")
    summary = json.loads(pilot_calibration(tmp_path / "complete", "M05", suggestions).read_text())
    assert summary["row_count"] == 128
    assert summary["preservation_agreement_rate"] == 1.0
    incomplete, _ = synthetic_pilot_files(tmp_path / "incomplete", reviewed=127)
    with pytest.raises(IntegrityError, match="incomplete"):
        pilot_calibration(tmp_path / "incomplete", "M05", incomplete)


def test_pilot_import_provenance_duplicate_refusal_and_status(tmp_path: Path) -> None:
    synthetic_pilot_files(tmp_path)
    audit = import_pilot_reviews(tmp_path)
    assert audit.exists()
    production = tmp_path / "analysis/model_assisted_scoring/reviews/M05_review_log.jsonl"
    events = [json.loads(line) for line in production.read_text().splitlines()]
    assert len(events) == 128
    assert all(event["provenance"]["source_review_log_sha256"] for event in events)
    status = measure_status(tmp_path, "M05")
    assert status["reviewed_latest_rows"] == 128
    assert status["reviewed_blind_outputs"] == 2
    assert status["unresolved_flags"] == 0
    with pytest.raises(FileExistsError):
        import_pilot_reviews(tmp_path)
