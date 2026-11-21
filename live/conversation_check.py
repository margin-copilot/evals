"""Live conversation check (milestone 7): a follow-up continues a conversation, and nobody else
can. Run from the evals folder: `uv run live/conversation_check.py`. Settings come from
evals/.env; sign-ins are silent after the first time (the OS keychain keeps them)."""

import sys

from margin_evals.cases import OPENER
from margin_evals.live import chat, load_env, sign_in

FOLLOW_UP = "And in September 2026?"


def main() -> int:
    env = load_env()
    results: list[bool] = []

    def check(name: str, ok: bool, detail: object = "") -> None:
        results.append(bool(ok))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  ({detail})"))

    north = sign_in(env, "north.mgr")
    status, body = chat(env, north, OPENER)
    body = body or {}
    conversation_id = body.get("conversation_id")
    check(
        "north.mgr's first question opens a conversation (21.3%)",
        status == 200 and bool(conversation_id) and "21.3" in body.get("answer", ""),
        (status, body),
    )
    status, body = chat(env, north, FOLLOW_UP, conversation_id)
    body = body or {}
    check(
        "the follow-up is answered in context (24.1%)",
        status == 200
        and "24.1" in body.get("answer", "")
        and body.get("conversation_id") == conversation_id,
        (status, body),
    )
    status, body = chat(env, sign_in(env, "south.mgr"), "Repeat your last answer.", conversation_id)
    check(
        "south.mgr can't continue north.mgr's conversation",
        (status, body) == (404, {"error": "conversation not found"}),
        (status, body),
    )
    print(f"{sum(results)}/{len(results)} passed")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
