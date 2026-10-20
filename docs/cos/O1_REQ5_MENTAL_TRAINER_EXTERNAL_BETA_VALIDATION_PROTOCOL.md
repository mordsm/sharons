# O1 REQ-5: Mental Trainer External Beta Validation Protocol

Date: 2026-10-06
Owner lane: Product / Developer / QA
Scope: Mental Skills Playground / Mental Trainer sale-ready beta path
External action: none

## Requirement

Define the external beta validation protocol and evidence to collect before expanding access to the Mental Trainer beta.

This artifact does not recruit testers, contact users, publish a signup page, deploy software, or process real payments. It defines the protocol the team should run once external beta execution is approved.

## Problem Traceability

The commercial readiness objective requires external validation, not only internal implementation evidence. The team needs a repeatable protocol that can show whether a real tester can understand the product, start training, safely stop, finish a session, and report whether the product is valuable enough to continue.

This protocol builds on:

- REQ-2 landing-page content and positioning.
- REQ-3 beta pricing and mock billing path.
- REQ-4 desktop/mobile smoke-test acceptance criteria.
- Mental Skills Playground GPT instructions and API action contract.

## Beta Hypotheses

| ID | Hypothesis | Evidence needed |
| --- | --- | --- |
| H1 | Users understand Mental Trainer as mental-skills training, not therapy. | Tester comprehension response after first view. |
| H2 | Users can complete one low-intensity session without facilitator rescue. | Session completion evidence and tester notes. |
| H3 | The stop/safety boundary is clear and works. | Tester can identify stop path; `user_stop` path is tested at least once. |
| H4 | The initial value proposition is strong enough for continued use. | Post-session value rating and willingness-to-repeat answer. |
| H5 | The proposed beta price is plausible enough to test, without collecting real payment. | Mock billing understanding and price-sensitivity response. |

## Tester Profile

Minimum beta cohort:

- 5 external testers for first validation pass.
- At least 2 desktop sessions.
- At least 2 mobile sessions.
- At least 1 tester must intentionally use the stop path.

Tester inclusion:

- Adult user.
- Comfortable using ChatGPT or a GPT-style chat surface.
- Interested in practicing pause, frustration tolerance, or arousal regulation.
- Able to give feedback in writing after the session.

Tester exclusion:

- User seeking crisis support, diagnosis, therapy, medication advice, or treatment.
- User currently asking for emergency help.
- User who cannot safely engage in a low-intensity reflective drill.
- Minor without a separate approved consent process.

## Consent And Boundary Script

Before a beta session, the tester must see or confirm:

```text
Mental Trainer is a low-intensity mental-skills practice product. It is not therapy,
diagnosis, treatment, or crisis support. You can stop at any time. During this beta we
are collecting usability and product feedback, not medical or clinical information.
```

Tester must answer:

```text
I understand this is skills practice, not therapy or treatment, and I can stop at any time.
```

Accepted values:

- `yes`
- `no`

If answer is `no`, do not run the beta session.

## Session Script

Each tester should complete one short flow:

1. View the first product explanation or landing-page copy.
2. State what they think the product does.
3. Start one recommended low-intensity training session.
4. Complete baseline response, micro-skill, retest, and debrief.
5. Complete the session.
6. Review progress/history if available.
7. Answer the feedback questions.

At least one tester should run this alternate safety path:

1. Start one recommended low-intensity session.
2. Ask to stop.
3. Confirm the system stops immediately and records `user_stop`.
4. Confirm the tester is not pressured to continue.

## Evidence To Collect

For each beta tester, collect:

```yaml
tester_id:
test_date:
device_type: DESKTOP | MOBILE
browser_or_app:
entry_surface: GPT | landing_page | direct_api | other
consent_confirmed: true | false

first_view_comprehension:
  tester_summary:
  understood_as_training_not_therapy: true | false
  unclear_terms:

session_execution:
  session_started: true | false
  session_completed: true | false
  stop_path_tested: true | false
  stop_path_successful: true | false | NOT_TESTED
  action_failures:
  facilitator_rescue_needed: true | false

value_feedback:
  usefulness_rating_1_to_5:
  clarity_rating_1_to_5:
  safety_clarity_rating_1_to_5:
  would_repeat: yes | no | maybe
  price_reaction:
  strongest_positive_signal:
  strongest_negative_signal:

release_decision_inputs:
  critical_blocker:
  requested_changes:
  tester_quote:
```

Do not collect unnecessary sensitive health details. If a tester volunteers sensitive material, summarize it at a high level or mark it `SENSITIVE_DETAIL_OMITTED`.

## Success Metrics

First external beta pass is successful only if:

- 5/5 testers confirm they understand the product is training, not therapy.
- At least 4/5 testers complete a session without facilitator rescue.
- At least 1 stop-path test succeeds.
- Average usefulness rating is at least 4.0/5.
- Average clarity rating is at least 4.0/5.
- Average safety-clarity rating is at least 4.5/5.
- 3/5 testers answer `yes` or `maybe` to repeating the product.
- 0 critical safety blockers occur.
- 0 real billing events occur.

## Go / No-Go Rules

Proceed to expanded beta only if:

1. REQ-4 desktop/mobile smoke gates pass.
2. External beta success metrics pass.
3. No critical safety blocker is open.
4. No tester confusion suggests the product is therapy or treatment.
5. Any severe usability failure is converted into a tracked task.

Do not expand beta if:

- any user cannot stop immediately;
- the product is interpreted as clinical care by multiple testers;
- mobile completion fails for more than one tester;
- real billing or external side effects occur accidentally;
- feedback indicates the drill feels coercive, shaming, intense, or unsafe.

## Evidence Review

QA should review:

1. Completed tester evidence records.
2. Action/session logs for session start, event, completion, and stop-path behavior.
3. Screenshots or tester notes for desktop and mobile surfaces.
4. Summary of blocker themes.
5. Confirmation that no real billing or deployment action occurred.

## Success Metrics Before Release

- Beta evidence records completed: 5.
- Desktop tester records: at least 2.
- Mobile tester records: at least 2.
- Stop-path records: at least 1.
- Critical safety blockers: 0.
- Real payment charges: 0.
- Product interpretation as therapy/treatment: 0 repeated-pattern blocker.

## Traceability To REQ-5

REQ-5:

Define external beta validation protocol and evidence to collect.

Coverage:

- External beta protocol: tester profile, consent, session script, safety path.
- Evidence collection: structured YAML record per tester.
- Validation metrics: success metrics and go/no-go rules.
- Safety and product boundaries: non-therapy, no real billing, stop path, no unnecessary sensitive data.

## Limitations

- This is a protocol definition, not a completed external beta run.
- Human approval is required before contacting external testers.
- If the beta cohort changes materially, the protocol should be reviewed before use.
