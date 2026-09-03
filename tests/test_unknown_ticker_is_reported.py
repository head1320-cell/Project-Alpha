"""종목 마스터가 **모르는** 코드를 응답이 말한다 — 막지는 않는다.

★착수 0단계 실측★

    POST /analyze  tickers = ["005930", "ZZZZZZ", "NOTREAL"]
        error    : False
        excluded : []                    ← 아무것도 빠지지 않았다고 말한다
        weights  : {"005930": 10.82, "ZZZZZZ": 89.18}

mock 생성기가 **어떤 문자열에도** 가격 이력을 만들어 주므로(262행) 오타 하나가
완전한 이력을 갖고 최적화에 들어가 **최대 비중**을 차지한다. 그런데 판정 능력은
이미 있었다 — `get_stock_name("ZZZZZZ")` 는 `None` 이고, ★아무도 묻지 않았다★
(`src/api/*.py` 전체에서 티커를 검증하는 라우트가 0개였다).

CLAUDE.md 가 이미 금지하는 계열이다: *"가짜 종목코드(100000~) 재도입 금지."*

★막지 않고 말한다★ `SPY` 도 마스터에는 없지만 해외 상장은 연구 대상으로 정당하다
(벤치마크 §8 의 경제노출/상품 분리). 주문을 거부하는 것은 직전 슬라이스의
`untradable` 게이트의 일이고, 이 슬라이스는 **응답이 사실을 말하게** 할 뿐이다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.data.stock_master import unknown_codes  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


def _analyze(client, tickers):
    r = client.post("/api/v1/allocation/analyze",
                    json={"tickers": tickers, "model": "mvo"})
    assert r.status_code == 200, r.text
    return r.json()


# ── 1. ★실측 재현★ ──────────────────────────────────────────────────────
def test_an_unknown_code_is_named_in_the_response(client):
    b = _analyze(client, ["005930", "ZZZZZZ"])
    assert b["unknown_tickers"]["codes"] == ["ZZZZZZ"], b["unknown_tickers"]


def test_real_codes_produce_an_empty_list(client):
    """★짝 — 항상 무언가를 지목하면 그것도 거짓이다★"""
    b = _analyze(client, ["005930", "069500"])
    assert b["unknown_tickers"]["codes"] == []
    assert b["unknown_tickers"]["note"] is None


def test_the_judgement_uses_get_stock_name_not_resolve_name():
    """★`resolve_name` 은 표시용 폴백이라 판정에 쓰면 항상 '안다' 가 된다★"""
    from src.data.stock_master import resolve_name
    assert resolve_name("ZZZZZZ") == "종목 ZZZZZZ", "폴백 관례가 바뀌었다"
    assert unknown_codes(["ZZZZZZ"]) == ["ZZZZZZ"]


# ── 2. ★막지 않는다 — 동작 불변★ ──────────────────────────────────────
def test_an_unknown_code_does_not_stop_the_analysis(client):
    """이 짝이 없으면 "거부하는" 구현으로 바뀌어도 통과한다."""
    b = _analyze(client, ["005930", "ZZZZZZ"])
    assert b["error"] is False
    w = (b.get("weights") or {}).get("optimized") or {}
    assert "ZZZZZZ" in w, "모르는 종목이 분석에서 빠졌다 — 막는 구현이 됐다"
    assert sum(w.values()) == pytest.approx(100.0, abs=0.5)


def test_a_foreign_listing_is_reported_but_still_researched(client):
    """★정당한 경우의 짝★ `SPY` 는 마스터에 없지만 연구는 계속돼야 한다."""
    b = _analyze(client, ["005930", "SPY"])
    assert "SPY" in b["unknown_tickers"]["codes"]
    assert b["error"] is False
    assert "SPY" in ((b.get("weights") or {}).get("optimized") or {})


# ── 3. ★합성이라는 것을 말한다★ ───────────────────────────────────────
def test_it_says_the_history_is_synthetic_in_mock_mode(client):
    b = _analyze(client, ["005930", "ZZZZZZ"])
    u = b["unknown_tickers"]
    assert u["synthetic_data"] is True
    assert "합성" in u["note"], u["note"]


def test_the_synthetic_flag_follows_the_mock_gate(monkeypatch, client):
    """★새 판정 기준을 만들지 않는다★ `mock_allowed()` 가 유일한 기준이다."""
    import src.api.allocation_routes as ar
    monkeypatch.setattr("src.data.mock_gate.mock_allowed", lambda: False)
    u = ar._unknown_tickers(["ZZZZZZ"])
    assert u["synthetic_data"] is False
    assert "합성" not in u["note"], u["note"]


# ── 4. ★`excluded` 와 섞지 않는다★ ────────────────────────────────────
def test_an_unknown_code_with_data_is_not_in_excluded(client):
    """두 칸이 **다른 사실**을 말한다 — 하나로 합치면 그 구분이 사라진다.

      · `excluded`        — 데이터가 없어 분석에서 빠졌다
      · `unknown_tickers` — 데이터는 있는데 그 종목이 실재하는지 모른다
    """
    b = _analyze(client, ["005930", "ZZZZZZ"])
    assert "ZZZZZZ" not in (b.get("excluded") or [])
    assert "ZZZZZZ" in b["unknown_tickers"]["codes"]


# ── 5. ★실행 게이트와의 연결★ ────────────────────────────────────────
def test_the_execution_gate_still_refuses_such_a_code():
    """연구는 열려 있고 주문은 막힌다 — 직전 슬라이스가 그 절반을 맡는다."""
    from src.data.target_versions import STATUS_RESEARCH_ONLY, compile_target
    tv = compile_target({"005930": 40.0, "ZZZZZZ": 60.0}, None)
    assert tv["status"] == STATUS_RESEARCH_ONLY
    assert "ZZZZZZ" in (tv["status_reason"] or "")


# ── 6. rebalance-decision 도 같은 사실을 말한다 ────────────────────────
def test_rebalance_decision_reports_it_too(client):
    r = client.post("/api/v1/allocation/rebalance-decision", json={
        "tickers": ["005930", "ZZZZZZ", "035420"],
        "holdings": {"005930": 50.0, "ZZZZZZ": 30.0, "035420": 20.0},
        "portfolio_value": 1e8, "model": "mvo"})
    assert r.status_code == 200, r.text
    assert r.json()["unknown_tickers"]["codes"] == ["ZZZZZZ"]
