# ADR 0001: Repository Boundaries

Date: 2026-09-15

## Status

Proposed

## Context

Sharons is intended to be the operating system for an AI-native company. It coordinates company strategy, portfolio state, governance, approvals, organizational memory, agents, and project work.

Several related systems already exist as separate repositories or projects, including:

- `C:\workspace\compass`
- `C:\workspace\research_manager`
- Mental Trainer / mental-skills projects elsewhere in the workspace

The user clarified that Research Manager is already developed and has its own repository named `research_manager`.

## Decision

Sharons remains an independent repository. It will not copy product source code, product operational databases, or the existing `research_manager` implementation by default.

Sharons owns:

- strategy
- objectives and plans
- task contracts
- approvals and audit
- organizational memory
- project registry records
- connector contracts and allowed capabilities

External project repositories own:

- their source code
- product-specific data models
- product operational databases
- product runtime behavior
- local implementation details

The existing `research_manager` repository is treated as an external subsystem or reference implementation unless and until the user explicitly approves a migration or code import.

## Consequences

Positive:

- Prevents Sharons from becoming a mixed product monolith.
- Preserves the working Research Manager implementation.
- Keeps ownership, persistence, and framework choices explicit.
- Allows Sharons to coordinate research through governance and contracts.

Tradeoffs:

- Integration requires adapters and contract tests.
- Some behavior may be duplicated temporarily at the contract layer.
- Cross-repository workflows need clearer versioning and audit.

## Guardrails

- No code import from `research_manager`, Compass, Mental Trainer, or any product repository without approval.
- Product writes require Rules Engine evaluation, audit, and the required human approval.
- Default project connections are read-only.
- Sharons may store repository references, capability declarations, and operational metadata.
- Sharons may not silently become the source of truth for product internals.
