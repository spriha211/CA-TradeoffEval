from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .generate import MEASURES, PROTOCOL_SHA256, ROOT, RUN_ROOT, atomic_json, atomic_text, sha256_file, verify_protocol


def blind_measure(measure: str) -> Path:
    verify_protocol()
    if measure not in MEASURES:
        raise ValueError("Measure is outside frozen Study 2 selection")
    blinded_dir = RUN_ROOT / "blinded" / measure
    mapping_path = RUN_ROOT / "sealed_private_mappings" / f"{measure}_blind_mapping_private.json"
    commitment_path = RUN_ROOT / "audits" / f"{measure}_blind_mapping_commitment.json"
    manifest_path = RUN_ROOT / "audits" / f"{measure}_blinded_manifest.json"
    protected = [mapping_path, commitment_path, manifest_path]
    protected.extend(blinded_dir.glob(f"{measure}-B*.txt") if blinded_dir.exists() else [])
    if any(path.exists() for path in protected):
        raise FileExistsError(f"Study 2 blinded packet already exists for {measure}; refusing overwrite")
    items = []
    for trial in range(1, 5):
        complete = RUN_ROOT / "generation" / measure / f"trial{trial:02d}" / "complete.json"
        data = json.loads(complete.read_text(encoding="utf-8"))
        if data["development_smoke"] or data["measure_id"] != measure or data["trial_number"] != trial:
            raise RuntimeError(f"Invalid production generation record: {complete}")
        for condition, text in data["final_outputs"].items():
            items.append({"trial_number": trial, "condition": condition, "text": text, "source_path": str(complete.relative_to(ROOT)), "source_sha256": sha256_file(complete)})
    if len(items) != 16:
        raise RuntimeError(f"Expected 16 outputs for {measure}; found {len(items)}")
    seed = secrets.randbits(256)
    random.Random(seed).shuffle(items)
    mapping = []
    for index, item in enumerate(items, 1):
        blind_id = f"{measure}-C{index:03d}"
        path = blinded_dir / f"{blind_id}.txt"
        atomic_text(path, item["text"])
        mapping.append({
            "blind_id": blind_id, "trial_number": item["trial_number"], "condition": item["condition"],
            "blinded_path": str(path.relative_to(ROOT)), "blinded_sha256": sha256_file(path),
            "source_generation_path": item["source_path"], "source_generation_sha256": item["source_sha256"],
        })
    atomic_json(mapping_path, {
        "schema_version": "1.0", "study": "Study 2", "measure_id": measure,
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "private_shuffle_seed": str(seed), "entries": mapping,
    })
    os.chmod(mapping_path, 0o600)
    atomic_json(commitment_path, {
        "schema_version": "1.0", "measure_id": measure,
        "mapping_path": str(mapping_path.relative_to(ROOT)), "mapping_sha256": sha256_file(mapping_path),
        "entry_count": 16, "protocol_sha256": PROTOCOL_SHA256,
    })
    atomic_json(manifest_path, {
        "schema_version": "1.0", "measure_id": measure, "blind_output_count": 16,
        "outputs": [{"blind_id": row["blind_id"], "path": row["blinded_path"], "sha256": row["blinded_sha256"]} for row in mapping],
        "mapping_commitment_path": str(commitment_path.relative_to(ROOT)),
    })
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--measure", choices=MEASURES)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if args.all == bool(args.measure):
        raise SystemExit("Choose exactly one of --all or --measure")
    for measure in MEASURES if args.all else [args.measure]:
        print(blind_measure(measure))


if __name__ == "__main__":
    main()
