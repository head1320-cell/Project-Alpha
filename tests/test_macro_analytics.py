"""매크로 분석 — 상관/타이밍/국면궤적 단위 검증 (mock, 결정론적).

검증 계약: 상관행렬 대칭·대각1·[-1,1], 롤링 길이/범위, 타이밍 0~100·가중합, 자산추세 필드,
국면궤적 분면/범위/전환. 데이터부족 폴백.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402

from src.engine.macro_analytics import (  # noqa: E402
    _ANALYTICS_UNIVERSE,
    _rolling_corr,
    correlation_panel,
    regime_trajectory,
    timing_panel,
)


def test_universe_is_13():
    assert len(_ANALYTICS_UNIVERSE) == 13
    assert "SPY" in _ANALYTICS_UNIVERSE and "TLT" in _ANALYTICS_UNIVERSE


def test_correlation_matrix_symmetric_diag1_ranged():
    p = correlation_panel("us")
    m = p["matrix"]
    n = len(m["tickers"])
    assert n >= 8
    v = m["values"]
    assert len(m["labels"]) == n
    for i in range(n):
        assert abs(v[i][i] - 1.0) < 1e-6, "대각 != 1"
        for j in range(n):
            assert -1.0001 <= v[i][j] <= 1.0001, "상관 범위 초과"
            assert abs(v[i][j] - v[j][i]) < 1e-6, "비대칭"


def test_correlation_pairs_and_avg():
    p = correlation_panel("us")
    assert len(p["pairs"]) == 5
    keys = {pp["key"] for pp in p["pairs"]}
    assert "SPY-TLT" in keys  # 주식-채권 핵심
    for pp in p["pairs"]:
        assert pp["series"] and all(-1.0001 <= s["corr"] <= 1.0001 for s in pp["series"])
    assert p["avg_corr"] and all(-1.0001 <= s["corr"] <= 1.0001 for s in p["avg_corr"])
    assert p["stock_bond_now"]["verdict"] in ("헤지", "동조", "중립")


def test_rolling_corr_length_and_range():
    a = list(np.sin(np.linspace(0, 12, 240)))
    b = list(np.cos(np.linspace(0, 12, 240)) + 0.1 * np.sin(np.linspace(0, 30, 240)))
    r = _rolling_corr(a, b, window=60)
    assert len(r) == len(a) - 60 + 1
    assert all(-1.0001 <= x <= 1.0001 for x in r)


def test_rolling_corr_short_input_empty():
    assert _rolling_corr([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], window=60) == []


def test_timing_composite_and_components():
    t = timing_panel("us")
    sc = t["composite"]["score"]
    assert 0 <= sc <= 100
    assert t["composite"]["label"] in ("위험 선호", "중립", "위험 회피")
    comps = t["components"]
    assert len(comps) == 5
    assert abs(sum(c["weight"] for c in comps) - 100) < 0.1
    weighted = sum(c["score"] * c["weight"] for c in comps) / 100
    assert abs(weighted - sc) < 0.5, "가중합 != composite"
    for c in comps:
        assert 0 <= c["score"] <= 100


def test_timing_asset_trend_table():
    t = timing_panel("us")
    assert len(t["assets"]) == 13
    need = {"ticker", "label", "vs_ma200_pct", "mom_12m", "dist_52w_high", "rsi", "trend"}
    for a in t["assets"]:
        assert need <= set(a.keys())
        assert a["trend"] in ("상승", "하락", "중립")
        if a["rsi"] is not None:
            assert 0 <= a["rsi"] <= 100


def test_timing_history_present():
    t = timing_panel("us")
    assert t["history"] and all(0 <= h["score"] <= 100 for h in t["history"])


def test_regime_trajectory_structure():
    tj = regime_trajectory()
    assert tj["path"]
    # 사분면 명칭 통일: 헤더(regime_analyzer)와 동일한 regime_axes.quadrant 공용
    quads = {"Goldilocks", "Reflation", "Stagflation", "Disinflation"}
    for p in tj["path"]:
        assert p["quadrant"] in quads
        assert -1.0001 <= p["growth"] <= 1.0001
        assert -1.0001 <= p["inflation"] <= 1.0001
    for tr in tj["transitions"]:
        assert tr["from"] != tr["to"]
        assert tr["from"] in quads and tr["to"] in quads


def test_deterministic_numeric():
    a, b = correlation_panel("us"), correlation_panel("us")
    assert a["matrix"]["values"] == b["matrix"]["values"]
    assert a["stock_bond_now"] == b["stock_bond_now"]
    ta, tb = timing_panel("us"), timing_panel("us")
    assert ta["composite"] == tb["composite"]
    assert [x["score"] for x in ta["components"]] == [x["score"] for x in tb["components"]]


def test_correlation_panel_no_data_fallback(monkeypatch):
    import src.engine.macro_analytics as ma
    monkeypatch.setattr(ma, "daily_closes", lambda *a, **k: [])
    p = ma.correlation_panel("us")
    assert p["matrix"]["tickers"] == []
    assert p["pairs"] == [] and p["avg_corr"] == []
    assert p["stock_bond_now"]["corr"] is None
