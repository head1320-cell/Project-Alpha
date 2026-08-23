"""리밸런싱 정책 배선 — `/allocation/rebalance-decision` (Brief §10 · 감사 §3.1)

★이 파일이 거는 것★
  1. 죽어 있던 `portfolio_rebalancer` 가 **실제 요청 경로에서** 돈다.
  2. 판단이 `/analyze` 와 **같은 μ/Σ 경로**를 탄다 — 두 화면이 갈리면 안 된다.
  3. ★조용한 폴백 금지★ 조건부를 못 썼으면 응답이 그 사실을 말한다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.engine.rebalance_policy import (  # noqa: E402
    DECISION_HOLD,
    DECISION_TRADE,
    DECISION_UNDETERMINED,
)

URL = "/api/v1/allocation/rebalance-decision"
TICKERS = ["005930", "000660", "035420"]
HOLDINGS = {"005930": 50.0, "000660": 30.0, "035420": 20.0}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


def _body(**kw) -> dict:
    base = {"tickers": TICKERS, "holdings": HOLDINGS,
            "portfolio_value": 100_000_000, "model": "mvo", "horizon_days": 63}
    base.update(kw)
    return base


def _post(client, **kw) -> dict:
    r = client.post(URL, json=_body(**kw))
    assert r.status_code == 200, r.text
    return r.json()


# ── 1. 라우트 ───────────────────────────────────────────────────────────────
def test_the_route_is_registered_and_the_neighbours_are_untouched(client):
    paths = {r.path for r in client.app.routes}
    assert URL in paths
    for p in ("/api/v1/allocation/analyze", "/api/v1/allocation/target-versions"):
        assert p in paths, p


def test_a_real_decision_comes_back(client):
    b = _post(client)
    assert b["decision"] in (DECISION_TRADE, DECISION_HOLD, DECISION_UNDETERMINED)
    assert b["reason"]
    assert b["cost"]["available"] is True
    assert b["benefit"]["available"] is True, b["benefit"].get("reason")


def test_the_decision_names_both_sides_of_the_comparison(client):
    """★편익 대 비용이 근거다★ 숫자 없이 '거래하세요' 라고 하지 않는다."""
    b = _post(client)
    assert b["cost"]["cost_pct"] is not None
    assert b["benefit"]["gain_pct"] is not None
    assert b["threshold_pct"] is not None
    assert "%" in b["reason"]


# ── 2. ★죽어 있던 모듈이 실제 경로에서 돈다★ ──────────────────────────────
def test_the_trigger_engine_actually_runs_in_the_request_path(client):
    b = _post(client)
    trig = b["triggers"]
    assert trig is not None and trig["available"] is True
    assert "triggers" in trig and "drift_pct" in trig
    assert "거래 근거가 아닙니다" in trig["note"]


def test_a_trigger_does_not_by_itself_decide(client):
    """트리거가 울려도 결론은 편익 대 비용이 낸다."""
    b = _post(client)
    assert b["triggers"]["triggers"], "drift 는 울린다"
    # 결론의 사유는 트리거 문구가 아니라 비용/편익 문구여야 한다.
    assert "Drift" not in b["reason"]


# ── 3. 목표 비중 ────────────────────────────────────────────────────────────
def test_without_targets_the_optimizer_supplies_them(client):
    b = _post(client)
    assert b["target_source"] == "optimize:mvo"
    assert set(b["target_weights"]) == set(TICKERS)
    assert sum(b["target_weights"].values()) == pytest.approx(100.0, abs=0.5)


def test_explicit_targets_are_used_as_given(client):
    tgt = {"005930": 33.0, "000660": 33.0, "035420": 34.0}
    b = _post(client, target_weights=tgt)
    assert b["target_source"] == "request"
    assert b["target_weights"] == tgt


# ── 4. ★밴드는 자산마다★ ───────────────────────────────────────────────────
def test_bands_come_back_per_asset_with_ranges(client):
    """★Brief §9 — 점 하나가 아니라 구간★"""
    by = _post(client)["band"]["by_asset"]
    assert set(by) == set(TICKERS)
    for code, band in by.items():
        assert band["low_pct"] <= band["inputs"]["target_weight_pct"] <= band["high_pct"]
        assert band["half_width_pct"] > 0


def test_the_bands_are_not_all_the_same_number(client):
    """전부 같으면 이름만 동적인 고정 밴드다(σ² 형태에서 실제로 그랬다)."""
    by = _post(client)["band"]["by_asset"]
    widths = {round(b["half_width_pct"], 4) for b in by.values()}
    clamped = {b["clamped"] for b in by.values()}
    assert len(widths) > 1 or clamped == {True}, (widths, clamped)


# ── 5. ★조용한 폴백 금지★ ─────────────────────────────────────────────────
def test_conditional_off_makes_no_conditional_claim(client):
    assert _post(client)["conditional"] is None


def test_conditional_on_reports_whether_it_was_actually_used(client):
    b = _post(client, conditional=True)
    c = b["conditional"]
    assert c is not None
    # 썼든 못 썼든 **말한다** — 숫자만 보고 국면이 반영됐다고 믿게 두지 않는다.
    assert "sigma_applied" in c or "available" in c


# ── 6. 가정이 드러난다 ─────────────────────────────────────────────────────
def test_the_horizon_assumption_is_visible_and_changes_the_answer(client):
    """★연율과 일회성을 그냥 비교하지 않는다★"""
    short = _post(client, horizon_days=1)
    long = _post(client, horizon_days=252)
    assert short["benefit"]["horizon_days"] == 1
    assert long["benefit"]["horizon_days"] == 252
    assert long["benefit"]["gain_pct"] > short["benefit"]["gain_pct"]
    assert "연율" in short["benefit"]["note"]


def test_risk_aversion_comes_from_the_same_knob_as_analyze(client):
    """★두 화면이 다른 λ 를 쓰면 같은 포트폴리오가 다른 판단을 받는다★"""
    b = _post(client, delta=7.5)
    assert b["benefit"]["risk_aversion"] == 7.5


def test_hysteresis_is_reported_and_applied(client):
    b = _post(client, hysteresis_mult=3.0)
    assert b["hysteresis_mult"] == 3.0
    assert b["threshold_pct"] == pytest.approx(b["cost"]["cost_pct"] * 4.0, rel=1e-3)


def test_low_confidence_produces_a_partial_move(client):
    b = _post(client, confidence=0.25)
    g = b["gradual"]
    assert g["alpha"] == 0.25
    for code, w in g["weights"].items():
        cur, tgt = HOLDINGS.get(code, 0.0), b["target_weights"].get(code, 0.0)
        assert w == pytest.approx(cur + 0.25 * (tgt - cur), abs=1e-3)


# ── 7. 입력 검증 ───────────────────────────────────────────────────────────
def test_a_zero_portfolio_value_is_rejected(client):
    assert client.post(URL, json=_body(portfolio_value=0)).status_code == 422


def test_empty_holdings_are_rejected(client):
    assert client.post(URL, json=_body(holdings={})).status_code == 422


def test_a_single_asset_universe_is_a_reason_not_a_crash(client):
    r = client.post(URL, json=_body(tickers=["005930"], holdings={"005930": 100.0}))
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["available"] is False and b["decision"] == DECISION_UNDETERMINED
    assert b["reason"]
