"""BR R1 — 전략끼리 견고성(관측만) · `src/engine/strategy_robustness.py`.

거는 것 (스펙 docs/superpowers/specs/2026-09-28-br-robustness-profile-design.md):
- 상관 추이: 알려진 상관의 흐름에서 띠가 참값을 품는다 · 상관 0 이면 띠가 0 을 품는다(짝) · 흔들림 없는 창은 None(0 아님)
- 위기 때: 정규 관계면 같이 떨어진 날 ≈ 기대 · 꼬리 동반을 심으면 관측 > 기대(짝) · 시장이 없으면 라벨 붙은 열화
- 최악 구간: 손으로 만든 두 구간의 겹침 비율이 정확 · 잃은 적이 없으면 None + 사유
- 안정성: 절반마다 상관이 다르면 표시 · 같으면 표시 없음(짝)
- 실질 개수 · 분산 효과: 같은 흐름이면 1 · 독립이면 n · √2
- 날짜를 지어내지 않는다 — 응답 어디에도 날짜 키가 없다
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.engine import strategy_robustness as sr


def _pair(rho: float, T: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((T, 2))
    x = z[:, 0]
    y = rho * z[:, 0] + math.sqrt(1 - rho * rho) * z[:, 1]
    return np.column_stack([x, y]) * 0.01


def _keys(obj) -> set[str]:
    out: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            out |= _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _keys(v)
    return out


# ── 상관 추이 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rho", [0.6, 0.0])
def test_rolling_band_holds_true_correlation(rho):
    S = _pair(rho, 756, seed=7)
    r = sr.rolling_correlation(["A", "B"], S, window=60)
    assert r["available"] is True
    p = r["pairs"][0]
    assert (p["a"], p["b"]) == ("A", "B")
    n = len(p["values"])
    assert n == 756 - 60 + 1 == len(p["lo"]) == len(p["hi"]) == len(r["ago"])
    cover = np.mean([lo <= rho <= hi for lo, hi in zip(p["lo"], p["hi"])])
    assert cover >= 0.85, cover                                   # 95% 띠(창이 겹쳐 독립은 아니다)
    assert abs(float(np.mean(p["values"])) - rho) < 0.08
    assert r["ago"][0] == 756 - 60 and r["ago"][-1] == 0          # 가로축은 "n거래일 전"
    assert p["current"] == p["values"][-1]


def test_rolling_flat_window_is_none_not_zero():
    S = _pair(0.5, 200, seed=3)
    S[100:180, 1] = 0.0                                            # 80일 동안 흔들림 없음
    r = sr.rolling_correlation(["A", "B"], S, window=60)
    vals = r["pairs"][0]["values"]
    assert all(vals[i] is None for i in range(100, 121))          # 창 전체가 흔들림 없는 구간 — 0 이 아니라 None
    assert r["pairs"][0]["n_empty"] == sum(v is None for v in vals) > 0
    # 짝 — 흔들림이 있으면 빈 창이 없다
    assert sr.rolling_correlation(["A", "B"], _pair(0.5, 200, 3), window=60)["pairs"][0]["n_empty"] == 0


def test_rolling_too_short_says_why():
    r = sr.rolling_correlation(["A", "B"], _pair(0.5, 50, 1), window=60)
    assert r["available"] is False and "50" in r["reason"] and "60" in r["reason"]


# ── 위기 때 상관 ─────────────────────────────────────────────────────────────

def test_crisis_gaussian_co_drops_match_expectation():
    S = _pair(0.5, 4000, seed=11)
    c = sr.crisis_correlation(["A", "B"], S, market=S.mean(axis=1) + 0.0)
    p = c["pairs"][0]
    assert c["basis"] == "market"
    assert abs(p["co_drops"] - p["expected_co_drops"]) / p["expected_co_drops"] < 0.25


def test_crisis_tail_coupling_exceeds_expectation():
    # 짝 — 평소엔 약하게 엮였지만 가끔 함께 크게 무너지는 두 흐름
    rng = np.random.default_rng(5)
    T = 4000
    S = _pair(0.1, T, seed=5)
    crash = rng.random(T) < 0.05
    S[crash] -= 0.03
    c = sr.crisis_correlation(["A", "B"], S, market=None)
    p = c["pairs"][0]
    assert p["co_drops"] > 1.5 * p["expected_co_drops"]


def test_crisis_without_market_is_labelled():
    S = _pair(0.3, 500, seed=2)
    c = sr.crisis_correlation(["A", "B"], S, market=None)
    assert c["basis"] == "strategy_mean" and "부풀" in c["note"]
    c2 = sr.crisis_correlation(["A", "B"], S, market=S[:, 0] * 0.5 + S[:, 1] * 0.5)
    assert c2["basis"] == "market" and "부풀" not in (c2.get("note") or "")


def test_crisis_small_sample_flag():
    assert sr.crisis_correlation(["A", "B"], _pair(0.3, 150, 4), market=None)["small_sample"] is True
    assert sr.crisis_correlation(["A", "B"], _pair(0.3, 600, 4), market=None)["small_sample"] is False


# ── 최악 구간 겹침 ───────────────────────────────────────────────────────────

def test_drawdown_overlap_exact():
    T = 40
    a = np.full(T, 0.01)
    b = np.full(T, 0.01)
    a[10:20] = -0.02                                               # A 가 잃은 날: 10~19
    b[15:25] = -0.02                                               # B 가 잃은 날: 15~24
    d = sr.drawdown_overlap(["A", "B"], np.column_stack([a, b]), shares=[0.5, 0.5], worst_window=5)
    sa, sb = d["strategies"]
    assert (sa["start_ago"], sa["end_ago"]) == (T - 1 - 10, T - 1 - 19)
    assert (sb["start_ago"], sb["end_ago"]) == (T - 1 - 15, T - 1 - 24)
    pair = d["pairs"][0]
    assert pair["overlap_days"] == 5 and pair["union_days"] == 15
    assert pair["overlap"] == pytest.approx(5 / 15, abs=1e-3)
    assert sa["max_drawdown_pct"] == pytest.approx((0.98 ** 10 - 1) * 100, abs=1e-2)
    w = d["worst_window"]
    assert (w["days"], w["start_ago"], w["end_ago"]) == (5, T - 1 - 15, T - 1 - 19)
    assert w["returns_pct"]["A"] == pytest.approx((0.98 ** 5 - 1) * 100, abs=1e-2)
    assert w["combined_pct"] == pytest.approx((0.98 ** 5 - 1) * 100, abs=1e-2)


def test_drawdown_none_when_never_lost():
    S = np.full((30, 2), 0.01)
    S[5, 1] = -0.01
    d = sr.drawdown_overlap(["A", "B"], S, shares=None, worst_window=5)
    assert d["strategies"][0]["max_drawdown_pct"] is None and d["strategies"][0]["reason"]
    assert d["strategies"][1]["max_drawdown_pct"] is not None
    assert d["pairs"][0]["overlap"] is None and d["pairs"][0]["reason"]


# ── 안정성 · 실질 개수 · 분산 효과 ───────────────────────────────────────────

def test_stability_flags_changed_relation_only():
    changed = np.vstack([_pair(0.8, 300, 1), _pair(-0.2, 300, 2)])
    same = _pair(0.5, 600, 3)
    assert sr.correlation_stability(["A", "B"], changed)["pairs"][0]["changed"] is True
    assert sr.correlation_stability(["A", "B"], same)["pairs"][0]["changed"] is False


def test_effective_n_and_diversification():
    x = _pair(0.0, 3000, 9)
    same = np.column_stack([x[:, 0], x[:, 0]])
    assert sr.effective_count(["A", "B"], same)["value"] == pytest.approx(1.0, abs=1e-6)
    three = np.column_stack([x, _pair(0.0, 3000, 10)[:, 0]])
    assert sr.effective_count(["A", "B", "C"], three)["value"] > 2.8
    assert sr.diversification(same, [0.5, 0.5])["ratio"] == pytest.approx(1.0, abs=1e-6)
    assert sr.diversification(x, [0.5, 0.5])["ratio"] == pytest.approx(math.sqrt(2), abs=0.08)


def test_flat_strategy_is_unknown_not_zero():
    S = _pair(0.4, 300, 8)
    S[:, 1] = 0.0
    e = sr.effective_count(["A", "B"], S)
    assert e["value"] is None and e["reason"]
    st = sr.correlation_stability(["A", "B"], S)
    assert st["pairs"][0]["changed"] is None and st["pairs"][0]["reason"]


# ── 묶음 보고서 ───────────────────────────────────────────────────────────────

def test_report_has_every_block_and_no_dates():
    S = np.column_stack([_pair(0.3, 400, 1), _pair(0.3, 400, 2)[:, 0]])
    rep = sr.robustness_report(["A", "B", "C"], S, shares=None, market=None, window=60)
    for k in ("rolling", "crisis", "drawdown", "stability", "effective_n", "diversification"):
        assert k in rep, k
    assert rep["shares_basis"] == "equal" and rep["n_days"] == 400 and rep["axis"] == "trading_days_ago"
    assert not any("date" in k.lower() for k in _keys(rep))
    rep2 = sr.robustness_report(["A", "B", "C"], S, shares=[0.5, 0.3, 0.2], market=S.mean(axis=1), window=60)
    assert rep2["shares_basis"] == "given"


def test_report_needs_two_strategies():
    rep = sr.robustness_report(["A"], _pair(0.1, 300, 1)[:, :1], shares=None)
    assert rep["available"] is False and rep["reason"]


# ── sleeve_analytics 정직성 (BR R1a) — 흔들림 없는 묶음의 상관은 0 이 아니라 모름 ─────────────────

def _golden_inputs():
    rng = np.random.default_rng(20260928)
    codes = ["005930", "000660", "035420", "051910"]
    base = rng.normal(0, 0.01, (300, 1))
    R = base * np.array([1.0, 0.8, 0.3, -0.2]) + rng.normal(0, 0.01, (300, 4))
    rm = {c: [float(x) for x in R[:, i]] for i, c in enumerate(codes)}
    sleeves = [{"name": "가", "weights": {"005930": 60.0, "000660": 40.0}},
               {"name": "나", "weights": {"000660": 50.0, "035420": 50.0}},
               {"name": "다", "weights": {"051910": 100.0}}]
    return sleeves, rm


def test_sleeve_analytics_normal_output_is_unchanged_golden():
    import json
    from pathlib import Path

    from src.engine.sleeve_combine import sleeve_analytics
    sleeves, rm = _golden_inputs()
    want = json.loads((Path(__file__).parent / "golden" / "sleeve_analytics_normal.json").read_text())["result"]
    got = json.loads(json.dumps(sleeve_analytics(sleeves, ret_matrix=rm, weights={"가": 0.5, "나": 0.3, "다": 0.2})))
    assert got == want


def test_sleeve_analytics_flat_sleeve_is_unknown_not_zero():
    from src.engine.sleeve_combine import sleeve_analytics
    sleeves, rm = _golden_inputs()
    rm["051910"] = [0.0] * 300                                     # '다' 는 흔들림이 없다
    out = sleeve_analytics(sleeves, ret_matrix=rm)
    assert out["correlation"]["가"]["다"] is None and out["correlation"]["다"]["나"] is None
    assert out["correlation"]["가"]["나"] is not None               # 짝 — 잰 쌍은 그대로
    assert "다" in out["correlation_reasons"] and out["correlation_reasons"]["다"]
    # 평균 상관은 잰 쌍(가·나)만으로 — 0 을 섞어 끌어내리지 않는다
    assert out["avg_correlation"] == out["correlation"]["가"]["나"]
    assert out["clusters"]["다"] is None
    sleeves2, rm2 = _golden_inputs()
    rm2["051910"] = [0.0] * 300
    rm2["005930"] = [0.0] * 300
    rm2["000660"] = [0.0] * 300
    rm2["035420"] = [0.0] * 300
    none = sleeve_analytics(sleeves2, ret_matrix=rm2)
    assert none["avg_correlation"] is None and none["n_clusters"] is None
