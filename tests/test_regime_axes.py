"""국면 축 — YoY 변환·z·가중 재정규화·사분면 (지수 레벨 z-score 버그의 회귀 방지)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.regime_axes import (  # noqa: E402
    KR_GROWTH,
    US_GROWTH,
    US_INFLATION,
    compute_axis,
    quadrant,
    yoy_pct,
    zscore_at,
)


class FakeSeries:
    def __init__(self, values):
        self.values = values


def test_yoy_pct_percent_change():
    vals = [100.0] * 12 + [103.0]
    y = yoy_pct(vals)
    assert abs(y[-1] - 3.0) < 1e-9 and y[0] is None


def test_constant_inflation_z_near_zero():
    # 매월 +0.25% (연 ~3%) 등속 상승 지수 — YoY가 일정 → z ≈ 0 (레벨 z였다면 ≈ +1.7)
    vals, v = [], 100.0
    for _ in range(120):
        vals.append(v)
        v *= 1.0025
    z = zscore_at(yoy_pct(vals))
    assert z is not None and abs(z) < 0.5


def test_accelerating_inflation_positive_z():
    vals, v = [], 100.0
    for i in range(120):
        vals.append(v)
        v *= 1.0015 if i < 100 else 1.006   # 최근 가속
    assert zscore_at(yoy_pct(vals)) > 1.0


def test_axis_sign_and_renormalize():
    sm = {"UNRATE": FakeSeries([4.0] * 100 + [6.0])}   # 실업률 급등(성장 부정) — 나머지 미가용
    g = compute_axis(sm, US_GROWTH)
    assert g < 0                                        # 부호 반전 + 재정규화로 단독 반영


def test_missing_all_series_zero():
    assert compute_axis({}, US_INFLATION) == 0.0
    assert compute_axis({}, KR_GROWTH) == 0.0


def test_quadrant_names():
    assert quadrant(1, -1) == "Goldilocks" and quadrant(1, 1) == "Reflation"
    assert quadrant(-1, 1) == "Stagflation" and quadrant(-1, -1) == "Deflation"
