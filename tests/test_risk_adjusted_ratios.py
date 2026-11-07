"""위험조정 지표 단일 출처 — ★관례가 수를 만든다★ (P1)
==============================================================================
설계: `docs/specs/2026-08-30-macro-to-portfolio-architecture-review.md` §2 W1

★공식이 아니라 관례가 갈라져 있었다★ `allocation_backtest` 와
`multi_strategy_backtest` 의 Sharpe 는 **대수적으로 동일**하다(rf·ddof 를 맞추면
차이 1.4e-16). 그런데 실제 값은 66% 어긋나고 부호까지 뒤집힌다 — 무위험이 한 곳은
0.035, 다른 곳은 0.025, 또 한 곳은 **아예 없고**, `ddof` 도 1/0 으로 갈리기 때문이다.

그래서 이 모듈의 계약은 "정의 하나" 가 아니라 ★**관례를 인자로 받고, 그 관례를
산출에 함께 싣는다**★ 다. 어떤 리포트든 그 수를 만든 관례를 달고 다녀야 한다.

★A3 에서 이미 물렸다★ 사전등록의 주 통계로 쓴 `summary.sharpe_ratio` 가
`round(_, 2)` 라 비용 5→100bps 에서 0.42 로 고정이었고, "비용 3수준 전부" 라는
사전등록 절이 무의미해졌다. 그래서 여기서는 **전정밀도**를 낸다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.quant_metrics import (  # noqa: E402
    DEFAULT_DDOF,
    DEFAULT_PERIODS_PER_YEAR,
    DEFAULT_RISK_FREE,
    compute_metrics,
    risk_adjusted_ratios,
)


def _series(n=1260, mu=0.0004, sd=0.01, seed=0):
    return np.random.default_rng(seed).normal(mu, sd, n)


def _equity(r):
    eq = [1.0]
    for x in r:
        eq.append(eq[-1] * (1 + x))
    return np.array(eq[1:])


# ══════════════════════════════════════════════════════════════════════════
# ★관례가 수를 만든다 — 죽은 인자를 되살린다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_risk_free_rate_actually_changes_the_answer():
    """★`compute_metrics(risk_free=...)` 는 선언만 되고 쓰이지 않았다★

    `allocation_backtest:495` 가 `risk_free=_RF` 를 넘기며 뭔가 한다고 믿고
    있었다. 이 테스트가 그 죽은 인자를 되살린다.
    """
    r = _series()
    a = risk_adjusted_ratios(r, _equity(r), risk_free=0.035)["sharpe_ratio"]
    b = risk_adjusted_ratios(r, _equity(r), risk_free=0.0)["sharpe_ratio"]
    assert a != b
    assert a < b, "무위험을 빼면 Sharpe 가 낮아져야 한다"


def test_the_three_repo_conventions_give_different_numbers():
    """★§2 W1 의 실측을 계약으로 못 박는다★

    같은 수익 계열에 세 관례를 적용하면 66% 어긋나고 **부호가 뒤집힌다**.
    이 사실이 사라지면 "관례를 신고해야 한다" 는 이 모듈의 존재 이유가 사라진다.
    """
    r = _series()
    eq = _equity(r)
    alloc = risk_adjusted_ratios(r, eq, risk_free=0.035, ddof=1)["sharpe_ratio"]
    multi = risk_adjusted_ratios(r, eq, risk_free=0.025, ddof=0)["sharpe_ratio"]
    none_rf = risk_adjusted_ratios(r, eq, risk_free=0.0, ddof=1)["sharpe_ratio"]

    assert alloc == pytest.approx(-0.161603, abs=1e-5)
    assert multi == pytest.approx(-0.097427, abs=1e-5)
    assert none_rf == pytest.approx(0.063148, abs=1e-5)
    assert abs(alloc - multi) / abs(multi) > 0.5      # 66% 어긋난다
    assert alloc < 0 < none_rf                        # ★부호가 뒤집힌다★


def test_the_conventions_travel_with_the_numbers():
    """★수만 내면 그 수가 무엇인지 알 수 없다★ 관례를 산출에 싣는다."""
    r = _series(n=300)
    out = risk_adjusted_ratios(r, _equity(r), risk_free=0.03, ddof=0,
                               periods_per_year=12)
    c = out["convention"]
    assert c["risk_free"] == 0.03
    assert c["ddof"] == 0
    assert c["periods_per_year"] == 12
    assert c["annualization"] == "arithmetic"
    assert c["declared"] is True


def test_the_ddof_convention_changes_the_answer():
    r = _series(n=60)
    one = risk_adjusted_ratios(r, _equity(r), ddof=1)["sharpe_ratio"]
    zero = risk_adjusted_ratios(r, _equity(r), ddof=0)["sharpe_ratio"]
    assert one != zero
    assert abs(one) < abs(zero), "ddof=1 이 표준편차를 키우므로 비율이 작아진다"


def test_the_defaults_are_the_repo_dominant_convention():
    """★0.035 가 지배 관례다★ — regime_analyzer·cash_management·realism_engine·
    company_analytics·allocation_backtest 가 전부 이 값을 쓴다."""
    assert DEFAULT_RISK_FREE == 0.035
    assert DEFAULT_DDOF == 1
    assert DEFAULT_PERIODS_PER_YEAR == 252


# ══════════════════════════════════════════════════════════════════════════
# 공식 — ★정확한 수로 검사한다★
# ══════════════════════════════════════════════════════════════════════════
def test_sharpe_is_annualised_excess_over_volatility():
    r = _series(n=500, seed=3)
    out = risk_adjusted_ratios(r, _equity(r), risk_free=0.02, ddof=1,
                               periods_per_year=252)
    want = (r.mean() - 0.02 / 252) / r.std(ddof=1) * np.sqrt(252)
    assert out["sharpe_ratio"] == pytest.approx(want, rel=1e-12)


def test_sortino_uses_downside_deviation_only():
    """하방편차는 **음수 수익만** 본다 — 전체 표준편차보다 작으므로 비율은 크다."""
    r = _series(n=500, seed=4)
    out = risk_adjusted_ratios(r, _equity(r), risk_free=0.0)
    assert out["sortino_ratio"] > out["sharpe_ratio"]
    down = r[r < 0]
    want = r.mean() / down.std(ddof=1) * np.sqrt(252)
    assert out["sortino_ratio"] == pytest.approx(want, rel=1e-12)


def test_calmar_is_annualised_return_over_max_drawdown():
    r = _series(n=500, seed=5)
    eq = _equity(r)
    out = risk_adjusted_ratios(r, eq, risk_free=0.0)
    mdd = float((eq / np.maximum.accumulate(eq) - 1.0).min())
    assert out["max_drawdown"] == pytest.approx(mdd, rel=1e-12)
    assert out["calmar_ratio"] == pytest.approx(
        out["annualized_return"] / abs(mdd), rel=1e-12)


def test_annualised_return_is_arithmetic_and_declared():
    """★산술이다 — 기하가 아니다★ 관례를 신고하므로 오독을 막는다."""
    r = _series(n=252, seed=6)
    out = risk_adjusted_ratios(r, _equity(r))
    assert out["annualized_return"] == pytest.approx(r.mean() * 252, rel=1e-12)
    assert out["convention"]["annualization"] == "arithmetic"


# ══════════════════════════════════════════════════════════════════════════
# ★전정밀도 — A3 에서 물린 그것★
# ══════════════════════════════════════════════════════════════════════════
def test_the_ratios_are_full_precision_not_rounded():
    """★반올림이 관문을 무의미하게 만들었다★

    A3 에서 `round(_, 2)` 된 Sharpe 가 비용 5→100bps 에서 0.42 로 **고정**이라
    사전등록의 "비용 3수준 전부" 절이 아무것도 요구하지 않게 됐다.
    """
    r = _series(n=800, seed=7)
    eq = _equity(r)
    base = risk_adjusted_ratios(r, eq)["sharpe_ratio"]
    nudged = risk_adjusted_ratios(r - 1e-6, eq)["sharpe_ratio"]
    assert base != nudged, "미세한 비용 차이가 지표에 보여야 한다"
    assert abs(base - nudged) < 1e-2, "그런데 크기는 미세하다 — 반올림이면 0 이 된다"


def test_a_cost_difference_survives_into_the_ratio():
    """★짝★ 비용을 5→100bps 로 올리면 Sharpe 가 **움직여야** 한다.

    처음에는 여기에 "반올림하면 구별이 사라진다" 도 걸었는데 이 픽스처에서는
    2자리에서도 구별됐다 — ★반올림이 항상 가리는 것은 아니다.★ A3 에서 가려진
    것은 그 계열의 Sharpe 가 마침 0.42 근처에 몰려 있었기 때문이다. 계열에
    의존하는 주장을 계약으로 걸지 않는다. 걸어야 할 것은 **전정밀도가 차이를
    보존한다** 하나다.
    """
    r = _series(n=800, seed=8)
    lo = risk_adjusted_ratios(r - 5e-4 / 252, _equity(r))["sharpe_ratio"]
    hi = risk_adjusted_ratios(r - 100e-4 / 252, _equity(r))["sharpe_ratio"]
    assert lo > hi
    assert abs(lo - hi) > 0, "비용 차이가 지표에서 사라졌다"


# ══════════════════════════════════════════════════════════════════════════
# ★미상은 0 이 아니다★
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("r", [np.array([]), np.array([0.01])])
def test_too_few_observations_are_unknown_not_zero(r):
    out = risk_adjusted_ratios(r, _equity(r) if r.size else np.array([]))
    assert out["sharpe_ratio"] is None
    assert out["reasons"]["sharpe_ratio"]


def test_zero_variance_is_unknown_not_infinite():
    """분산이 0 이면 비율이 정의되지 않는다 — `0.0` 도 `inf` 도 아니다."""
    r = np.full(100, 0.001)
    out = risk_adjusted_ratios(r, _equity(r))
    assert out["sharpe_ratio"] is None
    assert out["reasons"]["sharpe_ratio"]


def test_no_drawdown_means_no_calmar():
    """한 번도 손실이 없으면 Calmar 의 분모가 없다 — ★미상★."""
    r = np.full(100, 0.001)
    out = risk_adjusted_ratios(r, _equity(r))
    assert out["calmar_ratio"] is None
    assert out["reasons"]["calmar_ratio"]


def test_no_downside_means_no_sortino():
    r = np.full(100, 0.001)
    out = risk_adjusted_ratios(r, _equity(r))
    assert out["sortino_ratio"] is None
    assert out["reasons"]["sortino_ratio"]


def test_every_unknown_carries_a_reason():
    """★사유 없는 미상은 침묵 폴백이다★ (CLAUDE.md §4)"""
    out = risk_adjusted_ratios(np.array([]), np.array([]))
    for k, v in out.items():
        if k in ("convention", "reasons"):
            continue
        if v is None:
            assert (out["reasons"].get(k) or "").strip(), f"{k} 에 사유가 없다"


# ══════════════════════════════════════════════════════════════════════════
# compute_metrics 와의 통합 — ★두 벌이 되지 않게★
# ══════════════════════════════════════════════════════════════════════════
def test_compute_metrics_now_carries_the_ratios():
    """호출부가 바로 다음 줄에서 다시 계산할 이유가 없어야 한다."""
    r = _series(n=500, seed=9)
    m = compute_metrics(r, _equity(r), risk_free=0.035)
    for k in ("sharpe_ratio", "sortino_ratio", "calmar_ratio",
              "annualized_return", "annualized_volatility"):
        assert k in m, k
    assert m["convention"]["risk_free"] == 0.035


def test_compute_metrics_risk_free_is_no_longer_dead():
    """★죽은 인자를 되살렸다★ — 예전에는 넘겨도 아무 일이 없었다."""
    r = _series(n=500, seed=10)
    eq = _equity(r)
    a = compute_metrics(r, eq, risk_free=0.035)["sharpe_ratio"]
    b = compute_metrics(r, eq, risk_free=0.0)["sharpe_ratio"]
    assert a != b


def test_compute_metrics_agrees_with_the_standalone_function():
    """★단일 출처★ — 두 경로가 같은 수를 내야 한다."""
    r = _series(n=400, seed=11)
    eq = _equity(r)
    assert compute_metrics(r, eq, risk_free=0.02)["sharpe_ratio"] == pytest.approx(
        risk_adjusted_ratios(r, eq, risk_free=0.02)["sharpe_ratio"], rel=1e-15)


def test_existing_compute_metrics_keys_are_unchanged():
    """★가산 변경★ — 기존 소비자 5곳을 깨지 않는다."""
    r = _series(n=300, seed=12)
    m = compute_metrics(r, _equity(r))
    for k in ("volatility_pct", "var_pct", "cvar_pct", "ulcer_index",
              "skew", "kurtosis", "best_period_pct", "worst_period_pct"):
        assert k in m, k


# ══════════════════════════════════════════════════════════════════════════
# ★연율화 관례도 인자다★ — 기하 CAGR (P1 확장)
# ══════════════════════════════════════════════════════════════════════════
#
# P1 은 무위험·ddof 를 인자로 받아 관례를 산출에 실었지만 연율화는 **산술 고정**
# 이었다. 그래서 기하 CAGR 을 쓰는 모듈(`multi_strategy_backtest`)은 calmar 를
# 단일 출처로 옮길 수 없었다 — 옮기면 값이 바뀌기 때문이다. 그것이 이 divergence
# 가 P1 이후에도 살아남은 이유다.

def _geo_fixture():
    rng = np.random.default_rng(7)
    rets = rng.normal(0.0004, 0.011, 600)
    cap0 = 1_000_000.0
    return rets, cap0 * np.cumprod(1 + rets), cap0


def test_geometric_annualization_is_cagr_from_the_starting_equity():
    rets, eq, cap0 = _geo_fixture()
    out = risk_adjusted_ratios(rets, eq, annualization="geometric",
                               starting_equity=cap0)
    expected = (eq[-1] / cap0) ** (252 / len(rets)) - 1
    assert out["annualized_return"] == pytest.approx(expected, rel=1e-15)
    assert out["convention"]["annualization"] == "geometric"
    assert out["convention"]["starting_equity"] == cap0


def test_arithmetic_stays_the_default_and_is_unchanged():
    """★짝★ 기존 호출부는 한 자도 바뀌지 않아야 한다."""
    rets, eq, _ = _geo_fixture()
    out = risk_adjusted_ratios(rets, eq)
    assert out["convention"]["annualization"] == "arithmetic"
    assert out["annualized_return"] == pytest.approx(float(np.mean(rets)) * 252,
                                                     rel=1e-15)
    assert out["convention"]["starting_equity"] is None


def test_the_two_annualizations_really_differ():
    """둘이 같은 수를 내면 이 확장은 의미가 없다 — 실측 −26.99% vs −24.65%."""
    rets, eq, cap0 = _geo_fixture()
    a = risk_adjusted_ratios(rets, eq)["annualized_return"]
    g = risk_adjusted_ratios(rets, eq, annualization="geometric",
                             starting_equity=cap0)["annualized_return"]
    assert abs(a - g) > 0.02


def test_calmar_follows_the_declared_annualization():
    """calmar 는 연율수익/|낙폭| 이므로 관례가 바뀌면 함께 바뀐다."""
    rets, eq, cap0 = _geo_fixture()
    out = risk_adjusted_ratios(rets, eq, annualization="geometric",
                               starting_equity=cap0)
    assert out["calmar_ratio"] == pytest.approx(
        out["annualized_return"] / abs(out["max_drawdown"]), rel=1e-15)


def test_geometric_without_a_starting_equity_is_refused():
    """★규모를 모르면 CAGR 을 지어내지 않는다★ — 미상 + 사유."""
    rets, eq, _ = _geo_fixture()
    out = risk_adjusted_ratios(rets, eq, annualization="geometric")
    assert out["annualized_return"] is None
    assert out["reasons"]["annualized_return"].strip()


def test_an_unknown_annualization_is_refused_loudly():
    """짝 — 오타가 조용히 산술로 떨어지면 리포트가 거짓 관례를 신고한다."""
    rets, eq, cap0 = _geo_fixture()
    with pytest.raises(ValueError):
        risk_adjusted_ratios(rets, eq, annualization="compound",
                             starting_equity=cap0)


def test_a_nonpositive_starting_equity_is_refused():
    rets, eq, _ = _geo_fixture()
    out = risk_adjusted_ratios(rets, eq, annualization="geometric",
                               starting_equity=0.0)
    assert out["annualized_return"] is None
    assert out["reasons"]["annualized_return"].strip()
