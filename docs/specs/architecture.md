# 아키텍처·기술 스택 — 구현 상세

> `CLAUDE.md` 에서 옮겨 온 문서입니다. **CLAUDE.md 는 규율을, 여기는 구조를** 담습니다.
> 지침 파일이 매 세션 자동 로드되는 만큼 짧아야 하고, 구현 상세는 반드시 낡기 때문입니다.
>
> ★여기 적힌 개수·버전도 낡습니다★ — `CLAUDE.md` 의 원칙이 여기에도 적용됩니다.
> 세지 말고 레지스트리를 읽으세요. 실측 시점: 2026-08-28.

## 1. 전체 구성

FastAPI + Next.js 14 App Router + PostgreSQL. docker-compose 3컨테이너
(`ficc_backend:8000` · `ficc_frontend:3000` · `ficc_db:5432`).

브라우저는 백엔드 주소를 모릅니다 — 모든 API 가 동일출처 `/api/backend/...`
**런타임 프록시**(`frontend/src/app/api/backend/[...path]/route.ts`, 요청 시점에
`BACKEND_URL` 을 읽음)를 거칩니다. ★빌드 타임에 주소를 박으면 안 됩니다★
(`NEXT_PUBLIC_*`·`rewrites` 금지) — 이것은 `CLAUDE.md` 의 불변식입니다.

## 2. 백엔드 계층

| 위치 | 역할 |
|---|---|
| `main_api.py` | **얇은 진입점** — `create_app()` 호출만. `uvicorn main_api:app` 계약 유지 |
| `src/app_factory.py` | 앱 조립 — CORS · 관측성 · 기동 훅 · `ROUTER_MODULES` 로 라우터 등록 |
| `src/api/` | 도메인 라우터. 라우터 추가는 `ROUTER_MODULES` 에 한 줄 |
| `src/api/legacy_schemas.py` | 레거시 엔드포인트의 요청/응답 Pydantic 모델 |
| `src/startup/lifecycle.py` | 기동 시퀀스 + 백그라운드 사전적재 데몬 |
| `src/state/` | 프로세스 로컬 공유 상태 (`ingest_state` · `trading_state`) |
| `src/engine/` | 핵심 로직 — 스크리너·백테스트·매크로·자산배분·리스크 |
| `src/data/` | 데이터 계층 — DART/KIS/KRX 클라이언트, 팩터 스토어, 스냅샷 DB, `mock_gate` |
| `src/services/` | 수집기 — 매크로(ECOS·FRED) 등 |
| `src/execution/` | 실거래 — KIS 클라이언트, 킬스위치, 리스크 게이트웨이 |
| `src/models/` | 계량 모델 (VaR·GARCH·CVA·파생) |
| `src/observability/` | 구조화 로깅 + 요청 추적 ID 미들웨어 |

`src/state/` 가 프로세스 로컬인 것이 `uvicorn --workers 1` 고정의 이유입니다 —
워커를 늘리려면 캐시·DART 쿼터 카운터·적재 상태를 먼저 Redis/DB 로 옮겨야 합니다.

## 3. 프론트엔드 (FSD)

의존 방향은 위에서 아래로만. 슬라이스의 `index.ts` 가 Public API 이니 **구현을 뒤지지
말고 배럴만 읽으세요.** 단 **배럴은 "발견"용이고 `import` 는 실제 모듈에서** —
배럴 import 는 슬라이스 전체를 번들에 끌어옵니다(실측 +9KB).

| 계층 | 내용 |
|---|---|
| `app/` | Next.js 라우트 (파일시스템 라우팅 — FSD 의 app 계층이 아니라 Next 전용) |
| `widgets/` | 라우트에 붙는 완성 패널 (screener · backtester · macro · company · allocation · layout …) |
| `features/` | 재사용 기능 단위 (strategy-builder · factor-picker) |
| `entities/` | 도메인 모델 + API 클라이언트 (allocation · macro · company · backtest-run …) |
| `shared/` | `api/`(apiBase·queryClient) · `model/`(엔티티 공통 타입) · `ui/` · `lib/`(스토리지·포맷) |

UI 모듈: 01 Screener · 02 Backtester · 03 Macro · 04 Company · 05 Risk ·
06 Allocation Studio · 07 Data Infra.

**스타일** — Tailwind 는 이미 쓰입니다. shadcn/ui 는 `shared/ui/shadcn` 벤더링 ·
토큰은 `globals.css` 가 기존 `--t-*` 에 매핑(복제 금지) · **AAS 만 이전, 레거시는 순수
CSS** · 선행 `:root` 블록 불변(EOF 의 shadcn 브리지가 마지막 — ADR 지정, 세지도 지우지도
말 것) · CSS-in-JS 금지. 근거는
[ADR 001](../decisions/adr-001-tailwind-shadcn-aas-migration.md).

★CSS 클래스명이 E2E 계약입니다★ — `data-testid` 를 쓰지 않고 Playwright 가 `.tfm-*`·
`.brun-*`·`.as-*` 등을 직접 선택합니다. 클래스명을 바꾸면 해당 스펙도 함께 고칠 것.

`next build` 후에는 기존 `next` 프로세스를 모두 종료하고 재기동하세요
(스테일 청크 → `ChunkLoadError`).

## 4. 기술 스택

- **백엔드** Python 3.11 · FastAPI **0.111.0(고정)** · SQLAlchemy 2.0.30 · pandas ·
  numpy · scipy · scikit-learn · statsmodels · QuantLib · pytest · ruff
- **프론트** Node 20 · Next 14.2.5 · React 18 · TypeScript 5(strict) ·
  @tanstack/react-query 5 · zustand 4 · recharts · reactflow · 순수 CSS + Tailwind ·
  Playwright
- **데이터 소스** DART(재무) · KIS(시세·주문) · KRX(장기 일봉) · ECOS(한국 매크로) ·
  FRED/ALFRED(미국 매크로·빈티지)

★FastAPI 를 올리지 마세요★ — 0.139 에서 `include_router` 가 깨져 라우터가 등록되지
않았습니다. 이것은 `CLAUDE.md` 의 불변식입니다.

## 5. 실행

```bash
make all          # 전체 게이트 = lint + test + typecheck + build (CI와 동일)
make lint         # ruff check src/ tests/ main_api.py
make test         # KIS_USE_MOCK=1 pytest tests/ -q
cd frontend && npx tsc --noEmit && npx next build && npx playwright test
```

개발 서버 — `uvicorn main_api:app --reload --port 8000` + `cd frontend && npm run dev`
전체 스택 — `docker compose up --build -d` · 실데이터 점검 — `python verify_connection.py`
환경변수는 `.env.example` 참고. **`KIS_USE_MOCK=1` 이 개발 기본값**(외부 호출 0).

## 6. 관련 문서

- 데이터 계보·능력 감사 — [`2026-08-27-capability-lineage-audit.md`](2026-08-27-capability-lineage-audit.md) (`E0~E5` 정의 §0)
- 매크로 계층 아키텍처 — [`2026-08-25-macro-layer-architecture.md`](2026-08-25-macro-layer-architecture.md) (네 질문 · 채택 차단 조건)
- 피처 계층 mock 감사 — [`2026-08-27-feature-layer-mock-audit.md`](2026-08-27-feature-layer-mock-audit.md)
- ECOS 데이터 계약 감사 — [`2026-08-27-ecos-data-contract-audit.md`](2026-08-27-ecos-data-contract-audit.md)
