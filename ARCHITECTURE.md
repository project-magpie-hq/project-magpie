# 🪶 Project Magpie — Architecture Document

이 문서는 Project Magpie의 LangGraph 그래프 구조, 에이전트 역할, 도구(Tool) 명세를 상세하게 설명합니다.

---

## 📐 LangGraph 그래프 구조

```
[START]
   │
   ▼
┌─────────────────────────────────┐
│         owl_director            │  ← 사용자 입력 수신 / 전략 설계 / 도구 호출 판단
└─────────────────────────────────┘
   │
   ▼  owl_router() 함수가 tool_calls 내용을 검사하여 분기
   │
   ├──► "meerkat_scanner"  ──► [meerkat_scanner_node]
   │         (request_chart_analysis 호출 시)       │
   │                                                │ ToolMessage 반환
   │                                                ▼
   │                                         [owl_director]
   │
   ├──► "tools"  ──► [ToolNode]
   │     (register_strategy 등 일반 도구 호출 시)    │
   │                                                ▼
   │                                         [owl_director]
   │
   └──► END
         (tool_calls 없음 → 사용자에게 메시지 전달 완료)
```

### 노드(Node) 목록

| 노드 ID           | 함수                    | 역할                                                                 |
|-------------------|-------------------------|----------------------------------------------------------------------|
| `owl_director`    | `owl_node()`            | 사용자 메시지를 받아 LLM이 응답 생성. 도구 호출 여부 및 종류 결정    |
| `meerkat_scanner` | `meerkat_scanner_node()`| 기술적 지표 계산 + LLM 해석. 분석 결과를 ToolMessage로 반환         |
| `tools`           | `ToolNode([...])`       | LangChain 내장 도구 실행기. `register_strategy` 등 일반 도구 처리   |

### 엣지(Edge) 흐름

| 출발 노드         | 도착 노드         | 조건                                |
|-------------------|-------------------|-------------------------------------|
| `START`           | `owl_director`    | 항상 (그래프 진입점)                |
| `owl_director`    | `meerkat_scanner` | `request_chart_analysis` 툴 호출   |
| `owl_director`    | `tools`           | 그 외 toolcall (register_strategy 등)|
| `owl_director`    | `END`             | tool_calls 없음 (응답 완료)         |
| `meerkat_scanner` | `owl_director`    | 항상 (분석 결과 전달 후 복귀)       |
| `tools`           | `owl_director`    | 항상 (도구 실행 완료 후 복귀)       |

### 라우터: `owl_router()`

`owl_director` 노드 이후에 실행되는 커스텀 라우팅 함수입니다.

```python
# main.py
def owl_router(state: dict) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        for tc in last_message.tool_calls:
            if tc["name"] == "request_chart_analysis":
                return "meerkat_scanner"   # 차트 분석 → Meerkat Scanner
        return "tools"                     # 기타 도구 → ToolNode
    return END                             # 도구 없음 → 대화 종료
```

### 상태(State): `MagpieState`

```python
# state/magpie_state.py
class MagpieState(TypedDict):
    messages: Annotated[list, add_messages]
```

`add_messages` reducer를 사용하여 모든 메시지를 누적합니다.
`MemorySaver` 체크포인터로 `thread_id` 기반 대화 컨텍스트를 유지합니다.

---

## 🤖 에이전트(Agent) 명세

### 🦉 Owl Director

| 항목         | 내용                                                             |
|--------------|------------------------------------------------------------------|
| **파일**     | `agents/owl_director/owl_director.py`                           |
| **모델**     | `gemini-2.5-flash` (temperature=0.2)                            |
| **역할**     | 사용자 자연어 요청을 구체적인 매매 전략 JSON으로 번역, 대화 총괄 |
| **프롬프트** | `agents/owl_director/owl_director_prompt.md`                    |
| **바인딩 도구** | `register_strategy`, `request_chart_analysis`                |

**동작 흐름**
1. 사용자 자연어 → 전략 초안 브리핑 후 피드백 수집
2. 사용자 최종 승인 → `register_strategy` 호출로 DB에 JSON 전략 등록
3. 차트/지표 분석 요청 → `request_chart_analysis` 호출 → Meerkat Scanner 위임
4. Meerkat Scanner 결과 수신 → 사용자에게 요약 전달

---

### 🦔 Meerkat Scanner

| 항목         | 내용                                                               |
|--------------|--------------------------------------------------------------------|
| **파일**     | `agents/meerkat_scanner/meerkat_scanner.py`                       |
| **모델**     | `gemini-2.5-flash` (temperature=0.3)                              |
| **역할**     | 기술적 지표 계산 및 트레이딩 관점 심층 해석                        |
| **프롬프트** | `agents/meerkat_scanner/meerkat_scanner_prompt.md`                |
| **입력**     | `request_chart_analysis` 툴 호출에서 추출한 `ticker/interval/period` |
| **출력**     | `ToolMessage` (분석 보고서 텍스트)                                 |

**동작 흐름**
```
1. state["messages"]에서 가장 최근 request_chart_analysis 툴 호출 추출
      → (tool_call_id, ticker, interval, period)
2. calculate_technical_indicators.invoke() 호출
      → yfinance 데이터 수집 + ta-lib 지표 수치 계산
3. Meerkat Scanner LLM이 수치를 트레이딩 관점으로 해석
      → 보고서 생성 (종목 요약 / 개별 지표 / 종합 신호 / 시나리오)
4. ToolMessage로 래핑하여 반환
      → Owl Director가 수신하여 사용자에게 자연어 전달
```

**분석 보고서 형식**
1. **종목 요약** — 현재가 & 시장 상황 한 줄 요약
2. **개별 지표 해석** — 각 지표 수치의 의미
3. **종합 신호 판단** — 매수 우위 / 매도 우위 / 중립 / 횡보
4. **트레이딩 시나리오** — 강세/약세 시나리오별 목표가·지지선
5. **주의사항** — 분석 한계 및 추가 확인 사항

---

## 🛠️ 도구(Tool) 명세

### `tools/db_tools.py`

#### `register_strategy`

```python
@tool
def register_strategy(strategy_json: dict) -> str
```

| 항목   | 내용                                                        |
|--------|-------------------------------------------------------------|
| **용도** | 사용자가 최종 승인한 매매 전략을 DB(The-Nest)에 등록      |
| **호출자** | Owl Director (사용자 승인 후)                           |
| **입력** | `strategy_json: dict` — LLM이 설계한 전략 JSON 딕셔너리 |
| **출력** | `"투자 전략 등록이 성공적으로 완료되었습니다."`          |
| **처리** | 현재는 콘솔 출력 (실제 DB 연결 시 Motor/MongoDB 연동 예정)|

**전략 JSON 예시**
```json
{
  "target": "BTC-USD",
  "timeframe": "4h",
  "entry_condition": {
    "rsi_below": 40,
    "macd_crossover": true,
    "ema_alignment": "bullish"
  },
  "exit_condition": {
    "take_profit_pct": 8.0,
    "stop_loss_pct": 3.0
  },
  "position_size_pct": 20
}
```

---

### `tools/market_tools.py`

#### `get_ticker_ohlcv`

```python
@tool
def get_ticker_ohlcv(ticker: str, interval: str = "1d", period: str = "3mo") -> str
```

| 항목     | 내용                                                                    |
|----------|-------------------------------------------------------------------------|
| **용도** | yfinance를 통해 특정 종목의 OHLCV 틱 데이터를 조회하여 텍스트로 반환  |
| **입력** | `ticker` (종목 코드), `interval` (봉 주기), `period` (조회 기간)      |
| **출력** | 총 봉 수 및 최근 20개 봉의 OHLCV 데이터 표                            |
| **지원 interval** | 1m, 5m, 15m, 30m, 1h, 1d, 1wk, 1mo 등                      |
| **지원 period** | 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max                        |
| **참고** | 단기 interval(1m~30m)은 최근 7일, 1h~90m은 최근 60일 내 데이터만 제공 |

**지원 종목 예시**
- 미국 주식: `AAPL`, `TSLA`, `NVDA`, `SPY`
- 국내 주식: `005930.KS` (삼성전자), `000660.KS` (SK하이닉스)
- 암호화폐: `BTC-USD`, `ETH-USD`, `SOL-USD`
- ETF: `QQQ`, `TQQQ`, `KODEX200.KS`

---

#### `calculate_technical_indicators`

```python
@tool
def calculate_technical_indicators(ticker: str, interval: str = "1d", period: str = "1y") -> str
```

| 항목     | 내용                                                                 |
|----------|----------------------------------------------------------------------|
| **용도** | yfinance 데이터 + ta-lib으로 주요 기술적 지표를 계산하고 수치 반환 |
| **입력** | `ticker`, `interval`, `period` (EMA200 계산 위해 최소 200개 봉 필요)|
| **출력** | 각 지표의 최신 수치 및 1차 해석 포함 포맷된 텍스트                  |
| **호출자** | Meerkat Scanner 내부에서 직접 호출                               |

**계산 지표 목록**

| 지표                   | 파라미터                    | 해석 기준                             |
|------------------------|-----------------------------|---------------------------------------|
| **RSI** (상대강도지수) | 기간=14                     | >70 과매수, <30 과매도                |
| **MACD**               | 단기=12, 장기=26, 시그널=9  | MACD > Signal: 골든크로스 (상승 신호) |
| **볼린저밴드**         | 기간=20, 표준편차=2σ        | 현재가 상단 돌파/하단 이탈 여부       |
| **EMA** (지수이동평균) | 20/50/200                   | 정배열(EMA20>50>200) = 상승 추세      |
| **스토캐스틱**         | %K=14, %D 슬로우=3          | >80 과매수, <20 과매도                |
| **ADX** (추세강도)     | 기간=14                     | >25 강한 추세, <25 횡보               |

---

#### `request_chart_analysis`

```python
@tool
def request_chart_analysis(ticker: str, interval: str = "1d", period: str = "1y") -> str
```

| 항목     | 내용                                                                              |
|----------|-----------------------------------------------------------------------------------|
| **용도** | Owl Director → Meerkat Scanner 핸드오프 시그널 도구                             |
| **호출자** | Owl Director (사용자가 차트·지표·매매 타이밍 분석 요청 시)                   |
| **동작** | 툴 자체는 시그널만 반환. 실제 분석은 `owl_router`가 `meerkat_scanner_node`로 라우팅하여 실행 |
| **반환** | `"{ticker} 차트 분석 요청이 Meerkat Scanner에게 전달되었습니다."`               |

> **설계 의도:** LangChain `@tool`은 LLM이 "어떤 도구를 호출할지" 결정하는 인터페이스입니다.  
> `request_chart_analysis`가 호출되면 `owl_router()`가 이를 감지하여 그래프 흐름을 `meerkat_scanner` 노드로 전환합니다.  
> 실질적인 데이터 수집·계산·해석은 `meerkat_scanner_node()` 내부에서 수행됩니다.

---

## 📁 프로젝트 디렉토리 구조

```
project-magpie/
├── main.py                          # LangGraph 그래프 정의 및 실행 엔트리포인트
├── pyproject.toml                   # 의존성 관리 (uv)
├── docker-compose.yml               # MongoDB(The-Nest), Redis(Hamster-wheel) 인프라
├── README.md                        # 프로젝트 소개 및 개발 환경 세팅 가이드
├── ARCHITECTURE.md                  # 이 문서 (아키텍처 상세 명세)
│
├── state/
│   └── magpie_state.py              # LangGraph 공유 상태 스키마 (MagpieState)
│
├── agents/
│   ├── owl_director/
│   │   ├── owl_director.py          # Owl Director 노드 함수 & LLM 체인
│   │   └── owl_director_prompt.md  # Owl Director 시스템 프롬프트
│   │
│   └── meerkat_scanner/
│       ├── meerkat_scanner.py       # Meerkat Scanner 노드 함수 & LLM 체인
│       └── meerkat_scanner_prompt.md # Meerkat Scanner 시스템 프롬프트
│
└── tools/
    ├── db_tools.py                  # register_strategy (전략 DB 저장)
    └── market_tools.py              # get_ticker_ohlcv, calculate_technical_indicators,
                                     # request_chart_analysis (시장 데이터 & 지표)
```

---

## 🔗 의존성

| 패키지                    | 용도                                          |
|---------------------------|-----------------------------------------------|
| `langgraph`               | 멀티에이전트 그래프 오케스트레이션            |
| `langchain-core`          | Tool, Message, Prompt 추상화                  |
| `langchain-google-genai`  | Gemini 모델 연동 (`gemini-2.5-flash`)         |
| `yfinance`                | 글로벌 주식·ETF·암호화폐 시장 데이터 수집    |
| `ta-lib`                  | 기술적 지표 계산 (TA-Lib C 라이브러리 바인딩) |
| `pandas`                  | OHLCV 데이터 처리                             |
| `motor`                   | MongoDB 비동기 드라이버 (The-Nest 연동)       |
| `redis`                   | Redis 클라이언트 (Hamster-wheel 연동)         |
| `python-dotenv`           | 환경 변수 관리                                |
