# 🪶 Project Magpie

Project Magpie는 AI Harness 아키텍처 위에서 동작하는 LLM 자율 트레이딩 에이전트입니다.
사용자의 자연어 요청을 구체적인 매매 전략으로 번역하고, 시장을 실시간으로 감시하며 자동 매매를 수행합니다.

## 🌲 Architecture

* **🦉 Owl Director:** 사용자의 막연한 투자 전략을 구체적인 감시 룰(JSON)로 번역하고 텔레그램으로 소통합니다.
* **🦇 Bat Daemon:** 업비트 WebSocket을 통해 1초 단위로 시장의 흐름을 낚아채고 룰과 대조합니다.
* **🪹 The-Nest (MongoDB):** 전략 데이터와 누적된 매매 기록을 영구적으로 보관하는 안전한 둥지입니다.
* **🐹 Hamster-wheel (Redis Alpine):** 엄청나게 빠른 속도로 부엉이와 박쥐 사이의 메시지(Queue)를 실어 나르는 초경량 인메모리 쳇바퀴입니다.

---

## 🚀 로컬 개발 환경 세팅 가이드

팀원 간 원활한 협업을 위해 아래 순서대로 개발 환경을 세팅해 주세요.

### 1. 가상환경(venv) 생성 및 진입
```bash
python -m venv .venv
.\.venv\Scripts\activate
```
#### ⚠️ Windows 사용자 (PowerShell 권한 에러나오면 수행):
아래 명령어를 입력하여 스크립트 실행 권한을 허용한 이후 다시 가상환경에 진입합니다
```bash
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\.venv\Scripts\activate
```

### 2. 패키지 설치
본 시스템은 C언어 기반의 강력한 보조지표 라이브러리인 TA-Lib를 사용합니다.
별도 whl 파일로 설치가 필요합니다.

#### 🪟 컴파일 에러를 방지하기 위해 휠(.whl) 파일을 먼저 설치한 후 파이썬 패키지를 설치합니다.

```bash
pip install ./TA_Lib‑0.6.8‑cp314‑cp314‑win_amd64.whl
pip install -r requirements.txt
```

### 3. 인프라 실행 (Docker Compose)
The-Nest(MongoDB)와 Hamster-wheel(Redis)을 백그라운드에서 실행합니다.

```bash
docker-compose up -d
(종료 시: docker-compose down)
```

### 4. 환경 변수 세팅
프로젝트 루트 경로에 .env 파일을 생성하고 아래 내용을 입력합니다.
```
# Database URLs
MONGO_URL=mongodb://localhost:27017
REDIS_URL=redis://localhost:6379

# API Keys (각자 발급받은 키 입력)
UPBIT_ACCESS_KEY=your_upbit_access_key
UPBIT_SECRET_KEY=your_upbit_secret_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
GEMINI_API_KEY=your_gemini_api_token
GROQ_API_KEY=your_groq_api_key
```

---

## 🛠️ 실행 및 테스트 (VS Code)
루트 디렉토리의 .vscode/launch.json에 디버깅 환경이 세팅되어 있습니다.

VS Code 좌측의 Run and Debug 버튼 클릭

상단 드롭다운에서 🦉 Run Owl Director (main_test.py) 선택

F5 키를 눌러 실행
