"""Time and cost per question (roadmap milestone 9): the live runner sends each case's own trace
ID, then reads that trace's rows from the Log Analytics workspace (D-043). Telemetry carries
durations, labels and token counts, never content."""

import json
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

QUERY = """union AppRequests, AppDependencies
| where OperationId in (dynamic({ids}))
| project OperationId, Type, Name, AppRoleName, DurationMs, Properties"""


@dataclass(frozen=True)
class TurnCost:
    total_ms: float
    steps: dict[str, float] = field(default_factory=dict)
    model_calls: int = 0
    input_tokens: int = 0  # cached ones included, as the model reports them
    cached_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0


def new_trace_id() -> str:
    return secrets.token_hex(16)


def traceparent(trace_id: str) -> str:
    return f"00-{trace_id}-{secrets.token_hex(8)}-01"


def _properties(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("Properties") or {}
    return json.loads(value) if isinstance(value, str) else value


def summarize(
    rows: list[dict[str, Any]],
    input_price: float,
    output_price: float,
    cached_price: float | None = None,
) -> dict[str, TurnCost]:
    """Keyed by trace ID; a trace without the orchestrator's request row is left out (missing).
    Cached input tokens cost `cached_price` (the full input price when it isn't given)."""
    by_trace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_trace[row["OperationId"]].append(row)
    costs = {}
    for trace_id, trace_rows in by_trace.items():
        turn = [
            r
            for r in trace_rows
            if r["Type"] == "AppRequests" and r["AppRoleName"] == "orchestrator"
        ]
        if not turn:
            continue
        steps: dict[str, float] = defaultdict(float)
        calls = input_tokens = cached_tokens = output_tokens = 0
        for r in trace_rows:
            if r["Type"] != "AppDependencies":
                continue
            properties = _properties(r)
            if r["Name"].startswith("chat "):
                calls += 1
                input_tokens += int(properties.get("gen_ai.usage.input_tokens", 0))
                cached_tokens += int(properties.get("gen_ai.usage.cache_read.input_tokens", 0))
                output_tokens += int(properties.get("gen_ai.usage.output_tokens", 0))
            elif r["Name"] == "orchestrator.agent":
                steps[f"agent:{properties.get('margin.agent')}"] += r["DurationMs"]
            else:
                steps[r["Name"]] += r["DurationMs"]
        costs[trace_id] = TurnCost(
            total_ms=turn[0]["DurationMs"],
            steps=dict(steps),
            model_calls=calls,
            input_tokens=input_tokens,
            cached_tokens=cached_tokens,
            output_tokens=output_tokens,
            usd=(input_tokens - cached_tokens) / 1e6 * input_price
            + cached_tokens / 1e6 * (input_price if cached_price is None else cached_price)
            + output_tokens / 1e6 * output_price,
        )
    return costs


def fetch_rows(
    workspace_id: str, trace_ids: list[str], credential: Any, wait_s: int = 600
) -> list[dict[str, Any]]:
    """Ingestion takes minutes: polls every 30 s until each trace has its turn row, or wait_s."""
    from azure.monitor.query import LogsQueryClient  # live runs only

    client = LogsQueryClient(credential)
    query = QUERY.format(ids=json.dumps(trace_ids))
    deadline = time.monotonic() + wait_s
    while True:
        result = client.query_workspace(workspace_id, query, timespan=timedelta(days=1))
        rows = [
            dict(zip(table.columns, row, strict=True))
            for table in result.tables
            for row in table.rows
        ]
        arrived = {
            r["OperationId"]
            for r in rows
            if r["Type"] == "AppRequests" and r["AppRoleName"] == "orchestrator"
        }
        if arrived >= set(trace_ids) or time.monotonic() > deadline:
            return rows
        time.sleep(30)
