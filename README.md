# 📈 FICC Quant Platform

> **시뮬레이션 → 현실 보정 → 실거래 → 운영 모니터링까지 단일 시스템으로 연결한 기관급 한국 주식 퀀트 플랫폼.**

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-14.2-black.svg)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791.svg)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://www.docker.com/)
[![KIS API](https://img.shields.io/badge/KIS_Open_API-Integrated-FF6B6B.svg)](https://apiportal.koreainvestment.com)

---

## 💡 한 줄 요약

| 구분 | 보유 기능 |
|---|---|
| **데이터** | KRX 가격·거래량 · DART 재무제표 · 한국·미국 매크로 5종 |
| **전략** | DAG 비주얼 빌더 · DSL · YAML · 10개 KIS 프리셋 · 80개 지표 + 63개 캔들 패턴 |
| **백테스트** | PIT-safe · 멀티전략 통합 · 5-Factor Brinson Attribution · Counterfactual · Walk-Forward |
| **현실 보정** | Square Root Law 시장충격 · Cash Yield · Capacity · Buying Power · Regime-Adaptive |
| **가치평가** | RIM · DCF · DDM 통합 가중평균 · 괴리율 자동 산출 |
| **실거래** | KIS OpenAPI · 5-layer Safety · 3-mode Router (SHADOW/PAPER/LIVE) · Kill Switch |
| **운영** | Broker Reconciler · Priority Queue Gateway · State Machine · Slack/Discord 알림 |
| **리스크** | VaR (Normal/EWMA/Historical) · ES · Stress Test · Greeks · 효율적 프론티어 · 팩터 회귀 |
| **파생상품** | Black-76 · 변동성 표면 · XVA/CVA · Hull-White · SABR · Monte Carlo |

---

## 🏗 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│  Next.js 14 (Frontend) — PortfolioVisualizer 스타일 통합 인터페이스    │
│  ─────────────────────────────────────────────────────────          │
│  / (홈)              · Command Center — Macro/AI/Screener/Live 콕핏     │
│  /builder            · 비주얼 빌더 + DSL + YAML + 라이브러리 + 캔버스 │
│  /backtest           · 백테스트 + 최적화 + 포트폴리오 + 리밸런싱 + 실행 │
│  /risk-tools         · VaR + 포트폴리오 + 프론티어 + 팩터              │
│  /screener           · RIM·DCF·DDM 통합 스크리너 + Quick Flip 상세      │
│  /macro              · 16지표 Heatmap + 4-Quadrant + Yield Curve         │
│  /insights           · AI 자연어 보고서 (6 도메인 + 스트리밍)            │
│  /derivatives        · 옵션 + 변동성 + XVA + 금리 + 몬테카를로         │
│  /admin/multi-backtest · Stage 11 통합 백테스트                       │
│  /admin/realism      · Stage 12 현실 보정 패널                       │
│  /admin/live-trading · Stage 13 실거래 콕핏 + Production Monitor      │
└────────────────────────────────────┬────────────────────────────────┘
                                      │ FastAPI REST
┌────────────────────────────────────▼────────────────────────────────┐
│  FastAPI Backend — 베이스라인 + 73 신규 API endpoints                 │
│  ────────────────────────────────────────────────────────────         │
│  src/api/                                                              │
│    ├─ {기존 Stage 1-10 라우터들}                                      │
│    ├─ stage11_routes.py        (10) /api/v1/multibacktest/*           │
│    ├─ stage12_routes.py        (8)  /api/v1/realism/*                 │
│    ├─ stage13_routes.py        (14) /api/v1/live/*                    │
│    ├─ stage13_extensions.py    (15) /api/v1/live/{reconcile,gateway,...}│
│    └─ valuation_routes.py      (4)  /api/v1/valuation/*               │
│                                                                       │
│  src/engine/      백테스트 · 매크로 · 리스크 · 가치평가                 │
│  src/execution/   실거래 (KIS API + 5-layer 안전장치)                  │
│  src/data/        DART 재무제표 클라이언트                              │
│  src/utils/       Slack/Discord 알림 시스템                            │
└────────────────────────────────────┬────────────────────────────────┘
                                      │ asyncpg
                                      ▼
                              PostgreSQL 15
```

---

## 🚀 빠른 시작

### 1. 사전 요구사항
- Docker + Docker Compose
- Python 3.11 (개발 시)
- Node.js 20+ (Next.js dev 서버 사용 시)

### 2. 환경 설정
```bash
git clone <repo>
cd ficc-platform
cp .env.example .env
nano .env    # PG, KIS, DART, Slack 토큰 입력
```

### 3. 빌드 + 실행
```bash
docker compose up --build -d
```

### 4. DB 초기화 (최초 1회)
```bash
curl -X POST http://localhost:8000/api/v1/multibacktest/init-schema
curl -X POST http://localhost:8000/api/v1/live/init-schema
```

### 5. 헬스체크
```bash
curl http://localhost:8000/api/v1/live/health
# → 전 시스템 종합 상태 (gateway / reconciler / notifier / state machine)
```

### 6. 접속
- Frontend: <http://localhost:3000>
- Backend API: <http://localhost:8000/docs>

---

## 🔧 주요 기능 상세

### 1. 전략 빌더 (`/builder`)
**5가지 입력 방식**

| 탭 | 방식 | 적합한 사용자 |
|---|---|---|
| 비주얼 빌더 | 5단계 폼 (지표 → 진입 → 청산 → 리스크 → 메타) | 처음 만드는 사용자 |
| DSL 커스텀 | 수식 입력 + 실시간 Python 미리보기 | 수식 표현 익숙한 사용자 |
| YAML 가져오기 | `.kis.yaml` 업로드 + 검증 | 파일로 전략 보유 |
| 전략 라이브러리 | 10개 KIS 프리셋 카드 | 빠른 시작 |
| 노드 캔버스 | React Flow 시각 DAG | 복잡한 다단 전략 |

지표 라이브러리: **80개 기술지표 + 63개 캔들 패턴**

### 2. 백테스팅 (`/backtest`)
- **전략 백테스트** — TearSheet (Sharpe / MDD / Calmar / Sortino)
- **파라미터 최적화** — Grid Search 히트맵
- **포트폴리오 백테스트** — 다종목 비교
- **리밸런싱 시뮬** — Daily/Weekly/Monthly/Regime-Change 4 정책
- **전략 실행** — 시그널 → 주문 자동 전환

### 3. Stage 11 통합 백테스트 (`/admin/multi-backtest`)
**시뮬레이션 → 현실 보정 → 의사결정 가치 정량화**

- **PIT-safe Daily Simulation** — 리밸런싱일 정확히 일치, look-ahead bias 없음
- **5-Factor Brinson Attribution**: Allocation / Selection / Macro / Netting / Cost
- **Counterfactual Engine** — "이 결정이 없었다면?" N 시나리오 비교
- **Regime-Conditional Alpha** — 4-Quadrant별 전략 alpha 분해

### 4. Stage 12 Production Realism Engine (`/admin/realism`)
**5가지 현실 마찰을 통합한 백테스트**

| 마찰 요소 | 모델 | 효과 |
|---|---|---|
| ① 유동성 한계 | ADV 기반 capacity caps | 500M 주문이 mega vs small에 1,840배 다른 임팩트 |
| ② 시장 충격 | Square Root Law (Almgren-Chriss, α=0.35~3.2) | 비선형 슬리피지 정확히 모델링 |
| ③ Cash Yield | CD91 PIT-safe 일별 이자 | 60% 투자 시 +1.4%/yr 추가 수익 |
| ④ Buying Power | prorata / priority / strict 3 정책 | 발주 가능 자금 정확히 추적 |
| ⑤ Regime-Adaptive | EWMA + Hard Cap (PANIC 시 자본 50% 한도) | 위기 자동 방어 |

### 5. Stage 13 Live Trading (`/admin/live-trading`)
**5-Layer Safety + 3-Mode Router**

```
[Signal] → Layer 1: Static Risk (5 checks)
            ↓
          Layer 2: Dynamic Risk (5 checks)
            ↓
          Layer 3: Mode Router (SHADOW → PAPER → LIVE, token gate)
            ↓
          Layer 4: KIS Gateway (priority queue + circuit breaker)
            ↓
          Layer 5: Kill Switch (auto: -10% DD / -5% intraday / PANIC / API fail)
            ↓
          Audit Trail (모든 결정 영구 기록)
```

**LIVE 진입 안전장치:** `confirm_token="EXPLICIT_LIVE_CONFIRMED"` 명시 필수.

### 6. Production Hardening
- **Broker Reconciler** — KIS = 진실의 원천, Ghost/Missing position 자동 감지 + 자동 kill switch
- **Priority Queue Gateway** — heapq 기반 (KILL > SELL > BUY > QUERY), Circuit Breaker 5회 실패 → 30초 차단
- **Order State Machine** — 명시적 상태 전이 그래프, 장 마감 15:15 자동 정리
- **Real-time Notifier** — Slack/Discord, severity routing, 60초 dedup, async background worker

### 7. Valuation Engine (Phase 1) — `/api/v1/valuation/*`
**3개 모델 통합 가중평균:**

| 모델 | 공식 | 적합 |
|---|---|---|
| **RIM** | V = BPS + Σ(ROE-Ke)·BPS / (1+Ke)^t | 수익성 높은 기업 |
| **DCF** | V = ΣFCF / (1+WACC)^t + TV | 안정적 현금흐름 |
| **DDM** | V = ΣD / (1+Ke)^t + Pn | 배당주 / 금융주 |

자동 산출: **적정가 → 괴리율 → 판정 (극심한 저평가 ~ 극심한 고평가 7단계)**

### 8. 리스크 도구 (`/risk-tools`)
- VaR (Normal / EWMA-Parametric / Historical) · Expected Shortfall
- 포트폴리오 분산 + 상관관계
- 효율적 프론티어 (Markowitz)
- 팩터 회귀 (Fama-French)
- **종목 스크리너** — 알파벳 조건 빌더 (A AND B), 8개 팩터

### 9. 파생상품 (`/derivatives`)
- Black-76 옵션 프라이싱 + Greeks
- 변동성 표면 (3D surface)
- XVA / CVA — Hull-White 단기금리, PCA
- Hull-White / SABR 금리 모델
- Monte Carlo (이상치 옵션, ELS, KIKO)

---

## 📡 API Endpoints — 73개 신규 추가

### Stage 11 Multi-Backtest (10)
```
POST   /api/v1/multibacktest/init-schema
POST   /api/v1/multibacktest/run
GET    /api/v1/multibacktest/runs
GET    /api/v1/multibacktest/{run_id}
DELETE /api/v1/multibacktest/{run_id}
POST   /api/v1/multibacktest/attribution
POST   /api/v1/multibacktest/counterfactual
GET    /api/v1/multibacktest/counterfactual/scenarios
... (+ 2개)
```

### Stage 12 Realism (8)
```
POST /api/v1/realism/backtest
POST /api/v1/realism/market-impact/estimate
GET  /api/v1/realism/market-impact/calibration
GET  /api/v1/realism/cash-rate
POST /api/v1/realism/cash-yield/estimate
POST /api/v1/realism/buying-power/validate
POST /api/v1/realism/capacity/estimate
GET  /api/v1/realism/correlation-health
```

### Stage 13 Live Trading (14)
```
POST   /api/v1/live/init-schema
POST   /api/v1/live/orders/submit
GET    /api/v1/live/orders
GET    /api/v1/live/orders/{coid}
DELETE /api/v1/live/orders/{coid}
GET    /api/v1/live/balance
GET    /api/v1/live/mode
POST   /api/v1/live/mode                         # LIVE: token 필수
GET    /api/v1/live/kill-switch/status
POST   /api/v1/live/kill-switch/trigger          # 🚨
POST   /api/v1/live/kill-switch/resolve
GET    /api/v1/live/kill-switch/events
GET    /api/v1/live/audit
GET    /api/v1/live/audit/summary
GET    /api/v1/live/daily-pnl
```

### Stage 13+ Production Hardening (15)
```
POST /api/v1/live/reconcile/sync
GET  /api/v1/live/reconcile/status
GET  /api/v1/live/reconcile/history
POST /api/v1/live/reconcile/periodic/start
POST /api/v1/live/reconcile/periodic/stop

GET  /api/v1/live/gateway/stats
GET  /api/v1/live/orders/active
GET  /api/v1/live/orders/state-distribution
POST /api/v1/live/orders/cleanup-eod

POST /api/v1/live/notifier/test
GET  /api/v1/live/notifier/stats
GET  /api/v1/live/health
```

### Phase 1 Valuation (4)
```
POST /api/v1/valuation/evaluate              # RIM + DCF + DDM 통합
POST /api/v1/valuation/compare               # 다중 종목 비교
GET  /api/v1/valuation/financial/{stock_code}  # 재무 N년 시계열
GET  /api/v1/valuation/models                # 모델 카탈로그
```

### Phase 2 Screener (4)
```
POST /api/v1/screener/run                    # 전 종목 RIM·DCF·DDM 스캔
GET  /api/v1/screener/universes              # Universe 카탈로그 + 필터 차원
GET  /api/v1/screener/cache/stats            # 캐시 hit rate
POST /api/v1/screener/cache/clear            # 캐시 비우기
```

### Phase 3 AI Narrative Intelligence (10)
```
POST /api/v1/narrative/stock                 # 종목 분석 (Screener + Valuation)
POST /api/v1/narrative/portfolio             # 포트폴리오 (Backtest + Attribution)
POST /api/v1/narrative/macro                 # 매크로 브리핑 (Regime + 5 지표)
POST /api/v1/narrative/operations            # 운영 사건 (Kill switch + Audit)
POST /api/v1/narrative/counterfactual        # What-If 시나리오 비교
POST /api/v1/narrative/daily-summary         # 일일 활동 요약
POST /api/v1/narrative/stream/{domain}       # SSE 스트리밍
GET  /api/v1/narrative/usage                 # 토큰 + 비용 추적
GET  /api/v1/narrative/domains               # 도메인 카탈로그
GET  /api/v1/narrative/cache/stats           # 캐시 통계
POST /api/v1/narrative/cache/clear
```

### 베이스라인 API (Stage 1-10)
`/api/v1/strategies/*` · `/api/v1/backtests/*` · `/api/v1/var/*` · `/api/v1/options/*` · `/api/v1/xva/*` · `/api/v1/screener/*` · `/api/v1/regime/*` 등

전체 API는 `http://localhost:8000/docs` 에서 Swagger UI로 확인.

---

## 📂 디렉토리 구조

자세한 트리는 [PROJECT_STRUCTURE.md](./PROJECT_STRUCTURE.md) 참조.

```
.
├── main_api.py                          # FastAPI 단일 엔트리 (라우터 자동 등록)
├── src/
│   ├── engine/                          # 백테스트 + 매크로 + 리스크 + 가치평가
│   │   └── valuation/                   # RIM + DCF + DDM
│   ├── execution/                       # 실거래 (KIS API + 5-layer 안전장치)
│   ├── data/                            # DART 재무제표 클라이언트
│   ├── utils/                           # Slack/Discord 알림
│   ├── api/                             # FastAPI 라우터 (Stage 11~13+ + Valuation)
│   ├── kis_strategies/                  # KIS 10개 프리셋 전략
│   ├── models/                          # SQLAlchemy 모델
│   └── ...                              # 베이스라인 모듈들
├── frontend/                            # Next.js 14 (PortfolioVisualizer 스타일)
│   └── src/
│       ├── app/                         # App Router 페이지
│       ├── components/                  # 4 카테고리 + 멀티백테스트 + 실거래
│       └── lib/                         # presets · constants · YAML gen
├── tests/                               # pytest 테스트
└── docker-compose.yml                   # PostgreSQL + Backend + Frontend
```

---

## 🛡 안전 우선순위 (실거래 진입 전)

1. **`KIS_USE_MOCK=1`** — 1주일 이상 MockKISClient로 안정 운영
2. **`KIS_USE_MOCK=0`, `KIS_IS_PAPER=1`** — 1주일 이상 KIS 모의투자 운영
3. **Universe 화이트리스트** 명시적 등록 (`RiskGateway` 초기화 시 주입)
4. **RiskLimits** 보수적 조정
5. **Kill Switch** 수동 트리거 테스트 (cockpit + API 양쪽)
6. **Slack/Discord webhook** 통합 (`SLACK_WEBHOOK_URL`)
7. **`KIS_IS_PAPER=0`** — 소액 (예: 10만원)으로 첫 실거래 1주일

---

## 🗺 진화 로드맵

| Phase | 목표 | 상태 |
|---|---|:---:|
| Stage 1-10 (베이스라인) | 데이터·지표·백테스트·매크로·리스크·옵션·XVA·KIS API 통합 | ✅ |
| Stage 11 | Multi-Strategy 통합 백테스트 + 5-Factor Attribution | ✅ |
| Stage 12 | Production Realism Engine (5 hooks) | ✅ |
| Stage 13 | Live Trading + KIS API + 5-Layer Safety | ✅ |
| Stage 13+ | Production Hardening (Reconciler/Gateway/Notifier) | ✅ |
| **Phase 1** | Fundamental + Valuation (RIM/DCF/DDM) | ✅ |
| **Phase 2** | Smart Screener (재무 RIM·DCF·DDM 기반) | ✅ |
| **Phase 3** | AI Narrative (Claude API · 6 도메인 · 스트리밍) | ✅ |
| **Phase 4** | 한국 매크로 + 4-Quadrant + Yield Curve + Dynamic Linkage | ✅ |
| **Phase 5** | Premium UX — Command Center + Command Palette + Regime-Aware Theme | ✅ |

자세한 비교 분석은 [PLATFORM_EVOLUTION.md](./PLATFORM_EVOLUTION.md) 참조.

---

## 📚 문서

| 문서 | 내용 |
|---|---|
| [PROJECT_STRUCTURE.md](./PROJECT_STRUCTURE.md) | 전체 디렉토리 트리 + 모듈 설명 |
| [INTEGRATION_NOTES.md](./INTEGRATION_NOTES.md) | Stage 11~13 + Valuation 통합 가이드 |
| [STAGE11_INTEGRATION.md](./STAGE11_INTEGRATION.md) | Multi-Backtest 사용 가이드 |
| [STAGE12_INTEGRATION.md](./STAGE12_INTEGRATION.md) | Realism Engine 사용 가이드 |
| [STAGE13_INTEGRATION.md](./STAGE13_INTEGRATION.md) | Live Trading 가이드 + 안전 체크리스트 |
| [PLATFORM_EVOLUTION.md](./PLATFORM_EVOLUTION.md) | 밸리AI/젠포트 비교 + 5-Phase 로드맵 |

---

## ⚠ 책임 한계

본 시스템은 한국 주식 시장(KOSPI/KOSDAQ)을 대상으로 한 자동 매매 도구입니다. **실거래는 사용자 본인의 자금이 이동되며 모든 손익에 대한 책임은 사용자에게 있습니다.** 충분한 검증 없이 LIVE 모드로 진입하지 마세요.

## 🤝 기술 스택

- **Backend:** FastAPI · SQLAlchemy · asyncpg · pandas · numpy · scipy · QuantLib
- **Frontend:** Next.js 14 (App Router) · TypeScript 5 · React 18 · Tailwind CSS · Recharts · React Flow · Zustand · Lucide
- **Database:** PostgreSQL 15
- **Infrastructure:** Docker Compose · GCP e2-micro
- **External APIs:** 한국투자증권 OpenAPI · 금감원 DART OpenAPI · Slack/Discord Webhooks
