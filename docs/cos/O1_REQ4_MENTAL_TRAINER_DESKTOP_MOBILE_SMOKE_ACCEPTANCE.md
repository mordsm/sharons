# O1 REQ-4: Mental Trainer Desktop and Mobile Smoke-Test Acceptance Criteria

Date: 2026-10-06
Owner lane: Developer / QA
Scope: Mental Skills Playground / Mental Trainer sale-ready beta path

## Requirement

Define desktop and mobile smoke-test acceptance criteria for the initial Mental Trainer beta.

This requirement is satisfied by a release-gate checklist that can be run before beta access is offered. The product is currently API and custom-GPT action driven, so the smoke test covers the complete training flow through the public action contract plus manual checks for desktop and mobile ChatGPT surfaces.

## Problem Traceability

The commercial beta cannot be considered sale-ready unless a tester can confirm that the core training path works on both desktop and mobile without needing engineering interpretation.

The core user path is:

1. Open the Mental Trainer GPT experience.
2. Start a short training session.
3. Record one meaningful session event.
4. Complete the session.
5. Confirm progress/history can be read back.
6. Confirm the user can stop safely.

## Smoke-Test Matrix

| Area | Desktop acceptance | Mobile acceptance | Evidence required |
| --- | --- | --- | --- |
| Entry | GPT or beta entry point opens and explains the training frame without therapy or medical claims. | Same copy is readable without horizontal scrolling or clipped primary actions. | Screenshot or tester note. |
| Auth/API availability | `/health` returns success and protected MSP actions reject missing/invalid auth. | Same API behavior from the mobile GPT action path. | Command output or action log. |
| Recommendation | Tester can request a low-intensity training recommendation. | Same request completes without timeout or unusable formatting. | Action response includes `recommended_exercise_id`. |
| Start session | `POST /api/msp/sessions/start` creates or reuses a session idempotently. | Same action starts a session from mobile. | Response includes `session_id`, `skill_id`, `exercise_id`, `status`. |
| Session event | `POST /api/msp/sessions/{session_id}/event` records one allowed milestone event. | Same event can be recorded from mobile. | Response includes `success=true` and `event_id`. |
| Complete session | `POST /api/msp/sessions/{session_id}/complete` completes the session idempotently. | Same completion works from mobile. | Response includes `success=true` and completed status. |
| Progress/history | Progress or skill history reflects the completed session. | Same readback is understandable on mobile. | Response or screenshot shows updated history/progress. |
| Safety stop | If the tester asks to stop, a `user_stop` event marks safety state as stopped. | Same behavior works from mobile. | Response includes `safety_state=stopped`. |
| Copy fit | Core beta copy and instructions are scannable at desktop width. | Copy fits a narrow mobile viewport with no hidden required step. | Screenshot or tester note. |
| External action boundary | No payment, deployment, external publishing, clinical advice, or account mutation is performed during the smoke test. | Same boundary holds on mobile. | Tester note and action log. |

## Minimum Automated Check

Run the existing Mental Skills MVP test suite:

```powershell
uv run python -m unittest tests\test_mental_skills_mvp.py
```

This is the minimum automated gate because it verifies the core backend behaviors behind the desktop/mobile smoke path:

- session start idempotency;
- user stop safety state;
- session completion and progress update;
- FastAPI route availability with auth.

## Manual Desktop Pass Criteria

A desktop smoke pass requires:

1. The tester can complete one low-intensity session from start to completion.
2. The session produces durable progress or history readback.
3. The tester can stop the session and see the stopped safety state represented.
4. The visible experience is framed as mental-skills training, not therapy, diagnosis, or treatment.
5. No beta purchase, real billing, deployment, email, or external publication occurs.

## Manual Mobile Pass Criteria

A mobile smoke pass requires:

1. The same session path can be completed from a phone-width experience.
2. Required instructions and next actions remain readable without layout clipping.
3. Action responses are short enough to be usable in the mobile chat surface.
4. The stop path remains immediately available.
5. No mobile-only blocker prevents finishing or safely stopping a session.

## Release Gate

REQ-4 is passed when:

1. The automated MVP test suite passes.
2. A human tester records one desktop smoke pass.
3. A human tester records one mobile smoke pass.
4. Any failure is converted into a tracked follow-up task before beta access expands.

## Success Metrics

- Desktop smoke path completion: 1/1 required before beta release.
- Mobile smoke path completion: 1/1 required before beta release.
- Automated MVP test suite: 100% pass required.
- Critical safety-stop failures: 0 allowed.
- Real billing or external side effects during smoke test: 0 allowed.

## Limitations

- This artifact defines acceptance criteria; it does not claim that a live desktop/mobile smoke run has already been performed.
- The current repository contains backend/API surfaces, not a native web or mobile frontend.
- Real beta release still requires tester evidence for desktop and mobile execution.
