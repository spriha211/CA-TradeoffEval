import csv
import hashlib
import json
import random
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_CONDITIONS = [
    "setup1_single",
    "setup2_independent",
    "setup3_debate",
    "setup4_critic",
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if len(sys.argv) != 2:
    raise SystemExit(
        "Usage: python src/create_blinded_scoring_packet.py MEASURE_ID\n"
        "Example: python src/create_blinded_scoring_packet.py M02"
    )

measure_id = sys.argv[1].strip().upper()

raw_dir = ROOT / "runs/raw"
blinded_dir = ROOT / "runs/blinded" / measure_id
scoring_dir = ROOT / "runs/scored" / f"{measure_id}_confirmatory"
private_dir = ROOT / "runs/scored/private_mappings"
audit_dir = ROOT / "runs/audits" / measure_id

components_path = (
    ROOT
    / "data/reference_inventories"
    / f"{measure_id}_components.csv"
)

private_mapping_path = (
    private_dir
    / f"{measure_id}_blind_mapping_private.json"
)

commitment_path = (
    audit_dir
    / f"{measure_id}_blind_mapping_commitment.txt"
)

scoring_path = (
    scoring_dir
    / f"{measure_id}_component_scoring_sheet.csv"
)

unsupported_path = (
    scoring_dir
    / f"{measure_id}_unsupported_claims_sheet.csv"
)

index_path = (
    scoring_dir
    / f"{measure_id}_blinded_output_index.csv"
)

instructions_path = (
    scoring_dir
    / f"{measure_id}_SCORING_INSTRUCTIONS.txt"
)

packet_manifest_path = (
    audit_dir
    / f"{measure_id}_blinded_packet_manifest.txt"
)


# ------------------------------------------------------------
# Refuse accidental overwrite
# ------------------------------------------------------------

existing_blinded = list(
    blinded_dir.glob(f"{measure_id}-B*.txt")
) if blinded_dir.exists() else []

protected_paths = [
    private_mapping_path,
    commitment_path,
    scoring_path,
    unsupported_path,
    index_path,
]

existing_protected = [
    path for path in protected_paths if path.exists()
]

if existing_blinded or existing_protected:
    print("STOP — a blinded packet already appears to exist.")

    for path in existing_blinded + existing_protected:
        print("Existing:", path.relative_to(ROOT))

    raise SystemExit(
        "Nothing was overwritten. Investigate the existing packet first."
    )


# ------------------------------------------------------------
# Create directories
# ------------------------------------------------------------

blinded_dir.mkdir(parents=True, exist_ok=True)
scoring_dir.mkdir(parents=True, exist_ok=True)
private_dir.mkdir(parents=True, exist_ok=True)
audit_dir.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------
# Load four completed trial masters
# ------------------------------------------------------------

items = []

for trial_number in range(1, 5):
    trial_tag = f"trial{trial_number:02d}"

    masters = sorted(
        raw_dir.glob(
            f"{measure_id}_{trial_tag}_*_complete.json"
        )
    )

    if len(masters) != 1:
        raise RuntimeError(
            f"Expected exactly one {measure_id} {trial_tag} "
            f"master file; found {len(masters)}."
        )

    master_path = masters[0]

    data = json.loads(
        master_path.read_text(encoding="utf-8")
    )

    assert data.get("run_stage") == "confirmatory"
    assert data.get("measure_id") == measure_id
    assert int(data.get("trial_number")) == trial_number

    final_outputs = data.get("final_outputs")

    if not isinstance(final_outputs, dict):
        raise RuntimeError(
            f"{master_path.name}: final_outputs is not a dictionary."
        )

    if set(final_outputs.keys()) != set(EXPECTED_CONDITIONS):
        raise RuntimeError(
            f"{master_path.name}: unexpected condition keys: "
            f"{sorted(final_outputs.keys())}"
        )

    word_counts = data.get("final_word_counts", {})

    for condition in EXPECTED_CONDITIONS:
        text = final_outputs[condition]

        if not isinstance(text, str):
            raise RuntimeError(
                f"{master_path.name} {condition}: output is not text."
            )

        text = text.strip()

        if not text:
            raise RuntimeError(
                f"{master_path.name} {condition}: output is empty."
            )

        items.append(
            {
                "trial_number": trial_number,
                "condition_key": condition,
                "master_file": str(
                    master_path.relative_to(ROOT)
                ),
                "master_file_sha256": sha256_file(master_path),
                "text": text,
                "logged_word_count": word_counts.get(condition),
                "calculated_word_count": len(text.split()),
                "source_output_sha256": sha256_bytes(
                    text.encode("utf-8")
                ),
            }
        )

assert len(items) == 16


# ------------------------------------------------------------
# Randomize reproducibly using a private seed
# ------------------------------------------------------------

seed = secrets.randbits(256)
rng = random.Random(seed)
rng.shuffle(items)

created_at = datetime.now(timezone.utc).isoformat()

mapping_entries = []


# ------------------------------------------------------------
# Write the blinded text files
# ------------------------------------------------------------

for index, item in enumerate(items, start=1):
    blind_id = f"{measure_id}-B{index:03d}"
    blinded_path = blinded_dir / f"{blind_id}.txt"

    blinded_bytes = (
        item["text"].rstrip() + "\n"
    ).encode("utf-8")

    blinded_path.write_bytes(blinded_bytes)

    mapping_entries.append(
        {
            "blind_id": blind_id,
            "blinded_file": str(
                blinded_path.relative_to(ROOT)
            ),
            "blinded_file_sha256": sha256_bytes(
                blinded_bytes
            ),
            "trial_number": item["trial_number"],
            "condition_key": item["condition_key"],
            "master_file": item["master_file"],
            "master_file_sha256": item[
                "master_file_sha256"
            ],
            "source_output_sha256": item[
                "source_output_sha256"
            ],
            "logged_word_count": item[
                "logged_word_count"
            ],
            "calculated_word_count": item[
                "calculated_word_count"
            ],
        }
    )


# ------------------------------------------------------------
# Write the private mapping
# ------------------------------------------------------------

private_mapping = {
    "schema_version": "1.0",
    "measure_id": measure_id,
    "created_at_utc": created_at,
    "randomization_method": (
        "Python random.Random initialized with a "
        "cryptographically generated 256-bit private seed"
    ),
    "private_seed_hex": format(seed, "064x"),
    "number_of_outputs": len(mapping_entries),
    "mapping": mapping_entries,
}

mapping_bytes = (
    json.dumps(
        private_mapping,
        indent=2,
        sort_keys=True,
    )
    + "\n"
).encode("utf-8")

private_mapping_path.write_bytes(mapping_bytes)

try:
    private_mapping_path.chmod(0o600)
except OSError:
    pass

mapping_commitment = sha256_bytes(mapping_bytes)


# ------------------------------------------------------------
# Write the public mapping commitment
# ------------------------------------------------------------

commitment_text = f"""CA-TRADEOFFBENCH BLIND-MAPPING COMMITMENT

Measure: {measure_id}
Created at UTC: {created_at}
Number of blinded outputs: {len(mapping_entries)}

Private mapping file:
runs/scored/private_mappings/{measure_id}_blind_mapping_private.json

SHA-256 commitment to the exact private mapping file:
{mapping_commitment}

Purpose:
This hash commits to the trial/condition-to-blind-ID mapping before
confirmatory scoring begins.

The private mapping must not be opened until the prespecified blinded
primary scoring is complete and locked.
"""

commitment_path.write_text(
    commitment_text,
    encoding="utf-8",
)


# ------------------------------------------------------------
# Load atomic components
# ------------------------------------------------------------

if not components_path.exists():
    raise RuntimeError(
        f"Missing component file: {components_path}"
    )

with components_path.open(
    newline="",
    encoding="utf-8",
) as f:
    reader = csv.DictReader(f)
    component_fields = reader.fieldnames or []
    components = list(reader)

required_component_fields = {
    "component_id",
    "claim_id",
    "category",
    "component_text",
    "binary_scoring_rule",
    "source_page",
    "source_section",
}

missing_fields = (
    required_component_fields
    - set(component_fields)
)

if missing_fields:
    raise RuntimeError(
        "Component file is missing columns: "
        + ", ".join(sorted(missing_fields))
    )

if measure_id == "M02":
    assert len(components) == 65, (
        f"Expected 65 M02 components; found {len(components)}."
    )

component_ids = [
    row["component_id"] for row in components
]

assert len(component_ids) == len(set(component_ids)), (
    "Duplicate component IDs were found."
)


# ------------------------------------------------------------
# Write blinded output index
# ------------------------------------------------------------

with index_path.open(
    "w",
    newline="",
    encoding="utf-8",
) as f:
    fields = [
        "blind_id",
        "blinded_file",
        "word_count",
        "scoring_status",
    ]

    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()

    for entry in mapping_entries:
        writer.writerow(
            {
                "blind_id": entry["blind_id"],
                "blinded_file": entry["blinded_file"],
                "word_count": entry[
                    "calculated_word_count"
                ],
                "scoring_status": "not_started",
            }
        )


# ------------------------------------------------------------
# Write 16 × component scoring rows
# ------------------------------------------------------------

scoring_fields = [
    "blind_id",
    "component_id",
    "claim_id",
    "category",
    "component_text",
    "binary_scoring_rule",
    "source_page",
    "source_section",
    "preservation_score_0_or_1",
    "distortion_score_0_1_or_2",
    "evidence_or_scoring_notes",
    "scorer_id",
    "scoring_date",
]

with scoring_path.open(
    "w",
    newline="",
    encoding="utf-8",
) as f:
    writer = csv.DictWriter(
        f,
        fieldnames=scoring_fields,
    )
    writer.writeheader()

    for entry in mapping_entries:
        for component in components:
            writer.writerow(
                {
                    "blind_id": entry["blind_id"],
                    "component_id": component[
                        "component_id"
                    ],
                    "claim_id": component["claim_id"],
                    "category": component["category"],
                    "component_text": component[
                        "component_text"
                    ],
                    "binary_scoring_rule": component[
                        "binary_scoring_rule"
                    ],
                    "source_page": component[
                        "source_page"
                    ],
                    "source_section": component[
                        "source_section"
                    ],
                    "preservation_score_0_or_1": "",
                    "distortion_score_0_1_or_2": "",
                    "evidence_or_scoring_notes": "",
                    "scorer_id": "",
                    "scoring_date": "",
                }
            )


# ------------------------------------------------------------
# Write unsupported-claims scoring sheet
# ------------------------------------------------------------

unsupported_fields = [
    "blind_id",
    "word_count",
    "unsupported_claim_count",
    "unsupported_claims_per_1000_words",
    "unsupported_claim_notes",
    "scorer_id",
    "scoring_date",
]

with unsupported_path.open(
    "w",
    newline="",
    encoding="utf-8",
) as f:
    writer = csv.DictWriter(
        f,
        fieldnames=unsupported_fields,
    )
    writer.writeheader()

    for entry in mapping_entries:
        writer.writerow(
            {
                "blind_id": entry["blind_id"],
                "word_count": entry[
                    "calculated_word_count"
                ],
                "unsupported_claim_count": "",
                "unsupported_claims_per_1000_words": "",
                "unsupported_claim_notes": "",
                "scorer_id": "",
                "scoring_date": "",
            }
        )


# ------------------------------------------------------------
# Write scoring instructions
# ------------------------------------------------------------

instructions = f"""CA-TRADEOFFBENCH {measure_id} BLINDED SCORING PACKET

CONTENTS

Blinded outputs:
runs/blinded/{measure_id}/{measure_id}-B001.txt
through
runs/blinded/{measure_id}/{measure_id}-B016.txt

Atomic component scoring:
runs/scored/{measure_id}_confirmatory/{measure_id}_component_scoring_sheet.csv

Unsupported-claim scoring:
runs/scored/{measure_id}_confirmatory/{measure_id}_unsupported_claims_sheet.csv

Output index:
runs/scored/{measure_id}_confirmatory/{measure_id}_blinded_output_index.csv


BLINDING RULE

Do not open:
runs/scored/private_mappings/{measure_id}_blind_mapping_private.json

Do not attempt to infer or reconstruct conditions while scoring.


PRESERVATION SCORING

For every component:

1 = the component is correctly and sufficiently preserved.

0 = the component is absent, contradicted, materially incorrect,
or too vague to preserve the required information.

Use semantic equivalence rather than exact wording.

A materially distorted component receives preservation score 0.


DISTORTION SCORING

0 = no distortion.

1 = minor imprecision that does not reverse or materially alter
the central claim.

2 = material distortion involving direction, magnitude, mechanism,
entity, timeframe, or a critical qualifier.


UNSUPPORTED CLAIMS

Count each substantive claim that is not supported by the supplied
official source.

Hedging does not automatically make unsupported speculation
source-grounded.

After entering the count, calculate:

unsupported claims per 1,000 words
= unsupported claim count / word count × 1,000


IMPORTANT

Score against the frozen {measure_id} source packet, component rubric,
and active scoring guide.

Do not change the reference inventory or component definitions based
on anything seen in these outputs.
"""

instructions_path.write_text(
    instructions,
    encoding="utf-8",
)


# ------------------------------------------------------------
# Create a public packet-integrity manifest
# ------------------------------------------------------------

public_packet_files = (
    sorted(blinded_dir.glob(f"{measure_id}-B*.txt"))
    + [
        scoring_path,
        unsupported_path,
        index_path,
        instructions_path,
        commitment_path,
    ]
)

manifest_lines = [
    "CA-TRADEOFFBENCH BLINDED PACKET MANIFEST",
    "",
    f"Measure: {measure_id}",
    f"Created at UTC: {created_at}",
    "",
    "SHA-256 hashes:",
]

for path in public_packet_files:
    manifest_lines.append(
        f"{sha256_file(path)}  {path.relative_to(ROOT)}"
    )

packet_manifest_path.write_text(
    "\n".join(manifest_lines) + "\n",
    encoding="utf-8",
)


# ------------------------------------------------------------
# Final safe summary
# ------------------------------------------------------------

expected_scoring_rows = (
    len(mapping_entries) * len(components)
)

print("========================================")
print(f"{measure_id} BLINDED SCORING PACKET CREATED")
print("========================================")
print("Blinded outputs:", len(mapping_entries))
print("Atomic components:", len(components))
print("Component scoring rows:", expected_scoring_rows)
print("Unsupported-claim rows:", len(mapping_entries))
print()
print(
    "Blinded output folder:",
    blinded_dir.relative_to(ROOT),
)
print(
    "Scoring folder:",
    scoring_dir.relative_to(ROOT),
)
print(
    "Private mapping:",
    private_mapping_path.relative_to(ROOT),
)
print(
    "Public commitment:",
    commitment_path.relative_to(ROOT),
)
print("Commitment SHA-256:", mapping_commitment)
print()
print("No substantive model-output text was displayed.")
print("DO NOT OPEN THE PRIVATE MAPPING BEFORE SCORING.")
