"""FastAPI 앱 조립 — CORS · 관측성 · 기동 시퀀스 · 라우터 등록.

main_api.py는 이 팩토리를 호출하는 얇은 진입점일 뿐이다(`uvicorn main_api:app` 계약 유지).
라우트 자체는 전부 src/api/*_routes.py에 있고, 여기서는 조립만 한다.

라우터를 추가하려면 아래 ROUTER_MODULES에 모듈 경로를 한 줄 넣으면 된다 —
등록 순서 = 이 목록의 순서.
"""

from __future__ import annotations

import importlib
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("api.factory")

# 등록할 라우터 모듈 (각 모듈은 `router: APIRouter`를 노출).
# 앞쪽 11개는 main_api.py에서 도메인별로 분리해 나온 것들이고, 뒤쪽은 기존 라우터.
ROUTER_MODULES: tuple[str, ...] = (
    "src.api.system_routes",
    "src.api.data_routes",
    "src.api.risk_routes",
    "src.api.credit_routes",
    "src.api.ai_routes",
    "src.api.strategy_routes",
    "src.api.portfolio_routes",
    "src.api.screener_legacy_routes",
    "src.api.derivatives_routes",
    "src.api.account_order_routes",
    "src.api.market_data_routes",
    "src.api.stage11_routes",
    "src.api.stage12_routes",
    "src.api.stage13_routes",
    "src.api.stage13_extensions",
    "src.api.valuation_routes",
    "src.api.company_routes",
    "src.api.screener_routes",
    "src.api.screener_universe_count",
    "src.api.narrative_routes",
    "src.api.macro_routes",
    "src.api.trading_routes",
    "src.api.allocation_routes",
    "src.api.timing_routes",
    "src.api.research_routes",
    "src.api.regime_snapshot_routes",
    "src.api.alpha_routes",
    "src.api.execution_routes",
    "src.api.attribution_routes",
    "src.api.experimental_routes",
    "src.api.sleeve_routes",
    "src.api.backtest_run_routes",
)

CORS_ORIGINS = [
    "http://localhost:3000",      # Next.js 로컬 개발
    "http://localhost:8000",      # FastAPI 자체 (Swagger UI)
    "http://127.0.0.1:3000",
    "*",                          # 개발/배포 임시 허용
]


def register_routers(app: FastAPI) -> int:
    """ROUTER_MODULES를 순서대로 등록하고 등록된 라우터 수를 반환.

    한 모듈이 실패해도 나머지는 계속 등록한다(기존 동작 유지) — 다만 조용히 넘기지 않고
    무엇이 왜 빠졌는지 로그로 남긴다.
    """
    n = 0
    for mod in ROUTER_MODULES:
        try:
            app.include_router(importlib.import_module(mod).router)
            n += 1
        except Exception as e:
            logger.error(f"라우터 등록 실패 — {mod}: {e}")
    logger.info(f"라우터 {n}/{len(ROUTER_MODULES)}개 등록 완료")
    return n


def create_app() -> FastAPI:
    app = FastAPI(
        title="FICC Risk Management API",
        version="2.0.0",
        description="Full-stack quantitative risk platform: VaR, Greeks, Hedging, AI Forecasting",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 관측성: 구조화 로깅 + 요청 추적 ID + 요청 로깅 + 예외 안전망
    try:
        from src.observability.logging_config import setup_logging
        from src.observability.middleware import install_observability
        setup_logging()
        install_observability(app)
    except Exception as e:
        logging.getLogger(__name__).warning(f"관측성 설치 실패(계속 진행): {e}")

    from src.startup.lifecycle import run_startup
    app.add_event_handler("startup", run_startup)

    register_routers(app)
    return app
