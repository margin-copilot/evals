import os
import subprocess
from pathlib import Path

GATE = Path(__file__).parents[1] / "scripts" / "gate.sh"
SHA = "a" * 40


def run_gate(tmp_path, owner):
    log = tmp_path / "uv.log"
    fake = tmp_path / "uv"
    # records every call; prints SHA where gate.sh reads the installed commit
    fake.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\ncase "$*" in *python*) echo {SHA};; esac\n')
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    env.pop("GITHUB_REPOSITORY_OWNER", None)
    if owner is not None:
        env["GITHUB_REPOSITORY_OWNER"] = owner
    done = subprocess.run(
        ["bash", str(GATE), "orchestrator", SHA], env=env, capture_output=True, text=True
    )
    return done.returncode, log.read_text() if log.exists() else ""


def test_installs_from_the_callers_org(tmp_path):
    code, calls = run_gate(tmp_path, "example")
    assert code == 0
    assert f"git+https://github.com/example/orchestrator@{SHA}" in calls


def test_defaults_to_margin_copilot_outside_actions(tmp_path):
    code, calls = run_gate(tmp_path, None)
    assert code == 0
    assert f"git+https://github.com/margin-copilot/orchestrator@{SHA}" in calls


def test_a_bad_owner_stops_before_anything_is_installed(tmp_path):
    code, calls = run_gate(tmp_path, "evil/x@y")
    assert code == 2
    assert calls == ""
