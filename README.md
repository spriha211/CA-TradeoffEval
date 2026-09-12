# CA-TradeoffEval

**Measuring information preservation in multi-agent LLM deliberation**

CA-TradeoffEval studies what happens to source-grounded information when multiple language-model agents analyze, revise, debate, and synthesize complex policy material.

## Research question

> When AI agents work together, what information survives the conversation?

The project compares four conditions:

1. **Single agent** - one independent analysis.
2. **Independent ensemble** - three independent analyses combined by a synthesizer, with no debate.
3. **Normal debate** - agents see the other initial analyses, revise, and are then synthesized.
4. **Source-grounded critic debate** - one revision role is replaced by a critic focused on missing, weakened, distorted, or unsupported source-grounded information.

## Study 1

Study 1 used GPT-5.6 Sol across 10 California statewide ballot measures, with four paired trials per measure-condition.

The frozen evaluation inventory contained 120 high-level claims and 367 atomic components, producing 5,872 component-level scoring rows.

Mean claim-weighted preservation:

- Single agent: 0.8803
- Independent ensemble: 0.8929
- Normal debate: 0.8902
- Source-grounded critic debate: 0.9214

The critic condition exceeded normal debate by 3.13 percentage points, with a 95% measure-level bootstrap interval of [0.53, 6.34] percentage points.

## Study 2

A post-confirmatory cross-model replication used Claude Sonnet 5 on five deterministically selected measures: M03, M08, M02, M09, and M05.

The critic-minus-normal preservation estimate was +2.62 percentage points. The interval was wider and included zero, and critic debate also increased distortion in this replication.

## Repository contents

- `paper/` - accompanying preprint
- `protocols/` - frozen Study 1 and Study 2 protocols and audit manifests
- `prompts/` - experimental prompts
- `evaluation_inventory/` - scoring guide and frozen component inventories
- `src/` - generation, scoring, analysis, and replication code
- `results/` - post-lock result tables and summaries
- `figures/` - paper and analysis figures
- `tests/` - reproducibility tests

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

## Tests

```bash
PYTHONPATH="$PWD" python -m pytest -q tests/
```

## Paper

**When AI Agents Talk, What Information Gets Lost? A controlled study of independent analysis, debate, and source-grounded criticism**

DOI: `10.5281/zenodo.22715133`

## Public-release boundary

API credentials, private blinded-condition mappings, billing/account information, local debugging artifacts, and private provider logs are intentionally excluded.

## License

Original software in this repository is released under the MIT License. Third-party source materials are not covered unless explicitly stated.

## Repository

https://github.com/spriha211/CA-TradeoffEval
