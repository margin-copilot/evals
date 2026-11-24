"""Compares one chat API response with a case's expectations."""

import re
from collections.abc import Sequence
from decimal import Decimal

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


# The data agent reports these in their own fields; in an answer they are a leak (seen live).
INTERNAL_FIELD = re.compile(r"\b(regions_asked|found_data)\b")
NUMBER = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)(%?)")
DECIMAL_OR_PERCENT = re.compile(r"(\d+(?:\.\d+)?)(%?)")


def mentions(answer: str, text: str) -> bool:
    """Substring match, but numbers match whole: "0%" isn't in "30%", "21.3" isn't in "121.3".
    A decimal or a percentage matches by value and unit, so "30%" finds "30.0%" and "7.20" finds
    "7.2"; a plain integer stays exact, so "35" doesn't find an unrelated "35.00"."""
    text = text.strip().lower()
    target = DECIMAL_OR_PERCENT.fullmatch(text)
    if target and (target.group(2) or "." in target.group(1)):
        value, percent = Decimal(target.group(1)), target.group(2)
        return any(
            Decimal(number) == value and (unit or not percent)
            for number, unit in NUMBER.findall(answer)
        )
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
    if leaked := sorted(set(INTERNAL_FIELD.findall(answer))):
        problems.append(f"answer names an internal field: {', '.join(leaked)}")
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


def stream_problems(events: Sequence[str]) -> list[str]:
    """A streamed turn's events in order (D-045): steps first, at most one lead, then one done or
    error, last. An error may come before any step (an unknown conversation fails first)."""
    terminal = [i for i, event in enumerate(events) if event in ("done", "error")]
    if not terminal:
        return ["stream ended without done or error"]
    problems = []
    if len(terminal) > 1 or terminal[0] != len(events) - 1:
        problems.append("events after the answer")
    if events[terminal[0]] == "done" and "step" not in events[: terminal[0]]:
        problems.append("no step before the answer")
    if (leads := list(events).count("lead")) > 1:
        problems.append(f"{leads} lead events")
    return problems
