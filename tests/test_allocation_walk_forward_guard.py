"""E2 — ★학습창이 미래를 보지 않는다★ 를 **동작으로** 건다.

## 왜 이 파일이 생겼나

`allocation_evidence.window_axis()` 가 이 경로의 `window` 축을 `ok` 라고 판정한다.
그 근거는 `plan_walk_forward` 의

    R_win = R[lo:t]          # t **미포함**

한 줄이다. ★구조적 주장은 가드가 있을 때만 구조적이다★ — 이 슬라이스가 언젠가
`R[lo:t+1]` 로 바뀌면 배지는 여전히 `ok` 를 그리면서 거짓이 된다. 그것이 정확히
이 작업이 없애려는 모양(★상수가 관측 행세를 한다★)이다.

## ★소스 텍스트가 아니라 동작을 본다★ (CLAUDE.md §5)

`inspect.getsource` 로 `R[lo:t]` 문자열을 찾으면 리팩터링 한 번에 무의미해진다.
대신 **행 t 를 바꿔치고 비중이 안 움직이는지** 본다 — 슬라이스가 t 를 포함하면
비중이 반드시 달라진다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.engine.allocation_backtest import _rebalance_indices, plan_walk_forward

NAMES = ["A", "B", "C"]


def _dates(n: int) -> list:
    """실제 경로와 같은 모양 — 라우트는 `list(returns.index)`(Timestamp)를 넘긴다."""
    return list(pd.date_range("2020-01-01", periods=n, freq="D"))


def _returns(n: int, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0004, 0.01, size=(n, len(NAMES)))


def _plan(R, dates):
    p = plan_walk_forward(NAMES, R, dates, model="mvo", rebalance="M")
    assert not isinstance(p, dict), f"계획 단계에서 거부됐다: {p}"
    return p


def _weights(plan) -> list[dict]:
    return [dict(m.get("weights") or {}) for m in plan.rebalance_meta]


def test_the_fixture_actually_rebalances():
    """★테스트의 테스트★ — 리밸런싱이 없으면 아래 비교가 전부 공허하다."""
    n = 400
    dates = _dates(n)
    plan = _plan(_returns(n), dates)
    assert len(plan.rb_at) >= 3
    assert _weights(plan)[0], "비중이 비어 있으면 무엇도 비교할 수 없다"


def test_changing_the_row_at_a_rebalance_date_does_not_move_that_weight():
    """★핵심 가드★ 행 `t` 는 시점 `t` 의 비중에 들어가면 안 된다.

    슬라이스가 `R[lo:t+1]` 로 바뀌면 이 테스트가 죽는다 — `window` 축이 `ok` 라고
    말할 근거가 사라지는 바로 그 순간이다.
    """
    n = 400
    dates = _dates(n)
    R = _returns(n)
    rb = _rebalance_indices(dates, "M", 63)
    assert rb, "리밸런싱 인덱스가 없다"

    base = _weights(_plan(R, dates))

    # 마지막 리밸런싱 시점의 행 하나만 **극단적으로** 바꾼다.
    t = rb[-1]
    R2 = R.copy()
    R2[t, :] = np.array([5.0, -5.0, 5.0])
    moved = _weights(_plan(R2, dates))

    assert len(base) == len(moved)
    for name in NAMES:
        assert moved[-1].get(name) == pytest.approx(base[-1].get(name)), (
            f"행 t={t} 를 바꿨더니 **그 시점의 비중**이 움직였다 — 학습창이 "
            f"미래를 보고 있다({name})")


def test_changing_a_row_inside_the_training_window_does_move_the_weight():
    """★짝★ — 아무것도 반영 안 하는 구현을 배제한다.

    창 **안**(t 이전)을 바꾸면 비중은 반드시 달라져야 한다. 이 짝이 없으면 위
    테스트는 `_weights_at` 이 상수를 돌려줘도 통과한다.
    """
    n = 400
    dates = _dates(n)
    R = _returns(n)
    rb = _rebalance_indices(dates, "M", 63)
    t = rb[-1]

    base = _weights(_plan(R, dates))
    R2 = R.copy()
    R2[t - 1, :] = np.array([5.0, -5.0, 5.0])
    moved = _weights(_plan(R2, dates))

    assert any(moved[-1].get(nm) != pytest.approx(base[-1].get(nm)) for nm in NAMES), (
        "창 안을 바꿨는데 비중이 그대로다 — 이 테스트가 아무것도 재지 않는다")


def test_the_future_beyond_the_last_rebalance_never_touches_any_weight():
    """마지막 리밸런싱 **이후**의 행은 어떤 비중에도 들어가면 안 된다."""
    n = 400
    dates = _dates(n)
    R = _returns(n)
    rb = _rebalance_indices(dates, "M", 63)

    base = _weights(_plan(R, dates))
    R2 = R.copy()
    R2[rb[-1] + 1:, :] = 9.0          # 미래 전체를 말도 안 되는 값으로
    moved = _weights(_plan(R2, dates))

    assert len(base) == len(moved)
    for i, (b, m) in enumerate(zip(base, moved)):
        for name in NAMES:
            assert m.get(name) == pytest.approx(b.get(name)), (
                f"미래를 바꿨더니 {i}번째 리밸런싱 비중이 움직였다({name})")


def test_the_evidence_axis_and_this_guard_name_each_other():
    """★가드가 사라지면 배지의 근거도 사라진다★ — 서로를 가리키게 못 박는다."""
    from src.engine.allocation_evidence import window_axis
    assert window_axis()["guard"].endswith("test_allocation_walk_forward_guard.py")
