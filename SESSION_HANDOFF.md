# Session Handoff

Saved: 2026-09-15

## Current Session State

The active user request was: "save current session and start a new session in sharons".

The workspace root is `C:\workspace`. The target project is `C:\workspace\sharons`.

`sharons` already exists and is an independent Git repository with:

- `AGENTS.md`
- `README_INSTALL_HE.md`
- `docs/chief_of_staff/SPEC_HE.md`
- `docs/chief_of_staff/ENGINEERING_PLAN_HE.md`
- `docs/research/RESEARCH_MANAGER_SPEC.md`
- `agents/research/AGENTS.md`

No Django scaffold has been created yet in this session.

## Git Baseline

From `C:\workspace\sharons`, `git status --short` showed all current files as untracked:

```text
?? AGENTS.md
?? README_INSTALL_HE.md
?? agents/
?? docs/
```

From `C:\workspace`, the whole workspace also appears largely untracked. Do not treat that as permission to clean, delete, reset, or reorganize anything.

## Instructions Read

Read in this session:

- `C:\workspace\sharons\AGENTS.md`
- `C:\workspace\sharons\docs\chief_of_staff\SPEC_HE.md`
- `C:\workspace\sharons\docs\chief_of_staff\ENGINEERING_PLAN_HE.md`

The two Hebrew spec files printed with mojibake in the shell, but the governing intent is also summarized clearly in `AGENTS.md`.

Still read before research-specific changes:

- `C:\workspace\sharons\docs\research\RESEARCH_MANAGER_SPEC.md`
- `C:\workspace\sharons\agents\research\AGENTS.md`

## Governing Sharons Direction

Sharons is a new, independent Django project and the operating system for an AI-native company.

Chief of Staff is the company-level orchestrator. Research Manager is a specialist subsystem invoked by the Chief of Staff, not a competing top-level orchestrator.

Sharons owns:

- company strategy
- portfolio state
- governance
- approvals
- organizational memory
- project coordination
- project registry and adapters

Sharons must not own product source code or product operational databases. Compass, Mental Trainer, and future products remain separate repositories/systems and are connected through approved project adapters.

Non-negotiables:

- Use PostgreSQL from the start.
- Use Django templates and server-rendered forms.
- Do not introduce React.
- Keep business logic in models/services; views stay thin.
- Every material state change needs idempotency key, correlation ID, and audit event.
- Rules Engine is deterministic; no LLM authorization boundary.
- No `eval`, executable expressions, or free-text Boolean rule conditions.
- No autonomous spending, external publishing, contacting people, legal commitment, personal-data access expansion, deletion, or production-system change.
- Initial approvals happen in an authenticated dashboard; Gmail is a notification channel only until explicitly approved.
- Payment provider selection is deferred; only provider-neutral interface and mock provider later.
- Every completed task needs acceptance criteria, evidence, and verification.

## Required Next Work

Perform Phase 0 only:

1. Confirm the greenfield workspace with read-only inspection.
2. Confirm `sharons` is not nested inside Compass or another product repository.
3. Inspect existing dependency, settings, model, migration, and test files if present.
4. Run tests only if code/tests already exist, then record the baseline.
5. Create `docs/cos/IMPLEMENTATION_ASSESSMENT.md`.
6. Create two ADRs:
   - repository boundaries: Sharons owns company operations; product repos own product code and data
   - Project Registry and connector contracts
7. Report proposed minimal Django scaffold and first vertical slice.
8. Wait for user approval before scaffolding Django, connecting PostgreSQL, importing product data, adding infrastructure, enabling Gmail, or performing production actions.

First vertical slice to propose, not yet implement:

```text
POST /api/v1/cos/intake/
  -> validate request
  -> connect it to an approved objective
  -> create a DRAFT task
  -> create an append-only audit event
  -> return task ID, correlation ID and status
```

## Current Best Next Command Set

Suggested read-only starting commands for the next session:

```powershell
Set-Location C:\workspace\sharons
git status --short
Get-ChildItem -Force
Get-ChildItem -Recurse -Force | Select-Object FullName,Length,LastWriteTime
Get-Content -Raw AGENTS.md
Get-Content -Raw agents\research\AGENTS.md
Get-Content -Raw docs\research\RESEARCH_MANAGER_SPEC.md
```

Then create Phase 0 docs only.
