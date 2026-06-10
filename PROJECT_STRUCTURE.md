# FICC Quant Platform — 전체 구조

## 디렉토리 트리

```
.
├── README.md                            # 프로젝트 개요
├── INTEGRATION_NOTES.md                 # Stage 11~13+Valuation 통합 가이드
├── PLATFORM_EVOLUTION.md                # 밸리AI/젠포트 비교 + 진화 로드맵
├── STAGE11_INTEGRATION.md               # Multi-Backtest 가이드
├── STAGE12_INTEGRATION.md               # Realism Engine 가이드
├── STAGE13_INTEGRATION.md               # Live Trading 가이드
├── PROJECT_STRUCTURE.md                 # 본 문서
│
├── main_api.py                          # FastAPI 단일 엔트리 (Stage 1~10 + 자동 라우터 등록 패치)
├── docker-compose.yml                   # PostgreSQL + Backend + Frontend
├── Dockerfile.backend
├── Dockerfile.frontend
├── deploy_gcp.sh                        # GCP 배포 스크립트
├── setup_server.sh                      # 초기 VM 설정
├── requirements.txt                     # Python 의존성
├── .env.example                         # 환경변수 템플릿
├── .gitignore
│
├── src/                                 # 백엔드 121 Python 파일
│   ├── engine/                          # 백테스트 + 매크로 + 리스크 + 가치평가
│   │   ├── {Stage 1-10 모듈들 — DAG, AST, Walk-Forward, Regime, Allocator, ...}
│   │   │
│   │   ├── multibacktest_schema.py     # [S11] 3 DB tables
│   │   ├── multi_strategy_backtest.py  # [S11] PIT-safe 일별 백테스트
│   │   ├── attribution_decomposer.py   # [S11] 5-Factor Brinson 분해
│   │   ├── counterfactual_analyzer.py  # [S11] What-If 시나리오
│   │   ├── portfolio_rebalancer.py     # [S11] 4 가지 리밸런싱 정책
│   │   │
│   │   ├── market_impact.py            # [S12] Square Root Law (Almgren-Chriss)
│   │   ├── cash_management.py          # [S12] Cash yield + Buying power
│   │   ├── liquidity_capacity.py       # [S12] ADV 기반 수용량 한계
│   │   ├── regime_adaptive_allocator.py # [S12] EWMA + Hard cap
│   │   ├── realism_engine.py           # [S12] 5-hooks 통합 백테스트
│   │   │
│   │   ├── reconciler.py               # [S13+] Broker ↔ Local 동기화
│   │   ├── order_tracker.py            # [S13+] 주문 상태 머신
│   │   ├── screener.py                # [Phase 2] 전 종목 가치평가 스크리너
│   │   │
│   │   └── valuation/                  # [Phase 1] 가치평가
│   │       ├── __init__.py
│   │       └── valuation_models.py     # RIM + DCF + DDM 통합
│   │
│   ├── execution/                      # [S13] 실거래 모듈 (신규 폴더)
│   │   ├── __init__.py
│   │   ├── live_schemas.py             # 5 DB tables (orders/fills/audit/pnl/kill)
│   │   ├── kis_client.py               # KIS OpenAPI + MockKISClient
│   │   ├── risk_gateway.py             # 2-Tier 10-check 검증
│   │   ├── audit_trail.py              # 모든 결정 감사 로그
│   │   ├── kill_switch.py              # 비상 정지 + 4 자동 트리거
│   │   ├── order_executor.py           # 3-mode router (SHADOW/PAPER/LIVE)
│   │   └── order_executor_v2.py        # [S13+] Production hardened
│   │
│   ├── data/                           # [Phase 1] 외부 데이터 (신규 폴더)
│   │   ├── __init__.py
│   │   └── dart_client.py              # DART OpenAPI 재무제표
│   │
│   ├── utils/                          # [S13+] 유틸리티 (신규 폴더)
│   │   ├── __init__.py
│   │   └── notifier.py                 # Slack/Discord 실시간 알림
│   │
│   ├── api/                            # FastAPI 라우터
│   │   ├── {기존 베이스라인 라우터들}
│   │   ├── stage11_routes.py           # [S11] /api/v1/multibacktest/* (10)
│   │   ├── stage12_routes.py           # [S12] /api/v1/realism/* (8)
│   │   ├── stage13_routes.py           # [S13] /api/v1/live/* (14)
│   │   ├── stage13_extensions.py       # [S13+] /api/v1/live/* extensions (15)
│   │   ├── kis_gateway.py              # [S13+] Priority Queue Gateway
│   │   ├── valuation_routes.py         # [P1] /api/v1/valuation/* (4)
│   │   └── screener_routes.py          # [P2] /api/v1/screener/* (4)
│   │
│   ├── kis_strategies/                 # KIS 10개 프리셋 전략
│   ├── models/                         # SQLAlchemy 모델
│   ├── migrations/                     # DB 마이그레이션
│   ├── data_loader.py                  # KRX 가격 데이터 로더
│   ├── database.py                     # async DB 엔진
│   ├── kis_*.py                        # KIS API 클라이언트 (베이스라인)
│   ├── screener_*.py                   # 종목 스크리너 백엔드
│   ├── ui_screener.py                  # Streamlit 스크리너 UI
│   └── ...
│
├── frontend/                           # Next.js 14 (PortfolioVisualizer 스타일)
│   ├── package.json                    # 20 dependencies
│   ├── tsconfig.json                   # strict 모드 + @/* path mapping
│   ├── tailwind.config.ts
│   ├── postcss.config.js
│   ├── next.config.js
│   │
│   └── src/
│       ├── app/                        # App Router
│       │   ├── layout.tsx              # PV 스타일 글로벌 layout + TopNav
│       │   ├── globals.css             # PV Design System (라이트 테마)
│       │   ├── page.tsx                # 홈 — Hero + 4 카테고리 카드
│       │   │
│       │   ├── builder/page.tsx        # 전략 빌더 (5 탭)
│       │   ├── backtest/page.tsx       # 백테스팅 (5 탭)
│       │   ├── risk-tools/page.tsx     # 리스크 도구 (5 탭, 스크리너 포함)
│       │   ├── derivatives/page.tsx    # 파생상품 (5 탭)
│       │   │
│       │   ├── screener/page.tsx           # [P2] RIM·DCF·DDM 통합 스크리너
│       │   │
│       │   └── admin/
│       │       ├── multi-backtest/page.tsx  # [S11] 통합 백테스트
│       │       ├── realism/page.tsx          # [S12] 현실 보정 패널
│       │       └── live-trading/page.tsx    # [S13] 실거래 콕핏
│       │
│       ├── components/
│       │   ├── layout/
│       │   │   └── TopNav.tsx                # PV 스타일 상단 네비
│       │   ├── ui/
│       │   │   └── index.tsx                 # PageHeader, Section 등 공통
│       │   │
│       │   ├── builder/                      # 전략 빌더 컴포넌트
│       │   │   ├── StrategyCanvas.tsx        # React Flow 캔버스
│       │   │   ├── IndicatorPanel.tsx        # 80개 지표 패널
│       │   │   ├── ConditionPanel.tsx        # 조건식 빌더
│       │   │   ├── Panels.tsx
│       │   │   └── nodes/
│       │   │       ├── DataSourceNode.tsx
│       │   │       ├── IndicatorNode.tsx
│       │   │       └── ActionNode.tsx
│       │   │
│       │   ├── charts/                       # 차트 컴포넌트
│       │   │   ├── TearSheet.tsx
│       │   │   ├── ParameterOptimizer.tsx
│       │   │   └── EquityChart.tsx
│       │   │
│       │   ├── multibacktest/                # [S11] 6 컴포넌트
│       │   │   ├── BacktestConfigPanel.tsx
│       │   │   ├── WeightTimeseriesChart.tsx
│       │   │   ├── EquityWithRegimeBand.tsx
│       │   │   ├── AttributionWaterfall.tsx
│       │   │   ├── RegimeAttributionTable.tsx
│       │   │   └── CounterfactualCompare.tsx
│       │   │
│       │   ├── realism/                      # [S12] 6 컴포넌트
│       │   │   ├── RealismToggle.tsx
│       │   │   ├── RealismKPIs.tsx
│       │   │   ├── ComparativeEquityChart.tsx
│       │   │   ├── ErosionWaterfall.tsx
│       │   │   ├── LiquidityMonitor.tsx
│       │   │   └── RealismDashboard.tsx
│       │   │
│       │   ├── valuation/                    # [P2] 종목 가치 시각화
│       │   │   ├── StockDetail.tsx            # Price-Value Band + Gap Gauge + Snapshot
│       │   │   └── ScreenerPanel.tsx          # Filter + Leaderboard + Quick Flip
│       │   │
│       │   └── live/                         # [S13+] 1 컴포넌트
│       │       └── ProductionMonitor.tsx
│       │
│       ├── lib/
│       │   ├── api.ts                        # FastAPI 호출 클라이언트
│       │   ├── realismData.ts                # [S12] 타입 + Mock + KPI 계산
│       │   └── builder/
│       │       ├── constants.ts              # 80 지표 + 63 캔들 패턴
│       │       ├── presets.ts                # 10 KIS 프리셋
│       │       ├── store.ts
│       │       └── yamlgen.ts                # DAG → YAML 변환
│       │
│       ├── store/
│       │   └── useFlowStore.ts               # Zustand (React Flow 상태)
│       │
│       └── types/
│           ├── builder.ts                    # IndicatorDefinition 등
│           └── ...
│
└── tests/                              # pytest 테스트
    └── ...
```

---

## 모듈별 핵심 책임

| 모듈 | 책임 | Stage |
|---|---|:---:|
| `src/engine/multi_strategy_backtest.py` | PIT-safe 일별 시뮬레이션 | 11 |
| `src/engine/attribution_decomposer.py` | 5-Factor Brinson 분해 | 11 |
| `src/engine/realism_engine.py` | 5 hooks 통합 백테스트 | 12 |
| `src/engine/market_impact.py` | Square Root Law (Almgren-Chriss) | 12 |
| `src/engine/regime_adaptive_allocator.py` | EWMA + Hard cap 위기 대응 | 12 |
| `src/engine/reconciler.py` | KIS = 진실의 원천 동기화 | 13+ |
| `src/engine/order_tracker.py` | 명시적 상태 머신 + 장 마감 정리 | 13+ |
| `src/engine/valuation/valuation_models.py` | RIM + DCF + DDM 통합 가중평균 | P1 |
| `src/engine/screener.py` | 전 종목 병렬 가치평가 + Composite Score + LRU 캐시 | P2 |
| `src/execution/kis_client.py` | KIS OpenAPI + MockKISClient | 13 |
| `src/execution/risk_gateway.py` | 2-Tier 10-check pre-trade 검증 | 13 |
| `src/execution/kill_switch.py` | 비상 정지 (수동 + 자동 4 트리거) | 13 |
| `src/execution/order_executor.py` | 3-mode router (SHADOW/PAPER/LIVE) | 13 |
| `src/api/kis_gateway.py` | Priority Queue + Circuit Breaker | 13+ |
| `src/utils/notifier.py` | Slack/Discord async dispatch | 13+ |
| `src/data/dart_client.py` | DART OpenAPI 재무제표 수집 | P1 |

---

## 통합 패치 위치

기존 `main_api.py`의 `if __name__ == "__main__":` 직전에 18줄 자동 삽입:

```python
# ═══ Stage 11/12/13/Valuation Routers (auto-integrated) ═══
try:
    from src.api.stage11_routes import router as stage11_router
    from src.api.stage12_routes import router as stage12_router
    from src.api.stage13_routes import router as stage13_router
    from src.api.stage13_extensions import router as stage13_ext_router
    from src.api.valuation_routes import router as valuation_router
    app.include_router(stage11_router)
    app.include_router(stage12_router)
    app.include_router(stage13_router)
    app.include_router(stage13_ext_router)
    app.include_router(valuation_router)
    print("✓ Stage 11/12/13/Valuation 라우터 등록 완료 (51 endpoints)")
except ImportError as e:
    print(f"⚠ Stage 11+ 라우터 import 실패 (선택적): {e}")
```

→ 기존 Stage 1-10 endpoint는 그대로 작동. 신규 라우터 import 실패해도 베이스라인은 정상 가동 (graceful degradation).

---

## PortfolioVisualizer 디자인 시스템

| Token | Value |
|---|---|
| Primary brand | `#1200ff` (electric blue) |
| Primary hover | `#0e00cc` |
| Body text | `#212529` |
| Body bg | `#fff` |
| Border | `#dee2e6` |
| Light bg | `#f8f9fa`, `#f3f4f7` |
| Subtle bg | `#e2e7f2` |
| Navbar bg | `#07005c` (deep navy) |
| Hero gradient | `#07005c → #1200ff` |
| Font (body) | Roboto |
| Font (mono) | Roboto Mono |
| Border radius | 0.375rem (6px) |
| Body font size | 0.875rem (14px) |
| Body line height | 1.3125 |

`globals.css`에 PV Design System 전체 토큰이 정의되어 있음.

---

## 통계 (이번 통합본 기준)

| 카테고리 | 수치 |
|---|---|
| Backend Python | 121 files (~44,000 lines) |
| Frontend TS/TSX | 43 files (~2,600 lines) |
| Documentation | 7 .md files |
| Shell scripts | 2 (deploy + setup) |
| Dockerfiles | 3 |
| Tests | 4 files |
| **Total** | **235 files in ZIP** |

| API Endpoints | 수치 |
|---|---|
| 베이스라인 (Stage 1-10) | ~76 |
| Stage 11 (multibacktest) | 10 |
| Stage 12 (realism) | 8 |
| Stage 13 (live trading) | 14 |
| Stage 13+ (production hardening) | 15 |
| Phase 1 (valuation) | 4 |
| Phase 2 (screener) | 4 |
| **신규 누적** | **55** |
