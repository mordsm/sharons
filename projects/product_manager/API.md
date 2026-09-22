# Product Manager API

## Existing

```text
GET  /api/v1/product/manager/status/
POST /api/v1/product/spec-contracts/create/
POST /api/v1/product/spec-contracts/{contract_id}/drafts/create/
POST /api/v1/product/spec-drafts/{draft_id}/review/
```

## Mutation Rules

- Requires `Idempotency-Key`.
- Requires `X-Correlation-ID`.
- Writes audit events.
- Does not write to external product repositories.

## Proposed Next APIs

```text
POST /api/v1/product/roadmaps/create/
POST /api/v1/product/spec-drafts/{draft_id}/tasks/propose/
GET  /api/v1/product/projects/{project_id}/readiness/
```

