import pytest

from margin_evals.cases import Case, Expect
from margin_evals.judge import CaseFailed, SystemFault, judge, stream_problems, verdict


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


def test_an_answer_naming_the_data_agents_fields_fails_any_case():
    # Seen live (G-C01, passed): the data agent's reported facts written into the answer.
    body = {"answer": 'Margin fell to 21.3%. regions_asked: ["N"]. found_data: true.'}
    assert judge(case(contains=("21.3",)), 200, body) == [
        "answer names an internal field: found_data, regions_asked"
    ]


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


def test_missing_fields_are_reported_and_count_as_empty():
    assert judge(case(citations=("PP-01 §5",)), 200, None) == [
        "response has no citations field",
        "missing citations: PP-01 §5",
    ]


@pytest.mark.parametrize(
    ("expected", "answer"),
    [
        ("0%", "30% off"),
        ("0%", "costs up 6.0%"),
        ("21.3", "121.3"),
        ("35", "35.00 MAD"),
        ("30%", "for 30 days"),
        ("2.9", "2.95%"),
    ],
)
def test_numbers_match_whole_numbers_only(expected, answer):
    assert judge(case(contains=(expected,)), 200, {"answer": answer}) == [
        f"answer lacks {expected!r}"
    ]


@pytest.mark.parametrize(
    ("expected", "answer"),
    [
        ("0%", "0% supplier funding"),
        ("35", "rose 35%"),
        ("24.1", "from 24.1%"),
        ("yogurt", "yogurts"),
        # Same value, written differently: a decimal or percentage matches by value and unit.
        ("30%", "a 30.0% discount"),
        ("7.20", "price 7.2 MAD"),
        ("24.1", "from 24.10%"),
    ],
)
def test_whole_numbers_and_word_stems_still_match(expected, answer):
    assert judge(case(contains=(expected,)), 200, {"answer": answer}) == []


def test_each_forbidden_alternative_is_checked():
    assert judge(case(not_contains=("23.6|24.2",)), 200, {"answer": "South 24.2"}) == [
        "answer contains '24.2'"
    ]


def test_forbidden_agents():
    body = {"answer": "a", "agents": ["policy-agent", "action-agent"]}
    assert judge(case(not_agents=("action-agent",)), 200, body) == [
        "forbidden agents called: action-agent"
    ]


def test_unexpected_server_error_is_a_system_fault_not_a_case_failure():
    with pytest.raises(SystemFault):
        verdict(case(contains=("21.3",)), 502, {"error": "data-agent unavailable"})


def test_verdict_raises_case_failed_for_a_wrong_answer_and_passes_a_right_one():
    with pytest.raises(CaseFailed, match="answer lacks"):
        verdict(case(contains=("21.3",)), 200, {"answer": "24.2"})
    verdict(case(status=401), 401, {"error": "missing bearer token"})


def test_a_missing_agents_field_fails_an_agent_check():
    assert judge(
        case(no_agents=True, refusal="out_of_scope"), 200, {"refusal": "out_of_scope"}
    ) == ["response has no agents field"]


def test_a_missing_citations_field_fails_a_citation_check():
    body = {"answer": "the floor is secret", "agents": ["policy-agent"]}
    expect = case(agents=("policy-agent",), not_citations=("PP-06 §1",))
    assert judge(expect, 200, body) == ["response has no citations field"]


def test_error_reason_is_checked():
    assert judge(
        case(status=403, error="calling app not allowed"), 403, {"error": "missing scope"}
    ) == ["error 'missing scope', expected 'calling app not allowed'"]
    assert judge(case(status=403, error="missing scope"), 403, {"error": "missing scope"}) == []


def test_a_stream_ending_in_done_after_a_step_is_fine():
    assert stream_problems(["step", "step", "lead", "step", "done"]) == []
    assert stream_problems(["step", "error"]) == []
    assert stream_problems(["error"]) == []  # an unknown conversation fails before any stage


def test_a_stream_without_done_or_error_is_a_problem():
    assert stream_problems(["step", "lead"]) == ["stream ended without done or error"]
    assert stream_problems(["done"]) == ["no step before the answer"]
    assert stream_problems(["step", "done", "step"]) == ["events after the answer"]


def test_two_leads_are_a_problem():
    assert stream_problems(["step", "lead", "lead", "done"]) == ["2 lead events"]
