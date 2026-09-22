# Executive Assistant API

## Existing

```text
GET  /api/v1/executive-assistant/status/
GET  /api/v1/executive-assistant/briefs/
POST /api/v1/executive-assistant/briefs/create/
POST /api/v1/executive-assistant/briefs/{brief_id}/tasks/propose/
GET  /api/v1/executive-assistant/task-proposals/
POST /api/v1/executive-assistant/task-proposals/{proposal_id}/review/
GET  /api/v1/executive-assistant/email-drafts/
POST /api/v1/executive-assistant/email-drafts/create/
GET  /executive-assistant/
```

## Mutation Rules

- Requires `Idempotency-Key`.
- Requires `X-Correlation-ID`.
- Writes audit events.
- External email/calendar actions remain disabled.

## Proposed Next APIs

```text
POST /api/v1/executive-assistant/email-drafts/{draft_id}/review/
POST /api/v1/executive-assistant/email-drafts/{draft_id}/approval-request/
GET  /api/v1/executive-assistant/calendar/events/
```

