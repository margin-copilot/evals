"""The system under test in one process (D-019): orchestrator -> A2A -> data-agent with fake
outbound adapters and tokens from a local issuer. No network, no Azure."""

import json

import httpx
import jwt
from data_agent.adapters.inbound.a2a_server import create_a2a_app
from data_agent.adapters.outbound.analyst import FakeAnalyst
from margin_copilot_shared.security.obo import OboFailed
from margin_copilot_shared.security.tokens import TokenRejected, TokenValidator
from margin_copilot_shared.testing.issuer import LocalIssuer
from orchestrator.adapters.inbound.http_api import create_http_app
from orchestrator.adapters.outbound.a2a_agent import A2AAgent, FakeAgent
from orchestrator.adapters.outbound.router import FakeRouter

from margin_evals.cases import Case, Persona

ORCHESTRATOR = "eval-orchestrator"
DATA_AGENT = "eval-data-agent"
CLI = "eval-cli"
DATA_AGENT_SCOPE = f"api://{DATA_AGENT}/access_as_user"
DATA_AGENT_URL = "http://data-agent/"
OTHER_TENANT = "22222222-2222-2222-2222-222222222222"
CARRIED_CLAIMS = ("groups",)


class LocalObo:
    """Stands in for Entra OBO: checks the incoming token, mints one for the next service."""

    def __init__(
        self,
        issuer: LocalIssuer,
        incoming: TokenValidator,
        client_id: str,
        audiences: dict[str, str],
    ) -> None:
        self._issuer = issuer
        self._incoming = incoming
        self._client_id = client_id
        self._audiences = audiences

    def exchange(self, user_token: str, scopes: list[str]) -> str:
        if len(scopes) != 1 or scopes[0] not in self._audiences:
            raise OboFailed("invalid_scope")
        try:
            caller = self._incoming.validate(user_token)
        except TokenRejected:
            raise OboFailed("invalid_grant") from None
        claims = jwt.decode(user_token, options={"verify_signature": False})
        carried = {name: claims[name] for name in CARRIED_CLAIMS if name in claims}
        return self._issuer.issue(
            audience=self._audiences[scopes[0]], azp=self._client_id, oid=caller.oid, **carried
        )


class System:
    def __init__(self) -> None:
        self.issuer = LocalIssuer()
        user_tokens = self.issuer.validator(audience=ORCHESTRATOR, allowed_callers=frozenset({CLI}))
        data_agent_app = create_a2a_app(
            FakeAnalyst(),
            self.issuer.validator(audience=DATA_AGENT, allowed_callers=frozenset({ORCHESTRATOR})),
            DATA_AGENT_URL,
        )
        self.obo = LocalObo(self.issuer, user_tokens, ORCHESTRATOR, {DATA_AGENT_SCOPE: DATA_AGENT})
        data_agent = A2AAgent(
            "data-agent",
            DATA_AGENT_URL,
            DATA_AGENT_SCOPE,
            self.obo.exchange,
            httpx.AsyncClient(transport=httpx.ASGITransport(app=data_agent_app)),
        )
        agents = {"data-agent": data_agent, "policy-agent": FakeAgent("policy-agent")}
        app = create_http_app(FakeRouter(), agents, user_tokens)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://orchestrator"
        )

    def token(self, persona: Persona, variant: str) -> str | None:
        claims = {"oid": persona.oid, "groups": list(persona.groups)}
        match variant:
            case "valid":
                return self.issuer.issue(audience=ORCHESTRATOR, azp=CLI, **claims)
            case "none":
                return None
            case "unlisted_app":
                return self.issuer.issue(audience=ORCHESTRATOR, azp="unlisted-cli", **claims)
            case "data_agent_audience":
                return self.issuer.issue(audience=DATA_AGENT, azp=CLI, **claims)
            case "expired":
                return self.issuer.issue(audience=ORCHESTRATOR, azp=CLI, lifetime=-60, **claims)
            case "missing_scope":
                return self.issuer.issue(
                    audience=ORCHESTRATOR, azp=CLI, scp="other.scope", **claims
                )
            case "other_issuer":
                # Entra signs every tenant's tokens with the same keys; only iss and tid differ.
                other = f"https://local-issuer.invalid/{OTHER_TENANT}/v2.0"
                return self.issuer.issue(
                    audience=ORCHESTRATOR, azp=CLI, iss=other, tid=OTHER_TENANT, **claims
                )
        raise ValueError(f"unknown token variant {variant!r}")

    async def ask(self, case: Case, persona: Persona) -> tuple[int, dict | None]:
        headers = {"content-type": "application/json"}
        token = self.token(persona, case.token)
        if token is not None:
            headers["authorization"] = f"Bearer {token}"
        if case.raw_body is not None:
            content = case.raw_body.encode()
        else:
            content = json.dumps({"question": case.question * case.repeat}).encode()
        response = await self.client.post("/chat", content=content, headers=headers)
        try:
            body = response.json()
        except ValueError:
            body = None
        return response.status_code, body
