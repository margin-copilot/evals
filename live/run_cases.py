"""The live suite (D-033): live cases up to CURRENT_MILESTONE, against the deployed system.

    uv run live/run_cases.py                 # cases up to CURRENT_MILESTONE
    uv run live/run_cases.py --milestone 4   # before bumping CURRENT_MILESTONE
    uv run live/run_cases.py G-D01 A-10      # just these cases

The browser opens once per test user; sign in as the user it names. Prints every answer so the
case wording can be reviewed against it (D-029), then each question's time and cost, read from its
trace (MONITOR_WORKSPACE_ID; prices per million tokens in MODEL_INPUT/OUTPUT_USD_PER_MTOK).
"""

import sys
from itertools import groupby

from margin_evals import CURRENT_MILESTONE
from margin_evals.cases import OPENER, load_cases
from margin_evals.judge import judge
from margin_evals.live import chat, load_env, sign_in
from margin_evals.telemetry import fetch_rows, new_trace_id, summarize


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
    failed, traces = [], {}
    for persona, group in groupby(
        sorted(cases, key=lambda c: (c.persona, c.id)), lambda c: c.persona
    ):
        print(f"\nSign in as {persona} in the browser.")
        token = sign_in(env, persona)
        for case in group:
            conversation_id = None
            if case.conversation_of is not None:  # open a conversation as someone else first
                _, opened = chat(env, sign_in(env, case.conversation_of), OPENER)
                conversation_id = (opened or {}).get("conversation_id")
            traces[case.id] = new_trace_id()
            status, body = chat(env, token, case.question, conversation_id, traces[case.id])
            problems = judge(case, status, body)
            failed += [case.id] if problems else []
            print(f"{'FAIL' if problems else 'PASS'}  {case.id}  {'; '.join(problems)}")
            print(f"      {status} {body}")
    print(
        f"\n{len(cases) - len(failed)}/{len(cases)} passed"
        + (f"; failed: {' '.join(failed)}" if failed else "")
    )
    report(env, traces)
    return 1 if failed else 0


COLUMNS = (
    "case",
    "total s",
    "route",
    "data",
    "policy",
    "action",
    "compose",
    "calls",
    "in",
    "out",
    "$",
)
ROW = "{:8} {:>7} {:>6} {:>6} {:>6} {:>6} {:>7} {:>5} {:>7} {:>6} {:>8}"
STEPS = ("orchestrator.route", "agent:data-agent", "agent:policy-agent", "agent:action-agent")


def report(env: dict[str, str], traces: dict[str, str]) -> None:
    """Time and cost per question. A missing trace is reported, not judged: answers are the gate."""
    if not env.get("MONITOR_WORKSPACE_ID"):
        print("\nno time and cost report: set MONITOR_WORKSPACE_ID (infra scripts/spike-env.sh)")
        return
    from azure.identity import AzureCliCredential  # the owner's az login reads the workspace

    print("\nWaiting for the traces (ingestion takes a few minutes)...")
    rows = fetch_rows(env["MONITOR_WORKSPACE_ID"], list(traces.values()), AzureCliCredential())
    kinds = ("INPUT", "OUTPUT", "CACHED_INPUT")
    prices = [float(env.get(f"MODEL_{kind}_USD_PER_MTOK") or 0) for kind in kinds]
    costs = summarize(rows, *prices)
    print("\n" + ROW.format(*COLUMNS))
    for case_id, trace_id in traces.items():
        if (cost := costs.get(trace_id)) is not None:
            seconds = [
                cost.steps.get(name, 0.0) / 1000 for name in (*STEPS, "orchestrator.compose")
            ]
            print(
                ROW.format(
                    case_id,
                    f"{cost.total_ms / 1000:.1f}",
                    *(f"{value:.1f}" for value in seconds),
                    cost.model_calls,
                    cost.input_tokens,
                    cost.output_tokens,
                    f"{cost.usd:.4f}",
                )
            )
    if costs:
        total = sum(c.usd for c in costs.values())
        average = sum(c.total_ms for c in costs.values()) / len(costs) / 1000
        each = total / len(costs)
        print(f"\n{len(costs)} questions: average {average:.1f} s, ${each:.4f} each, ${total:.4f}")
    if missing := [case_id for case_id, trace_id in traces.items() if trace_id not in costs]:
        print(f"missing: {' '.join(missing)}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
