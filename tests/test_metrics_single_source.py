"""지표 단일 출처 이전 — ★값은 그대로, 출처는 하나로★ (P1)
==============================================================================
설계: `docs/specs/2026-08-30-macro-to-portfolio-architecture-review.md` §2 W1 · §6 P1

`allocation_backtest` 는 `compute_metrics()` 를 부른 **바로 다음 줄에서**
sharpe·sortino·calmar 를 인라인으로 다시 계산했다 — 같은 함수 안에 지표가 두
벌이었고, 그것이 관례가 갈라진 지점이다.

★이전은 값을 바꾸지 않는다★ 인라인 공식과 단일 출처의 공식이 대수적으로 동일하고
관례(`_RF=0.035`·`ddof=1`)도 같기 때문이다. 아래 골든이 그것을 못 박는다 — 값이
바뀌면 그것은 **의도하지 않은 변경**이므로 시끄럽게 실패해야 한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(scope="module")
def summary():
    from scripts.t3_transmission import build_panel

    from src.engine.allocation_backtest import walk_forward
    names, R, dates, _p, _b = build_panel(months=36)
    return walk_forward(names, R, dates, model="bl", rebalance="M",
                        min_train=252, cost_bps=10.0)["summary"]


#: ★골든★ 이전 **전**에 실측한 값. 이전은 값을 바꾸지 않아야 한다.
GOLDEN = {"sharpe_ratio": 0.56, "sortino_ratio": 0.92, "calmar_ratio": 0.86,
          "cagr_pct": 10.63, "volatility_pct": 13.45,
          "max_drawdown_pct": -12.9, "total_return_pct": 21.99}


@pytest.mark.parametrize("key", sorted(GOLDEN))
def test_the_migration_did_not_change_any_number(summary, key):
    assert summary[key] == GOLDEN[key]


def test_the_summary_now_declares_the_convention_that_made_it(summary):
    """★그 수를 만든 관례를 달고 다녀야 한다★ — 두 리포트를 비교하려면 필요하다."""
    c = summary["convention"]
    assert c["risk_free"] == 0.035
    assert c["ddof"] == 1
    assert c["periods_per_year"] == 252
    assert c["annualization"] == "arithmetic"


def test_the_summary_carries_a_full_precision_sharpe(summary):
    """★A3 에서 물린 것★ 표시용 `round(_,2)` 옆에 전정밀도를 함께 싣는다."""
    full = summary["sharpe_ratio_full"]
    assert full is not None
    assert round(full, 2) == summary["sharpe_ratio"]
    assert full != summary["sharpe_ratio"], "전정밀도가 반올림값과 같다 — 의심스럽다"


def test_the_backtest_no_longer_computes_ratios_inline():
    """★두 벌이 다시 생기는 것을 막는다★

    소스 텍스트가 아니라 **동작**을 보는 것이 원칙이지만, 여기서 막으려는 결함이
    정확히 "같은 함수 안에서 다시 계산한다" 라는 **구조**다. 인라인 공식이
    되살아나면 관례가 다시 갈라진다.
    """
    import inspect

    from src.engine.allocation_backtest import (
        plan_walk_forward,
        simulate_walk_forward,
        walk_forward,
    )
    # ★P7 이후 지표는 시뮬레이션 단계에 산다★ `walk_forward` 는 계획→시뮬 합성이라
    # 얇다. 이 가드가 지켜야 할 것은 "어느 함수에 있는가" 가 아니라 "인라인 공식이
    # 되살아나지 않았는가" 이므로 **세 함수 전부**를 본다.
    src = "".join(inspect.getsource(f) for f in
                  (walk_forward, plan_walk_forward, simulate_walk_forward))
    assert "(ann - _RF) / vol" not in src
    assert "(ann - _RF) / dvol" not in src
    assert "metrics[\"sharpe_ratio\"]" in src
    # ★그리고 계획 단계에는 지표가 아예 없어야 한다★ (P7 경계)
    assert "compute_metrics" not in inspect.getsource(plan_walk_forward)


# ══════════════════════════════════════════════════════════════════════════
# ★다른 엔진도 이전됐다 — 관례는 여전히 다르지만 이제 **신고된다**★
# ══════════════════════════════════════════════════════════════════════════
def test_the_other_engine_no_longer_defines_its_own_risk_free():
    """★P1 이 남긴 트립와이어가 제 일을 했다★

    이 테스트는 원래 "`rf_daily = 0.025 / 252` 가 아직 있다" 를 못 박아 두고
    "누군가 이 파일을 손대면 알려 준다" 고 적혀 있었다. P4 잔여 작업에서 그
    이전을 실제로 했으므로, 이제 **이전됐다는 사실**을 못 박는다.

    ★관례가 통일된 것이 아니다★ — 이 엔진은 여전히 `rf=0.025`·`ddof=0`·기하
    연율화를 쓴다(그래서 값이 안 바뀌었다). 달라진 것은 그 관례가 코드에 숨어
    있지 않고 산출과 함께 **신고된다**는 점이다.
    """
    import pathlib
    src = pathlib.Path("src/engine/multi_strategy_backtest.py").read_text(
        encoding="utf-8")
    assert "rf_daily = 0.025 / 252" not in src
    assert "risk_adjusted_ratios" in src


def test_the_two_engines_declare_different_conventions_on_purpose():
    """★짝★ 이전이 관례를 조용히 통일해 버렸다면 값이 바뀌었을 것이다."""
    import numpy as _np

    from src.engine.quant_metrics import risk_adjusted_ratios
    r = _np.array([0.01, -0.02, 0.03, 0.005, -0.001])
    eq = 100.0 * _np.cumprod(1 + r)
    alloc = risk_adjusted_ratios(r, eq, risk_free=0.035, ddof=1)
    multi = risk_adjusted_ratios(r, eq, risk_free=0.025, ddof=0,
                                 annualization="geometric", starting_equity=100.0)
    assert alloc["convention"]["risk_free"] != multi["convention"]["risk_free"]
    assert alloc["convention"]["annualization"] != multi["convention"]["annualization"]
    assert alloc["sharpe_ratio"] != multi["sharpe_ratio"]


def test_the_dominant_convention_is_what_the_migrated_path_uses():
    """지배 관례(0.035)와 이전된 경로의 관례가 같아야 한다."""
    from src.engine.allocation_backtest import _RF
    from src.engine.quant_metrics import DEFAULT_RISK_FREE
    assert _RF == DEFAULT_RISK_FREE == 0.035


# ══════════════════════════════════════════════════════════════════════════
# 연구 관문 경로
# ══════════════════════════════════════════════════════════════════════════
def test_the_research_gate_delegates_to_the_single_source():
    """`regime_control._sharpe` 가 공식을 직접 들고 있지 않아야 한다."""
    import inspect

    from scripts.regime_control import GATE_RISK_FREE, _sharpe
    assert GATE_RISK_FREE == 0.0
    src = inspect.getsource(_sharpe)
    assert "risk_adjusted_ratios" in src
    assert "np.sqrt(252" not in src, "공식이 아직 여기 남아 있다"


def test_the_research_gate_sharpe_is_unchanged_by_the_migration():
    """★골든★ A3·M7 의 측정이 이 수 위에 서 있다 — 바뀌면 안 된다."""
    from scripts.regime_control import _sharpe
    d = np.random.default_rng(0).normal(0.0004, 0.01, 1260)
    want = round(float(d.mean() / d.std(ddof=1) * np.sqrt(252.0)), 8)
    assert _sharpe(d) == want


def test_the_gate_risk_free_choice_cannot_change_a_difference():
    """★이 관문이 무위험 0 을 쓸 수 있는 이유★ — 주 통계가 **차이**이기 때문이다.

    공통 무위험은 두 팔에서 상쇄되므로 `sharpe_diff` 는 rf 선택에 불변이다.
    이것이 성립하지 않으면 관례 선택이 판정을 바꾼다.
    """
    from src.engine.quant_metrics import risk_adjusted_ratios
    rng = np.random.default_rng(1)
    a, b = rng.normal(0.0005, 0.01, 900), rng.normal(0.0003, 0.01, 900)

    def diff(rf):
        return (risk_adjusted_ratios(a, [], risk_free=rf)["sharpe_ratio"]
                - risk_adjusted_ratios(b, [], risk_free=rf)["sharpe_ratio"])

    # ★변동성이 다르면 완전 상쇄는 아니다★ 그래서 "정확히 같다" 로 걸 수 없고,
    # 걸어야 할 것은 "영향이 판정을 흔들 만큼 크지 않다" 다.
    # (처음에 `... or True` 를 붙인 단언을 하나 썼다가 지웠다 — 그것은 무엇도
    #  검사하지 않는다. 공허한 단언은 계약이 아니다.)
    delta = abs(diff(0.0) - diff(0.035))
    assert delta < 0.05, "무위험 선택이 sharpe_diff 를 크게 바꾼다 — 관례가 판정을 흔든다"
    assert delta > 0, "완전히 불변이면 이 테스트가 아무것도 확인하지 않는다"
