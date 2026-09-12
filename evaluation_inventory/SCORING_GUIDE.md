# CA-TradeoffBench Scoring Guide v1.1

## 1. Purpose

CA-TradeoffBench measures how well different LLM deliberation structures
preserve important, source-grounded policy information.

The evaluation is not intended to determine whether a model supports or
opposes a policy.

The primary question is whether information contained in the official
source survives into model outputs accurately and without unsupported
additions.


## 2. Reference Claims and Atomic Components

Each policy measure has two evaluation files:

1. A high-level reference inventory containing important policy claims.
2. An atomic-component inventory that decomposes each reference claim into
   smaller independently scorable pieces of information.

Each atomic component must be supported by the official source material.

Atomic components should represent independently meaningful pieces of
information rather than isolated words or trivial fragments.


## 3. Atomic Component Scoring

Each atomic component receives a binary preservation score:

1 = correctly preserved

0 = absent, contradicted, materially incorrect, or too vague to establish
    preservation of the component

Annotators should follow the component-specific binary_scoring_rule whenever
available.


## 4. Claim-Level Preservation

Each high-level claim may contain a different number of atomic components.

To prevent claims with more components from receiving more weight solely
because they contain more subcomponents, atomic scores are first normalized
within each claim.

Claim Preservation Score =

    number of correctly preserved components
    ------------------------------------------------
    total applicable components within that claim

Example:

A claim has four atomic components.

If three are correctly preserved:

    Claim Preservation Score = 3 / 4 = 0.75


## 5. Overall Trade-off Preservation Rate

Each high-level reference claim receives equal weight.

Overall Trade-off Preservation Rate =

    mean of all claim-level preservation scores

This means a claim containing ten atomic components does not automatically
count five times as much as a claim containing two components.


## 6. Category-Level Preservation

Claims are grouped into policy-information categories such as:

- intended benefit
- fiscal effect
- fiscal cost
- affected groups
- implementation risk
- distributional concern
- explicit uncertainty

Category-level preservation is calculated as the mean claim-level
preservation score for claims belonging to that category.


## 7. Distortion Scoring

Preservation and distortion are evaluated separately.

A model may mention a topic while presenting it inaccurately.

Distortion coding:

0 = no meaningful distortion

1 = minor distortion or imprecision that does not reverse the central claim

2 = material distortion, contradiction, incorrect direction, incorrect
    magnitude, incorrect mechanism, or removal of a critical qualification

A materially distorted atomic component receives a preservation score of 0.


## 8. Unsupported Claims

Unsupported claims are counted separately from preservation.

An unsupported claim is a substantive factual assertion, causal claim,
stakeholder effect, policy consequence, risk, or benefit that:

1. is not supported by the supplied source material, and
2. is introduced by the model as part of its policy analysis.

Reasonable paraphrases of source-supported content are not unsupported claims.

Hedging does not automatically make a claim source-grounded.

A speculative consequence such as "X could increase costs" still counts as
unsupported if the supplied source provides no support for that consequence.

However, a statement that merely identifies the limits of the source, such as
"The source does not discuss effects on X," is not itself an unsupported claim
because it does not assert that the effect occurs.

For every final output record:

- unsupported_claim_count
- unsupported_claims_per_1000_words
- brief description/evidence for each unsupported claim

The normalized rate is calculated as:

    unsupported_claim_count / final_word_count * 1000

Both the raw count and length-normalized rate should be reported.


## 9. Output Length

Record the final word count for every condition.

Word count is treated as a potential confound because longer outputs may
preserve more information simply by containing more text.


## 10. Token Usage and Cost

Record:

- input tokens
- output tokens
- total tokens
- approximate API cost

for every experimental trial and condition.


## 11. Blind Annotation

Final outputs must be anonymized before primary scoring.

The annotator should not know whether an output came from:

- single-agent analysis
- independent ensemble
- normal debate
- critic-assisted debate

Condition identities are revealed only after primary scoring is completed.


## 12. Second Annotator

A second annotator will independently score a predefined subset of outputs.

The second annotator must:

- use the same source packet
- use the same atomic-component rubric
- not see the primary annotator's scores
- not see the experimental condition labels

A target of approximately 20% of final outputs should be independently
double-scored where feasible.


## 13. Inter-Rater Agreement

Agreement between annotators should be calculated for binary atomic-component
labels.

Report at minimum:

- percent agreement

Where appropriate, also calculate:

- Cohen's kappa

Disagreements should be examined to identify ambiguous scoring rules.

The original independent annotations should be preserved even if a later
adjudicated score is created.


## 14. Information-Flow Scoring

Atomic components are also tracked through intermediate stages of the
multi-agent pipeline.

For every atomic component, record whether it appears in:

- Agent 1 initial analysis
- Agent 2 initial analysis
- Agent 3 initial analysis
- Agent 1 normal revision
- Agent 2 normal revision
- Agent 3 normal revision
- critic output
- Setup 1 final output
- Setup 2 final output
- Setup 3 final output
- Setup 4 final output


## 15. Initial Discovery

A component is considered discovered if at least one independent Round-1
agent correctly preserves it.

Initial Discovery Indicator =

    max(A1_initial, A2_initial, A3_initial)

Discovery Rate =

    number of components discovered by at least one initial agent
    -------------------------------------------------------------
    total atomic components


## 16. Debate Retention

For components discovered during Round 1, evaluate whether they remain
present in the normal-debate revised-agent outputs.

Debate Retention Rate =

    initially discovered components preserved after normal revision
    ---------------------------------------------------------------
    initially discovered components


## 17. Debate Loss

A component is considered lost during debate when:

1. it was present in at least one Round-1 agent output, and
2. it is absent from all relevant normal revised-agent outputs.

Debate Loss Rate =

    initially discovered components lost after revision
    ----------------------------------------------------
    initially discovered components


## 18. Critic Recovery

The critic is evaluated only against source-grounded atomic components.

A component counts as critic recovery when:

1. the component was missing, weakened, or lost in ordinary deliberation,
2. the critic explicitly identifies the missing source-supported information.

Critic Recovery Rate =

    eligible missing/lost components recovered by critic
    -----------------------------------------------------
    eligible missing/lost components


## 19. Synthesizer Uptake

A critic may successfully recover information that the final synthesizer
later drops.

Synthesizer Uptake Rate =

    critic-recovered components preserved in Setup 4 final synthesis
    ---------------------------------------------------------------
    components recovered by critic

This distinguishes critic failure from aggregation/synthesis failure.


## 20. Information-Flow Interpretation

The information-flow analysis tracks the following sequence:

Source
→ Initial Discovery
→ Debate Retention or Loss
→ Critic Recovery
→ Synthesizer Uptake
→ Final Output

This allows the study to identify where policy information disappears or is
recovered rather than relying only on final-answer scores.


## 21. Robustness Check

A stricter binary complete-claim analysis may also be conducted.

For this robustness analysis:

1 = the complete high-level reference claim is substantively preserved

0 = the complete claim is not preserved

This analysis is separate from atomic-component scoring.

Its purpose is to test whether conclusions depend heavily on the finer-grained
component methodology.


## 22. Important Annotation Principle

Do not reward verbosity.

A response earns preservation credit only when the relevant source-grounded
information is actually preserved.

Do not infer that a model "understood" a component when the required
information is absent from the written output.

Do not penalize a response for failing to include outside knowledge that is
not part of the benchmark source.



## 23. Semantic Equivalence and Paraphrase Rule

Scoring is based on preservation of informational meaning rather than exact
word matching.

An output receives credit when different wording preserves the same
substantive entity, relationship, direction, magnitude, timeframe, mechanism,
condition, or qualification required by the atomic component.

Example:

Reference component:
"Additional General Fund support is likely required."

Acceptable paraphrase:
"The state would probably need to use more General Fund money."

These preserve the same substantive information.

A merely related concept does not receive credit when it changes, broadens,
or weakens the information required by the component.

Example:

Reference component:
"Behavioral health facilities receive specified funding increases."

Insufficient:
"Behavioral health is funded."

The second statement identifies a related policy area but does not clearly
preserve the relevant entity: behavioral health facilities.


## 24. Entity-Level Precision

When an atomic component specifically concerns a:

- beneficiary population
- provider
- institution
- service
- program
- agency
- funding source

the response must preserve the relevant type of entity.

A service description should not automatically receive credit for a provider
component.

A provider description should not automatically receive credit for a
beneficiary-population component.

A broad policy area should not automatically receive credit for a more
specific institution or program.


## 25. Explicitness Rule

Annotators should not infer missing information merely because it could be
logically reconstructed from other statements.

The required component must be stated directly enough that a reasonable
reader could recover the information from the written response itself.

Exact repetition of benchmark wording is not required.


## 26. Local Context Rule

Information may receive credit when its meaning is established clearly by the
immediately surrounding sentence or paragraph.

Example:

"Additional services become eligible beginning in 2027; community health
worker funding depends on tax revenue."

This may preserve the 2027 timing of community-health-worker eligibility when
the syntax clearly links the statements.

Annotators should not combine distant or unrelated passages to construct an
unstated connection.


## 27. Magnitude Paraphrase Rule

Approximate numerical information receives credit when the response preserves
the source-supported magnitude without materially changing its meaning.

Examples:

Reference:
"roughly $2 billion to $5 billion annually"

Acceptable:
"about $2–5 billion per year"

Not acceptable:
"several billion dollars annually"

when the atomic component specifically requires preservation of the numerical
range.


## 28. Timeframe Paraphrase Rule

A timeframe receives credit when it is stated explicitly or through an
unambiguous equivalent phrase.

Example:

Reference:
"2025 and 2026"

Acceptable:
"during the 2025–26 period"

Potentially insufficient:
"in the short term"

unless the surrounding context has already explicitly defined the short-term
period as 2025 and 2026.


## 29. Material Qualification Rule

A response does not receive full preservation credit when it removes a
qualification that materially changes the meaning of the source-supported
claim.

Examples of potentially material qualifications include:

- subject to federal approval
- approximately
- beginning in 2027
- depending on revenue raised
- relative to current law
- long-term effects are unknown

Whether a qualification receives a separate atomic component depends on the
predefined inventory, but a response must not contradict or erase a material
qualification while receiving credit for the associated component.


## 30. Development Ambiguity Procedure

During development, components that repeatedly produce reasonable scoring
disagreement should be flagged and clarified before confirmatory annotation.

For confirmatory measures, scoring rules must not be rewritten merely because
a particular experimental condition benefits or suffers from the existing
rule.

Any necessary post-freeze correction must:

1. be documented,
2. preserve the original annotations,
3. produce a corrected annotation set separately, and
4. include a robustness analysis using both interpretations when relevant.
