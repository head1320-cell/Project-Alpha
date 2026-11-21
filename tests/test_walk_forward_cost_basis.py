"""배분 워크포워드 요약의 비용 기준 — 비용 전 · 비용 후를 나란히 (C1 · 2026-11-19 받은 결정)
==============================================================================
요약의 총수익률 · CAGR · 최대 낙폭은 거래비용을 뺀 자본곡선에서 나오는데, 변동성 · 샤프 · 소르티노는 비용을 빼기 전
일별 수익(`plan.port_daily`)에서 나오고 칼마는 비용 전 산술 연율 수익 ÷ 비용 후 최대 낙폭(혼합)이었다 — 그 기준이 적혀 있지 않았다.
받은 결정(CLAUDE.md §3 의 별도 승인): ★기존 값은 바이트까지 그대로★ 두고 비용 후 값을 같은 관례로 더해 나란히 싣는다.

손 계산 계획(엿새 · 리밸런싱 둘)을 직접 지어 시뮬레이터에 넣는다 — 비용 후 일별 수익은 리밸런싱 날에만
(1 − 회전율 × 비용) × (1 + 그날 수익) − 1 이고 다른 날은 그날 수익 그대로다(비용을 그날 수익보다 먼저 물린다 · 엔진 주석).
기대값은 이 파일의 식으로 따로 계산한다(엔진이 쓰는 함수를 부르지 않는다 — 같은 함수끼리 견주면 공허하다).
"""
from __future__ import annotations

import math
import os
import pathlib
import re

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.allocation_backtest import WalkForwardPlan, simulate_walk_forward  # noqa: E402
from src.engine.market_impact import ImpactAssumptions  # noqa: E402

RF = 0.035          # 이 모듈의 관례(`_RF`) — 연율 무위험
PPY = 252
PORT = [0.010, -0.020, 0.015, 0.000, 0.005, -0.010]
RB_AT = [0, 3]
TURNOVER = [1.0, 0.5]
NEW_KEYS = ("volatility_after_cost_pct", "sharpe_ratio_after_cost", "sortino_ratio_after_cost", "calmar_ratio_after_cost")


def _plan(port=PORT, rb_at=RB_AT, turnover=TURNOVER) -> WalkForwardPlan:
    days = list(range(len(port)))
    strs = [f"2024-01-{d + 2:02d}" for d in days]
    meta = [{"date": strs[i], "weights": {"A": 0.5, "B": 0.5}, "turnover_pct": round(t * 100, 2),
             "gross_pct": 100.0, "net_pct": 100.0} for i, t in zip(rb_at, turnover)]
    return WalkForwardPlan(
        names=["A", "B"], start=0, n_obs=len(port), model="ew", rebalance="M", window_days=None, arm="B0",
        long_short=False, sim_dates=days, sim_date_strs=strs, port_daily=list(port),
        rb_at=list(rb_at), rb_preds=[0.0] * len(rb_at), turnover=list(turnover), rebalance_meta=meta,
        regime_detail=[], infeasible=[])


def _after_cost(port, rb_at, turnover, cost_bps) -> np.ndarray:
    c = cost_bps / 1e4
    out = np.asarray(port, dtype=float).copy()
    for i, t in zip(rb_at, turnover):
        out[i] = (1.0 - t * c) * (1.0 + port[i]) - 1.0
    return out


def _equity(r: np.ndarray) -> np.ndarray:
    return np.cumprod(1.0 + r)


def _sharpe(r: np.ndarray) -> float:
    return (r.mean() - RF / PPY) / r.std(ddof=1) * math.sqrt(PPY)


def _sortino(r: np.ndarray) -> float:
    down = r[r < 0]
    return (r.mean() - RF / PPY) / down.std(ddof=1) * math.sqrt(PPY)


def _vol_pct(r: np.ndarray) -> float:
    return r.std(ddof=1) * math.sqrt(PPY) * 100


def _calmar(r: np.ndarray, eq: np.ndarray) -> float:
    mdd = float((eq / np.maximum.accumulate(eq) - 1.0).min())
    return r.mean() * PPY / abs(mdd)


def _same(v, hand: float) -> None:
    """요약은 소수 둘째 자리로 반올림한다 — 반올림 경계(예: 칼마 −15.855)에서는 1e-12 의 부동소수 차이로 자리가 갈리므로
    '두 자리 값이고, 반올림 전 손 계산과 반 칸(0.005) 안'을 건다(기계마다 갈리는 시험을 만들지 않는다 — M1c 의 교훈)."""
    assert isinstance(v, float) and round(v, 2) == v, v
    assert v == pytest.approx(float(hand), abs=0.005 + 1e-9), (v, hand)


# ── 비용 후 넷 — 손 계산과 같다 ─────────────────────────────────────────────
def test_the_after_cost_ratios_equal_the_hand_computed_ones():
    out = simulate_walk_forward(_plan(), cost_bps=50.0)
    s = out["summary"]
    r = _after_cost(PORT, RB_AT, TURNOVER, 50.0)
    eq = _equity(r)
    assert np.allclose(out["equity_curve"], np.round(eq, 5))                 # 손 계산의 자본곡선이 엔진의 것과 같다(전제)
    _same(s["volatility_after_cost_pct"], _vol_pct(r))
    _same(s["sharpe_ratio_after_cost"], _sharpe(r))
    _same(s["sortino_ratio_after_cost"], _sortino(r))
    _same(s["calmar_ratio_after_cost"], _calmar(r, eq))


def test_the_before_cost_values_cannot_see_the_cost():
    """C1 이 바로잡는 것(2026-11-19 잰 값) — 기존 변동성 · 샤프(★전정밀도 `sharpe_ratio_full` 까지★) · 소르티노와 분포 지표는 비용 전 수익에서
    나와 비용을 0 → 5 → 100bp 로 올려도 한 비트도 움직이지 않는다 ↔ 짝: 같은 실행의 비용 후 값(새 넷 · 기존 총수익률)은 움직인다.
    옛 주석 여섯 곳은 이 고정을 `round(_, 2)` 의 해상도 탓으로 적었다 — 반올림이 아니라 계산 기준 때문이다(84개월 패널에서도 같은 관측)."""
    outs = [simulate_walk_forward(_plan(), cost_bps=c) for c in (0.0, 5.0, 100.0)]
    s0, m0 = outs[0]["summary"], outs[0]["metrics"]
    assert isinstance(s0["sharpe_ratio_full"], float)                       # 전제: 전정밀도 값이 있다(None 끼리 같아서 통과하지 않게)
    for o in outs[1:]:
        for k in ("volatility_pct", "sharpe_ratio", "sharpe_ratio_full", "sortino_ratio"):
            assert o["summary"][k] == s0[k], k
        for k in ("var_pct", "cvar_pct", "omega", "skew", "downside_deviation_pct"):
            assert o["metrics"][k] == m0[k], k
    hi = outs[2]["summary"]
    assert hi["sharpe_ratio_after_cost"] < s0["sharpe_ratio_after_cost"]
    assert hi["volatility_after_cost_pct"] != s0["volatility_after_cost_pct"]
    assert hi["total_return_pct"] < s0["total_return_pct"]                  # 기존 비용 후 값도 같은 곡선에서 움직인다


def test_the_after_cost_values_include_the_market_impact():
    """시장 충격을 물리면 그것도 비용이다 — 리밸런싱 날의 비용 후 수익은 (1 − 회전율 × (비용 + 충격)) × (1 + 그날 수익) − 1 이고,
    충격은 엔진이 재귀에 쓰고 `rebalances[].impact_bps` 로 보고한 바로 그 값이다. 짝: 비용 전 값은 충격이 있든 없든 그대로다."""
    with_imp = simulate_walk_forward(_plan(), cost_bps=50.0, impact=ImpactAssumptions(portfolio_krw=20_000_000_000.0))
    without = simulate_walk_forward(_plan(), cost_bps=50.0)
    bps = [rb["impact_bps"] for rb in with_imp["rebalances"]]
    assert len(bps) == len(RB_AT) and all(b > 0 for b in bps), bps            # 전제: 충격이 실제로 물렸다(공허 방지)
    c = 50.0 / 1e4
    r = np.asarray(PORT, dtype=float).copy()
    for i, t, b in zip(RB_AT, TURNOVER, bps):
        r[i] = (1.0 - t * (c + b / 1e4)) * (1.0 + PORT[i]) - 1.0
    s = with_imp["summary"]
    _same(s["volatility_after_cost_pct"], _vol_pct(r))
    _same(s["sharpe_ratio_after_cost"], _sharpe(r))
    _same(s["sortino_ratio_after_cost"], _sortino(r))
    _same(s["calmar_ratio_after_cost"], _calmar(r, _equity(r)))
    assert s["sharpe_ratio_after_cost"] < without["summary"]["sharpe_ratio_after_cost"]
    for k in ("volatility_pct", "sharpe_ratio", "sharpe_ratio_full", "sortino_ratio"):
        assert s[k] == without["summary"][k], k


def test_the_existing_ratios_stay_before_cost_and_the_calmar_stays_mixed():
    """기존 키의 뜻은 그대로다 — 변동성 · 샤프 · 소르티노는 비용 전 수익 · 칼마는 비용 전 연율 ÷ 비용 후 낙폭(혼합)."""
    s = simulate_walk_forward(_plan(), cost_bps=50.0)["summary"]
    p = np.asarray(PORT)
    eq_after = _equity(_after_cost(PORT, RB_AT, TURNOVER, 50.0))
    _same(s["volatility_pct"], _vol_pct(p))
    _same(s["sharpe_ratio"], _sharpe(p))
    _same(s["sortino_ratio"], _sortino(p))
    _same(s["calmar_ratio"], _calmar(p, eq_after))
    _same(s["total_return_pct"], (eq_after[-1] - 1.0) * 100)                 # 총수익률은 비용 후(그대로)


def test_with_no_cost_the_two_sides_agree():
    """짝 — 비용이 0 이면 비용 전과 비용 후가 같다(차이가 비용에서만 온다)."""
    s = simulate_walk_forward(_plan(), cost_bps=0.0)["summary"]
    assert s["volatility_after_cost_pct"] == s["volatility_pct"]
    assert s["sharpe_ratio_after_cost"] == s["sharpe_ratio"]
    assert s["sortino_ratio_after_cost"] == s["sortino_ratio"]
    assert s["calmar_ratio_after_cost"] == s["calmar_ratio"]


def test_the_after_cost_returns_come_from_the_unrounded_curve():
    """비용 후 일별 수익은 ★반올림하기 전★ 자본곡선에서 되짚는다 — 응답의 `equity_curve` 는 소수 다섯째 자리로 반올림돼 있어, 하루 수익이
    1e-5 보다 작은 곡선에서는 그것으로 되짚으면 수익이 0 과 ±1e-5 로 뭉개진다. 비용이 0 이면 두 쪽이 같아야 한다(짝: 위 시험의 보통 크기 수익)."""
    tiny = [4e-6, -3e-6, 5e-6, -2e-6, 6e-6, -4e-6, 3e-6, 1e-6]
    out = simulate_walk_forward(_plan(port=tiny, rb_at=[0], turnover=[0.4]), cost_bps=0.0)
    s = out["summary"]
    assert len(set(out["equity_curve"])) < len(tiny)                          # 전제: 반올림한 곡선에서는 날의 차이가 사라진다
    assert s["sharpe_ratio_after_cost"] == s["sharpe_ratio"]
    assert s["sortino_ratio_after_cost"] == s["sortino_ratio"]


def test_with_a_cost_the_two_sides_differ():
    """짝의 반대 — 비용이 있으면 비용 후 샤프가 비용 전과 다르다(같으면 비용을 읽지 않은 것이다)."""
    s = simulate_walk_forward(_plan(), cost_bps=50.0)["summary"]
    assert s["sharpe_ratio_after_cost"] != s["sharpe_ratio"]
    assert s["volatility_after_cost_pct"] != s["volatility_pct"]


def test_the_cost_basis_names_every_ratio_and_the_mix():
    s = simulate_walk_forward(_plan(), cost_bps=50.0)["summary"]
    b = s["cost_basis"]
    assert set(b["after_cost"]) >= {"total_return_pct", "cagr_pct", "max_drawdown_pct", *NEW_KEYS}
    assert set(b["before_cost"]) >= {"volatility_pct", "sharpe_ratio", "sortino_ratio", "sharpe_ratio_full"}
    assert b["mixed"] == ["calmar_ratio"]
    assert not (set(b["after_cost"]) & set(b["before_cost"]))
    assert all(k in s for k in [*b["after_cost"], *b["before_cost"], *b["mixed"]])   # 적은 키는 요약에 실제로 있다
    note = b["note"]
    # 칼마의 혼합을 한 문장으로 적는다 — '칼마'라는 낱말만 있는지가 아니라 그 정의(비용 전 연율 ÷ 비용 후 낙폭)를 건다
    assert re.search(r"칼마는 비용 전[^.]*비용 후 최대 낙폭", note), note
    assert "비용 전" in note and "비용 후" in note
    assert not re.search(r"(해요|에요|예요|돼요)\b", note)


def test_every_summary_and_metrics_key_has_exactly_one_basis():
    """화면이 이름표에 붙일 기준표가 빠짐없다 — 키를 더하고 표에 안 적으면 여기서 걸린다(요약 · 지표 묶음 둘 다)."""
    out = simulate_walk_forward(_plan(), cost_bps=50.0)
    b = out["summary"]["cost_basis"]
    for block, table in ((out["summary"], b), (out["metrics"], b["metrics"])):
        keys = {k for k in block if k not in ("convention", "cost_basis", "reasons")}
        groups = [set(table[g]) for g in ("after_cost", "before_cost", "mixed", *(("not_measured",) if "not_measured" in table else ()))]
        assert sum(len(g) for g in groups) == len(set().union(*groups)), "한 키가 두 기준에 들었다"
        assert keys == set().union(*groups), sorted(keys ^ set().union(*groups))
    m = b["metrics"]
    assert {"var_pct", "cvar_pct", "downside_deviation_pct", "omega"} <= set(m["before_cost"])
    assert {"ulcer_index", "avg_drawdown_pct", "recovery_factor"} <= set(m["after_cost"])
    assert m["mixed"] == ["calmar_ratio"]


def test_a_wiped_out_curve_leaves_the_after_cost_ratios_unknown():
    """자본곡선이 0 이하로 내려가면 비용 후 일별 수익을 되짚을 수 없다 — 0 으로 나누지 않고 미상 + 사유(짝: 위 손 계산은 값)."""
    s = simulate_walk_forward(_plan(port=[0.01, 0.02, -0.01], rb_at=[0], turnover=[1.0]), cost_bps=10_000.0)["summary"]
    for k in NEW_KEYS:
        assert s[k] is None, k
        assert "0 이하" in s["cost_basis"]["reasons"][k]


def test_too_few_days_leave_the_after_cost_ratios_unknown_with_a_reason():
    """미상 ≠ 0 — 새 키는 옛 0.0 계약이 없으므로 None + 사유다(기존 키는 옛 계약대로 0.0)."""
    out = simulate_walk_forward(_plan(port=[0.01], rb_at=[0], turnover=[1.0]), cost_bps=10.0)
    s = out["summary"]
    for k in NEW_KEYS:
        assert s[k] is None, k
        why = s["cost_basis"]["reasons"].get(k)
        assert why and "1개" in why, (k, why)                                 # 서버 사유 그대로(관측 수) — 지어낸 문장이 아니다
        assert "—" not in why and "–" not in why and why.endswith("니다"), why  # 화면에 그대로 뜨는 글 — 줄표 없이 합니다체
    assert s["sharpe_ratio"] == 0.0                                           # 짝: 기존 키는 그대로 0.0


def test_no_decision_path_reads_the_after_cost_values():
    """새 값은 보이기만 한다 — 비교 · 선택 · 최적화 · 관문 스크립트가 읽지 않는다(정적 · CLAUDE.md §3 의 승인 범위).
    서버 코드(`src`)와 관문 · 연구 스크립트(`scripts`)를 다 훑는다 — 그 이름이 나오는 곳은 값을 만드는 엔진 한 곳뿐이다(주석도 세는 엄격한 검사)."""
    repo = pathlib.Path(__file__).resolve().parents[1]
    hits = sorted(str(p.relative_to(repo)) for d in ("src", "scripts") for p in (repo / d).rglob("*.py")
                  if "_after_cost" in p.read_text(encoding="utf-8"))
    assert hits == ["src/engine/allocation_backtest.py"], hits
