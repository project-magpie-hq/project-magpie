from collections.abc import Sequence
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI

from db.mongo import get_llm_usage_runs_collection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMConfig:
    model: str
    temperature: float


@dataclass(frozen=True)
class LLMPrice:
    input_per_1m_usd: float
    output_per_1m_usd: float


LLM_CONFIGS: dict[str, LLMConfig] = {
    "owl": LLMConfig(model="gemini-2.5-flash", temperature=0.0),
    "fox": LLMConfig(model="gemini-2.5-flash", temperature=0.0),
    "hawk": LLMConfig(model="gemini-2.5-flash", temperature=0.0),
    "meerkat": LLMConfig(model="gemini-2.5-flash", temperature=0.0),
    "calculate_debate": LLMConfig(model="gemini-2.5-flash", temperature=0.3),
    "calculate_dolphin": LLMConfig(model="gemini-2.5-flash", temperature=0.0),
}

LLM_PRICES: dict[str, LLMPrice] = {
    # Gemini API paid tier, text input/output, per 1M tokens.
    # Output includes thinking tokens.
    "gemini-2.5-flash": LLMPrice(input_per_1m_usd=0.30, output_per_1m_usd=2.50),
}

_active_usage: ContextVar[dict[str, Any] | None] = ContextVar("magpie_llm_usage", default=None)


def _usage_value(source: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = source.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _extract_usage_metadata(response: AIMessage) -> dict[str, int]:
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        response_metadata = getattr(response, "response_metadata", {}) or {}
        usage = response_metadata.get("usage_metadata") or response_metadata.get("token_usage")

    if not isinstance(usage, dict):
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    input_tokens = _usage_value(usage, "input_tokens", "prompt_tokens", "prompt_token_count")
    output_tokens = _usage_value(usage, "output_tokens", "completion_tokens", "candidates_token_count")
    thinking_tokens = _usage_value(usage, "thinking_tokens", "thoughts_token_count")
    if output_tokens == 0:
        output_tokens = thinking_tokens
    elif thinking_tokens:
        output_tokens += thinking_tokens

    total_tokens = _usage_value(usage, "total_tokens", "total_token_count")
    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price = LLM_PRICES.get(model)
    if price is None:
        return 0.0
    return (input_tokens / 1_000_000 * price.input_per_1m_usd) + (
        output_tokens / 1_000_000 * price.output_per_1m_usd
    )


def reset_llm_usage() -> Token[dict[str, Any] | None]:
    return _active_usage.set(
        {
            "total_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "by_model": {},
            "by_agent": {},
        }
    )


def restore_llm_usage(token: Token[dict[str, Any] | None]) -> None:
    _active_usage.reset(token)


def is_llm_usage_active() -> bool:
    return _active_usage.get() is not None


@contextmanager
def track_llm_usage():
    token = reset_llm_usage()
    try:
        yield
    finally:
        restore_llm_usage(token)


def record_llm_usage(config_key: str, response: AIMessage) -> None:
    usage = _active_usage.get()
    if usage is None:
        return

    config = LLM_CONFIGS.get(config_key)
    model = config.model if config else config_key
    tokens = _extract_usage_metadata(response)
    input_tokens = tokens["input_tokens"]
    output_tokens = tokens["output_tokens"]
    total_tokens = tokens["total_tokens"]
    estimated_cost_usd = _estimate_cost_usd(model, input_tokens, output_tokens)

    usage["total_calls"] += 1
    usage["input_tokens"] += input_tokens
    usage["output_tokens"] += output_tokens
    usage["total_tokens"] += total_tokens
    usage["estimated_cost_usd"] += estimated_cost_usd

    for group_key, group_value in (("by_model", model), ("by_agent", config_key)):
        grouped = usage[group_key].setdefault(
            group_value,
            {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
            },
        )
        grouped["calls"] += 1
        grouped["input_tokens"] += input_tokens
        grouped["output_tokens"] += output_tokens
        grouped["total_tokens"] += total_tokens
        grouped["estimated_cost_usd"] += estimated_cost_usd


def get_llm_usage_snapshot() -> dict[str, Any]:
    usage = _active_usage.get()
    if usage is None:
        usage = {
            "total_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "by_model": {},
            "by_agent": {},
        }

    return {
        "total_calls": usage["total_calls"],
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "total_tokens": usage["total_tokens"],
        "estimated_cost_usd": round(usage["estimated_cost_usd"], 8),
        "by_model": {
            key: {**value, "estimated_cost_usd": round(value["estimated_cost_usd"], 8)}
            for key, value in usage["by_model"].items()
        },
        "by_agent": {
            key: {**value, "estimated_cost_usd": round(value["estimated_cost_usd"], 8)}
            for key, value in usage["by_agent"].items()
        },
        "pricing_note": "Estimated from configured per-token prices; provider invoices may differ by tier/features.",
    }


def diff_llm_usage_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    by_model = _diff_usage_group(before.get("by_model") or {}, after.get("by_model") or {})
    by_agent = _diff_usage_group(before.get("by_agent") or {}, after.get("by_agent") or {})
    return {
        "total_calls": max(0, int(after.get("total_calls", 0)) - int(before.get("total_calls", 0))),
        "input_tokens": max(0, int(after.get("input_tokens", 0)) - int(before.get("input_tokens", 0))),
        "output_tokens": max(0, int(after.get("output_tokens", 0)) - int(before.get("output_tokens", 0))),
        "total_tokens": max(0, int(after.get("total_tokens", 0)) - int(before.get("total_tokens", 0))),
        "estimated_cost_usd": round(
            max(0.0, float(after.get("estimated_cost_usd", 0.0)) - float(before.get("estimated_cost_usd", 0.0))),
            8,
        ),
        "by_model": by_model,
        "by_agent": by_agent,
        "pricing_note": after.get("pricing_note")
        or "Estimated from configured per-token prices; provider invoices may differ by tier/features.",
    }


def _diff_usage_group(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    diff: dict[str, dict[str, Any]] = {}
    for key in sorted(set(before) | set(after)):
        before_row = before.get(key) or {}
        after_row = after.get(key) or {}
        row = {
            "calls": max(0, int(after_row.get("calls", 0)) - int(before_row.get("calls", 0))),
            "input_tokens": max(
                0,
                int(after_row.get("input_tokens", 0)) - int(before_row.get("input_tokens", 0)),
            ),
            "output_tokens": max(
                0,
                int(after_row.get("output_tokens", 0)) - int(before_row.get("output_tokens", 0)),
            ),
            "total_tokens": max(
                0,
                int(after_row.get("total_tokens", 0)) - int(before_row.get("total_tokens", 0)),
            ),
            "estimated_cost_usd": round(
                max(
                    0.0,
                    float(after_row.get("estimated_cost_usd", 0.0))
                    - float(before_row.get("estimated_cost_usd", 0.0)),
                ),
                8,
            ),
        }
        if row["calls"] or row["total_tokens"] or row["estimated_cost_usd"]:
            diff[key] = row
    return diff


async def save_llm_usage_run(
    *,
    run_type: str,
    graph_name: str,
    user_id: str | None,
    thread_id: str | None,
    usage: dict[str, Any] | None = None,
    status: str = "completed",
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
) -> str | None:
    usage_snapshot = usage or get_llm_usage_snapshot()
    document = {
        "run_type": run_type,
        "graph_name": graph_name,
        "user_id": user_id,
        "thread_id": thread_id,
        "status": status,
        "usage": usage_snapshot,
        "metadata": metadata or {},
        "error": error,
        "created_at": datetime.now(UTC),
    }
    try:
        result = await get_llm_usage_runs_collection().insert_one(document)
    except Exception:
        logger.exception("LLM 사용량 저장 실패: run_type=%s graph_name=%s", run_type, graph_name)
        return None
    return str(result.inserted_id)


async def fetch_recent_llm_usage_runs(
    *,
    user_id: str | None = None,
    run_type: str | list[str] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if user_id:
        query["user_id"] = user_id
    if isinstance(run_type, list):
        query["run_type"] = {"$in": run_type}
    elif run_type:
        query["run_type"] = run_type

    cursor = get_llm_usage_runs_collection().find(query).sort("created_at", -1).limit(limit)
    rows = await cursor.to_list(length=limit)
    for row in rows:
        row["_id"] = str(row["_id"])
    return rows


def get_base_llm(config_key: str) -> ChatGoogleGenerativeAI:
    config = LLM_CONFIGS[config_key]
    return ChatGoogleGenerativeAI(model=config.model, temperature=config.temperature)


def get_bound_llm(
    config_key: str,
    tools: Sequence[Any],
    *,
    tool_choice: str | None = None,
) -> Runnable[LanguageModelInput, AIMessage]:
    llm = get_base_llm(config_key)
    bind_kwargs: dict[str, Any] = {}
    if tool_choice is not None:
        bind_kwargs["tool_choice"] = tool_choice
    return llm.bind_tools(list(tools), **bind_kwargs)
