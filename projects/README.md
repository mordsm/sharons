# Sharons Role Projects

This folder makes the three operating roles explicit as separate projects.

The Django implementation is still shared where the domain requires it:

- Chief of Staff uses `core`, `operations`, `governance` and `portfolio`.
- Product Manager uses `product`, plus shared tasks/projects/approvals.
- Executive Assistant uses `executive_assistant`, plus mailbox/governance for safe email workflows.

Do not rename Django apps or move migrations casually. These project folders define ownership,
scope, APIs and next work while preserving the current tested app boundaries.

## Projects

- `chief_of_staff/`
- `product_manager/`
- `executive_assistant/`

