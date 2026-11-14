"""POST /api/v1/trade-journal/analyze — 체결 내역을 받아 매매일지를 계산해 돌려준다 (설계: 2026-11-14 매매일지 §6).

★저장하지 않는다★ — 받은 체결 줄은 계산에만 쓰고 버린다. DB · 파일에 쓰지 않고, 로그에는 줄 수만 남긴다(종목·수량·금액 없음).
그래서 상태도 mock 게이트도 없다: 이 문은 받은 줄만 가지고 답한다(지어내는 값이 없다 — 모르는 것은 `None` + 사유).
계산은 `src/engine/trade_journal` 의 순수 함수가 하고, 이 문은 ⑴ 로그인 ⑵ 줄 수 상한 ⑶ 종목 마스터를 엔진에 건네는 일만 한다.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.auth import require_login
from src.data.stock_master import get_stock_name, load_master_flags
from src.engine.trade_journal import analyze

logger = logging.getLogger("api.trade_journal")
router = APIRouter(prefix="/api/v1/trade-journal", tags=["trade-journal"])

#: 한 번에 받는 체결 줄의 상한. 넘으면 ★잘라서 계산하지 않는다★ — 앞부분만의 통계는 다른 통계다.
MAX_FILLS = 20_000


class AnalyzeBody(BaseModel):
    fills: list[dict]
    commission_bp: float | None = Field(None, ge=0, le=1_000)       # 편도 수수료율(bp). 없으면 모름 — 0 과 다르다
    unknown_market: Literal["KOSPI", "KOSDAQ", "KONEX"] | None = None
    unknown_instrument: Literal["stock", "etf"] | None = None


def _master_lookup():
    """종목 → 마스터 플래그(+ 이름). 이름은 `stock_master.get_stock_name` 하나로 정한다(단일 진실 공급원)."""
    flags = load_master_flags()
    seen: dict[str, dict | None] = {}

    def lookup(symbol: str) -> dict | None:
        if symbol not in seen:
            code = symbol.strip().upper()
            if code not in flags and len(code) == 7 and code.startswith("A"):       # 'A005930' 꼴의 단축코드
                code = code[1:]
            record = dict(flags.get(code) or {})
            name = get_stock_name(code)
            if name:
                record["name"] = name
            seen[symbol] = record or None
        return seen[symbol]

    return lookup


@router.post("/analyze")
def analyze_trades(body: AnalyzeBody, _principal=Depends(require_login)):
    rows = len(body.fills)
    if rows == 0:
        raise HTTPException(400, {"code": "no_rows", "reason": "분석할 체결 줄이 없습니다."})
    if rows > MAX_FILLS:
        raise HTTPException(400, {"code": "too_many_rows", "limit": MAX_FILLS, "rows": rows,
                                  "reason": f"체결 줄이 {rows:,}건으로 상한 {MAX_FILLS:,}건을 넘습니다. 기간을 나눠 올려 주십시오(앞부분만 잘라 계산하지 않습니다)."})
    out = analyze(body.fills, {"commission_bp": body.commission_bp, "unknown_market": body.unknown_market,
                               "unknown_instrument": body.unknown_instrument}, master=_master_lookup())
    inputs = out.get("inputs") or {}
    logger.info("trade-journal analyze: rows=%s fills=%s rejected=%s", rows, inputs.get("fills"), inputs.get("rejected"))
    return {**out, "limits": {"fills": MAX_FILLS}}
