"""루트·헬스체크·실시간 리스크 웹소켓 — main_api.py에서 분리(경로·동작 불변).
"""

import asyncio
import logging
import random
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.state.trading_state import trading_config

logger = logging.getLogger("api.system")
router = APIRouter(tags=["system"])


@router.get("/")
def root():
    return {"status": "Risk API is running", "version": "2.0.0",
            "timestamp": datetime.now().isoformat()}

@router.get("/health")
def health():
    return {"status": "ok"}

LIVE_RISK_SYNTHETIC = "합성 데이터 모드의 위험 흐름입니다 — 실제 시세·보유·VaR 이 아닙니다."
LIVE_RISK_NO_FEED = "실시간 위험 흐름은 실데이터 원천이 연결돼 있지 않아 값이 없습니다."


@router.websocket("/ws/live-risk/{ticker}")
async def live_risk(websocket: WebSocket, ticker: str):
    """실시간 위험 흐름 — ★운영에서는 값을 만들지 않는다★(사유를 한 번 보내고 닫는다).

    이 흐름의 시세·보유 수량·VaR 은 전부 난수다(실시간 원천이 연결돼 있지 않다). 그래서 mock 모드에서만
    내보내고, 메시지마다 합성이라고 적는다. 예전에는 게이트·라벨 없이 내보냈다."""
    await websocket.accept()
    from src.data.mock_gate import mock_allowed
    if not mock_allowed():
        await websocket.send_json({"ticker": ticker, "available": False, "is_mock": False,
                                   "reason": "no_feed", "message": LIVE_RISK_NO_FEED})
        await websocket.close()
        return
    price      = 75_000.0
    portfolio_qty = 1_333
    try:
        while True:
            price += random.normalvariate(0, 150)
            price  = max(price, 1000)
            port_val   = price * portfolio_qty
            intra_var  = port_val * 0.01 * random.uniform(0.85, 1.15)
            # 판정 키는 토글 라우트가 불려야 생긴다 — 없으면 한도 미설정이다(예전에는 여기서 KeyError 로 끝났다).
            var_limit  = trading_config.get("var_limit")
            is_breach  = bool(trading_config.get("auto_mode")) and var_limit is not None and intra_var > var_limit

            payload = {
                "ticker":       ticker,
                "available":    True,
                "is_mock":      True,
                "message":      LIVE_RISK_SYNTHETIC,
                "price":        round(price, 0),
                "portfolio_value": round(port_val, 0),
                "intraday_var": round(intra_var, 0),
                "var_limit":    var_limit,
                "breach":       is_breach,
                "timestamp":    datetime.now().strftime("%H:%M:%S"),
            }

            # Auto-hedge trigger
            if is_breach:
                payload["alert"] = "VaR 한도 초과 — 자동 헤지 신호 발생"

            await websocket.send_json(payload)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
