# 🪶 Project Magpie

Project Magpie는 AI Harness 아키텍처 위에서 동작하는 LLM 자율 트레이딩 에이전트입니다.

사용자의 자연어 요청을 구체적인 매매 전략으로 번역하고, 시장을 실시간으로 감시하며 자동 매매를 수행합니다.

## 🌲 Architecture

* **🦉 Owl Director:** 사용자의 막연한 투자 전략을 구체적인 감시 룰(JSON)로 번역하고 텔레그램으로 소통합니다.
* **🦇 Bat Daemon:** 업비트 WebSocket을 통해 1초 단위로 시장의 흐름을 낚아채고 룰과 대조합니다.
* **🪹 The-Nest (MongoDB):** 전략 데이터와 누적된 매매 기록을 영구적으로 보관하는 안전한 둥지입니다.
* **🐹 Hamster-wheel (Redis Alpine):** 엄청나게 빠른 속도로 부엉이와 박쥐 사이의 메시지(Queue)를 실어 나르는 초경량 인메모리 쳇바퀴입니다.



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


### 5. main 실행

```bash
uv run python -m main.run
```


## 🛠️ 실행 및 테스트 (VS Code)
루트 디렉토리의 .vscode/launch.json에 디버깅 환경이 세팅되어 있습니다.

VS Code 좌측의 Run and Debug 버튼 클릭

상단 드롭다운에서 🦉 Run Owl Director (main_test.py) 선택

F5 키를 눌러 실행

- Streamlit dashboard
    - `uv run streamlit run dashboard.py`