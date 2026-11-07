"""정책 백테스트의 분포 무가정 예측 구간 (M2-C)
==============================================================================
M1-T 가 `conformal.py` 를 지었지만 **프로덕션 소비자는 0건**이었다 —
`capability.py` 의 프로브 레지스트리와 자기 테스트뿐. 이 파일이 그 배선을 지킨다.

★이 기능의 정직성은 세 가지로 결정된다★
  1. 보정 표본이 모자라면 **숫자 대신 사유**를 낸다.
  2. 적중률은 이론 하한 `1-α` 를 복사하는 것이 아니라 **홀드아웃에서 세어** 낸다.
  3. 예측은 리밸런스 시점에 알 수 있는 것만 쓴다 — 구간 길이도 미래다.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.engine.allocation_backtest import walk_forward
from src.engine.conformal import required_calibration_size

NAMES = ["A", "B", "C"]


def _panel(n_days: int, seed: int = 7) -> tuple[np.ndarray, list]:
    import pandas as pd
    rng = np.random.default_rng(seed)
    R = rng.normal(0.0004, 0.011, (n_days, len(NAMES)))
    dates = list(pd.bdate_range("2019-01-02", periods=n_days))
    return R, dates


def _run(n_days: int, rebalance: str = "M", **kw) -> dict:
    R, dates = _panel(n_days)
    return walk_forward(NAMES, R, dates, model="mvo", rebalance=rebalance,
                        cost_bps=10.0, **kw)


# ── 1. ★보정 표본이 모자라면 숫자를 내지 않는다★ ───────────────────────────

# ★경계는 실측으로 잡았다★ 월 리밸런스에서 240일 → 8쌍(미달) · 280일 → 9쌍(요구치와
# 정확히 같음). 처음에는 "짧으면 skip" 으로 썼는데, 그러면 게이트를 아예 지우는 프로브에도
# 초록이 나온다 — 실패할 수 없는 가드였다. 두 표본을 **짝으로** 단언한다.
SHORT_DAYS, EXACT_DAYS = 240, 280


def test_a_short_backtest_reports_a_reason_instead_of_an_interval():
    out = _run(SHORT_DAYS)
    assert out.get("error") is not True, out.get("message")
    c = out["conformal"]
    assert c["available"] is False, f"쌍 {c['n_pairs']}개로 구간을 냈다"
    assert c["n_pairs"] < c["n_required"]
    assert c["reason"] and "보정" in c["reason"]
    assert "next_period" not in c, "구간을 못 만들었는데 구간을 냈다"


def test_the_gate_opens_exactly_at_the_required_calibration_size():
    """★짝 단언★ 미달은 막히고 요구치를 채우면 열린다 — 게이트가 진짜 게이트인지."""
    need = required_calibration_size(0.1)
    short = _run(SHORT_DAYS)["conformal"]
    exact = _run(EXACT_DAYS)["conformal"]
    assert short["n_required"] == exact["n_required"] == need
    assert short["n_pairs"] == need - 1 and short["available"] is False
    assert exact["n_pairs"] == need and exact["available"] is True


# ── 2. 충분하면 구간이 나오고, 그 구간은 점추정을 감싼다 ───────────────────

def test_a_long_backtest_produces_an_interval_around_its_point_estimate():
    c = _run(1300)["conformal"]
    assert c["available"], c.get("reason")
    n = c["next_period"]
    assert n["lower"] < n["point"] < n["upper"]
    assert n["half_width"] > 0
    assert c["unit"] == "daily_mean_return", "단위를 밝히지 않으면 숫자를 읽을 수 없다"


def test_a_tighter_alpha_widens_the_interval():
    """★자명한 방향을 먼저 고정한다★ α 가 작을수록(신뢰수준이 높을수록) 넓어야 한다."""
    from src.engine.conformal import conformal_quantile
    rng = np.random.default_rng(3)
    resid = np.abs(rng.normal(0, 1, 400))
    q10 = conformal_quantile(resid, 0.10)["q"]
    q01 = conformal_quantile(resid, 0.01)["q"]
    assert q01 > q10


# ── 3. ★적중률은 주장이 아니라 실측이다★ ──────────────────────────────────

def test_the_coverage_is_counted_on_a_holdout_not_copied_from_one_minus_alpha():
    c = _run(1300)["conformal"]
    assert c["available"], c.get("reason")
    cov = c["measured_coverage"]
    if not cov.get("available"):
        pytest.skip(f"홀드아웃 표본 부족: {cov.get('reason')}")
    # 세어서 나온 값이어야 한다 — hits/n 과 정확히 일치.
    assert cov["coverage"] == pytest.approx(cov["hits"] / cov["n"], abs=1e-12)
    assert cov["n"] >= 1 and cov["n_calibration"] >= 1
    # 유한표본에서 목표를 밑돌 수도 있다. 그 사실이 이 단언의 요점이다 —
    # `1-α` 를 그대로 복사했다면 항상 정확히 0.9 가 나온다.
    assert 0.0 <= cov["coverage"] <= 1.0


def test_coverage_absence_is_a_reason_not_a_fabricated_number():
    """홀드아웃이 없으면 `available: False` + 사유. 0 이나 0.9 를 적지 않는다."""
    out = _run(700)
    c = out["conformal"]
    if not c["available"]:
        pytest.skip("이 표본에서는 구간 자체가 안 나온다")
    cov = c["measured_coverage"]
    assert "available" in cov
    if not cov["available"]:
        assert cov.get("reason")
        assert "coverage" not in cov


# ── 4. ★예측은 미래를 쓰지 않는다★ ────────────────────────────────────────

def test_the_prediction_does_not_depend_on_the_period_length():
    """★단위를 일평균으로 맞춘 이유★

    구간 총수익으로 비교하려면 예측 시점에 "이 구간이 며칠짜리인가" 를 알아야 하는데
    그건 미래다. 일평균이면 그 값이 필요 없다. 여기서는 그 성질을 **꼬리를 잘라도
    앞부분 예측이 변하지 않는다**로 잰다 — 뒤가 바뀌어도 앞의 예측은 그대로여야 한다.
    """
    R, dates = _panel(1300)
    long_out = walk_forward(NAMES, R, dates, model="mvo", rebalance="M")
    short_out = walk_forward(NAMES, R[:900], dates[:900], model="mvo", rebalance="M")
    assert not long_out.get("error") and not short_out.get("error")
    # 앞쪽 리밸런스 날짜·비중이 동일해야 한다(같은 확장 학습창).
    a = [r["date"] for r in long_out["rebalances"][:10]]
    b = [r["date"] for r in short_out["rebalances"][:10]]
    assert a == b
    assert (long_out["rebalances"][5]["weights"]
            == short_out["rebalances"][5]["weights"])


def test_the_interval_is_reported_for_the_pending_period_not_a_completed_one():
    """마지막 리밸런스는 실현 구간이 아직 없다 — **그것이** 구간을 씌울 대상이다."""
    out = _run(1300)
    c = out["conformal"]
    assert c["available"], c.get("reason")
    assert c["n_pairs"] == out["n_rebalances"] - 1, (
        "완료된 쌍의 수가 리밸런스 수와 같다면 마지막 구간을 실현된 것으로 센 것이다")


# ── 5. 백테스트의 기존 출력은 바뀌지 않는다 ────────────────────────────────

def test_adding_conformal_does_not_change_the_backtest_itself():
    """★추가이지 변경이 아니다★ 자산곡선·지표·리밸런스가 그대로여야 한다."""
    out = _run(1300)
    assert set(out) >= {"equity_curve", "drawdown_curve", "rebalances", "metrics",
                        "summary", "config", "n_rebalances", "turnover_avg_pct"}
    assert len(out["equity_curve"]) == len(out["dates"])
    assert out["summary"]["sharpe_ratio"] is not None


def test_an_errored_backtest_has_no_conformal_claim():
    R, dates = _panel(40)
    out = walk_forward(NAMES, R, dates, model="mvo", rebalance="M")
    assert out.get("error") is True
    assert "conformal" not in out, "실패한 백테스트가 예측 구간을 냈다"
