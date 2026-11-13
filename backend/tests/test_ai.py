from types import SimpleNamespace

from app.ai.agent import ask
from app.ai.limits import DailyLimiter
from app.ai.tools import run_tool
from app.api.ask import get_ai_client
from app.main import app


def block(**kw):
    return SimpleNamespace(**kw)


class FakeClaude:
    """Asks for one tool, then answers using what the tool returned."""

    def __init__(self, tool_name, tool_input):
        self.tool_name, self.tool_input = tool_name, tool_input
        self.seen_results = None
        self.messages = self

    def create(self, **kw):
        msgs = kw["messages"]
        if len(msgs) == 1:
            return block(stop_reason="tool_use", content=[block(type="tool_use", id="t1", name=self.tool_name, input=self.tool_input)])
        self.seen_results = msgs[-1]["content"][0]["content"]
        return block(stop_reason="end_turn", content=[block(type="text", text="Jio Platforms is the top performer.")])


def test_agent_runs_tool_and_answers(seeded):
    fake = FakeClaude("search_ipos", {"sort_by": "latest_return", "limit": 1})
    out = ask("Which IPO did best?", seeded, fake, "test-model")
    assert out["answer"].startswith("Jio")
    assert out["tool_calls"] == [{"name": "search_ipos", "input": {"sort_by": "latest_return", "limit": 1}}]
    assert "Jio Platforms" in fake.seen_results


def test_tools_return_errors_not_exceptions(seeded):
    assert "error" in run_tool(seeded, "ipo_pnl", {"ipo": "No Such Co"})
    assert "error" in run_tool(seeded, "search_ipos", {"listed_from": "yesterday"})
    assert "error" in run_tool(seeded, "drop_tables", {})


def test_ipo_pnl_tool(seeded):
    r = run_tool(seeded, "ipo_pnl", {"ipo": "JPL", "date": "2026-10-29"})
    assert r["on_date"]["categories"]["bnii"]["shares"] == 900


def test_category_totals_tool(seeded):
    r = run_tool(seeded, "category_totals", {"category": "individual", "segment": "mainboard"})
    # Only Jio and Nityas have a listing-day price in the sample; the others are skipped, not guessed.
    assert r["ipos_counted"] == 2
    assert r["money_needed"] == 12 * 1119 + 200 * 75


def test_market_stats_tool(seeded):
    r = run_tool(seeded, "market_stats", {"segment": "any"})
    assert r["ipos"] == 5 and r["with_prices"] == 4


def test_limiter():
    lim = DailyLimiter(per_key=2, global_limit=3)
    assert lim.allow("a")[0] and lim.allow("a")[0]
    assert not lim.allow("a")[0]
    assert lim.allow("b")[0]
    assert not lim.allow("c")[0]  # global cap reached


def test_ask_endpoint_with_fake_client(client):
    app.dependency_overrides[get_ai_client] = lambda: FakeClaude("market_stats", {})
    try:
        r = client.post("/api/ask", json={"question": "How did IPOs do?"})
        assert r.status_code == 200 and r.json()["tool_calls"][0]["name"] == "market_stats"
        assert client.post("/api/ask", json={"question": "x" * 400}).status_code == 422
    finally:
        app.dependency_overrides.pop(get_ai_client, None)
