"""Parallel Coordinator 노드

여러 코인의 Meerkat → Calculate Team → Tools 파이프라인을
asyncio.gather로 병렬 실행하고 결과를 취합한다.

Flow:
  Coordinator 진입 → hawk_candidates 만큼 per_coin_pipeline 병렬 실행
                  → 모든 결과 per_coin_results에 취합
                  → Hawk Picker로 전달
"""

import asyncio
import logging
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from magpie_agent.state.magpie import MagpieState

logger = logging.getLogger(__name__)


async def parallel_coordinator_node(
    state: MagpieState,
    per_coin_pipeline: CompiledStateGraph | None = None,
) -> dict[str, Any]:
    """여러 후보 코인을 병렬로 분석/계산하는 Coordinator 노드.

    hawk_candidates의 각 코인에 대해 per_coin_pipeline을 asyncio.gather로
    동시에 실행하고, 모든 결과를 per_coin_results에 취합한다.

    Returns:
        per_coin_results에 모든 코인의 분석 결과를 담은 dict.
    """
    target_coins: list[str] = state.get("hawk_candidates") or []
    if not target_coins:
        print("   ⚠️ [Coordinator]: hawk_candidates가 비어 있어 병렬 처리를 건너<0xEB><0x8A><0xB0><0xEB><0x8B><0x88><0xEB><0x8B><0xA4>.")
        return {"per_coin_results": []}

    print(f"\n⚡ [Coordinator]: {len(target_coins)}개 코인 병렬 분석 시작...")
    if per_coin_pipeline is None:
        raise RuntimeError("per_coin_pipeline subgraph is required for parallel_coordinator_node")

    async def run_single_coin(coin: str) -> dict[str, Any]:
        """단일 코인에 대한 per_coin_pipeline을 실행한다."""
        input_state = {
            **state,
            "current_target_coin": coin,
            "hawk_candidates": [coin],
        }
        try:
            result = await per_coin_pipeline.ainvoke(input_state)
            # per_coin_pipeline은 collect_per_coin_result 노드에서
            # per_coin_results=[{coin, current_price, ...}]를 state에 설정함
            coin_results = result.get("per_coin_results", [])
            if coin_results:
                print(f"   ✅ [{coin}]: 분석 완료 (score={coin_results[0].get('dolphin_score')})")
            else:
                print(f"   ⚠️ [{coin}]: 분석 완료 but 결과 없음")
            return result
        except Exception as e:
            logger.exception("[%s] Per-coin pipeline 실행 실패", coin)
            print(f"   ❌ [{coin}]: 분석 실패 — {e}")
            # 실패해도 빈 entry로 수집을 유지
            return {
                "per_coin_results": [
                    {
                        "coin": coin,
                        "current_price": None,
                        "chart_context": "",
                        "dolphin_score": None,
                        "dolphin_reasoning": f"Error: {e}",
                        "bull_summary": "",
                        "bear_summary": "",
                        "error": str(e),
                    }
                ]
            }

    # 모든 코인 병렬 실행
    results = await asyncio.gather(*[run_single_coin(coin) for coin in target_coins])

    # 모든 per_coin_results 취합
    all_results: list[dict[str, Any]] = []
    for r in results:
        all_results.extend(r.get("per_coin_results", []))

    print(f"   ✅ [Coordinator]: {len(all_results)}개 코인 분석 완료 (취합)")
    return {"per_coin_results": all_results}
