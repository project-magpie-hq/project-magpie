# Project Magpie Agent Notes

이 문서는 이 저장소에서 작업할 때 빠르게 참고하는 운영 메모입니다.

## 목적

- `magpie_agent/`는 사용자 입력과 Daemon 이벤트를 LangGraph 기반 에이전트 플로우로 처리합니다.
- `magpie_agent/graphs/`는 용도별 LangGraph builder 모음입니다.
  - `common.py`: 사용자 기본 그래프
  - `target_refresh.py`: EXPIRED 타점 refresh 그래프
  - `signal_trigger.py`, `daily_report.py`: 현재는 직접 엔트리포인트 연결이 없는 준비된 분리 그래프
  - `shared.py`: Owl/Hawk/Meerkat/Calculate Team 노드 및 edge 조립 헬퍼
- `bat_daemon/`는 `monitoring_targets`를 기준으로 업비트 시장 데이터를 감시하고 시그널을 발생시킵니다.
- `db/`는 `strategies`, `monitoring_targets`, `wallets`를 관리합니다.
- `docs/project_magpie_manual.html`은 현재 코드 기준 실행 플로우 설명서입니다.
- `monitoring_targets`에는 가격 조건뿐 아니라 `buy_allocation_pct` 같은 포지션 비율 정보도 포함됩니다.
- Calculate Team (Bull/Bear/Dolphin)이 Meerkat의 차트 분석 결과를 입력받아 토론을 통해 타점을 최종 결정합니다.
- `wallets`에는 현재 자산 외에 `trade_history`가 저장되어 Meerkat이 다음 타점 계산 시 과거 체결 맥락을 함께 참고합니다.
- dashboard의 Backtest와 `bat_daemon/backtest.py`는 원본 전략 `user_id`를 읽어 백테스트 전용 `backtest_id`의 전략/지갑/타점을 새로 생성한 뒤 재생합니다.
- Calculate Team은 bull_first + bear_first (병렬) → bull_rebuttal + bear_rebuttal (병렬) → dolphin_judge 3-Wave 토론 구조입니다.
- dashboard는 전역 사이드바 대신 Agent 탭과 Bat Daemon 탭 안에서 각각 필요한 입력값을 직접 받습니다.

## 핵심 실행 흐름

- 사용자 진입점: `magpie_agent/run.py`
  - Owl Director가 사용자 요청을 분석합니다.
  - 필요 시 Hawk Picker가 종목을 선정합니다.
  - Meerkat Scanner가 차트 분석을 수행합니다.
- Calculate Team (Bull/Bear/Dolphin)이 토론을 통해 최종 타점을 계산하고 `monitoring_targets`를 저장합니다.
- Daemon 진입점: `bat_daemon/run.py`
  - `monitoring_targets`를 주기적으로 동기화합니다.
  - 실시간 가격/마감 캔들 조건을 검사합니다.
  - BUY 시그널 발생 시 `buy_allocation_pct`만큼 현재 원화 잔고를 사용해 직접 매수합니다.
  - SELL 시그널 발생 시 해당 코인 보유 수량을 직접 매도합니다.
  - 매도 완료 타겟은 `EXPIRED`로 바꾸고, Meerkat 그래프로 새 타점을 다시 계산합니다.
- 백테스트 진입점: `bat_daemon/backtest.py`
  - 원본 전략을 `backtest_id`로 복제하고, 백테스트 전용 지갑과 monitoring target을 초기화합니다.
  - 시작 시점의 refresh 그래프로 초기 타점을 만든 뒤, 전략의 `target_coins` 전체에 대한 과거 1시간봉 데이터를 로드합니다.
  - 과거 tick 재생 중 `EXPIRED` refresh가 예약되면 해당 refresh가 끝날 때까지 기다린 뒤 다음 tick 재생을 이어갑니다.
  - Meerkat/Gemini refresh가 쿼터 등으로 실패하더라도 백테스트 재생 자체는 계속 진행합니다.

## 수정 시 체크 규칙

- 기능, 조건 분기, 상태 전이, DB 컬렉션 사용 방식이 바뀌면 `docs/project_magpie_manual.html`도 같이 갱신합니다.
- 프로젝트 구조나 작업 원칙이 바뀌면 이 `AGENT.md`도 같이 갱신합니다.
- 특히 아래 변경은 문서 동기화 대상입니다.
  - 엔트리포인트 변경
  - `magpie_agent/graphs/` 내 builder 추가/삭제/사용처 변경
  - Owl / Hawk / Meerkat 라우팅 변경
  - BatDaemon 시그널 조건 변경
  - `strategies`, `monitoring_targets`, `wallets` 입출력 변경

## 작업 기본 원칙

- 플로우를 바꾸는 수정은 코드와 문서를 함께 반영합니다.
- UI/대시보드 수정이 아니더라도 실행 흐름에 영향이 있으면 `project_magpie_manual.html`을 먼저 의심합니다.
- 새 작업을 끝낼 때는 "코드", "`AGENT.md`", "`docs/project_magpie_manual.html`"의 동기화 여부를 함께 확인합니다.
- `bat_daemon/backtest.py`와 dashboard의 Backtest 뷰는 가능한 한 `bat_daemon/run.py`의 실제 체결 경로를 그대로 사용하되, 과거 tick 데이터와 `backtest_id` 전용 DB 문서만 다르게 사용합니다.
- 백테스트 동작을 바꿀 때는 초기 타점 생성 방식, 과거 데이터 로드 범위(`watching_coins` vs 전략 전체 `target_coins`), refresh 완료 대기 시점을 함께 확인합니다.
