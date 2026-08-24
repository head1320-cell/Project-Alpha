"""사용자가 준 비중의 **부호**는 라우트 경계에서 지워지지 않는다.

직전 슬라이스는 분석 **엔진** 7곳을 고쳤다. 그런데 그 엔진들에 값을 넣어 주는
**경계**가 여전히 숏을 잘라 내고 있었다 — 열거 grep 이 `head -30` 에서 잘렸고
나는 그것을 완전한 목록으로 취급했다.

★착수 0단계 실측★ 클램프가 **하류의 폭발을 가리고 있었다**:

    PortfolioAnalyzer(returns, weights)      # kis_portfolio_analyzer.py:193
        롱온리 60/40      → {A: 0.6,  B: 0.4}
        달러중립 100/−100 → {A: inf,  B: −inf}      ← w / w.sum()
        근사중립 100/−99  → {A: 100.0, B: −99.0}    ← 1.0 으로 나눴다

`/analyze` 의 `max(w, 0)` 을 먼저 걷었다면 `inf` 가 나갔을 것이다. 그래서
`PortfolioAnalyzer` 를 먼저 고치고 경계를 걷는다.

★값을 핀한다★ 지난 슬라이스에서 "200 이고 error 아님" 류 가드가 **세 번** 통과했다.
상태코드는 가드가 아니다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import math  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from src.kis_portfolio_analyzer import PortfolioAnalyzer  # noqa: E402


def _returns(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    return pd.DataFrame(rng.normal(0.0005, 0.012, size=(n, 2)), columns=["A", "B"])


# ═══════════════════════════════════════════════════════════════════════════
# 1. PortfolioAnalyzer — ★inf 발생지★
# ═══════════════════════════════════════════════════════════════════════════

def test_a_dollar_neutral_book_no_longer_normalizes_to_infinity():
    """★0단계 실측을 뒤집는다★ `w / w.sum()` 은 Σw≈0 에서 무너진다."""
    a = PortfolioAnalyzer(returns=_returns(), weights={"A": 100.0, "B": -100.0})
    w = a.weights.to_dict()
    assert all(math.isfinite(v) for v in w.values()), f"유한하지 않다: {w}"
    assert w["A"] == pytest.approx(0.5)
    assert w["B"] == pytest.approx(-0.5)


def test_a_near_neutral_book_is_not_left_at_a_hundred_times_scale():
    """★조용한 비정규화★ 100/−99 는 net 이 1.0 이라 예외 없이 통과하면서
    비중이 **100배**로 남았다 — 폭발보다 잡기 어려운 실패다."""
    a = PortfolioAnalyzer(returns=_returns(), weights={"A": 100.0, "B": -99.0})
    w = a.weights.to_dict()
    assert abs(w["A"]) < 1.0 and abs(w["B"]) < 1.0, f"정규화되지 않았다: {w}"
    assert sum(abs(v) for v in w.values()) == pytest.approx(1.0)


def test_the_diversification_ratio_measures_the_sum_of_the_parts():
    """분자 `Σ(vol·w)` 를 **부호대로** 더하면 중립 북에서 0 에 붙는다.

    처음 이 가드를 `0 < dr < 10` 으로 썼는데 변이 프로브가 **green** 이었다 —
    부호대로 합산한 값이 0.028299 라 그 범위 안에 있었기 때문이다. 범위는
    가드가 아니다. 실측으로 값을 핀한다.

    ★1.0 이 구조적 바닥이다★ 분산투자비율은 "개별 위험의 합 ÷ 포트폴리오 위험"
    이고 위험은 열등가법적이므로 1 미만이 될 수 없다. 0.0283 은 포트폴리오가
    부분들의 합보다 35배 더 위험하다는 뜻이 되어 성립하지 않는다.
    """
    m = PortfolioAnalyzer(returns=_returns(),
                          weights={"A": 100.0, "B": -100.0}).analyze()
    dr = m.diversification_ratio
    assert math.isfinite(dr), dr
    assert dr >= 1.0, f"분산투자비율이 구조적 바닥 아래다 — 분자를 부호대로 더했다: {dr}"
    assert dr == pytest.approx(1.4345, abs=5e-4)


@pytest.mark.parametrize("w,expected", [
    ({"A": 60.0, "B": 40.0}, {"A": 0.6, "B": 0.4}),
    ({"A": 100.0}, {"A": 1.0}),
    ({"A": 30.0, "B": 30.0}, {"A": 0.5, "B": 0.5}),
])
def test_long_only_normalization_is_unchanged(w, expected):
    """★짝 — 롱온리는 값까지 그대로★ `Σ|w| ≡ Σw` 이므로."""
    a = PortfolioAnalyzer(returns=_returns(), weights=w)
    for k, v in expected.items():
        assert a.weights[k] == pytest.approx(v)


def test_long_only_diversification_ratio_is_unchanged():
    """★짝★ 분자를 `abs` 로 바꾼 것이 롱온리를 건드리지 않았는지."""
    m = PortfolioAnalyzer(returns=_returns(), weights={"A": 60.0, "B": 40.0}).analyze()
    assert m.diversification_ratio == pytest.approx(1.3640, abs=5e-4)
