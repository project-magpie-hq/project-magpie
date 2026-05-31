# Project Magpie Agent Notes

이 문서는 이 저장소에서 작업할 때 빠르게 참고하는 운영 메모입니다.

## 목적

- `magpie_agent/`는 사용자 입력과 Daemon 이벤트를 LangGraph 기반 에이전트 플로우로 처리합니다.
- `magpie_agent/graphs/`는 용도별 LangGraph builder 모음입니다.
  - `common.py`: 사용자 기본 그래프
  - `target_refresh.py`: EXPIRED 타점 refresh 그래프
  - `signal_trigger.py`, `daily_report.py`: 현재는 직접 엔트리포인트 연결이 없는 준비된 분리 그래프
  - `shared.py`: Owl/Hawk/Meerkat 노드 및 edge 조립 헬퍼
- `bat_daemon/`는 `monitoring_targets`를 기준으로 업비트 시장 데이터를 감시하고 시그널을 발생시킵니다.
- `db/`는 `strategies`, `monitoring_targets`, `wallets`, `trade_history`를 관리합니다.
- `docs/project_magpie_manual.html`은 현재 코드 기준 실행 플로우 설명서입니다.
- `monitoring_targets`에는 가격 조건뿐 아니라 `buy_allocation_pct` 같은 포지션 비율 정보도 포함됩니다.
- `wallets`에는 현재 자산 외에 `trade_stats`가 저장되어 최근 체결과 누적 매수/매도 규모를 함께 추적합니다.
- dashboard의 Bat Daemon dry-run/backtest는 기본적으로 현재 `user_id`의 지갑을 쓰지만, 필요하면 별도 `wallet_user_id` 지갑을 선택해 시뮬레이션할 수 있습니다.
- dashboard는 전역 사이드바 대신 Agent 탭과 Bat Daemon 탭 안에서 각각 필요한 입력값을 직접 받습니다.

## 핵심 실행 흐름

- 사용자 진입점: `magpie_agent/run.py`
  - Owl Director가 사용자 요청을 분석합니다.
  - 필요 시 Hawk Picker가 종목을 선정합니다.
  - Meerkat Scanner가 최종 타점을 계산하고 `monitoring_targets`를 저장합니다.
- Daemon 진입점: `bat_daemon/run.py`
  - `monitoring_targets`를 주기적으로 동기화합니다.
  - 실시간 가격/마감 캔들 조건을 검사합니다.
  - BUY 시그널 발생 시 `buy_allocation_pct`만큼 현재 원화 잔고를 사용해 직접 매수합니다.
  - SELL 시그널 발생 시 해당 코인 보유 수량을 직접 매도합니다.
  - 매도 완료 타겟은 `EXPIRED`로 바꾸고, Meerkat 그래프로 새 타점을 다시 계산합니다.

## 수정 시 체크 규칙

- 기능, 조건 분기, 상태 전이, DB 컬렉션 사용 방식이 바뀌면 `docs/project_magpie_manual.html`도 같이 갱신합니다.
- 프로젝트 구조나 작업 원칙이 바뀌면 이 `AGENT.md`도 같이 갱신합니다.
- 특히 아래 변경은 문서 동기화 대상입니다.
  - 엔트리포인트 변경
  - `magpie_agent/graphs/` 내 builder 추가/삭제/사용처 변경
  - Owl / Hawk / Meerkat 라우팅 변경
  - BatDaemon 시그널 조건 변경
  - `strategies`, `monitoring_targets`, `wallets`, `trade_history` 입출력 변경

## 작업 기본 원칙

- 플로우를 바꾸는 수정은 코드와 문서를 함께 반영합니다.
- UI/대시보드 수정이 아니더라도 실행 흐름에 영향이 있으면 `project_magpie_manual.html`을 먼저 의심합니다.
- 새 작업을 끝낼 때는 "코드", "`AGENT.md`", "`docs/project_magpie_manual.html`"의 동기화 여부를 함께 확인합니다.
- `bat_daemon/backtest.py`와 dashboard의 Bat Daemon 뷰는 가능한 한 `bat_daemon/run.py`의 dry-run 직접 체결 경로와 동일하게 유지합니다.
- 단, dry-run/backtest에서는 target 조회용 `user_id`와 wallet 조회용 `wallet_user_id`를 분리할 수 있습니다.
