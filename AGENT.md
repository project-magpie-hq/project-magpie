# Project Magpie Agent Notes

이 문서는 저장소 구조를 다시 파악할 때 빠르게 보는 유지보수 메모입니다.

## What Is Active Now

- 사용자 대화 엔트리포인트: `magpie_agent/run.py`
- Agent 메인 그래프 alias: `magpie_agent/graph.py`
- 실제 사용자 기본 그래프: `magpie_agent/graphs/common.py`
- 실시간 감시 엔트리포인트: `bat_daemon/run.py`
- 백테스트 엔트리포인트: `bat_daemon/backtest.py`
- 운영 대시보드: `dashboard/run.py`
- 백테스트 대시보드: `dashboard/backtest.py`

## Graph Roles

### `build_common_graph()`

사용자 기본 그래프입니다.

```text
Owl Director
  -> Fox Finder
  -> Parallel Coordinator
  -> Hawk Picker
```

핵심 포인트:

- Fox가 후보 코인을 저장합니다.
- Coordinator가 후보 코인마다 `per_coin_pipeline`을 병렬 실행합니다.
- Hawk가 `per_coin_results`를 보고 최종 `target_coins`를 고릅니다.
- Hawk는 선택되지 않은 코인의 `monitoring_targets`를 정리합니다.

### `build_per_coin_pipeline()`

Coordinator가 코인별로 돌리는 서브그래프입니다.

```text
Meerkat Scanner
  -> prepare
  -> Bull / Bear
  -> rebuttal
  -> Dolphin Judge
  -> register_monitoring_targets_to_nest
  -> collect_result
```

핵심 포인트:

- 단일 코인 기준으로 실행됩니다.
- `current_target_coin`, `hawk_candidates=[coin]` 상태로 호출됩니다.
- 결과는 `per_coin_results`에 축적됩니다.

### `build_target_refresh_graph()`

Daemon 후속 재계산 그래프입니다.

```text
Meerkat Scanner
  -> Calculate Team
  -> register_monitoring_targets_to_nest
```

사용 시점:

- SELL 완료 후 타점이 `EXPIRED`가 되었을 때
- Daemon이 새 `WAITING_BUY` 타점을 다시 계산할 때

### `build_signal_trigger_graph()`

분리되어 준비된 그래프입니다.

- Daemon 이벤트용 Owl 진입 구조를 포함합니다.
- 현재 `bat_daemon/run.py`의 실사용 핵심 경로는 아닙니다.
- 문서에는 반드시 “현재 미연결/확장 예정”으로 취급합니다.

### `build_daily_report_graph()`

정기 점검용 확장 그래프입니다.

- Common과 유사한 구성입니다.
- 현재 직접 엔트리포인트에 연결되어 있지 않습니다.
- 문서에는 반드시 “현재 미연결/확장 예정”으로 취급합니다.

## Bat Daemon Rules

현재 기준 Daemon은 Agent 대신 직접 체결합니다.

- 감시 대상: `WAITING_BUY`, `HOLDING`
- BUY 체결 수량: 현재 KRW 잔고 `* buy_allocation_pct`
- SELL 체결 수량: 해당 자산 보유 전량
- SELL 완료 후 상태: `EXPIRED`
- `EXPIRED` 감지 시: `build_target_refresh_graph()` 호출

중요:

- 체결 로직은 `magpie_agent`가 아니라 `magpie_agent/tools/wallet.py`의 helper와 `bat_daemon/run.py`가 중심입니다.
- `process_trade_execution` tool은 남아 있어도, 현재 실시간 체결 주체는 Daemon입니다.

## Storage Map

MongoDB DB 이름: `the_nest`

- `strategies`
  - Owl이 등록/수정
  - Hawk가 최종 `target_coins` 갱신
- `monitoring_targets`
  - Calculate Team이 최종 타점 저장
  - Daemon은 `WAITING_BUY`, `HOLDING`만 감시
  - Hawk는 미선정 코인 타점을 삭제할 수 있음
- `wallets`
  - KRW 잔고, 자산, `trade_history` 저장
  - Daemon 체결 결과도 여기에 반영됨

## State Fields Worth Remembering

`MagpieState`에서 자주 보는 핵심 필드:

- `user_id`
- `from_daemon`
- `is_daily_review`
- `hawk_candidates`
- `current_target_coin`
- `per_coin_results`
- `chart_context`
- `current_price`
- `dolphin_score`
- `trigger_info`
- `wallet_data`
- `recent_trades`

## Backtest Behavior

`bat_daemon/backtest.py`는 현재 이렇게 동작합니다.

- 원본 전략을 `backtest_id` 사용자로 복제
- 백테스트 전용 지갑 초기화
- 기존 백테스트용 `monitoring_targets` 삭제
- 시작 시점에 `Target Refresh Graph`를 한 번 실행해 초기 타점 생성
- 과거 1시간봉을 tick path로 재생
- 재생 중 refresh가 예약되면 완료까지 기다렸다가 이어서 진행

즉, 가능하면 실시간 Daemon 체결 경로를 그대로 재사용하고, 입력 데이터만 과거 캔들로 바꿉니다.

## When You Change Code

아래 변경은 문서 동기화가 거의 필수입니다.

- 엔트리포인트 추가/삭제
- `magpie_agent/graphs/` 내부 빌더 구조 변경
- Agent 라우팅 순서 변경
- `per_coin_pipeline` 입력/출력 변경
- Daemon 상태 전이 변경
- `strategies`, `monitoring_targets`, `wallets` 스키마 의미 변경
- Dashboard 탭 구성 변경

함께 확인할 문서:

- `README.md`
- `AGENT.md`
- `docs/project_magpie_manual.html`
