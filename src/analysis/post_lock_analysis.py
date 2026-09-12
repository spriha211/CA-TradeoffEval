from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
MEASURES = tuple(f"M{i:02d}" for i in range(2, 12))
EXPECTED_COMPONENTS = {
    "M02": 65, "M03": 58, "M04": 12, "M05": 64, "M06": 29,
    "M07": 22, "M08": 28, "M09": 25, "M10": 31, "M11": 33,
}
CONDITIONS = (
    "single_agent", "independent_ensemble", "normal_debate", "critic_debate",
)
CONDITION_LABELS = {
    "single_agent": "Single agent",
    "independent_ensemble": "Independent ensemble",
    "normal_debate": "Normal debate",
    "critic_debate": "Critic debate",
}
CONDITION_KEYS = {
    "setup1_single": "single_agent",
    "setup2_independent": "independent_ensemble",
    "setup3_debate": "normal_debate",
    "setup4_critic": "critic_debate",
}
CONTRASTS = (
    ("independent_ensemble_minus_single_agent", "independent_ensemble", "single_agent"),
    ("normal_debate_minus_independent_ensemble", "normal_debate", "independent_ensemble"),
    ("critic_debate_minus_normal_debate", "critic_debate", "normal_debate"),
)
CONTRAST_LABELS = {
    "independent_ensemble_minus_single_agent": "Independent − single",
    "normal_debate_minus_independent_ensemble": "Normal debate − independent",
    "critic_debate_minus_normal_debate": "Critic debate − normal debate",
}
OUTCOMES = (
    "claim_weighted_preservation",
    "component_weighted_preservation",
    "mean_component_distortion_severity",
    "any_distortion_rate",
    "material_distortion_rate",
)
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20_260_809
PRE_MANIFEST_REL = "runs/audits/model_assisted_scoring/PRE_UNBLIND_INTEGRITY_MANIFEST.json"
PRE_MANIFEST_HASH = "4d98147e160b2e1f05f55dd7a346c79b18e8e972f9e4ed18112e3c19990e74d5"
AMENDMENT_REL = "runs/audits/model_assisted_scoring/PRE_UNBLIND_ANALYSIS_AMENDMENT.json"
OUTPUT_REL = "results/post_lock_analysis"


class AnalysisError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        if not rows:
            raise AnalysisError(f"Cannot infer columns for empty table: {path}")
        fields = list(rows[0])
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def write_text(path: Path, text: str) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def git_info(root: Path) -> dict:
    def run(*args: str) -> str:
        return subprocess.run(args, cwd=root, text=True, capture_output=True, check=True).stdout.strip()
    return {
        "commit": run("git", "rev-parse", "HEAD"),
        "worktree_status": run("git", "status", "--short"),
    }


def validate_pre_gate(root: Path) -> dict:
    path = root / PRE_MANIFEST_REL
    if sha256(path) != PRE_MANIFEST_HASH:
        raise AnalysisError("Authoritative pre-unblind manifest hash mismatch")
    value = json.loads(path.read_text())
    summary = value["summary"]
    if not (
        summary["status"] == "PASS" and summary["locked_measures"] == 10
        and summary["total_locked_rows"] == 5_872 and summary["unresolved_flags"] == 0
    ):
        raise AnalysisError("Authoritative pre-unblind manifest requirements failed")
    for row in value["measures"]:
        locked, manifest = root / row["locked_csv_path"], root / row["scoring_lock_manifest_path"]
        if sha256(locked) != row["locked_csv_sha256"] or sha256(manifest) != row["scoring_lock_manifest_sha256"]:
            raise AnalysisError(f"Locked input changed after pre-unblind audit: {row['measure_id']}")
    return value


def load_inputs(root: Path) -> tuple[list[dict], dict, list[dict], dict]:
    pre = validate_pre_gate(root)
    amendment_path = root / AMENDMENT_REL
    amendment = json.loads(amendment_path.read_text())
    if amendment["bootstrap"]["random_seed"] != BOOTSTRAP_SEED:
        raise AnalysisError("Bootstrap seed disagrees with pre-unblind amendment")

    master: list[dict] = []
    mapping_records: list[dict] = []
    input_hashes: dict[str, str] = {
        PRE_MANIFEST_REL: sha256(root / PRE_MANIFEST_REL),
        AMENDMENT_REL: sha256(amendment_path),
        "data/reference_inventories/SCORING_GUIDE.md": sha256(root / "data/reference_inventories/SCORING_GUIDE.md"),
    }
    for measure in MEASURES:
        mapping_path = root / f"runs/scored/private_mappings/{measure}_blind_mapping_private.json"
        mapping_data = json.loads(mapping_path.read_text())
        input_hashes[str(mapping_path.relative_to(root))] = sha256(mapping_path)
        mapping = {}
        for entry in mapping_data["mapping"]:
            blind_id = entry["blind_id"]
            condition = CONDITION_KEYS.get(entry["condition_key"])
            trial_number = int(entry["trial_number"])
            if condition is None or not 1 <= trial_number <= 4:
                raise AnalysisError(f"Invalid sealed mapping entry for {blind_id}")
            minimal = {
                "measure_id": measure, "blind_id": blind_id,
                "trial_number": trial_number, "trial_id": f"{measure}-trial{trial_number:02d}",
                "condition": condition,
            }
            mapping[blind_id] = minimal; mapping_records.append(minimal)
        if len(mapping) != 16 or len({(x["trial_number"], x["condition"]) for x in mapping.values()}) != 16:
            raise AnalysisError(f"Mapping balance failed for {measure}")

        locked_path = root / f"results/locked_scoring/{measure}/{measure}_locked_scoring.csv"
        lock_manifest_path = root / f"results/locked_scoring/{measure}/{measure}_scoring_lock_manifest.json"
        component_path = root / f"data/reference_inventories/{measure}_components.csv"
        for path in (locked_path, lock_manifest_path, component_path):
            input_hashes[str(path.relative_to(root))] = sha256(path)
        locked = read_csv(locked_path); components = read_csv(component_path)
        component_map = {row["component_id"]: row for row in components}
        if len(component_map) != EXPECTED_COMPONENTS[measure]:
            raise AnalysisError(f"Component count failed for {measure}")
        if len(locked) != 16 * EXPECTED_COMPONENTS[measure]:
            raise AnalysisError(f"Locked row count failed for {measure}")
        seen = set()
        for row in locked:
            key = (row["blind_id"], row["component_id"])
            if key in seen or row["blind_id"] not in mapping or row["component_id"] not in component_map:
                raise AnalysisError(f"Invalid locked join key: {measure} {key}")
            seen.add(key); identity = mapping[row["blind_id"]]; component = component_map[row["component_id"]]
            master.append({
                **identity,
                "blind_id": row["blind_id"],
                "condition_label": CONDITION_LABELS[identity["condition"]],
                "claim_id": component["claim_id"], "component_id": row["component_id"],
                "category": component.get("category", ""),
                "preservation_score": int(row["preservation_score"]),
                "distortion_score": int(row["distortion_score"]),
            })
    if len(master) != 5_872 or len({(r["measure_id"], r["blind_id"], r["component_id"]) for r in master}) != 5_872:
        raise AnalysisError("Master analysis row integrity failed")
    return master, input_hashes, mapping_records, amendment


def output_metrics(master: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in master:
        grouped[(row["measure_id"], row["blind_id"])].append(row)
    results = []
    for key, rows in sorted(grouped.items()):
        claims: dict[str, list[int]] = defaultdict(list)
        for row in rows: claims[row["claim_id"]].append(row["preservation_score"])
        first = rows[0]; distortions = np.array([r["distortion_score"] for r in rows], dtype=float)
        preservation = np.array([r["preservation_score"] for r in rows], dtype=float)
        results.append({
            "measure_id": first["measure_id"], "trial_id": first["trial_id"],
            "trial_number": first["trial_number"], "blind_id": first["blind_id"],
            "condition": first["condition"], "condition_label": first["condition_label"],
            "claim_weighted_preservation": float(np.mean([np.mean(v) for v in claims.values()])),
            "component_weighted_preservation": float(preservation.mean()),
            "mean_component_distortion_severity": float(distortions.mean()),
            "any_distortion_rate": float((distortions > 0).mean()),
            "material_distortion_rate": float((distortions == 2).mean()),
            "n_claims": len(claims), "n_components": len(rows),
        })
    if len(results) != 160:
        raise AnalysisError(f"Expected 160 output summaries; found {len(results)}")
    for measure in MEASURES:
        rows = [r for r in results if r["measure_id"] == measure]
        if len(rows) != 16 or {r["condition"] for r in rows} != set(CONDITIONS):
            raise AnalysisError(f"Output balance failed for {measure}")
        for condition in CONDITIONS:
            if {r["trial_number"] for r in rows if r["condition"] == condition} != {1, 2, 3, 4}:
                raise AnalysisError(f"Trial balance failed for {measure} {condition}")
    return results


def summarize(output_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in output_rows: groups[(row["measure_id"], row["condition"])].append(row)
    measure_condition = []
    for (measure, condition), rows in sorted(groups.items()):
        result = {
            "measure_id": measure, "condition": condition,
            "condition_label": CONDITION_LABELS[condition], "n_trials": len(rows),
            "n_components_per_output": rows[0]["n_components"], "n_claims_per_output": rows[0]["n_claims"],
        }
        for outcome in OUTCOMES:
            values = np.array([r[outcome] for r in rows])
            result[outcome] = float(values.mean())
            result[f"{outcome}_sd_across_trials"] = float(values.std(ddof=1))
        measure_condition.append(result)
    condition_summary = []
    for condition in CONDITIONS:
        rows = [r for r in measure_condition if r["condition"] == condition]
        result = {
            "condition": condition, "condition_label": CONDITION_LABELS[condition],
            "n_measures": len(rows), "n_outputs": sum(r["n_trials"] for r in rows),
        }
        for outcome in OUTCOMES:
            values = np.array([r[outcome] for r in rows])
            result[outcome] = float(values.mean())
            result[f"{outcome}_sd_across_measures"] = float(values.std(ddof=1))
        condition_summary.append(result)
    return measure_condition, condition_summary


def contrasts(measure_condition: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    lookup = {(r["measure_id"], r["condition"]): r for r in measure_condition}
    measure_rows = []
    for measure in MEASURES:
        for contrast, upper, lower in CONTRASTS:
            row = {"measure_id": measure, "contrast": contrast, "contrast_label": CONTRAST_LABELS[contrast], "n_trials_per_condition": 4}
            for outcome in OUTCOMES:
                row[f"{outcome}_difference"] = lookup[(measure, upper)][outcome] - lookup[(measure, lower)][outcome]
            measure_rows.append(row)

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    samples = rng.integers(0, len(MEASURES), size=(BOOTSTRAP_REPLICATES, len(MEASURES)))
    aggregate = []
    lomo = []
    for contrast, _, _ in CONTRASTS:
        rows = [r for r in measure_rows if r["contrast"] == contrast]
        for outcome in OUTCOMES:
            field = f"{outcome}_difference"; values = np.array([r[field] for r in rows], dtype=float)
            boot = values[samples].mean(axis=1); estimate = float(values.mean())
            ci_low, ci_high = np.percentile(boot, [2.5, 97.5])
            lomo_values = np.array([np.delete(values, i).mean() for i in range(10)])
            full_sign = int(np.sign(estimate))
            direction_change = bool(any(int(np.sign(v)) != full_sign for v in lomo_values))
            aggregate.append({
                "contrast": contrast, "contrast_label": CONTRAST_LABELS[contrast],
                "outcome": outcome, "mean_paired_difference": estimate,
                "sd_across_measure_differences": float(values.std(ddof=1)),
                "bootstrap_ci_95_low": float(ci_low), "bootstrap_ci_95_high": float(ci_high),
                "n_measures": 10, "bootstrap_replicates": BOOTSTRAP_REPLICATES,
                "bootstrap_seed": BOOTSTRAP_SEED,
                "positive_measure_differences": int((values > 0).sum()),
                "negative_measure_differences": int((values < 0).sum()),
                "zero_measure_differences": int((values == 0).sum()),
            })
            for index, omitted in enumerate(MEASURES):
                lomo.append({
                    "contrast": contrast, "contrast_label": CONTRAST_LABELS[contrast],
                    "outcome": outcome, "omitted_measure_id": omitted,
                    "leave_one_out_mean_difference": float(lomo_values[index]),
                    "full_sample_mean_difference": estimate,
                    "lomo_minimum": float(lomo_values.min()), "lomo_maximum": float(lomo_values.max()),
                    "direction_changes_in_any_omission": direction_change,
                    "n_measures_after_omission": 9,
                })
    return measure_rows, aggregate, lomo


def set_plot_style() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 9, "axes.titlesize": 10,
        "axes.labelsize": 9, "legend.fontsize": 8, "figure.dpi": 160,
        "savefig.dpi": 300, "axes.spines.top": False, "axes.spines.right": False,
    })


def save_figure(fig: plt.Figure, base: Path) -> list[Path]:
    paths = []
    for suffix in ("svg", "pdf", "png"):
        path = base.with_suffix(f".{suffix}")
        if path.exists(): raise FileExistsError(f"Refusing to overwrite: {path}")
        fig.savefig(path, bbox_inches="tight", facecolor="white")
        paths.append(path)
    plt.close(fig); return paths


def preservation_figure(measure_condition: list[dict], outcome: str, title: str, base: Path) -> list[Path]:
    set_plot_style(); fig, ax = plt.subplots(figsize=(7.2, 4.5)); x = np.arange(4)
    lookup = {(r["measure_id"], r["condition"]): r for r in measure_condition}
    for measure in MEASURES:
        values = [lookup[(measure, c)][outcome] for c in CONDITIONS]
        ax.plot(x, values, color="#8a99a8", alpha=.55, linewidth=.9, marker="o", markersize=3)
    means = [np.mean([lookup[(m, c)][outcome] for m in MEASURES]) for c in CONDITIONS]
    ax.plot(x, means, color="#1261a0", linewidth=2.5, marker="o", markersize=6, label="Mean across measures")
    ax.set_xticks(x, [CONDITION_LABELS[c] for c in CONDITIONS]); ax.set_ylim(0, 1)
    ax.set_ylabel("Preservation rate"); ax.set_title(title); ax.grid(axis="y", alpha=.25)
    ax.legend(frameon=False, loc="lower right"); fig.tight_layout(); return save_figure(fig, base)


def contrast_figure(measure_contrasts: list[dict], aggregate: list[dict], base: Path) -> list[Path]:
    set_plot_style(); fig, ax = plt.subplots(figsize=(7.2, 4.5)); outcome = "claim_weighted_preservation"
    for idx, (contrast, _, _) in enumerate(CONTRASTS):
        values = [r[f"{outcome}_difference"] for r in measure_contrasts if r["contrast"] == contrast]
        jitter = np.linspace(-.12, .12, len(values))
        ax.scatter(np.full(len(values), idx) + jitter, values, s=22, color="#687b8c", alpha=.75, zorder=2)
        agg = next(r for r in aggregate if r["contrast"] == contrast and r["outcome"] == outcome)
        estimate = agg["mean_paired_difference"]
        ax.errorbar(idx, estimate, yerr=[[estimate-agg["bootstrap_ci_95_low"]], [agg["bootstrap_ci_95_high"]-estimate]],
                    fmt="D", color="#b23a48", markersize=7, capsize=5, linewidth=2.2, zorder=3)
    ax.axhline(0, color="#333333", linewidth=.8); ax.set_xticks(range(3), [CONTRAST_LABELS[c[0]] for c in CONTRASTS])
    ax.set_ylabel("Paired difference in claim-weighted preservation")
    ax.set_title("Planned paired contrasts across measures")
    ax.grid(axis="y", alpha=.25); fig.tight_layout(); return save_figure(fig, base)


def distortion_figure(measure_condition: list[dict], base: Path) -> list[Path]:
    set_plot_style(); fig, axes = plt.subplots(1, 3, figsize=(10.2, 3.8))
    specs = (
        ("mean_component_distortion_severity", "Mean severity", (0, 2)),
        ("any_distortion_rate", "Any-distortion rate", (0, 1)),
        ("material_distortion_rate", "Material-distortion rate", (0, 1)),
    )
    for ax, (outcome, title, ylim) in zip(axes, specs):
        values = [[r[outcome] for r in measure_condition if r["condition"] == c] for c in CONDITIONS]
        means = [np.mean(v) for v in values]
        ax.bar(range(4), means, color="#6f93b5", width=.68)
        for idx, vals in enumerate(values):
            ax.scatter(np.full(len(vals), idx) + np.linspace(-.13,.13,len(vals)), vals, s=12, color="#34495e", alpha=.7)
        ax.set_xticks(range(4), ["Single", "Independent", "Normal", "Critic"], rotation=25, ha="right")
        ax.set_ylim(*ylim); ax.set_title(title); ax.grid(axis="y", alpha=.22)
    fig.suptitle("Distortion outcomes by condition", y=1.02, fontsize=11); fig.tight_layout(); return save_figure(fig, base)


def fmt(value: float) -> str:
    return f"{value:.4f}"


def write_summaries(out: Path, condition_summary: list[dict], aggregate: list[dict], lomo: list[dict]) -> list[Path]:
    primary = [r for r in aggregate if r["outcome"] == "claim_weighted_preservation"]
    lines = ["# Results Summary", "", "## Descriptive results", "", "Condition means are averages of the ten measure-level means; each measure-level mean averages four trials.", ""]
    for row in condition_summary:
        lines.append(
            f"- {row['condition_label']}: claim-weighted preservation {fmt(row['claim_weighted_preservation'])}; "
            f"component-weighted preservation {fmt(row['component_weighted_preservation'])}; "
            f"mean distortion severity {fmt(row['mean_component_distortion_severity'])}; "
            f"any-distortion rate {fmt(row['any_distortion_rate'])}; material-distortion rate {fmt(row['material_distortion_rate'])}."
        )
    lines += ["", "## Planned paired contrasts and statistical uncertainty", ""]
    for row in primary:
        lrows = [x for x in lomo if x["contrast"] == row["contrast"] and x["outcome"] == row["outcome"]]
        lines.append(
            f"- {row['contrast_label']}: mean paired difference {fmt(row['mean_paired_difference'])}, "
            f"95% measure-bootstrap CI [{fmt(row['bootstrap_ci_95_low'])}, {fmt(row['bootstrap_ci_95_high'])}]. "
            f"Measure directions: {row['positive_measure_differences']} positive, {row['negative_measure_differences']} negative, "
            f"{row['zero_measure_differences']} zero. LOMO range [{fmt(lrows[0]['lomo_minimum'])}, {fmt(lrows[0]['lomo_maximum'])}]; "
            f"direction changed: {'yes' if lrows[0]['direction_changes_in_any_omission'] else 'no'}."
        )
    lines += ["", "## Distortion findings", "", "All three frozen distortion outcomes are reported separately in the tables and figures; no composite distortion endpoint was constructed.", "", "## Interpretation boundaries", "", "These are paired condition comparisons from a controlled repeated-trial design. Confidence intervals resample the ten measures, which are the inferential units. No component-level independence or p-value testing was used. Unsupported-claim and word-count outcomes were not calculated because no complete frozen locked unsupported-claim input was available.", ""]
    summary_path = out / "RESULTS_SUMMARY.md"; write_text(summary_path, "\n".join(lines))

    table = ["# Paper Results Table", "", "## Condition means", "", "| Condition | Claim-weighted | Component-weighted | Mean distortion | Any distortion | Material distortion |", "|---|---:|---:|---:|---:|---:|"]
    for row in condition_summary:
        table.append(f"| {row['condition_label']} | {fmt(row['claim_weighted_preservation'])} | {fmt(row['component_weighted_preservation'])} | {fmt(row['mean_component_distortion_severity'])} | {fmt(row['any_distortion_rate'])} | {fmt(row['material_distortion_rate'])} |")
    table += ["", "## Primary planned contrasts", "", "| Contrast | Mean difference | 95% bootstrap CI | Measure directions (+/−/0) | LOMO range | Direction change |", "|---|---:|---:|---:|---:|---:|"]
    for row in primary:
        lr = next(x for x in lomo if x["contrast"] == row["contrast"] and x["outcome"] == row["outcome"])
        table.append(f"| {row['contrast_label']} | {fmt(row['mean_paired_difference'])} | [{fmt(row['bootstrap_ci_95_low'])}, {fmt(row['bootstrap_ci_95_high'])}] | {row['positive_measure_differences']}/{row['negative_measure_differences']}/{row['zero_measure_differences']} | [{fmt(lr['lomo_minimum'])}, {fmt(lr['lomo_maximum'])}] | {'Yes' if lr['direction_changes_in_any_omission'] else 'No'} |")
    table += ["", "Means and paired differences use ten measures; each measure-condition mean contains four trials. CIs are 10,000-replicate paired measure-bootstrap percentile intervals.", ""]
    paper_path = out / "PAPER_RESULTS_TABLE.md"; write_text(paper_path, "\n".join(table))
    return [summary_path, paper_path]


def main() -> None:
    parser = argparse.ArgumentParser(description="Frozen post-lock unblinded confirmatory analysis")
    parser.add_argument("--unblind", action="store_true", required=True)
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(); root = args.root.resolve(); out = root / OUTPUT_REL
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite nonempty analysis directory: {out}")
    out.mkdir(parents=True, exist_ok=True); (out / "figures").mkdir(exist_ok=True); (out / "audits").mkdir(exist_ok=True)
    master, input_hashes, mappings, amendment = load_inputs(root)
    analysis_started = datetime.now(timezone.utc).isoformat(); script_path = Path(__file__).resolve()
    versions = {
        "python": platform.python_version(), "numpy": np.__version__,
        "matplotlib": plt.matplotlib.__version__, **git_info(root),
    }
    unblind_path = out / "audits/UNBLINDING_AUDIT_MANIFEST.json"
    unblind = {
        "schema_version": "1.0", "unblinded_at_utc": analysis_started,
        "pre_unblind_manifest": {"path": PRE_MANIFEST_REL, "sha256": input_hashes[PRE_MANIFEST_REL]},
        "pre_unblind_analysis_amendment": {"path": AMENDMENT_REL, "sha256": input_hashes[AMENDMENT_REL]},
        "mapping_files": [
            {"path": f"runs/scored/private_mappings/{m}_blind_mapping_private.json", "sha256": input_hashes[f"runs/scored/private_mappings/{m}_blind_mapping_private.json"]}
            for m in MEASURES
        ],
        "locked_scoring_inputs": [
            {"measure_id": m, "path": f"results/locked_scoring/{m}/{m}_locked_scoring.csv", "sha256": input_hashes[f"results/locked_scoring/{m}/{m}_locked_scoring.csv"]}
            for m in MEASURES
        ],
        "blind_id_condition_trial_mapping": mappings,
        "analysis_code": {"path": str(script_path.relative_to(root)), "sha256": sha256(script_path)},
        "versions": versions,
    }
    write_text(unblind_path, json.dumps(unblind, indent=2, sort_keys=True) + "\n")

    master_path = out / "master_analysis_table.csv"; write_csv(master_path, master)
    trial_rows = output_metrics(master); trial_path = out / "trial_level_summary.csv"; write_csv(trial_path, trial_rows)
    measure_condition, condition_summary = summarize(trial_rows)
    mc_path = out / "measure_condition_summary.csv"; write_csv(mc_path, measure_condition)
    cs_path = out / "condition_summary.csv"; write_csv(cs_path, condition_summary)
    measure_contrasts, aggregate, lomo = contrasts(measure_condition)
    pc_path = out / "paired_contrasts.csv"; write_csv(pc_path, measure_contrasts)
    ac_path = out / "aggregate_contrasts.csv"; write_csv(ac_path, aggregate)
    lomo_path = out / "leave_one_measure_out.csv"; write_csv(lomo_path, lomo)

    figures = []
    figures += preservation_figure(measure_condition, "claim_weighted_preservation", "Claim-weighted preservation across measures", out / "figures/figure1_claim_weighted_preservation")
    figures += contrast_figure(measure_contrasts, aggregate, out / "figures/figure2_planned_paired_contrasts")
    figures += preservation_figure(measure_condition, "component_weighted_preservation", "Component-weighted preservation across measures", out / "figures/figure3_component_weighted_preservation")
    figures += distortion_figure(measure_condition, out / "figures/figure4_distortion_outcomes")
    summaries = write_summaries(out, condition_summary, aggregate, lomo)

    generated = [unblind_path, master_path, trial_path, mc_path, cs_path, pc_path, ac_path, lomo_path, *figures, *summaries]
    checks = {
        "pre_unblind_gate_pass": True, "ten_measures": len({r['measure_id'] for r in master}) == 10,
        "160_outputs": len(trial_rows) == 160, "5872_locked_rows": len(master) == 5_872,
        "four_conditions": {r['condition'] for r in trial_rows} == set(CONDITIONS),
        "four_trials_per_measure_condition": all(r['n_trials'] == 4 for r in measure_condition),
        "thirty_measure_contrasts": len(measure_contrasts) == 30,
        "fifteen_aggregate_contrast_outcomes": len(aggregate) == 15,
        "one_hundred_fifty_lomo_rows": len(lomo) == 150,
        "no_p_values": True,
    }
    if not all(checks.values()): raise AnalysisError(f"Post-analysis checks failed: {checks}")
    manifest_path = out / "POST_UNBLIND_ANALYSIS_MANIFEST.json"
    manifest = {
        "schema_version": "1.0", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS", "input_hashes": input_hashes,
        "analysis_scripts": [{"path": str(script_path.relative_to(root)), "sha256": sha256(script_path)}],
        "generated_artifacts": [{"path": str(p.relative_to(root)), "sha256": sha256(p)} for p in generated],
        "bootstrap": amendment["bootstrap"], "integrity_checks": checks,
        "versions": versions,
        "warnings": ["Unsupported-claim and word-count metrics deferred: no complete frozen locked unsupported-claim input."],
    }
    write_text(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(manifest_path)


if __name__ == "__main__":
    main()
