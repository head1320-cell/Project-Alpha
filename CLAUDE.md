# Project Alpha — 한국 주식 퀀트 플랫폼 (AI 에이전트용 요약)

> 이 파일은 매 세션 자동 로드됩니다. **100줄 미만으로 유지하세요.**
> 세션 요약·작업 기록은 여기가 아니라 **[`docs/HISTORY.md`](docs/HISTORY.md)** 맨 아래에 추가.
> 스펙·계획은 [`docs/specs`](docs/specs) · [`docs/plans`](docs/plans).
> **수치는 문서가 아니라 코드가 진실입니다** — 과거 CLAUDE.md의 "필터 13종 / FIELD_BY_ID 49개 /
> 라우트 223개"는 실측(11 / 157 / 268)과 전부 달랐습니다. 개수는 세지 말고 레지스트리를 읽으세요.

## 1. 아키텍처

FastAPI + Next.js 14 App Router + PostgreSQL. docker-compose 3컨테이너
(`ficc_backend:8000` · `ficc_frontend:3000` · `ficc_db:5432`).
브라우저는 백엔드 주소를 모릅니다 — 모든 API가 동일출처 `/api/backend/...` **런타임 프록시**
(`frontend/src/app/api/backend/[...path]/route.ts`, 요청 시점에 `BACKEND_URL`을 읽음)를 거칩니다.

| 위치 | 역할 |
|---|---|
| `main_api.py` | **얇은 진입점(23줄)** — `create_app()` 호출만. `uvicorn main_api:app` 계약 유지 |
| `src/app_factory.py` | 앱 조립 — CORS · 관측성 · 기동 훅 · `ROUTER_MODULES` 목록으로 라우터 30개 등록 |
| `src/api/` | 도메인 라우터 (앱 전체 268 경로). 라우터 추가는 `ROUTER_MODULES`에 한 줄 |
| `src/api/legacy_schemas.py` | 레거시 엔드포인트의 요청/응답 Pydantic 모델 모음 |
| `src/startup/lifecycle.py` | 기동 시퀀스 + 백그라운드 사전적재 데몬 |
| `src/state/` | 프로세스 로컬 공유 상태 (`ingest_state` · `trading_state`) |
| `src/engine/` | 핵심 로직 — 스크리너·백테스트·매크로·자산배분·리스크 |
| `src/data/` | 데이터 계층 — DART/KIS/KRX 클라이언트, 팩터 스토어, 스냅샷 DB, `mock_gate` |
| `src/execution/` | 실거래 — KIS 클라이언트, 킬스위치, 리스크 게이트웨이 |
| `src/models/` | 계량 모델 (VaR·GARCH·CVA·파생) |
| `src/observability/` | 구조화 로깅 + 요청 추적 ID 미들웨어 |

**프론트엔드는 FSD** — 의존 방향은 위에서 아래로만. 슬라이스의 `index.ts`가 Public API이니
**구현을 뒤지지 말고 배럴만 읽으세요.** 단 **배럴은 "발견"용, `import`는 실제 모듈에서** —
배럴 import는 슬라이스 전체를 번들에 끌어옵니다(실측 +9KB).

| 계층 | 내용 |
|---|---|
| `app/` | Next.js 라우트 (파일시스템 라우팅 — FSD의 app 계층이 아니라 Next 전용) |
| `widgets/` | 라우트에 붙는 완성 패널 (screener · backtester · macro · company · allocation · layout …) |
| `features/` | 재사용 기능 단위 (strategy-builder · factor-picker) |
| `entities/` | 도메인 모델 + API 클라이언트 (allocation · macro · company · backtest-run …) |
| `shared/` | `api/`(apiBase·queryClient·screenerApi) · `ui/`(프리미티브·차트) · `lib/`(스토리지·파서) |

UI 모듈: 01 Screener · 02 Backtester · 03 Macro · 04 Company · 05 Risk · 06 Allocation Studio · 07 Data Infra.

## 2. 기술 스택

- **백엔드** Python 3.11 · FastAPI **0.111.0(고정)** · SQLAlchemy 2.0.30 · pandas · numpy · scipy ·
  scikit-learn · statsmodels · QuantLib · pytest · ruff
- **프론트** Node 20 · Next 14.2.5 · React 18 · TypeScript 5(strict) · @tanstack/react-query 5 ·
  zustand 4 · recharts · reactflow · **순수 CSS**(`app/globals.css`) · Playwright
- **데이터 소스** DART(재무) · KIS(시세·주문) · KRX(장기 일봉). 키가 없으면 mock으로 자동 폴백.

## 3. 실행 & 검증

```bash
make all          # 전체 게이트 = lint + test + typecheck + build (CI와 동일)
make lint         # ruff check src/ tests/ main_api.py
make test         # KIS_USE_MOCK=1 pytest tests/ -q
cd frontend && npx tsc --noEmit && npx next build && npx playwright test
```

개발 서버 — `uvicorn main_api:app --reload --port 8000` + `cd frontend && npm run dev`
전체 스택 — `docker compose up --build -d` · 실데이터 점검 — `python verify_connection.py`
환경변수는 `.env.example` 참고. `KIS_USE_MOCK=1`이 개발 기본값(외부 호출 0).

## 4. 절대 불변식 (깨뜨리지 말 것)

**스크리너 3-레이어** — `유동성 게이트 → 필터 kind → 후처리 analyzer`. 이 구조와
`ValuationScreener`·백테스트 엔진의 동작 방식은 리팩터링 대상이 아닙니다.
`src/engine/filter_ast.py`의 `FIELD_BY_ID`가 필드 단일 레지스트리 —
**새 필터 kind를 추가하면 `validate()`의 field-check bypass 튜플에 반드시 등록**할 것.

**종목명** — `src/data/stock_master.py`의 `get_stock_name()` / `resolve_name()`이 단일 진실
공급원. `"Unknown Corp"`, 가짜 종목코드(100000~) 재도입 금지.

**mock 게이트** — `src/data/mock_gate.py::mock_allowed()`가 유일한 판정 기준이며
`KIS_USE_MOCK`이 **정확히 `"1"`일 때만** mock. 운영에서 조회가 실패하면 합성값으로 가리지 말고
정직하게 `None`/빈값을 반환할 것. `KIS_MODE`·`KIS_REAL_APP_KEY` 등 구 변수 재도입 금지.

**실거래 안전 (최우선)** — 자동매매 기본값은 `dry_run=True`. `TradingEngine`의 6중 안전장치를
우회하는 코드 금지. **`src.kis_order_executor.OrderExecutor`를 `trading_engine.py` 밖에서 직접
생성 금지**(자체 안전장치가 없어 곧장 `place_order()` 호출) — `tests/test_no_order_executor_bypass.py`
가 CI에서 정적으로 강제. KIS 연동은 `src/execution/kis_client.py::get_kis_client()` 단일 경로만
사용. 실계좌 전 반드시 모의투자(`KIS_IS_PAPER=1`)에서 검증.

**버전·프로세스 고정** — `fastapi==0.111.0` 유지(0.139에서 `include_router`가 깨져 라우터 미등록).
`uvicorn --workers 1` 유지 — 캐시·DART 쿼터 카운터·적재 상태가 전부 프로세스 로컬이라, 워커를
늘리려면 그 상태를 먼저 Redis/DB로 옮겨야 합니다.

**프론트엔드** — 순수 CSS 유지. **Tailwind·shadcn·CSS-in-JS 등 UI 프레임워크로 이전 금지.**
API 주소를 빌드 타임에 박지 말 것(`NEXT_PUBLIC_*`·`rewrites` 금지) — 반드시 런타임 프록시 경유.
**CSS 클래스명이 E2E 계약입니다**(`data-testid` 미사용, Playwright가 `.tfm-*`·`.brun-*`·`.as-*`
등을 직접 선택) — 클래스명을 바꾸면 해당 스펙도 함께 고칠 것.
`next build` 후에는 기존 `next` 프로세스를 모두 종료하고 재기동(스테일 청크 → `ChunkLoadError`).

**수치 안전** — 분수승·로그·제곱근에 음수가 들어갈 수 있는 파생식은 반드시 가드할 것
(적자기업 실데이터에서만 터집니다. mock은 항상 흑자라 테스트를 통과합니다).

**보안** — `.env`는 절대 커밋 금지(`.env.example`만). API 키를 채팅·이슈·로그에 노출 금지.

**작업 방식** — 조사 → 스펙(`docs/specs`) → 계획(`docs/plans`) → TDD 구현, 기능 단위 작은 커밋.
추정치를 사실처럼 쓰지 말고, 모르면 모른다고 적을 것.
