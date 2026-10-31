"""국내 시나리오팩 검증 (Full Expansion P3-b)

핵심 주장:
  카탈로그  — 7종 시나리오, 각기 라벨·설명·출처
  충격      — 팩터 노출 × 계수 선형 결합, 시장 기본충격 포함, severity 선형 배율
  귀속      — 팩터별 기여 합 + 시장충격 = 포트폴리오 충격 (분해 항등)
  구조      — 취약종목·팩터귀속·VaR/CVaR/MDD 프록시·실행가능성·헤지·가정 전부 반환
  슬리브    — sleeves 지정 시 슬리브별 취약 귀속
  방향성    — 반도체 시나리오는 반도체 종목을 더 때림(노출 부호 정합)
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402

import src.engine.kr_scenario_pack as ksp  # noqa: E402
from src.engine.kr_scenario_pack import SCENARIOS, catalog, run_scenario  # noqa: E402

CODES = ["005930", "000660", "035420", "051910", "105560", "005380"]
W = {c: 100.0 / len(CODES) for c in CODES}


#: 최초 지시서의 7종. Phase 9 가 4종을 더했지만 ★이 일곱은 하나도 사라지지 않는다★ —
#: 그것이 이 테스트가 지키는 불변식이고, 개수는 그 부산물이다(CLAUDE.md: 개수를 세지 말 것).
_ORIGINAL_SEVEN = {
    "shortsell_regulation", "leverage_unwind", "krw_sharp_move", "semi_selloff",
    "valueup_collapse", "earnings_dispersion", "retail_flow_reversal",
}
#: Phase 9 가 스펙 §5 의 빈 패밀리를 메우며 추가한 4종.
_PHASE9_ADDED = {
    "vol_shock_liquidity_vacuum", "credit_conditions_tightening",
    "corr_convergence_hedge_failure", "stagflation_regime",
}


def test_catalog_keeps_the_original_seven_and_adds_the_phase9_four():
    cat = catalog()
    assert all({"id", "label", "description", "source"} <= set(s) for s in cat)
    ids = {s["id"] for s in cat}
    assert _ORIGINAL_SEVEN <= ids, f"원래 7종 중 사라진 것: {_ORIGINAL_SEVEN - ids}"
    assert _PHASE9_ADDED <= ids, f"Phase 9 추가분 중 없는 것: {_PHASE9_ADDED - ids}"
    assert ids == _ORIGINAL_SEVEN | _PHASE9_ADDED, f"예상 밖의 시나리오: {ids - _ORIGINAL_SEVEN - _PHASE9_ADDED}"


def _fake_exposures(monkeypatch, semi_codes=("005930", "000660")):
    """결정론적 팩터 노출 주입 — 반도체 더미 + 임의 z."""
    def loader(codes):
        rng = np.random.default_rng(3)
        exp = {k: rng.normal(0, 1, len(codes)) for k in
               ("mkt_beta", "size", "momentum", "value", "leverage", "illiquidity")}
        exp["semi"] = np.array([1.0 if c in semi_codes else 0.0 for c in codes])
        names = [f"종목{c}" for c in codes]
        return exp, names, ["테스트 노출"]
    monkeypatch.setattr(ksp, "_load_exposures", loader)


def test_run_scenario_structure_and_attribution(monkeypatch):
    _fake_exposures(monkeypatch)
    r = run_scenario(CODES, W, "semi_selloff", severity=1.0)
    assert r["error"] is False
    # 필수 구조 (지시서)
    for key in ("portfolio_shock_pct", "factor_attribution", "rows", "most_vulnerable",
                "assumptions", "risk_proxy", "execution_feasibility", "hedge_note", "notes"):
        assert key in r
    assert set(r["risk_proxy"]) == {"var95_pct", "cvar95_pct", "mdd_proxy_pct"}
    assert {"correlation_rise", "volatility_rise", "liquidity_deterioration",
            "stressed_vol_pct"} <= set(r["assumptions"])
    # 팩터별 기여 합 + (시장은 factor_attribution에 market으로 포함) = 포트폴리오 충격
    attr_sum = sum(f["contribution_pct"] for f in r["factor_attribution"])
    assert abs(attr_sum - r["portfolio_shock_pct"]) < 0.05        # 분해 항등


def test_severity_scales_linearly(monkeypatch):
    _fake_exposures(monkeypatch)
    r1 = run_scenario(CODES, W, "leverage_unwind", severity=1.0)
    r2 = run_scenario(CODES, W, "leverage_unwind", severity=2.0)
    assert abs(r2["portfolio_shock_pct"] - 2 * r1["portfolio_shock_pct"]) < 0.1


def test_semi_scenario_hits_semi_names(monkeypatch):
    _fake_exposures(monkeypatch, semi_codes=("005930", "000660"))
    r = run_scenario(CODES, W, "semi_selloff", severity=1.0)
    shock = {row["stock_code"]: row["shock_pct"] for row in r["rows"]}
    semi_avg = (shock["005930"] + shock["000660"]) / 2
    non_semi = np.mean([shock[c] for c in CODES if c not in ("005930", "000660")])
    assert semi_avg < non_semi          # 반도체가 더 크게 하락(음수 더 큼)
    # 팩터 귀속에서 반도체가 가장 큰 음의 기여
    semi_attr = next(f for f in r["factor_attribution"] if f["factor"] == "semi")
    assert semi_attr["contribution_pct"] < 0


def test_sleeve_attribution(monkeypatch):
    _fake_exposures(monkeypatch)
    sleeves = {c: ("반도체" if c in ("005930", "000660") else "기타") for c in CODES}
    r = run_scenario(CODES, W, "semi_selloff", severity=1.0, sleeves=sleeves)
    assert r["sleeve_attribution"] is not None
    slv = {s["sleeve"]: s["contribution_pct"] for s in r["sleeve_attribution"]}
    assert "반도체" in slv and "기타" in slv
    assert slv["반도체"] < slv["기타"]   # 반도체 슬리브가 더 취약


def test_unknown_scenario_and_empty():
    assert run_scenario(CODES, W, "없는시나리오")["error"] is True
    assert run_scenario(CODES, {}, "semi_selloff")["error"] is True


def test_missing_exposure_honest(monkeypatch):
    """노출 로더가 전부 결측(0) → 시장충격만 남고, notes에 결측 안내."""
    def loader(codes):
        exp = {k: np.zeros(len(codes)) for k in
               ("mkt_beta", "size", "momentum", "value", "leverage", "illiquidity", "semi")}
        return exp, [f"종목{c}" for c in codes], ["노출 결측 팩터(0 기여): 시장 베타 — 실데이터 적재 시 채워짐(정직 결측)."]
    monkeypatch.setattr(ksp, "_load_exposures", loader)
    r = run_scenario(CODES, W, "semi_selloff", severity=1.0)
    assert abs(r["portfolio_shock_pct"] - r["market_shock_pct"]) < 0.05   # 팩터 기여 0
    assert any("결측" in n for n in r["notes"])


def test_all_seven_run(monkeypatch):
    _fake_exposures(monkeypatch)
    for sid in SCENARIOS:
        r = run_scenario(CODES, W, sid, severity=1.5)
        assert r["error"] is False and "portfolio_shock_pct" in r
