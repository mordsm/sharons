# O1 REQ-2: Mental Trainer Landing Page Content

Status: proposed internal product artifact
Date: 2026-10-06
Owner: Product / Chief of Staff
External action: none

## Purpose

This artifact defines landing-page content, primary call to action, and non-therapy safety positioning for Mental Skills Playground / Mental Trainer.

It is an internal product artifact. It does not publish content, write to the product repository, deploy a page, contact users, or alter billing.

## First View

Product name:

Mental Skills Playground

Headline:

Train the pause between trigger and response.

Supporting copy:

Short, low-intensity practice sessions for building meta-cognitive and meta-emotional skills: pause, frustration tolerance, and arousal regulation.

Primary CTA:

Start a 3-minute training session

Secondary CTA:

See how the training loop works

Safety note:

This is a mental-skills training product, not therapy, diagnosis, or crisis support.

## Core Positioning

Mental Skills Playground is a gym for mental muscles.

It helps users practice small repeatable drills:

1. Discover the automatic response.
2. Train one micro-skill.
3. Retest with a comparable scenario.
4. Transfer the skill to real life.
5. Learn from the pattern over time.

## MVP Skills

- Pause: create space before responding.
- Frustration tolerance: stay stable when something changes, fails, or delays.
- Arousal regulation: notice activation and reduce intensity safely.

## CTA Detail

Primary CTA label:

Start a 3-minute training session

CTA destination:

Start the recommended low-intensity training flow through the Mental Skills Playground session API or GPT action surface.

CTA promise:

One short scenario, one micro-skill, one retest, and one compact debrief.

## Non-Therapy Boundary

Use this language near the CTA and footer:

Mental Skills Playground is for skills practice. It does not diagnose, treat, or replace professional care. The MVP uses low-intensity drills only, and users can stop at any time.

Avoid these claims:

- therapy
- treatment
- diagnosis
- cure
- clinical improvement
- mental-health replacement

## Safety Requirements

- Keep first-session challenges low intensity.
- Never use humiliation, threats, trauma content, or strong provocation.
- Provide a stop path.
- Treat progress as training indicators, not psychological conclusions.
- Do not frame the user as broken or disordered.

## Success Metrics

Before release, the landing-page content should support these measurable checks:

- A user can identify the product as mental-skills training within 5 seconds.
- A user can identify the primary CTA without scrolling.
- The non-therapy boundary is visible before or near the first training action.
- The page names at least one MVP skill.
- The page does not make diagnosis, treatment, cure, or clinical claims.

## Traceability

Supporting existing artifacts:

- `C:/workspace/mental-skills-playground/README.md`
- `C:/workspace/mental-skills-playground/CUSTOM_GPT_INSTRUCTIONS.md`
- `C:/workspace/mental-skills-playground/app/main.py`
- `C:/workspace/mental-skills-playground/openapi.actions.yaml`

REQ-2 coverage:

- Landing page content: defined in First View, Core Positioning, and MVP Skills.
- CTA: defined in Primary CTA and CTA Detail.
- Non-therapy safety positioning: defined in Safety note, Non-Therapy Boundary, and Safety Requirements.
