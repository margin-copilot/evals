import pytest

from margin_evals.cases import CaseError, load_cases

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
