"""내부자(임원·주요주주) 순매수 — DART elestock 온디맨드 집계.
KIS에 없는 유일한 수급 주체. 운영선 실데이터/None(합성 금지), mock 모드선 결정론적 합성.
가격 필요(순주식수 × 최근가 → 억). 가격/공시 없으면 None."""
from __future__ import annotations

import logging

from src.data.dart_client import get_corp_code, get_dart_client

logger = logging.getLogger(__name__)


def _disclosures(corp_code: str) -> list[dict]:
    """공유 DARTClient로 내부자 공시 조회 (테스트에서 monkeypatch 지점)."""
    return get_dart_client().get_insider_disclosures(corp_code)


def _cutoff(as_of: str | None, days: int) -> str:
    """YYYYMMDD 컷오프 = as_of - days (캘린더). as_of None이면 오늘."""
    from datetime import datetime, timedelta
    base = datetime.strptime(as_of, "%Y%m%d") if as_of else datetime.now()
    return (base - timedelta(days=days)).strftime("%Y%m%d")


def insider_net(stock_code: str, days: int = 20, price: float | None = None,
                as_of: str | None = None) -> float | None:
    """내부자 순취득(억, 매수 양수). 운영: 실 공시 윈도우 합 × 가격. mock: 합성."""
    from src.data.mock_gate import mock_allowed
    if not mock_allowed():
        if price is None or price <= 0:
            return None
        corp = get_corp_code(stock_code)
        if not corp:
            return None
        cutoff = _cutoff(as_of, days)
        rows = [r for r in _disclosures(corp) if r.get("rcept_date", "") >= cutoff]
        if not rows:
            return None
        net_shares = sum(int(r.get("irds_cnt", 0)) for r in rows)
        return round(net_shares * price / 1e8, 1)
    # mock 모드 — 결정론적 합성 (기존 _mock_supply 재사용, 종목 일관)
    from src.data.market_data import _mock_supply
    return round(_mock_supply(stock_code, "insider_net") * 0.3, 1)
