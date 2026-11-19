"""The live suite's plumbing (D-019, D-033): settings from evals/.env, one browser sign-in per test
user, and POST /chat on the deployed orchestrator."""

import pathlib

import httpx
import msal

ENV_FILE = pathlib.Path(__file__).resolve().parents[2] / ".env"
TIMEOUT = 240  # cold start, a database waking from auto-pause, several model turns


class SignInFailed(Exception):
    pass


def load_env(path: pathlib.Path = ENV_FILE) -> dict[str, str]:
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    return {key.strip(): value.strip() for key, value in pairs if not key.startswith("#")}


def sign_in(env: dict[str, str], persona: str) -> str:
    """Opens the browser; the account picked must be the persona, or the results would lie."""
    app = msal.PublicClientApplication(
        env["CLI_CLIENT_ID"], authority=f"https://login.microsoftonline.com/{env['TENANT_ID']}"
    )
    hint = f"{persona}@{env['ENTRA_DOMAIN']}" if env.get("ENTRA_DOMAIN") else None
    result = app.acquire_token_interactive(
        [env["ORCHESTRATOR_SCOPE"]], prompt="select_account", login_hint=hint
    )
    if "access_token" not in result:
        raise SignInFailed(f"{result.get('error')}: {result.get('error_description')}")
    who = str(result.get("id_token_claims", {}).get("preferred_username", ""))
    if who.split("@")[0].lower() != persona:
        raise SignInFailed(f"signed in as {who!r}, expected {persona}")
    return result["access_token"]


def chat(env: dict[str, str], token: str, question: str) -> tuple[int, dict | None]:
    response = httpx.post(
        f"{env['ORCHESTRATOR_URL']}/chat",
        json={"question": question},
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT,
    )
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body if isinstance(body, dict) else None
