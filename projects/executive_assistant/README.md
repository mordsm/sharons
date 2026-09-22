# Executive Assistant Project

## Mission

Executive Assistant prepares briefs, tracks follow-ups, drafts administrative communications
and helps manage inbox/calendar work safely.

It must not send email, schedule meetings, contact people or use real calendar/email providers
without explicit approved adapters and approval-backed execution.

## Current Implementation

- EA models: `executive_assistant/models.py`
- EA services: `executive_assistant/services.py`
- EA views/API: `executive_assistant/views.py`, `executive_assistant/urls.py`
- EA templates: `templates/executive_assistant/`
- EA tests: `executive_assistant/tests/test_executive_brief_api.py`
- Mock inbox intake: `mailbox/`
- Approval/audit/outbox foundation: `governance/`

## Current APIs

- `GET /api/v1/executive-assistant/status/`
- `GET /api/v1/executive-assistant/briefs/`
- `POST /api/v1/executive-assistant/briefs/create/`
- `GET /api/v1/executive-assistant/task-proposals/`
- `POST /api/v1/executive-assistant/briefs/{brief_id}/tasks/propose/`
- `POST /api/v1/executive-assistant/task-proposals/{proposal_id}/review/`
- `GET /api/v1/executive-assistant/email-drafts/`
- `POST /api/v1/executive-assistant/email-drafts/create/`
- `GET /executive-assistant/`

## Current Capabilities

- Create executive briefs from internal Sharons state.
- Convert brief follow-ups into internal draft tasks.
- Review task proposals.
- Create internal email draft proposals from ingested mock mailbox messages.
- Track queue counts for briefs, task proposals and email drafts.
- Keep all external sending disabled.

## Boundaries

- No real Gmail access yet.
- No real calendar access yet.
- No email sending.
- No meeting scheduling.
- No external contacts.
- No autonomous external action.

## Next Work

1. Add email draft review lifecycle and approval request creation.
2. Add read-only real email connector behind explicit approval.
3. Add calendar event model for read-only calendar ingestion.
4. Add calendar prep briefs.
5. Add approval-backed external send/schedule execution only after provider adapters exist.

