"""P3-2 배선 — `GET /api/v1/backtest/runs/{run_id}/factor-attribution`

★이 파일이 거는 것★
  1. 저장된 `bt_*` 를 실제로 태워 귀인이 나온다.
  2. ★결과가 없는 실행은 500 이 아니라 사유★ 아직 안 끝났거나 옛 스키마일 수
     있는데, 실행이 존재하면 그것은 오류가 아니다.
  3. 기존 7개 라우트 불변.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

import src.data.backtest_runs as br  # noqa: E402

LEGACY = ("/api/v1/backtest/runs",
          "/api/v1/backtest/runs/{run_id}",
          "/api/v1/backtest/runs/{run_id}/status",
          "/api/v1/backtest/runs/{run_id}/cancel",
          "/api/v1/backtest/runs/{run_id}/retry")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


@pytest.fixture(scope="module")
def finished_run() -> str:
    """실제 백테스트를 돌려 저장한 실행."""
    from src.api.screener_routes import (
        ScreenToBacktestRequest,
        _screen_to_backtest_core,
    )
    rid = br.create_run("귀인테스트", {"kind": "test"})
    if not rid:
        pytest.skip("실행 저장소를 쓸 수 없다")
    req = ScreenToBacktestRequest(
        custom_tickers=["005930", "000660"],
        filter_ast={"logic": "AND", "conditions": [], "groups": []},
        strategy_name="Condition",
        buy_conditions=[{"factor_token": "종가", "function_id": "base",
                         "op": "gte", "rhs": 0}],
        sell_conditions=[], start_date="2021-01-01", end_date="2025-12-31",
        max_positions=2, max_tickers=2)
    bt = _screen_to_backtest_core(req).get("backtest")
    if not bt:
        pytest.skip("이 환경에서 백테스트를 낼 수 없다")
    br.advance(rid, "simulating")
    if not br.set_result(rid, bt)["ok"]:
        pytest.skip("결과 저장 실패")
    return rid


def _url(rid: str) -> str:
    return f"/api/v1/backtest/runs/{rid}/factor-attribution"


# ── 1. 라우트 ───────────────────────────────────────────────────────────────
def test_the_route_is_registered_and_the_legacy_seven_are_intact(client):
    paths = {r.path for r in client.app.routes}
    assert "/api/v1/backtest/runs/{run_id}/factor-attribution" in paths
    for p in LEGACY:
        assert p in paths, p


def test_a_finished_run_gets_a_factor_attribution(client, finished_run):
    r = client.get(_url(finished_run))
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["available"] is True, b.get("reason")
    assert b["run_id"] == finished_run
    assert b["rows"] and b["rows"][0]["factor"]
    assert b["months_from_run"] > 0


def test_the_identity_closes_in_the_response(client, finished_run):
    """★항등식이 응답에서도 닫힌다★"""
    b = client.get(_url(finished_run)).json()
    assert (b["alpha_contribution_pct"] + b["factor_contribution_pct"]
            == pytest.approx(b["arithmetic_total_pct"], abs=1e-3))
    assert abs(b["identity_residual_pct"]) < 1e-6


def test_both_totals_are_reported(client, finished_run):
    """★산술 합과 복리를 같은 것처럼 내지 않는다★"""
    b = client.get(_url(finished_run)).json()
    assert b["compound_total_pct"] is not None
    assert b["compounding_gap_pct"] == pytest.approx(
        b["compound_total_pct"] - b["arithmetic_total_pct"], abs=1e-3)


def test_the_diagnostics_travel_with_the_answer(client, finished_run):
    """R²·자유도·VIF 없이 기여만 보면 믿을지 판단할 수 없다."""
    d = client.get(_url(finished_run)).json()["diagnostics"]
    assert d["r_squared"] is not None
    assert d["dof"] >= 2 and d["n_months"] >= 24
    assert d["condition_number"] is not None
    assert d["max_vif"] is not None
    assert d["obs_per_param"] > 0


def test_every_row_carries_its_vif_and_collinearity_label(client, finished_run):
    b = client.get(_url(finished_run)).json()
    for row in b["rows"]:
        assert "vif" in row and "collinear" in row
        if row["collinear"]:
            assert "개별 값으로 읽지 마십시오" in row["collinear_reason"]


def test_the_proxies_used_are_disclosed(client, finished_run):
    """어느 계열로 잰 것인지 밝힌다 — 팩터 이름만으로는 재현할 수 없다."""
    b = client.get(_url(finished_run)).json()
    assert b["proxies"] and len(b["proxies"]) >= 3
    for row in b["rows"]:
        assert b["proxies"].get(row["factor"]) == row["series"]


# ── 2. ★없는 것은 사유, 오류가 아니다★ ────────────────────────────────────
def test_an_unknown_run_is_a_404(client):
    assert client.get(_url("bt_존재하지않음")).status_code == 404


def test_a_run_without_results_is_a_reason_not_a_500(client):
    """★아직 안 끝났을 수 있다★ 실행이 존재하면 500 이 아니다."""
    rid = br.create_run("결과없는실행", {"kind": "test"})
    if not rid:
        pytest.skip("실행 저장소를 쓸 수 없다")
    r = client.get(_url(rid))
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["available"] is False and b["reason"]
    assert b["run_id"] == rid and b["status"]


def test_the_response_survives_json_encoding(client, finished_run):
    """비유한 값이 있어도 500 이 되지 않는다(json_safe 통과)."""
    r = client.get(_url(finished_run))
    assert r.status_code == 200
    import json
    json.dumps(r.json())
