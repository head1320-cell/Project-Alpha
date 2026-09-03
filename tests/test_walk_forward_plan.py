"""walk-forward 계획/시뮬레이션 분리 — ★불변성을 구조로 만든다★ (P7)
==============================================================================
설계: `docs/specs/2026-09-02-deepseek-concept-review.md` §4 P7

P3 이 대수적 항등식으로 증명했다: **비중 경로는 비용에 불변**이다. 그런데 관문은
같은 비중 경로를 비용 수준마다 처음부터 다시 계산했다(3비용 × 185런 = 555
백테스트, 관문 1회 ≈ 12.4분 실측).

★캐시가 아니라 분리를 골랐다★ — 캐시는 키가 불완전하면 **다른 백테스트의 수를
조용히 쓴다**. 대신 계획 단계에서 비용을 인자에서 제거했다. 불변성이 키 관리가
아니라 구조가 되므로 비용 의존성을 넣는 것 자체가 서명 수준에서 막힌다.

비트 동일은 리팩터 **이전 커밋**을 `git worktree` 로 꺼내 같은 호스트에서 전정밀도
대조해 확인했다(18개 분기 격자 전부 일치). 동결 해시는 OpenBLAS 흔들림(`f0c7b10`)
에 취약해 쓰지 않았다.
"""

from __future__ import annotations

import ast
import inspect
import os
import textwrap

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.allocation_backtest import (  # noqa: E402
    WalkForwardPlan,
    plan_walk_forward,
    simulate_walk_forward,
    walk_forward,
)
from src.engine.market_impact import ImpactAssumptions  # noqa: E402


@pytest.fixture(scope="module")
def panel():
    from scripts.t3_transmission import build_panel
    names, R, dates, points, _beta = build_panel(months=36)
    return names, R, dates, points


def _plan(panel, **kw):
    names, R, dates, points = panel
    base = {"model": "bl", "rebalance": "M", "min_train": 252,
            "regime": {"points": points, "weighting": "hard"}}
    return plan_walk_forward(names, R, dates, **{**base, **kw})


# ── ★비용은 계획에 들어올 수 없다★ ───────────────────────────────────────
def test_the_plan_signature_cannot_accept_cost():
    """★이것이 이 리팩터의 요점이다★ 캐시 키를 관리하는 대신 인자를 없앴다."""
    params = set(inspect.signature(plan_walk_forward).parameters)
    assert "cost_bps" not in params
    assert "impact" not in params


def test_the_simulation_signature_does_accept_cost():
    """짝 — 비용이 어디에도 없으면 그건 분리가 아니라 삭제다."""
    params = set(inspect.signature(simulate_walk_forward).parameters)
    assert "cost_bps" in params and "impact" in params


def test_the_plan_body_never_mentions_equity_or_cost():
    """★서명만으로는 부족하다★ 본문이 몰래 비용을 만들어 쓸 수 있다."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(plan_walk_forward)))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "equity" not in names
    assert "cost" not in names and "cost_bps" not in names
    assert "impact" not in names


def test_the_simulation_body_does_use_equity():
    """짝 — 항상-빈 검사를 배제한다."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(simulate_walk_forward)))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "equity" in names and "cost" in names


# ── 계획의 성질 ──────────────────────────────────────────────────────────
def test_the_plan_is_deterministic(panel):
    a, b = _plan(panel), _plan(panel)
    assert a.port_daily == b.port_daily
    assert a.turnover == b.turnover
    assert a.rebalance_meta == b.rebalance_meta


def test_a_different_regime_path_gives_a_different_plan(panel):
    """★짝★ 계획이 입력에 반응하지 않으면 위 결정론 테스트는 공허하다."""
    import src.engine.regime_surrogates as rs
    names, R, dates, points = panel
    other = _plan(panel, regime={"points": rs.constant_path(points),
                                 "weighting": "hard"})
    assert _plan(panel).turnover != other.turnover


def test_the_plan_carries_aligned_rebalance_records(panel):
    """리밸런싱 세 목록은 1:1 이어야 한다 — 어긋나면 비용이 엉뚱한 날에 붙는다."""
    p = _plan(panel)
    assert len(p.rb_at) == len(p.turnover) == len(p.rebalance_meta) == len(p.rb_preds)
    assert len(p.sim_dates) == len(p.port_daily) == len(p.sim_date_strs)
    assert p.rb_at == sorted(p.rb_at)
    assert set(p.rb_at) <= set(p.sim_dates)


def test_the_plan_refuses_bad_input_the_same_way(panel):
    """오류 계약은 계획 단계에 있다 — 호출부가 보던 모양 그대로."""
    names, R, dates, points = panel
    bad = plan_walk_forward(names, R, dates, model="bl", min_train=252,
                            regime={"points": points, "weighting": "nope"})
    assert isinstance(bad, dict) and bad["error"] is True
    assert bad["message"].strip()


def test_the_plan_is_frozen(panel):
    """계획은 시뮬 사이에 공유되므로 ★변경 가능하면 안 된다★."""
    p = _plan(panel)
    assert isinstance(p, WalkForwardPlan)
    from dataclasses import FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        p.start = 0            # type: ignore[misc]


# ── 하나의 계획, 여러 비용 ────────────────────────────────────────────────
def test_one_plan_simulated_at_three_costs_obeys_the_p3_identity(panel):
    """★P3 항등식★ 비중 경로가 비용에 불변이므로

        equity(c) = equity(0) × Π_k (1 − τ_k·c/1e4)

    가 정확히 성립한다. 계획을 공유해도 그 성질이 유지되는지 본다.
    """
    p = _plan(panel)
    free = simulate_walk_forward(p, cost_bps=0.0)
    for c in (5.0, 10.0, 25.0):
        paid = simulate_walk_forward(p, cost_bps=c)
        mult = 1.0
        for rb in paid["rebalances"]:
            mult *= (1.0 - rb["turnover_pct"] / 100.0 * c / 1e4)
        ratio = paid["equity_curve"][-1] / free["equity_curve"][-1]
        assert ratio == pytest.approx(mult, rel=1e-4), f"cost={c}"


def test_simulating_the_same_plan_twice_is_identical(panel):
    """시뮬레이션이 계획을 **변형하지 않는다** — 공유 객체의 필수 조건."""
    p = _plan(panel)
    a = simulate_walk_forward(p, cost_bps=10.0)
    b = simulate_walk_forward(p, cost_bps=10.0)
    assert a["equity_curve"] == b["equity_curve"]
    assert a["rebalances"] == b["rebalances"]


def test_a_shared_plan_is_not_mutated_by_an_impact_run(panel):
    """★짝★ 충격 경로가 계획을 건드리면 다음 비용 수준이 오염된다."""
    p = _plan(panel)
    before = list(p.turnover), list(p.port_daily)
    simulate_walk_forward(p, cost_bps=10.0,
                          impact=ImpactAssumptions(portfolio_krw=1e11))
    assert (list(p.turnover), list(p.port_daily)) == before


def test_the_facade_equals_plan_then_simulate(panel):
    """`walk_forward` 가 합성 그 자체임을 값으로 확인한다."""
    names, R, dates, points = panel
    kw = dict(model="bl", rebalance="M", min_train=252,
              regime={"points": points, "weighting": "hard"})
    direct = walk_forward(names, R, dates, cost_bps=10.0, **kw)
    composed = simulate_walk_forward(_plan(panel), cost_bps=10.0)
    assert direct["equity_curve"] == composed["equity_curve"]
    assert direct["summary"] == composed["summary"]
    assert direct["rebalances"] == composed["rebalances"]


def test_the_cost_actually_changes_the_curve(panel):
    """★짝★ 비용이 아무것도 안 바꾸면 위 항등식 테스트들이 공허하다."""
    p = _plan(panel)
    assert (simulate_walk_forward(p, cost_bps=0.0)["equity_curve"]
            != simulate_walk_forward(p, cost_bps=25.0)["equity_curve"])


def test_the_equity_curve_is_exactly_the_plan_replayed(panel):
    """★자본곡선은 계획의 재생이고, 그 순서까지 계약이다★

    비트 동일 대조는 `git worktree` 가 필요해 **테스트 스위트 밖**에 있다. 그래서
    스위트 안에는 산술을 고정하는 것이 없었고, 변이 U6(일수익을 1e-7 만큼 흔들기)
    이 살아남았다 — 그런 변경은 CI 를 통과해 버린다.

    ★흔들림에 면역인 방식으로 건다★ 계획의 `port_daily`·`turnover` 를 그대로 써서
    자본곡선을 독립적으로 재구성한다. 양쪽이 같은 계획을 쓰므로 BLAS 를 다시 타지
    않고, 따라서 OpenBLAS 흔들림(`f0c7b10`)이 개입할 여지가 없다. 곱셈 **순서**가
    바뀌어도 깨진다(리밸런싱일에는 비용이 먼저다).
    """
    p = _plan(panel)
    for cost in (0.0, 10.0, 25.0):
        out = simulate_walk_forward(p, cost_bps=cost)
        rb_pos = {t: k for k, t in enumerate(p.rb_at)}
        eq, expected = 1.0, []
        for i, t in enumerate(p.sim_dates):
            k = rb_pos.get(t)
            if k is not None:                      # ★비용이 먼저★
                eq *= (1.0 - p.turnover[k] * (float(cost) / 1e4))
            eq *= (1.0 + p.port_daily[i])
            expected.append(eq)
        assert out["equity_curve"] == list(np.round(np.asarray(expected), 5)), \
            f"cost={cost}"


def test_the_replay_notices_a_reordered_multiplication(panel):
    """★짝★ 위 재생이 순서에 둔감하면 그 테스트는 절반만 건 것이다."""
    p = _plan(panel)
    assert p.rb_at, "리밸런싱이 없으면 순서를 논할 수 없다"
    rb_pos = {t: k for k, t in enumerate(p.rb_at)}

    def replay(cost_first: bool) -> list[float]:
        eq, out = 1.0, []
        for i, t in enumerate(p.sim_dates):
            k = rb_pos.get(t)
            if k is not None and cost_first:
                eq *= (1.0 - p.turnover[k] * 25.0 / 1e4)
            eq *= (1.0 + p.port_daily[i])
            if k is not None and not cost_first:
                eq *= (1.0 - p.turnover[k] * 25.0 / 1e4)
            out.append(eq)
        return out

    assert replay(True) != replay(False)
