"""walk-forward 국면 조건부 훅 — ★절단 경로만 본다★ (MS1-b0)
==============================================================================
계획: `docs/plans/2026-08-25-macro-vnext-plan.md` §1.13 · 검증계획 §6 B0-2

B0/B1/N 세 팔을 **같은 엔진**으로 돌리기 위한 훅이다. 그런데 백테스트에서
국면을 쓰는 순간 look-ahead 가 들어올 자리가 생긴다 — `_regime_path_for` 는
**오늘** 기준 경로를 주므로, 그것을 2020년 리밸런싱에 쓰면 미래를 보는 것이다.

★그래서 이 파일의 절반은 "절단이 실제로 일어나는가" 를 잰다.★
`s_override is None`(B0) · 경로 길이가 시점에 따라 **늘어난다**(N) ·
마지막 시점의 경로가 전체 경로보다 **짧다** — 셋을 못 박지 않으면
"walk-forward 인 척하는 in-sample" 이 조용히 통과한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from src.engine.allocation_backtest import walk_forward  # noqa: E402

NAMES = ["A", "B", "C"]
REG_A, REG_B = "Goldilocks", "Stagflation"


def _panel(months: int = 60, seed: int = 11):
    """월별로 국면이 번갈아 바뀌는 일별 수익률 + 그 경로."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-02", periods=months * 21, freq="C")
    beta = np.array([1.2, 0.9, 0.6])
    rows, points, seen = [], [], []
    for ts in idx:
        mo = ts.strftime("%Y-%m")
        if mo not in seen:
            seen.append(mo)
        reg = REG_A if (len(seen) - 1) % 2 == 0 else REG_B
        if reg == REG_A:
            f = rng.normal(0.0007, 0.013)
            rows.append(f * beta + rng.normal(0.0, 0.004, 3))
        else:
            rows.append(rng.normal(-0.0005, 0.012, 3))
    for i, mo in enumerate(seen):
        points.append({"t": mo, "growth": 0.1, "inflation": 0.1,
                       "regime": REG_A if i % 2 == 0 else REG_B})
    return np.array(rows), list(idx), points


def _run(regime=None, **kw):
    R, dates, points = _panel()
    if regime is not None:
        regime = {"points": points, **regime}
    return walk_forward(NAMES, R, dates, model="bl", rebalance="M",
                        cost_bps=kw.pop("cost_bps", 10.0), regime=regime, **kw)


# ══════════════════════════════════════════════════════════════════════════
# 세 팔이 돌고, 서로 다르다
# ══════════════════════════════════════════════════════════════════════════
def test_three_arms_all_run():
    for regime in (None, {"weighting": "hard"}, {"weighting": "probabilistic"}):
        out = _run(regime)
        assert not out.get("error"), out.get("message")
        assert len(out["rebalances"]) > 5


def test_arms_produce_different_weight_paths():
    """★B0 ≠ B1 ≠ N★ — 같으면 훅이 닿지 않았거나 표본이 국면을 구분 못 한다."""
    b0 = _run(None)
    b1 = _run({"weighting": "hard"})
    nn = _run({"weighting": "probabilistic"})

    def w_of(o):
        return [rb["weights"] for rb in o["rebalances"]]

    assert w_of(b0) != w_of(b1), "국면 배선이 비중에 닿지 않았다 (B0 == B1)"
    assert w_of(b1) != w_of(nn), "확률 혼합이 하드 라벨과 같다 (B1 == N)"


# ══════════════════════════════════════════════════════════════════════════
# ★look-ahead 방지 — 이 묶음이 이 파일의 존재 이유★
# ══════════════════════════════════════════════════════════════════════════
def test_b0_never_applies_a_regime_override():
    """B0 팔은 국면 배선이 **꺼져 있어야** 한다."""
    out = _run(None)
    assert out["regime_audit"]["arm"] == "B0"
    assert out["regime_audit"]["s_override_used"] == 0


def test_conditioned_arms_do_apply_the_override():
    """짝 — 켠 팔에서는 실제로 적용돼야 한다(가드가 전부를 막지 않도록)."""
    for weighting in ("hard", "probabilistic"):
        out = _run({"weighting": weighting})
        aud = out["regime_audit"]
        assert aud["s_override_used"] > 0, f"{weighting}: Σ 가 한 번도 안 바뀌었다"


@pytest.mark.parametrize("weighting", ["hard", "probabilistic"])
def test_path_is_truncated_and_grows_with_time(weighting):
    """★절단이 실제로 일어난다★ 각 리밸런싱이 쓴 경로 길이가 **단조 증가**하고,
    마지막 시점조차 전체 경로보다 짧거나 같다.

    전체 경로를 매번 쓰는 구현이면 길이가 **상수**로 나와 여기서 죽는다.
    """
    _, _, points = _panel()
    out = _run({"weighting": weighting})
    lens = out["regime_audit"]["path_len_at_rebalance"]

    assert len(lens) >= 5
    assert lens == sorted(lens), f"경로 길이가 단조 증가하지 않는다: {lens[:10]}"
    assert lens[0] < lens[-1], "경로가 시점에 따라 자라지 않는다 — 절단이 없다"
    assert lens[-1] <= len(points), "마지막 시점이 전체 경로보다 길다 — 미래를 봤다"
    assert len(set(lens)) > 1, "모든 시점이 같은 길이를 썼다 — 전체 경로를 쓴 것이다"


@pytest.mark.parametrize("weighting", ["hard", "probabilistic"])
def test_future_months_never_enter_the_path(weighting):
    """리밸런싱 시점의 달보다 **뒤에 있는** 달이 경로에 들어가면 안 된다."""
    out = _run({"weighting": weighting})
    for rb in out["regime_audit"]["detail"]:
        assert rb["last_path_month"] <= rb["month"], (
            f"{rb['month']} 리밸런싱이 {rb['last_path_month']} 를 봤다")


def test_appending_future_points_does_not_change_the_result():
    """★가장 강한 look-ahead 검사★ 경로 **뒤에** 미래 달을 덧붙여도 결과가 같다.

    미래를 쓰고 있다면 이 두 결과가 달라진다.
    """
    R, dates, points = _panel()
    base = walk_forward(NAMES, R, dates, model="bl", rebalance="M",
                        regime={"points": points, "weighting": "probabilistic"})
    future = points + [{"t": "2099-01", "growth": 9.0, "inflation": -9.0,
                        "regime": REG_B},
                       {"t": "2099-02", "growth": -9.0, "inflation": 9.0,
                        "regime": REG_A}]
    with_future = walk_forward(NAMES, R, dates, model="bl", rebalance="M",
                               regime={"points": future,
                                       "weighting": "probabilistic"})
    assert [r["weights"] for r in base["rebalances"]] == \
           [r["weights"] for r in with_future["rebalances"]]


# ══════════════════════════════════════════════════════════════════════════
# 실패는 조용하지 않다
# ══════════════════════════════════════════════════════════════════════════
def test_audit_counts_line_up():
    out = _run({"weighting": "probabilistic"})
    aud = out["regime_audit"]
    assert aud["n_rebalances"] == len(out["rebalances"])
    assert aud["s_override_used"] <= aud["n_rebalances"]
    assert len(aud["detail"]) == aud["n_rebalances"]


@pytest.mark.parametrize("weighting", ["hard", "probabilistic"])
def test_thin_regime_sample_is_reported_with_a_reason(weighting):
    """★표본이 얇아 조건부를 못 만든 시점은 **사유와 함께** 남는다★

    ★이 테스트는 한 번 헛돌았다★ 처음에는 기본 fixture 로 `all(d["reason"] …)` 을
    걸었는데, 그 fixture 에서는 미적용 시점이 **0개**라 `all([])` 이 공허하게 참이
    됐다 — 사유를 지우는 변이가 살아남았다. 그래서 여기서는 **미적용이 반드시
    생기는** fixture 를 만들고, 먼저 그 개수가 0이 아님을 단언한다.

    자산 12개면 하한이 `ceil(3.0 × 12) = 36행` 인데 한 달은 21영업일뿐이라,
    현재 국면의 라벨 월이 하나뿐인 시점은 반드시 실패한다.
    """
    rng = np.random.default_rng(3)
    names = [f"S{i:02d}" for i in range(12)]
    months = 30
    idx = pd.bdate_range("2019-01-02", periods=months * 21, freq="C")
    R = rng.normal(0.0, 0.01, size=(len(idx), len(names)))
    seen: list[str] = []
    for ts in idx:
        mo = ts.strftime("%Y-%m")
        if mo not in seen:
            seen.append(mo)
    # ★국면이 매달 바뀌되 대부분 유일하다★ — 현재 국면의 표본이 늘 한 달뿐이다.
    points = [{"t": mo, "growth": 0.1, "inflation": 0.1, "regime": f"R{i:02d}"}
              for i, mo in enumerate(seen)]

    out = walk_forward(names, R, list(idx), model="bl", rebalance="M",
                       regime={"points": points, "weighting": weighting})
    aud = out["regime_audit"]
    skipped = [d for d in aud["detail"] if not d["applied"]]

    assert skipped, "미적용 시점이 하나도 없다 — 이 테스트는 공허하다"
    assert all(d["reason"] for d in skipped), \
        f"사유 없는 미적용: {[d for d in skipped if not d['reason']][:2]}"


def test_unknown_weighting_is_refused():
    out = _run({"weighting": "smoothed"})
    assert out.get("error") is True
    assert "smoothed" in out["message"] or "가중" in out["message"]


def test_regime_audit_is_absent_when_hook_unused():
    """훅을 안 쓰면 B0 로 기록되고 상세는 비어 있다 — 없는 척하지 않는다."""
    out = _run(None)
    assert out["regime_audit"]["arm"] == "B0"
    assert out["regime_audit"]["detail"] == []
