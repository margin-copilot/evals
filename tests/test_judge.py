from margin_evals.cases import Case, Expect
from margin_evals.judge import judge


def case(**expect):
    return Case(
        id="X",
        kind="golden",
        milestone=4,
        persona="north.mgr",
        question="q",
        expect=Expect(**expect),
    )


def test_matching_answer_has_no_problems():
    body = {
        "answer": "North dairy margin fell to 21.3% after UHT costs rose",
        "agents": ["data-agent"],
    }
    assert judge(case(contains=("21.3", "uht"), agents=("data-agent",)), 200, body) == []


def test_alternatives_accept_either_wording():
    assert judge(case(contains=("6.0%|6%",)), 200, {"answer": "costs rose 6%"}) == []


def test_missing_and_forbidden_text_are_reported():
    expect = case(contains=("21.3",), not_contains=("24.2",))
    problems = judge(expect, 200, {"answer": "South 24.2"})
    assert problems == ["answer lacks '21.3'", "answer contains '24.2'"]


def test_wrong_status_is_the_only_problem_reported():
    assert judge(case(contains=("21.3",)), 502, {"error": "x"}) == ["status 502, expected 200"]


def test_expected_error_status_passes():
    assert judge(case(status=401), 401, {"error": "missing bearer token"}) == []


def test_refusals_are_compared_by_kind():
    assert judge(case(refusal="no_access"), 200, {"answer": "...", "refusal": "no_access"}) == []
    assert judge(case(refusal="no_access"), 200, {"answer": "24.2"}) == [
        "refusal None, expected 'no_access'"
    ]


def test_unexpected_refusal_fails_a_content_case():
    body = {"answer": "21.3 is outside your access", "refusal": "no_access"}
    assert judge(case(contains=("21.3",)), 200, body) == ["unexpected refusal 'no_access'"]


def test_agents_and_citations():
    body = {"answer": "a", "agents": ["policy-agent"], "citations": ["PP-06 §1"]}
    expect = case(agents=("data-agent",), citations=("PP-04 §3.2",), not_citations=("PP-06 §1",))
    assert judge(expect, 200, body) == [
        "agents not called: data-agent",
        "missing citations: PP-04 §3.2",
        "forbidden citations: PP-06 §1",
    ]


def test_no_agents_means_no_tool_calls():
    assert judge(case(no_agents=True), 200, {"answer": "no", "agents": ["data-agent"]}) == [
        "agents called: data-agent"
    ]


def test_missing_fields_count_as_empty():
    assert judge(case(citations=("PP-01 §5",)), 200, None) == ["missing citations: PP-01 §5"]
