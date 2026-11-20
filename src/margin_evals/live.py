"""The live suite's plumbing (D-019, D-033): settings from evals/.env, browser sign-ins remembered
in the OS keychain, and POST /chat on the deployed orchestrator."""

import pathlib

import httpx
import msal
from msal_extensions import PersistedTokenCache, build_encrypted_persistence

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


def sign_in(env: dict[str, str], persona: str) -> str:
    """Silent when this persona signed in before; otherwise the browser opens, and the account
    picked must be the persona, or the results would lie."""
    app = client(env)
    scopes = [env["ORCHESTRATOR_SCOPE"]]
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


def chat(env: dict[str, str], token: str, question: str) -> tuple[int, dict | None]:
    try:
        response = httpx.post(
            f"{env['ORCHESTRATOR_URL']}/chat",
            json={"question": question},
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )
    except httpx.TransportError as error:  # judged as a failed case; the run goes on
        return 0, {"error": f"no response: {type(error).__name__}"}
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body if isinstance(body, dict) else None
