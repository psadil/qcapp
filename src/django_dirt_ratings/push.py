"""The client half of the ingest API: what `manage push` talks over.

No Django imports, deliberately. Everything here takes bytes and strings a
caller already produced, which keeps the HTTP concerns testable against
``httpx.MockTransport`` with no database in the picture.

One unit is one request carrying two file parts, so the failure model is
simply "it landed or it did not". Retries are safe because the server is
idempotent on the unit's identities — but only network-level failures are
retried: a 4xx is the server saying the unit is wrong, and sending it again
would only be wrong twice.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

#: Generous, because a request can carry megabytes of animated AVIFs over a
#: domestic uplink and the server hashes every one of them on arrival.
DEFAULT_TIMEOUT = 300.0
RETRIES = 3
BACKOFF = 2.0


class PushFailed(Exception):
    """The server refused a unit, or stopped answering about it."""


@dataclass(frozen=True)
class PushTarget:
    base_url: str
    username: str
    password: str
    timeout: float = DEFAULT_TIMEOUT

    def url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/api{path}"


def open_client(target: PushTarget) -> httpx.Client:
    """A client that verifies TLS. There is deliberately no way to turn that off.

    The deployment holds a short-lived certificate for a bare IP address, so
    the one moment anybody would reach for `--insecure` is exactly the moment
    the certificate has expired and the connection is genuinely unprotected —
    which is when the push password would be handed to whoever answered.
    """
    return httpx.Client(
        auth=(target.username, target.password),
        timeout=target.timeout,
        follow_redirects=False,
    )


def fetch_plan(client: httpx.Client, target: PushTarget) -> dict[str, Any] | None:
    """The server's active plan (``{name, content_hash}``), or None."""
    response = client.get(target.url("/plan"))
    if response.status_code != 200:
        raise PushFailed(f"plan: HTTP {response.status_code} {_detail(response)}")
    return response.json()


def push_plan(
    client: httpx.Client, target: PushTarget, *, name: str, toml: str
) -> dict[str, Any]:
    """Persist and activate one review plan on the server (idempotent)."""
    response = client.post(target.url("/plan"), json={"name": name, "toml": toml})
    if response.status_code != 200:
        raise PushFailed(f"plan push: HTTP {response.status_code} {_detail(response)}")
    return response.json()


def fetch_units(
    client: httpx.Client, target: PushTarget, *, step: str
) -> dict[str, str]:
    """``{file1: unit_digest}`` for every unit the server already holds."""
    response = client.get(target.url("/units"), params={"step": step})
    if response.status_code != 200:
        raise PushFailed(f"units: HTTP {response.status_code} {_detail(response)}")
    return {row["file1"]: row["unit_digest"] for row in response.json()}


def push_unit(
    client: httpx.Client, target: PushTarget, *, payload: bytes, tar: bytes
) -> dict[str, Any]:
    """Send one unit. Retries transport failures and 5xx; never a 4xx."""
    files = {
        "unit": ("unit.json", payload, "application/json"),
        "images": ("images.tar", tar, "application/x-tar"),
    }
    last = ""
    for attempt in range(RETRIES):
        try:
            response = client.post(target.url("/units"), files=files)
        except httpx.HTTPError as exc:
            last = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code == 200:
                return response.json()
            if response.status_code < 500:
                raise PushFailed(f"HTTP {response.status_code}: {_detail(response)}")
            last = f"HTTP {response.status_code}: {_detail(response)}"
        if attempt < RETRIES - 1:
            time.sleep(BACKOFF * (attempt + 1))
    raise PushFailed(f"gave up after {RETRIES} attempts — {last}")


def trigger_prioritize(client: httpx.Client, target: PushTarget) -> dict[str, Any]:
    """Rescore priorities server-side (run once, after the last unit lands)."""
    response = client.post(target.url("/prioritize"))
    if response.status_code != 200:
        raise PushFailed(f"prioritize: HTTP {response.status_code} {_detail(response)}")
    return response.json()


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("message", response.text[:200]))
    except ValueError:
        return response.text[:200]
