"""company_analytics — 기업분석 심화 순수 함수 (스펙 2026-07-09).

mock 모드(KIS_USE_MOCK=1)의 결정론 데이터로 수식·구조·정직성 계약을 검증.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.engine import company_analytics as ca  # noqa: E402

CODE = "005930"
PRICE = 70000.0


def test_resolve_default_params_shape():
    p = ca.resolve_default_params(CODE)
    assert set(p) >= {"rf", "rf_source", "beta", "beta_source", "erp", "g", "years"}
    assert 0.0 < p["rf"] < 0.15 and 0.1 <= p["beta"] <= 3.0


def test_sensitivity_grid_monotonic():
    out = ca.valuation_sandbox(CODE, PRICE, {})
    sens = out["sensitivity"]
    assert len(sens["ke_axis"]) == 5 and len(sens["g_axis"]) == 5
    grid = sens["grid"]
    # ke↑(행) → 가치↓, g↑(열) → 가치↑ (null 칸 제외 비교)
    mid = 2
    col = [grid[i][mid] for i in range(5) if grid[i][mid] is not None]
    assert col == sorted(col, reverse=True), "ke 상승 시 가치는 단조 감소해야"
    row = [grid[mid][j] for j in range(5) if grid[mid][j] is not None]
    assert row == sorted(row), "g 상승 시 가치는 단조 증가해야"


def test_sensitivity_tv_divergence_guard():
    # g가 ke에 근접(0.5%p 미만)하면 해당 칸은 None (TV 발산 방지)
    out = ca.valuation_sandbox(CODE, PRICE, {"g": 0.05, "beta": 0.2, "erp": 0.01, "rf": 0.045})
    grid = out["sensitivity"]["grid"]
    assert any(c is None for row in grid for c in row)


def test_sandbox_assumptions_have_sources():
    out = ca.valuation_sandbox(CODE, PRICE, {})
    keys = {a["key"] for a in out["assumptions"]}
    assert {"rf", "beta", "erp", "g", "years"} <= keys
    assert all(a.get("source") for a in out["assumptions"])


def test_football_field_bands():
    out = ca.football_field(CODE, PRICE)
    assert out["current_price"] == PRICE
    ids = {b["id"] for b in out["bands"]}
    assert {"dcf", "rim", "ddm", "w52"} <= ids
    for b in out["bands"]:
        if b.get("available", True):
            assert b["lo"] <= b["hi"], f"{b['id']} 밴드 lo>hi"


def test_comps_table_has_median_and_implied():
    out = ca.comps_table(CODE)
    assert out["rows"], "피어 행이 비어있음"
    assert out["rows"][0]["code"] == CODE  # 첫 행 = 자사
    assert "median_row" in out and "implied" in out
    imp = out["implied"]
    assert set(imp) >= {"per_based", "pbr_based", "ev_ebitda_based"}
