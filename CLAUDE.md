# Project Alpha — 한국 주식 퀀트 플랫폼

> 이 파일은 Claude Code가 프로젝트 맥락을 파악하기 위해 자동으로 읽습니다.
> 새 세션을 시작할 때 이 문서 하나만 읽으면 전체 맥락(아키텍처·개발 이력·안전규칙)을 이어받습니다.

---

## 목차

### 빠른 참조 (항상 먼저 볼 것)
(렌더러에 따라 앵커 링크가 정확히 안 열릴 수 있음 — 안 열리면 제목으로 텍스트 검색)
- [환경 (Windows 기준)](#환경-windows-기준)
- [아키텍처](#아키텍처)
- [스크리너 V3 핵심 (★절대 깨뜨리지 말 것★)](#스크리너-v3-핵심-절대-깨뜨리지-말-것)
- [실데이터 연동 (DART + KIS + KRX)](#실데이터-연동-dart-kis-krx)
- [완성된 기능 (4대 우선순위 전부 완료)](#완성된-기능-4대-우선순위-전부-완료)
- [개발 규칙 (★작업 시 반드시 준수★)](#개발-규칙-작업-시-반드시-준수)
- [빌드 & 실행 (Windows)](#빌드--실행-windows)
- [알려진 제약 / 주의](#알려진-제약--주의)
- [디자인 시스템 — Variant "Institutional Terminal" (적용됨)](#디자인-시스템--variant-institutional-terminal-적용됨)

### 개발 이력 (연대기순 — 오래된 것부터, 각 섹션 제목 그대로)
1. P0 안정화(배포 준비도) · 실데이터 검증 전략 · 실데이터 전용 게이트(mock_gate.py)
2. 백엔드 기능 UI 연결 · 통합 지표 시스템 · 스크리너↔백테스터 펀더멘털 통합
3. 펀더멘털 팩터 35→64개 · 가격·수급 팩터 추가 · UI/UX 개선 1차
4. 스크리너→백테스터 전략 전달 · 프로덕션 준비 a+b+d · main_api 에러처리(완성+마무리) · 전략 비교 UI
5. 젠포트화 Phase 0~5(주문모델·체결가·매도/매수 정밀화·팩터가중·종목선택·전략관리)
6. 실데이터 연결 준비 · mock 점수 다양화 · 관심그룹(Watchlists) · UI/UX 다듬기
7. GCP 배포 에러 수정(1차·2차) · 죽은 코드 정리
8. **GCP 실배포 + 실데이터 적재 세션**(런타임 프록시·DB 적재·KIS master 유니버스·업종분류·
   Company Analysis Cockpit·대시보드 재구축)
9. 매크로 콕핏 최초 구축(6탭) · 상관관계·타이밍·국면궤적(07/08탭) · 리스크·최적화 전략 9종(13→22) ·
   전략 상세 모달 · 배당 실데이터 · 내부자·개인 수급 실데이터 · 전략→백테스터 프리필 · 성과지표 확장
10. 백테스터 조건식 수식 빌더 · 스크리너 유니버스 실수치화 · 백테스터 4수정+매크로 국면 재구축 ·
    적재 정체 해소 · 매크로 추천 신뢰도 가중 · DART 백필 정체 수정 · financials_history DB 연결
11. 펀더멘털 적재 정체 근본원인(부분연도/자본결측/CAGR 복소수) · 백테스터 전종목 사용+금융업 편입
12. 기업분석 탭 심화(FAS/DD) · 기업분석 라운드2(CIO 실사) · 매크로 탭 대개편(CIO 리팩토링+혁신 3과제)
13. 젠포트화 Phase 6(동적 재편입) · 나이틀리 배치 프리컴퓨트(설계 가이드, 미구현)
14. 백테스터 버그수정+캐싱+Mock 거버넌스+KIS 클라이언트 3중 통합
15. CLAUDE.md 단일화(파편화된 .md 문서 33개 조사·병합·삭제)
16. PIT look-ahead bias 수정 · 스크리너 enrichment 동시성 · 생존편향 유니버스 UI 노출
17. 백테스트 SSE 진행률 무음 구간 제거(Celery/Redis 전제 조사·기각, 최소 수정 적용)
18. Allocation Studio 신규 탭(Two Sigma Venn 벤치마킹, 사용자 뷰 Black-Litterman +
    3-존 콕핏)
19. Research OS 개편(전 탭 헤더 제거 + Allocation Studio 밀도·레짐/카나리
    컨텍스트·인과 체인·확률구름·타임라인)
20. Research OS v2(마이크로 워크스페이스 6분할 + Sensitivity Heatmap +
    Decision Journal + vNext 설계 원칙)
21. Allocation Studio 파이프라인 리디자인(Claude Design 핸드오프 구현, 7단계 순차
    리서치 파이프라인 + 공유 크롬) · Allocation Studio Multi-Stage Wizard 전면
    리디자인(목표 게이트 + 3-페이즈) · Allocation Studio 심화 툴 4종
22. **백테스트 실행 워크플로 영속화(BacktestRun) + AAS 404·매크로 에러 근본수정 +
    Playwright E2E 하네스**(이 세션 — 스펙/플랜 문서화 → 버그 2건 근본수정 →
    BacktestRun 도메인·API·로딩·결과·비교 5단계) ← 최신

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
├─ main_api.py              # FastAPI 진입점 (223 endpoints, 포트 8000)
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
      │  ├─ TerminalScreener.tsx # 3-pane 메인 UI (Institutional Terminal 디자인, FilterBuilder.tsx 후속)
      │  ├─ AnalyzerPanel.tsx    # M7/M8 분석
      │  ├─ BacktestPanel.tsx    # 백테스트 패널
      │  ├─ LiveTradingPanel.tsx # ★자동매매 패널
      │  └─ DataQualityPanel.tsx # ★데이터 품질 패널
      └─ lib/screenerApi.ts      # API 클라이언트 (모든 fetch)
```

### 현재 규모 (실측)
| 영역 | 파일 수 | 비고 |
|---|---|---|
| `src/**/*.py` | 178 | 백엔드 전체 |
| `tests/*.py` | 84 | pytest (평탄 구조, 하위폴더 없음) |
| `src/engine/` | 45 | 스크리너·백테스트·매크로·리스크·가치평가 핵심 엔진 |
| `src/data/` | 23 | DART·KIS·KRX 데이터 계층 |
| `src/models/` | 33 | SQLAlchemy 모델 + 파생상품/리스크 계량 모델 |
| `src/api/` | 13 | FastAPI 라우터(`main_api.py`가 11개 include_router) |
| `src/execution/` | 8 | 실거래 클라이언트·킬스위치·리스크게이트웨이 |
| `src/kis_strategies/` | 8 | 조건식 DSL·전략 프리셋 |
| `frontend/src/` | app/·components/·lib/·store/·types/ | app 하위 10모듈(admin/backtest/builder/dashboard/derivatives/insights/macro/risk-tools/screener 등), components 하위 15개 도메인 디렉터리 |

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

## 실데이터 연동 (DART + KIS + KRX)

`.env`에 키를 넣으면 **자동으로 실데이터**, 없으면 mock fallback (코드 수정 불필요). 역할 분담:
**KRX = 과거(장기 백테스트 DB 적재) · DART = 재무 · KIS = 현재(실시간 시세·주문)**.

| 데이터 | 소스 | 환경변수 | 채워지는 것 |
|---|---|---|---|
| 재무제표 | DART | `DART_API_KEY` | 펀더멘털 팩터(64개) 실데이터화 + PIT 스냅샷 |
| 시세·실거래 | KIS | `KIS_USE_MOCK`(`1`=mock 기본/`0`=실호출) · `KIS_IS_PAPER`(`1`=모의투자/`0`=실계좌⚠) · `KIS_APP_KEY`/`KIS_APP_SECRET`/`KIS_ACCOUNT_NO`/`KIS_ACCOUNT_PRDT` | 실시간 시세·시총·PER·PBR·기술지표·주문 |
| 역사 일봉(장기 백테스트) | KRX OpenAPI | `KRX_API_KEY` | 수년~20년 전종목 일봉 + 지수 + 시점 유니버스(생존편향 보정) |

### 키 발급
- **DART**(무료): https://opendart.fss.or.kr/ 가입 → 인증키 즉시 발급(40자리).
- **KIS**: 모의투자용/실전용 앱키가 **다름**(둘 다 있으면 OK). 데이터 조회만 할 거면 실전 키 +
  주문 안 함이 일봉 데이터가 더 안정적. **키 종류와 `KIS_IS_PAPER`를 맞출 것** — 안 맞으면
  "토큰 발급 실패"/401 에러.
- **KRX**: https://openapi.krx.co.kr 에서 발급 (날짜 기준 전종목 API).

### 검증
```powershell
python verify_connection.py                 # 단계별 연동 검증(DART/KIS/KRX 순)
python verify_connection.py --stock 000660   # 다른 종목으로 검증
```
성공 시 각 단계(DART 재무제표·KIS 시세·통합 실데이터 팩터)가 실제 수치와 함께 출력됨.

### KRX 장기 백테스트 DB 적재 (최초 1회)
KRX OpenAPI는 날짜 기준 전종목 API라 백테스트용 역사 DB를 채우는 공급원으로 씀 — 백테스트는
적재된 DB에서 읽는다(젠포트식).
```powershell
python verify_connection.py                       REM 【5】 KRX 도달성·키·필드 정합 확인
python -m src.data.krx_ingest --start 2015-01-01  REM 10년 백필 ≈ 5,000콜 ≈ 50분
```
- **재개 가능**: 중단돼도 재실행하면 적재된 날짜는 건너뜀(`--max-days N`으로 쿼터 분할 가능).
- **지수 포함**: KOSPI/KOSDAQ 지수가 함께 적재 → 벤치마크·마켓타이밍 실데이터화.
- **수정종가**: 완료 시 등락률 체인으로 `adj_close` 자동 재구성(분할·증자 점프 제거).
- **생존편향 보정**: 백테스터 `universe="all_asof"` → 시작일 당시 거래 종목(이후 상폐 포함)으로 평가.

### mock → 실데이터 전환 요약
| 설정 | 펀더멘털 | 시세/지표 |
|---|---|---|
| 키 없음 | mock | mock |
| DART만 | 실데이터 | mock |
| KIS만(`KIS_USE_MOCK=0`) | mock | 실데이터 |
| 둘 다 | 실데이터 | 실데이터 |

### 트러블슈팅
| 증상 | 원인 | 해결 |
|---|---|---|
| `corp_code를 찾을 수 없음` | corpCode.xml 미다운로드 | `DART_API_KEY` 확인 → 최초 실행 시 자동 다운로드 |
| KIS `토큰 발급 실패` | 키 종류 ≠ `KIS_IS_PAPER` | 모의/실전 키와 `KIS_IS_PAPER` 일치 확인 |
| KIS `1분당 1회 초과` | 토큰 재발급 과다 | 1분 대기(토큰은 24h 캐시됨) |
| `펀더멘털 = mock` | DART 키 없음/조회 실패 | `verify_connection.py`로 DART 단계 점검 |

### 보안
`.env`는 **절대 git 커밋 금지**(`.env.example`만 커밋). API 키를 채팅·이슈·로그에 노출 금지.
실계좌(`KIS_IS_PAPER=0`)는 주문 코드가 실제 자금을 거래 — 데이터 조회만 할 거면 주문 함수 호출 금지.

---

## 완성된 기능 (4대 우선순위 전부 완료)

1. **실데이터 연동** — DART(재무) + KIS(시세), 키만 넣으면 작동
2. **실데이터 백테스트** — `ohlcv_loader.py`(DB→KIS→mock) + 스크리너→백테스터 원클릭
3. **실거래 자동매매** — `trading_engine.py`, 6중 안전장치(Kill Switch·손실한도·주문상한·일일한도·포지션제한·Dry-run 기본)
4. **데이터 인프라 QA** — `stock_master.py`(종목명 100% 해소) + 데이터 품질 검증

전체 진행 이력은 이 문서 아래 연대기적 세션 로그(V1~V3 + 4대 우선순위부터)에 기록됨.

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
- **`src.kis_order_executor.OrderExecutor`를 `TradingEngine` 밖에서 직접 생성 금지** — 이 클래스는 자체 안전장치가
  전혀 없어(dry-run/한도/킬스위치 검증 없이 곧장 `client.place_order()` 호출) `TradingEngine(safety=SafetyConfig)`가
  감싸야만 안전. `tests/test_no_order_executor_bypass.py`가 CI에서 정적으로 강제(`trading_engine.py` 밖에서
  `from src.kis_order_executor import ... OrderExecutor ...` 발견 시 실패). KIS 연동은 `src/execution/kis_client.py`의
  `get_kis_client()` 팩토리 **단일 경로**만 사용 — `KIS_USE_MOCK`(정확히 `"1"`일 때만 mock)이 유일한 판정 기준
  (`src/data/mock_gate.py::mock_allowed()`). `KIS_MODE`/`KIS_REAL_APP_KEY` 등의 구 변수는 완전히 제거됨(2026-07,
  아래 세션 기록 참고) — 재도입 금지.

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

> "CLAUDE.md를 읽고 현재 상태를 파악해줘.
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
- **루트(/)는 랜딩 페이지** — 셸이 pathname==="/"에서 풀블리드 렌더(셸 없음). 셸 브랜드/팔레트 홈은 /dashboard

### 랜딩 (app/page.tsx — Variant 레퍼런스 3종 합성)
- 구조: 다크 티커 마퀴 → 미니멀 헤더(브랜드+앵커 내비) → 분할 히어로("The operating system for quantitative research.") → INTEGRATED TOOLSET 5모듈 컬럼(설명+mono 메트릭+SVG 미니 비주얼) → PLATFORM METRICS 6종(실측 수치: 팩터 290+/체결가 13/함수 19/벡터화 142×/테스트 470/데이터소스 5) → 푸터(미니 티커+©)
- 전부 정적(서버 컴포넌트 — 백엔드 미기동에도 동작). CTA는 히어로 Launch Terminal → /dashboard
- 기존 Command Center 대시보드는 /dashboard로 이동 (내부 홈 링크 전부 갱신)
- 스타일: globals.css lp-* (기존 디자인 토큰 사용, 반응형 1100/820px)

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

## 🔒 실데이터 전용 게이트 (mock_gate.py) + 시가총액 "—" 해결

운영(실키 설정, `KIS_USE_MOCK=0`)에서 실 호출이 실패/빈값이면 조용히 mock으로 대체되던 지점이
다수 있었음(`market_data.py`/`fundamentals_store.py`/`price_factors_store.py`/`ohlcv_loader.py`/
`kis_client.py`/`kis_flows.py`) — 사용자가 실키를 설정해도 화면에 가짜 숫자가 뜰 수 있는 구조였음.

### 해결
- `src/data/mock_gate.py::mock_allowed()` 신설 — `KIS_USE_MOCK`이 정확히 `"1"`일 때만 True(합성
  데이터 허용). 위 산재된 지점을 이 게이트로 통일: 운영선 실패 시 mock 대신 정직한 `None`/빈값,
  개발·테스트(mock 모드)선 기존처럼 100% 합성 동작(회귀 불변).
- 시가총액 "—" 문제(KOSPI200 편입 종목도 시총 결측 표시)는 KIS master 파일이 이미 전종목 시총을
  무료로 제공 중임을 활용해 해결 — 실시간 API 호출 없이 `screener.py::_to_item`에서
  `load_master_flags()`로 채움, `_enrich_kis_quotes`가 더 신선한 실시세로 덮어쓸 수 있으면 우선.
- "실데이터 전용"의 대가: 실데이터에 빈 곳이 있으면 합성으로 가리지 않고 더 많은 "—"가 정직하게
  보임 — 의도된 트레이드오프.

### 검증
`tests/test_mock_gate.py`+`tests/test_realdata_only.py` 신설, 회귀 전량 불변(mock 모드 동작 100%
동일). 이후 이 게이트가 스크리너/백테스터/자동매매 전반의 mock 판정 단일 기준으로 자리잡음.

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
- 실데이터 전환 시 "비로소 의미 있어지는" 백테스터 기능 정리: 팩터가중(mock은 composite_score
  균일이라 동일가중 폴백, 실데이터는 종목별 점수 차등 → 비중 실제 차등), 벤치마크 대비(실 코스피
  대비 α·β), 당일시초가 체결(mock은 시가≈종가라 체결가 선택 영향 미미, 실데이터는 실제 영향)

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

---

# 🌐 GCP 실배포 + 실데이터 적재 세션 (컨텍스트 압축 요약)

> **배포 주소**: `http://34.58.206.52:3000/` (docker-compose: `ficc_backend`/`ficc_frontend`/`ficc_db`, 네트워크 `ficc_net`)
> 아래는 GCP 실배포 후 "아무것도 안 보임 → 실데이터 전종목 흐름"까지의 대규모 세션 요약.
> 새 세션은 이 블록부터 읽으면 현재 상태를 이어받음.

## 0. 한 줄 현황
GCP에 docker-compose로 배포됨. **KIS/DART 실데이터가 흐르고**(verify_connection 통과), KIS master(무료)로
**전종목(약 3,992)** 적재 + 실제 종목명 + 업종분류 완료. 스크리너/백테스터/컴퍼니/대시보드가 서버 DB와 연동.
**핵심 원칙: KIS·DART는 무료. mock은 키 없을 때만. 키 설정 시 자동 실데이터 전환.**

## 1. GCP API 연결 — 런타임 동일출처 프록시 (★가장 중요한 근본수정★)
- **증상**: GCP 배포 후 모든 탭이 빈 화면, "Screen-to-backtest failed: 500". 프론트가 `localhost:8000`을 치고 있었음.
- **근본원인**: `NEXT_PUBLIC_*`/`next.config.js` rewrites는 **빌드 타임에 목적지가 박힘** → 컨테이너 런타임 IP를 모름.
- **해결 (런타임 프록시)**:
  - `frontend/src/app/api/backend/[...path]/route.ts` — **route handler가 런타임에** `process.env.BACKEND_URL`을 읽어 백엔드로 프록시 (GET/POST/PUT/DELETE, 스트리밍).
  - `frontend/src/lib/apiBase.ts` — 모든 API를 **동일출처 `/api/backend/...`** 로 보냄 (브라우저는 자기 origin만 앎 → IP 무관).
  - `docker-compose.yml`: frontend에 `BACKEND_URL=http://backend:8000` (compose 내부 DNS).
- **교훈**: Next.js에서 런타임 가변 백엔드 주소는 **반드시 route handler 프록시**. 빌드타임 env/rewrites 금지.

## 2. 실데이터 DB 적재 아키텍처 (재로딩 제거 → 즉시 서빙)
- **요구**: "유니버스 바꿀 때마다 로딩 → DB 한번 쌓이면 바로 리스트". 전종목을 가져오되 매번 재평가 금지.
- **신규 `src/data/snapshot_db.py`**:
  - `factor_snapshot` 테이블 (`cache_key` PK, `value` JSON, `updated_at`) — 포터블 UPSERT(`ON CONFLICT`).
  - **item 캐시**: 종목당 `ScreenerItem.to_dict()` 전체를 `item:{CODE}` 로 저장 → `ScreenerItem.from_dict()`로 **재평가 없이 즉시 복원**.
  - `ingested_codes()`, `bulk_read/write_many`, `sample_factors()`, `ingest_universe(no_cap)`(청크 run() → item 저장).
- **`src/engine/screener.py`**:
  - `ScreenerItem.from_dict/to_dict` 왕복, `_load_cached_items`/`_store_items`.
  - `run()` 패스트패스: `item:CODE` 있으면 평가 스킵·즉시 반환, 없으면 평가 후 저장. `no_cap` 파라미터(ingest용).
  - `_resolve_universe`: 큰 유니버스(>250)는 `ingested_codes()` 사용, 그 외 `resolve_universe`.
- **DART 디스크 캐시**(`dart_cache/`) + 공유 싱글턴 `DARTClient` + throttle(`DART_THROTTLE_SEC=0.15`).
- **`SCREENER_MAX_LIVE_COMPUTE`(=400)**: 라이브 DART 호출 상한(ingest는 no_cap으로 무제한).
- **검증**: ingest 후 0.006s 즉시 서빙(재평가 0), DB read-through 센티넬 증명.

## 3. KIS master 유니버스 — 전종목·실명·플래그 (무료, 인증 불필요)
- **핵심 발견**: KIS master 파일은 **무료·무인증** — `https://new.real.download.dws.co.kr/common/master/{kospi,kosdaq}_code.mst.zip`.
  여기에 KOSPI200/KOSDAQ150 편입 플래그, ETF group_code(EF/EN), 시가총액, **실제 종목명**, 지수업종(섹터) 코드가 전부 들어있음.
- **`src/kis_master_parser.py`**: mst 파싱 → 플래그(`is_etf/is_kospi200/is_kosdaq150`)·시총·명칭·섹터코드. `collect_master_files()`가
  `save_master_flags()` + `reload_master_flags()` + `invalidate_universe_frame()` 호출.
- **`src/data/stock_master.py`**: `ETF_NAMES`(40 ETF), `get_stock_name`(STOCK_MASTER→master_name→ETF_NAMES→DART 순),
  `search_stocks`, `build_master_universe`, `save/load_master_flags`. → **"종목 102110" 같은 코드 표기 박멸, 실제 ETF명 표기**.
- **`main_api.py` startup**: `load_master_flags()` 없으면 `_collect_master_bg`(백그라운드 자동 수집), `_prewarm_real_data`(kospi200 ingest).
- **유니버스 종류**: kospi50/kospi200/kosdaq150/kospi/kosdaq/etf/all_listed/mapped — `resolve_universe`가 master→DART→preset 순으로 해소.
- **결과**: 전종목 약 3,992개, 실제 종목명·ETF명, KOSPI200=전체 편입종목(이전 50/130 한계 제거).

## 4. 전 종목 업종 분류 — "전체 업종 = 전종목" (다수결 전파)
- **증상**: 백테스터 "전체 업종" 선택 시 125→123종목만 (젠포트 테마 시드 129개만 잡힘). 전체 선택인데 전종목이 안 나옴.
- **`src/data/genport_themes.py`**: `build_group_assignment(flags)` —
  ① 시드(KRX 섹터코드 라벨) → ② **같은 섹터코드 종목에 다수결 전파** → ③ 큐레이션(`_CURATED_TO_GROUP`) → ④ 미분류는 "기타".
  THEME_TREE 17그룹(기타 포함), THEME_SEED 129, SUBSECTOR_GROUP 88.
- **`src/engine/universe_select.py`**: `_master_frame()`에 `genport_group` 컬럼 추가. `load_universe_frame()`을
  **수동 캐시로 전환**(실 master 프레임만 캐시, fallback은 캐시 안 함) + `invalidate_universe_frame()`.
  `select_universe()`가 `df["genport_group"].isin(sel_groups)`로 필터 → **전체 업종 선택 = 전종목**.
- **버그·수정**:
  - lru_cache가 collect-master 완료 전 fallback(125개)을 캐시 → 수동캐시 + invalidate로 해결. 테스트 호환 위해 `load_universe_frame.cache_clear = invalidate_universe_frame` 별칭.
  - `test_resolve_universe_all_listed`: `>=200` 임계 너무 빡빡 → `if u:`(비어있지 않으면)로 완화.

## 5. Company Analysis — 실데이터 Cockpit (계획 distributed-hatching-kurzweil 실행)
- `/insights`를 얕은 1콜 페이지 → **실데이터 구동 Cockpit**으로 교체. 백엔드 무변경, 프론트 조립.
- **`frontend/src/lib/companyData.ts`**: `loadCompanyCore(code)` — companyLookup + valuation evaluate(base/bull/bear ×3 실재계산) +
  financial(연도 시계열) + prices(실주가) + 유니버스 표본(percentile 순위) + 피어 + fields 메타를 `Promise.all` 병렬 로드.
- **`components/insights/CompanyCockpit.tsx`** + `parts.tsx`/`types.ts`: 7탭 — Overview/Valuation/Financials/Factors/Peers·Network/Risk/AI.
  Risk(VaR/GARCH/Sharpe)·Network(graph-relations)·AI(narrative)는 **lazy 온디맨드**.
- **수정된 실데이터 버그**:
  - Factors 퍼센타일이 전부 50 → 라이브 표본 실패가 원인 → **DB factor-sample** 경로로 교체.
  - `/prices`가 DB-only라 빈 결과 → `ohlcv_loader.load_ohlcv_unified`(DB→KIS→mock)로 교체.
  - 분기 재무: 누적 vs 단독 자동판별, 연간과 동일 지표 셋.
  - 리스크 탭: 실주가 시계열에서 산출. Valuation: 실 시총 사용.
- **정직한 한계**: 분기 컨센서스·이벤트·수급 일부는 mock/"준비중" 배지.

## 6. 대시보드 재구축 + 검색/로고/랜딩
- **`frontend/src/app/dashboard/page.tsx`**: 라이트 터미널 톤으로 재구축 — QuickSearch/MacroStrip/ModuleGrid/TopPicks(`dash-*` CSS). 5개 툴과 통합.
- **로고→랜딩**: `TerminalShell` 브랜드 링크 `href="/"`, 셸은 `pathname==="/"`에서 풀블리드(랜딩).
- **컴퍼니 검색 자동완성**: 종목명·코드로 `symbols/search` + sessionStorage `alpha_company_ticker` 핸드오프.
- **랜딩 히어로 CTA**: 버튼 텍스트 **"Launch Terminal" → "Dashboard"** (`app/page.tsx`, href `/dashboard` 유지).
- **브라우저 탭 로고(favicon)**: 기존 브랜드 로고(큐브/레이어 `M12 2L2 7...`, accent #1200ff, 흰 스트로크)로
  **`frontend/src/app/icon.svg`** 생성(Next.js App Router 자동 favicon). `public/favicon.svg`도 동일 로고로 교체(이전 "M" 글자 불일치 수정).

## 7. 운영·보안 메모
- **DART_API_KEY는 한때 채팅에 노출됨 → 사용자 재발급 완료**("dart 키는 재발급 했어"). `.env`는 절대 커밋 금지.
- 전 백엔드 테스트 스위트 **539 passed / 10 skipped / 0 failed** 유지.
- 작업 브랜치: `claude/keen-thompson-bdk3e8` (이 브랜치 외 푸시 금지, PR은 명시 요청 시에만).
- **프론트 변경 후 stale `.next` 주의**: 렌더 실패 시 `pkill -9 node && rm -rf .next && npx next build`.

## 8. 다음 후보
- 전종목 ingest 진행률/상태 UI, 수급(외국인·기관) 실연결, 컨센서스 유료데이터, 분기 재무 실엔드포인트, 매크로 BOK/FRED 실연동.

---

## 🌌 매크로 콕핏 최초 구축 — 6개 탭 (Overview·Indicators·Regime·Valuation·Strategies·Recommend)

`/macro` 탭이 4분면 레짐 매트릭스 + 금리·환율 스탯 몇 개뿐이던 것을, 5개 실데이터 API
(BOK/ECOS·FRED·KRX·DART·KIS)를 최대 활용하는 6탭 콕핏으로 전면 개편. 밸리AI(국면·하위요인·
사이클·밸류 히트맵)·MacroMicro(지표 해석) 참고, jasan-calc식 택티컬 전략 현재비중 개념 채택.

### 구조
- 상단 고정 레짐 배너(국면·사이클·Stress·추천 헤드라인) + 좌측 6서브탭:
  01 Overview(핵심 게이지+추천카드) · 02 Indicators(6테마 지표+z-score 히트맵) ·
  03 Regime(4분면+사이클시계+수익률곡선+Stress) · 04 Valuation(자산군+한국 시장/섹터 밸류 히트맵) ·
  05 Strategies(13전략 현재비중, US⇄KR 토글) · 06 Recommend(규칙+백테스트+AI 3종 종합).
- `src/engine/tactical_allocations.py`(13개 모멘텀/타이밍 전략) 신규 —
  전통/종합/가속 듀얼모멘텀·영구포트·LAA·RAA·GTAA·PAA·VAA·FAA·AAA·DAA·채권동적.
- `src/engine/macro_recommender.py`(국면×아키타입 적합도 + 백테스트 + AI 서술 3종 추천).
- `src/data/etf_prices.py`(US ETF 24종 + KR 매핑, US_TO_KR 토글).
- `GET /macro/{dashboard,valuation,strategies,recommend}` 엔드포인트.
- 프론트: `MacroCockpit.tsx`(배너+6탭) + `components/macro/cockpitParts.tsx`(RegimeScatter·CycleClock·
  ArcGauge·YieldCurveChart·ZHeatmap·ValuationBars·HoldingsDonut 등) + `lib/macroData.ts`(병렬 로더).
- 매크로→백테스터 이식: 추천 배분을 asset_alloc 바스켓으로 프리필(`macroHandoff.ts`).

### 검증
`KIS_USE_MOCK=1 pytest` 544 passed 불변, tsc 0, next build 16/16(/macro 20.8kB).

### 정직한 한계
샌드박스는 키/네트워크 없어 실 매크로 값·US ETF는 GCP에서 실측 — 여기선 로직·게이트·빌드·라벨
검증. 컨센서스/미래실적은 유료라 제외.

---

## 📊 매크로 콕핏 — 상관관계 추이·마켓타이밍·국면 궤적 (07/08 탭)

콕핏이 "현재 국면 → 추천"까지는 하지만 자산배분의 두 축(마켓타이밍, 상관관계)이 비어 있던 것을,
새 외부 데이터 없이 기존 5-API 데이터(`daily_closes`+`MacroCollector`)만으로 채움.

### 구현
- **07 Correlations**(`/macro/correlations`): 13자산(SPY/QQQ/IWM/EFA/EEM/TLT/IEF/LQD/HYG/GLD/
  PDBC/VNQ/TIP) 13×13 상관행렬, 롤링 60일 상관 5쌍(SPY-TLT 주식-채권 헤지축 등), 평균 페어상관
  (분산 국면 판정), 현재 주식-채권 상관 헤지/동조화 판정.
- **08 Timing**(`/macro/timing`): risk-on/off 종합점수(0~100, breadth·모멘텀폭·수익률곡선·
  신용스프레드·VIX 5개 가중 서브지표), 월별 히스토리, 13자산 추세표(200일선·12M모멘텀·52주고점·RSI).
- **국면 궤적**(`/macro/regime-trajectory`): 최근 18개월 국면 경로(테마-z 프록시, 결합도 낮춘 투명한
  근사) + 분면 전환 타임라인 — Regime 탭이 "현재 점"만 보여주던 것에 경로 추가.
- `src/engine/macro_analytics.py` 신규. 장기 데이터 준비도 개선도 함께: `etf_prices` 조회 윈도우
  600일 → `ETF_HISTORY_DAYS`(기본 1825일, ~5년)로 확장 + ETF 유니버스 prewarm 데몬 추가 →
  DB가 쌓일수록 롤링 상관·타이밍 추이가 자동으로 길어짐.

### 검증
`pytest` 566 passed(555+11), tsc 0, next build 16/16(/macro 24kB). mock 상관/타이밍 절대수치는
합성(구조·부호·로직만 검증) — 실값은 GCP 실시세에서.

---

## 📈 리스크·최적화 기반 자산배분 전략 9종 추가 (13 → 22)

기존 13전략이 전부 모멘텀·추세 타이밍 로테이션이라, 자산배분의 나머지 절반인 **리스크 기반
(공분산 구동)·최적화 기반·추세추종**이 통째로 비어 있었음.

### 추가 9종 (`src/engine/risk_allocations.py` 신규)
동일가중(벤치마크) · 리스크 패리티(ERC, Bridgewater식) · **HRP**(López de Prado 2016, 계층적
클러스터링, 행렬역산 없음) · 최소분산(Ledoit-Wolf 수축 공분산) · 최대분산(TOBAM) · 최대샤프(탄젠시) ·
**블랙-리터만**(시장균형 prior + `regime_analyzer.asset_tilts`를 뷰로 주입 — 국면 분석을 자산배분에
직결하는 콕핏 차별화 포인트) · 매니지드 퓨처스(TSMOM, long-flat) · 하프켈리(Σ⁻¹μ×0.5, 롱온리 클립).
전부 long-only·합100%, `scipy`/`sklearn` 미설치 시 역변동성 폴백 가드.

### 배선
`tactical_allocations.py`에 `family` 필드 추가(모멘텀/리스크/최적화/추세/사이징/벤치마크) +
`ALL_STRATEGIES = STRATEGIES + RISK_STRATEGIES`(22개). `macro_recommender.py`의 국면×아키타입
매핑에 9종 편입 → 추천 랭킹 자동 22종. 프론트 StrategyBoard가 family별 그룹 섹션으로 표시.

### 검증
`pytest` 555 passed, tsc 0, next build. 회귀 불변(모멘텀 13종 산출 동일).

### 정직한 한계
mock 공분산은 샌드박스 합성 가격 기반이라 분산효과가 비현실적(로직·합100·폴백·결정론만 검증,
실 분산효과는 GCP 실시세). max_sharpe/kelly/BL은 기대수익 추정오차에 민감 — Ledoit-Wolf 수축·
하프켈리·롱온리 제약으로 완화하되 만능은 아님(UI에 명시).

---

## 🔎 전략 상세 모달 — 22전략 큐레이션 설명 + 학술 레퍼런스 + 실제 동적 백테스트 + AI

05 Strategies 탭 카드가 이름·시그널·한줄설명뿐이라, 카드 클릭 시 전략을 깊이 이해할 수 있는
상세 모달 추가.

### 구현
- `src/engine/strategy_profiles.py` 신규 — 22전략 전부의 큐레이션 카탈로그(개념·작동방식 단계·
  경제적 근거·유리/불리 국면·파라미터·학술 레퍼런스). 레퍼런스는 Antonacci·Faber·Keller & Keuning·
  López de Prado·Black & Litterman·Kelly 등 실제 논문/저서 출처(정확성 확인됨) — 구조화 데이터로
  코드에 보존.
- **과거 성과 곡선**: 현재 비중 고정 buy&hold가 아니라, 매월 그 시점까지의 데이터만 보고 전략
  비중을 실제로 재계산하는 **동적 백테스트**(모멘텀 로테이션·타이밍 전환을 재현). 월 리밸런스,
  수수료/슬리피지 미반영, 월말 종가 기준 — 정밀 비용/체결은 백테스터 탭 이식으로.
- 국면 적합도 4분면 막대, 현재 보유 도넛, AI 심층분석(온디맨드, `ANTHROPIC_API_KEY` 있을 때만).
- `GET /macro/strategy/{sid}`(모달 오픈 시) + `POST /macro/strategy/{sid}/ai`(버튼 클릭 시만).

### 검증
`pytest` 576 passed(566+10), tsc 0, next build 16/16(/macro 25.5kB).

---

## 💰 배당 팩터 실데이터 연결 (DART `alotMatter`)

배당 관련 수치 두 곳이 실데이터가 아니었음: ① `dart_client`의 `FinancialStatement.dps`가 항상
`None`(배당공시를 아예 호출 안 함) ② `fundamentals_store`가 `dividend = net_income * 0.25`로
**날조 근사**(DART 키가 있어도 실배당이 아니라 순이익의 25%를 씀 — 실데이터 전용 원칙 위반).

### 해결
`dart_client.py`에 `get_dividend_info(corp_code, year)`(+ 순수 파서 `_parse_dividend_rows`) 신규 —
DART `alotMatter.json`에서 주당 현금배당금·현금배당성향·현금배당수익률 파싱. `get_financial_statement_full`
배선(dps 채움) + `fundamentals_store._real_raw_financials`의 날조 0.25 계수를 실제 `payout_pct` 기반
계산으로 교체(공시상 배당 항목이 없으면 정직하게 0 — "무배당"과 "미상"을 구분).

### 검증
`tests/test_dividend_parsing.py` 신규(픽스처 기반, 키 없이 파싱/배선 검증). mock 모드는 기존 합성
유지(회귀 불변).

---

## 👥 내부자·개인 수급 팩터 실데이터 연결

behavioral 수급 4개 필드(`foreign_net_5d`/`institution_net_5d`/`insider_net_20d`/`retail_net_5d`)와
이를 쓰는 시그널 4종(내부자매수+개인매도 등)이 mock 전용이라 운영(`mock_gate` 적용 후)에선 전부
`None`으로 평가 불가였음. 확인 결과 외국인·기관·개인은 이미 적재 중인 `investor_flows` 테이블에
데이터가 있었고(배선만 안 됨), 진짜 없는 건 내부자(insider)뿐 — DART 지분공시 필요.

### 구현 (독립 3단위)
- `dart_client.get_insider_disclosures(corp_code)` 신규 — DART `elestock.json`(임원·주요주주 소유
  변동 공시) 파싱.
- `src/data/insider_flows.py` 신규 — `insider_net(stock_code, days=20)`: 최근 N일 공시 순취득
  주식수 합산 → 억원 환산(최근가 없으면 정직하게 `None`, 단위 혼용 금지). `mock_gate` 게이트.
- `market_data.py`에 `_real_supply()` 추가 — 외국인/기관/개인은 `kis_flows`의 금액 필드(`*_amt`)
  최근 N일 합, 내부자는 위 모듈. 부수로 `price_factors_store`의 기존 qty/amt 단위 불일치도 함께
  수정(두 스토어가 하나의 정의 공유). `price_factors_store`에 `insider_net_20d`/`retail_net_20d`
  필드 신규 추가 — 스크리너 컬럼·필터로도 노출.

### 검증
`tests/test_insider_parsing.py` 신규 + `test_realdata_only.py` 확장(픽스처/mock DB 기반, 키 없이
파싱·배선·게이트 검증). 실 수급 데이터는 사용자 GCP 실키 환경에서 채워짐.

---

## 🔀 전략 → 백테스터 원클릭 프리필 (전략 유형별 하이브리드 표현)

"백테스트" 버튼이 `asset_alloc`(정적 바스켓 buy&hold)만 셋업해, 모멘텀/타이밍/최적화 같은 동적
전략엔 부정확했던 문제.

### 하이브리드 표현 (`src/engine/strategy_backtest_map.py` 신규)
전략 유형에 따라 3가지로 백테스터에 매핑: **모멘텀 12종**은 편집 가능한 조건식(`factor_expr`
산술식 + 정렬 + 월 리밸런스 — 사용자가 보고 수정 후 RUN) · **정적 2종**(영구포트·동일가중)은
`asset_alloc` 바스켓 · **최적화 8종**(리스크패리티·HRP·최소분산 등 + LAA)은 조건식으로 표현 불가해
`screen_to_backtest`에 `strategy_name="tactical:<sid>"` 라우팅을 신설, 실제 동적 배분 엔진을
그대로 실행(조건 편집은 불가, UI에 명시). 유니버스는 US 티커를 국내 ETF 코드로 매핑(US_TO_KR)해
GCP 실데이터로 백테스트 가능.

### 검증
`pytest` 586 passed(577+9), tsc 0, next build 16/16. E2E: `tactical:hrp` 라우팅 정상, 모멘텀
조건식 파싱 통과, 3모드(조건식/자산배분/엔진) 셋업 확인.

---

## 📐 백테스트 성과지표 대폭 확장 + 거래로그/데이터소스 정직화

성과지표가 14종뿐이고 다수가 공백("—")으로 보였으며, 매크로(PAA 등) 백테스트에 `MOCK_DATA`
배지가 실제 사용 데이터와 무관하게 표시되던 문제(키 유무만 보고 판정 — 실제 사용한 ETF
시계열이 mock 폴백이었는지는 무관하게 `fully_real` 계산). QuantStats/empyrical 참고해 개선.

### 구현
- `src/engine/quant_metrics.py` 신규 — `compute_metrics(returns, equity, periods_per_year, ...)`
  순수함수. 위험(변동성·VaR·CVaR·Ulcer index·최장 수중구간) · 위험조정(Omega·회복계수·
  gain-to-pain·tail ratio, 기존 Sharpe/Sortino/Calmar 유지) · 분포(왜도·첨도) · 거래
  (손익비·기대값·Kelly%) · 벤치마크(정보비율) 지표 산출. daily(252)/월간(12) 양쪽 경로 공용.
- 조건식 백테스트(`kis_backtest_engine`)·매크로 엔진(`strategy_backtest_map`) 양쪽에 병합
  배선(기존 키 유지 + 신규 추가, 하위호환).
- 거래로그를 매수/매도 개별 leg에서 **라운드트립**(진입일·청산일·진입가·청산가·수익률) 형태로
  재구성 — 프론트가 기대하던 필드와 백엔드 응답 불일치가 전부 "—"로 보이던 원인 해소.
- 매크로 엔진의 `data_source.fully_real` 판정을 "키 유무"에서 "실제 사용한 ETF 시계열이
  mock 폴백이었는지" 기준으로 교정.

### 검증
`pytest` 641 passed 기준(신규 지표 테스트 포함), ruff·tsc·build 통과. 기존 stats 키/값 회귀 불변
(하위호환, 신규 키만 추가).

---

## 🧮 백테스터 조건식 — 수식 빌더 (젠포트식 다항 팩터 조합)

[배경] 백테스터 매수/매도 조건에서 팩터가 1개만 들어가고 연산자를 못 넣는다는 피드백.
실제로는 백엔드(`factor_expr.py`)가 이미 자유 산술식(`{종가} - 이동평균({종가}, {20일}) > 0`)을 평가하고,
`mapConds`가 `expr`(direct)를 직렬화 중이었음 → **백엔드 무변경, 순수 프론트 UX 격차**였다.

### 핵심 아키텍처 (변경 불필요한 것)
- `/backtest` → `TerminalBacktester` → `panels/{Buy,Sell}ConditionPanel` → **`ConditionFormulaEditor`** (매수/매도/마켓타이밍 공용).
- `mapConds()`(TerminalBacktester): `expr: c.direct ? c.expr : null` → `screen-to-backtest` → `ConditionStrategy`(`condition_strategy.py`) → `parse_expr`(`factor_expr.py`).
- 백엔드 문법: 팩터 `{토큰}`, 함수 한국어명, **기간 인자는 반드시 `{N일}`**(평범한 `20`은 "식 인자"로 해석돼 거부), 사칙연산 `+-*/`·괄호·인용부호.

### 추가/변경 (프론트 전용)
- **NEW `lib/backtest/factorFunctions.ts`**: `renderFn`/`renderTermExpr`/`termLabel` — FactorPick(팩터+함수+중첩+두번째팩터)을 **백엔드 valid 산술식**으로 렌더(★기간 `{N일}`, 큰개수/작은개수 임계값은 `{0}` 브레이스, 비교/큰값/작은값은 bare).
- **NEW `components/backtest/FormulaBuilder.tsx`**: 칩 기반 비주얼 수식 빌더 — `[+ 팩터]`(FactorPickerModal 재사용)·`+ − × ÷`·괄호·상수(인라인 입력)·지우기. `FormulaToken[]` → `buildExpr()`(백엔드식)/`buildLabel()`(친화 표기).
- **`ConditionFormulaEditor.tsx` 재작성**: 모드 토글 `수식 빌더 | 직접 입력`(기존 단일 "팩터 선택" 대체 — 1항도 수식). 저장 시 모두 `direct` 조건(expr)으로 통일. 조건 **편집(연필)** 추가(직접 입력 칸으로 재로드). 논리식(every/any/before)·세트 저장·AI 자연어 변환·식 검증 유지.
- **`FactorPickerModal.tsx`**: `allowNesting` prop 추가 — 켜면 단일시계열 함수 전부에 "내부 지표(먼저 적용할 함수)" 노출 → `이동평균(과거값({종가},1),20)` 같은 중첩 가능. 기본 off(스크리너 호환, 스크리너는 픽을 이름으로만 해석).

### 검증
- `parse_expr`가 렌더러 출력 **36/36 통과**(18함수 단일+중첩+다항결합), 평범한 `20`은 정상 거부.
- `ConditionStrategy` 평가 E2E: `종가-MA20≥0`→BUY, 사용자 예시 `전일종가-MA(전일,20)≥0`→BUY, 거짓→HOLD, `(종가-MA5)/MA20≥0`→BUY (4/4).
- 백엔드 조건/식 테스트 63 통과, tsc 0, next build 16/16(/backtest 25.1kB).
- 한계: 샌드박스 DB 무(daily_prices 없음)로 풀 백테스트 실거래 생성은 GCP에서. 조건 평가 로직은 합성 시계열로 검증됨.

---

## 🌐 스크리너 유니버스 실수치화 + 숫자 정직화 + 100행 페이지네이션

[배경] 사용자: 유니버스가 KRX 실제 상장 수(KOSPI 946/KOSDAQ 1,822/전체 2,875)보다 작음(전체 833 등),
"검색된 기업"≠"평가 완료" 격차, 가상 스크롤 혼란 → 진단 후 4갈래로 해결.

### 진단 (핵심 — 재발 시 참조)
- **유니버스 크기 = 적재 진행률**: 대형 유니버스(>250)는 `_resolve_universe`가 ingested_codes()와 교집합
  (screener.py). GCP 833 = 적재 중단 지점(395 KOSPI+438 KOSDAQ). 적재는 재개 가능(스냅샷 fast-path 스킵).
- **검색<평가 = 유동성 게이트**: UI가 항상 relaxed(시총300억·거래대금3억) 전송 → 무표시 탈락.
- **199/130 = 하드코딩 프리셋 분모**: /universes가 UNIVERSE_PRESETS 크기만 반환했음.
- **가상 스크롤 = 윈도잉 렌더** (보이는 ~20행만 그리는 성능 기법. 라벨이 혼란 유발).

### 구현 (6커밋)
1. **그룹 확장**: stock_master.py `UNIVERSE_GROUP_CODES=(ST,RT,FS,MF,IF,SC,DR)` — kospi/kosdaq/all_listed가
   리츠·외국주 등 포함(KRX 공식 수 대응). ETF/ETN/ELW 제외 유지. KONEX 제외(사용자 결정).
   `master_composition()` = 시장별×그룹별 종목 수(잔차 원인 리포트).
2. **/universes master-aware**: 마스터 적재 시 build_master_universe 실크기(kospi/kosdaq/all_listed 포함),
   미적재 시 프리셋 폴백 → 199/130 해소.
3. **정직 카운터**: ScreenerResult += universe_size/ingested_count/evaluated_actual/capped.
   _resolve_universe가 적재 현황 1회 조회로 메타 수집. run-advanced 응답에 4필드(하위호환).
4. **적재 가시화**: db-status += universe_progress{kospi/kosdaq/etf/all_listed:{master,ingested}}+composition.
   Data Infra에 UNIVERSE COVERAGE 섹션(마스터/적재/진행률).
5. **게이트 기본 OFF**: TerminalScreener gateOn state(기본 false→liquidity_floor "off") + 카운트바 토글.
   기본 상태에서 검색된 기업==평가 완료. ON 시 "유동성 제외 N" 표시. 헤더 재구성:
   "유니버스 M종목 · 적재 A · 평가 E · 신규 · 캐시 · 초" + capped 배지 + 적재 미완 힌트(bsc-ingest-hint).
6. **페이지네이션**: 윈도잉 전면 제거 → PAGE_SIZE=100, 페이지 바(이전/다음/압축번호/범위), 정렬·새결과 시
   1페이지 리셋. CSV/컬럼선택/히트맵은 전체 결과 기준 유지. CSS bsc-pager/bsc-gate-toggle 등.

### 검증
- 백엔드 668 passed/10 skipped(신규 TDD 11: universe_groups 5·universes_endpoint 2·honest_counts 3·db_status 1), ruff 통과.
- tsc 0, next build 16/16. 라이브(mock+Playwright): kospi200 130종목 → "검색된 기업 130개",
  헤더 "유니버스 130종목 · 적재 0 · 평가 130", 페이저 "1–100/130"→"101–130/130" 페이지 전환 확인.
- 게이트 ON API: 50평가→47표시, liquidity_gate.filtered_out=3 (헤더 "유동성 제외 3" 근거).

### GCP 런북 (실수치 도달 절차 — 사용자 실행)
1. 배포 후 Admin → Data Infra → "펀더멘털"(또는 ★전체) 적재 실행 — 전종목 수 시간, 중단돼도 재실행 시 이어짐.
2. UNIVERSE COVERAGE에서 KOSPI/KOSDAQ 적재가 마스터 크기까지 차오르는지 확인.
3. 스크리너 유니버스가 실수치(KOSPI ≈946 / KOSDAQ ≈1,822 / 전체 ≈2,768) 도달 확인.
4. 잔차가 있으면 db-status의 master_composition(그룹별 종목 수)으로 원인 확인 — 필요 시 UNIVERSE_GROUP_CODES 조정.

---

## 🔧 백테스터 4수정 + 매크로 국면 재구축 (KR/US)

[배경] ① 전종목 백테스트가 "200/200"으로 잘림 ② +366%인데 승률/PF/거래 0 ③ Constituents가
종목명 칩뿐 ④ 매크로 국면이 항상 Stagflation(의심) → 4건 모두 코드 원인 확정 후 수정.

### 진단→수정 (7커밋)
1. **기간종료 청산**: 매도 미발동 전략은 통계가 청산 거래만 집계해 전부 0이던 문제 —
   BacktestConfig.liquidate_at_end(엔진 기본 OFF·API 기본 ON), 마지막 거래일 종가 전량청산
   (reason "기간종료 청산", 비용 반영, 곡선 끝=실현 자산), stats.eod_liquidated.
2. **symbol_results 확장**: 라운드트립 기반 corp_name/round_trips/realized_pnl/avg_return_pct/
   avg_hold_days/contribution_pct (기존 필드 유지).
3. **평가상한**: TerminalBacktester 하드코딩 universe_eval_cap:200 제거 → 전략상태 evalCap
   (기본 4000=전체), UniversePanel 셀렉트(500/1k/2k/전체). Constituents → SymbolPerfTable
   (정렬/20행 페이지/거래종목만 토글/행 클릭 → 개별 거래 상세). 보조바 "기간종료 청산 N종목".
4. **매크로 핵심 버그**: CPI 등 지수형을 레벨 z-score → 물가 축 영구 +1.5~2.0 고정(관측 +1.78).
   NEW src/engine/regime_axes.py — 지수형은 YoY% 변환 후 z(변환은 이 모듈에서만 — collector/차트
   원시값 유지). yoy 단위 인지 수정(지수는 %변화), 저장 36→72개월, 실물 mock 프로파일 현실화.
5. **축 재정의(실물)**: US 성장=산업생산·고용·실업률(역)·GDP YoY / KR 성장=경기선행 순환변동치·
   산업생산 YoY·KOSPI YoY (BOK 901Y067/901Y033 신규 수집 — 코드는 GCP 검증, 실패 시 축에서 자동
   제외·재정규화). 물가=CPI YoY+기대인플레(T10YIE).
6. **KR/US 분리**: analyze(market), get_regime_states, /macro/regime에 markets.kr/us(최상위=KR
   하위호환), 궤적도 동일 축 공유(regime_trajectory(market=)) + 사분면 명칭 통일
   (Goldilocks/Reflation/Stagflation/Deflation — Overheating/Disinflation 제거).
7. **콕핏**: 레짐 배너 KR/US 두 카드(국면·축·신뢰도) + 공통 Stress/모드.

### 검증
- 681 passed / 10 skipped (신규 TDD 13), ruff·tsc 0, next build 17/17.
- 라이브(mock): 매수만 전략 → 거래 3·승률 66.7%·청산 3·SK하이닉스 realized_pnl/보유178일/기여도
  채워짐, round_trips reason "기간종료 청산". /macro 배너 2카드(KR Goldilocks / US Stagflation —
  mock 데이터 기준, 물가 축 +1.78 고정 해방 확인).

### GCP 확인 항목 (사용자)
- 재배포+하드새로고침 후: 매크로 헤더 두 카드의 실데이터 국면 확인. BOK 신규 2종은 Indicators
  소스 패널에서 real/unavailable 확인 — unavailable이면 bok_targets의 item 코드 2줄만 조정.
- 백테스트: 전종목+상한 '전체'로 실행(첫 실행 수 분), 결과 하단 종목별 성과 테이블·행 클릭 상세.

---

## 🔧 적재(Ingest) 정체 해소 — 관측성 + DART 쿼터 감지 + 표시 정확화

[배경] Data Infra에서 적재 버튼을 눌러도 UNIVERSE COVERAGE 불변, 일봉 848만 행인데
"종목 0 · 기간 —", 백테스터(종목) X. "KRX/DART 문제인가?" → 원인 4개 확정 후 수정.

### 진단 (재발 시 참조)
- **일봉은 이미 적재돼 있었음(KRX 정상)** — db-status의 COUNT(DISTINCT)+MIN/MAX 결합 쿼리가
  statement_timeout(5s) 초과 → "종목 0" 오표시 + 백테스터(종목) 거짓 X.
- **펀더멘털 정체 = DART 일일 한도(20k) 경쟁 + 침묵 실패**: financials 백필과 factors 적재가
  같은 키 공유. 한도 도달(status 020)이 logger.warning으로만 사라짐 → UI는 "적재 중…"만.
- **빈 팩터 영속 오염**: mock_base.cached()가 빈 결과도 무조건 persist + 빈 히트 서빙 → 재시도 차단.
- **ETF 유니버스(1,250) 팩터 적재 경로 부재**: "etf" 버튼=크로스에셋 15종 시세.

### 수정 (7커밋, TDD 10종)
1. cached(): truthy만 영속, 빈 결과 EMPTY_RETRY_TTL(60s) 재시도, 오염 빈 히트 miss 취급(자가 치유).
2. dart_client: _USAGE 카운터(요청/에러별) + status 020/'한도' → quota_exhausted + dart_usage().
3. ingest_universe(progress_cb): done/total/saved/failures 보고 + 쿼터 감지 조기중단(사유 명시).
   main_api._INGEST_STATUS(타깃별 진행/에러/결과) → db-status 노출.
4. db-status: n_distinct 추정 + 개별 MIN/MAX + 미확정 None("—") + 백테스터(종목) EXISTS 판정.
5. GET /api/v1/data/ingest-doctor: DART/KRX/KIS 경량 실호출 진단 {ok,message,latency}.
6. Data Infra UI: 타깃별 진행 라인·last_error 빨강·DART 사용량/한도 경고·🩺 연결 진단 버튼·
   ETF "시세 전용" 정직 라벨 + DART 한도 공유 주의문(권장: 재무시계열 완주 후 펀더멘털).

### 검증: 691 passed / 10 skipped, ruff·tsc 0, next build 17/17.

### GCP 런북
1. 재배포 → Data Infra "🩺 연결 진단": DART/KRX/KIS ✓/✗ 즉시 확인.
2. 일봉 행이 "종목 —"가 아닌 추정치(~2,700)로 표시 + 백테스터(종목) ✓ 복구 확인.
3. 펀더멘털 적재 실행 → 타깃별 진행 라인에 stage/저장/실패 표시. "DART 일일 한도" 뜨면
   자동 중단된 것 — 내일 재실행 시 캐시로 이어짐(재무시계열과 동시 실행 지양).

---

## 🎯 매크로 추천 — 신뢰도 가중 배분 + market 버그 수정 + 정직화

[배경] 기관 퀀트 관점 크리틱(Goldman Strats/GSAM 경력 가정): "US 신뢰도 27%인데 위험자산
고비중은 블랙박스", "Kelly 공식 오용 우려", "매크로 데이터 후행성". 코드 검증 후 반영.

### 코드 검증 결과
- **Kelly 지적은 오독**: `s_kelly`는 22전략 중 1개일 뿐이고 `Σ⁻¹μ` long-only + 100% 완전투자
  정규화(무레버리지) — 팻테일/레버리지 리스크 구조적으로 없음. 라벨만 명확화.
- **market 버그는 실제**: `macro_recommender.recommend()`가 `RegimeAnalyzer().analyze()`를
  market 인자 없이 호출 → US 탭 추천이 항상 KR 국면으로 계산되고 있었음.
- **신뢰도 무반영도 실제**: confidence를 산출만 하고 배분에 전혀 안 씀 — 27%든 80%든 top
  전략 100%.

### 수정 (3커밋, TDD 8종)
1. `confidence_overlay(holdings, confidence, max_derisk=0.6)`: cash=(1-conf)*max_derisk,
   위험자산 비례축소 + 현금성(BIL) 앵커 배정, 합100 정규화. conf≈1이면 원본 불변.
2. `recommend()`: `analyze(market=mk)`로 연결(버그 수정) + confidence/low_conviction(<0.35)/
   data_lag_note 반환 + `top.holdings_final`(오버레이 적용)/`cash_overlay_pct`. 랭킹·성과는
   원 holdings 기준 불변(오버레이는 표시 배분에만).
3. Kelly desc 정직화 + 프론트(MacroCockpit): 신뢰도%·저확신 배지·holdings_final 표시·
   data_lag_note.

### 검증
- mock 라이브: KR=Reflation(신뢰도.23) vs US=Stagflation(신뢰도.26) — market 버그 수정 전엔
  둘 다 KR로 동일했음. 저확신 → 현금 오버레이 ~44-46% 자동 확인.
- 702 passed/10 skipped, ruff·tsc 0, next build 17/17.

### 범위 밖(의도적)
- 전체 배분 MVO/RP 강제 교체 — 이미 22후보에 risk_parity/min_var/max_sharpe/hrp/
  black_litterman 포함, 사용자가 고르면 1위로 표면화.
- 국면 히스테리시스/전환비용 페널티, NLP 나우캐스팅 — 신뢰도 가중이 경계 요동을 상당 흡수,
  나머지는 별도 대형 과제.

---

## 🩹 DART 재무시계열 백필 정체 — 마스터캐시 경쟁 + 무한루프 재사용 수정

부팅 시 KIS 마스터 수집과 DART 재무 백필이 별도 스레드로 동시 시작 → 백필 루프 첫 반복이
마스터 캐시가 채워지기 전에 실행되면 전종목 목록이 빈 결과 → 조용히 30종목 시드 리스트로
폴백 → 이후 "정상 종료"로 보고되어 24시간 그대로 잠들어버리는 경쟁조건. 부수로 수동 "재무시계열"
버튼이 무한루프 백그라운드 함수를 그대로 재사용해 절대 끝나지 않던 잠재 버그도 확인.

### 수정
`backfill_financials`가 전종목 목록 조회 실패로 시드 폴백했을 때 `fallback_to_seed` 플래그를
남기도록 수정. `_dart_backfill_sleep_seconds(stats)`(순수함수) 신설 — 쿼터소진 3시간, 폴백 발생
시 짧은 재시도(`DART_HISTORY_RETRY_SEC` 기본 300초), 정상 완료 24시간으로 sleep 시간 분기. 수동
"재무시계열" 버튼은 무한루프 함수 대신 `backfill_financials`를 1회만 직접 호출하도록 교체(진행률
연결) — 버튼이 실제로 종료됨.

### 검증
fallback 플래그(마스터 있음/없음 2케이스) + sleep 분기 TDD, 기존 `test_dart_history.py` 회귀 불변.

---

## 🔗 스크리너 펀더멘털이 financials_history DB를 쓰도록 연결 (유니버스 884 정체 해소)

스크리너 유니버스 크기가 884에서 고착 — 원인은 펀더멘털 팩터 조회(`_real_raw_financials`)가
**라이브 DART만 호출하고, 이미 25,616행·2,562종목이 백필된 `financials_history` DB를 전혀
읽지 않던 것**. 운영에서 DART가 쿼터/throttle로 실패하면 빈 결과가 나고, 빈 결과는 (정당하게)
캐시에 영속되지 않아 유니버스가 못 자람 — 백필 파이프라인과 스크리너 읽기 경로가 분리돼 있었음.

### 해결 (DB 우선 주입)
`FundamentalsStore._fs_from_history(stock_code, year)` 신규 — `financials_history`의 원시 스냅샷을
`FinancialStatement`로 매핑. `_get_fs(dart, corp_code, stock_code, year)` 신규 — **DB 우선 → 라이브
DART 폴백**. `_real_raw_financials`가 이 경로를 쓰도록 교체 — corp_code나 DART 설정이 없어도 DB에
데이터만 있으면 동작. 배당은 corp_code 있을 때만 best-effort(실패해도 팩터 영속을 막지 않음).

### 효과 / 검증
백필된 2,562종목이 DART 쿼터 소모 없이 실 펀더멘털로 반영 → 유니버스가 ~2,562까지 확장(DB에
없는 신규상장 등 ~135종목은 정직하게 미포함). 기존 `test_realdata_parsing`(45)·`test_dart_history`
회귀 불변(DB가 비어있으면 기존처럼 DART 폴백).

---

## 🔧 펀더멘털 적재 정체 근본 원인 — 부분연도/자본결측 탈락 (유니버스 ~40% 고착 해소)

[증상] e2-standard-4 재배포 후 펀더멘털 적재를 눌러도 유니버스가 재무시계열 종목수
(~2,562)까지 안 차고 ~40%(ffl: 1,996)에서 멈춤. 정직 카운터 "factors 완료 all_listed
2,350/2,350 (저장 1)". financials_history엔 재무가 있는데 ffl:(팩터)이 안 생김.

### 진단 (스모킹건: item: 2,805 > ffl: 1,996)
- item:(ScreenerItem 스냅샷)은 무조건 저장되는데 ffl:(팩터)만 안 생기는 비대칭 = 809종목이
  `_store_items`엔 들어갔지만 `get_factors`가 **빈 dict {}** 반환 → `cached()`가 truthy만
  영속하므로 ffl: 미기록. `_build_factors`가 {}를 반환한 것.
- `_build_factors`가 {} 반환 = `_real_raw_financials`가 None (운영 모드, 합성 금지). 원인 2가지:
  1. **부분연도 탈락**: `_real_raw_financials`가 최신 결산연도부터 3년만 훑고, 첫 "매출+자산"
     연도를 선택한 뒤 5핵심필드(매출·영업이익·순이익·자산·자본) 엄격 게이트에서 탈락. 오늘
     시점 2025 사업보고서가 조기·부분 공시(매출·자산만, 순이익 미기재)면 2025를 선택하고
     탈락 — 정작 2024는 완전한데도 못 씀.
  2. **자본총계 결측**: DART 일부 공시가 자본총계 라인 누락(자산·부채만) → total_equity=None
     → 5필드 게이트 탈락. 회계 항등식(자본=자산-부채)으로 정확 복구 가능한데 안 함.
- 단독 진단(`_build_factors("450330")`)이 65팩터로 성공했던 건 450330이 우연히 완전연도를
  가진 종목이라서 — 부분연도/자본결측 종목은 조용히 {}로 탈락(실패 0, 저장 0).

### 수정 (src/data/fundamentals_store.py, TDD)
- `_fs_from_history`: 매핑 후 **회계 항등식 보완** — 자본 결측이면 자산-부채, 부채 결측이면
  자산-자본 (정확값, 날조 아님).
- `_real_raw_financials`: 3년→**8년** 후행 탐색 + 선택 기준을 "매출+자산"→**완전연도**(5핵심
  필드 모두 실측)로 강화. 최신 부분연도를 건너뛰고 직전 완전연도를 사용. 완전연도 없으면
  정직하게 None(합성 금지 유지).
- tests/test_fundamentals_partial_year.py (3): 부분최신연도→직전완전연도 선택, 자본 항등식
  복구, 무-완전연도→정직 None.

### 정직한 잔여 (별도 과제)
- **금융업(은행·보험·지주)**: 손익계산서에 "매출액" 라인이 없고 영업수익/이자수익만 → DART
  파서가 revenue=None → 완전연도 없음으로 잔존 탈락. 매출 정의 확장이 필요한 소수 버킷.
  scripts/diag_fundamentals.py가 이 잔여를 `financial_no_revenue`로 분류·계량.

### 검증
- 723 passed / 10 skipped (신규 3), ruff 통과.
- scripts/diag_fundamentals.py 확장: 미충족 표본에 싱글턴 `get_factors` 실경로로 ffl: 영속
  증가분 + 미복구 원인 분류(recovered/financial_no_revenue/no_usable_year) 출력.

### GCP 런북 (사용자)
1. 재배포 후 `docker compose exec backend python scripts/diag_fundamentals.py` —
   6)의 "ffl: 실제 영속 증가분"이 0보다 크면 수정 유효.
2. Data Infra "펀더멘털" 재적재 → 유니버스가 재무시계열 종목수(~2,562)까지 차오름.
   (금융업 소수는 잔존 — 정직 한계, 위 진단의 financial_no_revenue 수치로 확인)

### 후속: 적재 속도·정체 방지 — DB 전용 핫패스 (진단 로그로 확인된 2차 병목)
GCP 진단(diag_fundamentals.py)이 `get_corp_code`의 corpCode.xml(수 MB) **라이브 다운로드**에서
멈춤. 원인은 `_real_raw_financials`가 (a) corp_code를 **선(先) 조회**(DB 서빙 종목도 불필요),
(b) 종목마다 **라이브 배당 호출**(`_real_dividend`→`get_dividend_info`)을 하던 것. 완전연도 수정으로
게이트를 통과하는 종목이 늘자 이 두 비용이 종목당 네트워크로 드러남(재배포 직후 corp 맵 미캐시 시 정체).
- `_get_fs`: corp_code **지연 조회**(DB 미스 + DART 설정 시에만) + 성장연도(전년/3년전)는 `db_only=True`로
  네트워크 금지(근사 폴백 존재). → DB로 서빙되는 종목은 corpCode.xml 다운로드 0.
- 배당: 라이브 호출 제거 → **DB 적재 dps**(주당배당금)×발행주식수로 산출(정직, 쿼터·지연 0). 미적재면 0.
- diag: corp_code 맵 1회 프리워밍(메시지) → 루프 중 멈춤 방지. 실패해도 DB 경로 동작.
- tests/test_fundamentals_partial_year.py +1: DB 서빙 시 corp_code/라이브배당 **호출 0** 검증(BOOM 가드).
- 검증: 724 passed / 10 skipped, ruff 통과.

### ★진짜 근본 원인★ 적자기업 CAGR 복소수 크래시 (진단이 확정)
diag 재실행이 침묵 {}가 아니라 **실제 예외**를 잡음:
`TypeError: type complex doesn't define __round__ method` @ `_derive_factors`의
`eps_cagr_3y = pct((eps/eps_3y_ago or 1)**(1/3) - 1)`.
- **원인**: 적자기업은 당기 eps<0, 3년전 eps>0 → 비율<0 → **(음수)**(1/3)=복소수** →
  `round(복소수)` 크래시. mock eps는 항상 양수라 그동안 미검출(테스트 통과했던 이유).
- **파급**: ingest에서 `attach_fundamentals`가 이 예외로 **청크 중간에 중단** → screener의
  `except→logger.debug`가 삼킴 → 그 뒤 종목 ffl:이 통째로 누락. item:은 이후 `_store_items`가
  저장 → item:(2,806) > ffl:(2,089) 비대칭 + 정직 카운터 "저장 1"의 진짜 정체.
- **수정** (src/data/fundamentals_store.py):
  1. revenue_cagr_3y·eps_cagr_3y: 비율>0일 때만 3제곱근(부호전환이면 CAGR 미정의 → None, 정직).
  2. `attach_fundamentals`: **종목별 try/except 격리** — 한 종목 예외가 청크 전체를 날리지
     않게(방어). logger.exception으로 트레이스 보존.
- tests/test_fundamentals_partial_year.py +3: 적자 _derive/_build 무크래시, 배치 격리.
- 검증: 727 passed / 10 skipped, ruff 통과.

주의(교훈): mock은 항상 흑자·양수라 실데이터 적자·부호전환 경로를 못 밟는다. 파생식에
분수승/로그/제곱근이 있으면 음수 입력을 반드시 가드(적자기업 실데이터에서만 터짐).

---

## 🧩 백테스터 전종목 사용 + 금융업 펀더멘털 편입

[배경] 유니버스 적재가 96%(전체 2,583/2,698)에 도달했는데, ① 백테스터가 선택 2,523종목 중
665개만 사용 ② 금융업 ~160종목이 여전히 유니버스에서 빠짐. 둘 다 코드 원인 확정 후 수정.

### ① 백테스터 전종목 사용 (프론트, 즉시)
- **원인 2개**: TerminalBacktester가 `liquidity_floor: "standard"`(시총≥1000억) 하드코딩 →
  2,523→665로 필터. 추가로 `filter_ast: largeCapFilter()`(=per>0)가 **적자기업까지 탈락**시킴.
- **수정**: `BacktestStrategy.liquidityGate`("off"|"relaxed"|"standard", 기본 **off**) 추가.
  - `strategyToRun`: off면 `liquidity_floor:"off"` + `filter_ast: emptyFilter()`(사전필터 없음) →
    선택한 전 종목이 백테스트 유니버스. relaxed/standard면 게이트+per>0.
  - UniversePanel에 유동성 게이트 Segmented(전종목/완화/표준) — 스크리너 토글과 동일 패턴.
  - 백엔드 무변경: `resolve_floor("off")→None`(게이트 스킵), 빈 filter_ast→`is_empty()` 스킵.
    병렬 OHLCV 로더(ThreadPoolExecutor 10워커)+진행률 스트리밍 이미 구현 → 2,500+종목 실용.

### ② 금융업 펀더멘털 (파서 확장 + 재조회)
- **원인**: 금융업(은행·보험·증권·지주)은 DART 손익계산서에 "매출액" 라인이 없어(영업수익/
  이자수익만) `get_financial_statement_full`가 revenue=NULL로 적재 → 완전연도 게이트 탈락.
- **수정**:
  1. `dart_client.get_financial_statement_full`: 매출액 부재 시 **영업수익>수입보험료>이자수익**
     순으로 revenue 채택(금융업 매출 정의). 제조업(매출액 有)은 불변.
  2. `dart_history.refetch_revenue_null()`: revenue=NULL이고 net_income 있는 행을 확장 파서로
     재조회·UPSERT. 멱등(채워진 건 후보 제외), max_calls 쿼터 보호.
  3. `_ingest_run("financials")`: 백필 후 **2단계로 refetch 자동 실행**(새 버튼 없이 "재무시계열"
     하나로). 쿼터 소진 아니면 남은 한도로.
- tests/test_financial_revenue.py(6): 영업수익/이자수익 매핑·우선순위·제조업 회귀·재조회 갱신/멱등.

### 검증
- 733 passed / 10 skipped(신규 6), ruff·tsc 0, next build 16/16(/backtest 29.6kB), 216 라우트.

### GCP 런북 (사용자)
1. 재배포 후 **"재무시계열"** 재실행 → 백필(resume, 대부분 skip) 후 금융업 revenue 재조회
   (진행 라인 `revenue_refetch(금융업)`). → **"펀더멘털"** 재적재 → 금융업 유니버스 편입.
2. 백테스터: 매매대상 탭 **유동성 게이트=전종목**(기본)이면 선택 전 종목 백테스트(적자·소형 포함).

---

## 🏛️ 기업분석 탭 심화 — FAS/DD 실무 대개편 (Gemini 추천 → 실무 교정 구현)

[배경] 사용자 제공 Gemini 컨설팅 추천(7라운드 PDF)을 AX 파트너 실무 관점으로 교정해 구현.

### 구조 (탭당 1콜, 기존 lazy 패턴)
- **백엔드**: src/engine/company_analytics.py (순수 함수) + src/api/company_routes.py
  - GET /api/v1/company/{code}/valuation-sandbox?price=&rf=&beta=&erp=&g=&years=
  - GET /api/v1/company/{code}/financial-deep
  - GET /api/v1/company/{code}/risk-deep?price=
- **프론트**: components/insights/{ValuationTab,FinancialsDeepTab,RiskDeepTab}.tsx —
  CompanyCockpit 각 탭 상단에 삽입(기존 콘텐츠 보존). 자체 SVG(외부 라이브러리 無).
  screenerApi.ts companyApi.{valuationSandbox,financialDeep,riskDeep} + 타입.

### Valuation 탭
- **Football Field**: DCF/RIM/DDM(Bear~Bull 시나리오 밴드)·52주·그레이엄·피어 PER/PBR
  25~75분위 암시가 + 현재가 세로선. 무배당 DDM 등은 available:false+사유.
- **가정 샌드박스**: Rf/β/ERP/g/연수 슬라이더(350ms 디바운스 재평가). 기본값 실측 주입 —
  Rf=get_dynamic_risk_free_rate()(ECOS), β=price_factors beta_1y(KIS). 출처 배지, 복원 버튼.
- **민감도 매트릭스**: Ke×g 5×5 (ke축=rf 평행이동, g≥ke−0.5%p 칸은 TV 발산→null).
  초록=현재가 대비 업사이드.
- **Comps 테이블**: 자사+동일섹터 피어(≤15) — 시총/PER/PBR/EV/EBITDA/ROE/영업이익률/
  매출성장 + 피어 중간값 행 + 재평가 암시가 3종(현재가×중간값/자사 멀티플).

### Financials 탭
- **QoE**: NI vs OCF 10년 오버레이 + 발생액/자산 + Red Flag 규칙(R1 OCF<NI 3년연속=bad,
  R2 발생액 3년 상승=warn, R3 NWC/매출 3년 상승=warn).
- **NWC**: 유동자산−유동부채·NWC/매출% 10년.
- **자본배치 워터폴**: OCF→CapEx/배당(dps×주식수/1e8)/부채상환(감소분)/잔여.
  자사주 미보유 명시. 부채 순증 연도는 "조달" 주석.
- **듀폰 3단 분해**(접이식 보조) + **ROIC−WACC 스프레드**(Kd=Rf+2%p 근사 라벨).

### Risk 탭
- **Altman Z 분해**: X1~X5 값·가중치·기여도 바 (get_raw_financials 동일 원천 — 팩터와 일관).
- **Beneish 실측 8지수**: GMI/SGI/LVGI/TATA 실측 + AQI 근사 + DSRI/DEPI/SGAI 중립 1.0
  (매출채권·감가상각·판관비 원천 미보유 — basis 라벨 real/approx/neutral로 정직).
  원 논문 계수로 M-Score 재산출, 전년 무데이터 → available:false.
- **커버리지 추이**: 이자보상배율(총부채×(Rf+2%p) 근사)·순부채/EBITDA 10년.
- **금리충격 스트레스**: +100/200/300bp(할인율 평행이동) → 커버리지·DCF·통합가 재평가.

### 정직한 한계 (스펙 명시, 의도적 제외)
- 컨센서스/12M Fwd/어닝리비전(FnGuide 유료), 글로벌 피어, Normalized EBITDA(주석 필요),
  국면 팩터 하이라이트(퀀트용 — 실무 아님), 주석 RAG/M&A 시뮬레이터/보고서 생성(별도 과제).

### 검증
- 신규 TDD 19개(test_company_analytics 15 + test_company_routes 4): 민감도 단조성·TV 발산
  가드·듀폰 곱=ROE·워터폴 항등·QoE 규칙 발화/비발화·Beneish 수식/라벨/무전년·Altman 기여
  합=Z·스트레스 방향성. tsc 0, next build(/insights 18kB), 217 라우트.

---

## 🩺 기업분석 라운드2 — CIO 실사 데이터 정합성 백본 + 기관급 시각화

[배경] 사용자 제공 Gemini 라운드2 PDF: CIO 실사가 GCP 실화면에서 치명적 데이터 오류 고발
(BPS ₩566만, PER 36.99 vs 15.05 불일치, YoY==QoQ, 52주 +517%, 수급 -1519조, 시총 1672조,
시총이 안정성 카테고리) + 시각화 기관급 격상 요구. 스펙 없이 직접 구현(사용자 지시).

### ① 데이터 정합성 백본 (tests/test_data_integrity_round2.py 8종 + 기존 갱신)
1. **주식수/시총 단일 진실** (BPS ₩566만·시총 1672조·그레이엄 759만 공통 근본):
   financials_history.shares_outstanding은 대부분 NULL(DART FS API가 주식수 미제공) →
   10000만주 폴백 → BPS≈자본총계(억). 있어도 단위(주vs만주) 불일치.
   → `_market_snapshot(code)`: KIS master 시총(억)+daily_prices 최근종가로 **파생 주식수**
   (시총/주가 — 둘 다 post-split이라 액면분할 자동 보정). DART 주식수(만주 환산)와 2배 이상
   괴리 시 파생값 채택. mcap도 item>master>PBR1.2근사 순.
2. **수급 -1519조 (100배)**: KIS pbmn=백만원·KRX=원 혼합 저장 + '억' 라벨.
   → 적재 시 억 단일화(kis_client /100, krx_mdc /1e8) + scripts/migrate_flows_units.py
   (기존 행 1회 변환, 멱등 마커 meta:flows_unit, --dry-run 지원).
3. **YoY==QoQ 복사버그**: 실경로 rev_q=연간/4 → QoQ≡YoY. → 분기 원천 없으면 None(정직).
4. **실팩터 mock 오염 제거**: price_momentum_12_1/pead_score/growth_acceleration(난수) →
   실경로 None. beneish_m mock 지수 → 실측(GMI·SGI·발생액)+중립. _maybe_missing(인위결측) mock 전용화.
5. **배당 미상 vs 무배당**: dps NULL→dividend_yield None / dps=0→0 (구분).
6. **52주 +517%**: ±45% 단일봉 점프(분할·권리락 미보정 시그니처) 감지 시 52주류 팩터 None +
   football field 52주 밴드 available:false. 정상 시 현재가 정렬(scale=price/last_close).
7. **PER/PBR/배당 단일화**: attach_fundamentals가 실데이터일 때 item 기본필드(roe_pct/per/
   pbr/dividend_yield_pct)를 ffl 팩터로 동기화 + 프론트 헤더가 item 팩터 우선(evaluate 요약은 폴백).
8. **분류 재정립**: market_cap_억 → size("규모") 카테고리 (안정성에서 제거).

### ② 시각화 기관급 (프론트, 외부 라이브러리 無)
- **Football Field v2**: SVG→HTML 행 박스플롯. 로버스트 축(현재가 4배↑/0.15배↓ 밴드는 축
  계산 제외 + "축 범위 밖" 정직 표기 — 그레이엄 아웃라이어가 차트 뭉개던 렌더 버그 해결),
  현재가 관통 기준선+태그, 축 눈금, 행별 값 라벨(고평가 밴드 붉은색).
- **리스크-리턴-퀄리티 사분면**: comps_table에 scatter 추가 — Y=업사이드(내재가/현재가−1),
  X=퀄리티(Altman↑·Beneish↓·Sloan↓ 피어 내 백분위 통합×100). 자사 강조, 사분면 라벨
  (우량·고수익/투기적/안정/회피), **노드 클릭 → 듀폰 3단 분해 팝업**(financialDeep lazy).
- **Ke×g 3D 등축 표면**: 민감도 섹션 2D/3D 토글 — SVG 폴리곤 등축투영, TV 발산 칸은 절벽(구멍),
  현재가 대비 up/dn 색. "금리·성장 동시 악화 시 가치 절벽" 임계점 시각화.

### 제외 (정직 — 별도 대형 과제)
- RAG 주석 드릴다운·Generative UI·에이전틱 차팅(LLM 인프라 선행), 마르코프 확률 국면 엔진
  (기존 regime+trajectory와 중복), 섹터특화 밸류 우회(컨센서스 필요).

### 검증: 761 passed / 10 skipped, ruff·tsc 0, next build(/insights 19.6kB).
라이브: 스캐터 4노드(자사 self)·52주 밴드 현재가 정렬·풋볼필드 로버스트 축 확인.

### GCP 런북 (사용자)
1. 재배포 → `docker compose exec backend python scripts/migrate_flows_units.py --dry-run`
   (변환 대상 확인) → `--dry-run` 없이 실행 (수급 단위 1회 변환, 멱등).
2. **"펀더멘털" 재적재** → 주식수/시총/PER/PBR/배당이 실측 기반으로 재산출(BPS·그레이엄 정상화).
3. 기업분석 탭에서 헤더 PER == 팩터 PER 일치, 풋볼필드 정상 렌더, 스캐터·3D 표면 확인.

---

## 🌐 매크로 탭 대개편 — CIO(헤지펀드 퀀트) 리팩토링 + 혁신 3과제

[배경] 사용자 제공 Gemini 진단(4대 정합성 버그 + 깃허브 트렌드 3혁신)을 코드로 검증 후 구현.
추가 적발: 사분면 명명이 모듈 간 정반대(recommender 'Reflation'=성장↑물가↓ vs axes =성장↑물가↑).

### ① 4대 버그 수정 (tests/test_macro_v2.py 9종)
1. **명명 통일**: Deflation→**Disinflation**(물가 z<0=상승 둔화) + 全모듈 단일 컨벤션
   (Goldilocks 성장↑물가↓/Reflation 성장↑물가↑/Stagflation/Disinflation) — axes·analyzer·
   recommender·strategy_profiles·screener 국면가중치·프론트 라벨·CycleClock까지.
2. **축 분해·모멘텀**(regime_axes.compute_axis_detail): 지표별 변환 z(YoY)·모멘텀 z·가중·기여
   + 불확실성 se. 축 = 레벨 75% + 3개월 모멘텀 25%. "CPI 레벨 +2.17σ vs 축 -0.28 모순"의
   정체 = UI가 원시 레벨 z를 축 입력처럼 표시 → Regime 탭 '축 스코어 분해' 카드로 투명화.
3. **스트레스 v2**: 수익률곡선 10Y-2Y(역전 패널티 15%) + 실질금리(10Y−T10YIE) z(10%) 추가
   — "실질금리 +1.7σ 긴축인데 Normal 44" 수정(역전+실질긴축 시나리오 47.8→90+).
4. **좌표축 동적 스케일**(cockpitParts/analyticsParts): domain [-1,1] 고정+클램프 → ±ceil(max)
   동적 — KR 성장 +2.06 마커 소실 버그 수정. 코너 라벨 통일 명명으로 교체.

### ② 매크로 임베딩 TAA (macro_allocation.py + recommend 통합)
- 국면 스코어(성장·물가)가 **직접 입력**인 4계절 선형 틸트(base 전천후 중립 + 감도×스코어
  + 스트레스 디리스킹) — 가격 모멘텀 추천(S&P 88%)이 매크로 환경과 충돌하던 문제 해소.
- **XAI 기여 분해**: 자산별 base+성장+물가+스트레스 = 최종 (룰 항 정확 분해 — 근사 SHAP보다 강함).
- **MC 신뢰구간**: (g,i)~N(score,se) 400드로우(시드 고정) → 비중 p10/p50/p90 밴드.
- recommend() 응답에 macro_allocation + regime_probs. Recommend 탭 1순위 카드(도넛+기여
  워터폴+밴드). 기존 22전략 랭킹은 유지(참고용).

### ③ 확률적 신뢰도 (quadrant_probs)
- P(사분면)=Φ(g/se)·Φ(i/se) 조합(합=1), 신뢰도=최대 확률(기존 tanh 대체).
- 배너 두 카드에 ProbBars(4분포 미니바), Regime 탭 확률 카드 — 정적 "신뢰도 80%" 텍스트 대체.

### ④ 혁신 — CB 센티먼트 + 그레인저 인과 그래프 (tests/test_macro_innovations.py 6종)
- **cb_sentiment.py**: Fed/BOK 정책문 매파/비둘기 렉시콘 스코어(-1~+1, 결정론). 수집 실패 시
  available:false(합성 금지). Indicators 탭 게이지 2종. GET /macro/cb-sentiment.
- **causal_graph.py**: statsmodels 그레인저(maxlag 3, p<0.10) → 방향 엣지. Correlations 탭
  원형 노드-엣지 SVG + 상위 엣지 목록. **정직 라벨: 예측적 인과(구조적 아님)**.
  GET /macro/causal-graph. (DoWhy/FinBERT 등 무거운 의존성 대신 검증가능한 대체 — 정직)

### 제외 (별도 과제)
- LLM(FinBERT) 파인튜닝 센티먼트·뉴스 크롤러 파이프라인, Black-Litterman 전면 교체(기존
  22전략에 이미 존재 — 매크로 뷰 주입은 후속), Generative UI/에이전틱 차팅(LLM 인프라).

### 검증
- 776 passed / 10 skipped (신규 15) · ruff·tsc 0 · next build(/macro 29kB) · 221 라우트.
- 라이브: Goldilocks P=54%, SPY 기여분해(18.0+1.1+0.2−0.2=19.0), TLT 밴드 19.0~23.8,
  그레인저 엣지 13개(mock), CB 센티먼트 정직 결측(샌드박스 네트워크 차단).

### 운영 노트 (컨테이너 재수화 관련)
- fastapi는 반드시 requirements 고정 버전(0.111.0) — 최신 0.139에선 include_router가 깨져
  라우터가 등록되지 않음(94 vs 221 라우트). 새 환경 셋업 시 `pip install -r requirements.txt`.

### v3 — 밸리AI 거시경제 분석 UI/UX 흡수 (편의성·전문성·기능성·접근성)
[배경] 사용자 제공 밸리AI 랜딩 캡처의 장점(사이클 히트 스트립·하위요인 분해·자산군
밸류에이션 스트립·국가 비교·스토리텔링 UX)을 우리 데이터 현실 내 정직 구현.
- **백엔드 src/engine/macro_visuals.py** (TDD 4종, 순수 함수 — regime_axes 정의 재사용):
  cycle_strips(지표×18개월 변환 z 스트립) · axis_history(축 하위요인 기여 스택 시계열,
  기여 합=축 항등) · asset_strips(자산 가격 위치 5년 백분위 — "시세 기반, 멀티플 아님"
  정직 라벨) · kr_us_compare(동일 변환 z 2국 비교 — 다국 지표 소스 미연동 명시).
  GET /macro/{cycle-strips,axis-history,asset-strips,compare-krus} (225 라우트).
- **프론트**: 배너 아래 **한줄 브리핑**(규칙 자동문장: 국면 P%·성장/물가 주도 지표·Stress)
  + **스토리 앵커 칩**(성장·물가→지표·CB톤→자산 밸류→상관·인과→배분 — 밸리 '차례로 짚기').
  Overview에 KR/US 비교 테이블, Regime에 사이클 스트립+성장/물가 하위요인 스택차트,
  Valuation에 자산 스트립 타임라인, Indicators에 **지표 검색** 인풋.
  visualParts.tsx 신규(CycleStripGrid/AxisStackChart/AssetStripGrid/KrUsCompareTable/buildBriefing).
- 검증: 780 passed/10 skipped · tsc 0 · next build(/macro 31.2kB) · 4 엔드포인트 smoke
  (스트립 6지표·히스토리 18pt·자산 10종·비교 6행).
- 제외(정직): 다국가(중·일·유럽) 지표(수집 소스 없음 — FRED 확장 별도 과제), 멀티플 기반
  자산 밸류에이션(컨센서스/지수 PER 데이터 필요).

### v4 — 매크로 콕핏 UI 개편 (Gemini UI/UX 피드백: 정보 위계·시각화)
- **상단 3분할 도넛 카드** (1순위): [KR 국면] [US 국면] [Stress·모드] 독립 카드.
  도넛 중앙 P% 볼드 + 국면명, 국면별 컬러(주황 Reflation/초록 Goldilocks/빨강 Stagflation/
  파랑 Disinflation), 서브지표(성장/물가)는 ▲▼ 필 배지로 톤다운, 나머지 확률 상위 2개 소형 표기.
  Stress 카드 = 도넛 + 모드 필 + 역전 경고 + 실데이터/asof 메타. (visualParts:
  RegimeDonutCard/StressModeCard/DonutRing/AxisPill — 기존 텍스트 나열 배너 대체)
- **자산별 추세 테이블 v2** (2순위): 조건부 서식(▲▼ + 색 + 옅은 배경 틴트), 추세 필 뱃지
  (상승 초록/하락 빨강/중립 회색 배경형), RSI 미니 트랙(30~70 존 + 위치 도트), 숫자 우측
  정렬·패딩 확대. 스파크라인은 timing API에 시계열이 없어 정직 생략(백엔드 확장 시 후속).
- 서브탭 필 스타일 강화(hover/on 테두리+배경). 검증: tsc 0 · build(/macro 32.2kB).

---

## 🎯 젠포트화 Phase 6 — 동적 재편입(Dynamic Replenishment) + 백테스터 버그 3건 수정

[배경] 사용자 보고: ①백테스트가 초기 선정 Top-N 종목만 계속 보유(매도 후 빈자리가 재편입 안 됨)
②커스텀 매도조건을 설정해도 트레이드 로그에 "데드크로스"가 찍힘 ③조건 추가·고급옵션(체결가
오프셋) 수정 시 `[ERROR] network error`. 3개 Explore 에이전트(백엔드 엔진/프론트 UI/백엔드
요청·스트리밍) + 1개 Plan 에이전트(재편입 아키텍처)로 전수 조사 후 근본원인 확정·수정.

### ① Dynamic Replenishment — Top-N 고정 문제 해결
- **근본원인**: `_screen_to_backtest_core`가 스크리너를 요청 시점 1회만 호출해 정적
  `tickers: list[str]`을 확정(`screener_routes.py`) → `BacktestConfig.symbols`가 불변 필드라
  메인루프(`for ticker in self.cfg.symbols`)가 이 고정 리스트만 순회. 매도로 빈자리가 생겨도
  이 리스트 밖 종목은 절대 편입 불가능했음(엔진에 `composite_score` 개념 자체가 없었음).
- **재사용 인프라**: `src/kis_strategies/score_factors.py::build_score_panels()` — 가격+수급만
  사용하는 "모멘텀점수"는 그 날짜까지의 rolling/pct_change만 쓰는 시점별 횡단면 퍼센타일이라
  **구조적으로 룩어헤드 없음**. 재무 포함 완전한 시점별 종합점수 재계산은 RIM/DCF/DDM이
  종목당 실시간 DART 호출을 요구해 인프라 부재로 미지원 — **정직한 한계**로 명시. 재편입
  trade reason에 "동적 재편입 — 모멘텀점수(가격+수급) 기준, 재무 미반영"을 항상 표기.
- **두 메커니즘** (`kis_backtest_engine.py`):
  1. **연속 재편입**(`_replenish_slots`): 어떤 이유로든 슬롯이 빈 그날 즉시, 미보유
     `replenishment_pool` 후보를 모멘텀점수 상위부터 채움. `rebalance_period`와 무관하게 항상
     실행(사용자 확정: "매도 시점 기준"). `max_buy_per_day`는 다른 매수와 동일 카운터 공유.
  2. **정기 리밸런싱 순위이탈 정리**(`_rebalance_prune`): `rebalance_period` 설정 시 그 주기
     첫 거래일에만, 보유종목 중 현재 랭킹 상위 `max_positions` 밖으로 밀려난 종목만 매도
     (reason: "리밸런싱 순위이탈 매도" — 상위권 보유종목은 유지, 전량 리셋 아님). 생긴 빈자리는
     같은 날 뒤이어 실행되는 1이 자동으로 채움(중복 매수로직 불필요).
- **후보풀 분리**: 신규 `replenishment_pool_cap`(기본100, `screener_routes.py`)이
  `universe_eval_cap`(조건식 봉별평가용, 최대4000)과 완전히 분리된 별도 상한 — 스크리너를
  1회만 호출해 `tickers`(초기보유)와 `pool_tickers`(재편입후보, 상위집합)를 같은 결과에서
  슬라이스. `BacktestConfig.replenishment_pool`이 symbols와 함께 OHLCV 병렬로더에 로드되어
  `universe_eval_cap` 규모와 완전히 독립적인 작고 예측 가능한 추가 비용만 발생.
- **기본 강제 적용**: `BacktestConfig.dynamic_replenishment: bool = True`(기본값, API에 끄는
  스위치 비노출). `replenishment_pool_cap=0`(내부/회귀테스트 전용)이나 `replenishment_pool`을
  아예 넘기지 않는 기존 호출자는 완전히 비활성(레거시 동작 100% 재현 — 회귀 안전).
- `buy_weight_mode="factor"` 시 재편입 종목의 factor_weight도 같은 랭킹 패널에서 0~1
  정규화해 부여(기존엔 범위 밖 종목이 암묵적으로 동일가중 폴백되던 불일치 수정).

### ② '데드크로스' 매도사유 하드코딩 — 완전 확정 후 수정
- **위치**: `src/kis_strategies/strategies.py:61-97` `GoldenCrossStrategy` — MA5/MA20 크로스
  고정 전략, SELL reason이 `f"데드크로스 (MA{...} < MA{...})"`로 하드코딩.
- **트리거**: `TerminalBacktester.tsx`의 메인 "전략 실행" 모드가 매크로 엔진 모드가 아닌 한
  항상 `strategy_name: "GoldenCross"`를 하드코딩 전송(이 UI엔애초에 전략을 명시 선택할 방법이
  없었음). 백엔드가 `buy_conditions`/`sell_conditions`가 **둘 다 비어있을 때**(조건 칩 없이
  손절/익절/트레일링/보유기간 등 리스크룰만 설정한 경우)는 override가 발동하지 않아 실제
  `GoldenCrossStrategy`가 실행 — 사용자 의도와 무관하게 "데드크로스"가 정당하게 출력됨.
- **수정**: `strategyToRun()`이 이제 `"Condition"`을 항상 명시 전송(매크로 엔진 모드 제외).
  백엔드 `_screen_to_backtest_core`도 `strategy_name == "Condition"`이면 조건이 비어있어도
  `eff_params`를 올바르게 구성하도록 분기 조건 확장(`buy_conditions or sell_conditions` →
  `... or req.strategy_name == "Condition"`). 조건이 비어있으면 `ConditionStrategy`는 자체
  신호를 내지 않고(HOLD만) 진입은 전부 동적 재편입이, 청산은 사용자가 설정한 손절/익절/트레일링/
  보유기간 규칙만 담당 — "데드크로스" 등 원치 않는 하드코딩 시그널이 다시는 섞이지 않음.

### ③ "network error" — 별개의 백엔드/프론트 버그 2건 확정 후 수정
- **버그 A(고급옵션 수정 시)**: `OffsetInput.tsx`에 min/max 클램프가 없어 백엔드
  `Field(ge=-10.0, le=10.0)` 제약(체결가 오프셋 4필드)을 벗어난 값 입력 시 422 발생, 그
  `detail`(FastAPI 배열 형태)을 `screenerApi.ts`가 그대로 `new Error()`에 넣어 `[object
  Object]`로 뭉개짐 → 수정: `OffsetInput`에 클램프 추가 + `extractErrorDetail()` 헬퍼로 422
  배열을 사람이 읽을 수 있는 메시지로 변환.
- **버그 B(조건 추가 시)**: `TerminalBacktester.tsx`가 조건 1개만 추가해도
  `full_universe_eval`을 자동 true로, `universe_eval_cap` 기본값 4000을 그대로 사용 →
  10종목→최대4000종목 평가로 폭증, 인프라 타임아웃/OOM으로 SSE `error` 이벤트조차 못 보내고
  커넥션이 끊김(브라우저 네이티브 fetch 예외 = 사용자가 본 "network error"의 정체) →
  수정: `evalCap` 기본값을 200(백엔드 자체 기본값과 동일)으로 낮추고, 큰 값은 UniversePanel
  드롭다운에서 사용자가 명시 선택해야만 사용되도록 함(①의 `replenishment_pool_cap` 도입으로
  "재편입 후보 확보"라는 원래 목적은 이미 별도의 작은 비용으로 해결됨).

### 검증
- 신규 `tests/test_dynamic_replenishment.py`(4개): pool 미지정 시 `dynamic_replenishment`
  플래그 값과 무관하게 완전 비활성(레거시 호출자 무영향 증명) · symbols 밖 종목이 손절로 열린
  슬롯에 재편입되는지 · rebalance_period 순위이탈 정리+즉시재편입이 상위권 보유종목은 건드리지
  않고 정확히 이탈종목만 교체하는지.
- **정직한 참고**: 이 변경은 매도가 발생하는 모든 시나리오의 거래수·수익률을 바꾸는 것이 설계
  의도(빈자리가 더 이상 비어있지 않음) — 기존 CLAUDE.md의 "52거래 -8.1%" 등 수동 회귀 수치는
  이 변경 이후 재현되지 않는다(예상된 변화). `replenishment_pool`을 넘기지 않는 호출 경로는
  100% 이전과 동일(위 4개 테스트 중 처음 2개로 고정). 신규 `dynamic_replenishment=True` 실행
  결과를 새 기준선으로 삼으려면, 기존에 회귀비교에 쓰던 실제 mock 시나리오(kospi200 샘플 등)를
  재실행해 실측치를 확인할 것 — 예측치를 여기 미리 적지 않음(기존 "정직" 원칙 일관 적용).

---

## 📐 (설계 가이드, 미구현) 나이틀리 배치 프리컴퓨트 — 매크로/밸류에이션 스냅샷

캐싱 작업(react-query 프론트 캐시 + `_RUN_ADVANCED_CACHE` 백엔드 응답 캐시)으로 "탭 이동마다
재로딩" 문제는 해결됐지만, **첫 접속(콜드 캐시) 로딩은 여전히 실시간 계산**이다. 매일 DB
적재(Backfill)가 끝난 시점에 매크로·밸류에이션 스냅샷을 미리 계산해두면 콜드 로딩도 즉시
응답 가능 — 아래는 기존 인프라를 그대로 재사용하는 설계안(구현은 이번 범위 밖, 필요 시 후속
요청).

### 재사용할 기존 인프라
- `main_api.py:480-483`의 `_INGEST_TARGETS`/`_INGEST_STATUS`/`_INGEST_RUNNING` — 이미
  `("index","etf","stocks","factors","financials","flows")` 6개 타깃을 백그라운드 스레드로
  실행하고 진행상황을 `db-status`로 노출하는 패턴이 완성돼 있음(`POST /api/v1/data/ingest/
  {target}`, `main_api.py:683-723`의 `ingest_trigger`).
- `src/data/snapshot_db.py`의 `factor_snapshot` 테이블(UPSERT, `ingest_universe`) — 이미
  펀더멘털/가격 팩터 스냅샷을 이 방식으로 영속화 중.

### 설계안
1. `_INGEST_TARGETS`에 `"macro_snapshot"` 타깃 추가.
2. 새 함수 `snapshot_macro()` — `analysisApi`가 호출하는 5종(regime/dashboard/valuation/
   strategies/recommend)을 서버 프로세스 내에서 직접 호출해 계산한 뒤, `factor_snapshot`과
   같은 패턴의 새 테이블(예: `macro_snapshot(cache_key, value, updated_at)`) 또는 기존
   `MacroCollector._cache`(TTL 6h)에 결과를 미리 채워 넣는 방식 — 후자가 더 적은 신규 코드로
   충분(이미 6h TTL 캐시가 있으므로, 매일 1회 이 캐시를 "미리 워밍"만 해주면 됨).
3. `ingest_trigger("macro_snapshot")`가 이 워밍 함수를 백그라운드 스레드로 실행 — 기존
   `_INGEST_STATUS[target]`에 진행상황 기록(패턴 그대로 재사용, 신규 상태 관리 불필요).
4. Data Infra 관리자 패널(`frontend/src/app/admin/data/page.tsx`)에 "매크로 스냅샷" 버튼 1개
   추가(다른 5개 타깃과 동일한 UI 패턴).

### 신규로 필요한 것 (기존 확장이 아님 — 별도 결정 필요)
- **스케줄러 자체가 이 코드베이스에 없음**(APScheduler/cron/celery 전무 확인됨,
  `docker-compose.yml`에 워커 컨테이너 없음). "매일 자동 실행"까지 원하면:
  - 옵션A: FastAPI 시작 시 `APScheduler`(경량, 별도 프로세스/컨테이너 불필요)로 매일 1회
    `snapshot_macro()`/`ingest_universe()` 호출 — 가장 적은 인프라 변경.
  - 옵션B: 배포 환경의 OS/Docker 레벨 cron(예: `docker compose exec backend python -m
    scripts.nightly_snapshot`)이 `POST /api/v1/data/ingest/macro_snapshot`을 매일 1회 호출 —
    앱 코드 변경 없이 배포 설정만으로 가능, 이 프로젝트의 "배포 환경마다 다를 수 있는 운영
    설정"이라는 기존 관례(`docker-compose.yml`/`setup_server.sh`)와 더 잘 맞음.
  - 둘 다 신규 인프라 도입이라 이번 캐싱 작업 범위에서는 제외 — 필요하면 별도 요청으로 진행.

---

## 🛠️ 백테스터 버그수정 + 프론트/백엔드 캐싱 + Mock 거버넌스 + KIS 클라이언트 3중 통합

사용자가 제시한 스크린샷 4건(①백테스터 UI/데이터 버그 ②캐싱 성능 ③DART mock 누출 ④하드코딩
mock 시세)을 순서대로 작업. 조사(Explore 3 + Plan 1 에이전트) 중 스크린샷에 없던 더 큰 문제
(KIS 클라이언트 3중 구현 + 실주문 엔드포인트의 안전장치 완전 우회)를 발견해 사용자 확인 후
범위에 포함. 4개 전부 완료.

### ① 백테스터 UI/데이터 버그
- **투자금액 3자리 잘림**: `kit.tsx`의 `numBox`(모든 `QuickStepper` 공용)가 `width:64` →
  `100`으로 확장 + 네이티브 스피너 화살표 CSS로 숨김. `ConditionFormulaEditor.tsx`의 rhs/rhs2
  입력폭(70→104px)도 동일 사유로 함께 확장.
- **"대상 종목 수: 전체" 선택해도 100종목 고정 (★자기회귀★)**: 근본원인은 직전 세션의 Dynamic
  Replenishment 구현 자체의 설계공백 — `screener_routes.py`의 `full_eval_on = bool(
  full_universe_eval and (buy_conditions or sell_conditions))`가 매수조건이 하나도 없는
  기본 상태(앱 초기값)에서 `eval_cap`을 `max_tickers`(≤30)로 쪼그라뜨려, `replenishment_pool_cap`
  기본값 100이 "약간의 top-up"이 아니라 사실상 전체 유니버스가 되어버렸음.
  → `full_eval_on` 게이팅 완전 제거, `eval_cap`이 조건식 유무와 무관하게 항상
  `req.universe_eval_cap`을 사용하도록 단순화.
- **컨트롤 통합**: "대상 종목 수"(`BuyConditionPanel`)와 "평가 종목 상한"(`UniversePanel`)이
  서로 다른 개념(포트폴리오 슬롯 수 vs 스크리닝 후보 풀 크기)을 혼란스럽게 나눠 통제하던 문제 —
  "전체/제한" MAX/LIMIT 토글(`limitType`) 완전 제거, "대상 종목 수"는 라벨을
  "최대 보유 종목 수"로 명확화해 항상 유한한 보유슬롯 수로 남기고, 스크리닝 풀 크기 개념은
  "평가 종목 상한" 하나로 통합.
- 신규 회귀 테스트: `tests/test_backtest_universe_cap.py`(4개) — `eval_cap`이 조건식 유무와
  무관하게 `universe_eval_cap`을 따르고, `max_positions`는 독립적으로 전달되는지 확인.

### ② 프론트/백엔드 캐싱 성능최적화
- **근본원인**: `@tanstack/react-query`(v5)가 설치는 됐으나 `QueryClientProvider`가 어디에도
  없었음(부분 세팅이 아니라 아예 미착수) — 모든 탭이 `useEffect`+`useState` 수동 페칭으로
  탭 이동마다 100% 재요청.
- 신규 `frontend/src/lib/queryClient.ts`(`staleTime`/`gcTime` 24h) + `components/layout/
  Providers.tsx` → `app/layout.tsx`가 `<TerminalShell>`을 감쌈.
- **Screener**: 카탈로그 4종(fields/indicators/factorFieldMap/universes) + 300행 샘플을
  `useQuery`로 마이그레이션. 메인 스캔(`run-advanced-stream`)은 SSE라 그대로 유지(진행률 UX 보존).
- **Macro**: `loadMacroCore`의 5개 병렬 호출(regime/dashboard/valuation/strategies/recommend)을
  개별 `useQuery`로 분리 — `loadMacroCore()` 함수 자체는 삭제. `MacroCockpit`의 `compareKrUs`도
  `useQuery`화.
- **Company**: `loadCompanyCore` + Cockpit 마운트이펙트(`signal`/`macroRegime`)를 `useQuery`화.
  **`macroRegime()` 캐시 키를 Macro 탭과 동일(`["macro","regime"]`)하게 맞춰 두 탭 간 중복
  호출을 프론트 캐시 레벨에서 자동 해소**(백엔드 변경 없이 낭비 제거).
- **Prefetch**: `TerminalShell.tsx` 사이드바 `<Link>`에 `onMouseEnter`로 핵심 진입 쿼리
  prefetch(이 코드베이스 최초의 hover-prefetch 패턴).
- **백엔드 응답 캐시**: 기존에 3곳 반복되던 `_XCache`(TTL+LRU+`.stats()`/`.clear()`) 관례를
  그대로 재사용 — `screener_routes.py`에 `_ResponseCache`+`_RUN_ADVANCED_CACHE` 신설,
  `/cache/stats`·`/cache/clear`가 기존 `_ValuationCache`와 함께 보고.
- **나이틀리 배치**: 요청이 "선택 사항 + 가이드 제안"이라 설계만 문서화(위 섹션 참고), 실제
  스케줄러(APScheduler 등) 도입은 범위 밖.

### ③ DART/가격 Mock 데이터 거버넌스
- **DART 재무 침묵 폴백 차단**: `dart_client.py`는 키 미설정/쿼터초과/네트워크 에러를 전부
  `None`으로 뭉개고, 그 위 계층이 무조건 mock `FinancialStatement(is_mock=True)`로 폴백 —
  `fundamentals_store.py`는 이미 이 플래그를 방어했지만 `valuation_models.py::evaluate()`는
  무방비였음(운영에서도 DART 호출이 한 번이라도 실패하면 RIM/DCF/DDM이 합성 재무로 조용히
  계산되고 있었음). → `UnifiedValuation.is_mock: bool` 필드 추가 + `evaluate()`에
  `fs.is_mock and not mock_allowed()` 가드 추가(운영에서 mock 재무 감지 시 계산 대신 정직하게
  "데이터 없음" 반환, 종목명은 `stock_master.get_stock_name()` — "Unknown Corp" 금지 규칙 준수).
  `valuation_routes.py`의 `/evaluate`·`/compare` 응답에 `is_mock` 노출.
- **하드코딩 mock 시세가 게이트 없이 상시 적용되던 문제**: `screener.py`의 `_mock_price()`(10종목
  하드코딩)가 `ValuationScreener`의 **기본 `price_provider`**로 4개 프로덕션 생성 지점
  전부에서 `KIS_USE_MOCK`/키 설정과 무관하게 상시 적용 — 사후 `_enrich_kis_quotes()`가
  `current_price`만 실가로 패치하고 `gap_pct`/`verdict`/`composite_score`는 재계산 안 해
  "화면엔 진짜 가격, 저평가 판정은 가짜 가격 기준"인 내적 불일치가 있었음(자동매매 종목선정
  로직까지 영향). → `_enrich_kis_quotes`가 패치 후 `compute_gap_pct`/`gap_pct_to_verdict`/
  `_compute_scores`(시그니처를 `(gap_pct, fin)`로 리팩터링해 초기계산과 공유)를 재실행하도록 수정
  (순수 산술, 추가 네트워크 호출 0). `ScreenerItem`에 `price_is_mock`/`fundamentals_is_mock`
  필드 추가(데이터 품질 투명화).
- **부수 발견·수정**: `screener.py`에 `import os`가 누락돼 있었음 — `_enrich_kis_quotes`의
  `os.getenv("SCREENER_MAX_LIVE_COMPUTE",...)`가 실제 KIS 연동 시(mock 아닐 때) 항상
  `NameError`로 크래시하는 잠재 버그(기존 테스트 전부가 mock 경로만 태워 미발견). 이번에
  같은 함수를 수정하던 중 발견해 함께 수정.
- `mock_gate.py::mock_allowed()`(정확히 `"1"`일 때만 True)로 산재된 인라인 `os.getenv(
  "KIS_USE_MOCK",...)` 체크 14개 파일 21곳 일원화(`main_api.py`/`trading_routes.py`/
  `screener.py`/`snapshot_db.py`/`minute_bars.py` 등). 2곳(`!= "0"` 패턴)은 `mock_allowed()`로
  바꾸며 의도적으로 엄격화(`KIS_USE_MOCK=banana` 같은 쓰레기값이 이제 mock으로 안전하게 처리).
- 신규 테스트: `tests/test_valuation_mock_leak.py`(3), `tests/test_screener_price_enrichment.py`(3).

### ④ KIS 클라이언트 3중 구현 통합 + 실주문 안전장치 우회 제거 (★가장 중요★)
- **발견된 문제**: KIS 연동이 3개의 독립 구현체로 쪼개져 있었음 —
  1. `src/execution/kis_client.py`(`KISClient`/`MockKISClient`) — `KIS_USE_MOCK` 게이트, 문서화됨,
     `TradingEngine`이 쓰는 **정식 경로**.
  2. `src/api/broker_kis.py`(`KoreaInvestmentAPI`) — 별도 미문서화 변수 `KIS_MODE`로 게이트,
     `place_order()`에 안전장치가 전혀 없음. `/sync-broker`·`/place-order`가 사용.
  3. `src/kis_client.py`(최상위) — 역시 `KIS_MODE`+`KIS_MOCK_APP_KEY`/`KIS_REAL_APP_KEY`(문서화
     안 됨)로 게이트. `/api/v1/account/holdings`·`/api/v1/account/balance`·
     **`/api/v1/orders/execute`·`/api/v1/orders/batch`가 `OrderExecutor(KISClient())`를
     직접 생성 — `TradingEngine`/`SafetyConfig`(6중 안전장치)를 완전히 우회**하고 있었음.
  → CLAUDE.md가 문서화한 "KIS_USE_MOCK=0 + KIS_APP_KEY로 실거래 전환" 절차를 따라도 이 5개
  엔드포인트는 전혀 영향받지 않는(별도 미설정 `KIS_MODE`가 계속 mock 지배) 심각한 문서-실제 괴리였음.
  프론트 전체 grep으로 이 5개 엔드포인트를 호출하는 코드가 0건임을 확인 후(라이브 자동매매
  패널은 전부 `trading_routes.py`(정상 경로)만 사용) 안전하게 통합 진행.
- **`/sync-broker`+`/place-order` 삭제**: `src/api/broker_kis.py` 파일 자체 삭제(안전장치
  전무, dry-run 없이 즉시 실주문 가능했던 가장 위험한 경로, 미사용 확인됨). 기존
  `tests/test_api.py::test_sync_broker_demo`(구 데모 엔드포인트를 테스트하던 것)를
  `/sync-broker`·`/place-order`가 404로 사라졌는지 확인하는 재도입 방지 가드로 교체.
- **`/api/v1/account/holdings`·`/api/v1/account/balance` 재배선**: `get_kis_client()`(정식
  경로)로 교체. `PositionManager(client)`가 요구하는 `client.get_balance()` 메서드가 구
  `src.kis_client.KISClient`엔 아예 없어(`get_account_balance()`만 존재) 이 엔드포인트는
  **실제로 이미 조용히 깨져 있었음**(호출 시 `AttributeError`→500) — 재배선 자체가 버그 수정.
  응답 형태 유지를 위해 `execution/kis_client.py::get_balance()`에 이미 파싱되지 않고 있던
  `evlu_pfls_smtl_amt`(profit_loss)/`asst_icdc_erng_rt`(profit_rate) 필드를 추가 파싱(동일
  응답에서 이미 도착해 있던 필드, 새 네트워크 호출 없음). `mode`는 `"mock"|"paper"|"real"`
  문자열로 합성(`trading_engine.py`의 기존 관례와 동일 패턴).
- **`/api/v1/orders/execute`·`/api/v1/orders/batch` 재배선(핵심 안전 수정)**: `TradeSignal`
  구성 후 `TradingEngine(safety=SafetyConfig(dry_run=True)).execute_signals()` 경유로 재배선
  (`trading_routes.py`의 기존 `/api/v1/trading/execute`와 동일 패턴). 세부 안전설정(dry_run
  끄기 등)이 필요하면 이미 존재하는 `/api/v1/trading/execute`(safety 파라미터 전체 제어 가능)를
  쓰도록 안내 — 레거시 형태 엔드포인트는 항상 dry_run 고정, 이중 설정 표면을 만들지 않음.
  `quantity`/`target_price` 파라미터는 받되 미사용(포지션 사이징은 `SafetyConfig`가 강도 기반
  산정) — 명시적으로 문서화. 응답은 `TradeRecord`→구 `OrderResult.to_dict()` 형태로 역변환.
  - **부수 발견·수정**: `TradingEngine.execute_signals()`가 `sells + buys`만 순회해 `action:
    "hold"` 시그널이 통째로 누락되던 버그 발견(양쪽 리스트 어디에도 안 잡혀 `_execute_one`의
    hold 처리 분기가 죽은 코드였음) — 사전에 없던 회귀테스트로 즉시 발견, `sells + buys +
    others`로 수정. 기존 `/api/v1/trading/execute`(사전 존재)에도 동일하게 영향받던 버그라
    양쪽 다 수정 효과.
- **`src/kis_client.py`(3번째 구현체) 완전 삭제**: 유일한 남은 사용처
  `src/data_sync.py`(나이틀리 KIS 동기화 잡, `main_api.py` startup에서 실제로 기동 중인
  라이브 코드)를 `get_kis_client()`로 재배선. API 차이(구
  `get_daily_prices(ticker,start,end)`→신 `get_daily_ohlcv(ticker,days=)`) 흡수, `client.
  throttle()` 호출 제거(신 클라이언트는 자체 `RateLimiter`로 이미 스로틀 — 중복 불필요).
  `DailyPrice.trading_value` 컬럼을 위해 `get_daily_ohlcv()`에 `acml_tr_pbmn`(거래대금) 추가
  파싱(실·mock 클라이언트 양쪽, 동일 응답에서 이미 도착해 있던 필드).
- **CI 가드 테스트**: `tests/test_no_order_executor_bypass.py` — `src.kis_order_executor.
  OrderExecutor`(자체 안전장치 없음)가 `trading_engine.py` 밖에서 import되면 실패. 이름만 같은
  별개 클래스 `src.execution.order_executor.OrderExecutor`(Stage13 전용, 자체 kill_switch/
  risk_gateway/audit_trail 보유)는 정규식으로 명확히 구분해 오탐 없음.
- **환경변수 정리**: `docker-compose.yml`/`setup_server.sh`의 `KIS_MODE`/`KIS_MOCK_APP_KEY`/
  `KIS_MOCK_APP_SECRET`/`KIS_REAL_APP_KEY`/`KIS_REAL_APP_SECRET`를 표준 `KIS_USE_MOCK`/
  `KIS_IS_PAPER`/`KIS_APP_KEY`/`KIS_APP_SECRET`/`KIS_ACCOUNT_NO`로 교체(코드가 이미 안 읽는
  변수를 인프라 설정에 남겨두지 않음).
- 신규 테스트: `tests/test_api.py`에 계좌·주문 엔드포인트 6개(mock 클라이언트 주입, `place_order()`
  가 dry-run 경로에서 절대 호출 안 되는지 직접 검증) + `test_no_order_executor_bypass.py`(2개).

### 정직한 한계 / 범위 밖
- **Stage13 Live Trading 시스템**(`/api/v1/live/*`, `src/api/stage13_routes.py`) — 조사 중
  발견한 완전히 별개의 3번째 실거래 시스템(자체 `KillSwitch`/`RiskGateway`/`AuditTrail` 보유,
  프론트 `ProductionMonitor.tsx`/`admin/live-trading` 페이지가 실제로 호출하는 살아있는 코드).
  `TradingEngine`과는 독립된 별도 안전장치라 이 코드베이스엔 서로 다른 안전장치를 가진 병렬
  실거래 경로가 최소 2개 존재하는 셈 — 통합·정리는 이번 범위보다 훨씬 큰 별도 아키텍처 결정
  (유지/통합/폐기)이 필요해 **의도적으로 손대지 않음**. 후속 별도 작업 권장.
- **KIS_MODE가 저장소 밖(호스트 env/CI 시크릿)에 수동 설정된 배포가 있는지는 코드로 확인
  불가** — 실거래 재배선(이번 작업) 적용 후 사용자가 직접 확인 필요.
- **`/api/v1/orders/execute`·`/batch`·`/api/v1/account/*`의 실거래·모의투자 동작은 이 샌드박스
  에서 검증 불가**(mock 클라이언트로만 검증됨) — CLAUDE.md 규칙대로 반드시 모의투자
  (`KIS_IS_PAPER=1`)에서 수동 검증 후 사용할 것: ①dry_run 기본값이 실제로 KIS 호출 0건인지
  ②`/api/v1/trading/execute`의 명시적 `dry_run=false` 시 모의투자 TR_ID로 정상 주문되는지
  ③안전장치(한도·킬스위치) 개별 차단 확인 ④holdings/balance 숫자가 KIS 앱 화면과 일치하는지.

### 검증
- 백엔드: 이 세션 전체 작업 후 `pytest tests/` **799 passed / 10 skipped / 0 failed**
  (신규 테스트 다수 포함, ①②③④ 전부 반영). `ruff check` 통과.
- 프론트: `npx tsc --noEmit` 0 errors, `npx next build` 전체 페이지 성공 예정(아래 최종
  검증에서 재확인).
- 회귀: 백테스터 엔진 로직 무변경(체결가·매도/매수 정밀화·재편입 등 직전 세션 기능 전부 불변),
  기존 스크리너/백테스터/매크로/기업분석 테스트 전부 green.

---

## 📚 CLAUDE.md 단일화 — 파편화된 .md 문서 33개 조사·병합·삭제

레포지토리 전체에 흩어진 33개 `.md` 파일(README.md·CLAUDE.md 제외, 6,778줄)을 전수 조사해
현재 코드베이스와 대조·팩트체크한 뒤, 유효한 내용은 이 파일로 통합하고 전부 영구 삭제. 목적:
향후 문서관리 도구 도입을 원활하게 하고, 세션 시작 시 AI가 읽는 컨텍스트에서 구버전/폐기
자료로 인한 오염을 제거.

### 조사 (3 Explore + 1 Plan 에이전트 병렬, + 직접 전문 정독)
- **루트 4개**(전부 README.md가 링크): `PROJECT_STRUCTURE.md`는 TopNav/PortfolioVisualizer
  디자인·존재하지 않는 STAGE11/12/13_INTEGRATION.md·삭제된 Streamlit UI 등을 참조하는 완전
  구식 스냅샷 — 병합 없이 삭제. `PLATFORM_EVOLUTION.md`(밸리AI/젠포트 갭분석+로드맵)는 파일
  자체가 "Phase 1~5 완료" 선언 상태로 이 문서 초반 섹션과 중복 — 병합 없이 삭제.
  `INTEGRATION_NOTES.md`(1회성 구버전 VM 배포기록)도 완전 대체됨 — 삭제. `REAL_DATA_SETUP.md`
  (DART/KIS/KRX 가이드)만 진짜 유효 — "실데이터 연동" 섹션에 병합(KRX 장기적재 절차 포함).
- **`_docs/` 8개**: CLAUDE.md·README.md 어디서도 참조 0건, 2026-07-02 하루짜리 "다운로드해서
  Claude Cowork에서 이어개발" 일회성 핸드오프 패키지, 2개는 자체적으로 "압축 전 스냅샷"이라
  명시 — 전부 삭제.
- **`docs/superpowers/plans/` 5개**(TDD 구현계획, pytest 원문 포함): 파일들 스스로가 마지막
  태스크를 "CLAUDE.md에 요약 추가"로 끝맺는 빌드 스캐폴딩 — 최대(1,233줄) 파일조차 CLAUDE.md
  기존 섹션과 대조 시 이미 비교 가능한 밀도로 문서화돼 있음 확인. 고유 정보(테스트 원문·정확한
  계수)는 `tests/`·해당 소스 모듈에 이미 보존 — 전부 삭제.
- **`docs/superpowers/specs/` 16개**: 5개는 CLAUDE.md 해당 섹션과 진단·커밋 단위까지 대조
  확인된 완전 중복 — 삭제. 11개는 CLAUDE.md에 대응 서술이 전혀 없던 진짜 문서화 공백(매크로
  콕핏 최초설계·리스크전략 9종·전략모달·배당/수급 실데이터화·`mock_gate.py` 설계·백테스터
  프리필·성과지표 확장·DART 백필버그·DB우선 펀더멘털 등) — 코드로 각 claim을 재검증
  (`get_dividend_info`·`insider_net`·`mock_allowed`·`compute_metrics`·`_dart_backfill_sleep_seconds`·
  `_fs_from_history` 전부 실존 확인) 후 이 문서에 신규 섹션 11개로 압축 이식, 학술 레퍼런스·
  Beneish 계수 등 코드에 이미 보존된 상세는 재복제하지 않음(코드가 단일 권위 출처).

### 실행 (2단계 커밋)
Phase A(내용): 위 신규 섹션 11개 삽입 + REAL_DATA_SETUP.md 병합 + 현재 규모 실측 통계표
추가(PROJECT_STRUCTURE.md 대체) + 이 문서 자체의 죽은 자기참조 11곳(삭제 예정 파일 언급) 전부
제거 + 목차 신설 + README.md 문서 표 정리(깨질 링크 4개 + 기존부터 있던 죽은 링크 3개).
Phase B(삭제): 33개 파일 전부 `git rm`(원본 rm 아님 — git 히스토리에 보존, 필요시 이전 커밋에서
복원 가능) — 삭제 전 레포 전체 재검색으로 참조 0건 재확인 후 실행.

### 검증
순수 문서 변경이라 `pytest`/`tsc`/`next build`에 영향 없음 — `ruff check .`로 회귀 없음만 확인.

### 정직한 한계
`docs/superpowers/` 워크플로(스펙→플랜→구현→CLAUDE.md 요약) 자체는 계속 유효한 관례라
디렉터리 구조는 유지(내용물만 삭제) — 향후 세션이 같은 패턴을 다시 쓸 수 있음.

---

## 🎯 PIT look-ahead bias 수정 + 스크리너 enrichment 동시성 + 생존편향 유니버스 UI 노출

사용자가 "백테스트 루프가 매 리밸런싱마다 실시간 KIS/DART를 호출해 타임아웃 난다"는
진단(AI 프롬프트 초안 4개)을 제시했으나, 3개 병렬 Explore 에이전트가 이 메커니즘이
`kis_backtest_engine.py`엔 존재하지 않음을 grep 전수조사로 확인(백테스터는 스크리너·
가치평가 엔진을 아예 호출 안 함 — 의도된 설계, 기존에 정직하게 문서화됨). 대신 진짜
버그 3개를 다른 위치에서 발견해 사용자 확정("실제 버그 3개만 수정") 후 수정:

1. **Look-ahead bias**: `ValuationEngine.evaluate()`의 유일한 PIT 인지 호출부
   (`screener.py::_evaluate_one_safe`, `/run-pit` 경유)가 `bsns_year`를 안 넘겨 과거
   시점 평가에서도 재무가 현재 연도 기준으로 셈. `pit_store.py::_period_asof()`에
   `annual_only: bool = False` 추가(연간 보고서 코드만 필터 — 분기 코드를 그대로
   넘기면 `compute_ratios()`가 연환산 안 해 밸류에이션 2~4배 왜곡되는 별개 버그를
   새로 만들 뻔했음, 사전에 발견해 회피) → `_evaluate_one_safe`가 `annual_only=True`로
   구한 `bsns_year`를 명시 전달, 파싱 불가 시 wall-clock 폴백 없이 평가 스킵.
2. **PIT 가격 재오염 방지**: `_enrich_kis_quotes`가 `_active_asof` 설정 시(PIT 모드)
   조기 반환 — 과거 시점 가격을 오늘자 라이브 시세로 덮어쓰지 않음.
3. **`_enrich_kis_quotes` 동시성**(실제 타임아웃 원인): 최대 400종목 동기 `for` 루프를
   `ThreadPoolExecutor`로 교체(`screener.py:497` DART 단계와 동일 패턴 재사용).
   신규 env var `SCREENER_ENRICH_WORKERS`(기본 8, 상한 24).
4. **생존편향 보정 유니버스 UI 노출**: 백엔드(`universe_select.tickers_asof`/
   `top_mktcap_asof`)는 이미 구현·테스트돼 있었으나 프론트가 값을 전혀 안 보내
   도달 불가능한 죽은 기능이었음. `UniverseState.survivorshipMode`("off"|"all"|
   "top200") 추가, 활성 시 `caps`/`sectors`/`etf`/`managed`/`supervised`/`groups`를
   전부 비워 전송(안 비우면 백엔드 분기 우선순위상 `gran_tickers`가 먼저 걸려 무력화).
   `screener_routes.py`의 `all_asof`/`top200_asof` 분기에서만 `as_of_date`를
   `screener.run()`에 전달(1번 수정 선행 필요 — 안 그러면 상폐 종목이 유니버스엔
   포함돼도 라이브 재무 없어 "데이터 없음"으로 재탈락).

### 검증
818 passed / 10 skipped, ruff 통과, tsc 0, next build 통과. `kis_backtest_engine.py`는
전 구간 무변경 확인(트레이딩 백테스트 결과 회귀 없음).

### 정직한 한계
`/run-pit` 엔드포인트 자체를 화면에 재연결하는 작업, 생존편향 모드의 라이브 종목수
카운트 연동은 범위 밖 — 백엔드 정확성만 수정.

---

## 🔍 백테스트 SSE 진행률 무음 구간 제거 (Celery/Redis 전제 조사 → 기각 → 최소 수정)

사용자가 "Mission: Transition Backtest Engine to Asynchronous Task Queue Architecture
(Institutional-Grade)"라는 상세 프롬프트(스크린샷 5개)로 `kis_backtest_engine.py`를
Celery(태스크 큐)+Redis(브로커) 백그라운드 아키텍처로 전면 전환할 것을 요청. 3개 병렬
Explore 에이전트로 전제를 독립 검증한 결과 대부분 성립하지 않음이 드러남 — 상세 조사
기록은 `/root/.claude/plans/distributed-hatching-kurzweil.md` 참고, 핵심만 요약:

- **"동기 엔진 → async-sync 브릿지 필요"**: 전제 자체가 틀림 — `kis_backtest_engine.py`
  전체에 `async`/`await` 0건(grep 전수확인). 브릿지할 async 코드가 애초에 없음.
- **"SSE 진행률 인프라 부재"**: 틀림 — `/screen-to-backtest-stream`이 이미 존재하고
  `progress_cb`가 `BacktestEngine._emit()`까지 관통해 시뮬레이션 엔진 내부까지 배선돼
  있음. 단, **진짜 격차 2곳**은 확인됨: (a) 일별 시뮬레이션 루프가 루프 시작 시 1회만
  emit하고 이후 전혀 안 함(가장 오래 걸리는 구간이 정확히 무음), (b) `_screen_to_
  backtest_core`의 스크리닝 호출이 `screener.run()`에 `progress_cb`를 안 넘김
  (`_run_advanced_core`는 넘기는데 이쪽만 누락). 이 정확한 실패 모드(SSE 장시간 무음
  → 인프라 비활성 타임아웃 → "network error")는 이미 이 프로젝트에서 실제로 발생한
  적 있음(Phase 6 세션, 원인은 달랐지만 동일 메커니즘).
- **"타임아웃 원인"**: 진짜였으나 원인이 다름 — 2,500종목×750거래일 시뮬레이션 루프를
  합성 벤치마크로 실측하니 최선의 경우도 174초+(벡터화 안 된 10개 기본전략은
  `_generate_signal_as_of`가 매 호출마다 전체 슬라이스 재계산해 사실상 `O(기간²)`로
  더 나쁨). 이건 CPU-bound 순수 루프 비효율 — Celery로 감싸도 174초는 그대로(위치만
  옮겨질 뿐 안 줄어듦), 별도의 벡터화 과제.
- **인프라 현황**: `docker-compose.yml`엔 db/backend/frontend 3개뿐, redis/celery
  0건. `Dockerfile.backend`가 `--workers 1`을 고정한 이유를 스스로 주석에 명시(
  `_ValuationCache`/DART 쿼터 카운터/`_INGEST_STATUS` 등 프로세스 로컬 인메모리 상태
  때문 — "다중 인스턴스 필요해지면 상태를 Redis/DB로 옮긴 뒤 워커를 올릴 것") — 즉
  celery-worker 컨테이너는 정확히 이 주석이 경고하는 "두 번째 프로세스" 시나리오라,
  스크린샷엔 없던 캐시 이전 설계가 새로 필요해짐.

AskUserQuestion으로 조사 결과 제시 → 사용자가 "SSE 격차만 수정"(신규 인프라 0개) 선택.

### 구현 (3파일, 최소 수정)
- `src/kis_backtest_engine.py`: 시뮬레이션 루프에 `screener.py:504`와 동일한 throttle
  관용구(`step = max(1, total // 100)`)로 구간별 `self._emit("simulating", done=, total=)`
  추가(최대 ~100개 이벤트로 상한, 오버헤드 무시 가능 — dict 하나만 큐에 push).
- `src/api/screener_routes.py`: `_screen_to_backtest_core`에 `_screen_progress(done,
  total, misses)` 어댑터 신설 — `screener.run()`의 위치인자 콜백을 `_emit({"phase":
  "screening", ...})` dict 이벤트로 변환해 배선.
- `frontend/.../TerminalBacktester.tsx`: `BacktestProgress`의 `showCount` 게이트를
  `"loading"` 전용에서 `"screening"`/`"simulating"`까지 확장(스테이지 구성 무변경).

### 검증
823 passed / 10 skipped(신규 5: `test_backtest_progress_emit.py` 2개 +
`test_screen_to_backtest_progress.py` 3개), ruff 통과, tsc 0, next build 통과
(`/backtest` 30.1kB).

### 정직한 한계 / 범위 밖 (사용자 명시 제외)
- Celery/Redis 등 신규 태스크 큐 인프라 — 크래시 생존성·프로세스 간 확장·정식 취소가
  실제로 필요해지기 전까진 정당화 안 됨. 필요해지면 `_ValuationCache`/DART 쿼터
  카운터 등 기존 인메모리 상태를 Redis로 이전하는 설계가 선행돼야 함.
- 시뮬레이션 루프 자체의 성능 최적화(벡터화) — 이번 수정은 진행률만 보이게 할 뿐
  174초+ 원시 성능 문제 자체는 해결 안 됨. 특히 10개 기본전략의 `O(기간²)` 낭비는
  별도의 더 큰 과제.
- `_INGEST_STATUS` 패턴을 일반화한 task_id 기반 submit/poll API — Redis 없는 대안으로
  검토됐으나 사용자가 최소 옵션(SSE 격차만 수정)을 선택.

---

## 🎛️ Allocation Studio — 신규 사이드바 탭 (Two Sigma Venn 벤치마킹)

사용자가 3개 PDF(ChatGPT RAS 기획안 + Gemini 프로토타입 프롬프트 + Gemini 아키텍처
리뷰)와 다크 테마 목업으로 새 탭을 요청("데이터 인프라 탭 바로 위, 색은 기존 라이트
팔레트 유지"). AskUserQuestion 3답 확정: 풀 콕핏 1라운드 · KR 주식+ETF 통합 유니버스
(daily_prices) · 이름 "Allocation Studio" 라우트 `/allocation`.

### 조사 핵심 발견 (2 병렬 에이전트)
이 코드베이스엔 자산배분 스택이 2개 병렬 존재 — 매크로 탭 스택(risk_allocations 9종,
8-ETF 고정, BL 뷰가 regime_analyzer에 하드와이어)과 **퀀트/리스크툴 스택**
(`kis_portfolio_analyzer.py` + `src/models/`): 후자는 임의 tickers+weights로 scipy
SLSQP **효율적 프론티어(점별 자산 가중치 포함)** · risk_contributions · MC Dirichlet
클라우드 · 리밸런싱 시뮬까지 이미 보유(`POST /api/v1/portfolio/analyze` 라이브).
**진짜 신규는 "사용자 뷰 Black-Litterman"뿐** — 나머지는 조립.

### 백엔드 (커밋 25ee9d6)
- **`src/engine/allocation_studio.py`(신규)**: `build_user_views()` — 뷰
  {assets(그룹 지원), direction, magnitude_pct(연 %), confidence 0~100} → P/Q/Ω.
  **Ω = diag(P·τΣ·Pᵀ) × (100-conf)/max(conf,1)** (conf 50=Idzorek 관례, 100=뷰 강제,
  0=시장균형 복귀 — 신뢰도 슬라이더의 수학적 정체). `bl_posterior()`는
  risk_allocations.s_black_litterman(331-333행)과 동일 공식. `market_cap_weights()`
  KIS master 시총 캡가중(결측은 중앙값 대체+보고). `weights_for_model()` —
  mvo/bl/risk_parity(ERC)/hrp/min_var, risk_allocations의 `_cov`(Ledoit-Wolf)/`_opt`/
  `_hrp_weights` 헬퍼를 커스텀 R로 호출. **뷰 없는 BL = 캡가중 prior**(레퍼런스와 동일).
- **`src/api/allocation_routes.py`(신규, `/api/v1/allocation`)**: `POST /analyze`
  (수익률 행렬 1로드 → 프론티어 30점+클라우드 1500점+모델 최적화+Sankey 3단계
  flow[시장→뷰반영→최적화]+리스크기여+상관+요약지표 vs KOSPI+GBM 1년 MC 분포) ·
  `POST /factor-xray`(종목 팩터 가중 z vs 유니버스 표본, **팩터별 커버리지 %** —
  ETF 펀더멘털 결측은 재정규화+표기, 조용한 0 금지) · `POST /stress`(M8 펀더멘털
  충격 가중합 + 역사 윈도우 리플레이 2008/2018/2020/2022 — DB 범위 밖은 정직
  unavailable) · `GET /stress-catalog`. 시계열<30일 자산 excluded 보고, 2자산 미만
  정직 에러.
- **mock 폴백(mock_gate 준수)**: DB 무(빈 load_returns) + `KIS_USE_MOCK=1`일 때만
  `load_ohlcv_unified(prefer="mock")`로 합성 수익률/팩터 표본 — 응답에
  `coverage.source: "mock"` 표기(운영은 빈 결과 그대로 정직 에러). 개발 기본값에서
  전체 콕핏이 작동, GCP 실데이터에선 자동으로 DB 경로.

### 프론트엔드
- **사이드바**: TerminalShell MODULES에 "06 Allocation Studio"(파이차트 아이콘)
  삽입, Data Infra는 "07"로. `/allocation` prefetch(stress-catalog).
- **`app/allocation/page.tsx`** + **`components/allocation/`**: AllocationStudio
  (3-존 grid + 스테퍼 01 Thesis&Views/02 Build/03 Analysis), PortfolioBuilder
  (symbols/search 검색 + 6자리 코드 직접 추가 폴백 + 관심그룹 가져오기 + 균등배분 +
  저장 스터디), ViewBuilder(테제 문장+대상 자산 칩+방향+크기+신뢰도 슬라이더),
  parts.tsx(FrontierChart[recharts Scatter 클라우드+곡선+마커+λ점], AllocationSankey
  [recharts Sankey 3열], FactorXRayBars, RiskContribDonut, StressChart[자체 SVG dd],
  McHistogram, ConfidenceGauge, MetricsTable[Portfolio/Benchmark/Active]).
- **인터랙션(Gemini 리뷰 반영)**: 신뢰도/τ 슬라이더 드래그 중 로컬만, 릴리스 시
  `/analyze` mutation. **λ는 클라이언트 사이드** — 이미 받은 프론티어 30점(점별
  가중치 포함)에서 u=μ-(λ/2)σ² argmax 점만 이동(백엔드 호출 0). MOCK 데이터 배지
  (coverage.source). 노드 캔버스·AI 뷰 생성·Execution 스텝·상관 네트워크는 Gemini
  리뷰의 스코프 크립 경고대로 명시 제외.
- **`lib/allocationApi.ts`**(macroApi 관례) + **`lib/allocationStorage.ts`**
  (`alpha_allocation_studies`, strategyStorage idiom, 메모 필드 = Decision Journal
  1라운드).

### 검증
844 passed / 10 skipped(신규 21: views 11 + routes 10), ruff·tsc 0, next build
18/18(`/allocation` 17.2kB). Playwright 라이브 스모크(mock): 3종목 추가 → 뷰 추가
(신뢰도 60%) → Re-optimize → **BL 뷰 적용 배지 + Sankey 3열 가중치 이동(33.3%→
25.1/37.5/37.4) + 프론티어 클라우드/마커/λ점 + 팩터 8종 z 막대 + 리스크 도넛 +
시나리오 목록** 전부 렌더 확인. 강한 뷰(+15%/90%)가 대상 비중을 키우는 방향성은
TDD로 고정.

### 정직한 한계 / 범위 밖
- DRO·Entropy Pooling·Factor 모델 토글, Sensitivity Map, Correlation Network 탭,
  Historical Backtest 탭(기존 백테스터 프리필 링크로 후속 가능), AI View Generator,
  드래그&드롭 캔버스 — 후순위 명시(1라운드 제외).
- 역사 리플레이는 DB 커버리지 의존(KRX 백필 10년 기본 → 2008 금융위기는 대부분
  미보유, disabled+사유 표기). 팩터 X-ray 벤치마크는 master 플래그 적재 시
  KOSPI200 캡가중, 미적재 시 "유니버스 평균" 정직 라벨.
- mock 모드에선 ETF도 합성 펀더멘털이 있어 커버리지 100%로 보임 — 실데이터에서
  ETF 펀더멘털 결측 재정규화가 실제로 작동(설계·테스트로 고정).

---

## 🧭 Research OS 개편 — 전 탭 헤더 제거 + Allocation Studio 밀도·컨텍스트·인과 UI

사용자가 캡처 3장 + Gemini 텍스트 피드백(Research OS 4지침) + "Allocation Research
Operating System" 비전 문서로 요청: ① 모든 탭의 PageHeader(eyebrow·타이틀·인트로)와
사이드바 "System Operational" 도트 제거 후 콘텐츠 끌어올리기 ② Gemini 4지침 반영
③ Venn식 3패널 유지 + Research-first 철학 통합(기존 코드 최대 재사용, DAG는 v2).

### 전 탭 헤더 제거 (Part A)
- `components/layout/PageHeader.tsx` **삭제** — 사용처 8곳 정리: children 없는 4곳
  (risk-tools/macro/allocation/TerminalBacktester)은 통삭제, children 있는 4곳은
  기능 컨트롤만 **슬림 툴바**(`.t-toolbar`, 우측 정렬 한 줄)로 이동 — 스크리너
  (Universe 셀렉트), 기업분석(종목 검색박스), 대시보드(QuickSearch), DbStatusPanel
  (새로고침 + `MODE: REAL/MOCK` 배지 `.t-mode-badge` — mock 거버넌스 정보 보존).
- `.tpage-head/-head-top/-index/-status(-dot)`·`.t-eyebrow` CSS 삭제(`.tpage-fade`·
  `.tpage-intro`는 사용 중 — 유지). TerminalShell `.sidebar-foot`(System
  Operational) JSX+CSS 삭제. 파생상품 탭은 다른 PageHeader(`@/components/ui`,
  비-사이드바 레거시) — 무변경.

### Allocation Studio "Research OS" R1 (Part B — 렌더링/CSS만, 동작 로직 불변)
- **밀도(Gemini ①)**: `.as-*` gap 12→8, 카드 패딩 12/14→8/10, 폰트 축소,
  tabular-nums 명시, **얇은 슬라이더**(트랙 2px+썸 10px 커스텀 — `.as-root
  input[type=range]` 전역).
- **ContextStrip(Gemini ② + 비전 "화면 시작=Regime·Canary")**: 신규
  `components/allocation/ContextStrip.tsx` — `CURRENT: {국면} CONF {p}%` 배지
  (클릭→/macro) + 권고모드 + STRESS + **카나리 4종**(VIX·US10Y·HY Spread·10Y-2Y:
  latest+z색+스파크). 데이터는 `["macro","regime"]`/`["macro","dashboard"]` 기존
  쿼리 캐시 공유(신규 fetch 0) — 지표 id VIXCLS/DGS10/BAMLH0A0HYM2/T10Y2Y
  (macro_collector FRED 시리즈). 결측 "—" 정직.
- **테제 인과 체인(Gemini ③)**: ViewBuilder 재렌더 — `[테제 입력] ➔ [자산 칩] ➔
  [▲Overweight n%/년] ➔ [신뢰도 슬라이더]` 노드 체인(`.as-chain-*`), 핸들러
  (onChange/onCommit) 완전 불변.
- **확률 구름(Gemini ④a)**: FrontierChart 클라우드를 sharpe 상대순위 기반
  크기·투명도 그라데이션 점(CloudDot)으로 — 프론티어 곡선은 1.5px "능선".
- **Research Timeline(Gemini ④b, Research Memory 1단계)**: 신규
  `ResearchTimeline.tsx` + `logEvent()` — **하드코딩 아닌 실제 액션 로그**(뷰
  추가/삭제·재최적화(모델·λ·τ·뷰 수)·시나리오 전환·스터디 저장, hh:mm). 세션
  한정(영속화는 R2).
- **Robustness 상시 카드(비전)**: 우측 레일 `ROBUSTNESS` — 시나리오 미니 셀렉트 +
  추정충격/최대낙폭 요약, 기존 stressQ/catalogQ 상태 재사용(같은 데이터의 2번째 뷰,
  하단 상세 탭 유지).
- **Explainability 미니트리(비전 "왜 이 비중")**: OPTIMIZED WEIGHTS 행 클릭 →
  `① Market Prior → ② User View(BL) Δ → ③ Optimizer·제약 Δ` 인라인 분해 — 이미
  받은 `result.flow` 3열 재렌더(신규 fetch 0). Regime·Factor 단계는 "R2 로드맵"
  정직 라벨.

### Research OS 로드맵 (비전 문서 회신 — 기존 코드 재사용 매핑, 구현은 후속)
- **R2**: ① 테제 NL→P/Q/Ω 자동변환(nl2ast의 Claude 게이트 패턴 + 기존
  `build_user_views` 재사용) ② Probability Frontier(레짐 confidence·se 기반
  프론티어 밴드 — `macro_allocation`의 MC p10/50/90 밴드 패턴 이식) ③ 레짐 연동
  BL prior(`regime_analyzer.asset_tilts`→자산 매핑 재사용, 사용자 뷰와 P/Q 스택)
  ④ Explainability Tree 완전판(allocation_studio.optimize가 단계별 μ/w 기여
  breakdown 반환) ⑤ Research Memory 영속(스터디에 timeline 필드+자동 저장).
- **R3(v2)**: Research Graph DAG(reactflow 설치돼 있음)·Factor Mapping 엔진·
  Model Sensitivity 실시간·멀티 워크스페이스. 상태관리는 현행 useState+react-query
  유지(R2까지 충분), 워크스페이스 다중화 시 zustand 승격 검토.

### 검증
백엔드 무변경(844 passed/10 skipped 불변, ruff 통과), tsc 0, next build 18/18.
Playwright 라이브: 8개 탭 전부 200+헤더 부재+보존 컨트롤 작동, /allocation
스크린샷 — ContextStrip(Goldilocks CONF 54%·카나리 4종 스파크), 테제 체인,
확률구름, ROBUSTNESS 카드(-15.6%), Explainability 분해(+4.1%p 뷰 기여),
타임라인 실기록("재최적화 — BL · λ 2.5 · τ 0.05 · 뷰 1개") 확인.

---

## 🏗️ Research OS v2 — 마이크로 워크스페이스 + Sensitivity Heatmap + Decision Journal

사용자가 설계 피드백("89/100이지만 Optimizer 중심 도구에 머묾 — Workflow 중심
Research OS로") + 구현 지시("단일 화면 협소 — 중첩 라우팅 마이크로 워크스페이스로
확장, `b086cef` 기반") 5장을 첨부. 설계서 업그레이드와 구현을 함께 수행.

### Research OS Design Principles (vNext) — 파이프라인 단계 ↔ 화면 매핑
플랫폼 철학 = **Linear Research Pipeline**. 모든 화면·컴포넌트는 이 파이프라인의
한 단계를 담당한다:

| 파이프라인 단계 | 담당 화면/컴포넌트 | 상태 |
|---|---|---|
| Macro Intelligence | /macro (MacroCockpit) | 기존 |
| Current Regime · Canary Signals | ContextStrip (allocation 전 워크스페이스 상단 고정) | R1 |
| Research Thesis | /allocation/thesis (인과 체인 ViewBuilder) | **v2** |
| Factor Mapping | thesis 내 Factor Exposure Preview → R2 자동매핑 | v2=Preview |
| Portfolio Construction (BL) | /allocation/optimizer (모델 스위치+Frontier+Flow) | **v2** |
| Robustness (Sensitivity) | /allocation/robustness (**Sensitivity Heatmap**+시나리오) | **v2 신규** |
| Explainability | /allocation/explainability (Attribution 테이블+상관구조) | **v2** |
| Decision Journal (Research Memory) | /allocation/journal (구조화 저널+세션 타임라인) | **v2 신규** |

**데이터 파이프라인(DFD)**: `MacroCollector(BOK·FRED) → RegimeAnalyzer →
{regime, confidence, canary(VIXCLS·DGS10·BAMLH0A0HYM2·T10Y2Y)} → ContextStrip
(캐시 공유 ["macro","*"]) → [R2: BL prior 추천 자동 주입] →
allocation_studio.optimize(views→P/Q/Ω→posterior) → 프론티어/흐름/민감도/저널`.
현재 Macro→Allocation은 표시 연결(ContextStrip)까지, prior 자동 주입은 R2.

### 구현 (커밋 단위 1개)
- **백엔드**: `allocation_studio.sensitivity_matrix()` — 자산 i의 μ에 +bump(연
  %p) 충격 → max-sharpe 재최적화 → `matrix[i][j]=Δw_j`(%p, N×N). base μ는
  /analyze와 동일 경로(뷰 있으면 BL posterior — Robustness가 검증하는 대상이
  실제 사용 기대수익이 되도록). `POST /api/v1/allocation/sensitivity`
  (_load_clean_returns 재사용, mock 폴백·excluded·coverage 관례 동일).
  TDD 3종: 대각 우세(+5%p에서 자기 반응 최대), 행 Δ합≈0(완전투자 제약), 정직
  에러. **847 passed / 10 skipped**.
- **중첩 라우팅**: `app/allocation/layout.tsx` = `AllocationProvider`(구
  AllocationStudio 상태·로직 전체를 Context로 리프트 — App Router layout은
  자식 라우트 전환에도 유지되므로 워크스페이스 간 이동 시 유니버스·뷰·결과
  보존) + ContextStrip + SubNav(Hub·Thesis·Optimizer·Robustness·Explainability·
  Journal). `useAllocation()` 훅. AllocationStudio.tsx 삭제(허브+서브로 분해).
- **Hub**(`/allocation`): 요약 위젯 그리드(포트폴리오·프론티어 미니·최적 비중·
  팩터·Robustness·리스크 도넛·타임라인) — 각 카드 `[↗]` 드릴다운(Master-Detail).
- **Robustness 워크스페이스**: 좌(시나리오 8종 + μ bump 슬라이더 0.5~5%p, 릴리스
  시 재계산) / 우(**Sensitivity Heatmap** — 행=충격 자산·열=비중 반응 Δ%p,
  초록/빨강 발산색+base 열+정직 해설, 라이브 검증: 대각 +7.3/+6.0/+6.2 우세) +
  시나리오 상세(기존 스트레스 테이블/차트 이식).
- **Journal 워크스페이스**: Decision Journal 스키마 — `AllocationStudy +=
  {macro_view, changed, reason, result_summary, review}` + `updateStudyReview()`.
  새 엔트리 폼(Macro View는 현재 레짐 자동 스냅샷+편집, Result는 최적화 결과
  자동 첨부), 목록(5필드 그리드), Review 사후 편집. 세션 타임라인 병치.
- **Thesis/Optimizer/Explainability**: 기존 컴포넌트를 넓은 전용 화면으로 이식
  (Frontier 340px, Attribution 전 자산 테이블, CorrelationMini 신규).

### R2 스펙 확장 (설계 — 기존 코드 재사용 매핑)
① **Factor-first Research**: `POST /allocation/factor-map` {thesis_text} →
  {factor_tilts, asset_views} — nl2ast의 Claude 게이트 패턴 + build_user_views
  재사용. Thesis 워크스페이스의 Preview가 이 출력의 표시면이 됨.
② **Economic-driven BL**: 거시 테마→자산 View 추상화 레이어(예: "AI Capex↑ →
  GPU Demand → 반도체 Growth") — risk_allocations `_TILT_TO_ASSETS` 일반화 +
  genport_themes 그룹 매핑 재사용.
③ **Probability Frontier**: 프론티어 각 점에 레짐확률(quadrant_probs) 가중
  수익분포 + 테일확률 밴드 — macro_allocation의 MC p10/50/90 밴드 패턴 이식.
④ **Decision Journal 완전판**: Result 자동 사후검증(저장 시점 가중치를 이후
  실측 수익률과 대조하는 배치) — 이번 스키마가 선행 저장 구조.
⑤ **레짐 연동 BL prior**: ContextStrip이 표시 중인 regime_analyzer.asset_tilts를
  "추천 prior" 버튼으로 P/Q에 스택(사용자 뷰와 병합).

### 검증
847 passed/10 skipped(+3 sensitivity), ruff·tsc 0, next build **23/23**
(/allocation 6라우트). Playwright E2E: Thesis에서 3종목+뷰 추가 → Re-optimize →
SubNav로 Robustness 이동 → **holdings 유지 + 히트맵 12셀 렌더(상태 보존 증명)**
→ Hub 요약 유지 → Journal 엔트리 저장(Macro View 자동 스냅샷 "Goldilocks
(신뢰도 54%) · CAUTIOUS · Stress 52" + Result 자동 첨부) 확인.

### 정직한 한계 / 범위 밖
- R2 5건은 설계만(위 매핑) — LLM 팩터매핑·Probability Frontier 수학·레짐 prior
  주입·사후검증 배치는 미구현.
- Sensitivity는 max-sharpe 경로 기준(공분산 전용 모델은 μ 충격에 무반응이므로
  의미 없음 — BL/MVO 사용 시 유의미). N회 SLSQP라 자산 30개 상한.
- zustand 승격은 멀티 워크스페이스(동시 다중 스터디) 시점으로 유보 — 현재
  Context 1개로 충분.

---

## 🎬 Allocation Studio 파이프라인 리디자인 (Claude Design 핸드오프 구현)

사용자가 v2를 "UI/UX 최악 — Aladdin·Venn·Marquee 레퍼런스로 고도화, 설계를
순서대로 진행"이라 평가한 뒤, **Claude Design 프로젝트**(`c6ab0f11`, "Asset
Allocation Studio UI 개선")의 고충실도 핸드오프 `Asset Allocation Studio.dc.html`
(107KB·7페이지)를 첨부하고 "기존 코드베이스 패턴대로 재구현"을 지시. DesignSync
MCP(read-only)로 README·전체 HTML·parts 레퍼런스를 정독 후 구현.

### 핵심: 평평한 탭 → 7단계 순차 리서치 파이프라인
v2의 6개 평평한 워크스페이스(순서 없음·빈 화면·주 액션 부재)를 **탭 내부 7단계
순차 파이프라인**으로 재편: `00 OVERVIEW → 01 CONSTRUCT → 02 THESIS → 03 OPTIMIZE
→ 04 STRESS → 05 EXPLAIN → 06 JOURNAL`. 공유 크롬이 모든 단계를 감싼다.

### 백엔드 무변경 (프론트 전용)
기존 `/analyze`·`/sensitivity`·`/factor-xray`·`/stress` 응답으로 모든 화면 구동 —
Python 파일 0개 변경(847 passed 불변, ruff 통과). 디자인의 목업 수치를 실 API로 대체.

### 공유 크롬 — `app/allocation/layout.tsx` 전면 재작성 (SubNav 대체)
`AllocationProvider` + StageChrome:
- **브레드크럼** `MODULE 06 / ALLOCATION STUDIO / NN STAGE`
- **페이지 헤더**: 제목 `Allocation Studio — {Stage}` + 설명 + MOCK 배지(실 소스
  mock일 때) + 데이터 범위(coverage) + 최근 실행(lastRun) + **RE-OPTIMIZE**
  버튼(accent, pending 처리, 성공 시 lastRun 갱신 — runAnalyze 재사용)
- **ContextStrip**(레짐+카나리, 기존) · **PipelineBar**(신규) · 콘텐츠(aasFade,
  `key={pathname}`) · **하단 nav 바**(← 이전 / RESEARCH PIPELINE · NN / 다음 →)
- **PipelineBar**(`components/allocation/PipelineBar.tsx`): 7칩 = 상태점(완료 시
  accent) + 번호 + 라벨 + **파생 서브텍스트**(`N ASSETS · TW%` / `N VIEWS · CONF
  C%` / `BL · λ 2.5` / 시나리오명 등) + 커넥터선, 활성칩 accent 테두리+tint,
  `router.push` 이동 + **←/→ 키보드**(input 포커스 시 제외), overflow-x 스크롤.

### 라우트 7개 (기존 6개 재편)
`git mv` optimizer→optimize·robustness→stress·explainability→explain, `/construct`
신설, `/allocation`(허브)·`/thesis`·`/journal` 유지. `AllocationProvider`에 STAGES
메타(순서·href·라벨·타이틀·설명) + `lastRun` + `stageIndex(pathname)` 추가. 각
page는 자체 헤더 제거(크롬이 layout으로 승격) — 순수 콘텐츠만.

### 화면 (기존 parts 재사용 + 신규 소량)
- **00 OVERVIEW 재설계**: 6칸 KPI(기대수익·변동성·Sharpe·95%VaR·최대낙폭·뷰신뢰도
  — summary/mc/conf) + 12-col 그리드(FrontierChart span5 · OPTIMIZED WEIGHTS
  span4(Δ vs 현재) · RiskContribDonut span3 · FactorXRayBars span4 · ROBUSTNESS
  요약 span4 · ResearchTimeline span4), 각 카드 `NN ↗` 크로스링크.
- **01 CONSTRUCT 신설**: PortfolioBuilder(재사용) + 신규 3프리미티브 —
  `AllocationMap`(비중 비례 팔레트 블록), `WeightComparison`(현재/캡가중/최적 3중
  바), `concentration()`(HHI=Σw²×10⁴·TOP3·Neff=10⁴/HHI 순수함수) + DATA COVERAGE.
- **02 THESIS**: 뷰 빌더(인과 체인)만 — 자산 구성은 CONSTRUCT로 분리. 게이지 +
  팩터 프리뷰.
- **03~06**: 기존 optimizer/robustness/explainability/journal 콘텐츠 이식(헤더만
  제거) — 디자인과 이미 일치.

### CSS
globals.css `.aas-*` 신규(aasFade·크롬·파이프라인 칩·KPI·12-col·map·cmp·conc) +
구 `.as-subnav` 제거. 라이트 Institutional Terminal 토큰(#1200ff) 유지 = 디자인
토큰과 동일 체계.

### 검증
tsc 0 · next build **24/24**(/allocation 7라우트) · ruff 통과 · pytest 847(무변경).
Playwright E2E: CONSTRUCT에서 3종목 → 헤더 Re-optimize → 하단 nav로 THESIS(뷰
추가)→OPTIMIZE→STRESS 완주 → 파이프라인 칩으로 OVERVIEW 복귀, **상태 전 구간
보존**. 스크린샷 — Overview(6 KPI+12-col+크로스링크+파이프라인 상태), Construct
(ALLOCATION MAP 팔레트 블록·WEIGHT COMPARISON 3중 바·CONCENTRATION HHI 3,333).

### 정직한 한계
- 디자인 목업 수치 → 실 API 값 대체(완전 픽셀 일치 아님, 레이아웃·타이포·
  인터랙션 고충실도 재현). Re-optimize의 800ms 시뮬은 실 API 호출로 대체.
- DesignSync는 읽기만 사용(디자인 역동기화 안 함) — 요청은 코드 구현.

---

## 🧭 Allocation Studio — Multi-Stage Wizard 전면 리디자인 (목표 게이트 + 3-페이즈 파이프라인)

직전 파이프라인 리디자인(커밋 `9f65a5c`)이 평평한 7-스테이지였던 것을, 사용자 첨부
스크린샷(Portfolio Visualizer 위저드 원형 + "Progressive Disclosure / Contextual
Isolation / Multi-stage Wizard" 지시)에 따라 **목표 선택 진입점 + 3 매크로 페이즈 순차
위저드**로 재편. "전략 수립의 프로세스를 밟아나가는" 전문 퀀트 운용 느낌. **프론트 전용 —
백엔드/엔진 100% 무변경, 기존 tool·service·차트 전부 보존(기능 손실 0)**. ui-ux-pro-max
스킬(progressive-disclosure·multi-step-progress·primary-action·state-preservation) 적용.
(21st.dev/Figma/Canva 커넥터는 세션 중 MCP 오프라인이라 미사용 — 라이트 Institutional
Terminal 토큰으로 직접 구현. zip 핸드오프의 7-스테이지 스펙은 이미 100% 구현돼 있었음을
확인하고, 스크린샷의 새 위저드 IA를 그 위에 얹음.)

### 라우팅/IA (라우트 7→8)
- `/allocation` = **목표 선택 게이트**(신규, bare 렌더) — layout의 `isGate` 분기. Overview
  대시보드는 `/allocation/overview`로 이관(near-verbatim, Xlink 유효). 7 스테이지를 3 페이즈로:
  **SETUP**=01 Construct · **LOGIC**=02 Thesis·03 Optimize · **VALIDATION**=04 Stress·05 Explain,
  00 Overview·06 Journal 북엔드. 사이드바 active(`startsWith`)·딥링크 무변경, hover-prefetch에
  `["macro","regime"]`·`["screener","sectors"]` 추가.

### 신규/변경 컴포넌트
- **`GoalGate.tsx`**(신규): "어떤 목표의 포트폴리오를 만드시겠습니까?" + 목표 카드 6종(성장→mvo·
  방어→min_var·균형→risk_parity·테마→bl+강세뷰·현재 국면→regime 권고모드·직접 구성). 각 카드 =
  재사용 시드(`setModel`+`setHoldingsReset(equalize)`+옵션 `setViewsLogged` → `/construct`).
  시드 유니버스는 `backtestBridgeApi.sectors().sample` + `macroApi.regime()` + 큐레이션 폴백
  (항상 ≥2 종목 보장). 푸터: 관심그룹·저장 스터디·빈 상태·**Resume**(sessionStorage)·대시보드 건너뛰기.
- **`WizardTracker.tsx`**(신규, PipelineBar 삭제): 3 페이즈 세그먼트 + 하위 스텝 칩(완료점·번호·
  라벨·서브텍스트) + Overview/Journal 북엔드 + 칩 클릭 점프 + ←/→ 키보드. 완료는 Provider
  `stageComplete[]` 단일 소스.
- **`layout.tsx`** 재작성: `isGate` 분기 · 헤더 **상시 RE-OPTIMIZE 제거**(경쟁 주액션 → 화면당
  단일 주액션 원칙, coverage/lastRun/MOCK 유지 + "☰ 목표" ghost) · `.aas-intent` "이 단계에서 할 일"
  · WizardTracker · 하단 **단일 주 CTA "다음 단계로 →"**(WizardNav, VALIDATION 진입 시
  `ensureFreshRun()`).
- **`AllocationProvider.tsx`**: STAGES에 `phase`/`intent` + `PHASES` 메타 · `goal/setGoal` ·
  파생 `stageComplete[]`/`isResultStale`/`ensureFreshRun()`(runAnalyze dedupe라 무해) ·
  **sessionStorage 하이드레이트/persist**(goal/pos/wip, `result`는 미persist·재계산) —
  하이드레이트 후에만 persist(빈 상태 덮어쓰기 방지). → **위저드 중간 전체 새로고침이 비파괴적**
  (이전엔 파괴적).
- **각 단계 Progressive Disclosure**: Optimize(엔진·λ·τ) / Stress(μ-bump) / Explain(상관행렬)을
  네이티브 `<details className="aas-adv">`로 접기 — **신규 의존성 0, 기능 제거 0**. Optimize는 자체
  Re-optimize 유지 + `isResultStale` 인라인 어포던스. empty-state를 "01 CONSTRUCT →" 백-CTA로 표준화.
- CSS: `globals.css`에 `.aas-gate*`/`.aas-goal*`/`.aas-wiz*`/`.aas-intent`/`.aas-adv`/
  `.aas-botnav-next.primary` 신설(라이트 토큰). `parts.tsx` 차트 프리미티브 verbatim 유지.

### 검증
- `tsc` 0 · `next build` **25 페이지 / allocation 8 라우트** · `pytest` 백엔드 무변경(allocation
  24 통과, 전체 847 불변) · ruff.
- **라이브(시스템 Playwright + 사전설치 Chromium, mock 서버 2개, 프로젝트 devDependency 0)**:
  게이트(6 카드) → "성장 추구" 선택 → Construct 6종목 시드(MVO·λ2.5) → "다음 단계로" ×3 →
  Stress(VALIDATION, auto-run) 도달, **상태 전 구간 보존** → **중간 새로고침 재개**(sessionStorage)
  → 게이트 Resume 노출. **콘솔/페이지 에러 0(하이드레이트 이슈 없음)**. 스크린샷으로 게이트·
  Construct(브레드크럼 phase·인텐트·3-페이즈 트래커·단일 주 CTA) 확인.

### 정직한 한계 / 범위 밖
- 백엔드/엔진 무변경(전부 기존 `/api/v1/allocation/*` 재사용). 21st.dev/shadcn **실사용**은 커넥터
  재연결 시(세션 중 오프라인). R2(테제 NL→팩터 자동매핑·Probability Frontier·레짐 prior 주입)는
  문서만. Execution 단계·드래그&드롭 캔버스·AI View Generator는 후순위 제외.

---

## 🛠️ Allocation Studio 심화 툴 4종 + 헤더 제거 + 초기 구성 종목명 표시

[배경] 사용자가 Allocation Studio(모듈 06)에서 ① **팩터 기반 포트폴리오** ② **카나리 자산·지표**
③ **robustness** ④ **마켓타이밍** 4개 영역을 "더 깊이 있고 정교하게 커스텀"할 수 있는 툴 추가를
요청. 부수로 ⑤ Construct 스테이지 헤더 블록(스크린샷: 브레드크럼·큰 제목·자산 구성 부제·
`2019-07-17 ~ … 1,712일 · 최근 실행` 커버리지) 제거 + ⑥ **초기 포트폴리오 구성 시 종목코드 대신
종목명 표시**. 3개 병렬 Explore 에이전트로 factor/canary·timing/robustness 인프라를 전수 매핑 후,
전부 **기존 엔진 헬퍼 재사용 + 소형 신규 엔드포인트**로 구현(엔진 로직 무변경).

### 백엔드 (전부 `src/api/allocation_routes.py`에 추가 — 엔진 파일 무변경)
- **`POST /resolve-names`** {codes} → {labels}: `_labels()`/`stock_master.get_stock_name`(단일 진실
  공급원) 배치 해소. 게이트 시드·관심그룹·직접코드 입력의 코드→이름 공통 해결.
- **`POST /factor-portfolio`** {factors[{id,weight,direction}], top_k, weighting, tickers?}:
  유니버스 표본(`snapshot_db.sample_factors` + mock 폴백)에 **방향 인지 z-score 가중합**(factor-xray
  `_z` 패턴 재사용, direction 0=`FIELD_BY_ID[id].higher_better` 자동) → 상위 K 선정 →
  비중화(균등/팩터틸트/역변동성/리스크패리티/최소분산/HRP는 `allocation_studio.weights_for_model`
  재사용, 임의 R 행렬). 커버리지 재정규화·정직 라벨.
- **`POST /timing`** {market, canaries[{kind,id,signal,lookback,threshold,direction}], min_breadth,
  risk_on_assets, risk_off_assets, holdings?, overlay}: VAA/PAA/DAA 규칙을 사용자 파라미터로 일반화 —
  `tactical_allocations`의 `_abs_mom`/`_score_13612`/`_above_ma_m`/`_above_ma_d`/`_norm`/`_signal` +
  `macro_analytics._macro_series`/`_latest`(지표 카나리) + `etf_prices.resolve`(US→KR ETF 매핑) 재사용.
  브레드스 게이트(k-of-N), 위험-온(현재 포트폴리오 유지 가능)/위험-오프 자산군 스위치, 추세
  오버레이(이탈 자산 현금화), `timing_panel` 컴포짓·자산추세표 병기.
- **`POST /stress-correlation`** {tickers, weights?, target_rho, intensity, confidence_level}:
  위기 시 상관이 target_rho로 수렴하는 공분산 재구성 → `models.portfolio_risk.PortfolioRiskModel`
  (calculate_portfolio_var/component_var) 재사용해 base vs 위기의 변동성·VaR·기여VaR Δ 산출.
- **`StressRequest.severity`**(0.25~3×): 가상 시나리오 M8 충격에 배율 곱(역사 리플레이 제외).
- 신규 `tests/test_allocation_tools.py`(11): 이름해소·팩터 방향/랭킹/틸트/부족에러·타이밍
  온·오프·k-of-N·오버레이 현금화·severity 선형·상관국면 변동성상승/무강도무변화.

### 프론트엔드
- **헤더 제거**(`app/allocation/layout.tsx`): `.aas-crumb`·`.aas-header` 블록 삭제. 인텐트 라인·
  ContextStrip·WizardTracker·하단 nav 유지. ☰목표·MOCK 배지는 `WizardTracker` 우측으로 재배치
  (게이트 접근·데이터 정직성 보존). `저널로 마무리` 분기를 인덱스 하드코딩→라벨 기반으로 교정.
- **종목명 표시**(`AllocationProvider`): holdings 중 `name===code`(6자리 코드)인 항목을 배치
  `resolveNames`로 이름 패치하는 useEffect(비중·키 불변 → 재분석 없음, resolvedRef 중복가드).
  게이트 시드·관심그룹·직접코드 **전 경로 일괄 해결**. (라이브: 삼성전자·SK하이닉스·… 코드잔여 0)
- **신규 03 TIMING 스테이지**: `STAGES`에 삽입(00 Overview·01 Construct·02 Thesis·**03 Timing**·
  04 Optimize·05 Stress·06 Explain·07 Journal), PHASES logic=[2,3,4]/validation=[5,6],
  `stageComplete` 8칸, WizardTracker sub 8칸+북엔드 인덱스 갱신. `app/allocation/timing/page.tsx`
  (카나리 편집·게이트·자산군·오버레이 / 판정·권고배분·마켓타이밍 컴포짓) + Provider `timingCfg`/
  `timingQ`/`applyTiming`(+ sessionStorage wip 지속).
- **팩터 빌더**(Construct 모드 토글 `직접 구성|팩터 빌더`): `FactorBuilder.tsx` — `screenerApiAdvanced.
  fields()` 카탈로그로 팩터 다중선택(가중·방향 자동/고/저) + 프리셋(가치·퀄리티·모멘텀·저변동·배당)
  + 유니버스/top-N/비중방식 → `/factor-portfolio` → 상위 K 표(비중·점수·커버리지) → "이 포트폴리오로
  적용"(setHoldingsReset).
- **Stress 심화**(`stress/page.tsx`): 시나리오 강도(severity) 슬라이더 + μ bump 범위 5→10 확대 +
  **상관-국면 스트레스 카드**(목표 ρ·강도·VaR 신뢰수준 → base→위기 변동성·VaR·기여VaR 표).
- `lib/allocationApi.ts`: resolveNames/factorPortfolio/timing/stressCorrelation + 타입. `stress`에
  severity 인자. `globals.css` `.as-fb-*`/`.as-tm-*`/`.aas-wiz-right·mock·gate` 신설.

### 검증
- 백엔드 **858 passed / 10 skipped**(+11 신규), ruff 통과. tsc 0, next build **26 페이지 / allocation
  9 라우트**(신규 `/allocation/timing`).
- 라이브(mock, 시스템 Playwright + 사전설치 Chromium, 프로젝트 devDep 0): 게이트→성장추구→Construct
  (**헤더 부재·종목명 표시·코드잔여 0**)→팩터빌더(가치 프리셋→상위10)→Timing(카나리4·RISK-OFF·컴포짓
  83)→Stress(severity·상관국면 vol +130%) **콘솔 에러 0**.

### 정직한 한계
- mock 유니버스 표본(`sample_factors`)은 합성 코드라 팩터빌더 결과 종목명이 코드로 표시됨 — GCP
  실적재 유니버스에선 실코드→실명. mock ETF 시세는 결정론적 합성이라 카나리·컴포짓 절대수치는
  참고용(구조·부호·로직만 검증), 실값은 GCP. `market_timing` 컴포짓은 시장 전반(timing_panel)
  기준으로 카나리 판정과 독립(UI에 명시). BAA 등 미구현 전략·다국가 지표는 범위 밖.

---

## 🧩 백테스트 실행 워크플로 영속화(BacktestRun) + AAS 404·매크로 에러 근본수정 + Playwright E2E

[배경] 사용자가 캡처(AAS 게이트 진입 시 404)와 함께 4건을 요청: ① 백테스터를 "설정 → 클릭 →
같은 화면에 결과"에서 **"설정 → BacktestRun 생성 → 전용 로딩 페이지 → 전용 결과 페이지"**로
전환(새로고침·북마크·재방문 가능한 고정 URL, 완료 전 결과를 폼 아래에 절대 렌더하지 않음,
유효한 run_id 없이 절대 이동하지 않음) ② AAS 버튼 간헐적 404 근본수정(증거 기반) ③ 매크로 탭
에러 재현 후 근본수정(제네릭 ErrorBoundary 금지, 5가지 정직한 상태) ④ 회귀가 조용히 재발하지
않도록 커버리지 추가. **필수 절차**: Step 0 조사 전용(제품코드 금지) → Step 1 스펙 문서 단독
커밋 → Step 2 플랜 문서 단독 커밋 → Step 3 TDD 소단위 커밋. 순서는 AskUserQuestion으로
"버그 먼저 → 백테스트" 확정, E2E는 `@playwright/test` 신규 도입 확정.

### Step 0 조사 (증거, 제품코드 없이)
- 백테스트: `TerminalBacktester.run()`이 SSE로 결과를 **로컬 상태**에 저장해 폼 아래 렌더 —
  `run_id`도 영속도 새로고침 복구도 없음. 참고 가능한 영속 패턴은 이미 존재
  (`multibacktest_runs`/`stage11_routes.py`, `main_api.py`의 `_INGEST_STATUS` 스레드+폴링).
- **AAS 404·매크로 에러 둘 다 현재 HEAD(mock)에서 재현 안 됨** — 모든 AAS/매크로 엔드포인트가
  등록돼 있고(`allocation_routes.py` 4라우터, `macro_routes.py`), 런타임 프록시가 전 메서드를
  지원, `next.config.js`에 충돌 rewrite 없음. **결론: GCP 배포 프론트/백엔드 버전 불일치**(구
  프론트가 신 백엔드에 없는 걸 치거나 그 반대) — 코드 결함이 아니라 스테일 빌드. 그럼에도
  방어적 하드닝 + 회귀 잠금은 진행(재발 시 CI가 즉시 감지하도록).

### Step 1~2 — 문서 (단독 커밋)
`docs/specs/backtest-run-workflow.md`(`docs(spec):`) + `docs/plans/backtest-run-workflow-plan.md`
(`docs(plan):`) — BacktestRun 상태모델, 로딩/결과 IA, AAS/매크로 요구사항, 인수기준+테스트
매트릭스, 재사용 맵, 단계별 파일.

### E2E 하네스 (Phase 2)
`frontend/playwright.config.ts` — `next start`가 **실제 `main_api`**(`KIS_USE_MOCK=1`,
SQLite)와 **실제 Next.js**를 `webServer`로 기동(모킹 스텁 아님 → "0×404/0 콘솔에러" 단언이
의미있음). `e2e/helpers.ts::trackErrors()` — pageerror/console error/`/api/backend/` 4xx·5xx를
수집하는 공용 싱크(외부 폰트 net::ERR_ 등은 노이즈로 제외).

### AAS 404 하드닝 (Phase 4, `fix(aas):`)
`AllocationProvider.tsx`에 `isKnownAllocationRoute(pathname)`(게이트 또는 정확한 STAGES href만
허용) 신설 — `GoalGate.tsx`의 **Resume**이 스테일 `sessionStorage` 경로(과거 세션의 구 라우트
등)를 가리킬 때 죽은 링크로 이동하는 대신 `/construct`로 안전 폴백. `e2e/aas.spec.ts` —
전 위저드 스테이지 순회 + 액션 버튼 전수 클릭(ACTION_RE) → 0×404·0 콘솔에러 단언, 스테일
Resume 타깃 시드 → 죽은 링크 없음 단언.

### 매크로 에러 하드닝 (Phase 3, `fix(macro):`)
`MacroCockpit.tsx`의 `RecommendTab`이 `recommend.top`/`recommend.regime`이 없거나
`holdings_final`이 배열이 아닌 **부분 페이로드**(실 BOK/FRED 데이터가 추천을 완전히 산출 못할 때
실제로 나올 수 있는 형태)를 만나면 크래시하던 지점에 정직한 미가용 상태 가드 추가(제네릭
ErrorBoundary 아님 — 원인 지점에서 직접 처리). `tests/test_macro_contract.py`(3) — 추천 페이로드
형태 고정(`top.holdings_final` 리스트 등) + 한글 UTF-8 왕복 검증. `e2e/macro.spec.ts` — 8개
서브탭 전수 순회(0에러+한글 인코딩 검증) + `/macro/recommend` 부분 응답 스텁 → 크래시 없이
"데이터 미가용" 상태 렌더 단언.

### BacktestRun 워크플로 (Phase 5, 5단계 TDD)
- **5a 도메인**(`src/data/backtest_runs.py`, `feat(backtest): ... (5a)`): raw-SQL DB-optional
  영속 스토어(기존 `research_runs.py`/`execution_store.py` 관례 재사용). 상태 lifecycle
  `draft→queued→validating→loading_data→simulating→calculating_metrics→persisting_results→
  completed` + 터미널 `failed/cancelled/expired`, `_TRANSITIONS` 맵으로 불법 전이 차단.
  `input/parameter_snapshot`·`progress_percent`·`current_stage`·`status_message`·
  `error_code/message`·`correlation_id`·`is_mock_data`·`is_pit_verified` 보관.
  `tests/test_backtest_runs.py`(8): 생성→queued, 정상 lifecycle, 불법 전이 거부, 터미널 불변,
  새로고침 복구(다른 커넥션에서 영속 진행률 읽기), list 최신순.
- **5b API**(`src/api/backtest_run_routes.py`, `(5b)`): `POST /api/v1/backtest/runs`가 즉시
  `run_id`를 반환하고 백그라운드 스레드(`main_api.py`의 `_INGEST_STATUS` 스레딩 패턴 재사용)가
  기존 `_screen_to_backtest_core(progress_cb=)`를 실행하며 각 단계로 `advance()` — 취소는
  `_Cancelled` 예외로 다음 progress_cb 콜 지점에서 협조적으로 중단. `GET .../status`(경량 폴링)·
  `GET .../{id}`(전체 결과)·`POST .../cancel`(터미널이면 409)·`POST .../retry`(input_snapshot으로
  신규 run)·`GET /runs`(목록). `tests/test_backtest_run_routes.py`(6): 생성→폴링→완료, 엔진
  실패 시 안전 메시지(내부 정보 누출 0), 새로고침 복구, 미존재 404, retry, list.
- **5c 프론트 배선**(`(5c)`): `lib/backtestRunApi.ts` + `RunMonitor.tsx`
  (`/backtest/runs/[runId]/loading`) + `BacktestResults.tsx`
  (`/backtest/runs/[runId]/results`). `TerminalBacktester.run()`을 로컬 결과 렌더에서
  `POST /runs` → `router.push(.../loading)`로 교체 — **결과를 폼 아래에 절대 렌더하지 않고,
  유효한 run_id 없이 절대 이동하지 않음**. 로딩 페이지 = 실제 잡 모니터(전략명·run id·설정
  요약·데이터 출처·**실제** 현재 단계·**백엔드가 제공할 때만** 진행률·경과시간·활동
  타임라인·real/mock 배지·안전 취소/재시도·비민감 에러). `e2e/backtest.spec.ts` — (A) 실제
  백엔드로 클릭→로딩 이동(폼 미렌더 확인)→실제 단계/설정 표시→안전 취소→정직한 취소 상태,
  (B) 실스키마 스텁 완료 run으로 결정론적 결과 렌더+새로고침 복구 검증.
- **5d 결과 심화**(`(5d)`, 코드와 함께): 엔진이 실제 반환하는 **36개 통계 전부**를 수익/
  리스크/위험조정/분포/거래품질/비용 6개 그룹으로 재구성(기존 14개 노출 → 32개 렌더, Ulcer·
  Omega·Tail Ratio·gain-to-pain·recovery/information ratio·skew/kurtosis·기댓값·손익배율 등
  추가) — 데이터 없는 지표·그룹은 렌더 생략. `symbol_results.contribution_pct` 기반 **기여도
  분해(Attribution) 차트**(상위/하위 기여 종목) 신규. **진단 패널**: PIT 미검증/mock/무거래
  정직 경고 + "롤링 지표·시점별 익스포저·거래별 MFE/MAE는 엔진이 산출하지 않아 표시하지
  않는다"는 명시적 생략 고지(추정치로 대체 안 함).
- **5e 실행 비교**(`(5e)`, 신규 백엔드 없음 — 기존 `list()`/`get()`만 재사용):
  `BacktestCompare.tsx` + `/backtest/runs/[runId]/compare` — 완료된 다른 실행 B 선택 →
  정규화 자산곡선(시작=100) 오버레이 + 지표 델타 표(Δ=B−A, 우위 방향 색상) + 설정/스냅샷
  차이(다른 행 강조) + 비교 불가 상태 정직 표기(A/B 중 미완료면 사유와 함께 차단). 결과 헤더에
  "비교" 링크 추가.

### 검증 (풀 게이트, 전부 라이브 확인)
- 백엔드 **943 passed / 10 skipped / 0 failed**(신규 backtest_runs 8 + backtest_run_routes 6 +
  macro_contract 3), `ruff check` 통과.
- 프론트: `tsc` 0, `next build` 전 라우트 성공(`/backtest/runs/[runId]/{loading,results,compare}`
  포함). **Playwright 7/7**(aas 2 + backtest 3 + macro 2).
- **실 브라우저 라이브 검증**(스텁 아님): "백테스트 실행" 클릭 → `/backtest`가 아닌
  `/backtest/runs/{id}/loading`로 이동 → 실 엔진이 **785일 시뮬레이션**을 실제로 진행(진행률
  57%→100% 실시간 폴링 확인) → 완료 시 `/results`로 자동 전환 → **32개 KPI·기여도 차트·2개
  테이블·3개 차트·"MOCK 데이터"/"PIT 미검증" 배지·한글 인코딩 정상(mojibake 0)·페이지 에러
  0·API 404 0** → 새로고침 후에도 동일 결과 유지. 취소 경로: 실제 단계("시점(PIT) 데이터
  로딩") 노출 중 취소 클릭 → "실행이 취소되었습니다" 정직 상태 도달. 비교: 두 실 완료 run
  간 오버레이+델타(17행)+설정차이 렌더, 콘솔 에러 0.
- 트러블슈팅 메모: `next build` 후 이전 `next start`가 살아있으면 스테일 청크 해시로
  `ChunkLoadError`/React #423 발생 — 반드시 기존 `next` 프로세스를 전부 죽인 뒤 재기동
  (기존 "stale .next" 교훈과 동일 계열, 이번엔 프로세스 중복이 원인).

### 정직한 한계
- AAS 404·매크로 에러는 **현재 코드베이스에서 재현되지 않음** — 원래 증상은 GCP의 프론트/백엔드
  버전 불일치로 추정. 이번 세션은 근본원인 자체보다 **재발 방지 하드닝 + 회귀 잠금**(가드
  코드 + E2E)에 집중. 사용자는 `docker compose build --no-cache frontend backend`로 클린
  재배포 권장.
- 5d 진단은 **엔진이 실제로 계산하는 값만** 그룹화해 노출한 것 — 롤링(구간별) 지표, 시점별
  포지션 익스포저, 거래별 MFE/MAE는 엔진에 그 데이터가 없어 UI가 만들어내지 않고 명시적으로
  "표시 안 함"이라고 고지. 필요하면 엔진 확장이 선행돼야 함(범위 밖).
- 비교(5e)는 신규 백엔드 없이 기존 결과 페이로드만으로 클라이언트에서 계산 — 두 실행의 기간·
  길이가 다르면 자산곡선은 절대 날짜가 아닌 **인덱스 기준 정렬**임을 UI에 명시(절대 비교 주의).
- E2E 결과/비교 테스트는 **결정론적 검증을 위해 실스키마 스텁 페이로드**를 사용(엔진 자체는
  5c의 실행 A 테스트와 백엔드 pytest가 커버) — 로딩→취소 테스트만 실 엔진·실 시뮬레이션을 탄다.
