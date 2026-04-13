import logging
import os
from json import dumps
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END

from agents.owl_director.schema import StrategySchema
from agents.utils import normalize_content
from state.magpie import MagpieState
from tools.strategy import fetch_active_strategy_for_user, get_my_active_strategy, register_strategy_to_nest

logger = logging.getLogger(__name__)


def load_prompt() -> str:
    """에이전트 시스템 프롬프트 로드"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(current_dir, "prompt.md")
    try:
        with open(prompt_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.error("Owl 프롬프트 파일을 찾을 수 없습니다: %s", prompt_path)
        raise
    except OSError as e:
        logger.exception("Owl 프롬프트 파일 읽기 실패: %s", prompt_path)
        raise RuntimeError(f"프롬프트 파일 읽기 실패: {prompt_path}") from e


def get_owl_llm() -> Runnable[LanguageModelInput, AIMessage]:
    """Owl 에이전트 모델 초기화"""
    try:
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
        tools = [register_strategy_to_nest, get_my_active_strategy]
        return llm.bind_tools(tools)
    except Exception as e:
        logger.exception("Owl LLM 초기화 실패")
        raise RuntimeError("Owl LLM 초기화 실패") from e


def _format_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text)
        if chunks:
            return "\n".join(chunks)
    return str(content)


def build_owl_decision(response: Any, state: MagpieState) -> dict[str, Any]:
    tool_calls = getattr(response, "tool_calls", None) or []
    beaver_plan = state.get("beaver_plan")
    next_step = "meerkat_scanner" if state.get("trigger_event") or is_system_event(state) else "end"

    return {
        "status": "pending_tool_execution" if tool_calls else "reviewed",
        "summary": _format_content(response.content),
        "trigger_event_present": state.get("trigger_event") is not None,
        "beaver_plan": beaver_plan,
        "tool_calls": tool_calls,
        "next_step": next_step,
    }


def is_system_event(state: MagpieState) -> bool:
    for msg in reversed(state.get("messages", [])):
        if msg.type in ["user", "human"] and "SYSTEM_EVENT" in msg.content:
            return True
    return False


async def owl_node(state: MagpieState) -> dict[str, Any]:
    """사용자 요청을 분석하고 도구 호출 또는 답변을 생성하는 노드"""
    print("\n\n🦉 [Owl]: 사용자의 요청을 분석하고 있습니다...")

    system_prompt = load_prompt()
    current_strategy = state.get("owl_strategy")
    if not current_strategy:
        current_strategy = await fetch_active_strategy_for_user(state.get("user_id", "default_user"))

    trigger_event = state.get("trigger_event")
    portfolio_snapshot = state.get("portfolio_snapshot")
    beaver_plan = state.get("beaver_plan")

    injected_prompt = (
        system_prompt
        + f"\n\n[현재 시스템에 적용된 매매 전략]\n{dumps(current_strategy, ensure_ascii=False, indent=2, default=str)}\n"
        + f"\n[현재 트리거 이벤트]\n{dumps(trigger_event, ensure_ascii=False, indent=2, default=str)}\n"
        + f"\n[현재 포트폴리오 스냅샷]\n{dumps(portfolio_snapshot, ensure_ascii=False, indent=2, default=str)}\n"
        + f"\n[Beaver 제안서]\n{dumps(beaver_plan, ensure_ascii=False, indent=2, default=str)}\n"
        + (
            "(※ 자동화 모드에서는 Beaver 제안서를 1차 실행 초안으로 취급하세요. "
            "명확한 충돌 사유가 없다면 유지하고, 조정이 필요하면 근거와 함께 축소/보류하세요. "
            "최종 답변에는 Meerkat이 그대로 참고할 수 있도록 Beaver 반영 결과와 금액 중심 피드백을 반드시 포함하세요.)"
        )
    )

    messages_to_llm = [SystemMessage(content=injected_prompt)] + state["messages"]

    try:
        agent = get_owl_llm()
        response: AIMessage = normalize_content(await agent.ainvoke(messages_to_llm))
    except Exception as e:
        logger.exception("Owl LLM 호출 실패")
        raise RuntimeError("Owl 에이전트 실행 중 오류가 발생했습니다.") from e

    updates: dict[str, Any] = {"messages": [response]}

    if response.tool_calls:
        for tool_call in response.tool_calls:
            print(f"   🛠️ [Owl]: 도구 호출 결정 -> {tool_call['name']}")
            if tool_call["name"] == "register_strategy_to_nest":
                strategy_update = StrategySchema(
                    target_coins=tool_call["args"].get("target_coins", []),
                    strategy_details=tool_call["args"].get("strategy_details", {}),
                )
                updates["owl_strategy"] = strategy_update.model_dump()
                updates["is_strategy_updated"] = True

    updates["owl_decision"] = build_owl_decision(response, {**state, **updates})
    return updates


def route_after_owl(state: MagpieState) -> str:
    """메시지 내역을 기반으로 다음 노드로 분기하는 라우터"""
    messages = state.get("messages", [])
    if not messages:
        return END

    last_msg = messages[-1]

    if getattr(last_msg, "tool_calls", None):
        return "owl_tools"

    if state.get("trigger_event") or is_system_event(state):
        print("   🦉 [Owl]: 분석 및 지시 완료. Meerkat으로 넘어갑니다 ➡️")
        return "meerkat_scanner"

    if state.get("is_strategy_updated"):
        print("   🦉 [Owl]: 전략 갱신 완료. Meerkat으로 넘어갑니다 ➡️")
        return "meerkat_scanner"

    return END
