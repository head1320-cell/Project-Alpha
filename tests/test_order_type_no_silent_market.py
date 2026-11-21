"""BV0b — ★지정가가 조용히 시장가로 바뀌지 않는다★ (BV0 읽기 전용 감사, 2026-10-08).

`src/kis_order_executor.py::OrderExecutor._determine_order_type` 은 신호 강도 0.5~0.8 이고 목표가가 없으면
현재가로 지정가를 정하려 했다. 그런데
  · 부른 메서드 `get_current_price` 는 두 클라이언트(`KISClient`·`MockKISClient`) 어디에도 없고(있는 것은 `get_price`),
  · 꺼내는 키 `"price"` 도 응답에 없으며(있는 것은 `"current_price"`),
  · 예외는 `except Exception: pass` 로 삼켜져
그 주문은 ★늘 시장가로★ 나갔다. TradingEngine 은 목표가를 넘기지 않으므로 이 구간의 실주문 전부가 그랬다.

CLAUDE.md §4 "침묵 폴백 금지", §6 실거래 안전. 여기서 고정하는 것:
  ① 현재가를 받으면 호가단위로 내린 지정가 · 짝: 강한 신호(≥0.8)는 지금처럼 시장가
  ② 현재가를 못 받으면(예외 · 0 · 없음) ★주문하지 않고★ 사유를 남긴다 — 시장가로 바꾸지 않는다
  ③ 목표가가 있으면 그것으로 지정가(현재가를 묻지 않는다)
"""
from __future__ import annotations

import pytest

from src.kis_order_executor import OrderExecutor


class _FakeClient:
    """주문 경로가 부르는 것만 흉내 낸다 — 네트워크 0."""

    def __init__(self, price_reply=None, price_error: Exception | None = None):
        self._price_reply = price_reply
        self._price_error = price_error
        self.price_calls: list[str] = []
        self.orders: list[dict] = []

    def get_price(self, ticker: str) -> dict:
        self.price_calls.append(ticker)
        if self._price_error is not None:
            raise self._price_error
        return self._price_reply

    def place_order(self, ticker, side, quantity, order_type="MARKET", price=None):
        self.orders.append({"ticker": ticker, "side": side, "quantity": quantity,
                            "order_type": order_type, "price": price})
        return {"kis_order_no": "T-1", "msg": "ok"}

    def get_balance(self) -> dict:
        return {"positions": []}


def _buy(client, strength: float, target_price: float | None = None):
    ex = OrderExecutor(client=client, allow_duplicate_buy=True)
    return ex.execute("005930", "삼성전자", "buy", strength=strength, quantity=3, target_price=target_price)


# ── ① 현재가를 받으면 지정가 ────────────────────────────────────────────────

def test_a_mid_strength_signal_goes_out_as_a_limit_order_at_the_current_price():
    client = _FakeClient(price_reply={"ticker": "005930", "current_price": 71_234.0})
    res = _buy(client, strength=0.6)
    assert res.success is True
    assert client.price_calls == ["005930"]
    assert client.orders == [{"ticker": "005930", "side": "BUY", "quantity": 3,
                              "order_type": "LIMIT", "price": 71_200.0}]  # 5만~20만원 구간 호가단위 100원으로 내림


def test_a_strong_signal_still_goes_out_as_a_market_order():
    """★짝★ — 강도 0.8 이상은 원래 설계대로 시장가이고 현재가를 묻지 않는다."""
    client = _FakeClient(price_reply={"current_price": 71_234.0})
    res = _buy(client, strength=0.9)
    assert res.success is True
    assert client.price_calls == []
    assert client.orders[0]["order_type"] == "MARKET" and client.orders[0]["price"] is None


# ── ② 현재가를 못 받으면 주문하지 않는다 ────────────────────────────────────

@pytest.mark.parametrize("client", [
    _FakeClient(price_error=RuntimeError("KIS 503")),
    _FakeClient(price_reply={"current_price": 0}),
    _FakeClient(price_reply={"current_price": None}),
    _FakeClient(price_reply={}),
], ids=["lookup-raises", "price-zero", "price-none", "price-missing"])
def test_without_a_current_price_no_order_is_sent_and_the_reason_is_kept(client):
    res = _buy(client, strength=0.6)
    assert client.orders == [], "현재가를 모르는데 주문이 나갔다(조용한 시장가)"
    assert res.success is False
    assert "현재가" in res.message


def test_the_failure_reason_names_what_went_wrong():
    client = _FakeClient(price_error=RuntimeError("KIS 503"))
    res = _buy(client, strength=0.6)
    assert "KIS 503" in res.message


# ── ③ 목표가가 있으면 그것으로 ─────────────────────────────────────────────

def test_a_target_price_sets_the_limit_without_asking_for_the_current_price():
    client = _FakeClient(price_error=RuntimeError("부르면 안 된다"))
    res = _buy(client, strength=0.6, target_price=70_050)
    assert res.success is True
    assert client.price_calls == []
    assert client.orders[0]["order_type"] == "LIMIT" and client.orders[0]["price"] == 70_000.0


def test_the_executor_only_calls_methods_the_real_clients_have():
    """감사가 찾은 뿌리 — 없는 메서드 이름을 다시 부르지 않는다."""
    import ast
    import pathlib

    from src.execution.kis_client import KISClient, MockKISClient

    tree = ast.parse(pathlib.Path("src/kis_order_executor.py").read_text(encoding="utf-8"))
    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "_client"
    }
    assert called, "검사가 아무것도 보지 못했다"
    for name in called:
        assert hasattr(KISClient, name) and hasattr(MockKISClient, name), f"self._client.{name} 은 클라이언트에 없다"
