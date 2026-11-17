"""Visible Windows browser handoff for manual Clalit portal exploration.

This intentionally NEVER searches, books, cancels, screenshots, or reads credentials.
Run locally; do not execute on a server.
"""
from __future__ import annotations

import sys
from urllib.parse import urlsplit

CLALIT_PORTAL = "https://e-services.clalit.co.il/"


def validate_portal_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "e-services.clalit.co.il":
        raise ValueError("Only the official HTTPS Clalit e-services portal is permitted")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Credential-bearing or nonstandard-port URLs are prohibited")
    return url


def main() -> int:
    if sys.platform != "win32":
        print("This local proof of concept is intended for Windows.")
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Install Playwright: py -m pip install playwright")
        return 2

    print("A separate browser session will open the official Clalit site.")
    print("Log in manually there. Do NOT paste passwords or SMS codes into this console.")
    print("No appointment will be booked by this program.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        try:
            context = browser.new_context(locale="he-IL", timezone_id="Asia/Jerusalem")
            page = context.new_page()
            page.goto(validate_portal_url(CLALIT_PORTAL), wait_until="domcontentloaded")
            input("Explore the site manually; press Enter here to close the browser... ")
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
