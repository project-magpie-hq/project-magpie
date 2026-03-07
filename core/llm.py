"""
LLM 팩토리 모듈.

프로젝트 전체에서 사용하는 LLM 인스턴스를 통합 관리한다.
모델 종류를 ``LLMModel`` enum 으로 관리하고, ``create_llm()`` 팩토리
함수를 통해 provider(Gemini / Groq)에 관계없이 동일한 인터페이스로 생성한다.
"""

from __future__ import annotations

from enum import StrEnum

from langchain_core.language_models import BaseChatModel

# ---------------------------------------------------------------------------
# 지원 모델 목록
# ---------------------------------------------------------------------------


class LLMModel(StrEnum):
    """프로젝트에서 사용 가능한 LLM 모델 목록.

    Groq 무료 티어 TPM(분당 토큰) 한도:
      - LLAMA_33_70B : 12,000 TPM  ← 대용량 컨텍스트에서 초과 위험
      - LLAMA_31_8B  : 131,072 TPM ← OHLCV 누적 히스토리 처리에 권장
      - GEMMA2_9B    : 15,000 TPM
    """

    # --- Groq (무료 티어) ---
    LLAMA_33_70B = "llama-3.3-70b-versatile"
    LLAMA_31_8B = "llama-3.1-8b-instant"
    GEMMA2_9B = "gemma2-9b-it"

    # --- Google Gemini ---
    GEMINI_25_FLASH = "gemini-2.5-flash"
    GEMINI_20_FLASH = "gemini-2.0-flash"


DEFAULT_MODEL: LLMModel = LLMModel.LLAMA_31_8B
"""프로젝트 기본 모델 — Groq 무료 티어 (높은 TPM 한도)."""


# ---------------------------------------------------------------------------
# 내부 provider 판별
# ---------------------------------------------------------------------------

_GEMINI_PREFIXES = ("gemini",)


def _is_gemini(model: LLMModel) -> bool:
    return model.value.startswith(_GEMINI_PREFIXES)


# ---------------------------------------------------------------------------
# 팩토리
# ---------------------------------------------------------------------------


def create_llm(
    model: LLMModel = DEFAULT_MODEL,
    *,
    temperature: float = 0.0,
) -> BaseChatModel:
    """모델 enum에 따라 적절한 LangChain ChatModel 인스턴스를 생성한다.

    Parameters
    ----------
    model:
        사용할 모델. 기본값은 ``DEFAULT_MODEL`` (Groq Llama 3.1 8B).
    temperature:
        LLM sampling temperature.

    Returns
    -------
    BaseChatModel
        LangChain ChatModel 인스턴스 (Gemini 또는 Groq).
    """
    if _is_gemini(model):
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=model.value, temperature=temperature)

    # Groq 계열
    from langchain_groq import ChatGroq

    return ChatGroq(model=model.value, temperature=temperature)
