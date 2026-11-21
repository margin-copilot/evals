import jwt
import pytest
from data_agent.adapters.outbound.analyst import FakeAnalyst
from margin_copilot_shared.security.obo import OboFailed

from margin_evals.cases import Case, Expect, Persona
from margin_evals.judge import SystemFault, verdict
from margin_evals.system import DATA_AGENT, DATA_AGENT_SCOPE, ORCHESTRATOR, System

NORTH = Persona(name="north.mgr", oid="persona-north-mgr", groups=("grp-region-north",))


def ask(question="Who am I?", **fields):
    return Case(
        id="X",
        kind="plumbing",
        milestone=1,
        persona="north.mgr",
        question=question,
        expect=Expect(contains=("x",)),
        **fields,
    )


async def test_identity_crosses_the_hop_in_process():
    status, body = await System().ask(ask(), NORTH)
    assert len(body.pop("conversation_id")) == 32
    assert (status, body) == (
        200,
        {
            "answer": "fake data-agent answers as user persona-north-mgr",
            "refusal": None,
            "agents": ["data-agent"],
            "citations": [],
        },
    )


async def test_each_token_variant_gets_the_expected_status():
    system = System()
    expected = {
        "none": 401,
        "unlisted_app": 403,
        "data_agent_audience": 401,
        "expired": 401,
        "missing_scope": 403,
        "other_issuer": 401,
    }
    for variant, status in expected.items():
        assert (await system.ask(ask(token=variant), NORTH))[0] == status, variant


def test_local_obo_mints_a_data_agent_token_for_the_same_user_and_groups():
    system = System()
    user_token = system.token(NORTH, "valid")
    minted = system.obo.exchange(user_token, [DATA_AGENT_SCOPE])
    claims = jwt.decode(minted, options={"verify_signature": False})
    assert (claims["aud"], claims["azp"], claims["oid"]) == (DATA_AGENT, ORCHESTRATOR, NORTH.oid)
    assert claims["groups"] == ["grp-region-north"]


def test_local_obo_refuses_unknown_scopes_and_bad_tokens():
    system = System()
    with pytest.raises(OboFailed, match="invalid_scope"):
        system.obo.exchange(system.token(NORTH, "valid"), ["api://other/access_as_user"])
    with pytest.raises(OboFailed, match="invalid_grant"):
        system.obo.exchange(system.token(NORTH, "expired"), [DATA_AGENT_SCOPE])


async def test_a_broken_downstream_is_a_system_fault_not_a_case_failure(monkeypatch):
    async def broken(self, question):
        raise RuntimeError("database down")

    monkeypatch.setattr(FakeAnalyst, "answer", broken)
    case = ask()
    status, body = await System().ask(case, NORTH)
    assert status == 502
    with pytest.raises(SystemFault):
        verdict(case, status, body)


def test_other_tenant_token_is_signed_with_the_same_key():
    """Real Entra signs every tenant's tokens with the same keys; only iss/tid tell them apart."""
    system = System()
    token = system.token(NORTH, "other_issuer")
    public_key = system.issuer._key.public_key()
    claims = jwt.decode(token, public_key, algorithms=["RS256"], audience=ORCHESTRATOR)
    assert claims["tid"] != system.issuer.tenant_id
    assert claims["iss"] != system.issuer.issuer


async def test_the_hijack_case_passes_on_fakes():
    from margin_evals.cases import load_cases, load_personas
    from margin_evals.judge import judge

    case = next(c for c in load_cases() if c.id == "A-21")
    status, body = await System().ask(case, load_personas()[case.persona])
    assert (status, judge(case, status, body)) == (404, [])
