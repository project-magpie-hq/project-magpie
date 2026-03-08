# 🪶 Project Magpie

Project Magpie는 **LangGraph** 멀티 에이전트 아키텍처 기반의 가상자산 자동 매매 하네스(Harness)입니다.

사용자의 자연어 요청을 구체적인 매매 전략으로 번역하고, 백테스트 및 실거래 환경에서 자동 매매를 수행합니다.

---

## 🏗️ 기술 스택

| 구분 | 기술 |
|------|------|
| Python | 3.13, venv (`.venv/`) |
| LLM | Groq Llama 3.3 70B (기본), Gemini 2.5 Flash 등 — `LLMModel` enum 관리 |
| Agent Framework | LangGraph, LangChain |
| DB | MongoDB (motor, async) |
| 거래소 API | pyupbit (업비트 Open API) |
| 데이터 모델 | Pydantic BaseModel (전역 통일) |

---

## 🌲 Architecture

### 에이전트

* **🐿️ Meerkat Scanner:** 사용자의 매매 스타일과 종목을 입력받아 기술적 지표 기반 전략을 설계하고 MongoDB에 저장합니다.
* **🦉 Owl Director:** Meerkat이 설계한 전략과 실시간 OHLCV 데이터를 기반으로 매 타임스텝 BUY/SELL/HOLD 의사결정을 수행합니다.

### 인프라

* **🪹 The-Nest (MongoDB):** 전략, 매매 로그, 자산 스냅샷을 보관합니다.
* **🐹 Hamster-wheel (Redis):** 에이전트 간 메시지 큐 (예정).

### 실행 모드

`EngineConfig.mode` 파라미터 하나로 백테스트 ↔ 실거래 전환:

```python
from backtest.engine import EngineConfig
from providers.base import ProviderMode

config = EngineConfig(
    symbol="KRW-BTC",
    style="balanced",
    user_prompt="비트코인 균형 매매",
    mode=ProviderMode.BACKTEST,  # REAL로 바꾸면 실거래
)
```

---

## 📁 프로젝트 구조

```
project-magpie/
├── main.py                 # Telegram 챗봇 모드
├── backtest_main.py        # 백테스트 진입점
├── live_main.py            # 실거래 진입점
├── engine_factory.py       # 엔진 디스패치 팩토리
│
├── core/                   # 공용 모듈
│   ├── constants.py        # FEE_RATE, INTERVAL_SECONDS
│   ├── graph.py            # Meerkat 그래프 빌더, run_meerkat(), fetch_ohlcv()
│   └── llm.py              # LLMModel enum, create_llm() 팩토리
│
├── db/                     # MongoDB
│   ├── connection.py       # 공유 AsyncIOMotorClient (singleton)
│   └── schemas.py          # 컬렉션 스키마, CollectionName(StrEnum)
│
├── providers/              # 자산 정보 추상화
│   ├── base.py             # AssetProvider ABC, ProviderMode, BalanceInfo 등
│   ├── mongo.py            # 백테스트: MongoDB 가상 잔고
│   └── upbit.py            # 실거래: 업비트 API 실잔고 + 주문
│
├── state/                  # LangGraph State
│   ├── agent.py            # AgentState (TypedDict)
│   └── magpie.py           # MagpieState (Telegram 모드)
│
├── agents/
│   ├── meerkat_scanner/
│   │   ├── scanner.py      # Meerkat LangGraph 노드
│   │   └── prompt.md
│   └── owl_director/
│       ├── decision.py     # owl_decide() — BUY/SELL/HOLD
│       ├── director.py     # Telegram 모드 Owl 노드
│       └── prompt.md
│
├── tools/                  # LangChain Tools
│   ├── ohlcv.py            # get_ohlcv_tool (pyupbit)
│   ├── db.py               # 전략 DB CRUD
│   └── strategy.py         # Telegram 모드 전용
│
├── backtest/
│   ├── engine.py           # BacktestEngine, EngineConfig
│   └── reporter.py         # KPI 산출 (수익률, 승률, 샤프, MDD)
│
└── live/
    └── engine.py           # LiveEngine (무한 루프 + 실주문)
```

---

## 🚀 로컬 개발 환경 세팅

### 1. uv 설치

```bash
# https://docs.astral.sh/uv/getting-started/installation/
```

### 2. 패키지 설치

```bash
uv sync
```

### 3. 인프라 실행 (Docker Compose)

```bash
docker-compose up -d
# 종료: docker-compose down
```

### 4. 환경 변수

프로젝트 루트에 `.env` 파일 생성:

```
MONGO_URL=mongodb://localhost:27017
GROQ_API_KEY=<your-groq-api-key>            # 기본 LLM (Groq 무료 티어)
GOOGLE_API_KEY=<your-gemini-api-key>         # Gemini 모델 사용 시
UPBIT_ACCESS_KEY=<your-upbit-access-key>     # 실거래 모드
UPBIT_SECRET_KEY=<your-upbit-secret-key>     # 실거래 모드
```

---

## 🛠️ 실행

```bash
# 백테스트
uv run python backtest_main.py

# 실거래
uv run python live_main.py

# Telegram 챗봇 모드
uv run python main.py
```

상세 아키텍처 및 구현 가이드는 `development_guide.md` 참조.
