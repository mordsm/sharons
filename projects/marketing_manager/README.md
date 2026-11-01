# Marketing Manager

Draft-only marketing plans inside Sharons.

## Now

- The `marketing` agent is registered and its runner is on. An assigned task executed with `POST /api/v1/agents/execute/` creates the draft plan and moves the task to `DELIVERED_UNVERIFIED`.
- Publishing, sending, and ad spending stay off.

- `POST /api/v1/marketing/requests/create/` builds a strategy, audience hypothesis, positioning, campaign brief, and decision bundle.
- `POST /api/v1/marketing/requests/{id}/campaign-briefs/create/` adds another draft brief.
- `POST /api/v1/marketing/artifacts/{id}/review/` and `/revise/` keep approval tied to one version.
- `POST /api/v1/marketing/performance/analyze/` uses only a supplied snapshot.
- Page: `/marketing/`.
- An active objective can receive one Project Manager milestone proposal. The proposal does not execute the campaign.
- A content calendar stores draft titles, channel labels, and planned dates. Acknowledging an item does not publish or send it.
- An experiment register stores a hypothesis and a metric. It does not spend and it does not claim statistical significance.
- A claims register stays unsupported until a person supplies an evidence note. Acknowledging an unsupported claim does not mark it supported.

## Boundaries

- Publishing, email sending, ad spending, CRM reads, and live analytics stay off.
- Market or competitor figures are not invented when no source is supplied.
- Unsupported claims stay unapproved until a person acknowledges them.
- A revised artifact starts again as a draft.

## Later

- Read-only analytics only after a scoped connector exists.
- No channel publishing unless a separate approval adapter is added.
