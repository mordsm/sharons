# Executive Assistant Decisions

## Active Decisions

- EA lives in the `executive_assistant` Django app.
- Mailbox ingestion remains separate in `mailbox`.
- Email drafts are internal proposals only.
- `no_external_send` must remain true until an approved provider adapter exists.

## Deferred Decisions

- Gmail vs Outlook first.
- Required OAuth scopes.
- Calendar provider.
- Approval-backed executor action names for send/schedule.

