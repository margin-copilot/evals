import jwt
import pytest
from margin_copilot_shared.security.obo import OboFailed

from margin_evals.cases import Case, Expect, Persona
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
    assert (status, body) == (200, {"answer": "data-agent sees user persona-north-mgr"})


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
