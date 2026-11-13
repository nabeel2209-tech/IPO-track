"""Answer a plain-English question with Claude, using only the tools in ``tools.py``."""

import json
from datetime import date

from sqlalchemy.orm import Session

from app.ai.tools import TOOL_SPECS, run_tool
from app.services.summary import latest_price_date

MAX_TOOL_ROUNDS = 5

SYSTEM_PROMPT = """You answer questions about how Indian IPOs (NSE and BSE, mainboard and SME) performed for investors.

Rules:
- Use the tools for every number. Never estimate or use outside knowledge for prices, returns or lot sizes.
- If a tool returns an error or no data, say so plainly.
- Name the IPOs and dates your answer covers. Use Indian rupee formatting (₹1,23,456).
- P&L figures assume the investor was allotted the minimum application in that category at the issue price; mention this when you give category P&L.
- Keep answers short: a few sentences or a small list.
- You describe past performance only. Do not recommend buying, selling or applying for any IPO.
- Prices are end-of-day; the latest available date is {as_of}. Today's date is {today}."""


def ask(question: str, session: Session, client, model: str) -> dict:
    """Run the tool-use loop. ``client`` is an ``anthropic.Anthropic`` (or a test double)."""
    as_of = latest_price_date(session)
    system = SYSTEM_PROMPT.format(as_of=as_of.isoformat() if as_of else "unknown", today=date.today().isoformat())
    messages: list[dict] = [{"role": "user", "content": question}]
    calls: list[dict] = []

    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.messages.create(model=model, max_tokens=1024, system=system, tools=TOOL_SPECS, messages=messages)
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
            return {"answer": text or "I couldn't find an answer to that.", "tool_calls": calls}

        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if getattr(block, "type", "") != "tool_use":
                continue
            calls.append({"name": block.name, "input": dict(block.input or {})})
            output = run_tool(session, block.name, dict(block.input or {}))
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(output, default=str)})
        messages.append({"role": "user", "content": results})

    return {"answer": "That question needed too many lookups. Try asking something more specific.", "tool_calls": calls}
