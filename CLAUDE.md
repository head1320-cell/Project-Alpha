# Project Alpha — 한국 주식 퀀트 플랫폼

> 이 파일은 Claude Code가 프로젝트 맥락을 파악하기 위해 자동으로 읽습니다.
> 새 세션을 시작할 때 이 문서 + `PLATFORM_EVOLUTION.md`를 먼저 읽으면 전체 맥락을 이어받습니다.

---

## 한 줄 요약

FastAPI(백엔드) + Next.js 14(프론트엔드) + PostgreSQL + Docker 기반의 한국 주식 퀀트
**스크리닝 → 분석 → 백테스트 → 자동매매** 통합 플랫폼. 개발 환경은 **Windows**.

---

## 환경 (Windows 기준)

- OS: **Windows** (PowerShell 또는 명령 프롬프트)
- Python 3.10+ 권장, Node.js 18+ 권장
- 명령어는 모두 Windows 기준으로 안내 (경로 구분자 `\`, 가상환경 `venv\Scripts\activate`)

---

## 아키텍처

```
ficc-platform/
├─ main_api.py              # FastAPI 진입점 (106 endpoints, 포트 8000)
├─ requirements.txt         # Python 의존성
├─ verify_connection.py     # DART/KIS 실데이터 연동 검증 스크립트
├─ docker-compose.yml       # db(5432) + backend(8000) + frontend(3000)
├─ .env.example             # 환경변수 템플릿 (복사해서 .env로)
├─ src/
│  ├─ engine/               # 스크리너 핵심
│  │  ├─ filter_ast.py       # 13종 필터 kind + 49 field 카탈로그
│  │  ├─ screener.py         # ValuationScreener (3-레이어 실행)
│  │  ├─ analyzers.py        # M7(다중공선성) M8(스트레스) 후처리
│  │  ├─ trading_engine.py   # ★자동매매 오케스트레이터 + 6중 안전장치
│  │  ├─ screener_presets.py # 22개 프리셋 (10개 학술 전략)
│  │  └─ ...
│  ├─ data/                 # 데이터 계층
│  │  ├─ dart_client.py      # DART 재무제표 (실데이터/mock)
│  │  ├─ market_data.py      # KIS 시세 + 27개 기술지표
│  │  ├─ fundamentals_store.py  # 35개 학술 펀더멘털 팩터
│  │  ├─ stock_master.py     # ★종목명 단일 진실 공급원 + 데이터 품질 검증
│  │  ├─ ohlcv_loader.py     # 백테스트 OHLCV 통합 로더 (DB→KIS→mock)
│  │  └─ ...
│  ├─ execution/
│  │  └─ kis_client.py       # KIS 증권 API (주문/잔고/시세, OAuth)
│  ├─ kis_order_executor.py  # 주문 실행기
│  ├─ kis_backtest_engine.py # 백테스트 엔진
│  └─ api/
│     ├─ screener_routes.py  # 스크리너 API (+ 백테스트 브릿지, 데이터 품질)
│     └─ trading_routes.py   # ★자동매매 API (5 endpoints)
└─ frontend/
   └─ src/
      ├─ components/screener/
      │  ├─ FilterBuilder.tsx    # 3단 빌더 (메인 UI)
      │  ├─ AnalyzerPanel.tsx    # M7/M8 분석
      │  ├─ BacktestPanel.tsx    # 백테스트 패널
      │  ├─ LiveTradingPanel.tsx # ★자동매매 패널
      │  └─ DataQualityPanel.tsx # ★데이터 품질 패널
      └─ lib/screenerApi.ts      # API 클라이언트 (모든 fetch)
```

---

## 스크리너 V3 핵심 (★절대 깨뜨리지 말 것★)

3-레이어 아키텍처: **유동성 게이트 → 13종 필터 kind → 후처리 analyzer**

- **13 kind**: `field` | `formula` | `peer` | `technical` | `event` | `estimate` | `z_score` | `behavioral` | `graph` | `sentiment` | `vector_sim`
- **49 field**: 기본 14개 + 학술 펀더멘털 팩터 35개
  - 펀더멘털 팩터(GP/A·Altman Z·Piotroski F·QMJ·Magic Formula 등)는 **전부 `field` kind**로 통합됨 → 아키텍처 변경 없이 추가됨
- **22개 프리셋**: 거장 전략 + 10개 학술 논문 전략 (Novy-Marx, Greenblatt, Carlisle, Faber, Asness 등)
- **27개 기술지표**: 백테스터와 동일한 `kis_indicators` 공식 재사용

### 중요한 불변식 (깨지면 안 됨)
- `filter_ast.py`의 `FIELD_BY_ID`는 49개 (펀더멘털 35개가 `_register_fundamental_fields()`로 자동 등록)
- 새 필터 kind 추가 시 `validate()`의 field-check-bypass 튜플에 등록 필수
- 종목명은 `stock_master.py`의 `get_stock_name()`이 단일 진실 공급원 → **"Unknown Corp" 금지**

---

## 실데이터 연동 (DART + KIS)

`.env`에 키를 넣으면 **자동으로 실데이터**, 없으면 mock fallback (코드 수정 불필요).

| 환경변수 | 의미 |
|---|---|
| `DART_API_KEY` | DART 재무제표 (있으면 35개 펀더멘털 팩터 실데이터화) |
| `KIS_USE_MOCK` | `1`=mock(기본), `0`=실제 KIS 호출 |
| `KIS_IS_PAPER` | `1`=모의투자, `0`=실계좌(⚠ 실제 자금) |
| `KIS_APP_KEY` / `KIS_APP_SECRET` / `KIS_ACCOUNT_NO` | KIS 인증 |

검증: `python verify_connection.py` (자세한 건 `REAL_DATA_SETUP.md`)

---

## 완성된 기능 (4대 우선순위 전부 완료)

1. **실데이터 연동** — DART(재무) + KIS(시세), 키만 넣으면 작동
2. **실데이터 백테스트** — `ohlcv_loader.py`(DB→KIS→mock) + 스크리너→백테스터 원클릭
3. **실거래 자동매매** — `trading_engine.py`, 6중 안전장치(Kill Switch·손실한도·주문상한·일일한도·포지션제한·Dry-run 기본)
4. **데이터 인프라 QA** — `stock_master.py`(종목명 100% 해소) + 데이터 품질 검증

전체 진행 이력은 **`PLATFORM_EVOLUTION.md`**에 V1~V3 + 4대 우선순위가 기록됨.

---

## 개발 규칙 (★작업 시 반드시 준수★)

### 1. 변경 후 검증 (필수)
프론트엔드를 수정했다면 **반드시** 아래를 통과시킬 것:
```powershell
cd frontend
npx tsc --noEmit          # TypeScript 0 errors 여야 함
npx next build            # 14/14 pages 성공해야 함
cd ..
```
- `/screener` 페이지가 빌드되는지 확인 (~32kB)

### 2. 백엔드 검증
```powershell
python -c "import sys; sys.path.insert(0,'.'); from src.engine.screener import ValuationScreener; print('OK')"
```

### 3. mock 모드가 기본
- `KIS_USE_MOCK=1`이면 외부 호출 없이 deterministic mock으로 동작 (개발 기본값)
- 실데이터/실거래 테스트는 `.env` 설정 + `verify_connection.py` 후에만

### 4. 실거래 안전 (★최우선★)
- 자동매매는 **기본이 `dry_run=True`** (실주문 없이 시뮬)
- `dry_run=false` + `real` 모드 = **실제 자금 거래** → 반드시 모의투자(`KIS_IS_PAPER=1`)에서 충분히 검증 후 사용
- `trading_engine.py`의 6중 안전장치를 우회하는 코드 작성 금지

### 5. 종목명
- 항상 `stock_master.py`의 `resolve_name()` / `get_stock_name()` 사용
- "Unknown Corp" 또는 가짜 종목코드(100000~) 재도입 금지

### 6. 자주 커밋
- 기능 단위로 작은 커밋. 문제 생기면 `git revert`로 복구

---

## 빌드 & 실행 (Windows)

### 최초 1회 셋업
```powershell
# 1) Python 가상환경 (권장)
python -m venv venv
venv\Scripts\activate

# 2) Python 의존성 설치
#    torch가 무거우니, 먼저 가벼운 핵심만 설치해도 스크리너는 동작:
pip install fastapi uvicorn pydantic pandas numpy requests httpx python-dotenv sqlalchemy scikit-learn
#    전체 설치 (torch 포함 — 시간 걸림):
pip install -r requirements.txt

# 3) 프론트엔드 의존성
cd frontend
npm install
cd ..
```

### 개발 서버 실행 (터미널 2개)
```powershell
# 터미널 1 — 백엔드 (포트 8000)
venv\Scripts\activate
uvicorn main_api:app --reload --port 8000

# 터미널 2 — 프론트엔드 (포트 3000)
cd frontend
npm run dev
```
브라우저: `http://localhost:3000` → 스크리너 탭

### Docker로 전체 실행 (선택)
```powershell
docker compose up --build -d
docker compose logs -f backend
```

### 실데이터 검증 (키 설정 후)
```powershell
copy .env.example .env
notepad .env            # DART_API_KEY, KIS 키 입력, KIS_USE_MOCK=0
python verify_connection.py
```

---

## 알려진 제약 / 주의

- `torch>=2.0.0`이 requirements.txt에 있음 — Windows에서 설치가 느리거나 실패하면, 스크리너 핵심은 torch 없이도 동작하므로 위의 "가벼운 핵심만 설치"로 시작 가능 (torch는 일부 고급 기능에서만 사용)
- `node_modules`는 ZIP에 없음 → `npm install` 필요 (~수십 초)
- `.env`는 **절대 git에 커밋 금지** (`.gitignore`에 포함돼 있음)
- 이전 개발은 Linux sandbox에서 진행됨 → Windows에서 경로/줄바꿈 이슈가 보이면 알려줄 것

---

## 다음 작업 후보 (참고)

4대 우선순위 완료 후 가능한 방향:
- **실데이터 검증**: `verify_connection.py`로 실제 DART/KIS 데이터 흐름 확인 → 모의투자 전체 흐름 테스트
- **자동매매 고도화**: 정기 실행 스케줄러(매일 장 시작 전 리밸런싱), 주문 추적 대시보드, 포트폴리오 성과 추적
- **데이터 인프라 강화**: 매크로 데이터(BOK/FRED) 실연동, 캐싱 전략 일원화

---

## 첫 세션 추천 시작 멘트

> "CLAUDE.md와 PLATFORM_EVOLUTION.md를 읽고 현재 상태를 파악해줘.
> 그다음 `cd frontend && npx tsc --noEmit`로 빌드가 정상인지 확인해줘."

---

## 디자인 시스템 — Variant "Institutional Terminal" (적용됨)

플랫폼 UI가 Variant 시안 기반 "Institutional Terminal" 디자인으로 전환됨.

### 디자인 토큰 (globals.css)
- 폰트: Geist(본문) + JetBrains Mono(숫자/메타)
- 색: accent #1200ff, ink #111111, muted #71717a, border #e5e5e5, surface #fafafa
- radius: 2px (각진 터미널 느낌)

### 셸 (components/layout/TerminalShell.tsx)
- 좌측 사이드바: 5개 모듈 (01 Screener, 02 Backtester, 03 Macro, 04 Company, 05 Risk)
- 활성 탭에 좌측 3px #1200ff 액센트 바
- 상단: 로고 + Quick Search(⌘K) + Institutional Terminal 계정
- 사이드바 하단: SYSTEM OPERATIONAL 상태
- main 영역: 코너마크 4개 + 그리드 오버레이
- layout.tsx가 TerminalShell로 모든 페이지를 감쌈 (기존 TopNav 대체)

### 스크리너 (완성 — components/screener/TerminalScreener.tsx)
- Variant 3-pane: 카테고리 → 빌더(필드 클릭으로 조건 추가) → 활성 필터 스택 + 라이브 카운트
- EXECUTE SCAN → 결과 테이블 (Ticker/Company/PE/PBR/ROE/Alpha Score/Verdict)
- 실제 screenerApiAdvanced 데이터 연결

### 5개 탭 전부 터미널 스타일 완료 ✅
- **Screener** (components/screener/TerminalScreener.tsx) — 3-pane, 라이브 카운트, 결과 테이블
- **Backtester** (app/backtest/page.tsx) — 상단 모드 전환기로 2개 워크플로우 통합:
  - **전략 실행 (Execution)**: TerminalBacktester — 설정 패널 + 5개 지표 카드 + 자산곡선 + 구성종목. screen-to-backtest 브릿지 (run ~15초, 로딩 스피너)
  - **전략 설계 (Builder)**: BuilderPanel (components/backtest/BuilderPanel.tsx) — 비주얼 빌더/DSL/YAML/라이브러리/노드캔버스 5개 하위탭. 지표 조합으로 전략 설계 → 실시간 YAML 생성
  - 구 /builder 라우트는 /backtest로 리다이렉트됨
  - **전략 카탈로그 통합 (lib/builder/strategyCatalog.ts)**: 기성 10종 전략을 backendId↔builderState로 매핑. 양방향 워크플로우:
    - 실행→설계: 드롭다운 옆 "전략 설계에서 편집" → 해당 전략이 빌더로 로드됨
    - 설계→실행: 연결 배너의 "이 전략 실행하기" → 빌더 전략이 기성과 매칭되면 실행 모드로 그 전략 선택해 복귀
    - 빌더 상단 기성 전략 칩 10개로 즉시 로드/교체 가능
    - Zustand store(useBuilderStore)로 두 모드가 상태 공유
  - **커스텀 전략 실행 파이프라인 (신규)**:
    - 백엔드: src/kis_strategies/dsl_strategy.py — DslStrategy가 BuilderState(지표+진입/청산 조건)를 런타임 해석 (codegen/exec 없이 안전). get_strategy("__custom__", spec=...)로 생성
    - kis_indicators 25종 지표 지원 (sma/ema/rsi/macd/bb/atr/cci/adx 등)
    - 연산자: greater_than/less_than/cross_above/cross_below 등
    - API: screen-to-backtest에 strategy_name="__custom__", strategy_params={spec:BuilderState} 전달 (백엔드 변경 없이 기존 엔드포인트 재사용)
    - 프론트: components/backtest/CustomBacktestRunner.tsx — 커스텀 전략 백테스트 UI (기성과 동일 레이아웃)
    - 빌더에서 커스텀 전략 설계 → "이 전략 실행하기" → CustomBacktestRunner → DslStrategy 실행
    - backtestBridgeApi.customBacktest(spec) 메서드
- **Macro** (app/macro/page.tsx) — 4-quadrant 국면도 + 실제 지표. /api/v1/macro/regime
- **Company** (app/insights/page.tsx) — 헤더 + 메트릭바 + RIM/DCF/DDM 내재가치 + 점수분해. 종목코드 입력→스크리너 lookup
- **Risk** (app/risk-tools/page.tsx) — 시나리오 버튼 + 생존율 + 스트레스 취약종목 테이블. stress_test analyzer

### 데이터 연결 (analysisApi in screenerApi.ts)
- macroRegime() → /api/v1/macro/regime
- companyLookup(universe, code) → run-advanced에서 종목 추출 (limit 200, liquidity relaxed)
- stressTest(universe, scenario) → run-advanced + stress_test analyzer
- stressScenarios() → /api/v1/screener/stress-scenarios
- backtestBridgeApi.screenToBacktest() → /api/v1/screener/screen-to-backtest

### 주의 (mock 모드)
- mock에서는 market_cap_억이 None → 유니버스 필터는 per>0 사용 (시총 필터 쓰면 0종목)
- run-advanced limit 최대 200 (초과 시 422)

### 남은 다듬기 후보
- 나머지 라우트(/builder /derivatives /admin/* /strategy /portfolio /dashboard)는 기존 PageHeader+container 사용 → 셸 안에서 작동하나 톤 불일치. 필요시 같은 패턴으로 재구성
- StockDetail 패널(스크리너 우측)도 터미널 톤으로 통일 가능
- 실데이터(DART/KIS) 연결 시 verify_connection.py로 검증 후 시총 필터 사용 가능

---

## 🔧 P0 안정화 (배포 준비도 개선)

이전의 치명적 문제 2가지를 해결함.

### P0-1: torch를 선택적(optional) 의존성으로 전환 ✅
- **문제**: main_api.py가 최상단에서 torch를 무조건 import → torch 미설치 시 전체 API 다운
- **해결**:
  - `src/models/lstm_engine.py`: torch import를 try/except로 감싸 `TORCH_AVAILABLE` 플래그 + `_require_torch()` 가드. `from __future__ import annotations`로 타입힌트 lazy화. `class LSTMVolNet(_TorchModuleBase)` (torch 없으면 object 상속)
  - `main_api.py`: 최상단 lstm import 제거 → 2개 엔드포인트(`/ai-vol-compare`, `/lstm-forecast`) 내부에서 lazy import + torch 없으면 HTTP 503
- **검증**: torch 없이 main_api가 183개 라우트로 정상 기동. LSTM 호출 시에만 친절한 503, 나머지 전부 정상

### P0-2: requirements.txt 정리 + test_api.py 복구 ✅
- **문제**: test_api.py 167개 테스트가 bcrypt/yfinance/torch 누락으로 수집 단계 실패. requirements에 torch가 핵심처럼 섞여 있음
- **해결**:
  - requirements.txt 재구성: 핵심(CORE)/선택(OPTIONAL) 명확히 구분. torch는 주석 처리된 OPTIONAL 섹션으로. 누락됐던 PyJWT, python-multipart 추가
  - test_api.py: `TestLSTMUnit`에 `@pytest.mark.skipif(not _TORCH_OK)` → torch 없으면 실패가 아니라 skip
- **검증**: `pytest tests/` → **228 passed, 10 skipped, 0 failed** (이전: 167개 수집 실패)
  - test_api.py: 157 passed, 10 skipped
  - test_quant_models.py: 71 passed

### 배포 가이드 (Windows)
```
pip install -r requirements.txt              # 핵심만 (권장, 빠름) → API 정상 작동
pip install -r requirements.txt torch>=2.0.0 # LSTM 기능까지 필요 시
```
torch 없이도 5개 모듈 + 백테스트 + 자동매매 + 파생 전부 작동. LSTM 변동성 예측만 비활성(503).

---

## 🔍 실데이터 검증 전략 (API 키 없이 가능한 부분)

sandbox/CI는 DART/KIS 서버 네트워크가 차단되고(화이트리스트 프록시), 운영에서도 실키를 코드/CI에 넣을 수 없다. 그러나 실데이터 연동의 위험을 둘로 나누면 상당 부분 키 없이 검증된다:

  ① 요청을 올바르게 보내는가 → 실호출 필요 (키+네트워크). verify_connection.py로 사용자가 직접.
  ② 응답을 올바르게 파싱하는가 → 실제 응답 '구조'로 검증 가능. ★ tests/test_realdata_parsing.py ★
  + ①의 '형식 정확성'(URL/헤더/TR_ID/파라미터)도 요청 객체를 가로채 키 없이 검증.

### tests/test_realdata_parsing.py (45개, 키 없이 실행)
- **DART 금액 파싱 (7)**: 쉼표/음수/빈값/공백/가비지/0 → _parse_amount
- **DART 재무제표 매핑 (7)**: 실제 fnlttSinglAcnt.json 구조로 매출/영업이익/순이익/자산/부채/자본. '매출원가'가 revenue로 오매핑되지 않는지, 회계 항등식(자산=부채+자본), 적자기업 음수 처리
- **DART 비율 (3)**: ROE/부채비율 계산 + 적자기업 음수 ROE
- **DART 에러 처리 (2)**: 인증실패/데이터없음 → mock fallback (크래시 안 함)
- **KIS _safe_float (6)**: 쉼표/소수/음수%/빈값
- **KIS 잔고 구조 (3)**: output1(종목별)/output2(요약), 보유 0주 제외
- **KIS 주문 응답 (2)**: rt_cd 성공/실패 감지
- **KIS 시세 (3)**: 현재가/OHLC/등락률, 고가≥현재가≥저가 정합성
- **KIS 주문 요청 구성 (9)**: ★실거래 안전 핵심★ — 실거래 vs 모의 TR_ID 구분(TTTC vs VTTC), 매수/매도 TR_ID, 시장가(01)/지정가(00) 코드, 필수필드(계좌/종목/수량), 엔드포인트 경로, 인증헤더
- **KIS 주문 검증 (3)**: 잘못된 side/0수량/지정가 가격누락 거부

### 실행
```
pytest tests/test_realdata_parsing.py -v    # 키 없이 (파싱+요청구성)
python verify_connection.py                 # 실키로 (실제 도달, 사용자 환경)
```

### 전체 테스트: 283개 (273 passed + 10 skipped)
- test_api.py: 157 + 10 skip(torch)
- test_quant_models.py: 71
- test_realdata_parsing.py: 45 (신규)

---

## 🚀 백엔드 기능 UI 연결 (활용률 개선)

이전엔 스크리너가 백엔드 34개 중 3개만, 백테스터가 입력 4개만 노출. 백엔드의 고급 기능을 UI에 연결함.

### 1. 자연어 검색 (스크리너 nl2ast)
- `components/screener/TerminalScreener.tsx` 상단에 자연어 검색 바 추가
- "부채 적고 배당 높은 방어주" 입력 → `screenerApiAdvanced.nl2ast()` → 필터 AST 자동 생성 → 라이브 카운트
- 예시 칩(nl2astExamples), 해석 배지(AI/규칙 + 신뢰도) 표시
- mock 모드에서도 키워드 룰로 작동 (Claude 키 있으면 정확도↑)

### 2. 백테스터 고급 옵션
- `components/backtest/TerminalBacktester.tsx`에 접이식 고급 옵션 패널
- 수수료(bp)·슬리피지(bp) 슬라이더, 손절%·익절% 입력
- screenToBacktest에 commission_rate/slippage_rate/stop_loss_pct/take_profit_pct 전달 (백엔드 이미 지원)

### 3. 백테스터 확장 결과
- 5개 → 6개 지표 카드 (Calmar 추가)
- 보조 지표 바: 승률·손익비(PF)·평균손익·수수료·슬리피지 (실제 비용)
- Drawdown 곡선 (drawdown_curve, 빨강 낙폭 영역)
- Monthly Returns 히트맵 (monthly_returns, 월별 색코딩)
- Trade Log 테이블 (trades, 최근 15건: 진입/청산일·가격·수익률)
- 모두 screen-to-backtest가 이미 반환하던 데이터 (UI 연결만)

### API 추가 (screenerApi.ts)
- screenerApiAdvanced.nl2ast(query), nl2astExamples()
- screenToBacktest에 commission_rate/slippage_rate/max_positions 파라미터
- 타입: BacktestStatistics에 calmar_ratio/avg_trade_return, BacktestTrade, MonthlyReturn 추가

### 아직 미연결 (선택)
- PIT 백테스트(run-pit), 그래프 검색(graph-search), 센티먼트, 피어그룹, 벡터유사도
- 이들은 UX 설계가 더 필요해 보류. 핵심 워크플로우(자연어+백테스트 완성도)부터 연결함

---

## 🔧 통합 지표 시스템 — 조건 값 편집 + 빌더 재무 operand (완료)

이전에 백엔드의 수많은 지표를 양쪽(스크리너/백테스터)에서 못 쓰던 문제 해결.

### A. 스크리너 — 기술적 지표 통합 (완료)
- 펀더멘털/기술적 토글 + 기술적 지표 28종(5개 카테고리) + 지표 검색 박스
- 백엔드는 이미 kind:"technical"로 지원 → UI 연결만. RSI<30 등 기술 조건이 펀더멘털과 함께 작동
- screenerApiAdvanced.indicators() → /api/v1/screener/indicators

### B. 조건 값 편집 UI (완료)
- TerminalScreener: 정적 칩 → 편집 가능 컨트롤. 연산자 드롭다운(gt/gte/lt/lte/eq) + 값 입력(number)
- rank_mode 조건은 상위/하위 + rank_value 입력. 기술 조건은 tchip-tech 보라 마커
- updateCondition(idx, patch) 핸들러. CSS: tchip-op-select/tchip-input/tchip-unit

### C. 백테스터 빌더 — 재무 operand 통합 (완료)
- **역방향 통합**: 빌더(기술 지표 위주)에서 펀더멘털(ROE/부채비율 등)도 전략 조건으로 사용 가능
- types/builder.ts: ConditionOperandType에 "fundamental" 추가, ConditionOperand.fundamentalField
- ConditionPanel.tsx: operand 타입 선택에 "재무" 추가 + FUNDAMENTAL_FIELDS 5종(ROE/ROA/부채비율/배당수익률/영업이익률 — DART에서 직접 산출 가능한 항목만)
- **백엔드 DslStrategy**: _eval_operand에 fundamental 분기. _uses_fundamental로 사용 감지 시에만 종목 펀더멘털 스냅샷 조회(_load_fundamental_snapshot, 종목당 캐시). DART get_financial_statement→compute_ratios. 미사용 전략은 스냅샷 스킵(빠름)
- PER/PBR/composite_score는 가격·스코어링 필요 → 빌더 재무 operand에서 제외(스크리너에서 사용). 미제공 필드는 None으로 안전 평가
- 검증: ROE>0 + 골든크로스 복합 전략 백테스트 65거래 성공

### 활용률 변화
- 스크리너: 펀더멘털 49 + 기술적 28 (이전 펀더멘털만)
- 백테스터 빌더: 기술 지표 143종(constants) + 펀더멘털 5종 (이전 기술만)
- 양쪽 모두 펀더멘털+기술 혼합 조건 가능

---

## 🔗 스크리너↔백테스터 펀더멘털 통합 (단일 소스)

이전엔 두 시스템이 분리된 펀더멘털 경로를 씀:
- 스크리너: fundamentals_store의 35개 학술 팩터(ROIC/Altman Z/Piotroski F/Magic Formula 등)
- 백테스터: DslStrategy가 DART 직접 호출, 5개 기본 비율만

### 통합 (완료)
- **DslStrategy._load_fundamental_snapshot를 fundamentals_store 기반으로 교체**
  - `FundamentalsStore.get_default().get_factors(stock_code, None)` → 35개 팩터 전부
  - 스크리너와 동일한 소스 → 일관성 + 동일한 키 전환
- **빌더 재무 operand 5개 → 35개로 확장** (ConditionPanel FUNDAMENTAL_GROUPS)
  - 5개 카테고리 optgroup(수익성·품질 8 / 밸류에이션 10 / 성장성 7 / 안전성 7 / 종합 3)
  - 드롭다운이 난잡하지 않게 카테고리 그룹화
- 검증: ROIC>5 + 골든크로스 복합 전략 백테스트 58거래 성공

### DART 키 관련 (중요)
- **키 없이도 35개 팩터 전부 작동** (DeterministicMockStore — 종목별 일관된 mock)
- 키는 "더 많은 지표"가 아니라 "mock 값 → 실제 DART 재무"를 위해 필요
- DART_API_KEY 설정 시 fundamentals_store가 자동으로 실데이터 사용 (코드 변경 불필요)
- 키를 코드/외부에 노출할 필요 없음 — .env에 넣으면 자동 전환

### 결과: 양쪽이 동일한 35개 학술 팩터 공유
- 스크리너: 펀더멘털 35(학술) + 기술 28
- 백테스터 빌더: 기술 143(constants) + 펀더멘털 35(학술, fundamentals_store 공유)

---

## 📊 펀더멘털 팩터 대량 확장 (35 → 64개, DART 원천 파생)

젠포트 수준 팩터 라이브러리를 목표로 1단계: DART 원천에서 파생 팩터 대량 추가 (추가 API 불필요, 무료).

### 추가된 29개 팩터 (src/data/fundamentals_store.py)
- **수익성 심화(9)**: roe, roa, roe_dupont(듀폰분해), ebitda_margin, ocf_to_ni(이익의질), cash_conversion, rnd_intensity, sga_to_revenue, capex_intensity
- **밸류에이션 심화(9)**: per, pbr, ev_ic, dividend_yield, payout_ratio, bps, book_to_market(가치주), ncav_to_mcap(그레이엄 청산가치)
- **성장성 심화(4)**: revenue_qoq, growth_acceleration(성장가속도), sustainable_growth(지속가능성장률), fcf_growth
- **안전성 심화(6)**: net_debt_to_ebitda, cash_ratio, equity_ratio, sloan_accruals, debt_to_assets
- **종합 심화(3)**: graham_number(적정주가), greenblatt_score, value_composite

### 구현 방식
- _mock_raw_financials에 원천 항목 추가 (cash/receivables/rnd/sga/depreciation/tax/전년대차대조표/분기 등)
- _derive_factors에 29개 계산 공식 추가 (학술 출처 명시)
- FUNDAMENTAL_FACTORS 메타에 29개 등록 → 스크리너 fields + 빌더 드롭다운 자동 반영

### 단일 소스 → 양쪽 자동 반영
- 스크리너 필드: 49 → 76개 (fields 카탈로그 자동 확장)
- 백테스터 빌더 재무 드롭다운: **백엔드 fields에서 동적 로드로 전환** (ConditionPanel useFundamentalGroups). 하드코딩 제거 → 팩터 추가 시 UI 자동 반영
- 검증: book_to_market/graham_number 등 신규 팩터로 스크리닝(104종목)+백테스트(50거래) 정상

### 향후 (2~4단계, 별도 데이터 필요)
- KIS 가격 팩터(모멘텀/변동성/베타) + 수급 팩터(외국인·기관 순매수)
- 과거 시계열 DB 적재 (장기 백테스트)
- 컨센서스 팩터(목표주가/EPS추정) — FnGuide/DataGuide 유료 데이터 필요
- ※ 키 없이 mock으로 전부 작동, DART_API_KEY 설정 시 실데이터 자동 전환

---

## 📈 가격·수급 팩터 추가 (2단계 — 재무와 독립적)

KIS OHLCV에서 파생되는 가격·수급 팩터 28개 추가. 재무와 무관한 독립 팩터군이라 팩터 다양성 실질 증가.

### 신규 파일: src/data/price_factors_store.py (28개 팩터)
- **모멘텀(6)**: return_1m/3m/6m/12m, momentum_12_1, momentum_6_1
- **변동성(6)**: volatility_20d/60d, beta_1y, max_drawdown_1y, downside_vol, skewness
- **기술 위치(7)**: price_to_52w_high/low, dist_ma20/60/120, rsi_14, ma_alignment
- **거래(5)**: volume_trend_20d, turnover_rate, amount_20d_avg, volume_spike, price_volume_corr
- **수급(4)**: foreign_net_5d/20d, inst_net_5d/20d (외국인·기관 순매수)

### 구현 (fundamentals_store와 동일 패턴)
- PriceFactorsStore(DeterministicMockStore) — 종목별 일관 mock + KIS OHLCV 실데이터 연결
- _derive_from_ohlcv: 일봉 시계열 → 수익률/변동성/RSI/이격도/거래량 계산 (순수 함수)
- KIS_USE_MOCK=1 또는 키 없으면 mock, 실키 설정 시 get_daily_ohlcv 자동 사용
- beta/turnover/수급은 시장지수·상장주식수·투자자동향 API 필요 → 실데이터 단계에서 채움 (현재 mock)

### 단일 소스 통합 (양쪽 자동 반영)
- filter_ast.py: _register_price_fields()로 FIELD_CATALOG 병합 + 카테고리 라벨 5개 추가
- screener.py: attach_price_factors(items) 추가 (attach_fundamentals 옆)
- dsl_strategy.py: 펀더멘털 스냅샷에 가격 팩터 병합 → 백테스터에서 모멘텀/RSI 등 사용
- ConditionPanel.tsx: 동적 로드 allowed에 momentum/volatility/technical/volume/supply 추가, 라벨 "재무"→"팩터"

### 검증
- 스크리너 필드: 76 → 104개 (14개 카테고리)
- 모멘텀>0 필터 67종목, 외국인순매수+RSI 복합 44종목
- 백테스터: 모멘텀+외국인수급+기술 3중 결합 전략 20거래 성공

### 누적 팩터 현황
- 펀더멘털 64 (DART 원천) + 가격·수급 28 (KIS OHLCV) = 92개 독립 팩터
- 스크리너·백테스터 양쪽에서 재무+가격+수급+기술 자유 결합 가능
- ※ 전부 mock 작동, KIS/DART 키 설정 시 실데이터 자동 전환

---

## 🎨 UI/UX 개선 1차 — 결과 테이블 강화 + 로딩 상태

### 1. 스크리너 결과 테이블 강화 (TerminalScreener.tsx)
- **컬럼 선택기**: "⚙ 컬럼" 버튼 → 92개 팩터(펀더멘털+가격수급) 중 표시할 지표 자유 선택 (tcol-picker, 체크박스 칩)
- **정렬**: 모든 컬럼 헤더 클릭 → 오름/내림 토글 (sortable, ▲▼ 표시). sortCol/sortDir 상태
- **셀 내 히트맵 바**: 각 숫자 셀에 컬럼 min/max 정규화 바 (tcell-fill) → 값의 상대 위치 시각화
- 기본 컬럼: per/pbr/roe_pct/composite_score, 사용자가 추가/제거 가능
- 백엔드: ScreenerItem.to_dict에 PRICE_FACTOR_BY_ID 추가 → run-advanced 결과에 가격팩터 포함 (이전 64 → 112 필드)

### 9. 로딩 상태 (체감 대기 단축)
- **스크리너 스캔**: 스피너 + 스켈레톤 테이블(shimmer 애니메이션). loading && !results 시 표시
- **백테스터**: 정적 스피너 → 5단계 진행 표시(BacktestProgress: 시세로드→지표계산→시그널→시뮬레이션→집계, 3.2초씩 진행) + 6개 지표 카드 스켈레톤 + 차트 스켈레톤
- CSS: tshimmer/tspin/tpulse 애니메이션, tskeleton-*, tbt-stages/tbt-stage

### 검증
- TypeScript 0 errors, 프로덕션 빌드 통과
- 라이브 렌더: 결과 테이블 툴바(컬럼 버튼)+정렬 헤더(SCORE ▼)+히트맵 바 확인
- run-advanced 112 필드 (가격팩터 포함) 확인

---

## 🔀 스크리너 → 백테스터 전략 전달 (역할 분리)

[설계 변경] 스크리너는 "검색"에만 집중, 백테스팅은 백테스터 탭에서. 스크리너 조건식(전략)을 백테스터로 그대로 넘기는 흐름 구축. (스크리너 탭엔 원래 백테스팅 기능 없었음 — 검색 전용 유지하고 전달 다리만 추가)

### 전달 메커니즘 (frontend/src/lib/screenerHandoff.ts)
- 모듈 레벨 store + sessionStorage 폴백 (Next.js 클라이언트 라우팅에서 모듈 상태 유지)
- ScreenerStrategyHandoff: filterAst, universe, conditionSummary[], resultCount, createdAt
- setScreenerHandoff / getScreenerHandoff / clearScreenerHandoff / subscribeHandoff

### 스크리너 측 (TerminalScreener.tsx)
- 결과 툴바에 "이 전략으로 백테스트 →" 버튼 (tsend-bt-btn)
- 클릭 시 조건식+universe+조건요약을 handoff에 저장 → router.push("/backtest")
- conditionSummary(): 조건을 "PER > 0" 같은 읽기 쉬운 문자열로

### 백테스터 측 (TerminalBacktester.tsx)
- 마운트 시 getScreenerHandoff() 감지 → handoff 상태 + universe 자동 설정
- 상단 배너(tscreener-handoff): "스크리너 전략" 배지 + 조건 수 + N종목 매칭 + 조건 칩 + 해제 버튼
- run()이 handoff 있으면 largeCapFilter 대신 handoff.filterAst를 유니버스 필터로 사용
- 사용자는 전략/기간/자본 선택 후 RUN → 스크리너 검색 종목에 백테스트

### 동작 모델
스크리너 조건식 = 백테스트 유니버스 필터. screen-to-backtest API가 이미 filter_ast를 받으므로 백엔드 변경 불필요.
검증: PER<15+ROE>5 조건 → 10종목 검색 → GoldenCross 백테스트 132거래. 라이브로 스크리너 버튼→백테스터 배너 전달 확인.

---

## 🚀 프로덕션 준비 a+b+d (신뢰성 기반)

### a. 백테스트 속도 최적화 (8.2초 → 2.9초, 2.8배)
- [병목] cProfile: _generate_signal_as_of가 89%, 그 안 dt.strftime이 32%(3.7초). 매 거래일마다 df.copy().reset_index().dt.strftime → O(N²)
- [수정] src/kis_backtest_engine.py:
  - run(): ohlcv 로드 시 df["_date_str"] = df.index.strftime 1회만 생성
  - _generate_signal_as_of: copy/reset_index/strftime 제거 → 사전생성 _date_str로 경량 DataFrame 재구성
- [검증] 원본과 최적화가 동일 결과(3종목 GoldenCross 52거래 -8.1%) — 동작 불변. 10종목 5.9초

### b. 개발 프로세스 (CI + 린터 + 테스트 자동화)
- pyproject.toml: ruff(E/W/F/I/B/UP, line 120) + pytest 설정. 스타일 규칙(E701/E702/B904/B007/B023) ignore로 실버그(F계열) 집중
- .github/workflows/ci.yml: backend(ruff+pytest, KIS_USE_MOCK=1) + frontend(tsc+next build) 2-job
- Makefile: help/install/lint/fmt/test/typecheck/build/verify/clean/all
- ruff 1315개 자동수정 + **실버그 3개 발견·수정**:
  - ql_hedging_simulator.py: prev_opt_val 루프 전 초기화 (사용 후 정의 → F821)
  - main_api.py:2313: text(sql) → _sql_text(sql) (import 안 된 이름, 런타임 크래시 버그!)
  - ql_interest_rate_models.py: evaluationDate 읽기만 → 할당으로 수정 (useless expression, 실제론 날짜 설정 누락)
- [결과] ruff check All checks passed, 116 테스트 통과, 183 라우트 유지

### d. 로깅/에러처리 (관측성)
- src/observability/logging_config.py: 구조화 로깅(시각/레벨/모듈/요청ID/메시지), JSON 모드(LOG_JSON=1), 요청ID contextvar 전파, 멱등 setup_logging
- src/observability/middleware.py: RequestContextMiddleware — 요청별 추적ID(X-Request-ID 이어받기/생성) + 접근 로깅(메서드·경로·상태·소요ms) + 미처리 예외 안전망(상세는 로그만, 클라엔 일반 메시지+요청ID)
- main_api.py: CORS 뒤 setup_logging()+install_observability(app)
- screener_routes.py: raise HTTPException(500, str(e)) 32개 → logger.exception + 안전 메시지로 일괄 교체 (내부 에러 누출 차단)
- [검증] 라이브: X-Request-ID 헤더 이어받기/반환, "GET /...fields → 200 (30ms)" 요청 로깅 확인

### 신규 파일
- pyproject.toml, Makefile, .github/workflows/ci.yml
- src/observability/{__init__,logging_config,middleware}.py

---

## 🛡️ main_api 에러처리 완성 + UI/UX: 전략 저장

### main_api.py 에러처리 (d 연장)
- raise HTTPException(500, str(e)) 15개 + (status_code=500, detail=str(e)) 38개 = 53개를
  → logger.exception("요청 처리 실패") + 안전 메시지("처리 중 오류가 발생했습니다.")로 일괄 교체
- 400 에러 5개는 의도적 유지 (클라이언트에게 무엇이 잘못됐는지 알려주는 게 맞음)
- 모듈 레벨 logger = logging.getLogger("api.main") 추가
- ruff F841(unused e) 자동수정 → except Exception: 정리. All checks passed
- [라이브 검증] ValueError("DB password 민감") 유발 → 클라엔 {"detail":"처리 중 오류"} (민감정보 노출 0), 서버 로그엔 전체 스택+추적ID

### UI/UX: 스크리너 전략 저장/불러오기 (프리셋)
- frontend/src/lib/screenerPresets.ts: localStorage 기반 listPresets/savePreset/deletePreset. ScreenerPreset{id,name,group,universe,createdAt}
- TerminalScreener: Active Filters 아래 "저장된 전략" 섹션
  - "+ 저장" 버튼 → 이름 입력 다이얼로그 → 현재 조건식 저장
  - 저장된 프리셋 칩(이름+조건수 배지), 클릭 시 불러오기, ✕ 삭제
  - 마운트 시 listPresets() 로드, localStorage 영구 보관
- CSS: tpreset-section/head/save-btn/dialog/input/chip 등
- [라이브 검증] "저PER 우량주" 저장 → 칩에 "저PER 우량주 ②" 표시 확인

### 누적 UI/UX
결과 테이블 강화(컬럼선택/정렬/히트맵) + 로딩 스켈레톤 + 스크리너→백테스터 전달 + 전략 저장

---

## 🔧 main_api 에러처리 마무리 + 전략 비교 UI

### main_api 에러처리 (d 보강)
- 500 에러: 이전 세션에서 logger.exception + 안전메시지로 이미 처리됨 (누출 0)
- 400 에러 4곳(YAML/전략 파싱 ValueError): logger.warning 추가 + "입력 오류: {e}" 프레이밍 (사용자가 고칠 수 있게 메시지 유지, 단 명확히 검증오류로 표시)
- 결과: raw str(e) 클라이언트 노출 0개, ruff All checks passed

### 전략 비교 (Strategy Comparison) — 신규 UI
백테스터에 3번째 모드 추가. 퀀트 핵심 워크플로(전략 A vs B 나란히 비교).
- frontend/src/components/backtest/StrategyComparison.tsx (신규)
  - 유니버스/기간 설정 + 전략 다중선택 칩(2~5개)
  - 동일 조건으로 순차 백테스트 실행
  - Equity Curves 오버레이 (시작=100 정규화, 전략별 색상, SVG)
  - 지표 비교 테이블 9개(수익률/CAGR/Sharpe/Sortino/Calmar/MDD/승률/손익비/거래수), 각 지표 최고값 ★ 강조
- page.tsx: Mode에 "comparison" 추가, 3번째 모드버튼(03 전략 비교 Compare), StrategyComparison 렌더 분기
- globals.css: tcmp-* (config/strategy-chip/legend/chart/table/best 강조)
- 검증: 골든크로스 vs 모멘텀 비교 라이브 확인 — 오버레이 곡선 + 지표표 최고값 강조 작동

### 누적 백테스터 모드
01 전략 실행(Execution) · 02 전략 설계(Builder) · 03 전략 비교(Comparison)

---

## 🎯 젠포트화 Phase 0+1 — 주문 모델 기반 + 체결가 유형

[배경] 젠포트 백테스터 분석 → 가장 큰 격차는 "주문 정밀도". (B) Phase 0+1+2 진행 중.
[깊이] KIS OHLC로 종가류·피벗은 실데이터 계산 가능. TWAP만 분봉 필요(구조만). mock 검증 후 GCP 실데이터 전환.

### Phase 0 — 주문 모델 기반 (엔진 리팩토링)
- NEW src/engine/fill_price.py: FillPriceType(13종), resolve_fill_price(), resolve_from_slice()
  - 종가류: close/open/prev_close/prev_open/prev_high/prev_low
  - 피벗류: pivot/pivot_r1/pivot_r2/pivot_s1/pivot_s2 (전일 HLC로 계산, P=(H+L+C)/3)
  - 평균류: twap/vwap (분봉/체결량 미연결 → OHLC 근사)
  - 전일 데이터 없으면 당일종가 안전 폴백
- BacktestConfig += buy_fill_type/sell_fill_type (기본 "close")
- 메인 루프: 하드코딩된 close → resolve_from_slice() 사용. 기본 close = 기존 동작 불변
- 검증: 피벗 수동 계산 일치, close==종가(회귀 안전)

### Phase 1 — 체결가 유형 (API + UI)
- screener_routes: ScreenToBacktestRequest += buy_fill_type/sell_fill_type
- run_backtest() += buy_fill_type/sell_fill_type → BacktestConfig 전달
- NEW 엔드포인트 GET /api/v1/screener/fill-price-types (4그룹: 당일/전일/피벗/평균가)
- 프론트 screenerApi.ts: screenToBacktest에 fill_type 필드, fillPriceTypes() 메서드
- TerminalBacktester: buyFillType/sellFillType 상태, 고급옵션에 매수/매도 체결가 드롭다운(optgroup)

### 검증 (mock)
- 백엔드: 기본 close 52거래 -8.1%(불변) / 전일종가 +13.77% / 피벗 +13.76% — 체결가 모델 작동
- 라이브: 고급옵션 "체결가·수수료·손익절"에 매수/매도 체결가 드롭다운 13종 노출 확인
- 라우트 184개(+1), ruff All checks passed, TS 0 errors, next build 통과

### 다음: Phase 2 — 매도 정밀화 (보유기간·분할매도·조건매도식)

---

## 🎯 젠포트화 Phase 2 — 매도 정밀화

### 백엔드 (kis_backtest_engine.py)
- BacktestConfig += max_hold_days/min_hold_days/sell_divide_pct (모두 기본 비활성=불변)
- Position: entry_date 기존 보유 → 보유기간 계산에 사용
- _execute_sell(sell_fraction=1.0): 분할 매도 지원. frac<1이면 잔여의 일부만 매도, 평단가·진입일 유지
- _days_held(entry, current): 캘린더 경과일 헬퍼
- 메인 루프 step1: max_hold_days 경과 시 강제 청산(분할 적용), min_hold_days 이전엔 손익절 보류
- 메인 루프 step2: 신호 매도도 min_hold_days 존중 + sell_divide_pct 적용

### API (screener_routes.py) + run_backtest
- ScreenToBacktestRequest += max_hold_days/min_hold_days/sell_divide_pct
- run_backtest() 시그니처 + BacktestConfig 전달

### 프론트 (TerminalBacktester.tsx + screenerApi.ts)
- screenToBacktest 클라이언트에 Phase 2 필드
- maxHoldDays/minHoldDays/sellDividePct 상태
- 고급옵션에 "매도 정밀화" 구분 섹션: 보유기간 매도(일)/최소 보유(일)/매도 비중 슬라이더
- 고급옵션 3단 구조화: 체결가 / 매도 정밀화 / 비용·손익절 (tbt-divider-label)

### 검증 (mock)
- 회귀 불변: 기본 52거래 -8.1%
- 보유20일 -9.5% / 분할50% -1.6%(229→114→57→29주 잔여 절반씩 정확) / 최소보유10일 47거래 / 복합 213거래
- API: 보유20+분할50+최소5 → 694거래
- 라우트 184개, ruff All checks passed, TS 0 errors, next build 통과
- 라이브: 고급옵션 "매도 정밀화" 섹션 (보유기간/최소보유/매도비중) 노출 확인

### 젠포트화 진행 현황
- ✅ Phase 0 (주문 모델 기반) · ✅ Phase 1 (체결가 13종) · ✅ Phase 2 (매도 정밀화)
- 다음 후보: Phase 3 매수 정밀화(비중조절·분할매수·일일최대매수), Phase 4 종목선택 확장(테마/업종/관심그룹)
- 분할매도 주의: 신호 지속 시 잔여 절반씩 무한 분할 (젠포트는 N회 제한) — 현재는 단순 모델

---

## 젠포트화 Phase 2 보완 + Phase 3 — 매수 정밀화

### Phase 2 보완: 분할 매도 횟수 제한
- Position += sell_count/buy_count. BacktestConfig += max_sell_divisions (도달 시 잔량 전량청산)
- _execute_sell: is_last_division 체크로 무한분할 방지. 검증: buy458→sell 229,114,115 (3회 청산)

### Phase 3: 매수 정밀화
- BacktestConfig += buy_weight_mode(equal|factor)/buy_divide_pct/max_buy_per_day/max_buy_count
- _initial_alloc(factor_weight): 동일가중 vs 팩터가중(0.5~1.5배). _execute_buy 재작성(신규+add-on)
- 메인루프 _buys_today (일일제한). 검증: 회귀 52거래 -8.1% 불변, 분할매수 -4.1%, 일일1종목 50거래

### API+프론트
- run_backtest/ScreenToBacktestRequest/screenerApi 필드 전달
- TerminalBacktester 고급옵션 4단: 체결가/매도정밀화/매수정밀화/비용. 분할<100%시 횟수필드 조건부노출
- 검증: 라우트184, ruff통과, TS0, build통과, 라이브 4섹션 확인

### 진행: Phase 0~3 완료. 다음 Phase 4 종목선택(테마/업종/관심그룹)

---

## 팩터가중 연결 마무리 + Phase 4 종목선택 확장

### 팩터가중 연결 (완료)
- BacktestConfig += factor_weights (dict {ticker:0~1}). 매수 호출부에서 종목별 가중치 _execute_buy에 전달 (끊겼던 연결 복구)
- run_backtest 시그니처 + screen_to_backtest: composite_score를 0~1 정규화해 factor_weights 자동생성
- 검증: 가중치맵 주입 시 -8.1%→-12.6% (배분 변화), 맵없으면 동일가중 폴백
- 한계(정직): mock composite_score가 전종목 동일(79.21) → API 자동경로선 효과 안보임. 로직·연결 완성, 실데이터(KIS/DART)서 자동작동

### Phase 4 — 종목선택 확장 (업종/테마)
- screener.py: get_sector_universe() {업종:[종목]}, resolve_universe("sector:반도체"). _resolve_universe에 sector: 프리픽스 처리
- screener_routes.py: GET /sectors (10업종: 반도체/2차전지/금융/바이오/게임/화학/인터넷/자동차/철강/통신)
- screenerApi.ts: sectors() 메서드. TerminalBacktester: sectors 상태, ASSET UNIVERSE 드롭다운에 "업종·테마" optgroup
- 검증: 반도체업종 4종목 선별→백테스트 57거래. 라이브 드롭다운 13옵션(프리셋3+업종10) 확인, "반도체(4)" 선택 스크린샷 ✅

### 중요 트러블슈팅: stale .next
- 증상: sector 드롭다운 옵션 0개 + 콘솔 400 (_next/static/chunks/page-*.js)
- 원인: next start가 이전 빌드를 메모리에 들고있어 청크 해시 불일치 (BUILD_ID mismatch)
- 해결: pkill -9 node + rm -rf .next + npx next build 재실행 → 청크 해시 일치, 드롭다운 정상
- 교훈: 프론트 변경 후 렌더 실패 시 .next 클린 재빌드 필수

### 진행 현황: Phase 0~4 + 팩터가중 완료
- ✅ Phase 0 주문모델 · ✅ Phase 1 체결가13종 · ✅ Phase 2 매도정밀화+횟수제한 · ✅ Phase 3 매수정밀화 · ✅ 팩터가중연결 · ✅ Phase 4 종목선택(업종)
- 라우트 185개, ruff통과, TS0, 빌드통과
- 다음 후보: 테마 세분화, 관심그룹(사용자 종목묶음 저장), StrategyComparison에도 업종 추가(선택)

---

## 젠포트화 Phase 5 — 전략 관리 + 리포트 강화

### 5-C 벤치마크 대비 (백엔드 + 프론트)
- kis_backtest_engine.py: _compute_benchmark(dates, equity_values, strat_returns)
  - 코스피 지수("KOSPI"/"^KS11") → 대형주(005930) 폴백, 프록시 라벨 추적(정직)
  - 매수후보유 곡선을 전략 날짜에 ffill 정렬, 초기자본 스케일
  - 초과수익(전략-벤치 총수익), 베타(cov/var), 알파(연율화 252일)
  - run() 반환에 benchmark 추가
- screenerApi.ts: backtest.benchmark 타입 (label/curve/total_return_pct/excess_return_pct/beta/alpha_pct)
- TerminalBacktester EquityChart: benchmark 곡선 오버레이(회색 점선, 공통 스케일), 범례, 지표4개 카드(벤치수익/초과수익/베타/알파)
- CSS tbt-bench-* 

### 5-B CSV 내보내기 (프론트)
- NEW strategyStorage.ts: exportTradesCsv/exportSummaryCsv, downloadCsv(BOM 포함 한글 안전)
- 결과 상단 "내보내기" 툴바: 거래내역 CSV / 요약·월별 CSV
- exportTradesCsv는 Record<string,unknown>[] 받아 엔진 trade dict 유연 처리

### 5-A 전략 저장/불러오기 (프론트, localStorage)
- strategyStorage.ts: listStrategies/saveStrategy/deleteStrategy, SavedStrategy 타입(설정 전체)
- TerminalBacktester: collectConfig/handleSave/handleApply/handleDelete, savedList 상태
- RUN 버튼 아래 저장 행(이름 입력+저장+저장됨 토글), 저장목록 UI(불러오기/삭제)
- 최대 30개 보관, localStorage KEY=alpha_saved_strategies
- CSS tbt-save-*/tbt-saved-*/tbt-export-*

### 검증 (mock)
- 회귀 불변 52거래 -8.1%, 벤치마크 KOSPI 522포인트
- 라이브: 벤치마크 오버레이+지표4개, CSV툴바, 저장→목록→"저장됨(1)" 확인
- 라우트 185개, ruff통과, TS0, build통과(32kB)

### 정직한 한계
- 벤치마크 KOSPI가 mock에선 합성데이터 → +94.8% 비현실적, 초과수익 -109% 과장. 실데이터(KIS 지수API) GCP에서 정상화. 로직·UI·연결 완성
- 베타 0 = mock 전략수익률과 합성벤치 상관 거의 없음. 실데이터서 의미값

### 젠포트화 진행 현황: Phase 0~5 전체 완료
- ✅ Phase 0 주문모델 · ✅ Phase 1 체결가13종 · ✅ Phase 2 매도정밀화 · ✅ Phase 3 매수정밀화 · ✅ 팩터가중 · ✅ Phase 4 종목선택(업종) · ✅ Phase 5 전략관리+벤치마크
- 백테스터: 종목선택→매수/매도정밀화→체결가→전략관리→벤치마크 완비

---

## ① 실데이터 연결 준비 + ② mock 점수 다양화

### ① 실데이터 연결 준비
- 데이터 출처 배너 (TerminalBacktester): 결과 상단에 prov 배너 — "실데이터/Mock 백테스트 · 시세 KIS/mock · 재무 DART/mock", fully_real일 때 초록. mock일 때 "결과는 합성 데이터 기준" 주석. CSS tbt-prov-*
  - data_source는 _detect_data_source가 이미 반환 중이었음(market_data/fundamentals/fully_real), 프론트 표시만 추가
- 벤치마크 현실화 (ohlcv_loader._mock_ohlcv_df): 지수 티커(KOSPI/^KS11 등) 인식 → 시장다운 곡선(base 2500, drift 0.0001~0.0004, vol 0.008 = 개별주 절반). 벤치마크 KOSPI 총수익 +94.8%→+41.76% 현실화
- REAL_DATA_SETUP.md: GCP 배포 절차 + 백테스터 기능별 실데이터 영향표 + "실데이터서 비로소 의미있는 것"(팩터가중/벤치마크/시초가체결) + 코스피 지수 소스 안내

### ② mock 점수 다양화
- 원인: gap_score가 100 포화(모든 종목 저평가) → composite 79.21로 붕괴. roe_pct None(ffl_mock 경로)
- 해결: _compute_scores에 gap_depth_bonus 추가 — gap_pct<-50%일 때 깊이를 미세 가산(순위 보존). composite 고유값 1개→5개, 범위 79.33~94.36
- 효과: 팩터가중이 mock서도 효과 나타남 (동일가중 -17.94% vs 팩터가중 -18.18%, 이전엔 완전 동일)
- 한계(정직): 변별 여전히 미세(79.3대 밀집). 근본 해결은 valuation이 roe를 채우는 것 — 실데이터(DART)서 자동 해소

### 검증
- 엔진 회귀 불변 52거래 -8.1%, 라우트 185개, ruff통과, TS0, build통과(32.3kB)
- 라이브: 데이터 출처 배너 "Mock 데이터 백테스트 · 시세 mock · 재무 mock" + 벤치마크 완만한 곡선 확인

---

## ③ 관심그룹 (Watchlists) + ④ UI/UX 다듬기

### ③ 관심그룹
- NEW frontend/src/lib/watchlistStorage.ts: Watchlist 타입{id,name,tickers,updatedAt}, listWatchlists/createWatchlist/updateWatchlist/deleteWatchlist/addTicker/removeTicker, normalizeTicker(6자리 숫자만), localStorage KEY=alpha_watchlists (max 30)
- 백엔드: screen_to_backtest가 _universe = req.custom_tickers if req.custom_tickers else req.universe 사용. ScreenToBacktestRequest에 custom_tickers 필드 추가 (이게 없어서 AttributeError 났었음 → 수정)
- screenerApi.ts screenToBacktest body에 custom_tickers 추가
- TerminalBacktester: watchlists 상태, 핸들러(handleCreateWatch/handleDeleteWatch/handleAddTicker/handleRemoveTicker), run()서 watchlist:<id> 선택 시 종목을 customTickers로 전달 + effUniverse="custom"
  - ASSET UNIVERSE 드롭다운에 "관심그룹" optgroup (종목 0개면 disabled)
  - "관심그룹 관리" 토글 + 관리 패널(그룹 생성, 종목 칩+제거, 종목코드 입력 enter-to-add)
  - CSS tbt-watch-*
- 검증: custom_tickers 백테스트 작동(3종목→유동성게이트→2종목→32거래). 라이브: 그룹"내 반도체 픽" 생성→칩 3개(005930/000660/042700)→드롭다운 "내 반도체 픽 (3)" 자동등록 확인 ✅

### ④ UI/UX 다듬기
- StrategyComparison(03 전략비교)에 업종 유니버스 추가: sectors 상태+로드, UNIVERSE 드롭다운에 "업종·테마" optgroup (TerminalBacktester와 동일 패턴)
- admin/multi-backtest는 유지 결정 — command palette + EcosystemPanel(스크리너 생태계→티커 전달)에서 참조 중. StrategyComparison(전략 비교)과 목적 다름(티커 주도 vs 전략 주도)
- 검증: TS0, build통과(33.2kB), StrategyComparison 업종코드 청크 포함 확인. (모드 전환 렌더는 샌드박스 플레이크 — 코드는 execution모드서 검증된 동일 패턴)

### ①②③④ 통합 검증
- 회귀 불변 52거래 -8.1%, 라우트 185개, ruff통과, TS0, build통과
- 라이브 확인: ① 데이터 출처 배너 ② 점수 다양화(팩터가중 효과) ③ 관심그룹 생성→등록 ④ 빌드

### 4단계 작업 진행 현황: ①②③④ 전체 완료
- ✅ ① 실데이터 연결 준비(배너+벤치마크 현실화+GCP문서) · ✅ ② mock 점수 다양화 · ✅ ③ 관심그룹 · ✅ ④ UI/UX(비교모드 업종)

---

## GCP 배포 에러 수정 (Docker 빌드 실패 해결)

### 증상
- GCP에서 docker compose build 시 frontend 빌드 실패:
  1. "Module not found: @/components/multibacktest/*" — (실제로는 컴포넌트 존재, 사용자가 구버전 ZIP 사용한 정황)
  2. "Cannot find module 'tailwindcss'" — 진짜 원인

### 근본 원인 (검증됨)
- Dockerfile.frontend의 deps 단계 `npm ci --omit=dev` → typescript/tailwindcss/postcss/autoprefixer가 전부 devDependencies인데 빠짐 → next build 실패
- 로컬(맥/윈도우)은 devDeps까지 깔려 통과, GCP Linux 컨테이너만 실패
- /tmp/docker_sim에서 --omit=dev 재현 → "Cannot find module 'tailwindcss'" 확인 → 전체설치로 빌드 성공 검증

### 수정
1. Dockerfile.frontend: builder 단계를 deps와 분리, builder는 `npm ci`(전체) 설치 후 build. runner는 deps의 production node_modules만 복사 (이미지 경량 유지)
2. .dockerignore 신규: node_modules/.next/__pycache__/.env/캐시 제외 (빌드 컨텍스트 오염·stale 방지)
3. docker-compose.yml: backend env_file을 `{path: .env, required: false}`로 — .env 없어도 기동(environment 기본값 사용). 실키는 .env에 넣으면 자동 주입
4. .env 생성 (.env.example 복사, mock 기본값) — ZIP에 포함되어 즉시 docker compose up 가능
5. main_api.py startup의 init_db()를 try/except로 — DB 준비 전이어도 컨테이너 안 죽음

### 전체 점검 결과 (GCP 깨짐 후보 전수)
- frontend build: ✓ (clean install + next build, 14페이지 생성, TS0)
- backend import: ✓ (main_api:app, 185 라우트)
- requirements.txt: ✓ (pip dry-run 충돌 없음, QuantLib/arch/statsmodels 포함)
- multibacktest API: ✓ 존재 (stage11_routes.py, prefix /api/v1/multibacktest, 등록됨)
- ui_*.py: streamlit 미설치 + main_api 0참조 = 죽은 코드 (삭제 후보)

### 삭제 후보 (사용자 확인 후 결정)
- ui_*.py 10개 (Streamlit 잔재, 죽은 코드): ui_enterprise_risk/exotics/kis_screener/kis_strategy/options/quant_tools/screener/strategy/strategy_advanced/theme
- 깨진 브레이스 디렉토리 (빈 폴더): frontend/src/{lib... , frontend/src/{app...
- STAGE11/12/13_INTEGRATION.md (과거 개발노트)
- __pycache__ 5개, *.pyc 45개 (빌드산물, ZIP서 이미 제외)

---

## 죽은 코드 정리 (사용자 승인 후 삭제)

검증: 전체 코드베이스(py/tsx/ts/yml/json/Dockerfile) 참조 스캔 → 무영향 확인 후 삭제

### 삭제됨
- A) ui_*.py 10개 (Streamlit 잔재): enterprise_risk/exotics/kis_screener/kis_strategy/options/quant_tools/screener/strategy/strategy_advanced/theme
  - 검증: ui_strategy.py끼리만 서로 import하는 고립 섬, 외부 진입점 0, streamlit 미설치 → 죽은 코드
- B) 깨진 브레이스 빈 디렉토리: frontend/src/{lib... , frontend/src/{app... (과거 mkdir 오류 잔재, 파일 0개)
- C) STAGE11/12/13_INTEGRATION.md (과거 개발노트, 코드 참조 0)

### 삭제 후 무영향 증명
- 백엔드: ruff 통과, 라우트 185개(불변), 회귀 52거래 -8.1%(불변)
- 프론트: TS0, next build 성공, 14페이지 생성(불변)

---

## GCP 배포 에러 2차 수정 (public 폴더 누락)

### 증상
- 빌드 거의 끝까지 성공 (npm run build ✓), 마지막 runner 단계에서:
  `COPY --from=builder /app/public ./public` → `"/app/public": not found`

### 근본 원인
- frontend/public이 빈 폴더(파일 0개) → Git은 빈 폴더를 추적 안 함 → GitHub push 시 폴더 자체 소멸 → Docker COPY 실패
- (ZIP엔 빈 폴더 엔트리 있으나 Git이 드롭)

### 수정
1. frontend/public에 실제 파일 3개 생성: .gitkeep, robots.txt, favicon.svg → Git이 폴더 추적
2. Dockerfile.frontend builder 단계에 `RUN mkdir -p public` 추가 → public 없어도 COPY 안 깨짐 (이중 안전장치)

### 전수 점검 (다른 빈 폴더 문제 차단)
- 빈 폴더 전수 검색: 없음 (public 채움 + 브레이스 디렉토리 기제거)
- Dockerfile.backend: mkdir -p src/models src/api src/migrations tests로 이미 방어됨
- runner COPY 4경로(node_modules/public/.next/package.json) 전부 존재 검증
- /tmp/docker_sim2에서 builder→build→runner COPY 대상 전부 존재 재현 확인

### 빌드 통과 증명
- 백엔드: ruff 통과, 185 라우트, 회귀 52거래 -8.1%
- 프론트: build 성공, public 빌드 후 존재, .next 정상, npm start 스크립트 확인
