import json
import os
import shutil
import subprocess
import sys
from urllib.parse import urlencode


class ProviderHttpError(Exception):
    code = "PROVIDER_FETCH_FAILED"


_TLS_COMMAND: list[str] = []

_HELPER = """
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

spec = json.loads(sys.stdin.read())
data = spec.get("body")
payload = data.encode("utf-8") if isinstance(data, str) else None
request = Request(spec["url"], data=payload, headers=spec["headers"], method=spec["method"])
try:
    with urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8")
        status = response.status
except HTTPError as exc:
    raw = exc.read().decode("utf-8", errors="replace")
    status = exc.code
except (URLError, TimeoutError):
    sys.stdout.write(json.dumps({"ok": False}))
    raise SystemExit(1)
sys.stdout.write(json.dumps({"ok": True, "status": status, "body": raw}))
"""


def http_json(method: str, url: str, *, token: str, payload: dict | None = None) -> dict:
    if method not in {"GET", "POST"}:
        raise ProviderHttpError("Only GET and POST are available to approved adapters.")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "sharons-approved-adapter",
    }
    body = None
    if payload is not None:
        body = json.dumps(payload)
        headers["Content-Type"] = "application/json"
    return _exchange(method, url, headers=headers, body=body, failure="Provider request failed.")


def http_form(url: str, form: dict) -> dict:
    if url != "https://oauth2.googleapis.com/token":
        raise ProviderHttpError("Form posts are limited to the Google token endpoint.")
    return _exchange(
        "POST",
        url,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        body=urlencode(form),
        failure="Token refresh failed.",
    )


def _exchange(method: str, url: str, *, headers: dict, body: str | None, failure: str) -> dict:
    completed = subprocess.run(
        [*_tls_command(), "-c", _HELPER],
        input=json.dumps({"method": method, "url": url, "headers": headers, "body": body}),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise ProviderHttpError(failure)
    try:
        result = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ProviderHttpError(failure) from exc
    if not result.get("ok") or int(result.get("status", 0)) >= 400:
        raise ProviderHttpError(failure)
    parsed = json.loads(result.get("body") or "{}")
    if not isinstance(parsed, dict):
        raise ProviderHttpError(failure)
    return parsed


def _tls_command() -> list[str]:
    global _TLS_COMMAND
    if _TLS_COMMAND:
        return _TLS_COMMAND
    configured = os.environ.get("SHARONS_HTTP_PYTHON", "").strip()
    candidates = []
    if configured:
        candidates.append([configured])
    candidates.append([sys.executable])
    discovered = shutil.which("python")
    if discovered:
        candidates.append([discovered])
    candidates.append(["py", "-3"])
    seen = set()
    for command in candidates:
        key = tuple(command)
        if key in seen:
            continue
        seen.add(key)
        try:
            probe = subprocess.run(
                [*command, "-c", "from urllib.request import urlopen; urlopen('https://www.google.com/generate_204', timeout=15)"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0:
            _TLS_COMMAND = command
            return command
    raise ProviderHttpError("HTTPS is unavailable in this Python process.")
