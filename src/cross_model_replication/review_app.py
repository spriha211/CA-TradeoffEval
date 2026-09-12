from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from src.cross_model_replication.generate import MEASURES, ROOT
from src.cross_model_replication.scoring import ANALYSIS_ROOT

DEFAULT_ORDER = ["M09", "M08", "M03", "M05", "M02"]


def append_event(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()


def latest_reviews(path: Path) -> dict[tuple[str, str], dict]:
    latest = {}
    if not path.exists():
        return latest
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        event = json.loads(line)
        if not {"blind_id", "component_id"}.issubset(event):
            raise RuntimeError(f"Malformed review event line {number}")
        latest[(event["blind_id"], event["component_id"])] = event
    return latest


def load_measure(measure: str):
    suggestion_path = ANALYSIS_ROOT / "preannotations" / measure / f"{measure}_suggestions.csv"
    with suggestion_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    manifest = json.loads((ANALYSIS_ROOT / "jobs" / measure / "manifest.json").read_text(encoding="utf-8"))
    jobs = {record["blind_id"]: json.loads((ROOT / record["path"]).read_text(encoding="utf-8")) for record in manifest["jobs"]}
    return rows, jobs


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--measures", default=",".join(DEFAULT_ORDER))
    args, _ = parser.parse_known_args()
    order = [value.strip().upper() for value in args.measures.split(",")]
    if len(order) != len(set(order)) or not order or any(value not in MEASURES for value in order):
        raise RuntimeError("--measures must be a unique ordered subset of frozen Study 2 measures")
    st.set_page_config(page_title="Study 2 blinded review", layout="wide")
    st.title("Study 2 blinded Claude-output review")
    st.caption("Condition-blind. Saves append events only; Study 1 review artifacts are never used.")
    loaded = {}
    unreviewed_answers = []
    flagged_answers = []
    all_answers = []
    remaining_unreviewed = 0
    unresolved_flags = 0
    unavailable = []
    for measure in order:
        suggestion_path = ANALYSIS_ROOT / "preannotations" / measure / f"{measure}_suggestions.csv"
        if not suggestion_path.exists():
            unavailable.append(measure)
            continue
        rows, jobs = load_measure(measure)
        log = ANALYSIS_ROOT / "reviews" / f"{measure}_review_log.jsonl"
        latest = latest_reviews(log)
        loaded[measure] = (rows, jobs, log, latest)
        blind_order = list(dict.fromkeys(row["blind_id"] for row in rows))
        remaining_unreviewed += sum(
            (row["blind_id"], row["component_id"]) not in latest for row in rows
        )
        unresolved_flags += sum(
            latest.get((row["blind_id"], row["component_id"]), {}).get("flagged") is True
            for row in rows
        )
        for blind_id in blind_order:
            answer_rows = [row for row in rows if row["blind_id"] == blind_id]
            all_answers.append((measure, blind_id))
            if any((blind_id, row["component_id"]) not in latest for row in answer_rows):
                unreviewed_answers.append((measure, blind_id))
            if any(latest.get((blind_id, row["component_id"]), {}).get("flagged") is True for row in answer_rows):
                flagged_answers.append((measure, blind_id))

    st.metric("Unresolved flagged component rows", unresolved_flags)
    if unavailable:
        st.warning(f"Suggestions are unavailable for: {', '.join(unavailable)}")
    if remaining_unreviewed == 0 and unresolved_flags == 0 and not unavailable:
        st.success("All Study 2 rows reviewed and no unresolved flags remain.")
        return
    if remaining_unreviewed == 0 and unresolved_flags == 0:
        st.info("All available rows are reviewed with no unresolved flags; unavailable measures remain.")
        return

    queue_mode = st.sidebar.radio("Review queue", ["Unreviewed", "Flagged", "All"])
    if queue_mode == "Unreviewed" and not unreviewed_answers and flagged_answers:
        st.info("All rows are reviewed, but unresolved flags remain. Showing the Flagged queue.")
        queue_mode = "Flagged"
    queue = {"Unreviewed": unreviewed_answers, "Flagged": flagged_answers, "All": all_answers}[queue_mode]
    if not queue:
        st.info(f"The {queue_mode} queue is empty.")
        return
    selected_measure, blind_id = st.sidebar.selectbox(
        "Blinded answer", queue, format_func=lambda item: f"{item[0]} · {item[1]}"
    )
    rows, jobs, log, latest = loaded[selected_measure]
    job = jobs[blind_id]
    suggestions = [row for row in rows if row["blind_id"] == blind_id]
    component_map = {row["component_id"]: row for row in job["components"]}
    reviewed = sum((row["blind_id"], row["component_id"]) in latest for row in rows)
    st.subheader(f"{selected_measure} · {blind_id}")
    st.progress(reviewed / len(rows))
    st.write(f"{reviewed}/{len(rows)} component rows reviewed for {selected_measure}")
    st.text_area("Full blinded answer", job["blinded_answer"], height=360, disabled=True)
    table = []
    for row in suggestions:
        prior = latest.get((blind_id, row["component_id"]), {})
        component = component_map[row["component_id"]]
        table.append({
            "component_id": row["component_id"], "component": component["component_text"],
            "scoring_rule": component["binary_scoring_rule"], "model_suggestion": int(row["suggested_preservation"]),
            "exact_evidence": row["exact_evidence_quote"], "reason": row["short_reason"], "confidence": float(row["confidence"]),
            "model_distortion": int(row["distortion_severity"]),
            "preservation": int(prior.get("preservation_score", row["suggested_preservation"])),
            "distortion": int(prior.get("distortion_score", row["distortion_severity"])),
            "flag": bool(prior.get("flagged", row["needs_human_review"].lower() == "true")),
            "human_note": prior.get("human_note", ""),
        })
    with st.form("bulk_review"):
        edited = st.data_editor(table, hide_index=True, use_container_width=True, height=min(760, 80 + 35 * len(table)),
            disabled=["component_id", "component", "scoring_rule", "model_suggestion", "exact_evidence", "reason", "confidence", "model_distortion"],
            column_config={
                "preservation": st.column_config.SelectboxColumn(options=[0, 1], required=True),
                "distortion": st.column_config.SelectboxColumn(options=[0, 1, 2], required=True),
                "flag": st.column_config.CheckboxColumn(), "human_note": st.column_config.TextColumn(),
            })
        save = st.form_submit_button("Bulk-save this blinded answer", type="primary", use_container_width=True)
        if save:
            edited_rows = edited.to_dict("records") if hasattr(edited, "to_dict") else edited
            if any(int(row["distortion"]) == 2 and int(row["preservation"]) != 0 for row in edited_rows):
                st.error("Distortion 2 requires preservation 0. Nothing was saved.")
            elif any(int(row["preservation"]) not in (0, 1) or int(row["distortion"]) not in (0, 1, 2) for row in edited_rows):
                st.error("Invalid scoring value. Nothing was saved.")
            else:
                timestamp = datetime.now(timezone.utc).isoformat()
                suggestions_by_id = {row["component_id"]: row for row in suggestions}
                for row in edited_rows:
                    suggestion = suggestions_by_id[row["component_id"]]
                    append_event(log, {"schema_version": "1.0", "study": "Study 2", "timestamp_utc": timestamp,
                        "measure_id": selected_measure, "blind_id": blind_id, "component_id": row["component_id"],
                        "human_reviewed": True, "preservation_score": int(row["preservation"]), "distortion_score": int(row["distortion"]),
                        "flagged": bool(row["flag"]), "human_note": str(row["human_note"] or ""),
                        "model_suggested_preservation": int(suggestion["suggested_preservation"]),
                        "model_distortion_severity": int(suggestion["distortion_severity"])})
                st.rerun()


if __name__ == "__main__":
    main()
