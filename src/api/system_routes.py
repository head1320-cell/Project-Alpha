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

@router.websocket("/ws/live-risk/{ticker}")
async def live_risk(websocket: WebSocket, ticker: str):
    await websocket.accept()
    price      = 75_000.0
    portfolio_qty = 1_333
    try:
        while True:
            price += random.normalvariate(0, 150)
            price  = max(price, 1000)
            port_val   = price * portfolio_qty
            intra_var  = port_val * 0.01 * random.uniform(0.85, 1.15)
            is_breach  = trading_config["auto_mode"] and intra_var > trading_config["var_limit"]

            payload = {
                "ticker":       ticker,
                "price":        round(price, 0),
                "portfolio_value": round(port_val, 0),
                "intraday_var": round(intra_var, 0),
                "var_limit":    trading_config["var_limit"],
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
