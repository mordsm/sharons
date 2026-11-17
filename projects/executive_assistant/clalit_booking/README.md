# Clalit appointment booking — Windows browser proof of concept

Status: **local, read-only exploration only; no live booking capability**.

## Goal
An Administrative Agent workflow for an in-person dermatologist appointment around 2027-03-17 (or a caller-supplied date), with explicit user login and exact-appointment approval before any future external write.

## Security boundaries
- Start an isolated, visible Chromium browser on the user's Windows machine.
- Navigate only to the official Clalit portal: https://e-services.clalit.co.il/
- User enters all login credentials/OTP directly into Clalit's browser UI. Never ask for credentials in Sharons chat, logs, or agent prompts.
- Do not reuse the default Chrome profile. Ephemeral browser context: no cookies/session persistence.
- The proof of concept does not inspect the medical record, capture screenshots, or automate appointment searches.
- No bypassing CAPTCHA, bot protections, or account access restrictions.
- Never schedule, cancel, or change appointments without per-appointment CEO approval bound to an immutable appointment payload. Recheck availability and confirmation to avoid duplicate booking.
- Don't add sensitive medical data to GitHub, telemetry, LLM prompts, or unencrypted logs.

## Local experiment (Windows)
1. Clone the branch onto your own Windows computer.
2. From the repository root, install: `py -m pip install playwright`
3. Install local Chromium: `py -m playwright install chromium`
4. Run: `py projects/executive_assistant/clalit_booking/browser_poc.py`
5. A visible **separate** browser opens the official Clalit portal. Complete login manually and explore the appointment UI yourself.
6. Return to the console and press Enter to close the isolated browser. No booking is performed by code.

## Next implementation gates
1. Confirm the official site's permitted interaction model and its actual dermatologist booking flow manually.
2. Add a provider-specific read-only adapter using stable accessible UI locators, not guessed selectors; halt on unexpected UI/captcha.
3. Show available appointment offers to the user with doctor, clinic, address, date, local time, and any referral/copay requirement.
4. Generate a canonical SHA-256 payload hash and store a short-lived approval via Sharons governance, scoped to that *exact* slot and patient.
5. On approval, verify the slot and patient again, submit once, verify the Clalit-issued confirmation, audit only minimally required fields, then release the session.
6. Add integration tests with a mock provider before enabling any external action; do not perform live bookings in CI.

## Premortem
- **Site layout/anti-automation changes:** fail closed; no blind clicking.
- **Four-month horizon unavailable:** show no availability and allow a separately authorized reminder/check, never book earlier automatically.
- **Expired auth:** require manual re-login.
- **Slot gone after approval:** return to search; approval is invalid for replacement slots.
- **Network failure after submit:** reconcile external booking status before attempting any retry.
- **Sensitive data leakage:** redact all logs, never send screenshots/credentials to remote agents.
