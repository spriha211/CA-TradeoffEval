from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/post_lock_analysis"
OUTCOMES = (
    "claim_weighted_preservation", "component_weighted_preservation",
    "mean_component_distortion_severity", "any_distortion_rate", "material_distortion_rate",
)


def rows(name: str) -> list[dict[str, str]]:
    with (OUT / name).open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_post_unblind_manifest_and_artifact_hashes() -> None:
    manifest = json.loads((OUT / "POST_UNBLIND_ANALYSIS_MANIFEST.json").read_text())
    assert manifest["status"] == "PASS"
    assert all(manifest["integrity_checks"].values())
    for item in manifest["generated_artifacts"]:
        path = ROOT / item["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]


def test_master_and_output_level_aggregation() -> None:
    master = rows("master_analysis_table.csv")
    trial = rows("trial_level_summary.csv")
    assert len(master) == 5_872
    assert len(trial) == 160
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in master:
        grouped[(row["measure_id"], row["blind_id"])].append(row)
    trial_map = {(row["measure_id"], row["blind_id"]): row for row in trial}
    for key, component_rows in grouped.items():
        claims: dict[str, list[int]] = defaultdict(list)
        for row in component_rows:
            claims[row["claim_id"]].append(int(row["preservation_score"]))
        expected_claim = np.mean([np.mean(values) for values in claims.values()])
        expected_component = np.mean([int(row["preservation_score"]) for row in component_rows])
        distortion = np.array([int(row["distortion_score"]) for row in component_rows])
        actual = trial_map[key]
        assert np.isclose(float(actual["claim_weighted_preservation"]), expected_claim)
        assert np.isclose(float(actual["component_weighted_preservation"]), expected_component)
        assert np.isclose(float(actual["mean_component_distortion_severity"]), distortion.mean())
        assert np.isclose(float(actual["any_distortion_rate"]), (distortion > 0).mean())
        assert np.isclose(float(actual["material_distortion_rate"]), (distortion == 2).mean())


def test_pairing_bootstrap_and_lomo_reproducibility() -> None:
    paired = rows("paired_contrasts.csv")
    aggregate = rows("aggregate_contrasts.csv")
    lomo = rows("leave_one_measure_out.csv")
    assert len(paired) == 30 and len(aggregate) == 15 and len(lomo) == 150
    rng = np.random.default_rng(20_260_809)
    samples = rng.integers(0, 10, size=(10_000, 10))
    for aggregate_row in aggregate:
        contrast, outcome = aggregate_row["contrast"], aggregate_row["outcome"]
        values = np.array([
            float(row[f"{outcome}_difference"]) for row in paired if row["contrast"] == contrast
        ])
        bootstrap = values[samples].mean(axis=1)
        assert np.isclose(float(aggregate_row["mean_paired_difference"]), values.mean())
        assert np.allclose(
            [float(aggregate_row["bootstrap_ci_95_low"]), float(aggregate_row["bootstrap_ci_95_high"])],
            np.percentile(bootstrap, [2.5, 97.5]),
        )
        lomo_rows = [row for row in lomo if row["contrast"] == contrast and row["outcome"] == outcome]
        expected_lomo = [np.delete(values, index).mean() for index in range(10)]
        assert np.allclose([float(row["leave_one_out_mean_difference"]) for row in lomo_rows], expected_lomo)
