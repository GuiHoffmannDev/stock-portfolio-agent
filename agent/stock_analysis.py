"""Portfolio analysis workflow.

A CrewAI Flow parses the chat request, fetches prices, computes allocations and
writes insights. Progress is reported through an ``emit`` callback as AG-UI
events, so the caller can stream them to the UI while the flow runs.
"""

import asyncio
import json
import logging
import math
import os
import re
import uuid
from datetime import date, timedelta
from typing import Any, Awaitable, Callable, Literal

import pandas as pd
import yfinance as yf
from ag_ui.core import (
    BaseEvent,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from crewai import LLM
from crewai.constants import DEFAULT_LLM_MODEL
from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel, Field, PrivateAttr

logger = logging.getLogger(__name__)

Emit = Callable[[BaseEvent], Awaitable[None]]

MAX_POSITIONS = 10
MAX_HISTORY_MESSAGES = 10
MAX_MESSAGE_CHARS = 4000
MAX_CHART_POINTS = 120
TICKER_RE = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}")

USAGE_HINT = (
    "Tell me which stocks you hold and how much you invested in each, "
    'for example: "Analyze AAPL and MSFT with $10k each since January 2024".'
)


class UserFacingError(Exception):
    """A problem the user can fix; its message is shown in the chat."""


class Position(BaseModel):
    ticker: str = Field(description="Stock ticker symbol, e.g. AAPL")
    amount: float = Field(description="Amount invested in USD")


class PortfolioRequest(BaseModel):
    positions: list[Position] = Field(
        description="Positions to analyze. Empty when the user did not ask for a portfolio analysis."
    )
    start_date: str | None = Field(
        description="Investment date as YYYY-MM-DD, or null when the user gave none."
    )


class Insight(BaseModel):
    title: str
    description: str
    sentiment: Literal["bullish", "bearish"]


class Insights(BaseModel):
    summary: str = Field(description="Two or three plain sentences summarizing the portfolio.")
    insights: list[Insight] = Field(description="Three to six insights grounded in the numbers.")


def normalize_request(request: PortfolioRequest, today: date) -> tuple[dict[str, float], date]:
    """Validate the LLM-parsed request and return ``(amount per ticker, start date)``."""
    amounts: dict[str, float] = {}
    for position in request.positions:
        ticker = position.ticker.strip().upper()
        if not TICKER_RE.fullmatch(ticker):
            raise UserFacingError(f"'{position.ticker}' is not a valid ticker symbol.")
        if not math.isfinite(position.amount) or position.amount <= 0:
            raise UserFacingError(f"The amount for {ticker} must be greater than zero.")
        amounts[ticker] = amounts.get(ticker, 0.0) + position.amount
    if not amounts:
        raise UserFacingError(USAGE_HINT)
    if len(amounts) > MAX_POSITIONS:
        raise UserFacingError(f"I can analyze up to {MAX_POSITIONS} stocks at a time.")

    if request.start_date is None:
        return amounts, today - timedelta(days=365)
    try:
        start_date = date.fromisoformat(request.start_date)
    except ValueError:
        raise UserFacingError(f"'{request.start_date}' is not a valid date.") from None
    if start_date >= today:
        raise UserFacingError("The investment date must be in the past.")
    return amounts, start_date


def fetch_prices(tickers: list[str], start_date: date) -> pd.DataFrame:
    """Daily adjusted closes, one column per ticker."""
    data = yf.download(tickers, start=start_date.isoformat(), auto_adjust=True, progress=False)
    prices = data["Close"] if not data.empty else pd.DataFrame()
    missing = [t for t in tickers if t not in prices or prices[t].isna().all()]
    if missing:
        raise UserFacingError(f"No price data found for: {', '.join(missing)}.")
    return prices[tickers]


def analyze(prices: pd.DataFrame, amounts: dict[str, float]) -> dict[str, Any]:
    """Buy each position at the first common trading day and track its value."""
    # Start on the first day every ticker has a price, so all positions are bought together.
    prices = prices.ffill().dropna()
    if len(prices) < 2:
        raise UserFacingError("Not enough price history since that date to analyze.")

    invested = pd.Series(amounts)
    values = prices * (invested / prices.iloc[0])
    total = values.sum(axis=1)
    latest = values.iloc[-1]

    step = max(1, len(total) // MAX_CHART_POINTS)
    sampled = total.iloc[::step]
    if sampled.index[-1] != total.index[-1]:
        sampled = pd.concat([sampled, total.iloc[[-1]]])

    def pct(value: float, base: float) -> float:
        return round(float(value / base - 1) * 100, 2)

    return {
        "start_date": prices.index[0].date().isoformat(),
        "end_date": prices.index[-1].date().isoformat(),
        "invested": round(float(invested.sum()), 2),
        "value": round(float(total.iloc[-1]), 2),
        "return_pct": pct(total.iloc[-1], invested.sum()),
        "holdings": [
            {
                "ticker": ticker,
                "invested": round(amount, 2),
                "value": round(float(latest[ticker]), 2),
                "return_pct": pct(latest[ticker], amount),
                "allocation_pct": round(float(latest[ticker] / total.iloc[-1]) * 100, 2),
            }
            for ticker, amount in amounts.items()
        ],
        "history": [
            {
                "date": day.date().isoformat(),
                "value": round(float(value), 2),
                "holdings": {ticker: round(float(values.at[day, ticker]), 2) for ticker in amounts},
            }
            for day, value in sampled.items()
        ],
    }


class AnalysisState(BaseModel):
    messages: list[dict[str, str]] = []
    amounts: dict[str, float] = {}
    start_date: date | None = None
    analysis: dict[str, Any] = {}


class PortfolioFlow(Flow[AnalysisState]):
    _emit: Emit = PrivateAttr()
    _llm: LLM = PrivateAttr()
    _prices: pd.DataFrame = PrivateAttr()

    def _shared_state(self, **extra: Any) -> StateSnapshotEvent:
        request = {"positions": self.state.amounts, "start_date": self.state.start_date.isoformat()}
        return StateSnapshotEvent(snapshot={"request": request, **extra})

    async def _tool(self, name: str, args: dict[str, Any], work: Callable[[], Any], describe: Callable[[Any], str]) -> Any:
        """Run blocking ``work`` off the event loop, reported to the UI as a tool call."""
        call_id = str(uuid.uuid4())
        await self._emit(ToolCallStartEvent(tool_call_id=call_id, tool_call_name=name))
        await self._emit(ToolCallArgsEvent(tool_call_id=call_id, delta=json.dumps(args)))
        await self._emit(ToolCallEndEvent(tool_call_id=call_id))
        outcome = "Cancelled."
        try:
            result = await asyncio.to_thread(work)
            outcome = describe(result)
            return result
        except Exception as error:
            outcome = str(error) if isinstance(error, UserFacingError) else "Failed."
            raise
        finally:
            # Always close the call, so the UI never shows it as still running.
            await self._emit(
                ToolCallResultEvent(message_id=str(uuid.uuid4()), tool_call_id=call_id, content=outcome)
            )

    async def _ask(self, system: str, messages: list[dict[str, str]], model: type[BaseModel]) -> Any:
        reply = await self._llm.acall([{"role": "system", "content": system}, *messages], response_model=model)
        return reply if isinstance(reply, model) else model.model_validate_json(reply)

    @start()
    async def parse_request(self) -> None:
        today = date.today()
        request = await self._ask(
            f"Extract the stock portfolio the user wants analyzed. Today is {today.isoformat()}. "
            "Use the latest request, taking earlier messages only as context. Convert company "
            "names to ticker symbols and shorthand such as '10k' to numbers.",
            self.state.messages,
            PortfolioRequest,
        )
        self.state.amounts, self.state.start_date = normalize_request(request, today)
        await self._emit(self._shared_state())

    @listen(parse_request)
    async def fetch_stock_data(self) -> None:
        tickers = list(self.state.amounts)
        self._prices = await self._tool(
            "fetch_stock_data",
            {"tickers": tickers, "start_date": self.state.start_date.isoformat()},
            lambda: fetch_prices(tickers, self.state.start_date),
            lambda prices: f"Fetched {len(prices)} trading days for {', '.join(tickers)}.",
        )

    @listen(fetch_stock_data)
    async def calculate_allocations(self) -> None:
        self.state.analysis = await self._tool(
            "calculate_allocations",
            {"positions": self.state.amounts},
            lambda: analyze(self._prices, self.state.amounts),
            lambda result: f"Portfolio value ${result['value']:,.2f} ({result['return_pct']:+.2f}%).",
        )
        await self._emit(self._shared_state(analysis=self.state.analysis))

    @listen(calculate_allocations)
    async def generate_insights(self) -> None:
        figures = {key: value for key, value in self.state.analysis.items() if key != "history"}
        result: Insights = await self._ask(
            "You are a portfolio analyst. Using only the figures provided, write a short summary "
            "and balanced bullish and bearish insights about this portfolio. This is educational "
            "commentary: do not recommend buying or selling.",
            [{"role": "user", "content": json.dumps(figures)}],
            Insights,
        )
        await self._emit(
            self._shared_state(
                analysis=self.state.analysis,
                insights=[insight.model_dump() for insight in result.insights],
            )
        )
        await say(self._emit, result.summary)


async def say(emit: Emit, text: str) -> None:
    message_id = str(uuid.uuid4())
    await emit(TextMessageStartEvent(message_id=message_id, role="assistant"))
    await emit(TextMessageContentEvent(message_id=message_id, delta=text))
    await emit(TextMessageEndEvent(message_id=message_id))


def chat_history(input_data: RunAgentInput) -> list[dict[str, str]]:
    history = [
        {"role": message.role, "content": message.content[:MAX_MESSAGE_CHARS]}
        for message in input_data.messages
        if message.role in ("user", "assistant") and isinstance(message.content, str) and message.content
    ]
    return history[-MAX_HISTORY_MESSAGES:]


async def run_analysis(input_data: RunAgentInput, emit: Emit) -> None:
    """Run the workflow for one AG-UI request, emitting every event of the run."""
    await emit(RunStartedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id))
    try:
        messages = chat_history(input_data)
        if not messages or messages[-1]["role"] != "user":
            raise UserFacingError(USAGE_HINT)
        if not os.getenv("OPENAI_API_KEY"):
            raise UserFacingError("OPENAI_API_KEY is not set. Add it to agent/.env and restart the backend.")

        flow = PortfolioFlow()
        flow._emit = emit
        flow._llm = LLM(model=os.getenv("OPENAI_MODEL_NAME", DEFAULT_LLM_MODEL))
        await flow.kickoff_async(inputs={"messages": messages})
    except UserFacingError as error:
        await say(emit, str(error))
    except Exception:
        logger.exception("Portfolio analysis failed")
        await emit(RunErrorEvent(message="The analysis failed. Check the backend logs for details."))
        return
    await emit(RunFinishedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id))
