"""팩터 인지 — 자산 개수가 아니라 팩터 개수를 본다 (Brief §8.4)

★이 파일이 거는 것★
  1. ★있는 것이 아니라 **쓸 수 있는** 것을 고른다★ 수집기에 있어도 월별 관측이
     0인 계열이 있다(`KR_CREDIT_SPREAD` 실측 0개월).
  2. ★차원의 저주를 숨기지 않는다★ 월 59개에 팩터 9개면 관측/모수 6.56 이다.
  3. ★베타를 못 낸 자산을 0 으로 채우지 않는다★ 그러면 노출이 실제보다 작아 보인다.

합성 계열로 **성질**을 재고, 실제 수집기 경로는 아래 live 테스트가 확인한다 —
합성 입력만 쓰다 결함 둘을 놓친 뒤의 규칙이다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

from src.engine.factor_exposure import (  # noqa: E402
    FACTOR_PROXIES,
    FACTORS,
    MIN_MONTHS,
    asset_factor_betas,
    factor_concentration,
    portfolio_factor_exposure,
    resolve_proxies,
)


def _series(n_months: int, start: float = 100.0, step: float = 1.0):
    """`_series_monthly_change` 가 읽는 모양 — `timestamps` + `values`."""
    ts, vals = [], []
    for i in range(n_months):
        y, m = 2021 + (i // 12), (i % 12) + 1
        ts.append(f"{y}-{m:02d}")
        vals.append(start + step * i)
    return SimpleNamespace(timestamps=ts, values=vals)


def _map(**overrides) -> dict:
    """모든 팩터의 **첫** 후보를 넉넉한 계열로 채운 뒤 필요한 것만 덮는다."""
    out = {cands[0]: _series(60) for cands in FACTOR_PROXIES.values()}
    out.update(overrides)
    return out


# ── 1. ★쓸 수 있는 것을 고른다★ ───────────────────────────────────────────
def test_every_factor_resolves_when_the_first_proxy_is_usable():
    out = resolve_proxies(_map())
    assert out["available"] is True
    assert set(out["resolved"]) == set(FACTORS)
    assert out["unresolved"] == {}


def test_a_present_but_empty_series_falls_through_to_the_next_proxy():
    """★실측★ `KR_CREDIT_SPREAD` 는 수집기에 **있지만** 월 관측이 0이다.

    있고 없고가 아니라 **쓸 수 있고 없고**를 봐야 한다.
    """
    sm = _map(KR_CREDIT_SPREAD=_series(1), KR_TERM_SPREAD=_series(60))
    resolved = resolve_proxies(sm)["resolved"]
    assert resolved["credit"]["series"] == "KR_TERM_SPREAD"


def test_a_factor_with_no_usable_proxy_says_which_ones_it_tried():
    sm = _map()
    for cand in FACTOR_PROXIES["commodity"]:
        sm.pop(cand, None)
    out = resolve_proxies(sm)
    assert "commodity" not in out["resolved"]
    assert "수집기에 없음" in out["unresolved"]["commodity"]


def test_a_thin_series_is_reported_with_its_month_count():
    sm = _map()
    for cand in FACTOR_PROXIES["volatility"]:
        sm[cand] = _series(5)
    out = resolve_proxies(sm)
    assert "volatility" in out["unresolved"]
    assert "월 관측 4개" in out["unresolved"]["volatility"]


def test_an_empty_map_is_a_reason_not_a_crash():
    out = resolve_proxies({})
    assert out["available"] is False and out["reason"]


def test_a_dead_collector_answers_with_a_reason(monkeypatch):
    class _Boom:
        def __init__(self):
            raise RuntimeError("수집 불가")
    monkeypatch.setattr("src.engine.regime_analyzer.RegimeAnalyzer", _Boom)
    out = resolve_proxies()
    assert out["available"] is False and out["reason"]


# ── 2. ★차원의 저주를 숨기지 않는다★ ──────────────────────────────────────
def test_the_sample_to_factor_ratio_is_reported():
    b = asset_factor_betas(["005930"], series_map=_map())
    s = b["sample"]
    assert s["n_factors"] == len(FACTORS)
    assert s["obs_per_factor"] == pytest.approx(s["n_months"] / s["n_factors"], abs=0.01)


def test_the_method_is_univariate_and_says_so():
    """다변량으로 한 번에 풀면 59관측·9팩터에서 자유도가 위태롭다."""
    b = asset_factor_betas(["005930"], series_map=_map())
    assert b["method"] == "univariate_ols_monthly"
    assert b["multiple_testing"]["n_tested"] == len(FACTORS)
    assert "데이터 마이닝" in b["multiple_testing"]["note"]


def test_correlation_is_labelled_as_not_causation():
    b = asset_factor_betas(["005930"], series_map=_map())
    assert "인과가 아닙니다" in b["causality"]


def test_a_higher_minimum_closes_every_factor():
    b = asset_factor_betas(["005930"], series_map=_map(), min_months=10_000)
    assert b["available"] is False and b["reason"]


# ── 3. ★0 으로 채우지 않는다★ ─────────────────────────────────────────────
def test_coverage_is_reported_so_a_partial_exposure_is_not_read_as_small():
    """★베타 없는 자산을 0 으로 채우면 노출이 실제보다 작아 보인다★"""
    b = asset_factor_betas(["005930"], series_map=_map())
    assert b["available"] is True
    # 절반의 비중이 베타 없는 자산이면 커버리지가 그것을 말한다.
    e = portfolio_factor_exposure({"005930": 50.0, "없는종목": 50.0}, b)
    for factor, row in e["by_factor"].items():
        assert row["coverage_pct"] == pytest.approx(50.0, abs=0.01), factor
        assert "없는종목" in row["missing"]
    assert "0 으로 채우지 않습니다" in e["note"]


def test_full_coverage_is_reported_as_full():
    b = asset_factor_betas(["005930"], series_map=_map())
    e = portfolio_factor_exposure({"005930": 100.0}, b)
    for row in e["by_factor"].values():
        assert row["coverage_pct"] == pytest.approx(100.0, abs=0.01)
        assert row["missing"] == []


def test_zero_weights_are_refused():
    b = asset_factor_betas(["005930"], series_map=_map())
    assert portfolio_factor_exposure({"005930": 0.0}, b)["available"] is False


def test_an_unavailable_beta_block_propagates_its_reason():
    out = portfolio_factor_exposure({"A": 100.0},
                                    {"available": False, "reason": "표본 부족"})
    assert out["available"] is False and out["reason"] == "표본 부족"


def test_each_exposure_names_the_series_it_came_from():
    b = asset_factor_betas(["005930"], series_map=_map())
    e = portfolio_factor_exposure({"005930": 100.0}, b)
    for factor, row in e["by_factor"].items():
        assert row["series"] == b["proxies"][factor]


# ── 4. ★팩터 수준 집중도★ ────────────────────────────────────────────────
def test_factor_concentration_is_not_the_asset_enb():
    """★한 표에 섞지 않는다★ 자산 ENB(Σ 주성분)와 다른 물건이다."""
    b = asset_factor_betas(["005930"], series_map=_map())
    c = factor_concentration(portfolio_factor_exposure({"005930": 100.0}, b))
    assert c["available"] is True
    assert "자산 ENB" in c["note"]
    assert 1.0 <= c["effective_factors"] <= c["n_factors"]


def test_a_single_dominant_factor_gives_roughly_one_effective_factor():
    """자산이 분산돼도 팩터가 하나면 분산이 아니다 — 그것이 §8.4 의 요점이다."""
    exposure = {"available": True, "by_factor": {
        "equity": {"available": True, "exposure": 10.0},
        "duration": {"available": True, "exposure": 0.0001},
        "usd": {"available": True, "exposure": 0.0001}}}
    c = factor_concentration(exposure)
    assert c["effective_factors"] == pytest.approx(1.0, abs=0.05)
    assert c["hhi"] > 0.99


def test_evenly_spread_factors_give_the_full_count():
    exposure = {"available": True, "by_factor": {
        f: {"available": True, "exposure": 1.0} for f in ("a", "b", "c", "d")}}
    c = factor_concentration(exposure)
    assert c["effective_factors"] == pytest.approx(4.0, abs=1e-6)
    assert c["hhi"] == pytest.approx(0.25, abs=1e-6)


def test_all_zero_exposures_are_a_reason_not_a_number():
    exposure = {"available": True, "by_factor": {
        "a": {"available": True, "exposure": 0.0}}}
    assert factor_concentration(exposure)["available"] is False


# ── 5. ★실제 수집기 경로★ (합성만 쓰다 결함 둘을 놓친 뒤의 규칙) ──────────
@pytest.fixture(scope="module")
def live() -> dict:
    out = resolve_proxies()
    if not out.get("available"):
        pytest.skip(f"이 환경에서 매크로 계열을 낼 수 없다: {out.get('reason')}")
    return out


def test_the_real_collector_resolves_the_measured_proxies(live):
    """★실측 검산★ 숫자가 달라지면 상류 수집기가 바뀐 것이다."""
    got = {f: i["series"] for f, i in live["resolved"].items()}
    assert got.get("equity") == "KOSPI"
    assert got.get("duration") == "KR_10Y"
    assert got.get("commodity") == "DCOILWTICO", "유가 계열은 수집기에 있다"
    # KR_CREDIT_SPREAD 는 있지만 월 관측 0 이라 다음 후보로 넘어간다.
    assert got.get("credit") == "KR_TERM_SPREAD"


def test_the_real_series_carry_enough_months(live):
    for factor, info in live["resolved"].items():
        assert info["n_months"] >= MIN_MONTHS, factor
