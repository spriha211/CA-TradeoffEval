# CA-TradeoffBench Reference Inventory Construction Guide v1.0

## 1. Purpose

This guide defines how reference inventories for CA-TradeoffBench are
constructed from official policy source material.

Its purpose is to make benchmark construction systematic across measures and
reduce researcher discretion, cherry-picking, inconsistent coverage, and
post-hoc addition of claims based on model outputs.

For confirmatory measures, the reference inventory and atomic components must
be completed and frozen before experimental model outputs for that measure are
evaluated.


## 2. Source Requirement

Every reference claim must be supported by the official source packet used in
the experiment.

Each claim must record:

- claim ID
- category
- reference claim
- exact or directly supporting source text
- source document
- source page
- source section
- importance note

Outside knowledge must not be used to create reference claims.

Campaign arguments, news coverage, advocacy materials, or researcher opinions
must not be added unless they are themselves part of the predefined official
source packet.


## 3. Core Inclusion Test

A high-level reference claim should be included when all of the following are
true:

1. It is explicitly supported by the supplied official source.
2. It represents substantively meaningful policy information.
3. Omitting or materially distorting it would make an analysis meaningfully
   less complete or less accurate.
4. It is independently meaningful rather than a trivial wording detail.
5. It is not merely duplicative of another reference claim.

Claims should capture the important informational structure of the policy,
not every sentence in the source.


## 4. Eligible Types of Reference Claims

Relevant claims may include the following categories when present in the
source:

### Policy changes
What the measure creates, removes, changes, requires, prohibits, extends,
makes permanent, or otherwise alters.

### Intended benefits or funding purposes
Source-supported intended uses, benefits, services, or programs affected by
the policy.

### Fiscal effects
Changes in government revenue, spending, funding, costs, or budgetary
arrangements.

### Fiscal costs
Important costs or increased government obligations created by the measure.

### Baseline or fiscal context
Existing conditions needed to correctly interpret the measure's effects,
including current spending, revenue, already-scheduled changes, or existing
uses of funds.

Baseline information should be included only when it materially affects how a
reader interprets the policy effect.

### Affected groups
People, populations, providers, institutions, or other groups directly
identified by the source as affected or served.

### Distributional or allocation effects
Changes in which groups, programs, providers, services, or purposes receive
resources or benefits.

### Implementation conditions
Requirements or dependencies that must occur for the policy to operate as
described, including federal approval, future rulemaking, revenue thresholds,
or other explicit conditions.

### Risks, limitations, or constraints
Important source-grounded limitations on implementation or effects.

### Explicit uncertainty
Effects that the official source explicitly describes as unknown, uncertain,
conditional, dependent on future decisions, or otherwise indeterminate.

### Accountability or administrative safeguards
Audits, spending restrictions, administrative caps, reporting requirements,
oversight rules, or similar source-grounded controls.

The categories above are a coverage checklist, not a requirement that every
measure contain every category.


## 5. Baseline and Context Rule

Background facts should NOT automatically become reference claims.

Include a baseline or context claim only when it meets at least one of these
conditions:

1. It is necessary to interpret the magnitude of a policy effect.
2. It explains the mechanism producing a major policy effect.
3. It distinguishes the measure's incremental effect from changes already
   scheduled under current law.
4. It establishes an important counterfactual needed to understand what would
   occur without the measure.
5. It provides scale necessary to interpret an otherwise misleading number.

Example:

If a measure produces an additional $2–5 billion increase while approximately
$4 billion in increases are already scheduled under current law, the existing
$4 billion baseline may be necessary to interpret the incremental effect.

By contrast, an unrelated background statistic that does not change
interpretation of the measure should usually be excluded.


## 6. Affected-Groups Rule

Inventories should distinguish between different kinds of affected groups
when the source does so.

For example:

- beneficiaries or recipients
- providers
- institutions
- taxpayers
- agencies
- geographic groups

A provider list should not automatically substitute for a separately stated
beneficiary population when both are substantively important in the source.


## 7. Do Not Include Trivial Details

Exclude information that is technically present in the source but is unlikely
to materially affect the completeness or accuracy of a policy analysis.

Normally exclude:

- minor wording details
- document-navigation information
- website addresses
- formatting information
- repetitive restatements
- examples that add no distinct policy information
- names or labels that do not affect interpretation
- highly granular facts with little independent significance

The benchmark should measure policy-information preservation, not memorization
of every sentence.


## 8. Avoid Redundant Claims

Do not create several high-level claims that score essentially the same fact.

When closely related facts form one meaningful policy claim, place them under
one high-level claim and represent their distinct informational elements as
atomic components.

Example:

High-level claim:
The measure increases state costs by roughly $1–2 billion annually in
2025–26 because less tax revenue can offset existing Medi-Cal costs.

Possible atomic components:

- state costs increase
- magnitude is roughly $1–2 billion annually
- timeframe is 2025–26
- less tax revenue is available for existing Medi-Cal costs
- more General Fund support is therefore likely required


## 9. Atomic Component Construction

Each high-level claim must be decomposed into independently meaningful atomic
components.

Each component should answer one concrete yes/no preservation question.

Good components:

- State costs increase.
- The increase is roughly $1–2 billion annually.
- The relevant period is 2025–26.
- Federal approval remains required.

Bad components:

- "State"
- "Costs"
- "$1"
- "California"

Do not split language into fragments that have no independent policy meaning.


## 10. Component Granularity

Use the minimum number of atomic components necessary to represent the
meaningful informational structure of the claim.

Do not deliberately create more components for facts that seem especially
important.

Do not deliberately create fewer components for facts that seem less
important.

Component count should follow informational structure, not desired weighting.


## 11. Weighting

Atomic components are normalized within each high-level claim.

Claim Preservation Score =

    correctly preserved components
    ------------------------------
    applicable components in claim

Overall Trade-off Preservation Rate =

    mean of high-level claim preservation scores

Therefore, a claim with five components does not automatically count five
times as much as a claim with one component.

Each high-level reference claim receives equal weight in the primary
preservation metric.


## 12. Magnitude, Direction, Timeframe, and Mechanism

When a source-supported claim contains substantively distinct information
about:

- direction
- magnitude
- timeframe
- mechanism
- condition
- affected group

these should generally become separate atomic components when each element
could independently be preserved or lost.

Do not require an exact quotation.

Accurate paraphrases receive credit.


## 13. Qualifiers

Important qualifiers should receive their own component when removing the
qualifier would materially change interpretation.

Examples:

- "subject to federal approval"
- "approximately"
- "in 2025 and 2026"
- "depending on how much revenue is raised"
- "long-term effects are unknown"

Trivial linguistic qualifiers should not be separately scored.


## 14. Uncertainty

When the official source explicitly states uncertainty, the inventory should
preserve that uncertainty rather than convert it into a definite prediction.

Separate uncertainties may be represented separately when they concern
meaningfully different outcomes.

For example:

- future tax revenue is uncertain
- future health-program funding is uncertain
- future state costs are uncertain

may be separate components under one high-level uncertainty claim.


## 15. Counterfactual Information

Include a counterfactual when the official source indicates that understanding
what could happen without the measure is necessary to interpret its effect.

Example:

If the Legislature could renew an existing tax even if a ballot measure does
not pass, that fact may be necessary to interpret the measure's incremental
long-term effect.


## 16. No Output-Informed Additions for Confirmatory Measures

For confirmatory measures M02–M11:

Do not inspect experimental model outputs and then add benchmark claims because
a model happened to mention them.

Do not remove benchmark claims because models consistently fail to preserve
them.

Do not change atomic scoring rules because a particular condition appears to
benefit or suffer.

Inventory construction must be based on the official source rather than model
behavior.


## 17. Development-Measure Exception

M01 is explicitly designated as a development/pilot measure.

Model outputs from M01 were inspected during benchmark development and exposed
coverage gaps in the original inventory.

M01 may therefore be used to:

- improve benchmark-construction procedures
- test scoring rules
- test annotation tools
- diagnose ceiling effects
- develop information-flow metrics

M01 is excluded from the primary confirmatory aggregate.


## 18. Confirmatory Measure Freeze Procedure

For every confirmatory measure M02–M11:

1. Create the official source packet.
2. Verify that the source packet contains no accidental duplicate material.
3. Construct the high-level reference inventory.
4. Add exact supporting source evidence.
5. Construct atomic components.
6. Verify every component maps to a valid high-level claim.
7. Review category coverage using this guide.
8. Check for unnecessary duplication or excessive granularity.
9. Record file hashes.
10. Freeze the inventory and components.
11. Only then begin experimental model runs for that measure.

Any post-freeze correction must be documented.


## 19. Coverage Audit Before Freezing

Before freezing an inventory, explicitly ask:

- What does the policy change?
- What major benefits or intended uses are stated?
- What major fiscal effects are stated?
- What costs are stated?
- What existing baseline is necessary to interpret those effects?
- Who benefits or is affected?
- Are providers and beneficiaries distinct?
- Does resource allocation change?
- Are there implementation conditions?
- Are there explicit uncertainties?
- Are there important counterfactuals?
- Are there administrative, accountability, or spending restrictions?
- Is there any major source-supported consideration whose omission would make
  an analysis materially incomplete?

The goal is not to force every category into every benchmark.

The goal is to make sure an important category is not omitted merely because
the researcher forgot to look for it.


## 20. Final Principle

The inventory should be comprehensive enough to represent the important
source-grounded structure of the policy while remaining selective enough that
it measures meaningful policy information rather than exhaustive sentence
recall.

Benchmark completeness and benchmark restraint are both required.
