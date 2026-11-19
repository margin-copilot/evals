"""The eval suite. Cases for milestones up to CURRENT_MILESTONE must pass. Later cases must fail
with CaseFailed (the system answered, but not as expected); a crash or an early pass fails CI."""

import pytest

from margin_evals import CURRENT_MILESTONE
from margin_evals.cases import load_cases, load_personas
from margin_evals.judge import CaseFailed, judge
from margin_evals.system import System

PERSONAS = load_personas()


def cases():
    for case in load_cases(personas=PERSONAS):
        marks = []
        if case.milestone > CURRENT_MILESTONE:
            reason = f"needs milestone {case.milestone}"
            marks.append(pytest.mark.xfail(raises=CaseFailed, strict=True, reason=reason))
        yield pytest.param(case, id=case.id, marks=marks)


@pytest.mark.parametrize("case", list(cases()))
async def test_case(case):
    status, body = await System().ask(case, PERSONAS[case.persona])
    if problems := judge(case, status, body):
        raise CaseFailed("; ".join(problems))
