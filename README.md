# 🪶 Project Magpie

Project Magpie는 AI Harness 아키텍처 위에서 동작하는 LLM 자율 트레이딩 에이전트입니다.

사용자의 자연어 요청을 구체적인 매매 전략으로 번역하고, 시장을 실시간으로 감시하며 자동 매매를 수행합니다.

## 🌲 Architecture

* **🦉 Magpie Agent:** Owl Director, Hawk Picker, Meerkat Scanner가 LangGraph 위에서 협력해 전략, 종목, 타점을 계산합니다.
* **🦇 Bat Daemon:** `monitoring_targets`를 기준으로 업비트 1시간 캔들을 감시하고, BUY/SELL 신호 발생 시 즉시 직접 체결합니다.
* **🪹 The-Nest (MongoDB):** `strategies`, `monitoring_targets`, `wallets`를 저장합니다.
* **📊 Dashboard:** Streamlit에서 Agent 실행 과정, Bat Daemon dry-run, backtest 결과를 관찰합니다.

## 📁 Directory Structure

```text
magpie_agent/   # LangGraph 기반 에이전트 런타임
bat_daemon/     # 실시간 감시 데몬 및 과거 데이터 백테스트
dashboard/      # Streamlit 관찰/운영 대시보드
db/             # MongoDB 연결 및 Pydantic entity
```

* `magpie_agent/graph.py`: Owl/Meerkat 노드와 도구를 연결하는 LangGraph 그래프
* `magpie_agent/agents/`: Owl Director, Meerkat Scanner 노드/프롬프트/스키마
* `magpie_agent/tools/`: 전략, 타점, 지갑 도구
* `magpie_agent/graphs/`: common, target_refresh, signal_trigger, daily_report builder
* `bat_daemon/run.py`: DB의 monitoring target을 실시간 Upbit tick과 대조
* `bat_daemon/backtest.py`: 현재 DB target을 과거 1시간봉으로 dry-run 백테스트
* `dashboard/run.py`: Agent 탭과 Bat Daemon 탭을 제공하는 Streamlit 진입점

## 📝 작업 문서 동기화 규칙

기능 수정이나 실행 플로우 변경이 있으면 아래 문서도 함께 업데이트합니다.

* `AGENT.md`
* `docs/project_magpie_manual.html`

## 📌 현재 동작 기준 핵심 메모

* `magpie_agent/run.py`는 사용자 대화용 Common Graph를 실행합니다.
* `bat_daemon/run.py`는 Owl을 거치지 않고 직접 BUY/SELL을 실행합니다.
* SELL 완료 후 target 상태는 `EXPIRED`가 되고, Daemon은 Meerkat refresh 그래프로 새 `WAITING_BUY` 타점을 다시 계산합니다.
* `monitoring_targets`에는 `buy_allocation_pct`가 포함되며, BUY 체결 금액은 현재 지갑 원화 잔고의 해당 비율로 계산됩니다.
* `wallets`에는 잔고와 자산 외에 `trade_history`가 저장됩니다.
* `bat_daemon/backtest.py`와 dashboard의 Bat Daemon 뷰는 `run.py`의 dry-run 직접 체결 경로를 최대한 동일하게 재생합니다.
* dry-run/backtest에서는 target 조회용 `user_id`와 wallet 조회용 `wallet_user_id`를 분리할 수 있습니다.
* dashboard는 이제 전역 사이드바 대신 각 탭 안에서 필요한 입력값을 직접 받습니다.

## 🚀 로컬 개발 환경 세팅 가이드

팀원 간 원활한 협업을 위해 아래 순서대로 개발 환경을 세팅해 주세요.

### 1. uv 설치
본 프로젝트는 `uv`를 패키지 및 가상환경 관리 도구로 사용합니다.

https://docs.astral.sh/uv/getting-started/installation/

### 2. 패키지 설치

종속성은 `pyproject.toml`로 관리되며, 아래 명령어 한 줄로 가상환경 생성과 패키지 설치가 동시에 완료됩니다.

```bash
uv sync
```

### 3. 인프라 실행 (Docker Compose)
현재 핵심 저장소는 MongoDB입니다.

```bash
docker-compose up -d
(종료 시: docker-compose down)
```

### 4. 환경 변수 세팅
프로젝트 루트 경로에 .env.example을 복사해서 .env 파일을 생성하고 내용을 입력합니다.


### 5. Magpie Agent 실행

```bash
uv run python -m magpie_agent.run
```

### 6. Bat Daemon 실행

```bash
uv run python -m bat_daemon.run
```

### 7. Bat Backtest 실행

```bash
uv run python -m bat_daemon.backtest \
  --user-id test_developer_001 \
  --wallet-user-id test_developer_001 \
  --start "2024-01-01 00:00:00" \
  --end "2024-02-01 00:00:00"
```

### 8. Dashboard 실행

```bash
uv run streamlit run dashboard/run.py
```


## 🛠️ 실행 및 테스트 (VS Code)
루트 디렉토리의 .vscode/launch.json에 디버깅 환경이 세팅되어 있습니다.

VS Code 좌측의 Run and Debug 버튼 클릭

상단 드롭다운에서 원하는 실행 구성을 선택

F5 키를 눌러 실행

현재 제공되는 구성:

* `🦉 Magpie Agent`
* `🦇 Bat Daemon`
* `🧪 Bat Backtest`
