# 통합 가이드 — Stage 1-10 베이스라인 + Stage 11/12/13/13+/Valuation

> 이 ZIP은 기존 GCP 배포된 Stage 1-10 코드베이스 위에
> 본 세션에서 작성된 Stage 11~13+ + Valuation 코드를 통합한 단일 패키지입니다.

## 통합된 신규 모듈

### Backend (신규 19 파일)
```
src/engine/
  ├─ multibacktest_schema.py            # Stage 11 DB schema (3 tables)
  ├─ multi_strategy_backtest.py         # Stage 11 PIT-safe backtest
  ├─ attribution_decomposer.py          # Stage 11 5-Factor Brinson
  ├─ counterfactual_analyzer.py         # Stage 11 What-If
  ├─ portfolio_rebalancer.py            # Stage 11 4 rebalance policies
  ├─ market_impact.py                   # Stage 12 Square Root Law
  ├─ cash_management.py                 # Stage 12 Cash + Buying Power
  ├─ liquidity_capacity.py              # Stage 12 Capacity caps
  ├─ regime_adaptive_allocator.py       # Stage 12 EWMA + Hard Cap
  ├─ realism_engine.py                  # Stage 12 통합 백테스트
  ├─ reconciler.py                      # Stage 13+ Broker Reconciler
  ├─ order_tracker.py                   # Stage 13+ State Machine
  └─ valuation/
      ├─ __init__.py
      └─ valuation_models.py            # Phase 1 RIM + DCF + DDM

src/execution/                          # 신규 폴더 (Stage 13)
  ├─ live_schemas.py                    # 5 DB tables
  ├─ kis_client.py                      # KIS OpenAPI client + Mock
  ├─ risk_gateway.py                    # 2-Tier 10-check pre-trade
  ├─ audit_trail.py                     # 감사 로그
  ├─ kill_switch.py                     # 비상 정지
  ├─ order_executor.py                  # 3-mode router
  └─ order_executor_v2.py               # Production hardened

src/utils/                              # 신규 폴더 (Stage 13+)
  └─ notifier.py                        # Slack/Discord 실시간 알림

src/data/                               # 신규 폴더 (Phase 1)
  └─ dart_client.py                     # DART OpenAPI client

src/api/                                # 라우터 추가
  ├─ stage11_routes.py                  # 10 endpoints
  ├─ stage12_routes.py                  # 8 endpoints
  ├─ stage13_routes.py                  # 14 endpoints
  ├─ stage13_extensions.py              # 15 endpoints (production)
  ├─ kis_gateway.py                     # Priority Queue 게이트웨이
  └─ valuation_routes.py                # 4 endpoints (가치평가)
```

### Frontend (신규 17 파일)
```
frontend/src/
  ├─ lib/
  │   └─ realismData.ts
  ├─ components/
  │   ├─ multibacktest/   (6 components, Stage 11)
  │   ├─ realism/         (6 components, Stage 12)
  │   └─ live/            (1 component, Stage 13+)
  └─ app/admin/
      ├─ multi-backtest/page.tsx        # /admin/multi-backtest
      ├─ realism/page.tsx               # /admin/realism
      └─ live-trading/page.tsx          # /admin/live-trading
```

## main_api.py 자동 패치

기존 `main_api.py`의 `if __name__ == "__main__":` 직전에 다음이 자동 삽입됨:

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

기존 Stage 1-10 endpoint는 모두 그대로 작동. 신규 라우터 import가 실패해도 베이스라인은 정상 가동 (graceful degradation).

## 배포 (기존 GCP VM)

```bash
# 1. ZIP을 VM으로 전송
scp ficc-platform-complete.zip ti558759@ficc-risk-platform:~/

# 2. 압축 해제 + 기존 디렉토리 덮어쓰기
ssh ti558759@ficc-risk-platform
cd ~/ficc-platform
unzip -o ~/ficc-platform-complete.zip

# 3. 환경변수 추가
nano .env  # KIS_*, DART_API_KEY, SLACK_WEBHOOK_URL 추가

# 4. Docker 재기동
docker compose down
docker compose up --build -d

# 5. DB 초기화 (최초 1회)
curl -X POST http://localhost:8000/api/v1/multibacktest/init-schema
curl -X POST http://localhost:8000/api/v1/live/init-schema

# 6. 접속 확인
curl http://localhost:8000/api/v1/live/health
# → 전 시스템 종합 상태 단일 조회
```

## 누적 API Endpoints (총 51개)

| Stage | Prefix | Endpoints |
|---|---|---|
| 11 | /api/v1/multibacktest | 10 |
| 12 | /api/v1/realism | 8 |
| 13 | /api/v1/live | 14 |
| 13+ | /api/v1/live (extensions) | 15 |
| Phase 1 | /api/v1/valuation | 4 |
| **누적** | | **51 개** |

## 프론트엔드 페이지 (총 3개 신규)

| URL | 기능 |
|---|---|
| /admin/multi-backtest | Stage 11 Multi-Strategy Backtest |
| /admin/realism | Stage 12 Realism Panel (Ideal↔Reality) |
| /admin/live-trading | Stage 13 Live Trading Cockpit + Production Monitor |

기존 페이지(/, /backtest, /builder, /derivatives, /risk-tools)는 그대로 유지.

## 환경변수 (.env)

기존 .env에 다음 추가 필요:
```bash
# KIS OpenAPI
KIS_USE_MOCK=1         # 개발: 1 / 실거래: 0
KIS_IS_PAPER=1         # 모의투자: 1 / 실거래: 0
KIS_APP_KEY=...
KIS_APP_SECRET=...
KIS_ACCOUNT_NO=...

# DART (재무제표 — 미설정 시 Mock 데이터)
DART_API_KEY=

# 알림 (선택)
SLACK_WEBHOOK_URL=
DISCORD_WEBHOOK_URL=
```

## 검증 체크리스트

배포 후:
- [ ] `docker compose ps` — 모든 컨테이너 실행 중
- [ ] `curl http://localhost:8000/docs` — Swagger UI 51 endpoint 표시
- [ ] `curl http://localhost:8000/api/v1/live/health` — HEALTHY 응답
- [ ] http://localhost:3000/admin/multi-backtest 접속
- [ ] http://localhost:3000/admin/realism 접속
- [ ] http://localhost:3000/admin/live-trading 접속
- [ ] 기존 Stage 1-10 페이지도 정상 작동

## 안전 우선순위 (실거래 진입 전)

1. KIS_USE_MOCK=1로 1주일 안정 운영
2. KIS_USE_MOCK=0, KIS_IS_PAPER=1로 1주일 모의투자 운영
3. Universe whitelist 명시적 등록 (RiskGateway 초기화)
4. RiskLimits 보수 조정
5. Kill Switch 수동 트리거 테스트
6. Slack 알림 동작 확인
7. KIS_IS_PAPER=0으로 **소액**으로 첫 실거래
