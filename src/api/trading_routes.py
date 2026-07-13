"""
Trading Routes — Screener V3 실거래 자동매매 API
==========================================================================
스크리너/시그널 → 안전장치 → KIS 주문의 HTTP 인터페이스.

★ 안전 최우선 ★
  - 모든 엔드포인트 기본 dry_run=True
  - 실주문은 명시적 dry_run=false + 모드 확인 필요
  - kill_switch, 손실한도 등 안전장치 노출
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.data.mock_gate import mock_allowed

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/trading", tags=["trading"])


# ═══════════════════════════════════════════════════════════════════════════════
# 모델
# ═══════════════════════════════════════════════════════════════════════════════

class SafetyConfigModel(BaseModel):
    kill_switch: bool = False
    dry_run: bool = True                       # 기본 안전
    max_position_pct: float = Field(default=0.20, ge=0.01, le=1.0)
    max_order_amount_krw: float = Field(default=10_000_000, ge=0)
    max_daily_invest_krw: float = Field(default=50_000_000, ge=0)
    max_positions: int = Field(default=10, ge=0, le=100)
    daily_loss_limit_pct: float = Field(default=-5.0, le=0)
    min_order_amount_krw: float = Field(default=100_000, ge=0)
    allow_duplicate_buy: bool = False


class SignalModel(BaseModel):
    stock_code: str
    stock_name: str = ""
    action: str                                # buy | sell | hold
    strength: float = Field(default=1.0, ge=0, le=1)
    target_weight: float | None = None
    reason: str = ""


class ExecuteSignalsRequest(BaseModel):
    signals: list[SignalModel]
    safety: SafetyConfigModel = SafetyConfigModel()


class ScreenToTradeRequest(BaseModel):
    # 스크리닝
    universe: str = "kospi200"
    filter_ast: dict
    liquidity_floor: str = "standard"
    max_tickers: int = Field(default=10, ge=1, le=30)
    sort_by: str = "composite_score"
    # 매매 설정
    action: str = "buy"                        # 통상 buy (스크리닝 종목 매수)
    equal_weight: bool = True                  # 균등 비중 배분
    safety: SafetyConfigModel = SafetyConfigModel()


# ═══════════════════════════════════════════════════════════════════════════════
# 헬퍼
# ═══════════════════════════════════════════════════════════════════════════════

def _build_engine(safety_model: SafetyConfigModel):
    from src.engine.trading_engine import SafetyConfig, TradingEngine
    safety = SafetyConfig(**safety_model.model_dump())
    return TradingEngine(safety=safety)


# ═══════════════════════════════════════════════════════════════════════════════
# 엔드포인트
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/status")
def trading_status():
    """현재 계좌 상태 + 모드 (mock/paper/real)."""
    try:
        from src.engine.trading_engine import SafetyConfig, TradingEngine
        engine = TradingEngine(safety=SafetyConfig(dry_run=True))
        return engine.get_account_status()
    except Exception as e:
        raise HTTPException(500, f"계좌 조회 실패: {e}")


@router.get("/mode")
def trading_mode():
    """현재 KIS 연동 모드 안내."""
    use_mock = mock_allowed()
    is_paper = os.getenv("KIS_IS_PAPER", "1") == "1"
    has_key = bool(os.getenv("KIS_APP_KEY"))
    if use_mock or not has_key:
        mode, desc = "mock", "Mock 모드 — 가짜 데이터, 실주문 없음"
    elif is_paper:
        mode, desc = "paper", "모의투자 — KIS 모의계좌, 가상 자금"
    else:
        mode, desc = "real", "⚠ 실계좌 — 실제 자금이 거래됩니다"
    return {"mode": mode, "description": desc, "kis_use_mock": use_mock,
            "kis_is_paper": is_paper, "has_key": has_key}


@router.post("/execute")
def execute_signals(req: ExecuteSignalsRequest):
    """시그널 직접 실행 (안전장치 적용)."""
    try:
        from src.engine.trading_engine import TradeSignal
        engine = _build_engine(req.safety)
        signals = [TradeSignal(
            stock_code=s.stock_code, stock_name=s.stock_name, action=s.action,
            strength=s.strength, target_weight=s.target_weight, reason=s.reason,
        ) for s in req.signals]
        return engine.execute_signals(signals)
    except Exception as e:
        raise HTTPException(500, f"시그널 실행 실패: {e}")


@router.post("/screen-to-trade")
def screen_to_trade(req: ScreenToTradeRequest):
    """
    원클릭: 스크리닝 → 통과 종목 자동 매매.

    1) 스크리닝 (유동성 게이트 + 펀더멘털)
    2) 통과 상위 N종목 → 매매 시그널 변환 (균등 비중 옵션)
    3) 안전장치 적용하여 주문 실행 (기본 dry_run)

    스크리너 → 실거래를 잇는 핵심 연결.
    """
    try:
        from src.engine.filter_ast import parse_group
        from src.engine.screener import ValuationScreener
        from src.engine.trading_engine import TradeSignal

        # 1) 스크리닝
        screener = ValuationScreener()
        ast = parse_group(req.filter_ast)
        result = screener.run(
            universe=req.universe, filter_ast=ast, sort_by=req.sort_by,
            limit=req.max_tickers, liquidity_floor=req.liquidity_floor,
        )
        screened = result.items[:req.max_tickers]
        if not screened:
            return {"error": True, "message": "스크리닝 통과 종목 없음", "screened_count": 0}

        # 2) 시그널 변환
        weight = (1.0 / len(screened)) if req.equal_weight else None
        # 비중이 안전장치 max_position_pct 초과하지 않도록
        if weight and weight > req.safety.max_position_pct:
            weight = req.safety.max_position_pct
        signals = [TradeSignal(
            stock_code=it.stock_code,
            stock_name=getattr(it, "corp_name", "") or it.stock_code,
            action=req.action, strength=1.0, target_weight=weight,
            reason=f"스크리닝 통과 (점수 {getattr(it,'composite_score',0):.0f})",
        ) for it in screened]

        # 3) 실행
        engine = _build_engine(req.safety)
        exec_result = engine.execute_signals(signals)
        exec_result["screened_tickers"] = [
            {"stock_code": it.stock_code, "corp_name": getattr(it, "corp_name", ""),
             "composite_score": getattr(it, "composite_score", None)}
            for it in screened
        ]
        exec_result["screened_count"] = len(screened)
        return exec_result
    except Exception as e:
        raise HTTPException(500, f"screen-to-trade 실패: {e}")


@router.post("/kill-switch")
def toggle_kill_switch(enable: bool = True):
    """
    Kill Switch 안내 — 실제 차단은 각 요청의 safety.kill_switch로 적용.
    (상태 저장은 클라이언트/세션에서 관리)
    """
    return {
        "kill_switch": enable,
        "message": "모든 신규 주문 차단" if enable else "정상 거래 가능",
        "note": "각 execute/screen-to-trade 요청의 safety.kill_switch=true로 적용하세요",
    }
