# Sharons Current Session Handoff

Saved: 2026-09-19

## Project

Active project:

```text
C:\workspace\sharons
```

This is the separate Sharons Chief of Staff / AI organization project. It is not Compass and it is not `research_manager`.

Sharons is the company-level operating system:

- Chief of Staff orchestration
- organizational memory
- portfolio and objectives
- task lifecycle
- governance and approvals
- deterministic rules
- agent registry
- evidence, verification and audit

Product systems such as Compass, Mental Trainer and Research Manager stay separate and are referenced through registry/adapter contracts.

## Instructions Already Confirmed

Relevant instructions/specs read during this work:

- `AGENTS.md`
- `SESSION_HANDOFF.md`
- `docs/chief_of_staff/SPEC_HE.md`
- `docs/chief_of_staff/ENGINEERING_PLAN_HE.md`
- `docs/cos/IMPLEMENTATION_ASSESSMENT.md`

Important rules:

- Django + PostgreSQL.
- Django templates/server-rendered UI where UI is needed.
- No React.
- Business logic belongs in models/services; views stay thin.
- Every state-changing request requires `Idempotency-Key` and `X-Correlation-ID`.
- Every material state change creates an audit event.
- No external actions, Gmail, production changes, spending, publishing, contacting people, deleting, or payment-provider connection without explicit approval.
- Deterministic rules engine. No LLM authorization boundary.
- Product repositories/data are not copied into Sharons.

## What Works Now

Implemented and previously verified:

- Django/PostgreSQL scaffold.
- `POST /api/v1/cos/intake/`
  - creates a `DRAFT` task from an active objective
  - requires idempotency and correlation headers
  - writes audit event
- Portfolio:
  - objectives
  - project registry
  - project connections
- Operations:
  - task upsert
  - task status transition service
  - acceptance criteria
  - task evidence records
  - verification endpoint
  - completion gate
  - agent registry
  - task assignment to agents
  - safe agent invocation records
- Core:
  - organizational memory records
- Governance:
  - audit events
  - outbox/inbox contract records
  - deterministic rules foundation
  - approval request model/API
  - approval dashboard
  - permission provisioning
  - CEO reviewer setup command/tests
- Finance:
  - internal financial source of truth
  - reconciliation dashboard/API
- Mailbox:
  - mock Gmail intake workflow
  - deterministic email classification/proposed actions
- Payments:
  - provider-neutral mock payment interface
  - mock customers, subscriptions, charges, refunds and webhook intake
- Research:
  - bounded Research Task Contract creation
  - read-only project connection requirement
  - no external Research Manager execution yet

## Recent Completed Slices

### Approval Schema Fix

Added missing migration:

```text
governance/migrations/0004_approvalrequest_action_payload.py
```

This added `ApprovalRequest.action_payload`, matching the model and tests.

### Completion Verification Gate

Changed:

```text
operations/services.py
operations/tests/test_task_transitions.py
operations/tests/test_task_transition_api.py
```

Rule:

- A task cannot transition to `COMPLETED` unless required acceptance criteria exist.
- All required acceptance criteria must be `PASSED`.

### Task Evidence

Added:

```text
operations/migrations/0002_evidence.py
operations/tests/test_task_evidence_api.py
```

Endpoint:

```text
POST /api/v1/tasks/{id}/evidence/
```

Records task proof and writes audit event.

### Task Verification

Added:

```text
operations/tests/test_task_verify_api.py
```

Endpoint:

```text
POST /api/v1/tasks/{id}/verify/
```

Behavior:

- Requires at least one required acceptance criterion.
- Requires at least one verified evidence record.
- Can mark required criteria as `PASSED`.
- Moves `DELIVERED_UNVERIFIED` to `VERIFYING`.
- Writes audit event.

### Agent Registry

Added:

```text
operations/migrations/0003_agentdefinition.py
operations/tests/test_agent_registry_api.py
```

Endpoint:

```text
GET /api/v1/agents/
```

Filters by:

- `capability`
- `data_class`
- `max_risk_level`

Excludes inactive and over-capacity agents.

### Task Assignment

Added:

```text
operations/migrations/0004_task_owner_agent_id.py
operations/tests/test_task_assign_api.py
```

Endpoint:

```text
POST /api/v1/tasks/{id}/assign/
```

Behavior:

- Requires idempotency/correlation.
- Requires expected task version.
- Task must be `APPROVED`.
- Agent must be active.
- Agent must have available capacity.
- Sets `Task.owner_agent_id`.
- Moves task to `ASSIGNED`.
- Increments agent load.
- Writes audit event.

## Last Known Green Baseline

After completing the MemoryRecord slice, the full suite passed:

```text
uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests
137 passed in 7.67s
```

Note: `uv --native-tls` prints a deprecation warning. Future runs can use `uv --system-certs`.

## Completed AgentRun Slice

Added:

```text
operations/migrations/0005_agentrun.py
operations/migrations/0006_alter_agentrun_input_snapshot.py
operations/tests/test_agent_invoke_api.py
```

Endpoint:

```text
POST /api/v1/agents/invoke/
```

Behavior:

- Requires `Idempotency-Key`.
- Requires `X-Correlation-ID`.
- Accepts `task_id`, `agent_id`, and `input_snapshot`.
- Requires the task to be assigned to that same agent.
- Requires task status to be `ASSIGNED` or `IN_PROGRESS`.
- Creates an `AgentRun` with status `STARTED`.
- Stores `attempt_number`.
- Caps automatic attempts at 2.
- Writes an audit event.
- Does not call an LLM.
- Does not perform external actions.
- Does not send email, contact people, deploy, publish, spend money, delete, or access external personal data.

## Recommended Next Slice

Add `GET /api/v1/history/search/` as a simple database-backed memory/audit search endpoint, still without embeddings or external storage.

```text
core view/service:
- search MemoryRecord by text/type/classification/source
- optionally include AuditEvent references later
```

Suggested behavior:

- read-only endpoint
- no state change and no idempotency required
- filter by `q`, `record_type`, `classification`, `verification_status`, `source_type`
- return only structured metadata/content already stored in Sharons
- no vector search or embeddings
- no external data access

## Completed MemoryRecord Slice

Added:

```text
core/migrations/0002_memoryrecord.py
core/tests/test_memory_api.py
```

Endpoint:

```text
POST /api/v1/memory/
```

Behavior:

- Creates `MemoryRecord`.
- Requires idempotency and correlation headers.
- Stores record type, title, content object, source type/source id, owner, classification, verification status, version, validity fields and supersedes link.
- Writes audit event.
- Rejects `embedding_reference` in the initial slice.
- Rejects verified decisions sourced only from conversation summaries.
- No embeddings or external storage were added.

## Completed Outbox/Inbox Slice

Added:

```text
governance/migrations/0005_outboxmessage_inboxevent.py
governance/tests/test_outbox_inbox.py
```

Behavior:

- `OutboxMessage` stores topic, payload, status, attempts, next attempt, idempotency key and correlation ID.
- `InboxEvent` stores source, external event ID, payload, status and correlation ID.
- Inbox events deduplicate by `(source, external_event_id)`.
- Outbox enqueue is idempotent for identical topic/payload and rejects conflicting reuse.
- Creation writes audit events.
- No worker, broker, email delivery or external action was added.

## Completed Audit API Slice

Added:

```text
governance/tests/test_audit_api.py
```

Changed:

```text
governance/services.py
governance/views.py
sharons/urls.py
```

Endpoint:

```text
GET /api/v1/audit/
```

Behavior:

- Lists audit events.
- Filters by `action`, `object_type`, `object_id`, `actor_type`, `actor_id` and `correlation_id`.
- Supports `limit` from 1 to 100.
- Rejects invalid `actor_type` and invalid limits with `INVALID_AUDIT_FILTER`.
- Read-only; does not require idempotency/correlation headers and does not create audit events.

Verification:

- `uv --native-tls run python manage.py check` passed with no issues.
- `uv --system-certs run pytest core\tests operations\tests portfolio\tests governance\tests` failed to start because the local command runner returned `helper_unknown_error: setup refresh had errors`.
- `uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests` collected 143 tests but stalled after collection; it was interrupted.
- `uv --native-tls run pytest governance\tests\test_audit_api.py` collected 5 tests but stalled after collection; it was interrupted.

Follow-up: the test stall was caused by local Postgres not running. After `docker compose up -d postgres`, focused and full tests passed.

## Completed Executive Dashboard Slice

Added:

```text
templates/core/executive_dashboard.html
core/tests/test_executive_dashboard.py
```

Changed:

```text
core/services.py
core/views.py
sharons/urls.py
templates/base.html
```

Endpoint:

```text
GET /
```

Behavior:

- Login-protected server-rendered executive overview.
- Shows counts for active objectives, open tasks, blocked tasks, unverified deliveries, pending approvals and active agents.
- Shows active objectives, pending approvals, blocked tasks, unverified deliveries, agent capacity and recent audit events.
- Read-only; no state change, no idempotency headers required, no external action.

Latest verification:

```text
uv --native-tls run pytest core\tests\test_executive_dashboard.py
2 passed in 2.33s

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests
150 passed in 12.54s
```

## Completed Task Dashboard Slice

Added:

```text
templates/operations/task_list.html
templates/operations/task_detail.html
operations/tests/test_task_dashboard.py
```

Changed:

```text
operations/services.py
operations/views.py
operations/urls.py
templates/core/executive_dashboard.html
templates/base.html
```

Endpoints:

```text
GET /api/v1/tasks/
GET /api/v1/tasks/{task_id}/
```

Behavior:

- Login-protected server-rendered task list.
- Filters tasks by `status`, `objective_id` and `owner_agent_id`.
- Task detail page shows objective, plan, status, version, owner, business outcome, acceptance criteria, evidence, agent runs and task audit trail.
- Executive dashboard links open tasks and attention-needed task rows to these pages.
- Read-only; no state change, no idempotency headers required, no external action.

Latest verification:

```text
uv --native-tls run pytest operations\tests\test_task_dashboard.py
3 passed in 2.17s

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests
153 passed in 13.02s
```

## Completed Task Operating Console Slice

Added:

```text
operations/forms.py
```

Changed:

```text
operations/views.py
templates/operations/task_detail.html
templates/base.html
operations/tests/test_task_dashboard.py
```

Behavior:

- Task detail page now includes server-rendered POST forms for internal task actions:
  - transition task status
  - assign an agent
  - attach evidence
  - verify task and optionally mark required criteria passed
- Forms use CSRF and generated dashboard idempotency keys.
- Dashboard actions generate correlation IDs and call existing service-layer operations.
- Successful POSTs use redirect back to the task detail page.
- No external action, Gmail, product repository write, spending, publishing or production change was added.

Latest verification:

```text
uv --native-tls run pytest operations\tests\test_task_dashboard.py
7 passed in 3.37s

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests
157 passed in 17.33s
```

## Completed Weekly CEO Review Slice

Added:

```text
templates/core/weekly_review.html
core/tests/test_weekly_review.py
```

Changed:

```text
core/services.py
core/views.py
sharons/urls.py
```

Endpoints:

```text
GET /review/weekly/
GET /api/v1/reports/weekly/
```

Behavior:

- Login-protected server-rendered weekly review page.
- JSON weekly report endpoint.
- Summarizes active objectives, open tasks, pending approvals, blocked work, unverified deliveries, verification queue, recent completions, risks and next actions.
- Links review items back to approval and task operating pages.
- Read-only; no external email, Gmail, publishing, product repository write or production action.

Latest verification:

```text
uv --native-tls run pytest core\tests\test_weekly_review.py
3 passed in 6.88s

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests
160 passed in 21.69s
```

## Completed Rules Lifecycle API Slice

Added:

```text
governance/migrations/0006_ruletestcase.py
governance/tests/test_rule_lifecycle_api.py
```

Changed:

```text
governance/models.py
governance/services.py
governance/views.py
governance/urls.py
sharons/urls.py
```

Endpoints:

```text
POST /api/v1/rules/proposals/
POST /api/v1/rules/{rule_id}/validate/
POST /api/v1/rules/{rule_id}/test/
```

Behavior:

- Creates draft rule proposals with idempotency/correlation requirements.
- Validates rules using only the deterministic DSL and allowed operators.
- Persists rule test cases and records pass/fail results.
- Moves rules through `DRAFT -> VALIDATED -> TESTED` when validation and tests pass.
- Failed tests return `409` and persist failed test case results for inspection.
- Writes audit events for proposed, validated, tested and test-failed rule lifecycle actions.
- Does not activate rules yet and does not bypass CEO approval gates.

Latest verification:

```text
uv --native-tls run pytest governance\tests\test_rule_lifecycle_api.py
5 passed in 1.32s

uv --native-tls run python manage.py migrate
Applying governance.0006_ruletestcase... OK

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests
165 passed in 12.76s
```

## Completed Rule Activation Gate Slice

Added:

```text
governance/tests/test_rule_activation_api.py
```

Changed:

```text
governance/services.py
governance/views.py
sharons/urls.py
```

Endpoints:

```text
POST /api/v1/rules/{rule_id}/activation-request/
POST /api/v1/rules/{rule_id}/activate/
```

Behavior:

- Activation requests require the rule to be `TESTED`.
- Activation requests create an `ApprovalRequest` bound to:
  - `subject_type = governance.Rule`
  - exact rule UUID
  - exact rule version
  - `action = governance.rule.activate`
  - action payload `{rule_id, version, status: ACTIVE}`
- Activation requires an approved approval request bound to the same rule, version, action and payload hash.
- Successful activation moves `TESTED -> ACTIVE`, records approver metadata and writes an audit event.
- Activation without approval, with pending approval, or with an approval for another rule is rejected.

Latest verification:

```text
uv --native-tls run pytest governance\tests\test_rule_activation_api.py
5 passed in 2.52s

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests
170 passed in 20.64s
```

## Completed Outbox Recovery Slice

Added:

```text
templates/governance/outbox_dashboard.html
governance/tests/test_outbox_recovery_api.py
```

Changed:

```text
governance/services.py
governance/views.py
sharons/urls.py
```

Endpoints:

```text
GET /outbox/
GET /api/v1/outbox/
POST /api/v1/outbox/{message_id}/retry/
POST /api/v1/outbox/{message_id}/dead-letter/
```

Behavior:

- Login-protected outbox recovery dashboard.
- JSON outbox list filtered by status/topic.
- Failed or dead-letter messages can be marked `PENDING` for retry.
- Pending/failed/dead-letter messages can be moved to `DEAD_LETTER`; `SENT` messages cannot.
- Recovery actions require idempotency/correlation headers and write audit events.
- No worker, broker, email delivery, Gmail access or external action was added.

Latest verification:

```text
uv --native-tls run pytest governance\tests\test_outbox_recovery_api.py
7 passed in 4.19s

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests
177 passed in 12.46s
```

## Completed Finance Source Of Truth Slice

Added:

```text
finance/
finance/migrations/0001_initial.py
templates/finance/dashboard.html
finance/tests/test_finance_api.py
```

Changed:

```text
sharons/settings.py
sharons/urls.py
pyproject.toml
```

Endpoints:

```text
GET /finance/
GET /api/v1/finance/records/
POST /api/v1/finance/records/create/
POST /api/v1/finance/records/{record_id}/reconcile/
```

Behavior:

- Internal PostgreSQL-backed financial records.
- Supports income, expense, subscription cost, server cost, API cost and other cost records.
- Tracks amount, currency, source, category, description, external reference, metadata and reconciliation status.
- Duplicate external references are blocked per source.
- Reconciliation status can be updated to `UNRECONCILED`, `RECONCILED`, `DISCREPANCY` or `NEEDS_REVIEW`.
- Dashboard shows income, expenses, net total, unreconciled count, discrepancy count and recent records.
- State-changing finance APIs require idempotency/correlation headers and write audit events.
- No bank/card/Gmail/payment-provider integration, tax logic, accounting automation or external action was added.

Latest verification:

```text
uv --native-tls run python manage.py migrate
Applying finance.0001_initial... OK

uv --native-tls run pytest finance\tests
7 passed in 2.39s

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests
184 passed in 13.46s
```

## Completed Mock Gmail Inbox Workflow Slice

Added:

```text
mailbox/
mailbox/migrations/0001_initial.py
templates/mailbox/inbox_dashboard.html
mailbox/tests/test_mock_email_workflow.py
```

Changed:

```text
sharons/settings.py
sharons/urls.py
pyproject.toml
```

Endpoints:

```text
GET /inbox/
GET /api/v1/mailbox/emails/
POST /api/v1/mailbox/mock-gmail/inbound/
```

Behavior:

- Mock-only email intake; no real Gmail connection.
- Records a governance `InboxEvent` for each unique `(source, external_event_id)`.
- Deterministically classifies emails as `INFORMATION`, `TASK`, `DECISION`, `INVOICE`, `SPAM` or `PERSONAL_SENSITIVE`.
- Creates an internal proposed action such as `MANUAL_REVIEW`, `PROPOSE_TASK`, `REQUEST_INTERNAL_DECISION`, `RESTRICT_AND_REVIEW`, `IGNORE` or `STORE_INFORMATION`.
- Evaluates active deterministic rules against the email event.
- Stores rule decision and reason codes on the mock email.
- Deduplicates repeated external events.
- Writes audit event for ingested mock emails.
- External replies, Gmail access, contact actions and sending are not implemented.

Latest verification:

```text
uv --native-tls run python manage.py migrate
Applying mailbox.0001_initial... OK

uv --native-tls run pytest mailbox\tests
7 passed in 2.23s

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests
191 passed in 13.88s
```

## Completed Mock Payment Provider Slice

Added:

```text
payments/
payments/migrations/0001_initial.py
payments/tests/test_mock_payment_provider.py
```

Changed:

```text
sharons/settings.py
sharons/urls.py
pyproject.toml
```

Endpoints:

```text
POST /api/v1/payments/mock/customers/create/
POST /api/v1/payments/mock/subscriptions/create/
POST /api/v1/payments/mock/subscriptions/{subscription_id}/cancel/
POST /api/v1/payments/mock/charges/create/
POST /api/v1/payments/mock/refunds/create/
POST /api/v1/payments/mock/webhooks/
```

Behavior:

- Provider-neutral `PaymentProvider` interface with only `MockPaymentProvider` available.
- Mock customers, monthly/annual subscriptions, cancellation, charges, refunds and webhook recording.
- Charges can simulate `SUCCEEDED`, `FAILED` and `TIMEOUT`.
- Duplicate webhook events are deduplicated.
- Out-of-order subscription-cancel webhooks are recorded as `OUT_OF_ORDER`.
- State-changing payment APIs require idempotency/correlation headers and write audit events.
- No real payment provider, real card data, external charge, refund, bank/card integration or production action was added.

Latest verification:

```text
uv --native-tls run python manage.py migrate
No migrations to apply.

uv --native-tls run pytest payments\tests
8 passed in 1.45s

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests
214 passed in 15.43s
```

## Completed Research Task Contract Slice

Added:

```text
research/
research/migrations/0001_initial.py
research/tests/test_research_contract_api.py
```

Changed:

```text
sharons/settings.py
sharons/urls.py
pyproject.toml
```

Endpoint:

```text
POST /api/v1/research/contracts/create/
```

Behavior:

- Creates a bounded `ResearchTaskContract` linked to an existing Sharons task, project and read-only project connection.
- Requires the parent task to be `APPROVED`, `ASSIGNED` or `IN_PROGRESS`.
- Stores original request, research question, scope, deliverables, budgets, safety mode and depth mode.
- Requires idempotency/correlation headers and writes an audit event.
- Records `no_external_execution = true`; it does not call the external `research_manager`, write to a product repository or perform literature/database searches.

Latest verification:

```text
uv --native-tls run python manage.py migrate
Applying research.0001_initial... OK

uv --native-tls run pytest research\tests
4 passed in 1.88s

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests
218 passed in 15.30s
```

## Completed Chief Of Staff Gap Closeout Slice

Added:

```text
governance/migrations/0007_approvedactionexecution.py
governance/tests/test_approved_action_executor_api.py
core/tests/test_idempotency_concurrency.py
```

Changed:

```text
governance/models.py
governance/services.py
governance/views.py
governance/urls.py
research/services.py
research/views.py
research/urls.py
research/tests/test_research_contract_api.py
```

Endpoints:

```text
POST /api/v1/approvals/{approval_id}/execute/
GET  /api/v1/research/adapter/status/
```

Behavior:

- Approved approvals can now be executed once through a local executor.
- The first supported approved action is `operations.task.transition`, which calls the existing task transition service.
- Executions are persisted as `ApprovedActionExecution` records and write `governance.approval.executed` audit events.
- Duplicate execution attempts are blocked after the first completed execution.
- Pending approvals cannot execute.
- Research status is exposed as a read-only adapter status endpoint.
- Research status reports contract counts and matching read-only Research Manager project connections.
- Research status does not check, invoke or mutate the external Research Manager.
- Duplicate idempotency key behavior now has database-level concurrency coverage.
- Local CEO reviewer provisioning and authenticated dashboard access were smoke-tested through the service layer and Django test client.

Latest verification:

```text
uv --native-tls run python manage.py migrate
Applying governance.0007_approvedactionexecution... OK

uv --native-tls run pytest governance\tests\test_approved_action_executor_api.py
4 passed in 2.36s

uv --native-tls run pytest core\tests\test_idempotency_concurrency.py
1 passed in 1.95s

uv --native-tls run pytest research\tests
5 passed in 1.75s

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests
224 passed in 16.59s
```

Local CEO reviewer smoke:

```text
setup_ceo_reviewer service: ceo True True True
authenticated UI smoke with localhost: login True, approvals 200, dashboard 200
```

## Completed Product Manager Seed

Ran the core-agent seed command and verified the Product Manager registry record:

```text
product_manager Product Manager ['product', 'requirements', 'user_research', 'prioritization', 'roadmap'] ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL'] 2
```

Verification:

```text
uv --native-tls run pytest operations\tests\test_core_agent_seed.py operations\tests\test_agent_registry_api.py
7 passed
```

## Completed Product Manager Contract Slice

Added:

```text
product/
product/migrations/0001_initial.py
product/tests/test_product_spec_contract_api.py
```

Changed:

```text
sharons/settings.py
sharons/urls.py
pyproject.toml
```

Endpoints:

```text
GET  /api/v1/product/manager/status/
POST /api/v1/product/spec-contracts/create/
```

Behavior:

- Creates bounded `ProductSpecContract` records for Product Manager work.
- Contracts are linked to an existing Sharons task, project and read-only project connection.
- Parent task must be `APPROVED`, `ASSIGNED` or `IN_PROGRESS`.
- Stores spec type, objective, target users, problem statement, success metrics, requirements, constraints, open questions and deliverables.
- Requires idempotency/correlation headers and writes an audit event.
- Records `no_external_write = true`; it does not write to product repositories, publish, deploy or contact external systems.
- Product Manager status is read-only and reports registered agent state, product contracts and read-only product connections without external status checks.

Latest verification:

```text
uv --native-tls run python manage.py migrate
Applying product.0001_initial... OK

uv --native-tls run pytest product\tests
5 passed in 2.06s

uv --native-tls run python manage.py check
System check identified no issues (0 silenced).

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests product\tests
229 passed in 17.28s
```

## Completed Product Manager Draft Artifact Slice

Added:

```text
product/migrations/0002_productspecdraft.py
```

Changed:

```text
product/models.py
product/services.py
product/views.py
product/urls.py
product/tests/test_product_spec_contract_api.py
```

Endpoint:

```text
POST /api/v1/product/spec-contracts/{contract_id}/drafts/create/
```

Behavior:

- Creates internal `ProductSpecDraft` artifacts from a bounded product spec contract.
- Drafts store structured content, assumptions, risks and review status.
- Default draft content is deterministically assembled from the contract objective, users, problem statement, metrics, requirements, constraints, open questions and deliverables.
- Drafts start as `NEEDS_REVIEW`.
- Creating the first draft moves a `READY` contract to `IN_PROGRESS`.
- Requires idempotency/correlation headers and writes an audit event.
- Records `no_external_write = true`; it does not write issues, update repositories, publish, deploy or contact external systems.
- Product Manager status now reports both contract and draft counts.

Latest verification:

```text
uv --native-tls run python manage.py migrate
Applying product.0002_productspecdraft... OK

uv --native-tls run pytest product\tests
9 passed in 2.47s

uv --native-tls run python manage.py makemigrations --check --dry-run
No changes detected

uv --native-tls run python manage.py check
System check identified no issues (0 silenced).

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests product\tests
233 passed in 30.45s
```

## Completed Product Manager Draft Review Stabilization

Changed:

```text
product/services.py
product/views.py
product/urls.py
product/tests/test_product_spec_contract_api.py
```

Endpoint:

```text
POST /api/v1/product/spec-drafts/{draft_id}/review/
```

Behavior:

- Product spec drafts can now be internally approved or rejected.
- Approval moves the draft to `APPROVED` and the contract to `COMPLETED`.
- Rejection moves the draft to `REJECTED` and leaves the contract `IN_PROGRESS`.
- Reviewed drafts cannot be reviewed a second time with a new idempotency key.
- Review decisions are idempotent for repeated identical requests.
- Review metadata is stored in the draft content and an audit event is written.
- No external product repository write, issue creation, publishing or deployment was added.

Verification:

```text
uv --native-tls run pytest product\tests
13 passed in 1.79s
```

## Completed Executive Assistant Brief Slice

Added:

```text
executive_assistant/
executive_assistant/migrations/0001_initial.py
executive_assistant/tests/test_executive_brief_api.py
```

Changed:

```text
sharons/settings.py
sharons/urls.py
pyproject.toml
```

Endpoints:

```text
GET  /api/v1/executive-assistant/status/
POST /api/v1/executive-assistant/briefs/create/
```

Behavior:

- Creates internal `ExecutiveBrief` artifacts for weekly review prep, follow-ups and inbox triage.
- Briefs summarize internal Sharons state: pending approvals, blocked tasks, unverified work and mock inbox items.
- Briefs record agenda items, follow-ups, decisions needed and inbox items.
- Requires idempotency/correlation headers and writes audit events.
- Records `no_external_send = true`; it does not send email, schedule meetings, contact people or use a real calendar.
- Status endpoint is read-only and reports registered-agent state, brief count, pending approvals and mock inbox count.
- Verified seeded `executive_assistant` agent exists with low-risk capabilities and forbidden external actions.

Latest verification:

```text
uv --native-tls run python manage.py migrate
Applying executive_assistant.0001_initial... OK

uv --native-tls run pytest executive_assistant\tests
5 passed in 1.97s

uv --native-tls run python manage.py makemigrations --check --dry-run
No changes detected

uv --native-tls run python manage.py check
System check identified no issues (0 silenced).

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests product\tests executive_assistant\tests
242 passed in 31.52s
```

## Completed Executive Assistant Task Proposal Slice

Added:

```text
executive_assistant/migrations/0002_executivebrieftaskproposal.py
```

Changed:

```text
executive_assistant/models.py
executive_assistant/services.py
executive_assistant/views.py
executive_assistant/urls.py
executive_assistant/tests/test_executive_brief_api.py
```

Endpoint:

```text
POST /api/v1/executive-assistant/briefs/{brief_id}/tasks/propose/
```

Behavior:

- Converts taskable Executive Brief follow-ups into internal draft Sharons tasks.
- Uses deterministic external keys per brief follow-up for repeatability.
- Creates required manual acceptance criteria for each proposed follow-up task.
- Assigns proposed tasks to `executive_assistant`.
- Persists `ExecutiveBriefTaskProposal` records and writes audit events.
- Requires idempotency/correlation headers.
- Records `no_external_send = true`; it does not send email, contact people, schedule meetings or use real calendar access.

Latest verification:

```text
uv --native-tls run python manage.py migrate
Applying executive_assistant.0002_executivebrieftaskproposal... OK

uv --native-tls run pytest executive_assistant\tests
8 passed in 3.52s

uv --native-tls run python manage.py makemigrations --check --dry-run
No changes detected

uv --native-tls run python manage.py check
System check identified no issues (0 silenced).

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests product\tests executive_assistant\tests
245 passed in 36.79s
```

## Completed Executive Assistant Task Proposal Review Slice

Added:

```text
executive_assistant/migrations/0003_executivebrieftaskproposal_review_status.py
```

Changed:

```text
executive_assistant/models.py
executive_assistant/services.py
executive_assistant/views.py
executive_assistant/urls.py
executive_assistant/tests/test_executive_brief_api.py
```

Endpoint:

```text
POST /api/v1/executive-assistant/task-proposals/{proposal_id}/review/
```

Behavior:

- Executive Assistant task proposals now have a review lifecycle: `PENDING`, `ACCEPTED`, `DISMISSED`.
- Accepting a pending proposal moves the proposed task from `DRAFT` to `PLANNED`.
- Dismissing a pending proposal moves the proposed task from `DRAFT` to `CANCELLED`.
- Review actions are idempotent for repeated identical requests.
- Already-reviewed proposals cannot be reviewed again with a new idempotency key.
- Review decisions write audit events.
- No email, calendar, scheduling or external contact action was added.

Latest verification:

```text
uv --native-tls run python manage.py migrate
Applying executive_assistant.0003_executivebrieftaskproposal_review_status... OK

uv --native-tls run pytest executive_assistant\tests
12 passed in 2.23s

uv --native-tls run python manage.py makemigrations --check --dry-run
No changes detected

uv --native-tls run python manage.py check
System check identified no issues (0 silenced).

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests product\tests executive_assistant\tests
249 passed in 24.59s
```

## Completed Executive Assistant Read-Only Queue Slice

Changed:

```text
executive_assistant/views.py
executive_assistant/urls.py
executive_assistant/tests/test_executive_brief_api.py
```

Endpoints:

```text
GET /api/v1/executive-assistant/briefs/
GET /api/v1/executive-assistant/task-proposals/
```

Behavior:

- Lists Executive Assistant briefs with optional `brief_type`, `status` and `limit` filters.
- Lists task proposals with optional `review_status`, `brief_id` and `limit` filters.
- Validates filters and returns stable machine-readable errors.
- Read-only; no idempotency headers are required and no audit events or external actions are created.
- Keeps external email, calendar, scheduling and contact access disabled.

Latest verification:

```text
uv --native-tls run python manage.py makemigrations --check --dry-run
No changes detected

uv --native-tls run pytest executive_assistant\tests
16 passed in 2.53s

uv --native-tls run python manage.py check
System check identified no issues (0 silenced).

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests product\tests executive_assistant\tests
253 passed in 16.84s
```

## Completed Executive Assistant Dashboard Slice

Added:

```text
templates/executive_assistant/dashboard.html
```

Changed:

```text
executive_assistant/views.py
executive_assistant/tests/test_executive_brief_api.py
sharons/urls.py
```

Endpoint:

```text
GET /executive-assistant/
```

Behavior:

- Login-protected server-rendered Executive Assistant dashboard.
- Shows recent Executive Briefs and task proposals in read-only tables.
- Filters briefs by `brief_type` and `status`.
- Filters task proposals by `review_status`.
- Displays follow-up, decision and inbox counts from stored internal brief data.
- Does not create audit events because it is read-only.
- Does not send email, access real Gmail, schedule meetings, contact people or use calendar access.

Latest verification:

```text
uv --native-tls run pytest executive_assistant\tests
19 passed in 3.69s

uv --native-tls run python manage.py makemigrations --check --dry-run
No changes detected

uv --native-tls run python manage.py check
System check identified no issues (0 silenced).

uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests product\tests executive_assistant\tests
256 passed in 19.47s
```

## Useful Commands

Run:

```powershell
uv --native-tls run pytest operations\tests
uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests product\tests executive_assistant\tests
```

`uv --system-certs` and some management-command argument forms have hit local `helper_unknown_error` runner failures in this environment. `uv --native-tls` has worked reliably.

## Known Remaining Gaps

- Real Gmail access remains disabled and requires explicit approval.
- Real payment-provider selection/connection remains deferred and requires explicit approval.
- External Research Manager invocation remains disabled and requires explicit approval.
- Production deployment, product repository writes and external side effects remain disabled and require explicit approval.

## Safety Reminder

Before adding anything that touches Gmail, external contacts, product repositories, production systems, payments, personal-sensitive data, or new infrastructure, stop and request explicit user approval.
