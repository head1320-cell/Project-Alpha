"""비중의 **단위** — `dict[str, float]` 는 자기 단위를 말하지 않는다.

★착수 0단계 실측 — 같은 지시가 100배 다른 주문을 낸다★

    build_plan(현재 0, 목표 {"005930": 60.0, "000660": 40.0}, PV=10억)
        → 매수 999,970,000원 · 회전율 100.0%
    build_plan(현재 0, 목표 {"005930":  0.60, "000660":  0.40}, PV=10억)
        → 매수   9,950,000원 · 회전율   1.0%      ← 경고 없음

저장소 안에 서로 다른 두 관례가 공존한다:
  · 돈을 세는 계층(`execution_plan`·`rebalance_policy`·`instrument_selector`)은
    `/100.0` 으로 **퍼센트를 가정**한다.
  · 비율을 세는 계층(`factor_exposure`·`factor_risk`·`attribution`…)은 gross 로
    정규화해 **단위와 무관**하다.

그래서 한 응답 안에서 절반은 옳고 절반은 100배 틀릴 수 있다 — 실측으로
`rebalance-decision` 의 `max_gap_pct` 가 48.50 vs 68.30 으로 갈렸고 팩터 노출은
같았다.

★추측하지 않는다★ 합이 1 근처면 "분수로 준 100%" 인지 "퍼센트로 준 1%(현금 99%)"
인지 알 수 없다 — **둘 다 정당한 포트폴리오다.** 조용히 고르는 것이 이 결함을 만든
행동이므로, 모호하면 사유를 돌려주고 호출자가 선언하게 한다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.engine.portfolio_weights import (  # noqa: E402
    FRACTION,
    PERCENT,
    as_percent,
    unit_reason,
)

_PCT = {"005930": 60.0, "000660": 40.0}
_FRAC = {"005930": 0.60, "000660": 0.40}


# ── 1. ★모호한 것을 모호하다고 말한다★ ─────────────────────────────────
def test_a_book_summing_to_one_is_refused_without_a_declared_unit():
    r = unit_reason(_FRAC)
    assert r, "합이 1.0 인데 단위를 묻지 않았다"
    assert "100배" in r, r
    assert PERCENT in r and FRACTION in r, "무엇을 지정하면 되는지 말하지 않았다"


def test_declaring_the_unit_resolves_it():
    """★짝★ 물어보기만 하고 답을 받을 길이 없으면 막다른 길이다."""
    assert unit_reason(_FRAC, PERCENT) is None
    assert unit_reason(_FRAC, FRACTION) is None


def test_an_unambiguous_percent_book_passes_untouched():
    """★짝 — 기존 호출자를 막지 않는다★ 합 100 은 물을 것이 없다."""
    assert unit_reason(_PCT) is None


@pytest.mark.parametrize("g", [0.4, 0.05, 0.001])
def test_a_clearly_fractional_book_is_not_ambiguous(g):
    """합이 충분히 작으면 퍼센트로 읽어도 분수로 읽어도 '소액' 이라 갈리지 않는다."""
    assert unit_reason({"A": g}) is None


def test_a_bad_declaration_is_named():
    r = unit_reason(_PCT, "퍼센트")
    assert r and "weight_unit" in r


# ── 2. ★변환이 실제로 100배를 가른다★ ─────────────────────────────────
def test_as_percent_converts_a_declared_fraction():
    out = as_percent(_FRAC, FRACTION)
    assert out["005930"] == pytest.approx(60.0)
    assert out["000660"] == pytest.approx(40.0)


def test_as_percent_leaves_a_declared_percent_alone():
    """★짝★ 항상 100배 하면 위 테스트도 통과한다 — 양방향으로 건다."""
    out = as_percent(_PCT, PERCENT)
    assert out["005930"] == pytest.approx(60.0)
    assert out["000660"] == pytest.approx(40.0)


def test_the_two_readings_differ_by_a_hundred():
    """이 슬라이스가 존재하는 이유를 수치로 고정한다."""
    a = as_percent(_FRAC, FRACTION)["005930"]
    b = as_percent(_FRAC, PERCENT)["005930"]
    assert a == pytest.approx(b * 100.0)


# ── 3. ★돈이 되는 경계에서 막힌다★ ────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


_T = ["005930", "000660", "035420"]
_HOLD_PCT = {"005930": 50.0, "000660": 30.0, "035420": 20.0}
_HOLD_FRAC = {"005930": 0.50, "000660": 0.30, "035420": 0.20}


def test_rebalance_decision_refuses_an_ambiguous_book(client):
    r = client.post("/api/v1/allocation/rebalance-decision", json={
        "tickers": _T, "holdings": _HOLD_FRAC, "portfolio_value": 1e8})
    assert r.status_code == 422, r.text
    assert "100배" in r.text


def test_rebalance_decision_accepts_it_once_declared(client):
    """★짝★ 거부가 막다른 길이 되지 않는다."""
    r = client.post("/api/v1/allocation/rebalance-decision", json={
        "tickers": _T, "holdings": _HOLD_FRAC, "portfolio_value": 1e8,
        "weight_unit": "fraction"})
    assert r.status_code == 200, r.text


def test_rebalance_decision_is_unchanged_for_percent(client):
    """★짝 — 기존 동작 불변★"""
    r = client.post("/api/v1/allocation/rebalance-decision", json={
        "tickers": _T, "holdings": _HOLD_PCT, "portfolio_value": 1e8})
    assert r.status_code == 200, r.text
    assert r.json().get("decision") in ("trade", "hold", "undetermined")


def test_execution_plan_refuses_an_ambiguous_book(client):
    """★가장 중요한 경계★ 여기서 통과하면 100배 작은 **실제 주문**이 나간다."""
    r = client.post("/api/v1/allocation/execution-plan", json={
        "current_weights": {"005930": 0.0},
        "target_weights": {"005930": 0.60, "000660": 0.40},
        "portfolio_value": 1e9})
    assert r.status_code == 422, r.text
    assert "100배" in r.text


def test_execution_plan_is_unchanged_for_percent(client):
    """★짝★ 퍼센트 목표는 그대로 계획이 나온다."""
    r = client.post("/api/v1/allocation/execution-plan", json={
        "current_weights": {"005930": 0.0},
        "target_weights": {"005930": 60.0, "000660": 40.0},
        "portfolio_value": 1e9})
    assert r.status_code == 200, r.text
    assert r.json().get("blocked") is not True


def test_saving_a_plan_is_gated_too(client):
    """★미리보기만 막고 저장을 열어 두면 게이트가 아니다★

    같은 파일의 기존 주석이 이 원칙을 이미 적어 뒀다 — `_compute` 를 공유하므로
    단위 게이트도 두 경로에 똑같이 걸려야 한다.
    """
    r = client.post("/api/v1/allocation/execution-plan/save", json={
        "name": "단위 모호", "current_weights": {"005930": 0.0},
        "target_weights": {"005930": 0.60, "000660": 0.40},
        "portfolio_value": 1e9})
    assert r.status_code == 422, r.text
    assert "100배" in r.text


def test_saving_a_percent_plan_still_works(client):
    """★짝★ 퍼센트 경로는 그대로 저장 시도까지 간다(DB 미가용이면 정직 보고)."""
    r = client.post("/api/v1/allocation/execution-plan/save", json={
        "name": "퍼센트", "current_weights": {"005930": 0.0},
        "target_weights": {"005930": 60.0, "000660": 40.0},
        "portfolio_value": 1e9})
    assert r.status_code == 200, r.text
    b = r.json()
    assert "saved" in b and b.get("blocked") is not True
