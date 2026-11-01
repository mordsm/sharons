# Product Manager Project

## Mission

Product Manager converts 90-day objectives into product specs, requirements, user stories,
open questions, success metrics and internal implementation proposals.

Repository writes, publishing and customer contact stay off. GitHub is limited to creating
one issue after an approval bound to that exact title and body.

## Current Implementation

- Spec contracts and drafts: `product/models.py`
- Roadmap milestones, RICE features and feedback: `product/pm_engine.py`
- User research, competitive analysis, and pricing experiment briefs: `product/user_research.py`, `product/competitive.py`, `product/pricing.py`
- Approval-backed GitHub issue creation: `product/github_issues.py`
- API/views: `product/views.py`, `product/urls.py`
- Dashboard: `templates/product/dashboard.html`

## Current Capabilities

- Create and review product spec contracts and drafts.
- Turn an approved spec into internal draft tasks.
- Score features, record milestones, and link a milestone to an active objective for the same project.
- Report readiness and a roadmap for a project.
- Capture user-research interviews, findings and open questions without customer contact.
- Draft and review competitive analysis internally.
- Draft and review an ILS pricing experiment brief. The brief does not charge or spend.
- Request approval to create one GitHub issue. The request itself does not call GitHub.

## Boundaries

- No product-repository write.
- No publishing.
- No direct customer contact.
- No charge or spend from a pricing experiment brief.
- No GitHub action other than `create_issue`.
- No strategic change without an approved objective.

## Next Work

1. A live GitHub issue only after the title, body, and repository are chosen and the approval is executed.
