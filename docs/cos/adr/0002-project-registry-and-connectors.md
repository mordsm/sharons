# ADR 0002: Project Registry And Connector Contracts

Date: 2026-09-15

## Status

Proposed

## Context

Sharons must coordinate several current and future projects without absorbing their source code or operational databases. It also needs a way to reference the already-developed `research_manager` repository while preserving its independence.

## Decision

Implement a Project Registry in Sharons. Each external project or subsystem is represented by metadata and one or more versioned connections.

Initial Project fields should include:

- slug
- name
- description
- status
- owner
- repository provider
- repository reference
- default branch
- data classification
- metadata

Initial ProjectConnection fields should include:

- project
- connection type
- adapter type
- capabilities
- permission mode
- credential reference
- active flag
- contract version

Permission modes:

- `READ_ONLY`
- `PROPOSE_CHANGES`
- `WRITE_APPROVED`

The first Research Manager registry entry should point to `C:\workspace\research_manager` as an external subsystem. Its initial connection mode should be `READ_ONLY` until a specific adapter and approval policy are implemented.

## Connector Contract Principles

- A connector declares capabilities before use.
- A connector must not receive broader data access than the task requires.
- State-changing connector calls require idempotency key, correlation ID, Rules Engine evaluation, and audit.
- Product repository writes, deployments, data migrations, external communications, and production actions require the appropriate approval.
- Connector outputs are evidence or proposed actions, not authorization.

## Consequences

Positive:

- Lets Sharons coordinate work across repositories without copying code.
- Makes external capabilities reviewable and auditable.
- Gives a clean path to integrate the existing Research Manager.
- Keeps future projects consistent.

Tradeoffs:

- More upfront contract design.
- Requires adapter tests before useful automation.
- Read-only defaults may slow early workflows but reduce boundary risk.

## Initial Integration Path For Research Manager

1. Register `research_manager` as an external project/subsystem.
2. Record its current stack: FastAPI, LangGraph, Pydantic v2, SQLite, pytest.
3. Define a read-only adapter for status, capabilities, and research-run summaries.
4. Later, with approval, choose one path:
   - call `research_manager` as an external service;
   - wrap selected functions behind a Sharons adapter;
   - migrate selected behavior into Sharons while preserving state and traceability.

No migration or code import is part of Phase 0.
