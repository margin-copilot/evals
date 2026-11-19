"""Loads eval cases and personas from TOML and rejects malformed ones before anything runs."""

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

CASES_DIR = Path(__file__).resolve().parents[2] / "cases"
KINDS = frozenset({"plumbing", "golden", "scope", "adversarial"})
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


class CaseError(ValueError):
    pass


@dataclass(frozen=True)
class Persona:
    name: str
    oid: str
    groups: tuple[str, ...]


@dataclass(frozen=True)
class Expect:
    status: int = 200
    contains: tuple[str, ...] = ()  # each entry: alternatives separated by "|"
    not_contains: tuple[str, ...] = ()
    refusal: str | None = None
    agents: tuple[str, ...] = ()
    no_agents: bool = False
    citations: tuple[str, ...] = ()
    not_citations: tuple[str, ...] = ()


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
    if expect.refusal is not None and expect.refusal not in REFUSALS:
        problems.append(f"refusal {expect.refusal!r}")
    if not set(expect.agents) <= AGENTS:
        problems.append(f"agents {sorted(set(expect.agents) - AGENTS)}")
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
