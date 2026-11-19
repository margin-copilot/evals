"""The live suite (D-033): live cases up to CURRENT_MILESTONE, against the deployed system.

    uv run live/run_cases.py                 # cases up to CURRENT_MILESTONE
    uv run live/run_cases.py --milestone 4   # before bumping CURRENT_MILESTONE
    uv run live/run_cases.py G-D01 A-10      # just these cases

The browser opens once per test user; sign in as the user it names. Prints every answer so the
case wording can be reviewed against it (D-029).
"""

import sys
from itertools import groupby

from margin_evals import CURRENT_MILESTONE
from margin_evals.cases import load_cases
from margin_evals.judge import judge
from margin_evals.live import chat, load_env, sign_in


def main(args: list[str]) -> int:
    sys.stdout.reconfigure(line_buffering=True)  # show progress through `| tee` too
    milestone = CURRENT_MILESTONE
    if args[:1] == ["--milestone"]:
        milestone, args = int(args[1]), args[2:]
    cases = [
        case
        for case in load_cases()
        if case.suite == "live" and case.milestone <= milestone and (not args or case.id in args)
    ]
    if not cases:
        print("no live cases selected")
        return 1
    env = load_env()
    failed = []
    for persona, group in groupby(
        sorted(cases, key=lambda c: (c.persona, c.id)), lambda c: c.persona
    ):
        print(f"\nSign in as {persona} in the browser.")
        token = sign_in(env, persona)
        for case in group:
            status, body = chat(env, token, case.question)
            problems = judge(case, status, body)
            failed += [case.id] if problems else []
            print(f"{'FAIL' if problems else 'PASS'}  {case.id}  {'; '.join(problems)}")
            print(f"      {status} {body}")
    print(
        f"\n{len(cases) - len(failed)}/{len(cases)} passed"
        + (f"; failed: {' '.join(failed)}" if failed else "")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
