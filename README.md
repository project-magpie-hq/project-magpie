# 🪶 Project Magpie

Project Magpie는 AI Harness 아키텍처 위에서 동작하는 LLM 자율 트레이딩 에이전트입니다.

사용자의 자연어 요청을 구체적인 매매 전략으로 번역하고, 시장을 실시간으로 감시하며 자동 매매를 수행합니다.

## 🌲 Architecture

* **🦉 Owl Director:** 사용자의 막연한 투자 전략을 구체적인 감시 룰(JSON)로 번역하고 텔레그램으로 소통합니다.
* **🦇 Bat Daemon:** 업비트 WebSocket을 통해 1초 단위로 시장의 흐름을 낚아채고 룰과 대조합니다.
* **🪹 The-Nest (MongoDB):** 전략 데이터와 누적된 매매 기록을 영구적으로 보관하는 안전한 둥지입니다.
* **🐹 Hamster-wheel (Redis Alpine):** 엄청나게 빠른 속도로 부엉이와 박쥐 사이의 메시지(Queue)를 실어 나르는 초경량 인메모리 쳇바퀴입니다.

## 📁 Directory Structure

```text
magpie_agent/   # LangGraph 기반 에이전트 런타임
bat_daemon/     # 실시간 감시 데몬 및 과거 데이터 백테스트
dashboard/      # Streamlit 관찰/운영 대시보드
db/             # MongoDB 연결 및 Pydantic entity
```

* `magpie_agent/graph.py`: Owl/Meerkat 노드와 도구를 연결하는 LangGraph 그래프
* `magpie_agent/agents/`: Owl Director, Meerkat Scanner 노드/프롬프트/스키마
* `magpie_agent/tools/`: 전략, 타점, 지갑, 거래 내역 도구
* `bat_daemon/run.py`: DB의 monitoring target을 실시간 Upbit tick과 대조
* `bat_daemon/backtest.py`: 현재 DB target을 과거 1시간봉으로 dry-run 백테스트
* `dashboard/run.py`: Agent 탭과 Bat Daemon 탭을 제공하는 Streamlit 진입점

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
The-Nest(MongoDB)와 Hamster-wheel(Redis)을 백그라운드에서 실행합니다.

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
