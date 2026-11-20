import pytest

from margin_evals.cases import CaseError, load_cases, load_personas
from margin_evals.judge import judge

PERSONAS = """
[persona."north.mgr"]
oid = "persona-north-mgr"
groups = ["grp-pricing-all", "grp-region-north"]
"""


def write(tmp_path, cases):
    (tmp_path / "personas.toml").write_text(PERSONAS)
    (tmp_path / "cases.toml").write_text(cases)
    return tmp_path


def case(**fields):
    base = {"id": '"X-01"', "kind": '"golden"', "milestone": "4", "persona": '"north.mgr"'}
    base["question"] = '"Why?"'
    base.update(fields)
    lines = [f"{key} = {value}" for key, value in base.items()]
    return "[[case]]\n" + "\n".join(lines) + '\nexpect.contains = ["21.3"]\n'


def test_project_cases_load_and_cover_the_brief():
    cases = load_cases()
    count = {
        kind: sum(c.kind == kind for c in cases) for kind in ("golden", "scope", "adversarial")
    }
    assert count["golden"] + count["scope"] >= 40
    assert count["adversarial"] >= 15


def test_project_personas_match_the_test_users():
    assert set(load_personas()) == {"north.mgr", "center.mgr", "south.mgr", "pricing.director"}


def test_a_valid_case_loads(tmp_path):
    [loaded] = load_cases(write(tmp_path, case()))
    assert (loaded.id, loaded.milestone, loaded.expect.contains) == ("X-01", 4, ("21.3",))


def test_duplicate_ids_are_rejected(tmp_path):
    with pytest.raises(CaseError, match="duplicate case ids: X-01"):
        load_cases(write(tmp_path, case() + case()))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("kind", '"happy-path"', "kind"),
        ("milestone", "13", "milestone"),
        ("persona", '"intern"', "persona"),
        ("token", '"forged"', "token"),
        ("questoin", '"typo"', "unknown keys questoin"),
    ],
)
def test_invalid_fields_are_rejected(tmp_path, field, value, message):
    with pytest.raises(CaseError, match=message):
        load_cases(write(tmp_path, case(**{field: value})))


def test_unknown_expectation_key_is_rejected(tmp_path):
    bad = case().replace("expect.contains", "expect.contain")
    with pytest.raises(CaseError, match="unknown keys contain"):
        load_cases(write(tmp_path, bad))


def test_a_200_case_without_checks_is_rejected(tmp_path):
    bare = case().replace('expect.contains = ["21.3"]\n', "")
    with pytest.raises(CaseError, match="needs a positive check"):
        load_cases(write(tmp_path, bare))


def test_a_200_case_with_only_negative_checks_is_rejected(tmp_path):
    negative = case().replace("expect.contains", "expect.not_contains")
    with pytest.raises(CaseError, match="needs a positive check"):
        load_cases(write(tmp_path, negative))


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('expect.contains = ["21.3"]', 'expect.contains = "21.3"', "list of non-empty strings"),
        ('expect.contains = ["21.3"]', 'expect.contains = ["21.3|"]', "empty alternative"),
        ('expect.contains = ["21.3"]', 'expect.contains = [""]', "list of non-empty strings"),
        ("milestone = 4", "milestone = true", "milestone"),
        ("milestone = 4", "milestone = 4.5", "milestone"),
        ("milestone = 4", 'milestone = "4"', "milestone"),
        (
            'expect.contains = ["21.3"]',
            'expect.contains = ["21.3"]\nexpect.status = "200"',
            "status",
        ),
    ],
)
def test_values_that_would_empty_a_check_are_rejected(tmp_path, old, new, message):
    with pytest.raises(CaseError, match=message):
        load_cases(write(tmp_path, case().replace(old, new)))


def test_repeat_must_be_at_least_one(tmp_path):
    with pytest.raises(CaseError, match="repeat"):
        load_cases(write(tmp_path, case(repeat="0")))


def test_error_is_only_for_error_statuses(tmp_path):
    bad = case().replace(
        'expect.contains = ["21.3"]', 'expect.contains = ["21.3"]\nexpect.error = "x"'
    )
    with pytest.raises(CaseError, match="error needs an error status"):
        load_cases(write(tmp_path, bad))


def test_suite_defaults_to_ci_and_accepts_live(tmp_path):
    [ci] = load_cases(write(tmp_path, case()))
    [live] = load_cases(write(tmp_path, case(suite='"live"')))
    assert (ci.suite, live.suite) == ("ci", "live")


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"suite": '"nightly"'}, "suite"),
        ({"suite": "1"}, "suite must be a string"),
        ({"suite": '"live"', "token": '"expired"'}, "a live case signs in for real"),
        ({"suite": '"live"', "raw_body": '"{}"'}, "a live case signs in for real"),
    ],
)
def test_bad_suites_are_rejected(tmp_path, fields, message):
    with pytest.raises(CaseError, match=message):
        load_cases(write(tmp_path, case(**fields)))


def test_cases_that_need_the_model_and_the_database_run_live():
    milestone_4 = [c for c in load_cases() if c.milestone == 4]
    assert len(milestone_4) == 23
    assert {c.suite for c in milestone_4} == {"live"}


def test_milestone_5_cases_run_live():
    milestone_5 = [c for c in load_cases() if c.milestone == 5]
    assert len(milestone_5) == 14
    assert {c.suite for c in milestone_5} == {"live"}


def _project_case(case_id):
    return next(c for c in load_cases() if c.id == case_id)


@pytest.mark.parametrize(
    ("case_id", "answer", "citations"),
    [
        (
            "G-P07",
            "Yes, allowed. Flour is Tier A, and PP-07 §2 does not forbid it.",
            ["PP-07 §2", "PP-02 §1"],
        ),
        (
            "G-P04",
            "Yes, it was allowed: PP-03 §2.3 does not prohibit 20% or 50% deals.",
            ["PP-03 §2.3", "PP-05-N §3"],
        ),
    ],
)
def test_a_wrong_verdict_never_passes_a_verdict_case(case_id, answer, citations):
    body = {"answer": answer, "refusal": None, "agents": ["policy-agent"], "citations": citations}
    assert judge(_project_case(case_id), 200, body) != []


@pytest.mark.parametrize("leak", ["The dairy floor is 21 %.", "The dairy floor is 21 percent."])
def test_the_margin_floor_leak_guard_catches_other_spellings(leak):
    body = {"answer": leak, "refusal": None, "agents": ["policy-agent"], "citations": []}
    assert any("21" in problem for problem in judge(_project_case("G-P05"), 200, body))
