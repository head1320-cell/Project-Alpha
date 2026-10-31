"""롱숏 분석 계층 — ★부호를 잃지 않는다★ (P3 후속)

P3 는 롱숏을 **연구·백테스트 전용**으로 열었다. 실행에서는 의도적으로 막힌다 —
`test_long_only_chain.py` 가 그 결정을 고정하고 있고 ★이 파일은 그 경계를 건드리지
않는다.★ 여기서 재는 것은 포트폴리오를 **되읽는** 쪽이다.

★착수 0단계 실측 (이 파일이 뒤집는 사실)★

    시장중립 페어: A +100%, B −100% (둘 다 growth 베타 1.0)
        참값 노출  = 0.0
        보고된 노출 = 1.0     coverage_pct: 100.0   missing: []

★★합만 재는 가드를 쓰지 않는다★★ 이 슬라이스는 주제가 정규화라 `Σ|w| == 1` 류의
동어반복에 특히 취약하다. 그래서 **비대칭 픽스처**로 항마다 가른다:

    A +150 / β=1.0,  B −50 / β=3.0     gross = 200
        올바름   (0.75·1.0) + (−0.25·3.0) = 0.75 − 0.75 =  0.00
        숏 폐기  (1.00·1.0)                              =  1.00
        부호 무시(0.75·1.0) + ( 0.25·3.0) = 0.75 + 0.75 =  1.50

    셋이 전부 다른 값이므로 어떤 실수도 통과하지 못한다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import time  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402

import src.engine.kr_scenario_pack as ksp  # noqa: E402
from src.engine.attribution import compute_attribution  # noqa: E402
from src.engine.factor_exposure import portfolio_factor_exposure  # noqa: E402
from src.engine.kr_scenario_pack import run_scenario  # noqa: E402


# ── 픽스처 ────────────────────────────────────────────────────────────────
def _betas(**per_asset: float) -> dict:
    """자산 → growth 베타 하나. 노출 산수를 손으로 검산할 수 있게 최소로 만든다."""
    return {
        "available": True, "factors": ["growth"],
        "proxies": {"growth": "PROXY"}, "transforms": {"growth": "pct"},
        "unresolved": {}, "sample": None, "causality": None,
        "assets": {c: {"available": True,
                       "betas": {"growth": {"available": True, "beta": b,
                                            "resolvable": True}}}
                   for c, b in per_asset.items()},
    }


def _expo(weights: dict, betas: dict) -> dict:
    return portfolio_factor_exposure(weights, betas)["by_factor"]["growth"]


# ═══════════════════════════════════════════════════════════════════════════
# 1. factor_exposure — ★결론이 뒤집히던 곳★
# ═══════════════════════════════════════════════════════════════════════════

def test_a_market_neutral_pair_has_zero_factor_exposure():
    """★0단계 실측을 뒤집는다★ 예전에는 1.0 이 나왔다."""
    g = _expo({"A": 100.0, "B": -100.0}, _betas(A=1.0, B=1.0))
    assert g["exposure"] == pytest.approx(0.0, abs=1e-9)


def test_the_asymmetric_book_separates_all_three_possible_answers():
    """★★항마다 핀한다★★ 0.00(옳음) · 1.00(숏 폐기) · 1.50(부호 무시)."""
    g = _expo({"A": 150.0, "B": -50.0}, _betas(A=1.0, B=3.0))
    assert g["exposure"] == pytest.approx(0.0, abs=1e-9)
    assert g["exposure"] != pytest.approx(1.0), "숏을 버린 답"
    assert g["exposure"] != pytest.approx(1.5), "부호를 무시한 답"


def test_a_130_30_reports_its_exposure_per_unit_gross():
    """gross 기준임을 값으로 고정한다 — (1.30·1 − 0.30·1)/1.60 = 0.625."""
    g = _expo({"A": 130.0, "B": -30.0}, _betas(A=1.0, B=1.0))
    assert g["exposure"] == pytest.approx(100.0 / 160.0)


def test_the_response_says_which_basis_that_number_is_on():
    """0.625 가 무슨 뜻인지 응답이 스스로 말해야 한다."""
    out = portfolio_factor_exposure({"A": 130.0, "B": -30.0}, _betas(A=1.0, B=1.0))
    b = out["basis"]
    assert b["gross_pct"] == pytest.approx(160.0)
    assert b["net_pct"] == pytest.approx(100.0)
    assert b["long_short"] is True
    assert b["normalized_by"] == "gross"


def test_coverage_counts_the_short_leg_too():
    """★예전에는 숏을 버리고도 coverage_pct: 100 이라고 했다★"""
    betas = _betas(A=1.0, B=1.0)
    betas["assets"]["B"]["available"] = False          # B 의 베타가 없다
    g = _expo({"A": 100.0, "B": -100.0}, betas)
    assert g["coverage_pct"] == pytest.approx(50.0), "숏 다리가 커버리지에서 빠졌다"
    assert "B" in g["missing"], "베타 없는 숏이 missing 에 없다"


def test_coverage_counts_a_covered_short_as_covered():
    """★짝 — 위 가드의 구멍을 막는다★

    변이 프로브(`covered += max(wf, 0)`)를 돌렸더니 위 테스트가 **green** 이었다.
    거기서는 커버된 다리가 롱이라 `abs(wf) == max(wf, 0)` 로 같은 값이 나온다.
    그래서 커버된 쪽을 **숏으로** 뒤집는다 — 이러면 부호를 잘라 내는 순간
    커버리지가 0 이 되어 `available: False` 로 무너진다.
    """
    betas = _betas(A=1.0, B=2.0)
    betas["assets"]["A"]["available"] = False          # 이번엔 **롱**의 베타가 없다
    out = portfolio_factor_exposure({"A": 100.0, "B": -100.0}, betas)
    g = out["by_factor"]["growth"]
    assert g["available"] is True, "커버된 숏이 '커버 안 됨' 으로 취급됐다"
    assert g["coverage_pct"] == pytest.approx(50.0)
    assert g["exposure"] == pytest.approx(-0.5 * 2.0)
    assert "A" in g["missing"]


def test_an_all_short_book_gets_an_answer_not_a_false_reason():
    """★거짓 사유★ 예전 `sum(max(w,0)) <= 0` 은 "비중 합이 0" 이라고 답했다."""
    out = portfolio_factor_exposure({"A": -60.0, "B": -40.0}, _betas(A=1.0, B=2.0))
    assert out["available"] is True, out.get("reason")
    assert out["by_factor"]["growth"]["exposure"] == pytest.approx(-1.4)


# ── ★짝 — 롱온리는 값까지 그대로다★ ────────────────────────────────────
@pytest.mark.parametrize("w,beta,expected", [
    ({"A": 100.0}, {"A": 1.2}, 1.2),
    ({"A": 60.0, "B": 40.0}, {"A": 1.0, "B": 2.0}, 0.6 * 1.0 + 0.4 * 2.0),
    ({"A": 30.0, "B": 30.0}, {"A": 1.0, "B": 3.0}, 2.0),          # 합 60 → 재정규화
])
def test_long_only_exposure_is_unchanged(w, beta, expected):
    assert _expo(w, _betas(**beta))["exposure"] == pytest.approx(expected)


def test_long_only_basis_says_it_is_not_long_short():
    b = portfolio_factor_exposure({"A": 60.0, "B": 40.0}, _betas(A=1.0, B=1.0))["basis"]
    assert b["long_short"] is False
    assert b["short_pct"] == pytest.approx(0.0)
    assert b["gross_pct"] == b["net_pct"] == pytest.approx(100.0)


# ═══════════════════════════════════════════════════════════════════════════
# 2. factor_risk — 숏을 건너뛰던 곳
# ═══════════════════════════════════════════════════════════════════════════

def _stub_monthly(monkeypatch, series: dict[str, list[float]]):
    """`_monthly_returns` 를 결정론 계열로 바꾼다 — 실데이터 없이 산수를 검산한다."""
    import pandas as pd
    idx = pd.period_range("2024-01", periods=len(next(iter(series.values()))),
                          freq="M").to_timestamp()

    def fake(code, months=60, as_of=None):
        # ★as_of 를 받는다★ 프로덕션 시그니처가 바뀌면 더블도 따라가야 한다 —
        # 안 그러면 더블이 실제 호출 규약을 검증하지 않는 것이 된다.
        v = series.get(str(code))
        return None if v is None else pd.Series(v, index=idx)

    import src.engine.valuation.macro_sensitivity as ms
    monkeypatch.setattr(ms, "_monthly_returns", fake)


def test_a_neutral_book_has_near_zero_variance_not_the_long_legs(monkeypatch):
    """★두 다리가 상쇄되면 분산도 상쇄된다★ 숏을 건너뛰면 롱 북의 분산이 나온다."""
    from src.engine.factor_risk import portfolio_monthly_returns
    wave = [0.05, -0.05] * 12
    _stub_monthly(monkeypatch, {"A": wave, "B": wave})
    out = portfolio_monthly_returns({"A": 100.0, "B": -100.0})
    assert out["available"] is True, out.get("reason")
    assert out["variance"] == pytest.approx(0.0, abs=1e-12)
    assert np.allclose(out["returns"], 0.0)


def test_the_long_only_version_of_that_book_is_not_zero(monkeypatch):
    """★짝★ 위가 "무엇이든 0" 이 아님을 증명한다."""
    from src.engine.factor_risk import portfolio_monthly_returns
    wave = [0.05, -0.05] * 12
    _stub_monthly(monkeypatch, {"A": wave, "B": wave})
    out = portfolio_monthly_returns({"A": 100.0, "B": 100.0})
    assert out["variance"] > 1e-4


def test_factor_risk_coverage_is_on_a_gross_basis(monkeypatch):
    """숏 자산의 계열이 없으면 커버리지가 그만큼 내려가야 한다."""
    from src.engine.factor_risk import portfolio_monthly_returns
    _stub_monthly(monkeypatch, {"A": [0.01] * 24, "B": [0.02] * 24})   # C 없음
    out = portfolio_monthly_returns({"A": 100.0, "B": 60.0, "C": -40.0})
    assert out["available"] is True, out.get("reason")
    assert out["coverage_pct"] == pytest.approx(160.0 / 200.0 * 100.0)
    assert "C" in out["missing"]


def test_factor_risk_long_only_is_unchanged(monkeypatch):
    from src.engine.factor_risk import portfolio_monthly_returns
    _stub_monthly(monkeypatch, {"A": [0.01, 0.03] * 12, "B": [0.02, 0.00] * 12})
    out = portfolio_monthly_returns({"A": 60.0, "B": 40.0})
    expected = np.array([0.6 * a + 0.4 * b
                         for a, b in zip([0.01, 0.03] * 12, [0.02, 0.00] * 12)])
    assert np.allclose(out["returns"], expected)
    assert out["coverage_pct"] == pytest.approx(100.0)


# ═══════════════════════════════════════════════════════════════════════════
# 3. attribution — 숏이 소멸하던 곳
# ═══════════════════════════════════════════════════════════════════════════

def _run(weights: dict) -> dict:
    return {
        "run_id": "rr_ls_1", "kind": "allocation_analyze",
        "created_at": time.time() - 90 * 86400,
        "inputs": {"tickers": list(weights), "weights": weights},
        "outputs": {"weights": {"optimized": weights},
                    "summary": {"portfolio": {}, "extra": {}}},
    }


def _flat(code, s, e):
    """A 는 오르고 B 도 오른다 — 숏이 살아 있으면 기여가 **음수**로 나와야 한다."""
    step = 0.5 if code == "A" else 0.3
    return [100.0 + step * i for i in range(60)]


def test_a_short_leg_contributes_negatively_instead_of_vanishing():
    rep = compute_attribution(_run({"A": 130.0, "B": -30.0}), path_of=_flat,
                              benchmark_path=[100.0 + 0.1 * i for i in range(60)])
    per = {r["code"]: r for r in rep["contribution"]["assets"]}
    assert set(per) == {"A", "B"}, "숏이 사라졌다"
    assert per["B"]["weight_pct"] < 0, "숏이 롱으로 뒤집혔다"
    assert per["B"]["contribution_pct"] < 0, "오르는 종목을 숏 쳤는데 기여가 양수다"
    assert per["A"]["contribution_pct"] > 0


def test_a_dollar_neutral_book_reports_its_real_spread_return():
    """★net 재정규화가 죽는 지점★ — 그런데 죽는 방식이 예상과 달랐다.

    처음 이 가드를 "폭발하지 않는다(유한하다)" 로 썼는데 변이 프로브
    (`covw_gross = sum(v)`)가 **green** 이었다. 이유: 정확히 중립이면
    `sum(v) == 0` 이라 `covw_tot > 0` 분기가 막고 `cov_w` 가 **빈 dict** 가 된다
    → 기여가 전부 0, 수익률 0.0, 그리고 그것도 "유한" 하다. 조용한 0 이지 폭발이
    아니었다. 그래서 **값을 핀한다.**

    A 는 +29.5%, B 는 +17.7% 오른다. 절반씩 롱/숏이면 스프레드가 남는다.
    """
    rep = compute_attribution(_run({"A": 100.0, "B": -100.0}), path_of=_flat,
                              benchmark_path=[100.0 + 0.1 * i for i in range(60)])
    r = rep["returns"]["portfolio_pct"]
    assert r == pytest.approx(4.91, abs=0.05), f"중립 북의 스프레드 수익이 아니다: {r}"
    per = {x["code"]: x["contribution_pct"] for x in rep["contribution"]["assets"]}
    # ★항마다 핀한다★ 합만 재면 (14.75, −8.85) 와 (2.95, 1.96) 이 구분되지 않는다.
    assert per["A"] == pytest.approx(14.75, abs=0.05)
    assert per["B"] == pytest.approx(-8.85, abs=0.05)


def test_a_near_neutral_book_does_not_explode():
    """★짝★ 정확히 0 이 아니라 **거의** 0 일 때가 net 정규화의 진짜 폭발 지점이다.
    `sum(v)` 은 0.0005 라 분기를 통과하고 2,000 배로 부풀린다."""
    rep = compute_attribution(_run({"A": 100.0, "B": -99.9}), path_of=_flat,
                              benchmark_path=[100.0 + 0.1 * i for i in range(60)])
    r = rep["returns"]["portfolio_pct"]
    assert r == pytest.approx(4.92, abs=0.10), f"폭발했다: {r}"


def test_attribution_long_only_is_unchanged():
    """★짝★ 기존 롱온리 리포트가 값까지 그대로."""
    rep = compute_attribution(_run({"A": 60.0, "B": 40.0}), path_of=_flat,
                              benchmark_path=[100.0 + 0.1 * i for i in range(60)])
    per = {r["code"]: r["weight_pct"] for r in rep["contribution"]["assets"]}
    assert per == {"A": 60.0, "B": 40.0}


# ═══════════════════════════════════════════════════════════════════════════
# 4. kr_scenario_pack — 시나리오 손익이 롱 북의 것이던 곳
# ═══════════════════════════════════════════════════════════════════════════

def _fake_exposures(monkeypatch, per_code: dict[str, float]):
    codes_seen: list[str] = []

    def loader(codes):
        codes_seen[:] = list(codes)
        n = len(codes)
        vec = np.array([per_code.get(c, 0.0) for c in codes])
        exp = {f: (vec if f == "mkt_beta" else np.zeros(n)) for f in ksp.FACTORS}
        return exp, list(codes), []

    monkeypatch.setattr(ksp, "_load_exposures", loader)
    return codes_seen


def test_a_short_position_is_scored_in_the_scenario(monkeypatch):
    """★예전에는 `codes` 필터가 숏을 목록에서부터 지웠다★"""
    seen = _fake_exposures(monkeypatch, {"A": 1.0, "B": 1.0})
    r = run_scenario(["A", "B"], {"A": 100.0, "B": -100.0}, "semi_selloff")
    assert r["error"] is False, r.get("message")
    assert set(seen) == {"A", "B"}, "숏 종목이 노출 조회에서부터 빠졌다"
    assert {row["stock_code"] for row in r["rows"]} == {"A", "B"}


def test_a_neutral_book_takes_no_shock_at_all_and_says_so(monkeypatch):
    """★분해 항등이 롱숏에서도 성립한다★

    처음 이 가드를 "시장 기본충격만 남는다" 로 썼는데 **전제가 틀렸다.**
    `port_shock = market·Σw + Σ_f (w @ contrib_f)` 이므로 달러중립(Σw = 0)에서는
    시장충격도 두 다리에서 상쇄된다. 그런데 `factor_attribution` 의 market 행은
    스칼라 `market_shock` 을 그대로 적고 있어서 **Σw == 1 일 때만** 항등이
    성립했다 — 롱온리만 있던 동안 드러나지 않던 결함이다.
    """
    _fake_exposures(monkeypatch, {"A": 1.0, "B": 1.0})
    r = run_scenario(["A", "B"], {"A": 100.0, "B": -100.0}, "semi_selloff")
    attr = {f["factor"]: f["contribution_pct"] for f in r["factor_attribution"]}
    assert attr["market"] == pytest.approx(0.0, abs=0.02), "Σw=0 인데 시장충격이 남았다"
    assert sum(attr.values()) == pytest.approx(0.0, abs=0.05)
    assert r["portfolio_shock_pct"] == pytest.approx(0.0, abs=0.05)


def test_the_decomposition_identity_holds_for_a_130_30(monkeypatch):
    """★짝★ Σw = 0.625 인 북에서도 성립해야 한다 — 0 은 우연히 맞을 수 있다."""
    _fake_exposures(monkeypatch, {"A": 1.0, "B": -0.5})
    r = run_scenario(["A", "B"], {"A": 130.0, "B": -30.0}, "semi_selloff")
    total = sum(f["contribution_pct"] for f in r["factor_attribution"])
    assert total == pytest.approx(r["portfolio_shock_pct"], abs=0.05)
    assert r["portfolio_shock_pct"] != pytest.approx(0.0, abs=0.05), "픽스처가 무의미하다"


def test_scenario_long_only_is_unchanged(monkeypatch):
    _fake_exposures(monkeypatch, {"A": 1.0, "B": 1.0})
    a = run_scenario(["A", "B"], {"A": 60.0, "B": 40.0}, "semi_selloff")
    b = run_scenario(["A", "B"], {"A": 60.0, "B": 40.0}, "semi_selloff")
    assert a["portfolio_shock_pct"] == b["portfolio_shock_pct"]
    assert all(row["weight_pct"] > 0 for row in a["rows"])
    assert sum(row["weight_pct"] for row in a["rows"]) == pytest.approx(100.0, abs=0.05)


def test_a_truly_empty_book_is_still_refused(monkeypatch):
    """★짝★ 위 완화가 "무엇이든 통과" 가 되지 않게 한다."""
    _fake_exposures(monkeypatch, {"A": 1.0})
    r = run_scenario(["A"], {"A": 0.0}, "semi_selloff")
    assert r["error"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 5. 라우트 3곳 — 같은 3줄이 세 번 복사돼 있던 곳
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


_KR = ["005930", "000660", "035420"]
_LONG_ONLY = {"005930": 50.0, "000660": 30.0, "035420": 20.0}
_LONG_SHORT = {"005930": 80.0, "000660": 50.0, "035420": -30.0}


def test_factor_xray_accepts_a_long_short_book(client):
    r = client.post("/api/v1/allocation/factor-xray", json={"holdings": _LONG_SHORT})
    assert r.status_code == 200, r.text
    assert r.json().get("error") is not True, r.text


def _xray_z(client, holdings: dict) -> list[float]:
    b = client.post("/api/v1/allocation/factor-xray", json={"holdings": holdings}).json()
    assert b.get("error") is not True, b
    return [f["portfolio_z"] for f in (b.get("factors") or [])
            if f.get("portfolio_z") is not None]


def test_a_neutral_book_still_gets_factor_z_scores(client):
    """★조용한 None★ `cov_w` 를 부호대로 더하면 중립 북에서 0 에 붙어
    `pf_z = acc/cov_w if cov_w > 0` 이 **잴 수 있는데도** None 을 낸다 —
    실측: 그 상태에서 팩터 목록이 통째로 빈다."""
    z = _xray_z(client, {"005930": 100.0, "000660": -100.0})
    assert z, "중립 북의 팩터 z 가 하나도 나오지 않았다"


def test_a_near_neutral_book_does_not_get_absurd_z_scores(client):
    """★짝★ 정확히 0 이 아니면 None 대신 **폭발**한다 — 실측 −347.57.
    z 는 표준화 점수라 이런 크기가 나올 수 없다."""
    z = _xray_z(client, {"005930": 100.0, "000660": -99.0})
    assert z, "근사중립 북의 팩터 z 가 나오지 않았다"
    assert max(abs(v) for v in z) < 10.0, f"z 가 표준화 점수의 범위를 벗어났다: {z}"


def test_stress_accepts_a_long_short_book(client):
    r = client.post("/api/v1/allocation/stress",
                    json={"holdings": _LONG_SHORT, "scenario": "rate_hike_200bp"})
    assert r.status_code == 200, r.text
    assert r.json().get("error") is not True, r.text


def test_a_near_neutral_book_does_not_report_a_ten_thousand_percent_drawdown(client):
    """★역사 리플레이의 net 정규화★

    처음 이 가드를 "200 이고 error 아님" 으로만 썼는데 변이 프로브(`w / w.sum()`)가
    **green** 이었다 — 롱숏 픽스처의 net 이 100 이라 나눠도 폭발하지 않았기 때문이다.
    실측으로 값을 골랐다: net 정규화에서 100/−99 북은 **−10,416.59%** 를 낸다.
    """
    r = client.post("/api/v1/allocation/stress",
                    json={"holdings": {"005930": 100.0, "000660": -99.0},
                          "scenario": "hist_2020_covid"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("available") is True, body
    worst = min(body["portfolio_dd"])
    assert worst > -100.0, f"손실이 원금을 넘었다 — net 으로 나눈 증상이다: {worst}"


def test_an_exactly_neutral_book_gets_a_replay_instead_of_nothing(client):
    """★짝★ 정확히 중립이면 net 정규화는 0 으로 나눠 아예 답을 못 냈다."""
    r = client.post("/api/v1/allocation/stress",
                    json={"holdings": {"005930": 100.0, "000660": -100.0},
                          "scenario": "hist_2020_covid"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("available") is True, body
    assert body["portfolio_dd"], "리플레이 경로가 아무것도 내지 못했다"
    assert min(body["portfolio_dd"]) > -100.0


def test_kr_scenario_keeps_the_short_in_its_rows(client):
    """★숏이 결과 표에 남는다★ 예전에는 목록에서부터 지워졌다."""
    r = client.post("/api/v1/allocation/kr-scenario",
                    json={"holdings": _LONG_SHORT, "scenario": "semi_selloff"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("error") is not True, body
    rows = {row["stock_code"]: row["weight_pct"] for row in body["rows"]}
    assert set(rows) == set(_LONG_SHORT), "숏 종목이 표에서 빠졌다"
    assert rows["035420"] < 0, "숏이 롱으로 뒤집혔다"


def test_an_all_short_book_is_not_told_its_weights_sum_to_zero(client):
    """★거짓 사유★ 예전 `sum(max(w,0)) <= 0` 이 "보유 비중 합이 0입니다" 를 냈다."""
    r = client.post("/api/v1/allocation/kr-scenario",
                    json={"holdings": {"005930": -60.0, "000660": -40.0},
                          "scenario": "semi_selloff"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "0입니다" not in (body.get("message") or ""), body


@pytest.mark.parametrize("path,extra", [
    ("factor-xray", {}),
    ("stress", {"scenario": "rate_hike_200bp"}),
    ("kr-scenario", {"scenario": "semi_selloff"}),
])
def test_the_routes_are_unchanged_for_long_only(client, path, extra):
    """★짝★ 롱온리 응답은 그대로여야 한다 — 두 번 불러 값까지 같은지 본다."""
    body = {"holdings": _LONG_ONLY, **extra}
    a = client.post(f"/api/v1/allocation/{path}", json=body)
    b = client.post(f"/api/v1/allocation/{path}", json=body)
    assert a.status_code == b.status_code == 200
    assert a.json().get("error") is not True, a.text
    assert a.json() == b.json()


def test_long_only_kr_scenario_weights_still_sum_to_100(client):
    """롱온리 정규화가 살아 있는지 값으로 확인한다."""
    r = client.post("/api/v1/allocation/kr-scenario",
                    json={"holdings": _LONG_ONLY, "scenario": "semi_selloff"})
    rows = r.json()["rows"]
    assert sum(row["weight_pct"] for row in rows) == pytest.approx(100.0, abs=0.05)
    assert all(row["weight_pct"] > 0 for row in rows)


# ═══════════════════════════════════════════════════════════════════════════
# 6. neutralize — 출력은 음수를 내면서 입력의 음수는 지우던 곳
# ═══════════════════════════════════════════════════════════════════════════

def test_re_neutralizing_a_net_anchored_book_is_exactly_idempotent():
    """★멱등★ 이미 중립인 북을 다시 중립화하면 **같은 값**이어야 한다.

    예전에는 입력의 숏이 `max(w,0)` 로 먼저 지워져 2회차가 전혀 다른 북을
    중립화했다. 사영은 아핀 집합 위로 떨어뜨리므로 출발점의 스케일이 도착점을
    바꾼다 — 그래서 정규화는 **그 모드가 고정하는 양**(여기서는 net)으로 해야
    한다. gross 로 나누면 `Σw` 가 1 이 아닌 점에서 출발해 결과가 달라진다.
    """
    from src.engine.neutralize import beta_neutralize
    betas = {"A": 0.6, "B": 1.4, "C": 1.0}
    first = beta_neutralize({"A": 50.0, "B": 30.0, "C": 20.0}, betas, target_beta=0.3)
    assert first["error"] is False
    assert any(v < 0 for v in first["weights"].values()), "픽스처가 롱숏이 아니다"

    second = beta_neutralize(first["weights"], betas, target_beta=0.3)
    assert second["error"] is False
    for c, v in first["weights"].items():
        assert second["weights"][c] == pytest.approx(v, abs=1e-4), c


def test_re_neutralizing_a_dollar_neutral_book_keeps_its_direction():
    """★달러중립에는 스케일을 고정하는 것이 없다★ 그래서 멱등성은 **방향까지**다.

    `Σw = 0` 하나로는 크기를 말할 수 없다(P3 가 gross 를 도입한 이유와 같다).
    처음 이 가드를 값 동일로 썼다가 실측에서 배율 3.75 가 나와 전제를 고쳤다 —
    방향은 정확히 보존되고 크기만 입력의 gross 를 따른다. 그 사실은
    `gross_exposure` 로 보고한다.
    """
    from src.engine.neutralize import beta_neutralize
    betas = {"A": 0.6, "B": 1.4, "C": 1.0}
    first = beta_neutralize({"A": 50.0, "B": 30.0, "C": 20.0}, betas, target_beta=0.0,
                            dollar_neutral=True)
    second = beta_neutralize(first["weights"], betas, target_beta=0.0,
                             dollar_neutral=True)
    assert first["error"] is False and second["error"] is False
    assert any(v < 0 for v in first["weights"].values()), "픽스처가 롱숏이 아니다"

    ratios = [second["weights"][c] / first["weights"][c] for c in first["weights"]]
    assert max(ratios) == pytest.approx(min(ratios), rel=1e-4), \
        f"방향이 바뀌었다 — 숏이 지워졌을 때 나타나는 증상이다: {ratios}"
    assert second["gross_exposure"] == pytest.approx(1.0, abs=1e-4)
    # ★짝★ 두 번 모두 제약을 실제로 만족한다(비율만 보면 놓친다).
    for r in (first, second):
        assert r["beta_hit"] is True
        assert r["net"] == pytest.approx(0.0, abs=1e-4)


def test_beta_neutralize_long_only_input_is_unchanged():
    """★짝★ 롱온리 입력에서는 값까지 그대로다."""
    from src.engine.neutralize import beta_neutralize
    betas = {"A": 0.6, "B": 1.4}
    out = beta_neutralize({"A": 60.0, "B": 40.0}, betas, target_beta=1.0)
    assert out["error"] is False
    assert out["beta_hit"] is True
    assert sum(out["weights"].values()) == pytest.approx(100.0, abs=1e-3)


def test_sector_neutralize_keeps_a_short_inside_its_sector():
    """섹터 지분은 gross 로 잰다 — 롱숏이 섞인 섹터가 '비어 있다' 로 보이면 안 된다."""
    from src.engine.neutralize import sector_neutralize
    out = sector_neutralize({"A": 60.0, "B": -20.0, "C": 20.0},
                            {"A": "반도체", "B": "반도체", "C": "인터넷"})
    assert out["error"] is False
    assert out["weights"]["B"] < 0, "숏이 롱으로 뒤집혔다"
    # 반도체 섹터의 gross 지분이 목표(50%)에 맞춰졌다.
    assert out["sector_after_pct"]["반도체"] == pytest.approx(50.0, abs=0.1)
    assert out["sector_after_pct"]["인터넷"] == pytest.approx(50.0, abs=0.1)
