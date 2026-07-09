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


# ── financial_deep (합성 financials_history로 수식 검증) ──

def _install_history(monkeypatch, rows):
    import src.engine.company_analytics as camod
    monkeypatch.setattr(camod, "_annual_rows", lambda code: rows)


def _year(y, rev, op, ni, ta, tl, te, ca_, cl, ocf, capex, shares, dps):
    return {"year": y, "reprt": "11011", "revenue": rev, "operating_profit": op,
            "net_income": ni, "total_assets": ta, "total_liabilities": tl,
            "total_equity": te, "current_assets": ca_, "current_liabilities": cl,
            "operating_cf": ocf, "capex": capex, "shares_outstanding": shares,
            "dps": dps, "gross_profit": rev * 0.3}


def test_dupont_product_equals_roe(monkeypatch):
    rows = [_year(2022 + i, 1000e8, 100e8, 80e8, 2000e8, 800e8, 1200e8,
                  700e8, 400e8, 90e8, 30e8, 5000, 100) for i in range(3)]
    _install_history(monkeypatch, rows)
    out = ca.financial_deep("900100")
    d = out["dupont"]
    for i in range(len(d["years"])):
        prod = d["net_margin"][i] / 100 * d["asset_turnover"][i] * d["leverage"][i]
        assert abs(prod * 100 - d["roe"][i]) < 0.5, "듀폰 곱 ≠ ROE"


def test_nwc_and_waterfall_identity(monkeypatch):
    rows = [_year(2023, 1000e8, 100e8, 80e8, 2000e8, 800e8, 1200e8, 700e8, 400e8,
                  90e8, 30e8, 5000, 100),
            _year(2024, 1100e8, 120e8, 95e8, 2100e8, 850e8, 1250e8, 720e8, 410e8,
                  110e8, 35e8, 5000, 120)]
    _install_history(monkeypatch, rows)
    out = ca.financial_deep("900101")
    assert out["nwc"]["nwc"][-1] == pytest.approx((720e8 - 410e8) / 1e8)
    w = out["waterfall"]
    i = len(w["years"]) - 1
    # OCF - CapEx - 배당 - 부채상환(감소분) = 잔여 (항등식)
    assert w["residual"][i] == pytest.approx(
        w["ocf"][i] - w["capex"][i] - w["dividends"][i] - max(0.0, -(w["debt_delta"][i] or 0)),
        abs=0.5)


def test_qoe_red_flag_fires_when_ocf_below_ni(monkeypatch):
    rows = [_year(2021 + i, 1000e8, 100e8, 90e8, 2000e8, 800e8, 1200e8, 700e8, 400e8,
                  40e8, 30e8, 5000, 100) for i in range(4)]   # OCF 40 < NI 90 매년
    _install_history(monkeypatch, rows)
    out = ca.financial_deep("900102")
    assert any(f["rule"] == "R1" for f in out["qoe"]["red_flags"])


def test_qoe_no_flag_when_healthy(monkeypatch):
    rows = [_year(2021 + i, 1000e8, 100e8, 80e8, 2000e8, 800e8, 1200e8, 700e8, 400e8,
                  120e8, 30e8, 5000, 100) for i in range(4)]  # OCF 120 > NI 80
    _install_history(monkeypatch, rows)
    out = ca.financial_deep("900103")
    assert not any(f["rule"] == "R1" for f in out["qoe"]["red_flags"])


def test_financial_deep_unavailable_without_history(monkeypatch):
    _install_history(monkeypatch, [])
    out = ca.financial_deep("900104")
    assert out["available"] is False and "미적재" in out["note"]


# ── risk_deep ──

def test_altman_contributions_sum_to_z():
    out = ca.risk_deep(CODE, PRICE)
    alt = out["altman"]
    s = sum(c["contribution"] for c in alt["components"])
    assert abs(s - alt["z"]) < 0.05


def test_beneish_labels_and_score(monkeypatch):
    rows = [_year(2023, 1000e8, 100e8, 80e8, 2000e8, 800e8, 1200e8, 700e8, 400e8,
                  90e8, 30e8, 5000, 100),
            _year(2024, 1300e8, 120e8, 95e8, 2100e8, 900e8, 1200e8, 720e8, 410e8,
                  60e8, 35e8, 5000, 120)]
    _install_history(monkeypatch, rows)
    out = ca.risk_deep("900200", PRICE)
    b = out["beneish"]
    assert b["available"] is True
    basis = {i["id"]: i["basis"] for i in b["indices"]}
    assert basis["sgi"] == "real" and basis["dsri"] == "neutral" and basis["aqi"] == "approx"
    sgi = next(i for i in b["indices"] if i["id"] == "sgi")
    assert sgi["value"] == pytest.approx(1.3, abs=0.01)


def test_beneish_unavailable_without_prev_year(monkeypatch):
    rows = [_year(2024, 1000e8, 100e8, 80e8, 2000e8, 800e8, 1200e8, 700e8, 400e8,
                  90e8, 30e8, 5000, 100)]
    _install_history(monkeypatch, rows)
    out = ca.risk_deep("900201", PRICE)
    assert out["beneish"]["available"] is False


def test_rate_stress_direction():
    out = ca.risk_deep(CODE, PRICE)
    rows = out["rate_stress"]["rows"]
    ics = [r["interest_coverage"] for r in rows if r["interest_coverage"] is not None]
    assert ics == sorted(ics, reverse=True), "금리 충격이 커질수록 커버리지는 하락해야"
