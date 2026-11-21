"""Live sign-in: a remembered persona signs in silently; anyone else goes to the browser."""

import pytest

from margin_evals import live

ENV = {"TENANT_ID": "t", "CLI_CLIENT_ID": "c", "ORCHESTRATOR_SCOPE": "api://o/access_as_user"}


class FakeApp:
    def __init__(self, accounts, interactive=None):
        self.accounts, self.interactive, self.opened_browser = accounts, interactive, False

    def get_accounts(self):
        return self.accounts

    def acquire_token_silent(self, scopes, account):
        return {"access_token": f"silent for {account['username']}"}

    def acquire_token_interactive(self, scopes, prompt, login_hint):
        self.opened_browser = True
        return self.interactive


def test_a_remembered_persona_signs_in_silently(monkeypatch):
    app = FakeApp([{"username": "south.mgr@x.example"}, {"username": "north.mgr@x.example"}])
    monkeypatch.setattr(live, "client", lambda env: app)
    assert live.sign_in(ENV, "north.mgr") == "silent for north.mgr@x.example"
    assert not app.opened_browser


def test_a_new_persona_opens_the_browser(monkeypatch):
    claims = {"preferred_username": "north.mgr@x.example"}
    app = FakeApp([], {"access_token": "fresh", "id_token_claims": claims})
    monkeypatch.setattr(live, "client", lambda env: app)
    assert live.sign_in(ENV, "north.mgr") == "fresh"
    assert app.opened_browser


def test_signing_in_as_someone_else_is_refused(monkeypatch):
    claims = {"preferred_username": "south.mgr@x.example"}
    app = FakeApp([], {"access_token": "wrong", "id_token_claims": claims})
    monkeypatch.setattr(live, "client", lambda env: app)
    with pytest.raises(live.SignInFailed, match="expected north.mgr"):
        live.sign_in(ENV, "north.mgr")


def test_a_dropped_connection_fails_the_case_instead_of_the_run(monkeypatch):
    def drop(*args, **kwargs):
        raise live.httpx.RemoteProtocolError("Server disconnected without sending a response.")

    monkeypatch.setattr(live.httpx, "post", drop)
    env = {**ENV, "ORCHESTRATOR_URL": "https://orchestrator.example"}
    assert live.chat(env, "token", "question") == (0, {"error": "no response: RemoteProtocolError"})


def test_sign_in_asks_for_the_scope_given(monkeypatch):
    app = FakeApp([{"username": "north.mgr@x.example"}])
    asked = []
    original = app.acquire_token_silent

    def silent(scopes, account):
        asked.append(scopes)
        return original(scopes, account)

    app.acquire_token_silent = silent
    monkeypatch.setattr(live, "client", lambda env: app)
    live.sign_in(ENV, "north.mgr")
    live.sign_in(ENV, "north.mgr", scope="api://p/access_as_user")
    assert asked == [["api://o/access_as_user"], ["api://p/access_as_user"]]
