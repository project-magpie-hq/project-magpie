# Project Magpie

Project Magpie는 LangGraph 기반의 AI 트레이딩 워크플로우와 실시간 감시 데몬, 그리고 운영용 대시보드를 함께 갖춘 실험용 자동매매 프로젝트입니다.

지금 기준의 핵심 구조는 아래 세 층으로 나뉩니다.

- `magpie_agent/`: 사용자 요청을 전략과 감시 타점으로 바꾸는 LangGraph 에이전트
- `bat_daemon/`: 저장된 타점을 실시간 가격과 비교해 직접 BUY/SELL을 수행하는 감시 데몬
- `dashboard/`: Agent 실행 흐름, Daemon 판정, Wallet/Backtest 상태를 확인하는 Streamlit UI

## Current Flow

사용자 대화 진입점은 `magpie_agent/run.py`이며, 실제 메인 그래프는 `magpie_agent/graphs/common.py`의 `build_common_graph()`입니다.

현재 기본 그래프는 아래 순서로 동작합니다.

```text
Owl Director
  -> Fox Finder
  -> Parallel Coordinator
  -> Hawk Picker
```

다만 코인별 상세 분석은 Coordinator 내부에서 병렬로 실행되는 `per_coin_pipeline`이 담당합니다.

```text
Per-Coin Pipeline
  -> Meerkat Scanner
  -> Calculate Team (Bull / Bear / Dolphin)
  -> monitoring_targets 저장
```

정리하면:

- Owl Director: 사용자 요청을 해석하고 전략 등록/조회 흐름을 시작합니다.
- Fox Finder: 전략 기반으로 후보 코인을 뽑습니다.
- Parallel Coordinator: 후보 코인별 분석 파이프라인을 `asyncio.gather`로 병렬 실행합니다.
- Hawk Picker: 병렬 분석 결과를 보고 최종 타깃 코인을 확정합니다.
- Meerkat Scanner: 차트 분석 리포트와 계산 컨텍스트를 만듭니다.
- Calculate Team: Bull/Bear 토론과 Dolphin 판정으로 최종 타점과 `buy_allocation_pct`를 계산합니다.

## Runtime Components

### 1. Magpie Agent

- 엔트리포인트: `uv run python -m magpie_agent.run`
- 입력 채널: Telegram bot
- 역할: 전략 수립, 후보 종목 선정, 코인별 차트 분석, 최종 감시 타점 저장

### 2. Bat Daemon

- 엔트리포인트: `uv run python -m bat_daemon.run`
- 역할: `monitoring_targets`를 읽어 업비트 1시간 캔들을 감시하고 직접 체결

Daemon의 현재 동작 기준은 아래와 같습니다.

- `WAITING_BUY`, `HOLDING` 상태만 감시합니다.
- BUY는 `buy_allocation_pct`만큼 현재 KRW 잔고를 사용합니다.
- SELL은 보유 수량 전량 기준으로 처리합니다.
- SELL 완료 후 대상 타점은 `EXPIRED`로 바뀝니다.
- `EXPIRED` 타점이 보이면 `Target Refresh Graph`를 호출해 새 `WAITING_BUY` 타점을 다시 계산합니다.

### 3. Dashboard

- 엔트리포인트: `uv run streamlit run dashboard/run.py`
- 탭 구성:
  - `Magpie Agent`: 그래프 노드별 실행 이벤트 확인
  - `Bat Daemon`: 감시 타점, tick 판정, 시그널 로그 확인
  - `Wallet`: 지갑 및 체결 이력 확인

백테스트 전용 대시보드는 별도입니다.

- 엔트리포인트: `uv run streamlit run dashboard/backtest.py`
- 역할: 원본 전략을 `backtest_id`로 복제한 뒤 과거 tick 기반으로 실제 Daemon 체결 흐름을 재생

## Graph Map

`magpie_agent/graphs/` 아래 빌더들은 현재 이렇게 쓰입니다.

- `common.py`: 사용자 기본 진입 그래프
- `target_refresh.py`: Daemon이 `EXPIRED` 타점을 다시 계산할 때 사용하는 그래프
- `signal_trigger.py`: 분리되어 준비된 그래프, 현재는 직접 엔트리포인트에 연결되지 않음
- `daily_report.py`: 정기 점검용 확장 그래프, 현재는 직접 엔트리포인트에 연결되지 않음
- `analyze_and_calculate.py`: `Meerkat -> Calculate Team -> 저장` 재사용 서브그래프
- `per_coin_pipeline.py`: 코인 1개 단위 분석을 수행하는 병렬 처리용 서브그래프
- `shared.py`: 공통 노드/엣지 조립 헬퍼

## Data Model

MongoDB 데이터베이스 이름은 `the_nest`입니다.

- `strategies`: Owl이 저장하고 Hawk가 `target_coins`를 갱신합니다.
- `monitoring_targets`: Calculate Team이 최종 타점과 `buy_allocation_pct`를 저장합니다.
- `wallets`: 원화 잔고, 코인 자산, `trade_history`를 저장합니다.

## Local Setup

### 1. Install `uv`

`uv`를 패키지/가상환경 관리 도구로 사용합니다.

https://docs.astral.sh/uv/getting-started/installation/

### 2. Install dependencies

```bash
uv sync
```

### 3. Start MongoDB

```bash
docker-compose up -d
```

종료:

```bash
docker-compose down
```

### 4. Configure environment variables

루트에 `.env` 파일을 만들고 최소한 아래 값은 채워두는 편이 좋습니다.

- `MONGO_URL`
- `TELEGRAM_BOT_TOKEN`

## Run Commands

### Agent

```bash
uv run python -m magpie_agent.run
```

### Bat Daemon

```bash
uv run python -m bat_daemon.run
```

### Dashboard

```bash
uv run streamlit run dashboard/run.py
```

### Backtest CLI

```bash
uv run python -m bat_daemon.backtest \
  --strategy-user-id test_developer_001 \
  --backtest-id backtest_001 \
  --start "2024-01-01 00:00:00" \
  --end "2024-02-01 00:00:00" \
  --initial-balance 100000000
```

### Backtest Dashboard

```bash
uv run streamlit run dashboard/backtest.py
```

## Directory Guide

```text
magpie_agent/
  agents/      # Owl, Fox, Hawk, Meerkat, Calculate Team
  graphs/      # main graph builders and reusable subgraphs
  tools/       # strategy, wallet, target persistence helpers
  state/       # MagpieState

bat_daemon/
  run.py       # realtime monitoring daemon
  backtest.py  # historical replay based backtest

dashboard/
  run.py       # main Streamlit dashboard
  backtest.py  # backtest dashboard
  views/       # per-tab renderers

db/
  mongo.py     # Mongo connection
  entity.py    # Pydantic entities
```

## Documentation Sync

실행 플로우나 그래프 구조를 바꾸면 아래 문서도 함께 갱신합니다.

- `README.md`
- `AGENT.md`
- `docs/project_magpie_manual.html`
