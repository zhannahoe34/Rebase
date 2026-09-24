"""BAML calls over our own HTTP transport (PLAN.md Q13, option 1).

BAML builds the Anthropic request (`b.request.Fn`) and parses the reply (`b.parse.Fn`);
httpx sends it. BAML's built-in Rust client doesn't trust the cloud sandbox's egress CA,
while httpx honors SSL_CERT_FILE. Token usage comes from the response's `usage` block.
"""

import time
from typing import Any

import httpx
from baml_py import ClientRegistry

from rebase_agent import config
from rebase_agent.baml_client import b
from rebase_agent.ledger import Ledger
from rebase_agent.models import Usage

_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
_ATTEMPTS = 3
_TIMEOUT_S = 300.0


class LLMError(RuntimeError):
    pass


def _client(model: str):
    registry = ClientRegistry()
    registry.add_llm_client(
        name="Runtime",
        provider="anthropic",
        options={
            "model": model,
            "api_key": config.api_key(),
            "max_tokens": config.MAX_OUTPUT_TOKENS,
        },
    )
    registry.set_primary("Runtime")
    return b.with_options(client_registry=registry)


def _post(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=_TIMEOUT_S)
        except httpx.TransportError as e:
            if attempt == _ATTEMPTS:
                raise LLMError(f"connection failed after {attempt} attempts: {e}") from e
        else:
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code not in _RETRY_STATUS or attempt == _ATTEMPTS:
                raise LLMError(f"HTTP {resp.status_code}: {resp.text[:500]}")
        time.sleep(2**attempt)
    raise AssertionError("unreachable")


def _usage(data: dict[str, Any]) -> Usage:
    u = data.get("usage") or {}
    return Usage(
        input_tokens=u.get("input_tokens", 0),
        output_tokens=u.get("output_tokens", 0),
        cache_read_tokens=u.get("cache_read_input_tokens") or 0,
        cache_write_tokens=u.get("cache_creation_input_tokens") or 0,
    )


def call(
    fn: str,
    args: dict[str, Any],
    *,
    model: str,
    stage: str,
    ledger: Ledger | None = None,
    pr: str | None = None,
) -> tuple[Any, Usage]:
    """Run BAML function `fn` on `model`. Records a ledger row before parsing, so a call
    whose reply fails to parse is still paid for in the ledger."""
    if model not in config.PRICES:
        raise LLMError(f"model {model!r} has no entry in config.PRICES; add its published price")
    client = _client(model)
    req = getattr(client.request, fn)(**args)
    start = time.monotonic()
    data = _post(req.url, dict(req.headers), req.body.json())
    latency = time.monotonic() - start
    usage = _usage(data)
    if ledger is not None:
        ledger.record(stage=stage, model=model, usage=usage, latency_s=latency, pr=pr)

    stop = data.get("stop_reason")
    if stop not in ("end_turn", "stop_sequence"):
        raise LLMError(f"{fn} on {model} stopped with stop_reason={stop!r}")
    text = "".join(blk.get("text", "") for blk in data.get("content", []) if blk["type"] == "text")
    return getattr(client.parse, fn)(text), usage
