# O1 REQ-3: Mental Trainer Beta Pricing And Billing Test Path

Status: proposed internal product artifact
Date: 2026-10-06
Owner: Product / Finance / Chief of Staff
External action: none

## Purpose

This artifact defines an internal beta pricing and billing test path for Mental Skills Playground / Mental Trainer.

It does not connect a real payment provider, charge a real customer, publish pricing, deploy checkout, or write to the Mental Skills Playground repository.

## Current Finding

Mental Skills Playground currently has no pricing, billing, checkout, subscription, or payment code.

Existing evidence:

- `C:/workspace/mental-skills-playground/README.md`
- `C:/workspace/mental-skills-playground/openapi.actions.yaml`
- `C:/workspace/mental-skills-playground/app/main.py`

Sharons contains a mock payment provider suitable for an internal beta billing test path:

- `C:/workspace/sharons/payments/models.py`
- `C:/workspace/sharons/payments/services.py`
- `C:/workspace/sharons/payments/urls.py`
- `C:/workspace/sharons/payments/tests/test_mock_payment_provider.py`

## Proposed Beta Price

Initial beta test plan:

- Plan name: Mental Trainer Beta
- Price: 49 ILS / month
- Billing interval: monthly
- Currency: ILS
- Provider: Sharons mock payment provider only
- Real charging: disabled

This is a test-path price, not a public pricing decision.

## Billing Test Path

1. Create a mock payment customer.
2. Create a mock subscription for `Mental Trainer Beta`.
3. Create a mock successful charge.
4. Confirm finance can record or reconcile the test payment.
5. Receive duplicate and out-of-order mock webhooks without external side effects.
6. Cancel the mock subscription.

## Required Safety Boundaries

- No real payment provider.
- No real customer charge.
- No checkout publication.
- No production deployment.
- No external email or calendar action.
- No repository write to Mental Skills Playground.
- All events must remain audit logged and idempotent.

## Success Metrics

Before release, the beta billing path should satisfy:

- A mock subscription can be created with plan name, amount, currency, and interval.
- A mock charge can be recorded against the customer/subscription.
- Duplicate requests are idempotent.
- Out-of-order webhooks are recorded without external execution.
- A mock subscription can be cancelled.
- Finance can identify the test payment as Mental Trainer beta payment.

## Traceability To REQ-3

REQ-3:

Define pricing and billing test path for initial beta.

Coverage:

- Pricing: proposed beta test price and interval.
- Billing test path: customer, subscription, charge, webhook, cancellation.
- Safety: explicit mock-only/no-real-charge boundaries.
- Verification: payments mock provider tests.
