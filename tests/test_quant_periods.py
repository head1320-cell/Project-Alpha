"""기간별 수익 · 주요 낙폭 구간 — 자본곡선에서 **옮기기만** 하는 순수 함수 둘 (2026-11-09 · 캔버스 성과 그림 문법).

설계: `docs/superpowers/specs/2026-11-09-canvas-performance-viz-design.md` §4.5.
- 화면은 새 수를 만들지 않으므로(BJ 원칙) 해마다·월별 수익률과 낙폭 구간은 서버가 낸다. 지표 공식은 `quant_metrics` 한 곳
  (`tests/test_metrics_single_source.py`).
- ★부분 기간은 연환산하지 않는다★ — 3개월짜리 해를 "연 수익" 처럼 보이면 거짓이다. `partial` 로 표시만 한다.
- ★모르는 것은 None★ — 회복 못 한 낙폭의 회복일은 `None` 이지 오늘도 0 도 아니다. 빈 곡선은 빈 목록이다.
"""
from __future__ import annotations

import math

import pytest

from src.engine.quant_metrics import drawdown_episodes, period_returns


def _curve(step: dict[str, float]) -> tuple[list[str], list[float]]:
    """{날짜: 값} → (dates, equity). 넣은 순서 그대로."""
    return list(step), list(step.values())


# ── 기간별 수익 ────────────────────────────────────────────────────────────────

def test_yearly_and_monthly_returns_are_chained_from_the_curve():
    """해·달의 수익은 그 기간의 첫 값 **직전**부터 마지막 값까지 — 같은 곡선의 두 수준을 나눈 것이다(연환산 없음)."""
    dates, eq = _curve({
        "2024-11-29": 1.00, "2024-12-31": 1.10,           # 2024: 1.00 → 1.10 = +10% (12월만 · 부분)
        "2025-01-31": 1.21, "2025-06-30": 1.21, "2025-12-31": 0.99,   # 2025: 1.10 → 0.99 = −10%
        "2026-03-31": 1.188,                              # 2026: 0.99 → 1.188 = +20% (3개월 · 부분)
    })
    p = period_returns(dates, eq)
    years = {y["year"]: y for y in p["yearly"]}
    assert years[2025]["return_pct"] == pytest.approx(-10.0, abs=1e-6)
    assert years[2026]["return_pct"] == pytest.approx(20.0, abs=1e-6)
    # 첫 해는 곡선의 첫 값이 시작점이다(그 앞은 없다) — 2024 는 1.00 → 1.10.
    assert years[2024]["return_pct"] == pytest.approx(10.0, abs=1e-6)
    months = {(m["year"], m["month"]): m for m in p["monthly"]}
    assert months[(2025, 1)]["return_pct"] == pytest.approx(10.0, abs=1e-6)      # 1.10 → 1.21
    assert months[(2025, 12)]["return_pct"] == pytest.approx(-100 * (1 - 0.99 / 1.21), abs=1e-3)   # 소수 넷째 자리로 반올림해 싣는다


def test_partial_periods_are_flagged_and_never_annualized():
    """★짝★ 12개월을 다 채운 해만 `partial=False`. 3개월짜리 해의 수익은 그 3개월 수익 그대로(×4 가 아니다)."""
    dates, eq = _curve({"2025-01-02": 1.0, "2025-12-30": 1.5, "2026-03-31": 1.65})
    p = period_returns(dates, eq)
    years = {y["year"]: y for y in p["yearly"]}
    assert years[2025]["partial"] is False and years[2025]["n_days"] == 2
    assert years[2026]["partial"] is True and years[2026]["return_pct"] == pytest.approx(10.0, abs=1e-6)
    # 연환산했다면 10% 가 아니라 46% 쯤이다 — 그 값이면 실패.
    assert not math.isclose(years[2026]["return_pct"], ((1.1) ** 4 - 1) * 100, rel_tol=1e-3)
    months = {(m["year"], m["month"]): m for m in p["monthly"]}
    assert months[(2026, 3)]["n_days"] == 1 and months[(2026, 3)]["partial"] is True


def test_yearly_rows_carry_that_years_max_drawdown_from_the_curve():
    """해마다 'MDD(최대낙폭)' 은 그 해 안의 최고점 대비 — 다른 해의 고점을 끌어오지 않는다."""
    dates, eq = _curve({"2025-01-02": 1.0, "2025-03-03": 1.5, "2025-06-02": 1.2, "2025-12-30": 1.6,
                        "2026-01-02": 1.6, "2026-02-02": 1.44})
    p = period_returns(dates, eq)
    years = {y["year"]: y for y in p["yearly"]}
    assert years[2025]["max_drawdown_pct"] == pytest.approx(-20.0, abs=1e-6)     # 1.5 → 1.2
    assert years[2026]["max_drawdown_pct"] == pytest.approx(-10.0, abs=1e-6)     # 1.6 → 1.44 (2026 안에서)


def test_empty_or_single_point_curve_gives_empty_lists_not_zeros():
    assert period_returns([], []) == {"yearly": [], "monthly": []}
    assert period_returns(["2025-01-02"], [1.0]) == {"yearly": [], "monthly": []}


def test_non_finite_values_are_skipped_not_zeroed():
    """값을 모르는 날(None/NaN)은 그 날을 건너뛴다 — 0 으로 두면 −100% 낙폭을 지어낸다."""
    dates = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]
    p = period_returns(dates, [1.0, None, float("nan"), 1.1])
    assert p["monthly"][0]["return_pct"] == pytest.approx(10.0, abs=1e-6)
    assert p["monthly"][0]["n_days"] == 2
    assert p["yearly"][0]["max_drawdown_pct"] == 0.0           # NaN 을 0 으로 두면 −100% 낙폭이 생긴다
    assert drawdown_episodes(dates, [1.0, None, float("nan"), 1.1]) == []


# ── 큰 낙폭 사건 ───────────────────────────────────────────────────────────────

def test_drawdown_episodes_are_sorted_by_depth_and_carry_dates_and_days():
    dates, eq = _curve({
        "2025-01-02": 1.0, "2025-01-03": 0.9, "2025-01-06": 1.0,                      # 사건 A: −10%, 바닥 1일, 회복 2일
        "2025-02-03": 1.2, "2025-02-04": 1.0, "2025-02-05": 0.84, "2025-02-06": 1.1, "2025-02-07": 1.25,   # B: −30%, 바닥 2일, 회복 4일
        "2025-03-03": 1.3, "2025-03-04": 1.17,                                         # C: −10%, 아직 회복 못 함
    })
    eps = drawdown_episodes(dates, eq, top=3)
    assert [round(e["depth_pct"], 6) for e in eps] == [-30.0, -10.0, -10.0]
    b = eps[0]
    assert (b["peak_date"], b["trough_date"], b["recovery_date"]) == ("2025-02-03", "2025-02-05", "2025-02-07")
    assert b["days_to_trough"] == 2 and b["days_to_recover"] == 4
    # 같은 깊이면 먼저 일어난 것이 앞 — A 가 C 보다 앞.
    assert eps[1]["peak_date"] == "2025-01-02" and eps[2]["peak_date"] == "2025-03-03"


def test_unrecovered_episode_says_so_with_none_not_a_date():
    """★짝★ 회복 못 한 사건의 회복일·회복 일수는 None — 마지막 날짜나 0 으로 채우지 않는다."""
    dates, eq = _curve({"2025-01-02": 1.0, "2025-01-03": 0.8, "2025-01-06": 0.9})
    (e,) = drawdown_episodes(dates, eq)
    assert e["recovery_date"] is None and e["days_to_recover"] is None
    assert e["depth_pct"] == pytest.approx(-20.0, abs=1e-6) and e["trough_date"] == "2025-01-03"


def test_top_limits_the_count_and_a_flat_curve_has_no_episodes():
    dates, eq = _curve({"2025-01-02": 1.0, "2025-01-03": 1.0, "2025-01-06": 1.1})
    assert drawdown_episodes(dates, eq) == []
    many = {f"2025-01-{d:02d}": v for d, v in zip(range(1, 11), [1, .9, 1, .8, 1, .7, 1, .6, 1, 1.0])}
    assert len(drawdown_episodes(*_curve(many), top=2)) == 2
    assert drawdown_episodes([], []) == []
