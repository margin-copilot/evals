"""The eval suite. Cases for milestones up to CURRENT_MILESTONE must pass. Later cases must fail
with CaseFailed (the system answered, but not as expected). A crash, a 5xx where an answer was
expected (SystemFault), or an early pass fails CI."""

import pytest

from margin_evals import CURRENT_MILESTONE
from margin_evals.cases import load_cases, load_personas
from margin_evals.judge import CaseFailed, verdict
from margin_evals.system import System

PERSONAS = load_personas()


def cases():
    for case in load_cases(personas=PERSONAS):
        marks = []
        if case.suite == "live":
            marks.append(pytest.mark.skip(reason="live suite: uv run live/run_cases.py"))
        elif case.milestone > CURRENT_MILESTONE:
            reason = f"needs milestone {case.milestone}"
            marks.append(pytest.mark.xfail(raises=CaseFailed, strict=True, reason=reason))
        yield pytest.param(case, id=case.id, marks=marks)


@pytest.mark.parametrize("case", list(cases()))
async def test_case(case):
    status, body = await System().ask(case, PERSONAS[case.persona])
    verdict(case, status, body)
