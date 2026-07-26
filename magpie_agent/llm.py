from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI


@dataclass(frozen=True)
class LLMConfig:
    model: str
    temperature: float


LLM_CONFIGS: dict[str, LLMConfig] = {
    "owl": LLMConfig(model="gemini-2.5-flash", temperature=0.0),
    "fox": LLMConfig(model="gemini-2.5-flash", temperature=0.0),
    "hawk": LLMConfig(model="gemini-2.5-flash", temperature=0.0),
    "meerkat": LLMConfig(model="gemini-2.5-flash", temperature=0.0),
    "calculate_debate": LLMConfig(model="gemini-2.5-flash", temperature=0.3),
    "calculate_dolphin": LLMConfig(model="gemini-2.5-flash", temperature=0.0),
}


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
