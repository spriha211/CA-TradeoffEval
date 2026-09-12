from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from itertools import permutations
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential


# --------------------------------------------------
# PROJECT SETTINGS
# --------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
PROMPT_DIR = ROOT / "prompts" / "v1_0"

load_dotenv(ROOT / ".env")

RUN_STAGE = os.getenv(
    "CA_TRADEOFF_RUN_STAGE",
    "confirmatory",
).strip().lower()

if RUN_STAGE not in {
    "pilot",
    "confirmatory",
}:
    raise ValueError(
        "CA_TRADEOFF_RUN_STAGE must be "
        "'pilot' or 'confirmatory'."
    )

if RUN_STAGE == "pilot":
    OUTPUT_DIR = ROOT / "runs" / "pilot"
else:
    OUTPUT_DIR = ROOT / "runs" / "raw"

API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("OPENAI_MODEL")

REASONING_MODE = os.getenv(
    "OPENAI_REASONING_MODE",
    "standard",
)

REASONING_EFFORT = os.getenv(
    "OPENAI_REASONING_EFFORT",
    "medium",
)

TEXT_VERBOSITY = os.getenv(
    "OPENAI_TEXT_VERBOSITY",
    "medium",
)

MAX_OUTPUT_TOKENS = int(
    os.getenv(
        "OPENAI_MAX_OUTPUT_TOKENS",
        "25000",
    )
)

if not API_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing from .env")

if not MODEL:
    raise RuntimeError("OPENAI_MODEL is missing from .env")

client = OpenAI(api_key=API_KEY)


# --------------------------------------------------
# BASIC HELPERS
# --------------------------------------------------

def read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")

    text = path.read_text(encoding="utf-8").strip()

    if not text:
        raise ValueError(f"File is empty: {path}")

    return text


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def word_count(text: str) -> int:
    return len(text.split())


def parse_measure_number(measure_id: str) -> int:
    match = re.fullmatch(r"M(\d+)", measure_id)

    if not match:
        raise ValueError(
            "Measure ID must look like M01, M02, M03, etc."
        )

    number = int(match.group(1))

    if number < 1:
        raise ValueError("Measure number must be at least 1.")

    return number


CORE_MEASURES = 10
CORE_TRIALS_PER_MEASURE = 4


def presentation_schedule_index(
    measure_number: int,
    trial_number: int,
) -> int:
    """
    Predefined counterbalancing schedule.

    The primary experiment contains:
        10 measures x 4 trials = 40 trials.

    For those 40 trials, presentation orders are distributed
    as evenly as mathematically possible across the six possible
    permutations.

    Any fifth-trial stretch runs are placed after the complete
    40-trial core schedule so they do not change the core
    counterbalancing.
    """

    if trial_number <= CORE_TRIALS_PER_MEASURE:
        return (
            (measure_number - 1)
            * CORE_TRIALS_PER_MEASURE
            + (trial_number - 1)
        )

    # Stretch trials come after the 40 core trials.
    return (
        CORE_MEASURES * CORE_TRIALS_PER_MEASURE
        + (trial_number - CORE_TRIALS_PER_MEASURE - 1)
        * CORE_MEASURES
        + (measure_number - 1)
    )


def get_trial_controls(
    measure_number: int,
    trial_number: int,
) -> tuple[list[int], int, int]:
    """
    Returns three controls fixed before model outputs are generated:

    1. presentation_order
    2. critic_agent
    3. single_agent

    Presentation order:
    Cycles systematically through all six permutations.

    Critic identity:
    Rotates across Agents 1, 2, and 3. Every measure's four
    core trials include all three possible critic identities.

    Single-agent identity:
    Also rotates across Agents 1, 2, and 3, using a different
    schedule from critic identity. Every measure's four core
    trials include all three possible single-agent identities.

    Nothing is selected after seeing model outputs.
    """

    orders = [
        list(order)
        for order in permutations([1, 2, 3])
    ]

    order_index = presentation_schedule_index(
        measure_number,
        trial_number,
    )

    presentation_order = orders[
        order_index % len(orders)
    ]

    critic_agent = (
        (measure_number + trial_number - 2) % 3
    ) + 1

    single_agent = (
        (
            2 * (measure_number - 1)
            + trial_number
        )
        % 3
    ) + 1

    return (
        list(presentation_order),
        critic_agent,
        single_agent,
    )


# --------------------------------------------------
# TOKEN / FORMATTING HELPERS
# --------------------------------------------------

def token_totals(records: list[dict]) -> dict:
    return {
        "input_tokens": sum(
            record.get("input_tokens", 0)
            for record in records
        ),
        "cached_input_tokens": sum(
            record.get("cached_input_tokens", 0)
            for record in records
        ),
        "output_tokens": sum(
            record.get("output_tokens", 0)
            for record in records
        ),
        "reasoning_tokens": sum(
            record.get("reasoning_tokens", 0)
            for record in records
        ),
        "total_tokens": sum(
            record.get("total_tokens", 0)
            for record in records
        ),
    }


def format_candidate_outputs(
    outputs_by_agent: dict[int, str],
    presentation_order: list[int],
) -> str:
    parts = []

    for agent_id in presentation_order:
        parts.append(
            f"CANDIDATE OUTPUT {agent_id}:\n"
            f"{outputs_by_agent[agent_id]}"
        )

    return "\n\n".join(parts)


def reviewer_input(
    source_text: str,
    agent_id: int,
    initial_outputs: dict[int, str],
    presentation_order: list[int],
) -> str:
    """
    The normal-review and critic versions of the same agent receive
    exactly the same information.

    Only the role prompt changes.
    """

    other_agent_ids = [
        other_id
        for other_id in presentation_order
        if other_id != agent_id
    ]

    other_outputs = "\n\n".join(
        f"OTHER AGENT {other_id} INITIAL ANALYSIS:\n"
        f"{initial_outputs[other_id]}"
        for other_id in other_agent_ids
    )

    return f"""
OFFICIAL SOURCE MATERIAL:

{source_text}

YOUR ORIGINAL ANALYSIS:

{initial_outputs[agent_id]}

OTHER AGENTS' INITIAL ANALYSES:

{other_outputs}
""".strip()


# --------------------------------------------------
# LOAD VERSIONED PROMPTS
# --------------------------------------------------

ROUND1_PROMPT = read_text(
    PROMPT_DIR / "round1.txt"
)

NORMAL_REVIEW_PROMPT = read_text(
    PROMPT_DIR / "normal_review.txt"
)

CRITIC_PROMPT = read_text(
    PROMPT_DIR / "critic.txt"
)

SYNTHESIS_PROMPT = read_text(
    PROMPT_DIR / "synthesis.txt"
)

PROMPTS = {
    "round1": ROUND1_PROMPT,
    "normal_review": NORMAL_REVIEW_PROMPT,
    "critic": CRITIC_PROMPT,
    "synthesis": SYNTHESIS_PROMPT,
}

PROMPT_HASHES = {
    name: sha256_text(text)
    for name, text in PROMPTS.items()
}


# --------------------------------------------------
# MODEL CALL
# --------------------------------------------------

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(
        multiplier=2,
        min=2,
        max=20,
    ),
)
def call_model(
    instructions: str,
    input_text: str,
    call_name: str,
) -> tuple[str, dict]:
    response = client.responses.create(
        model=MODEL,
        instructions=instructions,
        input=input_text,
        reasoning={
            "mode": REASONING_MODE,
            "effort": REASONING_EFFORT,
        },
        text={
            "verbosity": TEXT_VERBOSITY,
        },
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )

    output_text = response.output_text

    if not output_text:
        raise RuntimeError(
            f"No text returned for {call_name}"
        )

    usage_record = {
        "call_name": call_name,
        "requested_model": MODEL,
        "returned_model": getattr(
            response,
            "model",
            None,
        ),
        "status": getattr(
            response,
            "status",
            None,
        ),
        "incomplete_details": (
            str(
                getattr(
                    response,
                    "incomplete_details",
                    None,
                )
            )
            if getattr(
                response,
                "incomplete_details",
                None,
            ) is not None
            else None
        ),
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }

    if getattr(response, "usage", None) is not None:
        usage_record["input_tokens"] = getattr(
            response.usage,
            "input_tokens",
            0,
        )

        usage_record["output_tokens"] = getattr(
            response.usage,
            "output_tokens",
            0,
        )

        usage_record["total_tokens"] = getattr(
            response.usage,
            "total_tokens",
            0,
        )

        input_details = getattr(
            response.usage,
            "input_tokens_details",
            None,
        )

        output_details = getattr(
            response.usage,
            "output_tokens_details",
            None,
        )

        usage_record["cached_input_tokens"] = (
            getattr(
                input_details,
                "cached_tokens",
                0,
            )
            if input_details is not None
            else 0
        )

        usage_record["reasoning_tokens"] = (
            getattr(
                output_details,
                "reasoning_tokens",
                0,
            )
            if output_details is not None
            else 0
        )

    return output_text, usage_record


# --------------------------------------------------
# STEP 1: SHARED ROUND-1 ANALYSES
# --------------------------------------------------

def generate_initial_analyses(
    source_text: str,
) -> tuple[dict[int, str], list[dict]]:
    outputs: dict[int, str] = {}
    usage_records = []

    print(
        "Step 1/6: Generating three shared "
        "independent analyses..."
    )

    for agent_id in [1, 2, 3]:
        print(f"  Running Agent {agent_id}...")

        output, usage = call_model(
            instructions=ROUND1_PROMPT,
            input_text=f"""
OFFICIAL SOURCE MATERIAL:

{source_text}
""".strip(),
            call_name=f"round1_agent_{agent_id}",
        )

        outputs[agent_id] = output
        usage_records.append(usage)

    return outputs, usage_records


# --------------------------------------------------
# IDENTICAL SYNTHESIZER FOR SETUPS 2, 3, AND 4
# --------------------------------------------------

def synthesize(
    source_text: str,
    outputs_by_agent: dict[int, str],
    presentation_order: list[int],
    call_name: str,
) -> tuple[str, dict]:

    candidate_outputs = format_candidate_outputs(
        outputs_by_agent,
        presentation_order,
    )

    return call_model(
        instructions=SYNTHESIS_PROMPT,
        input_text=f"""
OFFICIAL SOURCE MATERIAL:

{source_text}

CANDIDATE AGENT OUTPUTS:

{candidate_outputs}
""".strip(),
        call_name=call_name,
    )


# --------------------------------------------------
# STEP 3: NORMAL DEBATE REVISIONS
# --------------------------------------------------

def generate_normal_revisions(
    source_text: str,
    initial_outputs: dict[int, str],
    presentation_order: list[int],
) -> tuple[dict[int, str], list[dict]]:

    revisions: dict[int, str] = {}
    usage_records = []

    print(
        "Step 3/6: Generating three normal "
        "debate revisions..."
    )

    for agent_id in [1, 2, 3]:
        print(
            f"  Running normal reviewer "
            f"Agent {agent_id}..."
        )

        output, usage = call_model(
            instructions=NORMAL_REVIEW_PROMPT,
            input_text=reviewer_input(
                source_text,
                agent_id,
                initial_outputs,
                presentation_order,
            ),
            call_name=(
                f"normal_revision_agent_{agent_id}"
            ),
        )

        revisions[agent_id] = output
        usage_records.append(usage)

    return revisions, usage_records


# --------------------------------------------------
# STEP 5: SOURCE-GROUNDED CRITIC
# --------------------------------------------------

def generate_critic_output(
    source_text: str,
    initial_outputs: dict[int, str],
    presentation_order: list[int],
    critic_agent: int,
) -> tuple[str, dict]:

    print(
        "Step 5/6: Generating source-grounded "
        f"critic as Agent {critic_agent}..."
    )

    return call_model(
        instructions=CRITIC_PROMPT,
        input_text=reviewer_input(
            source_text,
            critic_agent,
            initial_outputs,
            presentation_order,
        ),
        call_name=f"critic_agent_{critic_agent}",
    )


# --------------------------------------------------
# MAIN TRIAL
# --------------------------------------------------

def main() -> None:

    if len(sys.argv) != 3:
        print("Usage:")
        print(
            "python src/run_four_setups.py M01 1"
        )
        sys.exit(1)

    measure_id = sys.argv[1].upper()

    try:
        trial_number = int(sys.argv[2])
    except ValueError:
        print(
            "Trial number must be a whole number."
        )
        sys.exit(1)

    if trial_number < 1:
        print(
            "Trial number must be at least 1."
        )
        sys.exit(1)

    try:
        measure_number = parse_measure_number(
            measure_id
        )
    except ValueError as exc:
        print(exc)
        sys.exit(1)

    source_file = (
        ROOT
        / "data"
        / "source_documents"
        / f"{measure_id}.txt"
    )

    source_text = read_text(source_file)

    if len(source_text) < 200:
        raise ValueError(
            f"{measure_id}.txt is too short "
            "to be a valid source packet."
        )

    (
        presentation_order,
        critic_agent,
        single_agent,
    ) = get_trial_controls(
        measure_number,
        trial_number,
    )

    source_hash = sha256_text(source_text)

    started_at = datetime.now(
        timezone.utc
    )

    timestamp = started_at.strftime(
        "%Y%m%dT%H%M%SZ"
    )

    trial_id = (
        f"{measure_id}_trial"
        f"{trial_number:02d}_{timestamp}"
    )

    print()
    print("=" * 68)
    print(
        "CA-TRADEOFFBENCH FOUR-CONDITION TRIAL"
    )
    print("=" * 68)
    print(f"Run stage: {RUN_STAGE.upper()}")
    print(f"Measure: {measure_id}")
    print(f"Trial: {trial_number}")
    print(f"Model: {MODEL}")
    print(
        "Presentation order: "
        f"{presentation_order}"
    )
    print(
        "Single-agent identity: "
        f"Agent {single_agent}"
    )
    print(
        "Critic identity: "
        f"Agent {critic_agent}"
    )
    print("=" * 68)
    print()

    all_usage: list[dict] = []

    # --------------------------------------------------
    # SHARED ROUND 1
    # --------------------------------------------------

    initial_outputs, usage = (
        generate_initial_analyses(
            source_text
        )
    )

    all_usage.extend(usage)

    # --------------------------------------------------
    # SETUP 1 — SINGLE AGENT
    # --------------------------------------------------

    print(
        "Step 2/6: Assigning Setup 1 "
        f"from Agent {single_agent}..."
    )

    setup1_final = (
        initial_outputs[single_agent]
    )

    # --------------------------------------------------
    # SETUP 2 — INDEPENDENT ENSEMBLE
    # --------------------------------------------------

    print(
        "Step 2/6: Creating Setup 2 "
        "independent-ensemble synthesis..."
    )

    setup2_final, usage = synthesize(
        source_text=source_text,
        outputs_by_agent=initial_outputs,
        presentation_order=presentation_order,
        call_name=(
            "setup2_independent_synthesis"
        ),
    )

    all_usage.append(usage)

    # --------------------------------------------------
    # SETUP 3 — NORMAL DEBATE
    # --------------------------------------------------

    normal_revisions, usage = (
        generate_normal_revisions(
            source_text,
            initial_outputs,
            presentation_order,
        )
    )

    all_usage.extend(usage)

    print(
        "Step 4/6: Creating Setup 3 "
        "normal-debate synthesis..."
    )

    setup3_final, usage = synthesize(
        source_text=source_text,
        outputs_by_agent=normal_revisions,
        presentation_order=presentation_order,
        call_name="setup3_debate_synthesis",
    )

    all_usage.append(usage)

    # --------------------------------------------------
    # SETUP 4 — CRITIC DEBATE
    # --------------------------------------------------

    critic_output, usage = (
        generate_critic_output(
            source_text,
            initial_outputs,
            presentation_order,
            critic_agent,
        )
    )

    all_usage.append(usage)

    critic_branch_outputs = dict(
        normal_revisions
    )

    critic_branch_outputs[
        critic_agent
    ] = critic_output

    print(
        "Step 6/6: Creating Setup 4 "
        "critic-debate synthesis..."
    )

    setup4_final, usage = synthesize(
        source_text=source_text,
        outputs_by_agent=critic_branch_outputs,
        presentation_order=presentation_order,
        call_name="setup4_critic_synthesis",
    )

    all_usage.append(usage)

    finished_at = datetime.now(
        timezone.utc
    )

    # --------------------------------------------------
    # RECORD WHICH CALLS BELONG TO EACH ARCHITECTURE
    # --------------------------------------------------

    logical_condition_calls = {
        "setup1_single": [
            f"round1_agent_{single_agent}",
        ],

        "setup2_independent": [
            "round1_agent_1",
            "round1_agent_2",
            "round1_agent_3",
            "setup2_independent_synthesis",
        ],

        "setup3_debate": [
            "round1_agent_1",
            "round1_agent_2",
            "round1_agent_3",
            "normal_revision_agent_1",
            "normal_revision_agent_2",
            "normal_revision_agent_3",
            "setup3_debate_synthesis",
        ],

        "setup4_critic": [
            "round1_agent_1",
            "round1_agent_2",
            "round1_agent_3",

            *[
                (
                    "normal_revision_agent_"
                    f"{agent_id}"
                )
                for agent_id in [1, 2, 3]
                if agent_id != critic_agent
            ],

            f"critic_agent_{critic_agent}",
            "setup4_critic_synthesis",
        ],
    }

    # --------------------------------------------------
    # FINAL OUTPUTS
    # --------------------------------------------------

    final_outputs = {
        "setup1_single": setup1_final,
        "setup2_independent": setup2_final,
        "setup3_debate": setup3_final,
        "setup4_critic": setup4_final,
    }

    final_word_counts = {
        name: word_count(text)
        for name, text
        in final_outputs.items()
    }

    # --------------------------------------------------
    # MASTER RECORD
    # --------------------------------------------------

    master_record = {
        "trial_id": trial_id,
        "run_stage": RUN_STAGE,
        "measure_id": measure_id,
        "measure_number": measure_number,
        "trial_number": trial_number,
        "requested_model": MODEL,

        "started_at": (
            started_at.isoformat()
        ),

        "finished_at": (
            finished_at.isoformat()
        ),

        "source": {
            "file": str(source_file),
            "sha256": source_hash,
            "word_count": (
                word_count(source_text)
            ),
        },

        "protocol": {
            "protocol_file": str(
                ROOT
                / "paper"
                / "protocol_v1_1.md"
            ),
            "prompt_version": "v1_0",
            "prompt_hashes": (
                PROMPT_HASHES
            ),
            "prompts": PROMPTS,
        },

        "controls": {
            "presentation_order": (
                presentation_order
            ),

            "single_agent_identity": (
                single_agent
            ),

            "critic_agent_identity": (
                critic_agent
            ),

            (
                "shared_round1_across_"
                "setups_2_3_4"
            ): True,

            (
                "shared_normal_revisions_"
                "between_setups_3_4"
            ): [
                agent_id
                for agent_id
                in [1, 2, 3]
                if agent_id
                != critic_agent
            ],

            (
                "same_synthesis_prompt_"
                "for_setups_2_3_4"
            ): True,
        },

        "intermediate_outputs": {
            "round1_initial": {
                str(agent_id): text
                for agent_id, text
                in initial_outputs.items()
            },

            "normal_revisions": {
                str(agent_id): text
                for agent_id, text
                in normal_revisions.items()
            },

            "critic": {
                "agent_id": critic_agent,
                "output": critic_output,
            },
        },

        "final_outputs": final_outputs,

        "final_word_counts": (
            final_word_counts
        ),

        "logical_condition_calls": (
            logical_condition_calls
        ),

        "actual_api_calls": all_usage,

        "actual_trial_token_totals": (
            token_totals(all_usage)
        ),

        "api_parameters": {
            "reasoning_mode": (
                REASONING_MODE
            ),

            "reasoning_effort": (
                REASONING_EFFORT
            ),

            "text_verbosity": (
                TEXT_VERBOSITY
            ),

            "max_output_tokens": (
                MAX_OUTPUT_TOKENS
            ),

            "temperature": (
                "not explicitly set"
            ),
        },
    }

    # --------------------------------------------------
    # SAVE MASTER FILE
    # --------------------------------------------------

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    master_file = (
        OUTPUT_DIR
        / f"{trial_id}_complete.json"
    )

    master_file.write_text(
        json.dumps(
            master_record,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # --------------------------------------------------
    # SAVE SMALL CONDITION FILES
    # --------------------------------------------------

    for (
        condition_name,
        final_text,
    ) in final_outputs.items():

        condition_record = {
            "trial_id": trial_id,
            "run_stage": RUN_STAGE,
            "measure_id": measure_id,
            "trial_number": trial_number,
            "condition": condition_name,
            "requested_model": MODEL,
            "source_sha256": source_hash,
            "prompt_version": "v1_0",

            "presentation_order": (
                presentation_order
            ),

            "single_agent_identity": (
                single_agent
            ),

            "critic_agent_identity": (
                critic_agent
            ),

            "final_output": final_text,

            "final_word_count": (
                final_word_counts[
                    condition_name
                ]
            ),

            "logical_call_names": (
                logical_condition_calls[
                    condition_name
                ]
            ),
        }

        condition_file = (
            OUTPUT_DIR
            / (
                f"{trial_id}_"
                f"{condition_name}.json"
            )
        )

        condition_file.write_text(
            json.dumps(
                condition_record,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    # --------------------------------------------------
    # FINISH
    # --------------------------------------------------

    print()
    print("=" * 68)
    print("TRIAL COMPLETE")
    print("=" * 68)

    for (
        name,
        count,
    ) in final_word_counts.items():
        print(
            f"{name}: {count} words"
        )

    totals = token_totals(all_usage)

    print()
    print(
        "Actual API tokens used in "
        "this paired trial: "
        f"{totals['total_tokens']}"
    )

    print(
        f"Master record: {master_file}"
    )

    print()

    print(
        "Do not run another trial until "
        "this one is inspected."
    )


if __name__ == "__main__":
    main()
