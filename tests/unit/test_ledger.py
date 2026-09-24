import pytest
from typer.testing import CliRunner

from rebase_agent import llm
from rebase_agent.cli import app
from rebase_agent.ledger import Ledger, cost_usd, read_rows, rollup
from rebase_agent.models import Usage


def test_cost_uses_every_token_kind():
    usage = Usage(
        input_tokens=1000, output_tokens=100, cache_read_tokens=500, cache_write_tokens=200
    )
    cost, rates = cost_usd("claude-sonnet-5", usage)
    assert rates == {"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_write": 2.5}
    assert cost == pytest.approx((1000 * 2 + 100 * 10 + 500 * 0.2 + 200 * 2.5) / 1e6)


def test_unknown_model_is_an_error_not_zero():
    with pytest.raises(KeyError):
        cost_usd("claude-made-up", Usage(input_tokens=1, output_tokens=1))
    with pytest.raises(llm.LLMError, match="no entry in config.PRICES"):
        llm.call("Smoke", {"text": "x"}, model="claude-made-up", stage="smoke")


def test_ledger_rows_and_rollup(tmp_path):
    ledger = Ledger(tmp_path / "run1", scenario="trivial")
    u = Usage(input_tokens=1_000_000, output_tokens=0)
    ledger.record(stage="analyst_merged", model="claude-haiku-4-5-20251001", usage=u, latency_s=1)
    ledger.record(
        stage="analyst_pr", model="claude-haiku-4-5-20251001", usage=u, latency_s=1, pr="a"
    )
    ledger.record(stage="orchestrator", model="claude-sonnet-5", usage=u, latency_s=1, pr="a")
    ledger.record(
        stage="analyst_pr", model="claude-haiku-4-5-20251001", usage=u, latency_s=1, pr="b"
    )
    rows = read_rows(tmp_path / "run1")
    assert [r.run_id for r in rows] == ["run1"] * 4
    assert all(r.cost_source == "estimated" for r in rows)
    s = rollup(rows)
    assert s["total_usd"] == pytest.approx(5.0)
    assert s["by_stage"] == {"analyst_merged": 1.0, "analyst_pr": 2.0, "orchestrator": 2.0}
    assert s["by_pr"] == {"(shared: merged summary)": 1.0, "a": 3.0, "b": 1.0}
    assert s["merged_summary_per_pr_usd"] == pytest.approx(0.5)

    out = CliRunner().invoke(app, ["costs", str(tmp_path / "run1")])
    assert out.exit_code == 0, out.output
    assert "total: $5.0000" in out.output


def test_costs_on_empty_run_fails(tmp_path):
    assert CliRunner().invoke(app, ["costs", str(tmp_path)]).exit_code == 1


def test_runtime_client_sends_model_key_and_max_tokens(monkeypatch):
    monkeypatch.setenv("REBASE_ANTHROPIC_API_KEY", "k-test")
    req = llm._client("claude-opus-5-5").request.Smoke("hi")
    body = req.body.json()
    assert body["model"] == "claude-opus-5-5"
    assert body["max_tokens"] == 16000
    assert req.headers["x-api-key"] == "k-test"
