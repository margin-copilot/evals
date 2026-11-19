# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#   "httpx==0.28.1",
#   "msal==1.39.0",
#   "margin-copilot-shared @ git+https://github.com/margin-copilot/shared@v0.1.1",
# ]
# ///
"""Milestone 1 live check: identity across one A2A hop, run on the laptop (D-019).

Reads evals/.env (written by infra/scripts/spike-env.sh). The browser opens twice: sign in as the
first test user both times, first through the allow-listed CLI app, then through the unlisted one.
"""

import pathlib
import sys

import httpx
import msal
from margin_copilot_shared.testing.issuer import LocalIssuer

QUESTION = {"question": "who am I?"}


def load_env(path: pathlib.Path) -> dict[str, str]:
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    return {key.strip(): value.strip() for key, value in pairs if not key.startswith("#")}


def sign_in(env: dict[str, str], client_id: str) -> str:
    app = msal.PublicClientApplication(
        client_id, authority=f"https://login.microsoftonline.com/{env['TENANT_ID']}"
    )
    result = app.acquire_token_interactive([env["ORCHESTRATOR_SCOPE"]], prompt="select_account")
    if "access_token" not in result:
        sys.exit(f"sign-in failed: {result.get('error')}: {result.get('error_description')}")
    return result["access_token"]


def main() -> int:
    env = load_env(pathlib.Path(__file__).resolve().parent.parent / ".env")
    chat = f"{env['ORCHESTRATOR_URL']}/chat"
    results = []

    def check(name: str, passed: bool, detail: str) -> None:
        results.append(passed)
        print(f"{'PASS' if passed else 'FAIL'}  {name}: {detail}")

    with httpx.Client(timeout=120) as http:
        token = sign_in(env, env["CLI_CLIENT_ID"])
        response = http.post(chat, json=QUESTION, headers={"Authorization": f"Bearer {token}"})
        agents = response.json().get("agents") if response.status_code == 200 else None
        check(
            "signed-in user crosses the A2A hop",
            agents == ["data-agent"],
            f"{response.status_code} {response.text[:200]}",
        )

        token = sign_in(env, env["UNLISTED_CLIENT_ID"])
        response = http.post(chat, json=QUESTION, headers={"Authorization": f"Bearer {token}"})
        check(
            "token from an unlisted app is rejected",
            response.status_code == 403,
            f"{response.status_code} {response.text[:200]}",
        )

        local = LocalIssuer(tenant_id=env["TENANT_ID"]).issue(
            audience=env["ORCHESTRATOR_CLIENT_ID"], azp=env["CLI_CLIENT_ID"]
        )
        response = http.post(chat, json=QUESTION, headers={"Authorization": f"Bearer {local}"})
        check(
            "locally signed token is rejected",
            response.status_code == 401,
            f"{response.status_code} {response.text[:200]}",
        )

        try:
            card = f"https://{env['DATA_AGENT_FQDN']}/.well-known/agent-card.json"
            status = str(http.get(card, timeout=30).status_code)
        except httpx.HTTPError as error:
            status = type(error).__name__
        check("data-agent is unreachable from the internet", status != "200", status)

    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
