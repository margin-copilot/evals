"""Compares one chat API response with a case's expectations."""

import re

from margin_evals.cases import Case


class CaseFailed(AssertionError):
    """The system answered, but not as the case expects. The only way a pending case may fail."""


class SystemFault(Exception):
    """The system broke (5xx) where the case expects an answer. Never an expected failure."""


def verdict(case: Case, status: int, body: dict | None) -> None:
    if status >= 500 and case.expect.status < 500:
        raise SystemFault(f"status {status}: {body}")
    if problems := judge(case, status, body):
        raise CaseFailed("; ".join(problems))


def mentions(answer: str, text: str) -> bool:
    """Substring match, but numbers match whole: "0%" isn't in "30%", "21.3" isn't in "121.3"."""
    text = text.strip().lower()
    pattern = re.escape(text)
    if text[:1].isdigit():
        pattern = r"(?<![\d.])" + pattern
    if text[-1:].isdigit():
        pattern += r"(?!\.?\d)"
    return re.search(pattern, answer) is not None


def judge(case: Case, status: int, body: dict | None) -> list[str]:
    expect = case.expect
    if status != expect.status:
        return [f"status {status}, expected {expect.status}"]
    if status != 200:
        reason = str(body.get("error", "")) if isinstance(body, dict) else ""
        if expect.error is not None and expect.error.lower() not in reason.lower():
            return [f"error {reason!r}, expected {expect.error!r}"]
        return []
    body = body if isinstance(body, dict) else {}
    answer = str(body.get("answer", "")).lower()
    refusal = body.get("refusal")
    agents = set(body.get("agents") or [])
    citations = set(body.get("citations") or [])
    problems = []
    for item in expect.contains:
        if not any(mentions(answer, alt) for alt in item.split("|")):
            problems.append(f"answer lacks {item!r}")
    for item in expect.not_contains:
        for alt in item.split("|"):
            if mentions(answer, alt):
                problems.append(f"answer contains {alt.strip()!r}")
    if expect.refusal is not None and refusal != expect.refusal:
        problems.append(f"refusal {refusal!r}, expected {expect.refusal!r}")
    if expect.refusal is None and expect.contains and refusal:
        problems.append(f"unexpected refusal {refusal!r}")
    if (expect.agents or expect.not_agents or expect.no_agents) and "agents" not in body:
        problems.append("response has no agents field")
    if (expect.citations or expect.not_citations) and "citations" not in body:
        problems.append("response has no citations field")
    if missing := sorted(set(expect.agents) - agents):
        problems.append(f"agents not called: {', '.join(missing)}")
    if forbidden := sorted(set(expect.not_agents) & agents):
        problems.append(f"forbidden agents called: {', '.join(forbidden)}")
    if expect.no_agents and agents:
        problems.append(f"agents called: {', '.join(sorted(agents))}")
    if missing := sorted(set(expect.citations) - citations):
        problems.append(f"missing citations: {', '.join(missing)}")
    if forbidden := sorted(set(expect.not_citations) & citations):
        problems.append(f"forbidden citations: {', '.join(forbidden)}")
    return problems
