# Product Manager API

## Existing

```text
GET  /api/v1/product/manager/status/
GET  /api/v1/product/dashboard/
GET  /api/v1/product/projects/{project_id}/readiness/
GET  /api/v1/product/projects/{project_id}/roadmap/
GET  /api/v1/product/features/prioritization/
GET  /api/v1/product/features/rank/
POST /api/v1/product/features/{feature_id}/rice/
POST /api/v1/product/prd/generate/
POST /api/v1/product/milestones/create/
POST /api/v1/product/milestones/{milestone_id}/objective/
GET  /api/v1/product/roadmap/timeline/
POST /api/v1/product/feedback/ingest/
GET  /api/v1/product/feedback/summary/
POST /api/v1/product/spec-contracts/create/
POST /api/v1/product/spec-contracts/{contract_id}/drafts/create/
POST /api/v1/product/spec-drafts/{draft_id}/review/
POST /api/v1/product/spec-drafts/{draft_id}/tasks/propose/
GET  /api/v1/product/spec-contracts/{contract_id}/user-research/
POST /api/v1/product/spec-contracts/{contract_id}/user-research/create/
POST /api/v1/product/user-research/{research_id}/interviews/create/
POST /api/v1/product/user-research/{research_id}/findings/create/
POST /api/v1/product/user-research/{research_id}/questions/create/
POST /api/v1/product/user-research/questions/{question_id}/update/
POST /api/v1/product/spec-contracts/{contract_id}/competitive-analyses/create/
POST /api/v1/product/competitive-analyses/{draft_id}/review/
POST /api/v1/product/spec-contracts/{contract_id}/pricing-experiments/create/
POST /api/v1/product/pricing-experiments/{brief_id}/review/
POST /api/v1/product/github-issues/create/
POST /api/v1/product/github-issues/{issue_id}/approval-request/
```

## Mutation Rules

- Requires `Idempotency-Key`.
- Requires `X-Correlation-ID`.
- Writes audit events.
- Does not write to a product repository.
- GitHub is contacted only when an approved `product.github.issue.create` action is executed.

## Pricing experiment brief

A brief is an internal price comparison attached to a product spec. It stores two to four ILS variants, a hypothesis, a success metric, a success criterion, and a stop condition. It starts at `NEEDS_REVIEW`. Approval records a decision only.

The brief does not charge, refund, publish, spend, or contact a customer. Currency other than `ILS` is rejected. Payment, card, and contact fields are rejected.

## Not built

- A live price test.
- Payment-provider calls.
