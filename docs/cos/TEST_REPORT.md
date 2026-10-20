# Test Report

Date: 2026-09-16

## Current Result

The current Chief of Staff scaffold passes Django system checks, applies the approval permission migration, and the implemented core, operations, portfolio and governance test suites pass. Governance now includes approval listing, decision API, server-rendered approval dashboard, login requirement, decision-permission coverage, approval permission group provisioning and initial CEO reviewer setup coverage.

Update on 2026-09-17: added the read-only `GET /api/v1/audit/` endpoint and focused tests. The earlier pytest stall was caused by local Postgres not running; after starting it with `docker compose up -d postgres`, the suite passed.

Latest update on 2026-09-20: closed the remaining local Chief of Staff verification gaps before continuing Product Manager work. The approved-action executor now supports approved task transitions, duplicate execution protection is covered, idempotency duplicate-key concurrency behavior is covered, the CEO reviewer flow was smoke-tested locally, and the Research Manager adapter status endpoint is read-only.

Product Manager update on 2026-09-20: added and verified the bounded Product Manager contract slice, internal draft artifact slice and draft review stabilization. Product spec contracts link an approved or active Sharons task to a registered project through a read-only project connection, store product requirements metadata, and explicitly record `no_external_write = true`. Product spec drafts are generated as internal review-gated artifacts from those contracts, record assumptions and risks, and can be approved or rejected without writing to product repositories or external systems.

Executive Assistant update on 2026-09-20: added and verified the first bounded Executive Assistant slices. Executive briefs summarize internal Sharons state, pending approvals, blocked work, unverified work and mock inbox items for weekly review prep, follow-ups and inbox triage. Brief follow-ups can now be converted into internal draft Sharons tasks with deterministic external keys and acceptance criteria, then accepted into planning or dismissed. Briefs and task proposals are listable through read-only filtered endpoints and a login-protected server-rendered dashboard at `/executive-assistant/`. Briefs and proposals explicitly record `no_external_send = true`; no email, calendar, contact or external communication was added. The implemented core, operations, portfolio, governance, finance, mailbox, payments, research, product and executive assistant suites pass with 256 tests.

## Environment

Local PostgreSQL was started with:

```powershell
docker compose up -d postgres
```

`sharons/settings.py` now loads a local `.env` file when present. The local `.env` is ignored by Git and was created from `.env.example` for development testing.

## Commands Run

```powershell
uv --native-tls run python manage.py migrate
```

Result:

```text
Applying research.0001_initial... OK
```

```powershell
uv --native-tls run pytest research\tests
```

Result:

```text
4 passed in 1.88s
```

```powershell
uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests
```

Result:

```text
224 passed in 16.59s
```

```powershell
uv --native-tls run python manage.py migrate
```

Result:

```text
Applying product.0001_initial... OK
```

```powershell
uv --native-tls run pytest product\tests
```

Result:

```text
5 passed in 2.06s
```

```powershell
uv --native-tls run python manage.py check
```

Result:

```text
System check identified no issues (0 silenced).
```

```powershell
uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests product\tests
```

Result:

```text
229 passed in 17.28s
```

```powershell
uv --native-tls run python manage.py migrate
```

Result:

```text
Applying product.0002_productspecdraft... OK
```

```powershell
uv --native-tls run pytest product\tests
```

Result:

```text
9 passed in 2.47s
```

```powershell
uv --native-tls run python manage.py makemigrations --check --dry-run
```

Result:

```text
No changes detected
```

```powershell
uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests product\tests
```

Result:

```text
233 passed in 30.45s
```

```powershell
uv --native-tls run pytest product\tests
```

Result:

```text
13 passed in 1.79s
```

```powershell
uv --native-tls run python manage.py migrate
```

Result:

```text
Applying executive_assistant.0001_initial... OK
```

```powershell
uv --native-tls run pytest executive_assistant\tests
```

Result:

```text
5 passed in 1.97s
```

```powershell
uv --native-tls run python manage.py makemigrations --check --dry-run
```

Result:

```text
No changes detected
```

```powershell
uv --native-tls run python manage.py check
```

Result:

```text
System check identified no issues (0 silenced).
```

```powershell
uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests product\tests executive_assistant\tests
```

Result:

```text
242 passed in 31.52s
```

```powershell
uv --native-tls run python manage.py migrate
```

Result:

```text
Applying executive_assistant.0002_executivebrieftaskproposal... OK
```

```powershell
uv --native-tls run pytest executive_assistant\tests
```

Result:

```text
8 passed in 3.52s
```

```powershell
uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests product\tests executive_assistant\tests
```

Result:

```text
245 passed in 36.79s
```

```powershell
uv --native-tls run python manage.py migrate
```

Result:

```text
Applying executive_assistant.0003_executivebrieftaskproposal_review_status... OK
```

```powershell
uv --native-tls run pytest executive_assistant\tests
```

Result:

```text
12 passed in 2.23s
```

```powershell
uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests product\tests executive_assistant\tests
```

Result:

```text
249 passed in 24.59s
```

```powershell
uv --native-tls run python manage.py makemigrations --check --dry-run
```

Result:

```text
No changes detected
```

```powershell
uv --native-tls run pytest executive_assistant\tests
```

Result:

```text
16 passed in 2.53s
```

```powershell
uv --native-tls run python manage.py check
```

Result:

```text
System check identified no issues (0 silenced).
```

```powershell
uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests product\tests executive_assistant\tests
```

Result:

```text
253 passed in 16.84s
```

```powershell
uv --native-tls run pytest executive_assistant\tests
```

Result:

```text
19 passed in 3.69s
```

```powershell
uv --native-tls run python manage.py makemigrations --check --dry-run
```

Result:

```text
No changes detected
```

```powershell
uv --native-tls run python manage.py check
```

Result:

```text
System check identified no issues (0 silenced).
```

```powershell
uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests research\tests product\tests executive_assistant\tests
```

Result:

```text
256 passed in 19.47s
```

```powershell
uv --native-tls run pytest governance\tests\test_approved_action_executor_api.py
```

Result:

```text
4 passed in 2.36s
```

```powershell
uv --native-tls run pytest core\tests\test_idempotency_concurrency.py
```

Result:

```text
1 passed in 1.95s
```

```powershell
uv --native-tls run pytest research\tests
```

Result:

```text
5 passed in 1.75s
```

Local CEO reviewer smoke:

```text
setup_ceo_reviewer service: ceo True True True
authenticated UI smoke with localhost: login True, approvals 200, dashboard 200
```

```powershell
uv --native-tls run python manage.py migrate
```

Result:

```text
No migrations to apply.
```

```powershell
uv --native-tls run pytest payments\tests
```

Result:

```text
8 passed in 1.45s
```

```powershell
uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests finance\tests mailbox\tests payments\tests
```

Result:

```text
214 passed in 15.43s
```

```powershell
uv --native-tls run python manage.py check
```

Result:

```text
System check identified no issues (0 silenced).
```

Attempted:

```powershell
uv --system-certs run pytest core\tests operations\tests portfolio\tests governance\tests
```

Result:

```text
Failed to create unified exec process: helper_unknown_error: setup refresh had errors
```

Attempted:

```powershell
uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests
uv --native-tls run pytest governance\tests\test_audit_api.py
```

Result: both commands collected tests and then stalled after collection, so they were interrupted before pass/fail results.

Resolution:

```powershell
docker compose up -d postgres
uv --native-tls run pytest governance\tests\test_audit_api.py
```

Result:

```text
5 passed in 1.42s
```

```powershell
uv --native-tls run pytest core\tests\test_executive_dashboard.py
```

Result:

```text
2 passed in 2.33s
```

```powershell
uv --native-tls run pytest operations\tests\test_task_dashboard.py
```

Result:

```text
7 passed in 3.37s
```

```powershell
uv --native-tls run pytest core\tests\test_weekly_review.py
```

Result:

```text
3 passed in 6.88s
```

```powershell
uv --native-tls run pytest governance\tests\test_rule_lifecycle_api.py
```

Result:

```text
5 passed in 1.32s
```

```powershell
uv --native-tls run pytest governance\tests\test_rule_activation_api.py
```

Result:

```text
5 passed in 2.52s
```

```powershell
uv --native-tls run pytest governance\tests\test_outbox_recovery_api.py
```

Result:

```text
7 passed in 4.19s
```

```powershell
uv --native-tls run python manage.py migrate
```

Result:

```text
Applying finance.0001_initial... OK
```

```powershell
uv --native-tls run pytest finance\tests
```

Result:

```text
7 passed in 2.39s
```

```powershell
uv --native-tls run python manage.py migrate
```

Result:

```text
Applying mailbox.0001_initial... OK
```

```powershell
uv --native-tls run pytest mailbox\tests
```

Result:

```text
7 passed in 2.23s
```

```powershell
uv --native-tls run python manage.py migrate
```

Result:

```text
Applying governance.0006_ruletestcase... OK
```

```powershell
uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests
```

Result:

```text
191 passed in 13.88s
```

```powershell
uv --native-tls run python manage.py check
```

Result:

```text
System check identified no issues (0 silenced).
```

```powershell
uv --native-tls run python manage.py migrate
```

Result:

```text
Applying governance.0002_approvalrequest... OK
```

```powershell
uv --native-tls run pytest core\tests operations\tests portfolio\tests governance\tests
```

Result:

```text
97 passed in 12.24s
```

```powershell
uv --native-tls run python manage.py provision_approval_permissions
```

Result:

```text
approval_viewers: view_approvalrequest
approval_deciders: decide_approvalrequest, view_approvalrequest
Provisioned approval permission groups.
```

```powershell
uv --native-tls run python manage.py help setup_ceo_reviewer
```

Result: command help printed successfully, including `--username`, `--email` and `--password`.

Attempted:

```powershell
uv --native-tls run python manage.py setup_ceo_reviewer --username=ceo --email=ceo@example.local
```

Result: blocked by the command runner with `helper_unknown_error` before Django executed the command. Focused command tests pass.

## Coverage Verified

- Chief of Staff intake creates a `DRAFT` task and audit event.
- Intake rejects whitespace-only titles, missing correlation IDs, inactive objectives and conflicting idempotency keys.
- Task transition service enforces allowed and forbidden transitions.
- Task upsert API validates task and acceptance-criterion content.
- Objectives API and Project Registry API pass their current tests.
- Deterministic Rules Engine tests pass.
- ApprovalRequest binds subject version and action payload hash.
- Approval decisions reject expired, stale, tampered and already-decided requests.
- Approval list and decision API endpoints pass focused tests.
- Approval inbox and detail dashboard pages pass focused tests.
- Approval dashboard requires login.
- Approval dashboard decisions require `governance.decide_approvalrequest`.
- Approval permission group provisioning command passes focused tests.
- Initial CEO reviewer setup service and command pass focused tests.
- Authenticated local CEO reviewer smoke test passed through the service layer and Django test client.
- Concurrent duplicate idempotency key creation is covered at the database constraint level.
- Approved-action executor covers approved task transition execution, idempotent repeat, duplicate execution blocking and pending-approval rejection.
- Research Manager adapter status endpoint is read-only and does not invoke external research.
- Product Manager spec contracts require approved or active tasks and read-only project connections.
- Product Manager status endpoint is read-only and does not check or mutate external product systems.
- Product Manager draft artifacts are internal, review-gated and audit logged.
- Product Manager draft review approves or rejects drafts without external product writes.
- Executive Assistant briefs summarize internal state and mock inbox data only.
- Executive Assistant status endpoint is read-only and external email/calendar remain disabled.
- Executive Assistant task proposals create internal draft tasks only; no external sends or scheduling occur.
- Executive Assistant proposal review accepts task proposals into planning or dismisses them by cancelling the draft task.
- Executive Assistant briefs and task proposals have read-only filtered list endpoints for review queues.
- Executive Assistant has a login-protected read-only dashboard for briefs and task proposal queues.

## Not Yet Verified

- Real Gmail access remains disabled and requires explicit approval.
- Real payment-provider selection/connection remains deferred and requires explicit approval.
- External Research Manager invocation remains disabled and requires explicit approval.
- Production deployment, product repository writes and external side effects remain disabled and require explicit approval.

## Next Verification Step

Before any external action workflow is connected, bind it to an exact approved action payload, keep the dry-run/read-only path testable, and require explicit CEO approval.
