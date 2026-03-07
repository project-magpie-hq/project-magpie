# Project Magpie: Crypto Trading Agent Harness Development Guide

## 1. Project Overview

본 프로젝트는 **LangGraph** 프레임워크를 기반으로 멀티 에이전트 시스템을 활용한 가상자산 자동 매매 하네스(Harness)를 구축하는 것을 목표로 한다. 백테스팅 환경과 실거래 환경을 `EngineConfig.mode` 파라미터 하나로 전환할 수 있도록 추상화되어 있다.

### 기술 스택

| 구분 | 기술 |
|------|------|
| Python | 3.13, venv (`.venv/`) |
| LLM | Groq Llama 3.3 70B (기본), Gemini 2.5 Flash 등 — `core.llm.LLMModel` enum 관리 |
| Agent Framework | LangGraph, LangChain |
| DB | MongoDB (motor, async) — Docker `magpie-nest:27017`, DB `the_nest` |
| Cache | Redis — Docker `hamster-wheel:6379` (예정) |
| 거래소 API | pyupbit (업비트 Open API) |
| 데이터 모델 | Pydantic BaseModel (전역 통일) |
| 수수료 | 업비트 현물 0.05 % (`core.constants.FEE_RATE`) |

---

## 2. 프로젝트 구조

```
project-magpie/
├── main.py                     # Telegram 챗봇 모드 (Owl Director)
├── backtest_main.py            # 백테스트 진입점
├── live_main.py                # 실거래 진입점
├── engine_factory.py           # EngineConfig.mode → 엔진 디스패치 팩토리
├── docker-compose.yml          # MongoDB + Redis 컨테이너
├── pyproject.toml              # 의존성
├── .env                        # 환경변수 (MONGO_URL, UPBIT_ACCESS_KEY, ...)
│
├── core/                       # 프로젝트 공용 모듈
│   ├── constants.py            # FEE_RATE, INTERVAL_SECONDS
│   ├── graph.py                # build_meerkat_graph(), run_meerkat(), fetch_ohlcv()
│   └── llm.py                  # LLMModel enum, create_llm() 팩토리
│
├── db/                         # MongoDB 스키마 및 연결
│   ├── connection.py           # 공유 AsyncIOMotorClient (lazy singleton)
│   └── schemas.py              # 컬렉션 스키마 (Pydantic), CollectionName(StrEnum)
│
├── providers/                  # 자산 정보 추상화 (AssetProvider)
│   ├── base.py                 # AssetProvider ABC, ProviderMode, BalanceInfo, HoldingInfo, PortfolioInfo
│   ├── mongo.py                # 백테스트: MongoDB 가상 잔고
│   └── upbit.py                # 실거래: 업비트 API 실잔고 + 주문
│
├── state/                      # LangGraph State 정의
│   ├── agent.py                # AgentState (Meerkat ↔ Engine 공유 TypedDict)
│   └── magpie.py               # MagpieState (Telegram 챗봇 모드)
│
├── agents/                     # 에이전트 로직
│   ├── meerkat_scanner/
│   │   ├── scanner.py               # Meerkat LangGraph 노드
│   │   └── prompt.md                # 시스템 프롬프트
│   └── owl_director/
│       ├── decision.py              # owl_decide() — 매 타임스텝 BUY/SELL/HOLD
│       ├── director.py              # Telegram 챗봇 모드 Owl 노드
│       └── prompt.md                # Telegram 모드 시스템 프롬프트
│
├── tools/                      # LangChain Tools
│   ├── ohlcv.py                # get_ohlcv_tool (pyupbit Open API)
│   ├── db.py                   # find_existing_strategy, save_backtest_strategy, update_strategy_performance
│   └── strategy.py             # Telegram 모드 전용 (register_strategy_to_nest, get_my_active_strategy)
│
├── backtest/                   # 백테스트 엔진
│   ├── engine.py               # EngineConfig, TradeRecord, BacktestResult, BacktestEngine
│   └── reporter.py             # BacktestReporter (KPI 산출 + 터미널 출력)
│
└── live/                       # 실거래 엔진
    └── engine.py               # LiveEngine (무한 루프 + 실주문)
```

---

## 3. System Architecture & Agents

### 3.1 Meerkat Scanner Agent (Strategy Designer)

- **역할:** 투자 전략 수립 및 검증.
- **구현:** `agents/meerkat_scanner/scanner.py` — LangGraph 노드.
- **책임:**
    - 사용자의 매매 스타일(aggressive/stable/balanced) + 종목을 입력받아 기술적 지표(RSI, MACD, EMA 등)와 가중치를 정의한다.
    - 업비트 Open API로 OHLCV 데이터를 로드하여 전략의 유효성을 1차 검증한다.
    - MongoDB를 조회하여 동일 프롬프트/종목에 기존 전략이 있는지 확인한다 (prompt_hash 기반).
    - 기존 전략이 있으면 과거 매매 결과를 분석하여 전략 유지/수정을 결정한다 (Self-correction).
    - 최종 전략을 `[STRATEGY_READY]` 태그와 함께 반환한다.
- **도구:** `get_ohlcv_tool`, `find_existing_strategy`, `save_backtest_strategy`
- **LLM:** `core.llm.create_llm()` — 기본 Groq Llama 3.3 70B (temperature=0.1)

### 3.2 Owl Director Agent (Decision Maker)

- **역할:** 시점별 BUY/SELL/HOLD 의사결정.
- **구현:** `agents/owl_director/decision.py` — 단일 async 함수 `owl_decide()`.
- **책임:**
    - Meerkat이 확정한 전략과 현재 시점 OHLCV 윈도우를 받아 분석한다.
    - 전략에 정의된 지표와 가중치를 고려하여 BUY/SELL/HOLD 판단을 내린다.
    - JSON 형식으로 `OwlDecision(action, confidence, reasoning)` 반환.
- **LLM:** `core.llm.create_llm()` — 기본 Groq Llama 3.3 70B (temperature=0.0, 모듈 레벨 lazy singleton 재사용)

---

## 4. Data Layer

### 4.1 MongoDB 컬렉션 (`db/schemas.py`)

| 컬렉션 | 스키마 | 설명 |
|--------|--------|------|
| `strategies` | `StrategyDocument` | Meerkat이 생성/수정한 전략 (지표, 성과, 수정 이력) |
| `trade_logs` | `TradeLogDocument` | 매수/매도 시점, 가격, 수량, 수수료, 판단 근거 |
| `asset_states` | `AssetStateDocument` | 액션 후 자산 스냅샷 (현금 잔고, 보유 종목, 총 평가액) |

- **`CollectionName`**: `StrEnum` 으로 정의하여 타입 안전성 확보.
- **인덱스**: `ensure_indexes(db)` — 앱 시작 시 1회 호출.

### 4.2 공유 DB 연결 (`db/connection.py`)

```python
from db.connection import get_db, close_connection

db = get_db()  # lazy singleton AsyncIOMotorClient
# ... 사용 ...
await close_connection()  # 앱 종료 시
```

모든 모듈이 단일 `AsyncIOMotorClient`를 공유한다. 개별 모듈에서 `AsyncIOMotorClient`를 생성하지 않는다.

### 4.3 AssetProvider 추상화 (`providers/base.py`)

```
AssetProvider (ABC)
├── MongoAssetProvider   # 백테스트: MongoDB 가상 잔고 (save_snapshot, initialize_session)
└── UpbitAssetProvider   # 실거래: 업비트 API 실잔고 (buy_market_order, sell_market_order)
```

**반환 모델** (모두 Pydantic `BaseModel`):
- `BalanceInfo` — 현금 잔고 (cash, currency=KRW)
- `HoldingInfo` — 단일 종목 보유 (symbol, quantity, avg_buy_price)
- `PortfolioInfo` — 전체 포트폴리오 (cash, holdings, total_value)

### 4.4 공용 상수 (`core/constants.py`)

- `FEE_RATE = 0.0005` (업비트 0.05 %)
- `INTERVAL_SECONDS` — interval 문자열 → 초(seconds) 매핑 dict

### 4.5 LLM 팩토리 (`core/llm.py`)

프로젝트의 모든 에이전트는 `core.llm.create_llm()` 팩토리를 통해 LLM 인스턴스를 생성한다.
개별 에이전트에서 `ChatGoogleGenerativeAI` / `ChatGroq`를 직접 생성하지 않는다.

```python
from core.llm import LLMModel, create_llm

# 기본 모델 (Groq Llama 3.3 70B)
llm = create_llm(temperature=0.1)

# 특정 모델 지정
llm = create_llm(model=LLMModel.GEMINI_25_FLASH, temperature=0.0)
```

**`LLMModel` enum (StrEnum):**

| 값 | Provider | 모델 |
|----|----------|------|
| `LLAMA_33_70B` (기본) | Groq | `llama-3.3-70b-versatile` |
| `LLAMA_31_8B` | Groq | `llama-3.1-8b-instant` |
| `GEMMA2_9B` | Groq | `gemma2-9b-it` |
| `GEMINI_25_FLASH` | Google | `gemini-2.5-flash` |
| `GEMINI_20_FLASH` | Google | `gemini-2.0-flash` |

- Groq 모델: `GROQ_API_KEY` 환경변수 필요.
- Gemini 모델: `GOOGLE_API_KEY` 환경변수 필요.

---

## 5. Engine Architecture

### 5.1 모드 전환

```python
from backtest.engine import EngineConfig
from providers.base import ProviderMode
from engine_factory import create_engine

config = EngineConfig(
    symbol="KRW-BTC",
    style="balanced",
    user_prompt="비트코인 균형 매매",
    mode=ProviderMode.BACKTEST,   # ← REAL 로 바꾸면 실거래
)
engine = create_engine(config)    # BacktestEngine 또는 LiveEngine
await engine.run(config)
```

`EngineConfig` (Pydantic `BaseModel`):
- `symbol`, `style`, `user_prompt` — 필수
- `mode` — `ProviderMode.BACKTEST` (기본) | `ProviderMode.REAL`
- `initial_cash` — gt=0 검증, 기본 10,000
- `interval` — 캔들 단위, 기본 "day"
- `candle_count` — gt=0, 기본 200
- `window_size` — gt=0, 기본 50

### 5.2 공유 그래프 (`core/graph.py`)

- `build_meerkat_graph()` — Meerkat LangGraph 생성
- `run_meerkat(user_prompt, symbol, style, session_id)` → `(strategy_id, strategy_dict)`
- `fetch_ohlcv(symbol, interval, count)` → `list[dict]`

BacktestEngine과 LiveEngine 모두 이 함수들을 사용한다.

### 5.3 BacktestEngine (`backtest/engine.py`)

흐름:
1. `run_meerkat()` → 전략 확보
2. `fetch_ohlcv()` → 과거 OHLCV 전체 로드
3. `MongoAssetProvider.initialize_session()` → 가상 자산 초기화
4. 봉 단위 루프: Owl 판단 → 포트폴리오 업데이트 → DB 기록
5. `BacktestResult` 반환 → `BacktestReporter`가 KPI 산출

트랜잭션 헬퍼: `execute_buy()`, `execute_sell()` (공개 함수)

### 5.4 LiveEngine (`live/engine.py`)

흐름:
1. `run_meerkat()` → 전략 확보
2. `UpbitAssetProvider` 연결
3. 무한 루프: 최신 N봉 로드 → Owl 판단 → 실주문 실행 → DB 기록 → 대기

### 5.5 KPI Reporter (`backtest/reporter.py`)

`BacktestReporter.compute_kpis()`:
- 수익률 (profit_rate)
- 승률 (win_rate)
- 샤프 지수 (sharpe_ratio, 연환산 √252)
- 최대 낙폭 MDD (max_drawdown)

---

## 6. Owl Decision Model (`agents/owl_director/decision.py`)

```python
class OwlAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

class OwlDecision(BaseModel):
    action: OwlAction
    confidence: float       # 0.0 ~ 1.0, Pydantic Field(ge=0.0, le=1.0)
    reasoning: str
```

- LLM 인스턴스는 모듈 레벨 lazy singleton으로 재사용 (매 호출마다 생성하지 않음).
- JSON 파싱 실패 시 안전하게 HOLD 처리.

---

## 7. 데이터 모델 통일 규칙

- **DB 스키마 + 엔진 설정 + 반환 객체**: 모두 Pydantic `BaseModel` 사용.
- **Enum**: `ProviderMode(str, Enum)`, `TradeAction(str, Enum)`, `OwlAction(str, Enum)`, `CollectionName(StrEnum)`, `LLMModel(StrEnum)`.
- **LangGraph State**: `TypedDict` (LangGraph 호환 유지).
- `dataclass`는 사용하지 않는다.

---

## 8. Implementation Checklist

- [x] MongoDB 스키마 정의 (`StrategyDocument`, `TradeLogDocument`, `AssetStateDocument`)
- [x] `AssetProvider` ABC + `MongoAssetProvider` + `UpbitAssetProvider`
- [x] OHLCV 도구 (업비트 Open API, `get_ohlcv_tool`)
- [x] DB 도구 (`find_existing_strategy`, `save_backtest_strategy`, `update_strategy_performance`)
- [x] Meerkat Scanner 에이전트 (LangGraph 노드 + 프롬프트)
- [x] Owl Director 의사결정 (`owl_decide()`)
- [x] BacktestEngine + BacktestReporter
- [x] LiveEngine (실거래 무한 루프)
- [x] 팩토리 패턴 (`engine_factory.py`)
- [x] 공유 DB 연결 (단일 클라이언트)
- [x] 공용 상수 / 그래프 빌더 추출 (`core/`)
- [x] Pydantic BaseModel / Enum 전역 통일
- [x] 안전성 개선 (EngineConfig 유효성 검증, LLM singleton, 연결 관리)

---

## 9. Constraints & Notes

- 모든 코드는 Python으로 작성하며, 비동기 처리를 기본으로 한다.
- 에이전트의 판단 근거(Reasoning)는 항상 로그로 남긴다.
- 전략 수정 시 "왜 수정하는지"에 대한 분석 결과가 `StrategyRevision`에 기록된다.
- MongoDB 연결은 `db.connection` 모듈을 통해 공유한다. 개별 모듈에서 `AsyncIOMotorClient`를 생성하지 않는다.
- 앱 종료 시 `await close_connection()`을 호출하여 연결을 정리한다.
- `EngineConfig`에는 Pydantic 유효성 검증이 적용되어 있다 (`initial_cash > 0`, `candle_count > 0`, `window_size > 0`).

---

## 10. 환경 설정

### .env 파일

```
MONGO_URL=mongodb://localhost:27017
GROQ_API_KEY=<your-groq-api-key>               # 기본 LLM (Groq 무료 티어)
GOOGLE_API_KEY=<your-gemini-api-key>            # Gemini 모델 사용 시
UPBIT_ACCESS_KEY=<your-upbit-access-key>        # 실거래 모드에서만 필요
UPBIT_SECRET_KEY=<your-upbit-secret-key>        # 실거래 모드에서만 필요
```

### Docker

```bash
docker-compose up -d   # MongoDB(magpie-nest:27017) + Redis(hamster-wheel:6379)
```

### 실행

```bash
# 백테스트
uv run python backtest_main.py

# 실거래
uv run python live_main.py

# Telegram 챗봇 모드 (Owl Director)
uv run python main.py
```