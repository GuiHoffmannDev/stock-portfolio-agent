import json
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import stock_analysis
from main import app
from stock_analysis import (
    Insight,
    Insights,
    PortfolioRequest,
    Position,
    UserFacingError,
    analyze,
    normalize_request,
)

TODAY = date(2026, 1, 15)
PRICES = pd.DataFrame(
    {"AAA": [10.0, 12.0, 15.0], "BBB": [None, 50.0, 25.0]},
    index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
)


def test_analyze_buys_on_first_common_day():
    result = analyze(PRICES, {"AAA": 1200.0, "BBB": 1000.0})

    assert result["start_date"] == "2025-01-03"
    assert result["invested"] == 2200.0
    assert result["value"] == 2000.0  # AAA 1200 -> 1500, BBB 1000 -> 500
    assert result["return_pct"] == -9.09
    assert result["holdings"][0] == {
        "ticker": "AAA", "invested": 1200.0, "value": 1500.0, "return_pct": 25.0, "allocation_pct": 75.0,
    }
    assert result["history"] == [
        {"date": "2025-01-03", "value": 2200.0, "holdings": {"AAA": 1200.0, "BBB": 1000.0}},
        {"date": "2025-01-06", "value": 2000.0, "holdings": {"AAA": 1500.0, "BBB": 500.0}},
    ]


def test_normalize_request_merges_duplicates_and_defaults_to_one_year():
    request = PortfolioRequest(
        positions=[Position(ticker=" aapl", amount=100), Position(ticker="AAPL", amount=50)], start_date=None
    )
    assert normalize_request(request, TODAY) == ({"AAPL": 150.0}, date(2025, 1, 15))


@pytest.mark.parametrize(
    "positions, start_date",
    [
        ([], None),
        ([Position(ticker="AAPL; DROP", amount=100)], None),
        ([Position(ticker="AAPL", amount=-5)], None),
        ([Position(ticker="AAPL", amount=float("nan"))], None),
        ([Position(ticker="AAPL", amount=100)], "2026-01-15"),
        ([Position(ticker="AAPL", amount=100)], "last year"),
        ([Position(ticker=f"T{i}", amount=1) for i in range(11)], None),
    ],
)
def test_normalize_request_rejects_bad_input(positions, start_date):
    with pytest.raises(UserFacingError):
        normalize_request(PortfolioRequest(positions=positions, start_date=start_date), TODAY)


class FakeLLM:
    def __init__(self, **_):
        pass

    async def acall(self, messages, response_model):
        if response_model is PortfolioRequest:
            return PortfolioRequest(
                positions=[Position(ticker="AAA", amount=1200), Position(ticker="BBB", amount=1000)],
                start_date="2025-01-02",
            )
        return Insights(
            summary="Down nine percent.",
            insights=[Insight(title="AAA leads", description="Up 25%.", sentiment="bullish")],
        )


def run_agent(message: str) -> list[dict]:
    body = {
        "threadId": "t1", "runId": "r1", "state": {}, "tools": [], "context": [], "forwardedProps": {},
        "messages": [{"id": "m1", "role": "user", "content": message}],
    }
    response = TestClient(app).post("/crewai-agent", json=body)
    assert response.status_code == 200
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_endpoint_streams_the_whole_workflow(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(stock_analysis, "LLM", FakeLLM)
    monkeypatch.setattr(stock_analysis, "fetch_prices", lambda tickers, start: PRICES)

    events = run_agent("Analyze AAA and BBB")

    assert [event["type"] for event in events] == [
        "RUN_STARTED",
        "STATE_SNAPSHOT",
        "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT",
        "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT",
        "STATE_SNAPSHOT",
        "STATE_SNAPSHOT",
        "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END",
        "RUN_FINISHED",
    ]
    final_state = events[11]["snapshot"]
    assert final_state["request"] == {"positions": {"AAA": 1200.0, "BBB": 1000.0}, "start_date": "2025-01-02"}
    assert final_state["analysis"]["value"] == 2000.0
    assert final_state["insights"][0]["sentiment"] == "bullish"
    assert events[13]["delta"] == "Down nine percent."


def test_endpoint_explains_a_missing_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    events = run_agent("Analyze AAA")

    assert [event["type"] for event in events] == [
        "RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END", "RUN_FINISHED",
    ]
    assert "OPENAI_API_KEY" in events[2]["delta"]
