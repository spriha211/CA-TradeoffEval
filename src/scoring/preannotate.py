from __future__ import annotations

import argparse
import csv
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from src.scoring.integrity import (
    IntegrityError, append_jsonl, atomic_write_json, atomic_write_text,
    read_text, require_unique, sha256_bytes, validate_blind_id, validate_measure,
)

ROOT = Path(__file__).resolve().parents[2]


class ComponentSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    blind_id: str
    component_id: str
    suggested_preservation: int = Field(ge=0, le=1)
    exact_evidence_quote: str
    short_reason: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    distortion_severity: int = Field(ge=0, le=2)
    distortion_explanation: str
    needs_human_review: bool


class SuggestionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    suggestions: list[ComponentSuggestion]


ORIGINAL_SYSTEM_PROMPT = """You are a condition-blind research pre-annotator. Score every supplied
atomic component against only the blinded answer and its component-specific rule.
Return one row per component. Give preservation 1 only when correctly and sufficiently
preserved; otherwise 0. Do not infer unstated facts. Use semantic equivalence. A material
distortion must receive preservation 0. Evidence must be an exact contiguous quote from
the blinded answer, or the empty string when no supporting quote exists. Flag uncertainty,
partial matches, ambiguous scope, wrong quantities, missing qualifications, and possible
contradictions for human review. These are suggestions, never final labels."""

PILOT_SENTENCE = (
    "Evaluate every component independently: a quote that supports only a related or "
    "neighboring component is insufficient; if the quote itself does not establish the "
    "required entity, relationship, quantity, timeframe, and material qualification, "
    "score preservation 0 and flag it for human review."
)
PILOT_SYSTEM_PROMPT = ORIGINAL_SYSTEM_PROMPT + "\n\n" + PILOT_SENTENCE
PROMPTS = {
    "v1.0": ORIGINAL_SYSTEM_PROMPT,
    "v1.1-pilot": PILOT_SYSTEM_PROMPT,
    "v1.1-production": PILOT_SYSTEM_PROMPT,
}


def validate_batch(batch: SuggestionBatch, job: dict[str, Any]) -> None:
    blind_id = validate_blind_id(job["blind_id"], job["measure_id"])
    expected = [row["component_id"] for row in job["components"]]
    found = [row.component_id for row in batch.suggestions]
    if len(found) != len(expected) or set(found) != set(expected):
        raise IntegrityError("Model response has missing or unexpected component rows")
    require_unique(found, "model component_id")
    answer = job["blinded_answer"]
    for row in batch.suggestions:
        if row.blind_id != blind_id:
            raise IntegrityError(f"Model returned wrong blind_id: {row.blind_id}")
        if row.exact_evidence_quote and row.exact_evidence_quote not in answer:
            raise IntegrityError(f"Evidence quote is not exact for {row.component_id}")
        if row.suggested_preservation == 1 and not row.exact_evidence_quote:
            raise IntegrityError(f"Preservation 1 requires evidence for {row.component_id}")
        if row.distortion_severity == 2 and row.suggested_preservation != 0:
            raise IntegrityError(f"Material distortion must score 0 for {row.component_id}")


def fail_closed_invalid_quotes(
    batch: SuggestionBatch, job: dict[str, Any]
) -> tuple[SuggestionBatch, list[str]]:
    """Downgrade invalid model evidence without altering the saved raw response."""
    corrected = batch.model_copy(deep=True)
    answer = job["blinded_answer"]
    changed: list[str] = []
    for row in corrected.suggestions:
        if row.exact_evidence_quote and row.exact_evidence_quote not in answer:
            row.suggested_preservation = 0
            row.exact_evidence_quote = ""
            row.needs_human_review = True
            changed.append(row.component_id)
    return corrected, changed


def load_checkpoint(root: Path, parsed_path: Path, job: dict[str, Any]) -> SuggestionBatch:
    batch = SuggestionBatch.model_validate_json(read_text(root, parsed_path))
    validate_batch(batch, job)
    return batch


def response_usage(
    response: Any, blind_id: str, attempts: int, prompt_version: str, prompt_sha256: str
) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "blind_id": blind_id,
        "attempts": attempts,
        "scoring_prompt_version": prompt_version,
        "scoring_prompt_sha256": prompt_sha256,
        "model": getattr(response, "model", None),
        "input_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
        "output_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
        "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
    }
    in_rate = os.getenv("OPENAI_INPUT_COST_PER_1M")
    out_rate = os.getenv("OPENAI_OUTPUT_COST_PER_1M")
    if in_rate and out_rate:
        record["estimated_cost_usd"] = (
            record["input_tokens"] * float(in_rate) + record["output_tokens"] * float(out_rate)
        ) / 1_000_000
    return record


def run_preannotation(
    root: Path,
    measure: str,
    client: OpenAI,
    model: str,
    blind_id: str | None = None,
    limit: int | None = None,
    prompt_version: str = "v1.1-production",
) -> Path:
    measure = validate_measure(measure)
    if prompt_version not in PROMPTS:
        raise IntegrityError(f"Unknown scoring prompt version: {prompt_version}")
    scoring_prompt = PROMPTS[prompt_version]
    prompt_sha256 = sha256_bytes((scoring_prompt + "\n").encode("utf-8"))
    jobs_dir = root / "analysis/model_assisted_scoring/jobs" / measure
    manifest = json.loads(read_text(root, jobs_dir / "manifest.json"))
    if manifest["measure_id"] != measure or manifest["blind_output_count"] != 16:
        raise IntegrityError("Invalid scoring-job manifest")
    job_records = manifest["jobs"]
    if blind_id is not None:
        validate_blind_id(blind_id, measure)
        job_records = [record for record in job_records if record["blind_id"] == blind_id]
        if len(job_records) != 1:
            raise IntegrityError(f"Blind ID is not present in the job manifest: {blind_id}")
    elif limit is not None:
        if limit < 1 or limit > 16:
            raise IntegrityError("--limit must be between 1 and 16")
        job_records = job_records[:limit]
    out_dir = root / "analysis/model_assisted_scoring/preannotations" / measure
    raw_dir, parsed_dir = out_dir / "raw", out_dir / "parsed"
    usage_path, error_path = out_dir / "usage.jsonl", out_dir / "errors.jsonl"
    correction_path = out_dir / "validation_corrections.jsonl"
    batches: list[SuggestionBatch] = []
    attempts: dict[str, int] = {}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
    def call(job: dict[str, Any]):
        blind_id = job["blind_id"]
        attempts[blind_id] = attempts.get(blind_id, 0) + 1
        response = client.responses.parse(
            model=model,
            instructions=scoring_prompt,
            input=json.dumps(job, ensure_ascii=False),
            text_format=SuggestionBatch,
        )
        if response.output_parsed is None:
            raise IntegrityError("Model response did not contain parsed structured output")
        raw_value = response.model_dump(mode="json", warnings=False)
        corrected, corrections = fail_closed_invalid_quotes(response.output_parsed, job)
        validate_batch(corrected, job)
        return response, raw_value, corrected, corrections

    for record in job_records:
        job = json.loads(read_text(root, root / record["path"]))
        current_blind_id = validate_blind_id(job["blind_id"], measure)
        parsed_path = parsed_dir / f"{current_blind_id}.json"
        if parsed_path.exists():
            batches.append(load_checkpoint(root, parsed_path, job))
            continue
        try:
            response, raw_value, parsed_batch, corrections = call(job)
            raw_path = raw_dir / f"{current_blind_id}.json"
            if raw_path.exists():
                # A prior process may have stopped between raw and parsed writes.
                # Preserve both responses without overwriting either one.
                response_id = str(getattr(response, "id", "retry")).replace("/", "_")
                raw_path = raw_dir / f"{current_blind_id}.{response_id}.json"
            atomic_write_json(root, raw_path, raw_value)
            atomic_write_text(root, parsed_path, parsed_batch.model_dump_json(indent=2) + "\n")
            append_jsonl(root, usage_path, response_usage(
                response, current_blind_id, attempts[current_blind_id],
                prompt_version, prompt_sha256,
            ))
            if corrections:
                append_jsonl(root, correction_path, {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "blind_id": current_blind_id,
                    "component_ids": corrections,
                    "action": "invalid quote cleared; preservation set to 0; human review required",
                    "raw_response_preserved": True,
                })
            batches.append(parsed_batch)
        except Exception as exc:
            append_jsonl(root, error_path, {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "blind_id": current_blind_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "attempts": attempts.get(current_blind_id, 0),
            })
            raise

    rows = [row.model_dump() for batch in batches for row in batch.suggestions]
    expected_rows = len(job_records) * int(manifest["component_count"])
    if len(rows) != expected_rows:
        raise IntegrityError(f"Expected {expected_rows} parsed rows; found {len(rows)}")
    keys = [(row["blind_id"], row["component_id"]) for row in rows]
    require_unique(("\x1f".join(key) for key in keys), "blind/component row")
    fields = list(ComponentSuggestion.model_fields)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    if blind_id is not None:
        csv_path = out_dir / f"{measure}_pilot_{blind_id}_suggestions.csv"
    elif limit is not None:
        csv_path = out_dir / f"{measure}_pilot_first_{limit}_suggestions.csv"
    else:
        csv_path = out_dir / f"{measure}_suggestions.csv"
    if csv_path.exists():
        existing = read_text(root, csv_path)
        if existing.splitlines() != stream.getvalue().splitlines():
            raise FileExistsError(f"Existing aggregate differs; refusing overwrite: {csv_path}")
    else:
        atomic_write_text(root, csv_path, stream.getvalue())
    return csv_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Model-assisted blinded component pre-annotation")
    parser.add_argument("--measure", required=True)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--blind-id", help="Preannotate one manifest-listed blinded output")
    selection.add_argument("--limit", type=int, help="Preannotate only the first N manifest-listed outputs")
    parser.add_argument(
        "--prompt-version", choices=sorted(PROMPTS), default="v1.1-production",
        help="Versioned blinded scoring prompt (default: v1.1-production)",
    )
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args()
    load_dotenv(args.root / ".env")
    api_key, model = os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_MODEL")
    if not api_key or not model:
        raise SystemExit("OPENAI_API_KEY and OPENAI_MODEL are required")
    print(run_preannotation(
        args.root.resolve(), args.measure, OpenAI(api_key=api_key), model,
        blind_id=args.blind_id, limit=args.limit, prompt_version=args.prompt_version,
    ))


if __name__ == "__main__":
    main()
