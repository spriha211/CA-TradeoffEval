# Reproducing the analysis

Run commands from the repository root.

## Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

## Validation

```bash
PYTHONPATH="$PWD" python -m pytest -q tests/
```

## Study 1

Relevant materials are in `protocols/study1/`, `evaluation_inventory/study1/`, `src/scoring/`, `src/analysis/`, and `results/post_lock_analysis/`.

## Study 2

Relevant materials are in `protocols/study2/`, `src/cross_model_replication/`, `results/study2/`, and `runs/audits/cross_model_replication/`.

The original audit and result paths are intentionally preserved where reproducibility tests or frozen hashes depend on them.
