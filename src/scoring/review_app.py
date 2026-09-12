from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from src.scoring.integrity import append_jsonl, read_text, validate_measure

ROOT = Path(__file__).resolve().parents[2]


def load_rows(root: Path, measure: str, path: Path | None = None) -> list[dict[str, str]]:
    path = path or root / f"analysis/model_assisted_scoring/preannotations/{measure}/{measure}_suggestions.csv"
    return list(csv.DictReader(read_text(root, path).splitlines()))


def resolve_review_paths(
    root: Path, measure: str, suggestions_file: Path | None
) -> tuple[Path, Path]:
    if suggestions_file is None:
        suggestions_path = root / f"analysis/model_assisted_scoring/preannotations/{measure}/{measure}_suggestions.csv"
        log_path = root / f"analysis/model_assisted_scoring/reviews/{measure}_review_log.jsonl"
        return suggestions_path, log_path
    suggestions_path = suggestions_file if suggestions_file.is_absolute() else root / suggestions_file
    expected_parent = (root / f"analysis/model_assisted_scoring/preannotations/{measure}").resolve()
    if suggestions_path.resolve().parent != expected_parent:
        raise RuntimeError("Pilot suggestions file must be in the measure's preannotations directory")
    pattern = rf"{re.escape(measure)}_(pilot_[A-Za-z0-9_-]+)_suggestions\.csv"
    match = re.fullmatch(pattern, suggestions_path.name)
    if not match:
        raise RuntimeError("Pilot suggestions filename is invalid or does not match the measure")
    log_path = root / "analysis/model_assisted_scoring/reviews" / f"{measure}_{match.group(1)}_review_log.jsonl"
    return suggestions_path, log_path


def load_jobs(root: Path, measure: str) -> dict[str, dict]:
    manifest_path = root / f"analysis/model_assisted_scoring/jobs/{measure}/manifest.json"
    manifest = json.loads(read_text(root, manifest_path))
    return {
        job["blind_id"]: json.loads(read_text(root, root / job["path"]))
        for job in manifest["jobs"]
    }


def load_reviews(root: Path, path: Path) -> dict[tuple[str, str], dict]:
    if not path.exists():
        return {}
    latest: dict[tuple[str, str], dict] = {}
    for number, line in enumerate(read_text(root, path).splitlines(), start=1):
        try:
            event = json.loads(line)
            latest[(event["blind_id"], event["component_id"])] = event
        except (json.JSONDecodeError, KeyError) as exc:
            raise RuntimeError(f"Malformed review log line {number}") from exc
    return latest


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--measure", default="M04")
    parser.add_argument("--suggestions-file", type=Path)
    args, _ = parser.parse_known_args()
    measure = validate_measure(args.measure)
    root = ROOT
    suggestions_path, log_path = resolve_review_paths(root, measure, args.suggestions_file)
    rows, jobs = load_rows(root, measure, suggestions_path), load_jobs(root, measure)
    if not rows or any(row["blind_id"].split("-", 1)[0] != measure for row in rows):
        raise RuntimeError("Suggestions rows are empty or do not match the requested measure")
    latest = load_reviews(root, log_path)
    blind_order = list(dict.fromkeys(row["blind_id"] for row in rows))
    pending_blinds = [
        blind_id for blind_id in blind_order
        if any(
            (row["blind_id"], row["component_id"]) not in latest
            for row in rows if row["blind_id"] == blind_id
        )
    ]
    flagged_blinds = [
        blind_id for blind_id in blind_order
        if any(
            latest.get((row["blind_id"], row["component_id"]), {}).get("flagged") is True
            for row in rows if row["blind_id"] == blind_id
        )
    ]
    reviewed_count = len(rows) - sum(
        (row["blind_id"], row["component_id"]) not in latest for row in rows
    )

    st.set_page_config(page_title=f"{measure} blinded review", layout="wide")
    st.title(f"{measure} blinded component review")
    st.caption("Condition-blind review. Every save appends a new immutable log event.")
    if args.suggestions_file is not None:
        st.caption(f"Pilot file: {suggestions_path.name} · isolated log: {log_path.name}")
    st.progress(reviewed_count / len(rows))
    st.write(f"Reviewed {reviewed_count} of {len(rows)} component rows")
    queue_name = st.sidebar.radio("Review queue", ["Unreviewed", "Flagged", "All"])
    queue = (
        pending_blinds if queue_name == "Unreviewed"
        else flagged_blinds if queue_name == "Flagged"
        else blind_order
    )
    if not queue and queue_name == "Flagged":
        st.info("There are no currently flagged rows.")
        return
    if not queue:
        st.success("All component rows have been reviewed. You can now run the locking command.")
        return

    blind_id = queue[0]
    job = jobs[blind_id]
    suggestion_rows = [row for row in rows if row["blind_id"] == blind_id]
    component_map = {row["component_id"]: row for row in job["components"]}
    st.subheader(blind_id)
    st.markdown("**Full blinded answer**")
    st.text_area("Answer", job["blinded_answer"], height=360, disabled=True, label_visibility="collapsed")

    table_rows = []
    for row in suggestion_rows:
        prior = latest.get((blind_id, row["component_id"]), {})
        component = component_map[row["component_id"]]
        table_rows.append({
            "component_id": row["component_id"],
            "component": component["component_text"],
            "scoring_rule": component["binary_scoring_rule"],
            "model_preservation": int(row["suggested_preservation"]),
            "evidence": row["exact_evidence_quote"],
            "model_reason": row["short_reason"],
            "confidence": float(row["confidence"]),
            "model_distortion": int(row["distortion_severity"]),
            "human_preservation": int(prior.get("preservation_score", row["suggested_preservation"])),
            "human_distortion": int(prior.get("distortion_score", row["distortion_severity"])),
            "flagged": bool(prior.get("flagged", row["needs_human_review"].lower() == "true")),
            "human_note": prior.get("human_note", ""),
        })

    with st.form("answer_review"):
        edited = st.data_editor(
            table_rows,
            key=f"table_{blind_id}_{queue_name}",
            hide_index=True,
            use_container_width=True,
            disabled=[
                "component_id", "component", "scoring_rule", "model_preservation", "evidence",
                "model_reason", "confidence", "model_distortion",
            ],
            column_config={
                "human_preservation": st.column_config.SelectboxColumn(options=[0, 1], required=True),
                "human_distortion": st.column_config.SelectboxColumn(options=[0, 1, 2], required=True),
                "flagged": st.column_config.CheckboxColumn(),
                "human_note": st.column_config.TextColumn(),
            },
            height=min(700, 80 + 35 * len(table_rows)),
        )
        submitted = st.form_submit_button(
            "Accept / bulk-save this blinded answer", type="primary", use_container_width=True
        )
        if submitted:
            edited_rows = edited.to_dict("records") if hasattr(edited, "to_dict") else edited
            invalid = [
                row for row in edited_rows
                if int(row["human_distortion"]) == 2 and int(row["human_preservation"]) != 0
            ]
            if invalid:
                st.error("Material distortion (2) requires preservation 0. No rows were saved.")
            else:
                timestamp = datetime.now(timezone.utc).isoformat()
                suggestion_map = {row["component_id"]: row for row in suggestion_rows}
                for edited_row in edited_rows:
                    suggestion = suggestion_map[edited_row["component_id"]]
                    append_jsonl(root, log_path, {
                        "schema_version": "1.0", "timestamp_utc": timestamp,
                        "measure_id": measure, "blind_id": blind_id,
                        "component_id": edited_row["component_id"], "human_reviewed": True,
                        "preservation_score": int(edited_row["human_preservation"]),
                        "distortion_score": int(edited_row["human_distortion"]),
                        "flagged": bool(edited_row["flagged"]),
                        "human_note": str(edited_row["human_note"] or ""),
                        "model_suggested_preservation": int(suggestion["suggested_preservation"]),
                        "model_distortion_severity": int(suggestion["distortion_severity"]),
                    })
                st.rerun()


if __name__ == "__main__":
    main()
