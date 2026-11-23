import re

import pytest

from margin_evals.telemetry import new_trace_id, summarize, traceparent

TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"


def row(kind, name, role, ms, **properties):
    return {
        "OperationId": TRACE,
        "Type": kind,
        "Name": name,
        "AppRoleName": role,
        "DurationMs": ms,
        "Properties": properties,
    }


def tokens(input_tokens, output_tokens):
    return {
        "gen_ai.usage.input_tokens": str(input_tokens),
        "gen_ai.usage.output_tokens": str(output_tokens),
    }


COMPOSED_TURN = [
    row("AppRequests", "POST", "orchestrator", 9000.0),
    row("AppDependencies", "orchestrator.route", "orchestrator", 1500.0),
    row(
        "AppDependencies",
        "orchestrator.agent",
        "orchestrator",
        5000.0,
        **{"margin.agent": "data-agent"},
    ),
    row(
        "AppDependencies",
        "orchestrator.agent",
        "orchestrator",
        3000.0,
        **{"margin.agent": "policy-agent"},
    ),
    row("AppDependencies", "orchestrator.compose", "orchestrator", 2000.0),
    row("AppDependencies", "chat gpt-5-mini", "orchestrator", 1400.0, **tokens(1000, 200)),
    row("AppDependencies", "chat gpt-5-mini", "data-agent", 4000.0, **tokens(3000, 400)),
    row("AppDependencies", "chat gpt-5-mini", "policy-agent", 2500.0, **tokens(500, 100)),
    row("AppRequests", "POST", "data-agent", 5200.0),  # an agent's own request: not the turn's
]


def test_traceparent_is_w3c():
    trace_id = new_trace_id()
    assert re.fullmatch(r"[0-9a-f]{32}", trace_id) and trace_id != new_trace_id()
    assert re.fullmatch(rf"00-{trace_id}-[0-9a-f]{{16}}-01", traceparent(trace_id))


def test_a_turn_sums_steps_tokens_and_cost():
    (cost,) = summarize(COMPOSED_TURN, input_price=0.25, output_price=2.0).values()
    assert cost.total_ms == 9000.0
    assert cost.steps["orchestrator.route"] == 1500.0
    assert cost.steps["agent:data-agent"] == 5000.0 and cost.steps["agent:policy-agent"] == 3000.0
    assert cost.steps["orchestrator.compose"] == 2000.0
    assert (cost.model_calls, cost.input_tokens, cost.output_tokens) == (3, 4500, 700)
    assert cost.usd == pytest.approx(0.002525)


def test_properties_may_arrive_as_json_text():
    rows = [row("AppRequests", "POST", "orchestrator", 100.0)]
    rows.append(
        {
            **row("AppDependencies", "chat gpt-5-mini", "orchestrator", 50.0),
            "Properties": '{"gen_ai.usage.input_tokens": "10", "gen_ai.usage.output_tokens": "2"}',
        }
    )
    (cost,) = summarize(rows, input_price=1.0, output_price=1.0).values()
    assert (cost.input_tokens, cost.output_tokens) == (10, 2)


def test_a_trace_without_rows_is_missing():
    without_request = [r for r in COMPOSED_TURN if r["Type"] != "AppRequests"]
    assert summarize(without_request, input_price=0.25, output_price=2.0) == {}


def test_cached_input_is_priced_at_the_cached_rate():
    rows = [
        row("AppRequests", "POST", "orchestrator", 100.0),
        row(
            "AppDependencies",
            "chat gpt-5-mini",
            "policy-agent",
            50.0,
            **tokens(10000, 1000),
            **{"gen_ai.usage.cache_read.input_tokens": "8000"},
        ),
    ]
    (cost,) = summarize(rows, input_price=0.25, output_price=2.0, cached_price=0.025).values()
    assert cost.input_tokens == 10000 and cost.cached_tokens == 8000
    assert cost.usd == pytest.approx(2000 / 1e6 * 0.25 + 8000 / 1e6 * 0.025 + 1000 / 1e6 * 2.0)
