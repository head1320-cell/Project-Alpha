"""설명 표면 둘의 계약 (AB4)

설계: `docs/plans` AB

    POST /api/v1/explain/daily                                   보유 수준
    GET  /api/v1/multibacktest/{id}/attribution?include_daily=1  전략 수준
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

URL = "/api/v1/explain/daily"
HOLDINGS = {"005930": 60.0, "000660": 40.0}


@pytest.fixture(scope="module")
def client():
    from src.app_factory import create_app
    return TestClient(create_app())


def _post(client, **kw):
    body = {"holdings": dict(HOLDINGS), "weight_unit": "percent",
            "as_of": "2026-09-11"}
    body.update(kw)
    r = client.post(URL, json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ═══════════════════════════════════════════════════════════════════════════
# 보유 수준 표면
# ═══════════════════════════════════════════════════════════════════════════
def test_the_response_carries_a_korean_paragraph(client):
    """로드맵 완료 판정 — "하루치 설명이 한국어 한 문단으로 나온다"."""
    exp = _post(client)["explanation"]
    assert exp["summary_ko"] and "\n" not in exp["summary_ko"]
    assert "하루 변동" in exp["summary_ko"]


def test_the_same_request_gives_the_same_bytes(client):
    """★같은 입력에 항상 같은 문장★ — 감사 가능성의 요건."""
    a = _post(client)["explanation"]["summary_ko"]
    b = _post(client)["explanation"]["summary_ko"]
    assert a == b


def test_the_residual_and_missing_drivers_are_visible(client):
    """★설명하지 못한 몫이 보인다★ — 완료 판정의 세 번째 절."""
    exp = _post(client)["explanation"]
    assert "residual_pct" in exp and "residual_reason" in exp
    assert exp["missing_drivers"], "미측정 축이 하나도 없다고 보고했습니다"
    for name, why in exp["missing_drivers"].items():
        assert isinstance(why, str) and why.strip(), name


def test_dividend_and_fx_are_reported_as_unmeasurable(client):
    exp = _post(client)["explanation"]
    for d in ("dividend", "fx"):
        assert exp["drivers"][d] is None
        assert d in exp["missing_drivers"]


def test_the_price_axis_is_not_called_the_total(client):
    """★가격 기여를 총합으로 승격하지 않는다★"""
    exp = _post(client)["explanation"]
    assert exp["residual_pct"] is None
    assert "관측" in exp["residual_reason"]


def test_trades_absent_differs_from_trades_empty(client):
    """⑬ "매매 없음" ≠ "매매를 못 받음"."""
    unknown = _post(client)["explanation"]
    none_today = _post(client, trades=[], portfolio_value=1e8)["explanation"]
    assert unknown["drivers"]["rebalance"] is None
    assert none_today["drivers"]["rebalance"] == 0.0


def test_the_evidence_rollup_is_attached_without_target_or_macro(client):
    """⑮ AA3 의 축을 쓰되 이 표면이 다루지 않는 둘은 축이 아니다."""
    ev = _post(client)["evidence_rollup"]
    assert ev["axes"]["price"] is not None and ev["axes"]["as_of"] is not None
    assert ev["axes"]["target"] is None and ev["axes"]["macro"] is None
    assert "target" not in ev["applicable"]


def test_the_note_states_the_p1_boundary(client):
    note = _post(client)["note"]
    assert "계좌" in note and "LLM" in note


def test_an_ambiguous_weight_unit_is_refused(client):
    r = client.post(URL, json={"holdings": {"005930": 0.6, "000660": 0.4}})
    assert r.status_code == 422


def test_empty_holdings_are_refused(client):
    r = client.post(URL, json={"holdings": {}, "weight_unit": "percent"})
    assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# 전략 수준 — ★기존 응답에 덧붙일 뿐 기존 키는 그대로★
# ═══════════════════════════════════════════════════════════════════════════
def test_each_daily_row_explains_itself(monkeypatch):
    from src.api import stage11_routes as s11

    class _Fake:
        def __init__(self, engine): pass

        def decompose(self, run_id, include_daily=False):
            from src.engine.daily_explain_backtest import explain_backtest_day
            row = {"date": "2026-09-11", "portfolio_return": 0.41,
                   "allocation_effect": 0.31, "selection_effect": 0.16,
                   "macro_effect": None, "netting_effect": 0.0,
                   "cost_effect": -0.08, "regime": "GOLDILOCKS",
                   "coverage": {"n_total": 5, "n_known": 4, "complete": False,
                                "missing": ["macro_effect"]}}
            row["explanation"] = explain_backtest_day(row, run_id=run_id).to_dict()
            return {"available": True, "daily_attribution": [row]}

    monkeypatch.setattr("src.database.get_sync_engine", lambda: object())
    monkeypatch.setattr("src.engine.attribution_decomposer.AttributionDecomposer",
                        _Fake)
    body = s11.multibacktest_attribution(1, include_daily=True)
    row = body["daily_attribution"][0]
    # ★기존 키가 하나도 사라지지 않는다★
    for k in ("date", "portfolio_return", "allocation_effect", "regime"):
        assert k in row, k
    exp = row["explanation"]
    assert exp["driver_set"] == "strategy_effects"
    assert exp["residual_kind"] == "unexplained"
    # ★못 잰 드라이버를 이름으로 부른다★ — BH2 부터 드라이버는 수익률 항등식의 넷이라
    # (매크로는 보고 전용) 이 행에 없는 동일가중 기준이 불린다.
    assert "동일가중 기준" in exp["summary_ko"]
