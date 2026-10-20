# Research Manager Domain Specification

**Scope:** Research subsystem inside Sharons  
**Company-level orchestrator:** Chief of Staff  
**Domain orchestrator:** Research Manager

This document preserves the detailed research requirements. It is a domain specification, not the repository-root instruction file. Where it conflicts with the root `AGENTS.md`, the root architecture, authorization, privacy and approval rules prevail.

# AI Research Organization
## Domain Orchestrator: Research Manager

---

# 1. Purpose

This project implements an AI-native research organization.

The primary purpose is to conduct rigorous, transparent, reproducible research workflows rather than provide quick answers.

The initial target domain is medical and scientific research, but the architecture must remain extensible to other domains.

The system must support:

- research question formulation;
- research planning;
- source discovery;
- evidence collection;
- evidence quality assessment;
- contradiction analysis;
- hypothesis generation;
- cross-domain reasoning;
- branching research;
- stopping decisions;
- confidence tracking;
- specialist-agent proposals;
- final structured reporting.

The system must distinguish rigorously between:

- direct evidence;
- indirect evidence;
- inference;
- hypothesis;
- speculation;
- unknowns.

The system must not optimize for producing an answer.

It must optimize for producing the best-supported current representation of reality.

---

# 2. Core Design Principle

The Research Manager is not a single monolithic prompt.

It is an orchestrator that coordinates several specialized roles.

Default architecture inside Sharons:

```mermaid
flowchart TD
    CEO["Human Owner"] --> COS["Chief of Staff"]
    COS --> RM["Research Manager"]
    RM --> PLAN["Planner node"]
    PLAN --> EXEC["Executor and Evidence nodes"]
    EXEC --> REVIEW["Critic and Synthesizer nodes"]
    REVIEW --> SUP["Research Supervisor"]
    SUP --> REPORT["Verified Research Result"]
    SUP -->|"Approval or scope change"| COS
```

The Research Supervisor may redirect the workflow before finalization.

Roles may initially be implemented as workflow nodes rather than separate persistent agents.

Only promote a role into a separate agent when:

- it requires different tools;
- it needs independent memory;
- it uses a different model;
- it becomes computationally expensive;
- it needs independent scheduling;
- it requires different permissions;
- it repeatedly performs a stable reusable function.

---

# 3. Logical Components and Repository Placement

The research subsystem requires these logical components:

- manager and workflow nodes;
- persistent research state;
- branching, stopping and escalation policies;
- structured schemas for questions, studies, claims, hypotheses and reports;
- adapters for search, literature, citation, full text and statistics;
- source registry, evidence store, research memory and confidence service;
- API endpoints and tests.

These are logical boundaries, not permission to create a separate FastAPI project or a second source of truth. Codex must map them into the new Sharons/Django repository after Phase 0 design. Research state belongs to Sharons; product source code and product data remain in their independent repositories and systems. Do not create duplicate organizational persistence or bypass Sharons governance.

---

# 4. Research Manager

## Mission

The Research Manager owns the research process.

It receives:

- raw idea;
- observation;
- research question;
- scientific hypothesis;
- user concern;
- research objective.

It must convert that input into a structured research program.

The Research Manager must:

1. understand the objective;
2. identify ambiguity;
3. invoke planning;
4. authorize research branches;
5. supervise evidence collection;
6. request criticism;
7. track uncertainty;
8. decide when research is sufficient;
9. produce a transparent report;
10. escalate decisions that require human approval.

The Research Manager must never silently modify the user's original research objective.

---

# 5. Research Planner

## Mission

Design the research strategy before deep evidence collection.

## Responsibilities

The Planner must produce:

- primary research question;
- secondary questions;
- possible PICO formulation when applicable;
- hypotheses;
- alternative hypotheses;
- possible mechanisms;
- confounders;
- adjacent fields;
- search domains;
- source priorities;
- inclusion criteria;
- exclusion criteria;
- evidence quality criteria;
- branch candidates;
- stopping criteria.

## Planner Output

The Planner returns a ResearchPlan object.

Example:

```json
{
  "primary_question": "Does X affect Y?",
  "secondary_questions": [
    "What direct clinical evidence exists?",
    "What biological mechanisms could connect X and Y?",
    "Are there safety concerns?"
  ],
  "hypotheses": [
    {
      "id": "H1",
      "statement": "X reduces Y through mechanism A"
    },
    {
      "id": "H2",
      "statement": "Observed association is explained by confounder B"
    }
  ],
  "search_domains": [
    "clinical trials",
    "systematic reviews",
    "mechanistic studies",
    "epidemiology"
  ],
  "stop_policy": {
    "saturation_threshold": 3,
    "max_deep_branches": 3,
    "max_shallow_branches": 3
  }
}
```

---

# 6. Research Executor

## Mission

Execute the approved research plan.

## Responsibilities

The Executor must:

* generate search queries;
* search approved sources;
* collect candidate studies;
* record source coverage;
* remove duplicates;
* screen titles and abstracts;
* prioritize high-value evidence;
* retrieve full text when possible;
* record inaccessible sources;
* extract study metadata;
* identify references worth following;
* detect new research branches.

The Executor must never infer that inaccessible evidence does not exist.

---

# 7. Evidence Analyst

## Mission

Assess the methodological value of each material study.

## Required Study Fields

For every material study store:

```yaml
study_id:
citation:
authors:
year:
journal:
country:
study_type:
population:
sample_size:
intervention:
comparator:
duration:
primary_outcomes:
secondary_outcomes:
effect_size:
confidence_interval:
p_value:
clinical_significance:
statistical_significance:
randomization:
blinding:
attrition:
confounders:
risk_of_bias:
funding:
conflicts_of_interest:
replication_status:
directness:
major_limitations:
evidence_weight:
fulltext_available:
citation_verified:
```

Unknown values must be stored as:

UNKNOWN

Never fabricate missing data.

---

# 8. Evidence Hierarchy

Default medical evidence weighting:

1. high-quality systematic review / meta-analysis
2. high-quality randomized controlled trial
3. controlled clinical study
4. prospective cohort
5. retrospective cohort
6. case-control
7. cross-sectional
8. case series
9. case report
10. mechanistic human study
11. animal study
12. in-vitro study
13. expert opinion
14. theoretical reasoning

This hierarchy is contextual.

Methodological quality may override nominal category.

A weak meta-analysis must not automatically outrank a strong RCT.

---

# 9. Evidence Claim Model

Every important conclusion must be represented as a structured claim.

Schema:

```yaml
claim_id:
text:
claim_type:
status:

supporting_studies:
contradicting_studies:

direct_evidence_count:
indirect_evidence_count:

evidence_strength:
confidence_score:

assumptions:
unknowns:
alternative_explanations:

traceability:
  source_ids:

review_status:
```

Allowed claim_type values:

DIRECT_EVIDENCE
INDIRECT_EVIDENCE
INFERENCE
HYPOTHESIS
SPECULATION

Allowed evidence_strength values:

HIGH
MODERATE
LOW
VERY_LOW
INSUFFICIENT

Confidence score:

0 to 100

The confidence score is not a probability.

It is an internal communication score.

---

# 10. Direct vs Indirect Evidence

The system must distinguish direct evidence from chains of inference.

Example:

X -> Y

is direct only when a study directly evaluates X against Y.

The following:

X -> A
A -> B
B -> Y

is an indirect evidence chain.

The system may construct:

X -> A -> B -> Y

but must label it:

INDIRECT INFERENCE

or:

HYPOTHESIS

It must not present the chain as clinical proof.

---

# 11. Research Critic

## Mission

Attack the current interpretation.

The Critic must actively search for reasons the current conclusion may be wrong.

Required questions:

* Is there contradictory evidence?
* Are negative studies missing?
* Are observational results being interpreted causally?
* Is the sample size adequate?
* Is there publication bias?
* Is there selective reporting?
* Are surrogate endpoints being mistaken for meaningful outcomes?
* Are animal results being generalized to humans?
* Are mechanistic findings being presented as clinical evidence?
* Is a single study dominating the conclusion?
* Are industry-funded studies influencing the result?
* Are older studies inconsistent with newer studies?
* Are population differences being ignored?
* Are there retractions or major corrections?

The Critic must output:

```yaml
critical_issues:
counter_evidence:
alternative_explanations:
bias_risks:
confidence_reduction:
recommended_followup:
```

---

# 12. Evidence Synthesizer

## Mission

Integrate all evidence after criticism.

The Synthesizer must generate:

* agreement map;
* contradiction map;
* evidence hierarchy;
* direct evidence summary;
* indirect evidence summary;
* hypothesis map;
* uncertainty map;
* unresolved questions;
* confidence estimate;
* research gaps.

It must never smooth over disagreement.

---

# 13. Research Supervisor

## Mission

Control research direction, resource use, and stopping behavior.

The Supervisor does not primarily search literature.

It evaluates the research state.

After every substantial cycle it asks:

1. What do we currently believe?
2. Why?
3. What remains uncertain?
4. Which assumptions are weak?
5. What branches are available?
6. Which branch offers the highest expected information gain?
7. Is another search likely to materially change the conclusion?
8. Are we becoming repetitive?
9. Should we continue, redirect, expand, escalate, or stop?

Possible decisions:

CONTINUE_CURRENT_BRANCH
OPEN_NEW_BRANCH
DEEPEN_BRANCH
SHALLOW_EXPLORE
RETURN_TO_PLANNER
REQUEST_SPECIALIST
REQUEST_HUMAN_APPROVAL
STOP_RESEARCH

---

# 14. Research State

Use a persistent research state.

Suggested structure:

```python
class ResearchState:
    research_id: str

    original_user_request: str
    primary_question: str

    research_plan: dict

    active_hypotheses: list
    rejected_hypotheses: list

    candidate_branches: list
    active_branches: list
    completed_branches: list
    unexplored_branches: list

    discovered_sources: list
    screened_sources: list
    included_studies: list
    excluded_studies: list
    inaccessible_sources: list

    claims: list
    contradictions: list

    current_conclusion: str | None
    current_confidence: float

    unknowns: list
    assumptions: list

    iteration_count: int
    search_budget_used: float

    stopping_reason: str | None

    specialist_agent_proposals: list
```

---

# 15. Research Branch Schema

Each research branch must include:

```yaml
branch_id:
title:
description:

origin:
parent_branch_id:

hypothesis_ids:

priority_score:
expected_information_gain:
estimated_cost:
evidence_availability:

status:

sources_checked:
findings:
open_questions:

promotion_reason:
stop_reason:
```

Branch status values:

PROPOSED
ACTIVE
SHALLOW
DEEP
PAUSED
COMPLETED
REJECTED

---

# 16. Branching Policy

Default branch strategy:

* deeply investigate top 3 high-value branches;
* shallowly investigate next 3;
* keep remaining branches in backlog.

A branch may be promoted when:

* new evidence increases relevance;
* contradiction appears;
* expected information gain increases;
* safety concern emerges;
* direct evidence is missing but indirect evidence becomes strong.

Do not explore every branch.

Exploration must be resource-aware.

---

# 17. Search Strategy

Research must use an explicit search strategy.

Potential sources include:

* PubMed
* MEDLINE
* PubMed Central
* Cochrane Library
* ClinicalTrials.gov
* WHO resources
* NIH resources
* FDA publications
* EMA publications
* Google Scholar
* Crossref
* Semantic Scholar
* preprint servers
* major specialty journals
* citation networks
* reference lists

Actual use depends on available tools and permissions.

---

# 18. Search Coverage Record

Every research run must maintain:

```yaml
databases_searched:
sources_searched:
search_queries:
search_dates:
publication_years:
languages:

candidate_documents:
screened_documents:
fulltext_reviewed:
included_documents:
excluded_documents:

exclusion_reasons:

unavailable_databases:
paywalled_documents:
abstract_only_documents:
missing_supplements:
unavailable_datasets:
```

Never say:

"all research was reviewed"

unless provably true.

Preferred wording:

"Within the sources, date range, and search strategy described..."

---

# 19. Search Query Logging

Every substantial literature search must log:

* exact query;
* source;
* date;
* result count;
* filters;
* pagination or depth;
* relevant result IDs;
* reason query was modified.

Example:

```yaml
source: PubMed
query: "(fruit OR berries) AND influenza AND randomized"
date: 2026-09-09
results: 48
filters:
  humans: true
  years: "2000-2026"
notes: "Low direct evidence. Expanded to immune response."
```

---

# 20. Cross-Domain Search

The system may expand beyond the direct question.

Expansion may include:

* biological mechanisms;
* molecular pathways;
* metabolites;
* immune mechanisms;
* microbiome;
* pharmacology;
* nutrition;
* genetics;
* epidemiology;
* related diseases;
* analogous interventions;
* similar populations.

Cross-domain research exists primarily for hypothesis generation.

It must not inflate apparent evidence strength.

---

# 21. Hypothesis Schema

```yaml
hypothesis_id:
statement:

origin:
direct_evidence:
indirect_evidence:

supporting_claims:
contradicting_claims:

mechanistic_plausibility:
assumptions:
unknowns:

falsification_conditions:

proposed_test:
proposed_experiment:

confidence:
status:
```

Hypothesis status:

ACTIVE
WEAKENED
SUPPORTED
REJECTED
UNTESTED

---

# 22. Hypothesis Generation Rules

The system may generate new hypotheses.

Every hypothesis must include:

* supporting evidence;
* contradicting evidence;
* assumptions;
* unknowns;
* falsification criteria;
* suggested study;
* confidence.

Do not describe generated hypotheses as established findings.

---

# 23. Anti-Confirmation-Bias Policy

The original user hypothesis has no privileged status.

For every major hypothesis H investigate:

* H is true;
* H is false;
* H is partially true;
* H is conditional;
* another variable explains the result;
* the original observation is unreliable.

The Critic must explicitly attempt to falsify the leading hypothesis.

---

# 24. Stopping Policy

Research cannot continue indefinitely.

Possible stopping conditions:

EVIDENCE_SATURATION
LOW_MARGINAL_INFORMATION_GAIN
CONFIDENCE_STABILIZED
RESOURCE_LIMIT
LITERATURE_EXHAUSTED
DECISION_SUFFICIENT
HUMAN_STOP_REQUEST

A research run must store:

```yaml
stopping_reason:
stopping_evidence:
remaining_uncertainty:
unexplored_branches:
recommended_future_work:
```

---

# 25. Evidence Saturation

Evidence saturation may be declared when multiple consecutive searches:

* return mostly duplicate evidence;
* fail to identify new material findings;
* fail to alter claim confidence;
* fail to change research direction.

Default:

3 consecutive low-information cycles may trigger supervisor review.

This is configurable.

---

# 26. Continue-Research Triggers

Continue research when:

* contradictions remain unresolved;
* confidence remains low;
* a critical database is missing;
* a high-information branch appears;
* a safety concern emerges;
* the conclusion depends on one study;
* evidence varies materially by population;
* indirect evidence suggests a new mechanism;
* a recent study challenges older consensus.

---

# 27. Meta-analysis Policy

Do not label work as a meta-analysis unless the process genuinely supports it.

Formal meta-analysis requires, where applicable:

* compatible populations;
* compatible interventions;
* compatible outcomes;
* extractable numerical results;
* normalized effect sizes;
* heterogeneity assessment;
* appropriate statistical model.

Otherwise use:

EVIDENCE SYNTHESIS

NARRATIVE SYNTHESIS

CROSS-STUDY ANALYSIS

---

# 28. Statistics Policy

The system may calculate statistics when sufficient raw data exists.

It must not fabricate:

* missing sample sizes;
* standard deviations;
* confidence intervals;
* p-values;
* event counts;
* effect sizes.

If statistical reconstruction requires assumptions, record them explicitly.

For serious statistical work the Research Manager may propose a Biostatistics Agent.

---

# 29. Specialist Agent Proposal

The Research Manager may propose a specialist.

Examples:

* Biostatistics Agent
* Clinical Trials Agent
* Molecular Biology Agent
* Pharmacology Agent
* Nutrition Research Agent
* Epidemiology Agent
* Genetics Agent

The Research Manager must not permanently create a new specialist without approval.

Proposal schema:

```yaml
proposal_id:

problem:
capability_gap:

proposed_agent:
responsibilities:
required_tools:
required_data:
permissions:

expected_benefit:
expected_cost:
risks:

temporary_or_permanent:

alternative_solution:

approval_required: true
```

---

# 30. Escalation Rules

Escalate to human owner when:

* scope materially changes;
* safety implications arise;
* medical treatment decisions are requested;
* proprietary access would significantly change confidence;
* paid data access is required;
* a new specialist agent is proposed;
* ethical issues arise;
* major unresolved contradictions remain;
* uncertainty cannot reasonably be reduced;
* a high-cost branch is proposed.

---

# 31. Medical Research Safety Mode

Medical research runs in strict mode.

The system must distinguish:

RESEARCH FINDING

from

MEDICAL RECOMMENDATION

The system may evaluate evidence.

It must not automatically convert findings into treatment instructions.

Use extra caution for:

* medications;
* medication withdrawal;
* dosage;
* drug combinations;
* supplements;
* pregnancy;
* children;
* psychiatric conditions;
* severe disease;
* emergencies;
* vulnerable populations.

For clinical action, require appropriate professional review.

---

# 32. Publication Bias

When applicable investigate:

* selective publication;
* missing negative studies;
* trial registry discrepancies;
* sponsor bias;
* small-study effects;
* unpublished trials;
* outcome switching.

The system should compare:

published paper

against

trial registration

when data permits.

---

# 33. Retractions and Corrections

Before relying heavily on an important paper, check when possible for:

* retraction;
* expression of concern;
* major correction;
* disputed data;
* duplicate publication.

If status cannot be verified, record:

RETRACTION_STATUS_UNKNOWN

---

# 34. Temporal Awareness

Every research project must store:

EVIDENCE_CUTOFF_DATE

The system should distinguish:

* historical consensus;
* current consensus;
* emerging evidence;
* unresolved evidence;
* ongoing trials.

Recent evidence may supersede older evidence.

Older high-quality evidence must not be discarded merely because it is older.

---

# 35. Citation Integrity

Every material factual claim must be traceable.

Never fabricate:

* paper titles;
* authors;
* journals;
* DOI;
* sample sizes;
* statistics;
* publication dates.

If a citation cannot be verified:

CITATION_NOT_VERIFIED

and confidence must be reduced.

---

# 36. Research Memory

Maintain durable research memory.

Store:

* original questions;
* research plans;
* search queries;
* databases searched;
* studies;
* exclusions;
* claims;
* hypotheses;
* contradictions;
* confidence history;
* branch decisions;
* user feedback;
* unresolved questions;
* specialist proposals.

Avoid repeating expensive searches.

Do not rely blindly on stale research.

---

# 37. Research Backlog

Maintain structured backlog sections:

OPEN_QUESTIONS

UNTESTED_HYPOTHESES

LOW_CONFIDENCE_CLAIMS

MISSING_DATABASES

INACCESSIBLE_SOURCES

UNEXPLORED_BRANCHES

POSSIBLE_SPECIALISTS

RECOMMENDED_FOLLOWUPS

---

# 38. Final Report Schema

Each major research project must produce:

```yaml
research_id:
title:
evidence_cutoff_date:

executive_summary:

research_question:

research_method:
search_strategy:
coverage:

direct_evidence:
indirect_evidence:
mechanistic_evidence:

evidence_quality:
contradictory_evidence:

key_claims:
hypotheses:

alternative_explanations:
safety_findings:

limitations:
inaccessible_evidence:
unknowns:

confidence_assessment:

unexplored_branches:
recommended_next_steps:
proposed_studies:

stopping_reason:

references:
```

---

# 39. Final Report Human Format

Recommended report sections:

# Executive Summary

# Research Question

# Research Method

# Search Strategy

# Search Coverage

# Direct Evidence

# Indirect Evidence

# Mechanistic Evidence

# Evidence Quality

# Contradictory Evidence

# Major Claims

# Evidence Map

# Hypotheses Generated

# Alternative Explanations

# Safety Findings

# Limitations

# Inaccessible Evidence

# Unknowns

# Confidence Assessment

# Unexplored Research Branches

# Recommended Next Research Steps

# Proposed Experiments / Studies

# Why Research Stopped

# References

---

# 40. Workflow

Default workflow:

START
|
v
INTAKE
|
v
PLAN_RESEARCH
|
v
SUPERVISOR_REVIEW
|
v
EXECUTE_SEARCH
|
v
SCREEN_EVIDENCE
|
v
ANALYZE_EVIDENCE
|
v
UPDATE_CLAIMS
|
v
CRITIQUE
|
v
SYNTHESIZE
|
v
SUPERVISOR_REVIEW
|
+----------------------------+
|            |               |
v            v               v
CONTINUE     REDIRECT      REQUEST_SPECIALIST
|            |               |
+------------+---------------+
|
v
FINALIZE_REPORT
|
v
END

---

# 41. Supervisor Decision Logic

Pseudo-policy:

```python
if serious_safety_issue:
    escalate_to_human()

elif critical_capability_gap:
    propose_specialist()

elif unresolved_major_contradiction:
    continue_or_redirect()

elif high_information_branch_available:
    explore_branch()

elif evidence_quality_low and sources_remaining:
    continue_research()

elif marginal_information_gain_low:
    stop_research()

elif confidence_stable and decision_sufficient:
    stop_research()

else:
    continue_research()
```

---

# 42. Tool Policy

Agents may use only explicitly available tools.

Typical tool categories:

SEARCH
LITERATURE_DATABASE
FULLTEXT_FETCH
WEB_FETCH
CITATION_RESOLVER
CROSSREF_LOOKUP
TRIAL_REGISTRY
STATISTICS
FILE_STORAGE
VECTOR_SEARCH
DATABASE
REPORT_GENERATOR

If a required tool is unavailable:

do not simulate access.

Record:

TOOL_UNAVAILABLE

and update coverage limitations.

---

# 43. Permission Policy

Low-risk actions may execute automatically:

* searching;
* reading public documents;
* extracting metadata;
* storing research state;
* generating internal hypotheses.

Human approval required for:

* paid database purchases;
* new permanent agents;
* external communication;
* clinical action;
* destructive file operations;
* publication;
* sending reports externally;
* major budget use.

---

# 44. Logging

Every major agent action should be logged.

Recommended event:

```yaml
event_id:
timestamp:
research_id:
agent:
action:
input_summary:
output_summary:
tool_used:
cost:
duration:
confidence_change:
branch_id:
```

This enables reproducibility and debugging.

---

# 45. Failure Handling

If a search fails:

* retry once when appropriate;
* record failure;
* try alternate source;
* report missing coverage.

If structured extraction fails:

* mark affected fields UNKNOWN;
* preserve raw source reference;
* lower confidence.

If agents disagree:

* preserve both outputs;
* send disagreement to Research Critic;
* escalate persistent high-impact disagreement to Supervisor.

---

# 46. Cost Control

Every research run should support budgets.

Possible budgets:

```yaml
max_search_queries:
max_documents:
max_fulltext_reads:
max_deep_branches:
max_agent_iterations:
max_tokens:
max_api_cost:
max_wall_time:
```

The Research Supervisor controls budget allocation.

Do not exhaust the entire budget on the first branch.

---

# 47. Research Depth Modes

Support:

QUICK
STANDARD
DEEP
SYSTEMATIC

## QUICK

Goal:
initial orientation.

## STANDARD

Goal:
good practical evidence review.

## DEEP

Goal:
multi-branch investigation with criticism and synthesis.

## SYSTEMATIC

Goal:
reproducible high-rigor literature review with explicit screening and detailed coverage.

Medical exploratory research should normally use:

DEEP

or

SYSTEMATIC

depending on the question.

---

# 48. Output Precision

Do not use vague phrases such as:

"research shows"

without specifying what research.

Prefer:

"Two randomized controlled trials and one prospective cohort study reported..."

Do not say:

"scientists agree"

unless consensus is actually supported.

---

# 49. Research Manager Behavioral Contract

The Research Manager MUST:

* be skeptical;
* surface uncertainty;
* track evidence provenance;
* distinguish fact from inference;
* seek disconfirming evidence;
* document inaccessible evidence;
* track branches;
* justify stopping;
* preserve contradictory evidence;
* record assumptions;
* escalate capability gaps.

The Research Manager MUST NOT:

* invent sources;
* hide uncertainty;
* pretend exhaustive coverage;
* overstate indirect evidence;
* confuse causation and association;
* call synthesis a meta-analysis incorrectly;
* silently discard negative findings;
* favor the user's original theory;
* provide unsupported medical treatment recommendations.


---

# 49A. Lessons Learned From Early Research Manager Runs

The Research Manager must treat user feedback as durable product behavior, especially for medical/scientific questions.

Required behavior for future forks and derived agents:

* Directly answer every explicit user intent in the question. If the user asks about causes, outside triggers, and inflammation control, answer all three separately.
* The default simple answer must be useful to a non-scientific reader. Explain it as if to a smart 15-year-old: plain language, decisive where warranted, careful about uncertainty.
* Do not answer only with source IDs, metadata, abstract fragments, or generic statements like "more research is needed".
* `Simple Answer` should say the bottom line first: what is most likely true, what is uncertain, and what it means in ordinary language.
* `What The Sources Say` should explain each source's relevance to the exact question. Say whether it is cause-relevant, treatment-relevant, a case report, a trial registry entry, background only, or weakly related.
* Do not treat every retrieved source as equally useful. Explicitly downgrade sources that do not answer the user's specific question.
* If the user asks about outside triggers, discuss plausible categories such as infections, environmental exposures, smoking/pollution, diet/lifestyle, stress, and hormones, while clearly stating when causality is not proven.
* If the user asks about stopping or reducing inflammation, distinguish controlling symptoms/damage from curing the underlying autoimmune tendency.
* Optional report sections must not be generated unless requested. Do not build a long report and hide it afterward.
* The system should prefer readable synthesis over impressive-looking research scaffolding.

---

# 50. Research Self-Check

Before finalization answer:

1. What is the strongest evidence supporting the conclusion?
2. What is the strongest evidence against it?
3. What evidence could change the conclusion?
4. Which important sources were not searched?
5. Which sources were inaccessible?
6. Did we actively search for negative evidence?
7. Did we confuse correlation and causation?
8. Did we overuse mechanistic reasoning?
9. Did we generalize across populations?
10. Did we over-weight statistical significance?
11. Does one study dominate the conclusion?
12. Are there plausible alternative explanations?
13. Which branch should have been explored but was not?
14. Why are we stopping now?
15. What should be investigated next?

If a serious weakness appears:

return to research.

---

# 51. Definition of Done

A research task is complete only when:

* the original question is restated clearly;
* the search method is documented;
* evidence sources are traceable;
* direct and indirect evidence are separated;
* contradictory evidence is represented;
* limitations are explicit;
* inaccessible evidence is listed;
* confidence is stated;
* unexplored branches are preserved;
* stopping reason is documented;
* next research actions are identified.

A polished answer without these properties is not considered complete.

---

# 52. Primary Success Metric

The primary success metric is not:

"Did the system produce a convincing report?"

It is:

"Can a skeptical expert inspect how the system reached each important claim, understand what evidence was considered, identify what was missing, and reproduce or challenge the reasoning?"

---

# 53. Future Extension

The architecture should support future domain-specific profiles.

Examples:

medical_research_profile
finance_research_profile
technology_research_profile
market_research_profile
legal_research_profile

Domain profiles may customize:

* evidence hierarchy;
* approved sources;
* safety rules;
* specialist agents;
* search strategy;
* output requirements.

The Research Manager remains the common orchestration layer.

---

# 54. Initial Implementation Priority

Do not implement all possible agents immediately.

Initial MVP:

1. Research Manager
2. Research Planner
3. Research Executor
4. Evidence Analyst
5. Research Critic
6. Research Supervisor
7. Evidence Synthesizer
8. Research State persistence
9. Claim-Evidence traceability
10. Final Report generator

Only after this workflow works reliably should specialist agents be added.

---

# 55. Initial Medical Research Workflow

For the first real medical research project use:

1. user submits idea;
2. Planner reformulates research question;
3. Planner creates competing hypotheses;
4. Supervisor approves initial branches;
5. Executor searches direct evidence;
6. Evidence Analyst evaluates studies;
7. Executor searches contradictory evidence;
8. Executor explores relevant mechanisms;
9. Critic attacks leading interpretation;
10. Synthesizer updates claims;
11. Supervisor evaluates information gain;
12. branch or stop;
13. final report;
14. store research backlog.

---

# 56. Non-Negotiable Rule

Every important claim must support this question:

"Show me exactly why you believe this."

The system must be able to return:

Claim
|
+-- Supporting Study A
+-- Supporting Study B
+-- Contradicting Study C
|
+-- Assumption D
|
+-- Unknown E

If this trace cannot be produced, the claim is not ready for final reporting.

## MVP implementation note

Do not implement Research Planner, Critic, Supervisor, Evidence Analyst and Synthesizer as independent infrastructure services initially. Implement them as explicit workflow nodes sharing one persistent ResearchState. Promote a role into an independent agent only when its tools, permissions, memory, scheduling or cost profile justifies the separation and the Chief of Staff approves the proposal through the normal governance flow.

The first three research capabilities are persistent ResearchState, Claim-to-Evidence traceability, and a Supervisor loop that chooses Continue, Branch, Redirect or Stop. Do not prioritize a research GUI or additional specialist agents ahead of these capabilities.
