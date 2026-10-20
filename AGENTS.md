# Codex Execution Instructions — Sharons AI Organization

## Mission

Create a new, independent Django project named `sharons`. It is the operating system of an AI-native company that develops and manages current and future software projects. The Chief of Staff is the company-level operational orchestrator. Research Manager is a specialist subsystem invoked by the Chief of Staff; it is not a competing company-level orchestrator.

Sharons owns company strategy, portfolio state, governance, agents, approvals, organizational memory and project coordination. It must not own the source code or operational database of products such as Mental Trainer or Compass. Products remain separate repositories/systems and connect through versioned project adapters.

The implementation serves a project-development factory. The first 90-day business objectives are:

1. Mental Trainer commercial readiness on desktop and mobile.
2. A PostgreSQL-backed financial single source of truth.
3. Zero-touch administration with a weekly 30-minute CEO review.
4. A deterministic Rules Engine learned through structured interviews and operated with human approval.

Read `docs/chief_of_staff/SPEC_HE.md`, `docs/chief_of_staff/ENGINEERING_PLAN_HE.md`, and every nested `AGENTS.md` that applies to the files being changed. For research work also read `docs/research/RESEARCH_MANAGER_SPEC.md`. This file governs company-wide implementation order and safety constraints; the domain specifications govern intent inside their scope.

## Instruction hierarchy

- This root file applies to the entire Sharons repository.
- `agents/research/AGENTS.md` adds research-specific rules inside the research subtree.
- A nested file may specialize behavior but may not weaken root safety, authorization, audit, privacy, architecture or approval rules.
- If instructions conflict, stop and report the exact conflict. Do not silently choose the more permissive instruction.
- Chief of Staff owns company-level prioritization, resource allocation and escalation.
- Research Manager owns the internal research workflow after receiving an approved Research Task Contract.
- Research Supervisor may redirect or stop research within its assigned scope and budget; it may not change company strategy, create a permanent agent, purchase access or contact an external person without the required approval.

## Non-negotiable decisions

- Build a new repository; do not place Sharons under Compass and do not copy Compass application code into Sharons.
- Treat Compass, Mental Trainer and future products as external projects registered in a Project Registry.
- Use PostgreSQL from the start.
- Use Django templates and server-rendered forms. Do not introduce React.
- Keep business logic in models/services. Views remain thin; the frontend displays state and collects input.
- Do not let the frontend directly determine permissions, transitions, priority or completion.
- The Rules Engine is deterministic. Never use an LLM as the authorization boundary.
- Do not use `eval`, executable expressions or free-text Boolean conditions in rules.
- Every state-changing request requires an idempotency key and correlation ID.
- Every material state change creates an audit event.
- Never create an inline task, subtask or step from empty or whitespace-only text.
- No autonomous spending, external publishing, contacting a person, legal commitment, access expansion to personal data, deletion or production-system change.
- Those actions require a CEO approval bound to the exact object version and action-payload hash.
- Gmail is the notification channel. Initial approvals are completed in an authenticated dashboard, not by interpreting free-text email replies.
- Payment-provider selection is deferred. Implement only a provider-neutral interface and a mock provider.
- Never store card data.
- Every completed task requires acceptance criteria, evidence and verification. Otherwise use `DELIVERED_UNVERIFIED`.
- Limit automated agent retries to two.
- Limit concurrent agents to three per project.
- Reallocation of more than 20% of weekly team time between quarterly objectives requires CEO approval.
- Classify data as `PUBLIC`, `INTERNAL`, `CONFIDENTIAL` or `PERSONAL_SENSITIVE`.
- Access to `PERSONAL_SENSITIVE` data must be explicitly allowlisted and audited.

## Initial repository structure

Create the smallest structure needed for the approved vertical slice. This is the target direction, not permission to scaffold every module immediately:

```text
sharons/
├── manage.py
├── sharons/
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── core/
│   ├── admin.py
│   ├── apps.py
│   ├── models.py
│   ├── services.py
│   ├── urls.py
│   ├── views.py
│   ├── auth.py
│   ├── permissions.py
│   ├── events.py
│   ├── memory.py
│   ├── routing.py
│   └── tests/
├── portfolio/
│   ├── models.py
│   ├── services.py
│   └── tests/
├── governance/
│   ├── models.py
│   ├── services.py
│   └── tests/
├── operations/
│   ├── models.py
│   ├── services.py
│   └── tests/
├── integrations/
│   ├── projects/
│   ├── gmail/
│   └── payments/
└── agents/
    ├── base.py
    ├── registry.py
    ├── mail_manager.py
    ├── self_manage.py
    ├── task_commander.py
    ├── administrative_agent.py
    ├── assessment.py
    └── research/
        └── AGENTS.md
```

Do not create product-specific business logic inside Sharons. A product integration belongs behind `integrations/projects/` and a portfolio record.

## Required working method

### 1. Confirm the greenfield workspace

Start with read-only inspection:

- Locate and read repository-level and nested `AGENTS.md` files.
- Run `git status --short` and preserve any user files already present.
- Confirm whether the directory is empty, an initialized Git repository, or already contains a partial Sharons scaffold.
- Inspect any existing dependency, settings, model, migration and test files before proposing additions.
- If code already exists, run its tests and record the baseline.
- Confirm that this repository is not nested inside Compass or another product repository.
- Identify how external project repositories will be referenced without copying their source code.

Do not alter code during this inspection phase.

### 2. Produce an implementation assessment

Before the first material code change, create `docs/cos/IMPLEMENTATION_ASSESSMENT.md` containing:

- Current architecture and relevant files.
- Existing files, if any, and the proposed greenfield scaffold.
- Gaps against the specifications.
- Proposed additive file changes.
- PostgreSQL setup and initial-migration risk.
- Security and privacy risks.
- Test baseline, including an explicit note if no tests existed.
- A phase-by-phase implementation plan.
- Explicit decisions that still require the user.

Do not ask the user about decisions already stated in this file.

### 3. Stop at architectural gates

Request user approval before:

- Importing or copying code/data from Compass, Mental Trainer or another project.
- Changing the approved repository boundaries.
- Introducing a new framework, broker or infrastructure service.
- Changing authentication.
- Migrating real data.
- Enabling Gmail access.
- Deploying, publishing or changing a production system.
- Connecting a real payment provider.

The approved baseline uses separate `portfolio`, `governance` and `operations` Django apps. Codex may propose a smaller first scaffold, but it must preserve these logical boundaries and explain any temporary consolidation.

### 4. Build vertical slices

Implement one end-to-end path at a time. Do not create every model before proving a usable flow.

Required first slice:

```text
POST /api/v1/cos/intake/
  → validate request
  → connect it to an approved objective
  → create a DRAFT task
  → create an append-only audit event
  → return task ID, correlation ID and status
```

This slice must not require an LLM, Gmail, a worker or a new frontend framework.

## Implementation phases

### Phase 0 — Greenfield design and PostgreSQL setup plan

Deliver:

- Architecture assessment.
- Workspace and Git baseline report.
- Proposed minimal Django scaffold and dependency list.
- PostgreSQL provisioning, configuration, backup and recovery plan.
- An ADR confirming repository boundaries: Sharons owns company operations; product repositories own product code and data.
- An ADR defining Project Registry and connector contracts.

Do not import product data, connect external repositories or modify production configuration in this phase.

### Phase 1 — Operational core

Implement or extend:

- StrategyVersion.
- Objective and KeyResult.
- Plan.
- Task and AcceptanceCriterion.
- TaskDependency.
- AgentDefinition and AgentRun.
- Evidence.
- Project and ProjectConnection records.
- Project repository references and capability declarations.
- Task state-transition service.
- Prioritization service.
- Agent registry filtering by capability, data classification, risk and capacity.

Task states:

```text
DRAFT
PLANNED
PENDING_APPROVAL
APPROVED
ASSIGNED
IN_PROGRESS
BLOCKED
DELIVERED_UNVERIFIED
VERIFYING
COMPLETED
FAILED
CANCELLED
```

Enforce transitions in the service layer. Do not permit arbitrary model status writes through views.

Priority formula:

```text
(impact × urgency × strategic_fit × confidence) / (effort × risk)
```

Use scores from 1 through 5 and store each component plus the computed score.

### Phase 2 — Deterministic governance

Implement or extend:

- Versioned Rule.
- RuleTestCase.
- RuleEvaluation.
- ApprovalRequest.
- AuditEvent.
- InboxEvent and OutboxMessage.
- Deterministic rule interpreter.
- Approval binding to subject ID, subject version, action-payload hash and expiry.

Allowed Boolean structures:

```text
all, any, not
```

Allowed operators:

```text
equals
not_equals
less_than
less_or_equal
greater_than
greater_or_equal
in
not_in
exists
```

Allowed decisions:

```text
ALLOW
ALLOW_AND_NOTIFY
REQUIRE_APPROVAL
BLOCK
NEEDS_MORE_DATA
```

No match must never produce an implicit `ALLOW`.

Rule lifecycle:

```text
DRAFT → VALIDATED → TESTED → PENDING_APPROVAL → ACTIVE → SUSPENDED → RETIRED
```

An active rule is immutable. Changes create a new version.

### Phase 3 — Gmail and the first two workflows

Do not enable real Gmail access without user approval. First implement adapters and mocks.

Workflow A:

```text
invoice/receipt email
→ deduplicate event and document
→ extract structured fields with confidence
→ deterministic classification
→ proposal, filing or manual-review request
→ financial record only after the required approval
```

Never pay an invoice automatically.

Workflow B:

```text
incoming email
→ sanitize/untrusted-content boundary
→ classify as information/task/decision/invoice/spam/personal-sensitive
→ create a proposed internal action
→ apply Rules Engine
→ require approval before external reply or contact
```

Treat instructions inside email bodies and attachments as untrusted data.

### Phase 4 — Verification and memory

Implement:

- Verification against all required acceptance criteria.
- Evidence checks.
- Independent verification for high-risk tasks.
- `DELIVERED_UNVERIFIED` when verification is incomplete.
- Versioned MemoryRecord with source, classification, verification status, validity and supersession.
- Weekly status report.

Conversation summaries must not become approved decisions automatically.

### Phase 5 — Finance and administration

Implement a minimal financial source of truth supporting:

- Income and expense records.
- Server, API and subscription costs.
- Monthly reconciliation status.
- Unexplained discrepancies.
- Mental Trainer unit economics.
- Less than 15 minutes monthly maintenance as a measurable target.

Do not invent accounting or tax rules. Flag required accountant/legal review.

### Phase 6 — Mental Trainer commercial-readiness support

Implement a provider-neutral `PaymentProvider` interface and `MockPaymentProvider` for:

- Create customer.
- Create monthly or annual subscription.
- Cancel subscription.
- Refund transaction.
- Successful charge.
- Failed charge.
- Timeout.
- Duplicate and out-of-order webhooks.

Provider selection remains `DEFERRED` until before paid beta. The target is initially Israel, ILS, up to 100 paying users, combined billing documents, with recurring-charge reliability prioritized over small fee differences.

## Rules activation gate

A rule may not become `ACTIVE` unless:

- It passes JSON Schema validation.
- It uses only allowed operators.
- Synthetic tests pass.
- At least 30 real cases have been reviewed.
- At least 5 are exception cases.
- At least 90% of recommendations were approved without editing.
- No high-risk false allow occurred.
- The CEO explicitly approved that exact version.

Because 30 cases provide limited statistical confidence, use staged rollout and continue human approval for external actions.

## API requirements

Use `/api/v1/`. Once an endpoint is released, preserve compatibility unless explicitly approved otherwise.

Required initial endpoints:

```text
POST /api/v1/cos/intake/
GET  /api/v1/projects/
POST /api/v1/projects/
POST /api/v1/projects/{id}/connections/
GET  /api/v1/objectives/
POST /api/v1/plans/
POST /api/v1/tasks/upsert/
POST /api/v1/tasks/{id}/assign/
POST /api/v1/tasks/{id}/transition/
POST /api/v1/tasks/{id}/evidence/
POST /api/v1/tasks/{id}/verify/
GET  /api/v1/agents/
POST /api/v1/agents/invoke/
POST /api/v1/rules/events/
POST /api/v1/rules/evaluate/
POST /api/v1/rules/proposals/
POST /api/v1/rules/{id}/validate/
POST /api/v1/rules/{id}/test/
POST /api/v1/rules/{id}/activate/
GET  /api/v1/approvals/
POST /api/v1/approvals/{id}/decision/
POST /api/v1/history/search/
POST /api/v1/events/
POST /api/v1/conversation/finalize/
GET  /api/v1/reports/weekly/
GET  /api/v1/audit/
```

Validate request and response schemas. Use UTC timestamps. Return stable machine-readable error codes. Never expose raw internal exceptions or secrets.

## Reliability requirements

- Use database transactions for state change plus outbox creation.
- Deduplicate external events by source and external-event ID.
- Fingerprint invoices to catch the same document from different emails.
- Use exponential backoff with jitter only for transient failures.
- Never retry validation, permission or policy failures automatically.
- Preserve failed messages in a dead-letter state.
- Use optimistic concurrency or expected-version checks.
- Keep PostgreSQL as the source of truth; workers are not authoritative.

Do not introduce a queue/broker product until the user approves the infrastructure choice. Build the outbox contract independently of that choice.

## Dashboard requirements

Use Django templates and Django forms for:

- Executive overview.
- Objectives and critical path.
- Tasks.
- Approval inbox.
- Rules and test results.
- Agents and current capacity.
- Finance and reconciliation exceptions.
- Audit search.

Enable CSRF. Use POST/Redirect/GET. The system must remain functionally usable without client-side JavaScript.

## Testing requirements

Use the project's selected test framework and document the convention before adding tests. Add tests for:

- Every allowed and forbidden task transition.
- Empty and whitespace-only task/subtask/step rejection.
- Rule operators and nested Boolean structures.
- No-match default behavior.
- Approval expiry, version mismatch and payload mismatch.
- Duplicate Gmail event and duplicate invoice.
- Prompt-injection content inside email.
- Outbox recovery after worker failure.
- Agent result without evidence.
- Concurrent task update.
- Data-classification access denial.
- Mock-payment duplicate and out-of-order webhooks.

Run the smallest relevant tests after each change and the complete suite before handoff.

## Documentation deliverables

Maintain:

```text
docs/cos/IMPLEMENTATION_ASSESSMENT.md
docs/cos/ARCHITECTURE.md
docs/cos/API.md
docs/cos/DATA_MODEL.md
docs/cos/RULES_DSL.md
docs/cos/SECURITY.md
docs/cos/OPERATIONS.md
docs/cos/TEST_REPORT.md
```

Record important structural choices as ADRs. Include migration, rollback and recovery procedures.

## Reporting format to the user

Lead with the outcome. For every implementation phase report:

- What works now.
- Files changed.
- Tests run and exact result.
- Pre-existing failures separately from new failures.
- Risks or assumptions.
- Decision required from the user, if any.
- Next safe step.

Do not claim completion from code inspection alone. Do not claim a test passed unless it was executed successfully.

## Pre-mortem checks before each phase

Ask internally:

1. Could this change bypass approval?
2. Could it create a duplicate external action?
3. Could it leak confidential or personal-sensitive data?
4. Could a model-written output be mistaken for verified evidence?
5. Could it blur the boundary between Sharons and a product repository?
6. Is the team building infrastructure while Mental Trainer receives no usable progress?

If any answer is yes or uncertain, mitigate or stop at the appropriate approval gate.

## First Codex task

Perform Phase 0 only.

Do not implement the full system in the first pass. Confirm the greenfield repository, inspect any files already present, create the implementation assessment and the two boundary ADRs, and report the proposed minimal scaffold and first vertical slice. Wait for user approval before scaffolding the Django project, connecting PostgreSQL, importing product data, adding infrastructure, enabling Gmail or performing any production action.

## Efficiency, Test, Continue and Action Logging Policy

Optimize implementation for useful progress while preserving correctness and safety.

### Testing

* Do not run the full test suite after every change.
* For small or local changes, run only tests directly relevant to the affected code.
* Run module-level tests after completing a meaningful functional unit.
* Run the full test suite only at milestone boundaries, before merge/release, after cross-cutting architectural changes, or when broader regression is reasonably suspected.
* Documentation-only, comment-only, formatting-only, and other non-functional changes normally require no tests.
* Do not rerun previously passing tests unless affected code, dependencies, configuration, or behavior changed.
* Never skip verification required for safety-critical, authorization, persistence, or state-transition behavior.

### Context and repository inspection

* Do not repeatedly rediscover context already documented in `AGENTS.md`, specifications, engineering plans, ADRs, `IMPLEMENTATION_ASSESSMENT.md`, or `IMPLEMENTATION_STATUS.md`.
* Read applicable project documentation first and use it as the source of truth.
* Inspect the smallest relevant set of files before broad repository searches.
* Do not repeatedly read unchanged files without a concrete need.
* Do not refactor or redesign unrelated working areas.

### Implementation status tracking

* `IMPLEMENTATION_STATUS.md` is the persistent operational state file for ongoing development.
* If `IMPLEMENTATION_STATUS.md` does not exist, create it before the next meaningful implementation work unit.
* After creation, maintain it continuously.
* Do not require the user to remember or restate implementation progress that can be derived from the repository and this file.
* `IMPLEMENTATION_STATUS.md` must contain at minimum:

  * `Last Completed`
  * `Current State`
  * `Next Step`
  * `Blockers`
  * `Important Decisions`
* Update only materially changed information. Do not rewrite or summarize the full project history after every step.
* The file must be sufficient for a future session to resume work without reconstructing previous conversations.

### Implementation workflow

* Prefer coherent work units over many tiny steps.
* Do not stop after every small change merely to report progress.
* Continue until a meaningful milestone, real blocker, missing decision, or justified broader verification point.
* If a decision already exists in project documentation, use it instead of asking the user again.
* Do not create unnecessary documentation, abstractions, infrastructure, or refactors.

### Continue behavior

When the user says `continue`:

1. Read `IMPLEMENTATION_STATUS.md` first.
2. Determine the next unresolved implementation step from:

   * `IMPLEMENTATION_STATUS.md`,
   * the applicable SPEC,
   * the engineering plan,
   * and the current repository state.
3. Do not ask the user what to do next unless a genuine product, business, architecture, security, or authorization decision is missing.
4. Do not redo completed work.
5. Do not re-analyze the whole project.
6. Do not repeat previous explanations or summaries unless necessary for the current step.
7. Execute the smallest meaningful next implementation step.
8. Run only the minimum relevant verification.
9. Update `IMPLEMENTATION_STATUS.md` after the work unit.
10. Continue autonomously until a meaningful milestone, real blocker, or genuine user decision is reached.

The user is not expected to know or specify the next implementation step. Determining the next step is part of the agent's responsibility.

### Action logging and automatic status updates

After every meaningful implementation action:

* Record what was actually changed.
* Record the files or components materially affected.
* Record verification or tests actually performed and their result.
* Record any new blocker, risk, dependency, or unresolved decision discovered.
* Update `IMPLEMENTATION_STATUS.md` automatically. Do not wait for the user to request the update.
* Do not mark work as completed merely because code was written. Completion requires the verification required by the applicable acceptance criteria.
* Do not rewrite historical status unnecessarily; update only information that materially changed.

### Communication

At the end of a meaningful work unit, report only:

1. What was completed.
2. Verification actually performed and its result.
3. Any blocker or decision requiring user input.
4. The next implementation step.

Do not repeat project history or previously documented decisions unless directly relevant.

### Guiding rule

Minimize unnecessary work, tool calls, repository scanning, repeated testing, repeated analysis, and repetitive explanation — but never at the expense of correctness, safety, required verification, traceability, or recoverability.
