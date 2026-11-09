"""FastAPI app exposing the portfolio analysis agent over the AG-UI protocol."""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
# CrewAI otherwise prompts on the terminal about execution traces on the first flow run.
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")

import uvicorn  # noqa: E402
from ag_ui.core import RunAgentInput  # noqa: E402
from ag_ui.encoder import EventEncoder  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402

from stock_analysis import run_analysis  # noqa: E402

app = FastAPI(title="Stock Portfolio Agent")


@app.post("/crewai-agent")
async def crewai_agent(input_data: RunAgentInput) -> StreamingResponse:
    encoder = EventEncoder()

    async def stream():
        queue: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(run_analysis(input_data, queue.put))
        task.add_done_callback(lambda _: queue.put_nowait(None))
        try:
            while (event := await queue.get()) is not None:
                yield encoder.encode(event)
        finally:
            # Stops the workflow when the client disconnects mid-run.
            task.cancel()

    return StreamingResponse(stream(), media_type=encoder.get_content_type())


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
