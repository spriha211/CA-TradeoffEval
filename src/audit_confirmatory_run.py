import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_runner_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def first(mapping, names, default=None):
    if not isinstance(mapping, dict):
        return default

    for name in names:
        if name in mapping:
            return mapping[name]

    return default


def recursive_find(value, possible_keys):
    if isinstance(value, dict):
        for key in possible_keys:
            if key in value:
                return value[key]

        for nested in value.values():
            found = recursive_find(nested, possible_keys)
            if found is not None:
                return found

    elif isinstance(value, list):
        for nested in value:
            found = recursive_find(nested, possible_keys)
            if found is not None:
                return found

    return None


if len(sys.argv) != 3:
    raise SystemExit(
        "Usage: python src/audit_confirmatory_run.py MEASURE_ID TRIAL_NUMBER\n"
        "Example: python src/audit_confirmatory_run.py M02 2"
    )

measure_id = sys.argv[1].upper()

try:
    trial_number = int(sys.argv[2])
except ValueError:
    raise SystemExit("Trial number must be an integer.")

trial_tag = f"trial{trial_number:02d}"

masters = sorted(
    (ROOT / "runs/raw").glob(
        f"{measure_id}_{trial_tag}_*_complete.json"
    )
)

if len(masters) != 1:
    raise RuntimeError(
        f"Expected exactly one {measure_id} {trial_tag} master file; "
        f"found {len(masters)}."
    )

master_path = masters[0]
data = json.loads(master_path.read_text(encoding="utf-8"))

source_path = ROOT / f"data/source_documents/{measure_id}.txt"
freeze_path = (
    ROOT
    / f"data/freeze_manifests/{measure_id}_freeze_manifest.txt"
)


# ============================================================
# Run identity
# ============================================================

print("=== RUN IDENTITY ===")
print("Master file:", master_path.relative_to(ROOT))
print("Trial ID:", data.get("trial_id"))
print("Run stage:", data.get("run_stage"))
print("Measure:", data.get("measure_id"))
print("Trial:", data.get("trial_number"))
print("Model:", data.get("requested_model"))
print("Started:", data.get("started_at"))
print("Finished:", data.get("finished_at"))

assert data.get("run_stage") == "confirmatory"
assert data.get("measure_id") == measure_id
assert int(data.get("trial_number")) == trial_number
assert data.get("requested_model")

print("PASS — run identity")


# ============================================================
# Source integrity
# ============================================================

assert source_path.exists(), f"Missing source: {source_path}"
assert freeze_path.exists(), f"Missing freeze manifest: {freeze_path}"

current_raw_hash = sha256_bytes(source_path)
runner_normalized_hash = sha256_runner_text(source_path)
logged_source_hash = data["source"]["sha256"]

freeze_text = freeze_path.read_text(encoding="utf-8")

match = re.search(
    rf"([0-9a-f]{{64}})\s+.*data/source_documents/{re.escape(measure_id)}\.txt",
    freeze_text,
)

assert match is not None, (
    f"Could not find the {measure_id}.txt hash in the freeze manifest."
)

frozen_raw_hash = match.group(1)

print("\n=== SOURCE INTEGRITY ===")
print("Frozen raw-file hash:", frozen_raw_hash)
print("Current raw-file hash:", current_raw_hash)
print("Runner-normalized hash:", runner_normalized_hash)
print("Logged run hash:", logged_source_hash)
print("Logged source words:", data["source"].get("word_count"))

assert current_raw_hash == frozen_raw_hash
assert runner_normalized_hash == logged_source_hash

print("PASS — frozen source file remains unchanged")
print("PASS — run used the normalized frozen source text")


# ============================================================
# Protocol and prompt hashes
# ============================================================

protocol = data["protocol"]
prompt_version = protocol["prompt_version"]
logged_prompt_hashes = protocol["prompt_hashes"]

print("\n=== PROTOCOL ===")
print("Protocol file:", protocol.get("protocol_file"))
print("Prompt version:", prompt_version)
print("Logged prompt hashes:")

for name, digest in logged_prompt_hashes.items():
    print(f"  {name}: {digest}")

assert "protocol_v1_1" in str(protocol.get("protocol_file"))

prompt_files = {
    "round1": ROOT / f"prompts/{prompt_version}/round1.txt",
    "normal_review": ROOT / f"prompts/{prompt_version}/normal_review.txt",
    "critic": ROOT / f"prompts/{prompt_version}/critic.txt",
    "synthesis": ROOT / f"prompts/{prompt_version}/synthesis.txt",
}

for name, path in prompt_files.items():
    assert path.exists(), f"Missing prompt file: {path}"

    current_hash = sha256_runner_text(path)
    logged_hash = logged_prompt_hashes[name]

    assert current_hash == logged_hash, (
        f"Prompt hash mismatch for {name}."
    )

print("PASS — protocol v1.1 recorded")
print("PASS — all logged prompt hashes match current frozen prompts")


# ============================================================
# API parameters
# ============================================================

api = data["api_parameters"]

print("\n=== API PARAMETERS ===")
for key, value in api.items():
    print(f"{key}: {value}")

assert api.get("reasoning_mode") == "standard"
assert api.get("reasoning_effort") == "medium"
assert api.get("text_verbosity") == "medium"
assert int(api.get("max_output_tokens")) == 25000

print("PASS — API parameters")


# ============================================================
# Experimental controls
# ============================================================

controls = data["controls"]

presentation_order = controls["presentation_order"]
single_identity = controls["single_agent_identity"]
critic_identity = controls["critic_agent_identity"]
shared_round1 = controls[
    "shared_round1_across_setups_2_3_4"
]
shared_revisions = controls[
    "shared_normal_revisions_between_setups_3_4"
]
same_synthesis = controls[
    "same_synthesis_prompt_for_setups_2_3_4"
]

print("\n=== CONTROLS ===")
print("Presentation order:", presentation_order)
print("Single-agent identity:", single_identity)
print("Critic-agent identity:", critic_identity)
print("Shared Round 1:", shared_round1)
print("Shared normal revisions:", shared_revisions)
print("Same synthesis prompt:", same_synthesis)

assert sorted(presentation_order) == [1, 2, 3]
assert single_identity in [1, 2, 3]
assert critic_identity in [1, 2, 3]
assert shared_round1 is True
assert same_synthesis is True

expected_noncritic_agents = sorted(
    agent for agent in [1, 2, 3]
    if agent != critic_identity
)

assert sorted(shared_revisions) == expected_noncritic_agents

print("PASS — presentation order is valid")
print("PASS — paired Round-1 control is active")
print("PASS — Setup 4 reuses the two non-critic revisions")
print("PASS — synthesis prompt is held constant")


# ============================================================
# Final word counts only
# ============================================================

word_counts = data["final_word_counts"]

print("\n=== FINAL WORD COUNTS ===")

for condition, count in word_counts.items():
    print(f"{condition}: {count}")

assert len(word_counts) == 4

for condition, count in word_counts.items():
    assert 0 < int(count) <= 500, (
        f"{condition} has invalid word count: {count}"
    )

print("PASS — four nonempty outputs, all within 500 words")


# ============================================================
# API-call metadata only
# ============================================================

raw_calls = data["actual_api_calls"]

if isinstance(raw_calls, list):
    calls = raw_calls
elif isinstance(raw_calls, dict):
    calls = list(raw_calls.values())
else:
    raise RuntimeError(
        f"Unexpected actual_api_calls type: {type(raw_calls)}"
    )

print("\n=== API CALLS ===")
print("Actual call records:", len(calls))

assert len(calls) == 10

bad_statuses = []
incomplete_calls = []
missing_statuses = 0

for index, call in enumerate(calls, start=1):
    label = first(
        call,
        [
            "call_label",
            "call_name",
            "stage",
            "role",
            "name",
        ],
        f"call_{index}",
    )

    status = first(
        call,
        ["status", "response_status"],
        None,
    )

    incomplete = first(
        call,
        ["incomplete_details", "incomplete_reason"],
        None,
    )

    input_tokens = recursive_find(
        call,
        ["input_tokens", "prompt_tokens"],
    )

    output_tokens = recursive_find(
        call,
        ["output_tokens", "completion_tokens"],
    )

    reasoning_tokens = recursive_find(
        call,
        ["reasoning_tokens"],
    )

    cached_tokens = recursive_find(
        call,
        ["cached_input_tokens", "cached_tokens"],
    )

    print(
        f"{index:02d}. {label} | "
        f"status={status if status is not None else '[not logged]'} | "
        f"input={input_tokens} | "
        f"output={output_tokens} | "
        f"reasoning={reasoning_tokens} | "
        f"cached={cached_tokens}"
    )

    if status is None:
        missing_statuses += 1
    elif str(status).lower() not in {
        "completed",
        "complete",
        "success",
        "succeeded",
    }:
        bad_statuses.append((label, status))

    if incomplete not in (None, "", {}, []):
        incomplete_calls.append((label, incomplete))

assert not bad_statuses, bad_statuses
assert not incomplete_calls, incomplete_calls

print("PASS — exactly 10 API calls")
print("PASS — no logged failures or incomplete responses")

if missing_statuses:
    print(
        f"NOTE — explicit status missing for "
        f"{missing_statuses}/10 calls."
    )
else:
    print("PASS — explicit status logged for all calls")


# ============================================================
# Token totals
# ============================================================

totals = data["actual_trial_token_totals"]

print("\n=== TOKEN TOTALS ===")
print(json.dumps(totals, indent=2))

input_total = recursive_find(
    totals,
    ["input_tokens", "total_input_tokens"],
)

output_total = recursive_find(
    totals,
    ["output_tokens", "total_output_tokens"],
)

total_tokens = recursive_find(
    totals,
    ["total_tokens"],
)

assert input_total is not None and int(input_total) > 0
assert output_total is not None and int(output_total) > 0
assert total_tokens is not None and int(total_tokens) > 0

print("PASS — nonzero token totals")


# ============================================================
# Output files
# ============================================================

condition_files = sorted(
    (ROOT / "runs/raw").glob(
        f"{measure_id}_{trial_tag}_*_setup*.json"
    )
)

print("\n=== CONDITION FILES ===")

for path in condition_files:
    print(path.name)

assert len(condition_files) == 4

print("PASS — exactly four condition files")


print("\n========================================")
print(
    f"{measure_id} TRIAL {trial_number} "
    "METADATA AUDIT: PASS"
)
print("No substantive model-output text was displayed.")
print("========================================")
