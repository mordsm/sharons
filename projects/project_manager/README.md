# Project Manager Project

## Mission

Project Manager watches objective execution, proposes milestones, and turns coordination
signals into internal follow-up. It does not take external actions.

## Current Implementation

- Execution reviews, milestone proposals and blocker reviews: `project_manager/models.py`
- Service logic: `project_manager/services.py`
- API: `project_manager/views.py`, `project_manager/urls.py`
- Coordination page: `templates/project_manager/dashboard.html` at `/project-manager/`

## Current Capabilities

- Create an execution review from objective health.
- Create draft follow-up tasks for blocked work and unverified deliveries.
- Propose milestones as internal draft tasks.
- Accept or dismiss a milestone proposal once.
- On a blocked task, open either an unblock approval or an internal follow-up task.
- Show blocked tasks, open proposals, reviews and blocker follow-ups on one page.

## Boundaries

- No external action.
- Accepting a milestone proposal does not complete the underlying task.
- A blocker review does not itself move the blocked task.

## Next Work

No missing coordination feature from the current slice. The open milestone proposals and
blocked tasks on the coordination page are records waiting for a human decision, not
unimplemented screens.
