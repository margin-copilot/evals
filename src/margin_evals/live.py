"""The live suite's plumbing (D-019, D-033): settings from evals/.env, browser sign-ins remembered
in the OS keychain, and POST /chat on the deployed orchestrator, as JSON or as a stream (D-045)."""

import json
import pathlib
import time
from collections.abc import Iterable, Iterator

import httpx
import msal
from msal_extensions import PersistedTokenCache, build_encrypted_persistence

from margin_evals.telemetry import traceparent

ENV_FILE = pathlib.Path(__file__).resolve().parents[2] / ".env"
# Marker file for the test users' tokens, which the OS keeps encrypted (macOS: Keychain item
# "msal-extensions"; forget them with `security delete-generic-password -s msal-extensions`).
TOKEN_CACHE = pathlib.Path.home() / ".margin-copilot" / "msal-token-cache.bin"
TIMEOUT = 240  # cold start, a database waking from auto-pause, several model turns


class SignInFailed(Exception):
    pass


def load_env(path: pathlib.Path = ENV_FILE) -> dict[str, str]:
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    return {key.strip(): value.strip() for key, value in pairs if not key.startswith("#")}


def client(env: dict[str, str]) -> msal.PublicClientApplication:
    TOKEN_CACHE.parent.mkdir(mode=0o700, exist_ok=True)
    cache = PersistedTokenCache(build_encrypted_persistence(str(TOKEN_CACHE)))
    return msal.PublicClientApplication(
        env["CLI_CLIENT_ID"],
        authority=f"https://login.microsoftonline.com/{env['TENANT_ID']}",
        token_cache=cache,
    )


def sign_in(env: dict[str, str], persona: str, scope: str | None = None) -> str:
    """Silent when this persona signed in before; otherwise the browser opens, and the account
    picked must be the persona, or the results would lie. `scope` defaults to the orchestrator's."""
    app = client(env)
    scopes = [scope or env["ORCHESTRATOR_SCOPE"]]
    for account in app.get_accounts():
        if account["username"].split("@")[0].lower() == persona:
            result = app.acquire_token_silent(scopes, account=account)
            if result and "access_token" in result:
                return result["access_token"]
    hint = f"{persona}@{env['ENTRA_DOMAIN']}" if env.get("ENTRA_DOMAIN") else None
    result = app.acquire_token_interactive(scopes, prompt="select_account", login_hint=hint)
    if "access_token" not in result:
        raise SignInFailed(f"{result.get('error')}: {result.get('error_description')}")
    who = str(result.get("id_token_claims", {}).get("preferred_username", ""))
    if who.split("@")[0].lower() != persona:
        raise SignInFailed(f"signed in as {who!r}, expected {persona}")
    return result["access_token"]


def chat(
    env: dict[str, str],
    token: str,
    question: str,
    conversation_id: str | None = None,
    trace_id: str | None = None,
) -> tuple[int, dict | None]:
    """`trace_id` becomes the turn's trace (a `traceparent` header), for its time and cost."""
    payload = {"question": question}
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    headers = {"Authorization": f"Bearer {token}"}
    if trace_id is not None:
        headers["traceparent"] = traceparent(trace_id)
    try:
        response = httpx.post(
            f"{env['ORCHESTRATOR_URL']}/chat", json=payload, headers=headers, timeout=TIMEOUT
        )
    except httpx.TransportError as error:  # judged as a failed case; the run goes on
        return 0, {"error": f"no response: {type(error).__name__}"}
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body if isinstance(body, dict) else None


def sse_events(lines: Iterable[str]) -> Iterator[tuple[str, str]]:
    """(event, data) from text/event-stream lines: a blank line ends an event, ":" lines are
    comments (the server's pings), and an event cut off by the end is dropped."""
    event, data = "message", []
    for line in lines:
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
        elif not line.startswith(":"):
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)


def chat_stream(
    env: dict[str, str],
    token: str,
    question: str,
    conversation_id: str | None = None,
    trace_id: str | None = None,
) -> tuple[int, dict | None, list[tuple[str, float]]]:
    """POST /chat as a stream: the status (an error event's own status), the `done` body or the
    error, and each event with its seconds since the request."""
    payload = {"question": question}
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    if trace_id is not None:
        headers["traceparent"] = traceparent(trace_id)
    events: list[tuple[str, float]] = []
    start = time.monotonic()
    try:
        url = f"{env['ORCHESTRATOR_URL']}/chat"
        with httpx.stream("POST", url, json=payload, headers=headers, timeout=TIMEOUT) as response:
            status, body = response.status_code, None
            if not response.headers.get("content-type", "").startswith("text/event-stream"):
                response.read()
                try:
                    body = response.json()
                except ValueError:
                    body = None
                return status, body if isinstance(body, dict) else None, events
            for event, data in sse_events(response.iter_lines()):
                events.append((event, round(time.monotonic() - start, 1)))
                if event in ("done", "error"):
                    body = json.loads(data)
                    if event == "error":
                        status = body.get("status", status)
            return status, body, events
    except httpx.TransportError as error:  # judged as a failed case; the run goes on
        return 0, {"error": f"no response: {type(error).__name__}"}, events


def stream_times(events: list[tuple[str, float]]) -> str:
    """first step 0.4 s, lead 21.3 s, done 44.0 s"""
    first = {}
    for event, at in events:
        first.setdefault("first step" if event == "step" else event, at)
    return ", ".join(f"{name} {at} s" for name, at in first.items())
