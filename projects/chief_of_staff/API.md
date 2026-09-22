# Chief of Staff API

## Existing

```text
POST /api/v1/cos/intake/
POST /api/v1/cos/objectives/{objective_id}/work/propose/
GET  /api/v1/reports/weekly/
GET  /review/weekly/
GET  /
```

## Mutation Rules

- Requires `Idempotency-Key`.
- Requires `X-Correlation-ID`.
- Writes audit events.
- Creates internal records only.

## Proposed Next APIs

```text
GET  /api/v1/cos/objectives/health/
GET  /api/v1/cos/objectives/{objective_id}/operating-review/
POST /api/v1/cos/objectives/{objective_id}/next-actions/propose/
```

