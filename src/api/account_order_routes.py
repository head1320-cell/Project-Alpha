"""계좌·주문·자동매매 토글 — main_api.py에서 분리(경로·동작 불변).
"""

import logging

from fastapi import APIRouter, HTTPException

from src.api.legacy_schemas import (
    AutoTradingConfig,
    BatchOrderRequest,
    OrderRequest,
)
from src.database import get_trade_history
from src.state.trading_state import trading_config

logger = logging.getLogger("api.account_order")
router = APIRouter(tags=["account_order"])


@router.get("/trade-history/{username}")
def trade_history(username: str):
    return {"history": get_trade_history(username)}

@router.post("/toggle-auto-trading")
def toggle_auto_trading(cfg: AutoTradingConfig):
    trading_config["auto_mode"] = cfg.auto_mode
    trading_config["var_limit"] = cfg.var_limit
    return {
        "auto_mode": trading_config["auto_mode"],
        "var_limit": trading_config["var_limit"],
        "message":   f"Auto-trading {'ENABLED' if cfg.auto_mode else 'DISABLED'}",
    }

@router.get("/trading-status")
def trading_status():
    return trading_config

def _kis_mode_label(client) -> str:
    """정식 KIS 클라이언트(execution/kis_client.py) 인스턴스 → "mock"|"paper"|"real" 표시용 라벨."""
    if type(client).__name__ == "MockKISClient":
        return "mock"
    return "paper" if getattr(getattr(client, "creds", None), "is_paper", True) else "real"

@router.get("/api/v1/account/holdings")
def get_holdings():
    """KIS API로 현재 보유 종목 조회."""
    try:
        from src.execution.kis_client import get_kis_client
        from src.kis_order_executor import PositionManager
        client = get_kis_client()
        pm = PositionManager(client)
        positions = pm.get_positions(refresh=True)
        return {
            "mode": _kis_mode_label(client),
            "count": len(positions),
            "positions": [p.to_dict() for p in positions],
        }
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")

@router.get("/api/v1/account/balance")
def get_balance():
    """예수금 및 평가금액 조회."""
    try:
        from src.execution.kis_client import get_kis_client
        client = get_kis_client()
        balance = client.get_balance()
        return {
            "mode": _kis_mode_label(client),
            "deposit": balance.get("deposit", 0),
            "eval_amount": balance.get("evaluated_total", 0),
            "profit_loss": balance.get("profit_loss", 0),
            "profit_rate": balance.get("profit_rate", 0),
        }
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")

def _trade_record_to_legacy(rec: dict) -> dict:
    """TradeRecord.to_dict() → 구 OrderResult.to_dict() 응답 형태로 역변환(레거시 호환)."""
    return {
        "success": rec["success"], "stock_code": rec["stock_code"],
        "stock_name": rec["stock_name"], "action": rec["action"],
        "quantity": rec["quantity"], "price": rec["price"],
        "order_no": rec["order_no"], "message": rec["message"],
        "timestamp": rec["timestamp"], "blocked_by": rec.get("blocked_by"),
    }

@router.post("/api/v1/orders/execute")
def execute_order(req: OrderRequest):
    """
    단일 주문 실행 — TradingEngine(6중 안전장치) 경유.

    quantity/target_price는 참고용(미사용) — 포지션 사이징은 안전장치(SafetyConfig)가
    strength 기반으로 산정. 항상 dry_run(모의 실행)만 수행 — 실거래/세부 안전설정이
    필요하면 /api/v1/trading/execute(safety 파라미터로 전체 제어 가능)를 사용할 것.
    """
    try:
        from src.engine.trading_engine import SafetyConfig, TradeSignal, TradingEngine

        engine = TradingEngine(safety=SafetyConfig(dry_run=True))
        signal = TradeSignal(
            stock_code=req.stock_code,
            stock_name=req.stock_name or req.stock_code,
            action=req.action.lower(),
            strength=req.strength,
        )
        result = engine.execute_signals([signal])
        rec = (result["executed"] or result["blocked"])[0]
        return {**_trade_record_to_legacy(rec), "mode": result["mode"]}
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")

@router.post("/api/v1/orders/batch")
def batch_execute_orders(req: BatchOrderRequest):
    """
    시그널 일괄 실행 — TradingEngine(6중 안전장치) 경유, 항상 dry_run(모의 실행).
    매도 시그널이 매수보다 먼저 처리됨(현금 확보 우선, TradingEngine 기본 동작) —
    응답 순서가 req.orders 입력 순서와 다를 수 있음.
    """
    try:
        from src.engine.trading_engine import SafetyConfig, TradeSignal, TradingEngine

        engine = TradingEngine(safety=SafetyConfig(dry_run=True))
        signals = [TradeSignal(
            stock_code=o.stock_code,
            stock_name=o.stock_name or o.stock_code,
            action=o.action.lower(),
            strength=o.strength,
        ) for o in req.orders]
        result = engine.execute_signals(signals)
        orders_out = [_trade_record_to_legacy(rec) for rec in result["executed"] + result["blocked"]]
        success_count = sum(1 for r in orders_out if r["success"])
        return {
            "total": len(orders_out),
            "success": success_count,
            "failed": len(orders_out) - success_count,
            "orders": orders_out,
            "mode": result["mode"],
        }
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
