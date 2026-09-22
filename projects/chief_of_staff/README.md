# Chief of Staff Project

## Mission

Chief of Staff turns the 90-day company strategy into objectives, plans, tasks, approvals,
verification and weekly operating reviews.

It must not execute external actions directly. It proposes internal work, routes decisions,
tracks blockers and escalates when approval is needed.

## Current Implementation

- Core services: `core/services.py`
- Core API/views: `core/views.py`, `core/urls.py`
- Tasks, plans, agents and verification: `operations/`
- Objectives and project registry: `portfolio/`
- Approvals, rules, audit and outbox: `governance/`

## Current APIs

- `POST /api/v1/cos/intake/`
- `POST /api/v1/cos/objectives/{objective_id}/work/propose/`
- `GET /api/v1/reports/weekly/`
- `GET /review/weekly/`
- `GET /`

## Current Capabilities

- Create draft tasks from intake.
- Generate internal work proposals for active objectives.
- Produce weekly review data from live Sharons state.
- Surface blocked tasks, unverified deliveries and pending approvals.
- Preserve audit trail and idempotency for state-changing requests.

## Boundaries

- No external communication.
- No repository writes.
- No production changes.
- No payments or spending.
- No task completion without verification evidence and acceptance criteria.

## Next Work

1. Add a 90-day operating dashboard grouped by objective.
2. Add objective health status: on-track, at-risk, blocked, unknown.
3. Add critical path and dependency view.
4. Add a CoS recommendation endpoint: "what should be worked on next?"
5. Add WIP limits and stale-task detection.

