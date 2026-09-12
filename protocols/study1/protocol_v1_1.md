CA-TRADEOFFBENCH EXPERIMENTAL PROTOCOL v1.0

PRIMARY RESEARCH QUESTION

How does the structure of LLM deliberation affect preservation of
source-grounded policy trade-offs, and can structured dissent reduce
information loss without increasing unsupported claims?


PRIMARY EXPERIMENTAL UNIT

One trial consists of one policy source packet analyzed under four
deliberation conditions.


CONDITION 1 — SINGLE AGENT

One independently generated AI analysis is used as the final response.

Purpose:
Establish baseline policy-information preservation from one model call.


CONDITION 2 — INDEPENDENT ENSEMBLE

Three agents independently analyze the same source.

They do not see one another's responses.

The three independent analyses are provided to a synthesizer that produces
one final response.

Purpose:
Measure the benefit of multiple independent generations without interaction.


CONDITION 3 — NORMAL DEBATE

The same three independent initial analyses used in Condition 2 are reused.

Each agent sees the three initial responses and produces a revised analysis
using a neutral review prompt.

A synthesizer receives the three revised analyses and produces the final
response.

Purpose:
Measure the effect of communication beyond independent sampling.


CONDITION 4 — SOURCE-GROUNDED CRITIC DEBATE

The same initial analyses from Conditions 2 and 3 are reused.

Two agents use their same normal-debate revisions from Condition 3.

One agent is replaced by a source-grounded adversarial critic.

The critic may identify only omissions, distortions, qualifications,
trade-offs, affected groups, risks, or uncertainties explicitly supported
by the supplied source.

The critic may not introduce outside knowledge or hypothetical risks.

A synthesizer produces the final response.

Purpose:
Measure the effect of structured dissent relative to ordinary debate.


PAIRED DESIGN

Conditions 2, 3, and 4 share the exact same three Round-1 generations
within a trial.

Conditions 3 and 4 share the exact same normal reviewer outputs except
for the reviewer replaced by the critic.

This reduces random-generation differences between conditions.


POSITION CONTROL

The order in which agent outputs are presented will be counterbalanced
across trials.

Within a trial, the same presentation order will be used across matched
conditions.

Presentation order will be saved in the run metadata.

The critic will not always occupy the same prompt position.


CRITIC IDENTITY CONTROL

The agent assigned to the critic role will rotate across repeated trials
rather than always being Agent 3.

The corresponding normal review from that same agent will be used in the
normal-debate comparison.


OUTPUT-LENGTH CONTROL

All final-condition outputs will use the same target maximum word count.

Intermediate analysis and reviewer outputs will also use fixed maximum
word-count instructions.

Actual word counts will be recorded.


SOURCE CONTROL

All agents within a trial receive the same official source packet.

Source packets will contain official material only.

Information will not be duplicated simply to highlight uncertainty or
other scoring categories.

A hash of the source packet will be recorded with each run.


MODEL CONTROL

The primary experiment will use the same underlying model for every
condition.

Model identity and API settings will be logged.

Repeated trials will measure generation variability.


SYNTHESIS CONTROL

Conditions 2, 3, and 4 use the same synthesis prompt and output limit.

The synthesis prompt will not reveal the benchmark's scoring categories.


REFERENCE INVENTORY

Each policy measure receives a human-created source-grounded reference
inventory before final experimental outputs are evaluated.

Every reference claim must include exact supporting source evidence.


ATOMIC COMPONENT SCORING

Each complex reference claim is decomposed into essential atomic
information components.

Each component receives:

1 = correctly preserved
0 = missing, contradicted, or materially incorrect

Item preservation score =
correctly preserved components / applicable components


PRIMARY OUTCOME

Trade-off Preservation Rate =
correctly preserved atomic components /
total applicable atomic components


SECONDARY OUTCOMES

1. Category-level preservation
2. Unsupported claims
3. Distortions
4. Uncertainty preservation
5. Final word count
6. Token usage
7. Approximate API cost


INFORMATION-FLOW OUTCOMES

Initial Discovery:
Whether at least one independent Round-1 agent contains a reference
component.

Debate Retention:
Whether a component present initially survives normal agent revision.

Debate Loss:
Whether a component present initially disappears after normal revision.

Critic Recovery:
Whether the source-grounded critic identifies an important component
missing or weakened in ordinary deliberation.

Synthesizer Uptake:
Whether a component identified by the critic survives into the final
critic-condition synthesis.


ANNOTATION CONTROLS

Final outputs will be anonymized before primary scoring so the annotator
does not know the condition.

A second annotator will independently score a predefined subset.

Inter-rater agreement will be reported.

A stricter binary complete-claim robustness analysis may also be conducted.


CORE SCALE

Target:
10 policy measures
4 conditions
4 repeated trials

Total:
160 final-condition outputs


STRETCH SCALE

If the core experiment is completed with sufficient time:

10 measures
4 conditions
5 trials

= 200 final outputs

Additional stretch:
replicate a smaller predefined subset using a second model.


INTERPRETATION

A critic condition is not considered superior merely because it mentions
more information.

Preservation must be considered alongside unsupported claims, distortion,
output length, and computational cost.


MODEL PLAN

Primary confirmatory model:
- Provider: OpenAI
- Model: GPT-5.6 Sol
- API model ID: gpt-5.6-sol
- Reasoning mode: standard
- Reasoning effort: medium
- Text verbosity: medium
- Tools: none
- Web access: none
- Same model configuration across all four experimental conditions

GPT-5.6 Luna runs conducted before the confirmatory protocol was frozen are
engineering and pilot runs only. They will not be included in the primary
confirmatory dataset.

Cross-provider replication:
- Provider: Anthropic
- Model: Claude Opus 4.8
- API model ID: claude-opus-4-8

The Claude replication will use the same source packets, prompts, four
deliberation architectures, counterbalancing rules, scoring inventory, and
annotation methodology as the primary experiment.

Provider-specific inference settings will be held constant within each model
and fully recorded. The cross-provider replication will not be pooled with
the primary model as though both models used identical inference mechanisms.

Priority order:
1. Complete and validate the primary GPT-5.6 Sol study.
2. Conduct the predefined Claude Opus 4.8 cross-provider replication.
3. Additional models or repetitions are stretch analyses only.


DEVELOPMENT VS. CONFIRMATORY MEASURES

M01 (California Proposition 35) is designated as a development/pilot measure.

M01 was used to validate the experimental runner, source-grounded critic,
scoring methodology, and reference-inventory coverage.

Because M01 outputs were inspected during benchmark development and informed
subsequent refinements to the reference inventory and evaluation methodology,
M01 will not be included in the primary confirmatory aggregate.

The primary confirmatory experiment will instead use ten separate measures:

M02 through M11.

Reference inventories for M02-M11 will be constructed and frozen from the
official source material before experimental outputs for those measures are
evaluated.

Primary confirmatory scale:

10 measures
x 4 conditions
x 4 repeated trials
= 160 final outputs.


REFERENCE INVENTORY CONSTRUCTION

Reference inventories for confirmatory measures M02-M11 will be constructed
according to:

data/reference_inventories/INVENTORY_CONSTRUCTION_GUIDE.md

This guide defines source requirements, inclusion and exclusion criteria,
baseline/context inclusion, affected-group coverage, atomic decomposition,
weighting, uncertainty treatment, and the pre-output freeze procedure.

Inventories for confirmatory measures must be completed and frozen before
experimental outputs from those measures are evaluated.


CONFIRMATORY PROTOCOL REVISION — v1.1

M01 is designated as a development-only measure and is excluded from the
primary confirmatory aggregate.

The confirmatory study will use ten separate measures, designated M02-M11.

Reference inventories for confirmatory measures must be constructed according
to:

data/reference_inventories/INVENTORY_CONSTRUCTION_GUIDE.md

Primary annotation must use:

data/reference_inventories/SCORING_GUIDE.md

The active scoring guide is version 1.1 and includes:

- binary atomic-component scoring
- equal weighting across high-level claims
- semantic-equivalence and paraphrase rules
- entity-level precision
- explicitness requirements
- local-context rules
- magnitude and timeframe paraphrase rules
- material-qualification rules
- separate distortion scoring
- separate unsupported-claim scoring
- unsupported claims per 1,000 words
- blind confirmatory annotation
- second-annotator validation
- inter-rater agreement

PRIMARY EXPERIMENTAL CONDITIONS

1. Single agent
2. Independent ensemble
3. Normal simulated debate
4. Debate with a source-grounded critic

PAIRING

Conditions 2-4 reuse the same three initial independent analyses within each
trial.

Conditions 3 and 4 reuse the same two non-critic normal revisions.

Only the designated critic branch differs between Conditions 3 and 4.

COUNTERBALANCING

Presentation order is predefined and systematically counterbalanced.

Critic identity is rotated.

Single-agent identity is rotated.

Within a matched trial, presentation order is held constant across applicable
conditions.

PRIMARY MODEL

Provider: OpenAI
Model: gpt-5.6-sol
Reasoning mode: standard
Reasoning effort: medium
Text verbosity: medium
Tools: disabled
Web access: disabled

The same model configuration is used across all four conditions.

PRIMARY SCALE

10 confirmatory measures
x 4 repeated trials
x 4 final conditions
= 160 confirmatory final outputs

PRIMARY PRESERVATION METRIC

Each atomic component is scored:

1 = correctly preserved
0 = absent, contradicted, materially incorrect, or insufficiently explicit

Each high-level claim is scored as:

correctly preserved atomic components
-------------------------------------
applicable atomic components

Overall Trade-off Preservation Rate is the mean of high-level claim scores,
giving each high-level claim equal weight.

SECONDARY OUTCOMES

- category-level preservation
- distortion
- unsupported claims
- unsupported claims per 1,000 words
- final word count
- token usage
- approximate API cost

INFORMATION-FLOW OUTCOMES

- initial discovery
- debate retention
- debate loss
- critic recovery
- synthesizer uptake

CONFIRMATORY FREEZE RULE

For every measure M02-M11:

1. Select the official source.
2. Create and clean the source packet.
3. Construct the high-level reference inventory.
4. Construct atomic components.
5. Perform the inventory coverage audit.
6. Verify all source citations and page numbers.
7. Freeze the source, inventory, and components.
8. Only then generate experimental model outputs.

No confirmatory reference claim may be added because a model output happened
to mention it.

No confirmatory reference claim may be removed because models consistently
fail to preserve it.

No scoring rule may be changed merely because one experimental condition
benefits or suffers from the existing rule.

M01 remains available only for development, annotation training, and pipeline
testing.


CONFIRMATORY MEASURE SELECTION

The confirmatory measure set is defined using a complete calendar-year
selection rule.

All California statewide propositions appearing during calendar year 2024 are
included except Proposition 35, which was previously designated as the M01
development measure.

This produces ten untouched confirmatory measures:

M02 — Proposition 1
M03 — Proposition 2
M04 — Proposition 3
M05 — Proposition 4
M06 — Proposition 5
M07 — Proposition 6
M08 — Proposition 32
M09 — Proposition 33
M10 — Proposition 34
M11 — Proposition 36

The measure set was frozen before confirmatory model generation.

See:

paper/measure_selection_v1_1.md
data/measure_manifest.csv
