"""Loads eval cases and personas from TOML and rejects malformed ones before anything runs."""

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

CASES_DIR = Path(__file__).resolve().parents[2] / "cases"
KINDS = frozenset({"plumbing", "golden", "scope", "adversarial"})
# ci: in-process on fakes (D-019). live: the deployed system, real sign-ins, model and data (D-033).
SUITES = frozenset({"ci", "live"})
REFUSALS = frozenset({"out_of_scope", "no_access", "no_data"})
TOKENS = frozenset(
    {
        "valid",
        "none",
        "unlisted_app",
        "data_agent_audience",
        "expired",
        "missing_scope",
        "other_issuer",
    }
)
AGENTS = frozenset({"data-agent", "policy-agent", "action-agent"})
LAST_MILESTONE = 12
LIST_FIELDS = ("contains", "not_contains", "agents", "not_agents", "citations", "not_citations")


class CaseError(ValueError):
    pass


@dataclass(frozen=True)
class Persona:
    name: str
    oid: str
    groups: tuple[str, ...]


# The first turn a case with conversation_of opens, as that persona (D-011: the conversation the
# case then tries to continue as someone else).
OPENER = "What was North dairy margin in October 2026?"


@dataclass(frozen=True)
class Expect:
    status: int = 200
    contains: tuple[str, ...] = ()  # each entry: alternatives separated by "|"
    not_contains: tuple[str, ...] = ()
    refusal: str | None = None
    agents: tuple[str, ...] = ()
    not_agents: tuple[str, ...] = ()
    no_agents: bool = False
    citations: tuple[str, ...] = ()
    not_citations: tuple[str, ...] = ()
    error: str | None = None  # text the error reason must contain, for error statuses


@dataclass(frozen=True)
class Case:
    id: str
    kind: str
    milestone: int
    persona: str
    question: str
    expect: Expect
    token: str = "valid"
    raw_body: str | None = None
    repeat: int = 1
    suite: str = "ci"
    conversation_of: str | None = None  # the runner opens a conversation as this persona first
    note: str = ""


def load_personas(path: Path = CASES_DIR / "personas.toml") -> dict[str, Persona]:
    data = tomllib.loads(path.read_text())
    return {
        name: Persona(name=name, oid=raw["oid"], groups=tuple(raw["groups"]))
        for name, raw in data["persona"].items()
    }


def load_cases(
    directory: Path = CASES_DIR, personas: dict[str, Persona] | None = None
) -> list[Case]:
    personas = personas if personas is not None else load_personas(directory / "personas.toml")
    cases: list[Case] = []
    for path in sorted(directory.glob("*.toml")):
        if path.name == "personas.toml":
            continue
        for raw in tomllib.loads(path.read_text()).get("case", []):
            cases.append(_case(raw, personas, path.name))
    ids = [case.id for case in cases]
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise CaseError(f"duplicate case ids: {', '.join(duplicates)}")
    return cases


def _case(raw: dict, personas: dict[str, Persona], source: str) -> Case:
    where = f"{source} case {raw.get('id', '?')}"
    raw = dict(raw)
    expect_raw = raw.pop("expect", {})
    _check_keys(raw, {f.name for f in fields(Case)} - {"expect"}, where)
    _check_keys(expect_raw, {f.name for f in fields(Expect)}, f"{where} expect")
    _check_types(raw, expect_raw, where)
    expect = Expect(**{k: tuple(v) if isinstance(v, list) else v for k, v in expect_raw.items()})
    case = Case(expect=expect, **raw)
    problems = []
    if case.kind not in KINDS:
        problems.append(f"kind {case.kind!r}")
    if not 1 <= case.milestone <= LAST_MILESTONE:
        problems.append(f"milestone {case.milestone}")
    if case.persona not in personas:
        problems.append(f"persona {case.persona!r}")
    if case.token not in TOKENS:
        problems.append(f"token {case.token!r}")
    if case.suite not in SUITES:
        problems.append(f"suite {case.suite!r}")
    if case.conversation_of is not None and (
        case.conversation_of not in personas or case.token != "valid" or case.raw_body is not None
    ):
        problems.append(f"conversation_of {case.conversation_of!r} (a persona, with a valid token)")
    if case.suite == "live" and (case.token != "valid" or case.raw_body is not None):
        problems.append("token or raw_body (a live case signs in for real and asks a question)")
    if expect.refusal is not None and expect.refusal not in REFUSALS:
        problems.append(f"refusal {expect.refusal!r}")
    if expect.error is not None and expect.status < 400:
        problems.append("expect.error needs an error status")
    if not set(expect.agents) | set(expect.not_agents) <= AGENTS:
        problems.append(f"agents {sorted((set(expect.agents) | set(expect.not_agents)) - AGENTS)}")
    # Negative checks alone pass on a system that says nothing, so a 200 case needs a positive one.
    if expect.status == 200 and not (
        expect.contains or expect.agents or expect.citations or expect.refusal
    ):
        problems.append("a 200 case needs a positive check (contains, agents, citations, refusal)")
    if problems:
        raise CaseError(f"{where}: invalid {', '.join(problems)}")
    return case


def _check_keys(raw: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise CaseError(f"{where}: unknown keys {', '.join(unknown)}")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_types(raw: dict, expect_raw: dict, where: str) -> None:
    """Rejects values that would silently empty a check (a string read as a list, "a|" etc.)."""
    problems = []
    for name in ("id", "kind", "persona", "question", "token", "suite", "conversation_of", "note"):
        if name in raw and not isinstance(raw[name], str):
            problems.append(f"{name} must be a string")
    if not _is_int(raw.get("milestone")):
        problems.append("milestone must be an integer")
    if "repeat" in raw and not (_is_int(raw["repeat"]) and raw["repeat"] >= 1):
        problems.append("repeat must be an integer of at least 1")
    if "raw_body" in raw and not isinstance(raw["raw_body"], str):
        problems.append("raw_body must be a string")
    if "status" in expect_raw and not _is_int(expect_raw["status"]):
        problems.append("status must be an integer")
    if "no_agents" in expect_raw and not isinstance(expect_raw["no_agents"], bool):
        problems.append("no_agents must be true or false")
    for name in ("refusal", "error"):
        if name in expect_raw and not isinstance(expect_raw[name], str):
            problems.append(f"{name} must be a string")
    for name in LIST_FIELDS:
        value = expect_raw.get(name, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            problems.append(f"{name} must be a list of non-empty strings")
        elif any(not alt.strip() for v in value for alt in v.split("|")):
            problems.append(f"{name} has an empty alternative")
    if problems:
        raise CaseError(f"{where}: {', '.join(problems)}")
