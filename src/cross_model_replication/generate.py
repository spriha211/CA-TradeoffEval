from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from itertools import permutations
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "runs/audits/cross_model_replication/STUDY2_PRE_GENERATION_PROTOCOL.json"
PROTOCOL_SHA256 = "c6a054ad78c8f3f1e1f06428dcc7ac2a5d74a90b40f9b530b514507c60d619b8"
RUN_ROOT = ROOT / "runs/cross_model_replication/claude_sonnet_5"
PROMPT_DIR = ROOT / "prompts/v1_0"
MEASURES = ["M03", "M08", "M02", "M09", "M05"]
MODEL = "claude-sonnet-5"
MAX_TOKENS = 25_000
TEMPERATURE = 1.0


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recorded_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def atomic_text(path: Path, value: str) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(value.rstrip() + "\n", encoding="utf-8")
    os.replace(temporary, path)


def verify_protocol() -> None:
    if sha256_file(PROTOCOL) != PROTOCOL_SHA256:
        raise RuntimeError("Frozen Study 2 protocol hash mismatch")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol["measure_selection"]["frozen_selected_measures"] != MEASURES:
        raise RuntimeError("Frozen Study 2 measure selection mismatch")


def controls(measure: str, trial: int) -> tuple[list[int], int, int]:
    number = int(measure[1:])
    orders = [list(order) for order in permutations([1, 2, 3])]
    index = (number - 1) * 4 + (trial - 1)
    return orders[index % 6], ((number + trial - 2) % 3) + 1, ((2 * (number - 1) + trial) % 3) + 1


def reviewer_input(source: str, agent: int, initial: dict[int, str], order: list[int]) -> str:
    others = "\n\n".join(
        f"OTHER AGENT {other} INITIAL ANALYSIS:\n{initial[other]}"
        for other in order if other != agent
    )
    return f"OFFICIAL SOURCE MATERIAL:\n\n{source}\n\nYOUR ORIGINAL ANALYSIS:\n\n{initial[agent]}\n\nOTHER AGENTS' INITIAL ANALYSES:\n\n{others}"


def candidates(outputs: dict[int, str], order: list[int]) -> str:
    return "\n\n".join(f"CANDIDATE OUTPUT {agent}:\n{outputs[agent]}" for agent in order)


class ClaudeAdapter:
    def __init__(self, client: Anthropic, run_dir: Path):
        self.client = client
        self.run_dir = run_dir
        self.usage: list[dict[str, Any]] = []

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20), reraise=True)
    def _request(self, instructions: str, input_text: str):
        # Anthropic's SDK requires streaming for requests with a token ceiling
        # large enough to exceed its ten-minute non-streaming timeout estimate.
        # This changes transport only; prompts and generation parameters are identical.
        with self.client.messages.stream(
            model=MODEL,
            system=instructions,
            messages=[{"role": "user", "content": input_text}],
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
        ) as stream:
            return stream.get_final_message()

    def call(self, name: str, instructions: str, input_text: str) -> str:
        parsed_path = self.run_dir / "parsed" / f"{name}.txt"
        metadata_path = self.run_dir / "metadata" / f"{name}.json"
        raw_path = self.run_dir / "raw" / f"{name}.json"
        if parsed_path.exists() and metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.usage.append(metadata["usage"])
            return parsed_path.read_text(encoding="utf-8").strip()
        if raw_path.exists():
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            output = "".join(block["text"] for block in raw["content"] if block.get("type") == "text").strip()
            raw_usage = raw.get("usage", {})
            returned_model = raw.get("model")
            usage = {
                "call_name": name, "requested_model": MODEL, "returned_model": returned_model,
                "input_tokens": raw_usage.get("input_tokens", 0), "output_tokens": raw_usage.get("output_tokens", 0),
                "cache_creation_input_tokens": raw_usage.get("cache_creation_input_tokens", 0) or 0,
                "cache_read_input_tokens": raw_usage.get("cache_read_input_tokens", 0) or 0,
            }
        else:
            response = self._request(instructions, input_text)
            text_blocks = [block.text for block in response.content if getattr(block, "type", None) == "text"]
            output = "".join(text_blocks).strip()
            usage = {
                "call_name": name, "requested_model": MODEL, "returned_model": response.model,
                "input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens,
                "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
                "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            }
            raw = response.model_dump(mode="json") if hasattr(response, "model_dump") else json.loads(response.to_json())
            atomic_json(raw_path, raw)
        if not output:
            raise RuntimeError(f"Claude returned no text for {name}")
        atomic_text(parsed_path, output)
        atomic_json(metadata_path, {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "provider": "anthropic",
            "parameters": {"model": MODEL, "max_tokens": MAX_TOKENS, "temperature": TEMPERATURE},
            "provider_specific_format": {"instructions": "system", "input": "single user message"},
            "usage": usage,
            "raw_response_path": recorded_path(raw_path),
            "raw_response_sha256": sha256_file(raw_path),
            "parsed_text_path": recorded_path(parsed_path),
            "parsed_text_sha256": sha256_file(parsed_path),
        })
        self.usage.append(usage)
        return output


def run_trial(client: Anthropic, measure: str, trial: int, smoke: bool = False) -> Path:
    verify_protocol()
    if measure not in MEASURES or trial not in range(1, 5):
        raise ValueError("Trial is outside the frozen Study 2 design")
    base = RUN_ROOT / ("development_smoke" if smoke else "generation")
    trial_dir = base / measure / f"trial{trial:02d}"
    complete = trial_dir / "complete.json"
    if complete.exists():
        return complete
    source_path = ROOT / "data/source_documents" / f"{measure}.txt"
    source = source_path.read_text(encoding="utf-8").strip()
    if len(source) < 200:
        raise RuntimeError("Invalid source packet")
    prompts = {name: (PROMPT_DIR / f"{name}.txt").read_text(encoding="utf-8").strip() for name in ("round1", "normal_review", "critic", "synthesis")}
    order, critic_agent, single_agent = controls(measure, trial)
    adapter = ClaudeAdapter(client, trial_dir)
    initial = {
        agent: adapter.call(f"round1_agent_{agent}", prompts["round1"], f"OFFICIAL SOURCE MATERIAL:\n\n{source}")
        for agent in (1, 2, 3)
    }
    setup1 = initial[single_agent]
    setup2 = adapter.call("setup2_independent_synthesis", prompts["synthesis"], f"OFFICIAL SOURCE MATERIAL:\n\n{source}\n\nCANDIDATE AGENT OUTPUTS:\n\n{candidates(initial, order)}")
    normal = {
        agent: adapter.call(f"normal_revision_agent_{agent}", prompts["normal_review"], reviewer_input(source, agent, initial, order))
        for agent in (1, 2, 3)
    }
    setup3 = adapter.call("setup3_debate_synthesis", prompts["synthesis"], f"OFFICIAL SOURCE MATERIAL:\n\n{source}\n\nCANDIDATE AGENT OUTPUTS:\n\n{candidates(normal, order)}")
    critic = adapter.call(f"critic_agent_{critic_agent}", prompts["critic"], reviewer_input(source, critic_agent, initial, order))
    critic_branch = dict(normal)
    critic_branch[critic_agent] = critic
    setup4 = adapter.call("setup4_critic_synthesis", prompts["synthesis"], f"OFFICIAL SOURCE MATERIAL:\n\n{source}\n\nCANDIDATE AGENT OUTPUTS:\n\n{candidates(critic_branch, order)}")
    finals = {"setup1_single": setup1, "setup2_independent": setup2, "setup3_debate": setup3, "setup4_critic": setup4}
    returned_models = sorted({row["returned_model"] for row in adapter.usage})
    record = {
        "schema_version": "1.0", "study": "Study 2", "development_smoke": smoke,
        "measure_id": measure, "trial_number": trial,
        "requested_model": MODEL, "returned_models": returned_models,
        "parameters": {"max_tokens": MAX_TOKENS, "temperature": TEMPERATURE},
        "source": {"path": str(source_path.relative_to(ROOT)), "sha256": sha256_file(source_path)},
        "prompts": {name: {"path": str((PROMPT_DIR / f'{name}.txt').relative_to(ROOT)), "sha256": sha256_file(PROMPT_DIR / f"{name}.txt")} for name in prompts},
        "controls": {"presentation_order": order, "critic_agent": critic_agent, "single_agent": single_agent,
                     "shared_round1_across_conditions": True, "normal_revisions_reused_in_critic_branch": [a for a in (1,2,3) if a != critic_agent]},
        "intermediate_outputs": {"initial": initial, "normal_revisions": normal, "critic": {"agent_id": critic_agent, "text": critic}},
        "final_outputs": finals, "final_word_counts": {key: len(value.split()) for key, value in finals.items()},
        "api_calls": adapter.usage,
        "protocol_path": str(PROTOCOL.relative_to(ROOT)), "protocol_sha256": PROTOCOL_SHA256,
    }
    atomic_json(complete, record)
    return complete


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--measure", choices=MEASURES)
    parser.add_argument("--trial", type=int, choices=range(1, 5))
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=1)
    args = parser.parse_args()
    if args.all == bool(args.measure):
        raise SystemExit("Choose either --all or --measure with --trial")
    if args.measure and args.trial is None:
        raise SystemExit("--trial is required with --measure")
    load_dotenv(dotenv_path=".env")
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY is unavailable (value was not printed)")
    targets = [(m, t) for m in MEASURES for t in range(1, 5)] if args.all else [(args.measure, args.trial)]
    def execute(target: tuple[str, int]) -> Path:
        measure, trial = target
        return run_trial(Anthropic(api_key=key), measure, trial, smoke=args.smoke)
    if args.workers == 1:
        for target in targets:
            print(execute(target))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(execute, target): target for target in targets}
            for future in as_completed(futures):
                print(future.result())


if __name__ == "__main__":
    main()
