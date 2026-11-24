"""Ask the deployed copilot one question as a test user:

uv run live/ask.py north.mgr "What was dairy margin in the North in October 2026?"
uv run live/ask.py --stream north.mgr "..."   # each event and its time first (D-045)
"""

import sys

from margin_evals.live import chat, chat_stream, load_env, sign_in


def main(args: list[str]) -> int:
    sys.stdout.reconfigure(line_buffering=True)  # show progress through `| tee` too
    stream = args[:1] == ["--stream"]
    args = args[1:] if stream else args
    if len(args) != 2:
        print(__doc__)
        return 2
    persona, question = args
    env = load_env()
    if stream:
        status, body, events = chat_stream(env, sign_in(env, persona), question)
        for event, at in events:
            print(f"{at:6.1f} s  {event}")
    else:
        status, body = chat(env, sign_in(env, persona), question)
    if status != 200 or body is None:
        print(f"{status} {body}")
        return 1
    print(body["answer"])
    print(f"\nrefusal: {body.get('refusal')}   agents: {', '.join(body.get('agents') or [])}")
    if body.get("citations"):
        print(f"citations: {', '.join(body['citations'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
