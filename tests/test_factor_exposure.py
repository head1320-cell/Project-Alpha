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


def _series(n_months: int, start: float = 100.0, step: float = 1.0,
            wobble: float = 0.0):
    """`series_changes` 가 읽는 모양 — `timestamps` + `values`.

    ★`wobble` 이 필요한 이유★ 완전 선형이면 **차분이 상수**가 되어 회귀가
    "설명변수가 상수" 로 정당하게 거절한다. 변환이 비율에서 차분으로 바뀌면서
    이 픽스처가 그 함정에 걸렸다 — 코드가 아니라 픽스처의 문제였다.
    """
    ts, vals = [], []
    for i in range(n_months):
        y, m = 2021 + (i // 12), (i % 12) + 1
        ts.append(f"{y}-{m:02d}")
        vals.append(start + step * i + wobble * ((i * 7919) % 13 - 6))
    return SimpleNamespace(timestamps=ts, values=vals)


def _map(**overrides) -> dict:
    """모든 팩터의 **첫** 후보를 넉넉한 계열로 채운 뒤 필요한 것만 덮는다."""
    out = {cands[0]: _series(60, wobble=0.7) for cands in FACTOR_PROXIES.values()}
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


# ── 6. ★변화의 단위★ 비율과 차분은 다른 숫자다 ────────────────────────────
def test_a_rate_series_uses_differences_not_ratios():
    """★금리·스프레드는 %p 가 경제적 단위다★ 비율은 뜻이 다르다."""
    from src.engine.factor_exposure import series_changes
    ch, kind, note = series_changes(_series(12, start=3.0, step=0.1), "KR_10Y")
    assert kind == "diff" and note is None
    assert all(abs(v - 0.1) < 1e-9 for v in ch.values()), "차분이면 매달 +0.1"


def test_a_price_series_uses_ratios():
    """★짝★ 가격·지수는 비율이 맞다 — 전부 차분으로 바꾸면 안 된다."""
    from src.engine.factor_exposure import series_changes
    ch, kind, note = series_changes(_series(12, start=100.0, step=10.0), "KOSPI")
    assert kind == "pct" and note is None
    assert ch["2021-02"] == pytest.approx(0.10), "100 → 110 은 +10%"


def test_a_series_crossing_zero_is_not_ratio_transformed():
    """★실측★ `VIXCLS` 가 음수(최소 −5.09)를 지나며 한 달 변화가 6730% 로 튀었고,
    그 이상치 하나가 Ledoit-Wolf 를 λ=1.0(항등행렬)로 밀어 상관구조를 지웠다.
    """
    from src.engine.factor_exposure import series_changes
    crossing = SimpleNamespace(
        timestamps=["2021-01", "2021-02", "2021-03", "2021-04"],
        values=[2.0, 0.0001, -1.0, 3.0])
    ch, kind, note = series_changes(crossing, "KOSPI")   # pct 대상인데 0 을 지난다
    assert kind == "diff", "0 을 지나면 비율을 쓰지 않는다"
    assert note and "폭발" in note
    assert max(abs(v) for v in ch.values()) < 10.0, "폭발하지 않는다"


def test_the_ratio_blowup_is_what_we_are_preventing():
    """★짝의 대조★ 같은 계열을 비율로 강제하면 실제로 폭발한다 — 그래서 막는다."""
    vals = [2.0, 0.0001, -1.0, 3.0]
    ratios = [vals[i + 1] / vals[i] - 1.0 for i in range(len(vals) - 1)
              if abs(vals[i]) > 0]
    assert max(abs(r) for r in ratios) > 100.0, "비율이면 100배 넘게 튄다"


def test_an_unknown_series_defaults_to_the_safe_transform():
    from src.engine.factor_exposure import series_changes
    _ch, kind, _n = series_changes(_series(12), "처음보는계열")
    assert kind == "diff", "모르는 계열은 안전한 쪽으로"


def test_the_transform_is_reported_so_betas_can_be_read():
    """★무엇을 썼는지 모르면 베타를 해석할 수 없다★"""
    b = asset_factor_betas(["005930"], series_map=_map())
    assert set(b["transforms"]) == set(b["proxies"])
    for factor, fit in b["assets"]["005930"]["betas"].items():
        if fit.get("available"):
            assert fit["transform"] in ("pct", "diff"), factor


def test_the_real_series_transforms_match_the_measurement(live):
    """★실측 검산★ 금리·스프레드·VIX 는 차분, 가격·물가는 비율."""
    t = {f: i["transform"] for f, i in live["resolved"].items()}
    assert t["duration"] == "diff" and t["credit"] == "diff"
    assert t["volatility"] == "diff", "VIXCLS 는 0 을 지난다"
    assert t["equity"] == "pct" and t["inflation"] == "pct"
