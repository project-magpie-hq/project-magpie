import os

from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from tools.market_tools import calculate_technical_indicators


def load_prompt() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(current_dir, "meerkat_scanner_prompt.md")
    with open(prompt_path, encoding="utf-8") as f:
        return f.read()


def _extract_chart_request(state: dict) -> tuple[str, str, str, str]:
    """
    state의 messages에서 가장 최근 request_chart_analysis 툴 호출을 찾아
    (tool_call_id, ticker, interval, period)를 반환합니다.
    """
    for msg in reversed(state["messages"]):
        if not hasattr(msg, "tool_calls"):
            continue
        for tc in msg.tool_calls:
            if tc["name"] == "request_chart_analysis":
                args = tc.get("args", {})
                return (
                    tc["id"],
                    args.get("ticker", "AAPL"),
                    args.get("interval", "1d"),
                    args.get("period", "1y"),
                )
    return ("", "AAPL", "1d", "1y")


def meerkat_scanner_node(state: dict) -> dict:
    """
    LangGraph 노드 함수.
    1. Owl Director의 request_chart_analysis 툴 호출에서 요청 정보를 추출합니다.
    2. calculate_technical_indicators 툴로 지표 수치를 계산합니다.
    3. LLM(Meerkat Scanner)이 해당 수치를 트레이딩 관점으로 심층 해석합니다.
    4. 분석 결과를 ToolMessage로 반환하여 Owl Director가 사용자에게 전달할 수 있게 합니다.
    """
    tool_call_id, ticker, interval, period = _extract_chart_request(state)

    if not tool_call_id:
        error_msg = ToolMessage(
            content="❌ Meerkat Scanner: 분석 요청 정보를 찾을 수 없습니다.",
            tool_call_id="unknown",
            name="request_chart_analysis",
        )
        return {"messages": [error_msg]}

    print(f"\n{'🦔' * 20}")
    print(f"🦔 [Meerkat Scanner]: {ticker} 분석 시작 ({interval} / {period})")
    print("─" * 40)

    # 1. 기술적 지표 수치 계산
    raw_indicators = calculate_technical_indicators.invoke({"ticker": ticker, "interval": interval, "period": period})

    # 2. LLM이 지표를 해석 (Meerkat Scanner 시스템 프롬프트 적용)
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.3)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", load_prompt()),
            (
                "human",
                "아래 기술적 지표 데이터를 바탕으로 트레이딩 분석 보고서를 작성해줘.\n\n{indicator_data}",
            ),
        ]
    )

    chain = prompt | llm
    response = chain.invoke({"indicator_data": raw_indicators})
    analysis = response.content

    print(f"� [Meerkat Scanner]: {ticker} 분석 완료")
    print("🦔" * 20 + "\n")

    # 3. ToolMessage로 래핑 → Owl Director가 이어받아 사용자에게 전달
    tool_message = ToolMessage(
        content=analysis,
        tool_call_id=tool_call_id,
        name="request_chart_analysis",
    )

    return {"messages": [tool_message]}
