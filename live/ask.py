"""Ask the deployed copilot one question as a test user:

uv run live/ask.py north.mgr "What was dairy margin in the North in October 2026?"
"""

import sys

from margin_evals.live import chat, load_env, sign_in


def main(args: list[str]) -> int:
    sys.stdout.reconfigure(line_buffering=True)  # show progress through `| tee` too
    if len(args) != 2:
        print(__doc__)
        return 2
    persona, question = args
    env = load_env()
    status, body = chat(env, sign_in(env, persona), question)
    if status != 200 or body is None:
        print(f"{status} {body}")
        return 1
    print(body["answer"])
    print(f"\nrefusal: {body.get('refusal')}   agents: {', '.join(body.get('agents') or [])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
