from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field
from tenacity import retry, stop_after_attempt, wait_exponential

from src.scoring.integrity import EXPECTED_COMPONENTS
from src.scoring.preannotate import PROMPTS
from .generate import MEASURES, ROOT, RUN_ROOT, atomic_json, atomic_text, sha256_file, verify_protocol

ANALYSIS_ROOT = ROOT / "analysis/cross_model_replication/claude_sonnet_5"
PROMPT_PATH = ROOT / "analysis/model_assisted_scoring/prompt_versions/scoring_prompt_v1.1-production.txt"
PROMPT_SHA256 = "32097fee8cf8f7a3bc2e70ba1e3079b275763e9cc966e5d2d13e47981e7919d8"


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    blind_id: str
    component_id: str
    suggested_preservation: int = Field(ge=0, le=1)
    exact_evidence_quote: str
    short_reason: str
    confidence: float = Field(ge=0, le=1)
    distortion_severity: int = Field(ge=0, le=2)
    distortion_explanation: str
    needs_human_review: bool


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    suggestions: list[Suggestion]


def prompt_text() -> str:
    if sha256_file(PROMPT_PATH) != PROMPT_SHA256:
        raise RuntimeError("Frozen Study 1 production scoring prompt hash mismatch")
    text = PROMPT_PATH.read_text(encoding="utf-8").rstrip("\n")
    if text != PROMPTS["v1.1-production"]:
        raise RuntimeError("Prompt file and frozen production prompt implementation differ")
    return text


def build_jobs(measure: str) -> Path:
    verify_protocol()
    if measure not in MEASURES:
        raise ValueError("Measure outside Study 2")
    inventory = ROOT / "data/reference_inventories" / f"{measure}_components.csv"
    guide = ROOT / "data/reference_inventories/SCORING_GUIDE.md"
    components = list(csv.DictReader(inventory.read_text(encoding="utf-8").splitlines()))
    if len(components) != EXPECTED_COMPONENTS[measure]:
        raise RuntimeError("Frozen inventory component count mismatch")
    outputs = sorted((RUN_ROOT / "blinded" / measure).glob(f"{measure}-C*.txt"))
    if len(outputs) != 16:
        raise RuntimeError(f"Expected 16 Study 2 blinded outputs; found {len(outputs)}")
    out_dir = ANALYSIS_ROOT / "jobs" / measure
    records = []
    for output in outputs:
        job = {
            "schema_version": "1.0", "study": "Study 2", "measure_id": measure,
            "blind_id": output.stem, "blinded_answer": output.read_text(encoding="utf-8").strip(),
            "scoring_guide": guide.read_text(encoding="utf-8").strip(),
            "components": [{key: row[key] for key in ("component_id", "claim_id", "component_text", "binary_scoring_rule")} for row in components],
        }
        path = out_dir / f"{output.stem}.json"
        atomic_json(path, job)
        records.append({"blind_id": output.stem, "path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)})
    manifest = out_dir / "manifest.json"
    atomic_json(manifest, {
        "schema_version": "1.0", "study": "Study 2", "measure_id": measure,
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "blind_output_count": 16,
        "component_count": len(components), "expected_rows": 16 * len(components),
        "inventory": {"path": str(inventory.relative_to(ROOT)), "sha256": sha256_file(inventory)},
        "scoring_guide": {"path": str(guide.relative_to(ROOT)), "sha256": sha256_file(guide)},
        "scoring_prompt": {"path": str(PROMPT_PATH.relative_to(ROOT)), "sha256": PROMPT_SHA256},
        "jobs": records,
    })
    return manifest


def validate(batch: Batch, job: dict[str, Any]) -> Batch:
    expected = [row["component_id"] for row in job["components"]]
    found = [row.component_id for row in batch.suggestions]
    if len(found) != len(expected) or len(set(found)) != len(found) or set(found) != set(expected):
        raise RuntimeError("Malformed model response component set")
    answer = job["blinded_answer"]
    corrected = batch.model_copy(deep=True)
    for row in corrected.suggestions:
        if row.blind_id != job["blind_id"]:
            raise RuntimeError("Wrong blind ID in model response")
        if row.exact_evidence_quote and row.exact_evidence_quote not in answer:
            row.exact_evidence_quote = ""
            row.suggested_preservation = 0
            row.needs_human_review = True
        if row.suggested_preservation == 1 and not row.exact_evidence_quote:
            raise RuntimeError("Preservation 1 lacks exact evidence")
        if row.distortion_severity == 2 and row.suggested_preservation != 0:
            raise RuntimeError("Material distortion must have preservation 0")
    return corrected


def preannotate(measure: str, client: OpenAI, model: str) -> Path:
    manifest_path = ANALYSIS_ROOT / "jobs" / measure / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    out = ANALYSIS_ROOT / "preannotations" / measure
    batches = []

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
    def call(job: dict[str, Any]):
        return client.responses.parse(model=model, instructions=prompt_text(), input=json.dumps(job, ensure_ascii=False), text_format=Batch)

    for record in manifest["jobs"]:
        job = json.loads((ROOT / record["path"]).read_text(encoding="utf-8"))
        parsed_path = out / "parsed" / f"{job['blind_id']}.json"
        if parsed_path.exists():
            batch = validate(Batch.model_validate_json(parsed_path.read_text(encoding="utf-8")), job)
            batches.append(batch)
            continue
        response = call(job)
        if response.output_parsed is None:
            raise RuntimeError("No parsed scoring response")
        raw_path = out / "raw" / f"{job['blind_id']}.json"
        atomic_json(raw_path, response.model_dump(mode="json", warnings=False))
        batch = validate(response.output_parsed, job)
        atomic_text(parsed_path, batch.model_dump_json(indent=2))
        usage = response.usage
        usage_path = out / "usage.jsonl"
        usage_path.parent.mkdir(parents=True, exist_ok=True)
        with usage_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"timestamp_utc": datetime.now(timezone.utc).isoformat(), "blind_id": job["blind_id"], "model": response.model,
                                     "input_tokens": getattr(usage, "input_tokens", 0), "output_tokens": getattr(usage, "output_tokens", 0),
                                     "prompt_sha256": PROMPT_SHA256}) + "\n")
        batches.append(batch)
    rows = [row.model_dump() for batch in batches for row in batch.suggestions]
    if len(rows) != manifest["expected_rows"]:
        raise RuntimeError("Aggregate scoring row count mismatch")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(Suggestion.model_fields))
    writer.writeheader(); writer.writerows(rows)
    target = out / f"{measure}_suggestions.csv"
    atomic_text(target, stream.getvalue())
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["build-jobs", "preannotate"])
    parser.add_argument("--measure", choices=MEASURES)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--workers", type=int, choices=range(1, 6), default=1)
    args = parser.parse_args()
    if args.all == bool(args.measure):
        raise SystemExit("Choose exactly one of --all or --measure")
    measures = MEASURES if args.all else [args.measure]
    if args.command == "build-jobs":
        for measure in measures: print(build_jobs(measure))
        return
    load_dotenv(ROOT / ".env")
    key, model = os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_MODEL")
    if not key or not model:
        raise SystemExit("OPENAI_API_KEY and OPENAI_MODEL are required")
    def execute(measure: str) -> Path:
        return preannotate(measure, OpenAI(api_key=key), model)
    if args.workers == 1:
        for measure in measures: print(execute(measure))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(execute, measure): measure for measure in measures}
            for future in as_completed(futures): print(future.result())


if __name__ == "__main__":
    main()
