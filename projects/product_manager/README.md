# Product Manager Project

## Mission

Product Manager converts 90-day objectives into product specs, requirements, user stories,
open questions, success metrics and internal implementation proposals.

It does not write to product repositories, create external issues, publish content or contact
users unless a future approval-backed adapter explicitly allows it.

## Current Implementation

- Product contracts and drafts: `product/models.py`
- Product service logic: `product/services.py`
- Product API/views: `product/views.py`, `product/urls.py`
- Product tests: `product/tests/test_product_spec_contract_api.py`
- Shared projects: `portfolio/`
- Shared tasks: `operations/`
- Shared approvals/audit: `governance/`

## Current APIs

- `GET /api/v1/product/manager/status/`
- `POST /api/v1/product/spec-contracts/create/`
- `POST /api/v1/product/spec-contracts/{contract_id}/drafts/create/`
- `POST /api/v1/product/spec-drafts/{draft_id}/review/`

## Current Capabilities

- Create bounded product spec contracts.
- Create internal product spec draft artifacts.
- Review product spec drafts internally.
- Keep external product repository writes disabled.
- Report Product Manager status.

## Boundaries

- No GitHub issue creation yet.
- No repository write.
- No publishing.
- No direct customer contact.
- No strategic change without approved objective context.

## Next Work

1. Add roadmap/milestone artifacts linked to 90-day objectives.
2. Add product spec to internal task proposal conversion.
3. Add user research artifact contracts.
4. Add feature prioritization scoring.
5. Add product readiness dashboard per project.

