"""Compares one chat API response with a case's expectations."""

from margin_evals.cases import Case


class CaseFailed(AssertionError):
    """The system answered, but not as the case expects. The only way a pending case may fail."""


def judge(case: Case, status: int, body: dict | None) -> list[str]:
    expect = case.expect
    if status != expect.status:
        return [f"status {status}, expected {expect.status}"]
    if status != 200:
        return []
    body = body if isinstance(body, dict) else {}
    answer = str(body.get("answer", "")).lower()
    refusal = body.get("refusal")
    agents = set(body.get("agents") or [])
    citations = set(body.get("citations") or [])
    problems = []
    for item in expect.contains:
        if not any(alt.strip().lower() in answer for alt in item.split("|")):
            problems.append(f"answer lacks {item!r}")
    for item in expect.not_contains:
        if item.lower() in answer:
            problems.append(f"answer contains {item!r}")
    if expect.refusal is not None and refusal != expect.refusal:
        problems.append(f"refusal {refusal!r}, expected {expect.refusal!r}")
    if expect.refusal is None and expect.contains and refusal:
        problems.append(f"unexpected refusal {refusal!r}")
    if missing := sorted(set(expect.agents) - agents):
        problems.append(f"agents not called: {', '.join(missing)}")
    if expect.no_agents and agents:
        problems.append(f"agents called: {', '.join(sorted(agents))}")
    if missing := sorted(set(expect.citations) - citations):
        problems.append(f"missing citations: {', '.join(missing)}")
    if forbidden := sorted(set(expect.not_citations) & citations):
        problems.append(f"forbidden citations: {', '.join(forbidden)}")
    return problems
