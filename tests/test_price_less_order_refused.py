"""가격 없는 주문은 ★거절하고 사유를 말한다★ — 위험 검사에서 터지지 않는다.

BV5 테스트 중 발견(2026-10-09): `POST /api/v1/live/orders/submit` 은 MARKET 주문에 가격을 요구하지 않는데,
`RiskGateway` 가 `quantity * price` 를 `price=None` 으로 계산해 500(`int * NoneType`)이 났고, 실행기를 직접 부르면
`KeyError: 'price'` 였다. 신호 감사 행만 남고 판정 행이 없는 반쪽 기록이었다.

정한 것: 가격을 모르면 한도(회전·비중·집중)를 잴 수 없으므로 ★거절 + 사유★. 0 으로 가정하지 않는다
(BV0b `OrderPriceUnavailable` 와 같은 규율). 시세로 채우는 길은 만들지 않았다.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

import src.database as dbmod
from src.execution.risk_gateway import RiskGateway, RiskLimits

_SECRET = "price-less-order-test-secret-0123456789ab"
_BASE = {"strategy_id": 1, "ticker": "005930", "side": "BUY", "quantity": 1}
_WHY = "가격 미상"


# ── 위험 게이트웨이 단위 ───────────────────────────────────────────────────

def _gw() -> RiskGateway:
    return RiskGateway(engine=None, limits=RiskLimits(), universe={"005930"}, bypass_market_hours=True)


_STATE = {"equity_krw": 100_000_000, "cash_krw": 100_000_000, "positions": {}, "daily_turnover_krw": 0}


@pytest.mark.parametrize("price", [None, 0, -100, "abc"])
def test_an_order_without_a_usable_price_is_refused_with_a_reason(price, monkeypatch):
    gw = _gw()
    tier2: list[int] = []
    monkeypatch.setattr(gw, "_tier2_dynamic_checks", lambda *a, **k: tier2.append(1))
    order = {**_BASE, "order_type": "MARKET"}
    if price is not None:
        order["price"] = price
    res = gw.check(order, dict(_STATE))
    assert res.approved is False
    assert any(_WHY in f for f in res.tier_failures), res.tier_failures
    assert tier2 == [], "가격을 모르는데 동적 검사까지 갔다"


def test_an_order_with_a_price_is_not_refused_for_its_price():
    """★짝★ — 언제나 '가격 미상' 으로 거절하는 구현을 배제한다."""
    for order_type in ("LIMIT", "MARKET"):
        res = _gw().check({**_BASE, "order_type": order_type, "price": 71000.0}, dict(_STATE))
        assert not any(_WHY in f for f in res.tier_failures), (order_type, res.tier_failures)


# ── 실제 경로 ──────────────────────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    dbmod.reset_session()
    dbmod.init_db()
    import src.api.stage13_routes as stage13
    import src.execution.kis_client as kc
    monkeypatch.setattr(stage13, "_EXECUTOR", None, raising=False)
    monkeypatch.setattr(kc, "_kis_singleton", None, raising=False)

    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        c.post("/api/v1/live/init-schema", headers=_admin(c))
        yield c

    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def _admin(client) -> dict[str, str]:
    tok = client.post("/api/v1/auth/login",
                      json={"username": "admin", "password": "frm123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _statuses() -> list[str]:
    from sqlalchemy import text
    with dbmod.get_engine().connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT status FROM live_orders"))]


def test_a_price_less_market_order_is_refused_not_crashed(client):
    res = client.post("/api/v1/live/orders/submit", json={**_BASE, "order_type": "MARKET"},
                      headers=_admin(client))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "REJECTED"
    assert _WHY in body["message"]
    assert "SUBMITTED" not in _statuses() and "FILLED" not in _statuses()
    events = client.get("/api/v1/live/audit", headers=_admin(client)).json()["events"]
    kinds = {e["event_type"] for e in events}
    assert "RISK_CHECK_REJECTED" in kinds, f"판정 행이 없다(반쪽 기록): {kinds}"


def test_a_priced_limit_order_is_not_refused_for_its_price(client):
    """★짝★ — 경로에서도 가격이 있으면 이 사유로 막지 않는다."""
    res = client.post("/api/v1/live/orders/submit",
                      json={**_BASE, "order_type": "LIMIT", "price": 71000.0}, headers=_admin(client))
    assert res.status_code == 200, res.text
    assert _WHY not in str(res.json().get("message") or "")


def test_calling_the_executor_without_a_price_key_is_the_same_refusal(client):
    import src.api.stage13_routes as stage13
    out = stage13.get_executor().execute_signal({**_BASE, "order_type": "MARKET"})
    assert out["status"] == "REJECTED"
    assert _WHY in out["message"]
