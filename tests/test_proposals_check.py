"""live/proposals_check.py against fakes: a call that fails never counts as a pass."""

import importlib.util
import pathlib

import httpx

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "live" / "proposals_check.py"


def load():
    spec = importlib.util.spec_from_file_location("proposals_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_failed_listing_fails_its_check(monkeypatch, capsys):
    check = load()
    env = {"PROPOSALS_API_URL": "https://proposals.example", "PROPOSALS_SCOPE": "s"}
    monkeypatch.setattr(check, "load_env", lambda: env)
    monkeypatch.setattr(check, "sign_in", lambda env, persona, scope=None: persona)
    monkeypatch.setattr(check, "chat", lambda env, token, q: (200, {"answer": "pending director"}))

    def request(method, url, json=None, headers=None, timeout=None):
        persona = headers["Authorization"].split()[1]
        if persona == "south.mgr":
            return httpx.Response(500, json={"error": "boom"})
        if method == "GET":
            return httpx.Response(200, json={"proposals": []})
        return httpx.Response(403, json={"error": "calling app not allowed"})

    monkeypatch.setattr(check.httpx, "request", request)
    assert check.main() == 1
    assert "FAIL  south.mgr's list holds no North or Center proposal" in capsys.readouterr().out
