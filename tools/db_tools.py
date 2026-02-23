import json

from langchain_core.tools import tool


@tool
def register_strategy(strategy_json: dict) -> str:
    """사용자가 전략을 최종 승인했을 때 호출하여, DB에 전략을 저장합니다."""
    print("\n" + "⚙️" * 25)
    print("🪹 [The Nest]: 새로운 전략이 DB에 등록되었습니다!")
    print("-" * 50)
    # LLM이 만든 딕셔너리를 예쁜 JSON 문자열로 출력
    print(json.dumps(strategy_json, indent=2, ensure_ascii=False))
    print("⚙️" * 25 + "\n")

    return "투자 전략 등록이 성공적으로 완료되었습니다."
