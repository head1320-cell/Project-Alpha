"""매매 몫 결합 — 순수 함수 `src.engine.core_satellite` (구현 계획 2026-11-16 §7.5 · K4 · 설계 2026-11-17 §5).

핵심(배분 결과의 비용 후 일별 수익)과 위성(분봉 시행의 비용 후 일별 손익 ÷ 매매 몫 자본)을 사용자가 정한 국면별 매매 몫으로 합친다.
거는 것:
  · ★손 계산★ 나흘 두 달(표 30% · 10% · 국면 확률 (1, 0) → (0, 1) · 비용 10bp) — 각 걸음을 이 파일에 산수로 적는다:
    첫날 핵심에서 위성으로 옮기는 몫도 비용을 낸다 · 재조정 사이에는 두 몫이 각자 표류한다(날마다 되돌리지 않는다) ·
    둘째 달 첫날의 옮긴 몫 = |목표 − 표류한 몫| · 재조정은 그날 수익보다 먼저다(전 거래일 종가에 아는 확률로 정한 몫).
  · 몫 고정 판 = 같은 날 · 같은 재조정 날 · 같은 비용에 목표만 ★날 가중 평균 목표 몫★ — 날 수가 다른 두 달에서 달 평균과 다르다(짝).
  · 목표 몫 = Σ 확률 × 표(짝: 섞인 확률) · 표가 모두 0 이면 합친 곡선 = 핵심 곡선 · 비용이 0 이면 옮김이 곡선을 바꾸지 않는다.
  · 입력 결함은 지어내지 않고 `ValueError`(길이 · NaN · −100% 이하 · 확률 합 · 표 범위 · 몫을 정하는 날의 확률 빠짐 · 비용 범위).
반올림하지 않는다 — 보기용 반올림은 노드가 한다.
"""
from __future__ import annotations

import math

import pytest

from src.engine import core_satellite as cs

DATES = ["2026-02-26", "2026-02-27", "2026-03-02", "2026-03-03"]
CORE = [0.01, -0.02, 0.0, 0.03]          # 핵심의 비용 후 일별 수익
SAT = [0.01, 0.0, -0.005, 0.02]          # 위성의 그날 손익 ÷ 매매 몫 자본
TABLE = (0.3, 0.1)                       # 국면 1 일 때 30% · 국면 2 일 때 10%
PROBS = {0: (1.0, 0.0), 2: (0.0, 1.0)}   # 몫을 정하는 날(첫날 · 3월 첫 거래일)의 국면 확률
COST = 0.001                             # 10bp


def by_hand_regime() -> tuple[list[float], list[float], list[dict]]:
    """국면 몫 판을 손으로 — 시작 자본 1 은 모두 핵심에 있다."""
    # 2026-02-26 (몫을 정하는 날 · 국면 1 → 30%): 핵심에서 위성으로 0.3 을 옮긴다 — 비용 0.3 × 0.001
    v = 1.0 - 0.3 * 0.001                       # 0.9997
    c, s = v * 0.7, v * 0.3
    c, s = c * 1.01, s * 1.01                   # 그날 수익
    e0 = c + s                                  # 1.009697
    share0 = 0.3
    # 2026-02-27: 되돌리지 않는다 — 핵심 −2% · 위성 0
    c, s = c * 0.98, s * 1.0
    e1 = c + s
    share1 = (v * 0.3 * 1.01) / e0              # 그날 시작의 몫 = 표류한 몫(30% 가 아니다)
    # 2026-03-02 (몫을 정하는 날 · 국면 2 → 10%): 표류한 몫에서 10% 로 되돌린다 — 옮긴 몫 = |0.1 − 표류한 몫|
    drifted = s / e1
    moved = abs(0.1 - drifted)
    cost2 = moved * 0.001 * e1
    v2 = e1 - cost2
    c, s = v2 * 0.9, v2 * 0.1
    c, s = c * 1.0, s * 0.995
    e2 = c + s
    # 2026-03-03: 핵심 +3% · 위성 +2%
    share3 = s / e2
    c, s = c * 1.03, s * 1.02
    e3 = c + s
    moves = [{"i": 0, "before": 0.0, "after": 0.3, "moved": 0.3, "cost": 0.3 * 0.001},
             {"i": 2, "before": drifted, "after": 0.1, "moved": moved, "cost": cost2}]
    return [e0, e1, e2, e3], [share0, share1, 0.1, share3], moves


def by_hand_fixed() -> list[float]:
    """몫 고정 판 — 목표 = 날 가중 평균 (0.3 × 2일 + 0.1 × 2일) ÷ 4일 = 0.2 · 같은 재조정 날 · 같은 비용."""
    v = 1.0 - 0.2 * 0.001                       # 0.9998
    c, s = v * 0.8, v * 0.2
    c, s = c * 1.01, s * 1.01
    e0 = c + s                                  # 1.009798
    c, s = c * 0.98, s * 1.0
    e1 = c + s
    drifted = s / e1
    v2 = e1 - abs(0.2 - drifted) * 0.001 * e1
    c, s = v2 * 0.8, v2 * 0.2
    c, s = c * 1.0, s * 0.995
    e2 = c + s
    c, s = c * 1.03, s * 1.02
    e3 = c + s
    return [e0, e1, e2, e3]


# ── 손 계산 ─────────────────────────────────────────────────────────────────────────
def test_two_months_by_hand_the_regime_panel():
    out = cs.mix(DATES, CORE, SAT, PROBS, TABLE, COST)
    equity, share, moves = by_hand_regime()
    got = out["regime"]
    assert got["equity"][0] == pytest.approx(1.009697, rel=1e-12)          # 0.9997 × 1.01
    assert got["equity"] == pytest.approx(equity, rel=1e-12)
    assert got["share"] == pytest.approx(share, rel=1e-12)
    assert [m["i"] for m in got["moves"]] == [0, 2]
    for want, m in zip(moves, got["moves"], strict=True):
        assert m == pytest.approx(want, rel=1e-12)
    assert got["cost_total"] == pytest.approx(moves[0]["cost"] + moves[1]["cost"], rel=1e-12)
    assert got["total_return"] == pytest.approx(equity[-1] - 1.0, rel=1e-12)
    assert got["avg_share"] == pytest.approx(sum(share) / 4, rel=1e-12)


def test_the_share_drifts_between_rebalances_it_is_not_reset_every_day():
    """재조정 사이에는 몫이 표류한다 — 2월 27일 핵심 −2% · 위성 0 이면 3월 첫날 되돌리기 전의 몫은 30% 보다 크고,
    3월 2일 핵심 0 · 위성 −0.5% 면 3월 3일 시작의 몫은 10% 보다 작다(날마다 되돌리면 둘 다 목표 그대로다).
    첫날은 두 몫이 모두 +1% 라 둘째 날 시작의 몫은 30% 그대로다(짝 — 표류는 수익이 다를 때만 생긴다)."""
    out = cs.mix(DATES, CORE, SAT, PROBS, TABLE, COST)["regime"]
    assert out["share"][0] == pytest.approx(0.3, rel=1e-12) and out["share"][1] == pytest.approx(0.3, rel=1e-12)
    before = out["moves"][1]["before"]
    assert before > 0.3 and not math.isclose(before, 0.3, rel_tol=1e-9)
    assert out["share"][3] < 0.1 and not math.isclose(out["share"][3], 0.1, rel_tol=1e-9)


def test_the_first_move_from_the_core_pays_the_cost_too():
    """시작 자본은 핵심에 있다 — 첫날 위성으로 옮기는 몫(0.3)도 비용을 낸다(비용이 0 이면 첫날 값은 1.01)."""
    paid = cs.mix(DATES, CORE, SAT, PROBS, TABLE, COST)["regime"]["equity"][0]
    free = cs.mix(DATES, CORE, SAT, PROBS, TABLE, 0.0)["regime"]["equity"][0]
    assert free == pytest.approx(1.01, rel=1e-12) and paid == pytest.approx(1.01 * (1 - 0.3 * 0.001), rel=1e-12)


def test_the_rebalance_comes_before_that_days_returns():
    """재조정은 그날 장 시작 전이다 — 3월 첫날의 위성 손익(−0.5%)은 되돌린 뒤의 10% 에 붙는다."""
    out = cs.mix(DATES, CORE, SAT, PROBS, TABLE, COST)["regime"]
    after = out["moves"][1]
    e1 = out["equity"][1]
    v2 = e1 - after["cost"]
    assert out["equity"][2] == pytest.approx(v2 * 0.9 * 1.0 + v2 * 0.1 * 0.995, rel=1e-12)


def test_the_fixed_panel_holds_the_day_weighted_average_target():
    out = cs.mix(DATES, CORE, SAT, PROBS, TABLE, COST)
    assert out["fixed_share"] == pytest.approx(0.2, rel=1e-12)
    assert out["fixed"]["equity"] == pytest.approx(by_hand_fixed(), rel=1e-12)
    assert out["fixed"]["equity"][0] == pytest.approx(1.009798, rel=1e-12)     # 0.9998 × 1.01
    assert [m["after"] for m in out["fixed"]["moves"]] == pytest.approx([0.2, 0.2])
    assert [m["i"] for m in out["fixed"]["moves"]] == [0, 2]                   # 같은 재조정 날


def test_the_fixed_share_weights_days_not_months():
    """짝: 2월 하루 · 3월 사흘 — 날 가중 (0.3 × 1 + 0.1 × 3) ÷ 4 = 0.15 · 달 평균이면 0.2 가 된다."""
    dates = ["2026-02-27", "2026-03-02", "2026-03-03", "2026-03-04"]
    out = cs.mix(dates, [0.0] * 4, [0.0] * 4, {0: (1.0, 0.0), 1: (0.0, 1.0)}, TABLE, COST)
    assert out["fixed_share"] == pytest.approx(0.15, rel=1e-12)
    assert not math.isclose(out["fixed_share"], 0.2, rel_tol=1e-9)


def test_the_months_list_carries_the_probabilities_the_target_and_the_move():
    out = cs.mix(DATES, CORE, SAT, PROBS, TABLE, COST)
    _, _, moves = by_hand_regime()
    months = out["months"]
    assert [(m["i"], m["date"]) for m in months] == [(0, "2026-02-26"), (2, "2026-03-02")]
    assert [list(m["probs"]) for m in months] == [[1.0, 0.0], [0.0, 1.0]]
    assert [m["target"] for m in months] == pytest.approx([0.3, 0.1])
    assert [m["moved"] for m in months] == pytest.approx([moves[0]["moved"], moves[1]["moved"]], rel=1e-12)
    assert [m["cost"] for m in months] == pytest.approx([moves[0]["cost"], moves[1]["cost"]], rel=1e-12)


def test_drawdown_follows_the_backtest_convention_peak_of_the_curve_points():
    """낙폭 = 곡선의 점들 가운데 앞선 고점 대비(정책 백테스트와 같은 관례) · %."""
    out = cs.mix(DATES, CORE, SAT, PROBS, TABLE, COST)["regime"]
    eq = out["equity"]
    peak = [max(eq[: i + 1]) for i in range(4)]
    assert out["drawdown_pct"] == pytest.approx([(e / p - 1.0) * 100 for e, p in zip(eq, peak, strict=True)], rel=1e-12, abs=1e-12)
    assert out["max_drawdown"] == pytest.approx(min(e / p - 1.0 for e, p in zip(eq, peak, strict=True)), rel=1e-12)
    assert out["drawdown_pct"][0] == 0.0 and out["drawdown_pct"][1] < 0


# ── 목표 몫 · 짝 ─────────────────────────────────────────────────────────────────────────
def test_target_share_is_the_probability_weighted_table():
    assert cs.target_share((0.25, 0.75), (0.3, 0.1)) == pytest.approx(0.15, rel=1e-12)
    assert cs.target_share((1.0, 0.0), (0.3, 0.1)) == pytest.approx(0.3, rel=1e-12)
    assert cs.target_share((0.2, 0.3, 0.5), (0.5, 0.0, 0.2)) == pytest.approx(0.2, rel=1e-12)


def test_an_all_zero_table_leaves_the_core_curve_untouched():
    """짝: 몫이 0 이면 옮김도 비용도 없다 — 합친 곡선 = 핵심 곡선(시작 1 에서 복리)."""
    out = cs.mix(DATES, CORE, SAT, PROBS, (0.0, 0.0), COST)
    core_curve, v = [], 1.0
    for r in CORE:
        v *= 1 + r
        core_curve.append(v)
    assert out["regime"]["equity"] == pytest.approx(core_curve, rel=1e-12)
    assert out["regime"]["cost_total"] == 0.0 and out["fixed"]["equity"] == pytest.approx(core_curve, rel=1e-12)


def test_with_zero_cost_moving_does_not_change_the_value_on_the_day():
    out = cs.mix(DATES, CORE, SAT, PROBS, TABLE, 0.0)["regime"]
    assert out["cost_total"] == 0.0 and all(m["cost"] == 0.0 for m in out["moves"])


def test_month_starts_are_the_first_day_and_each_new_month():
    assert cs.month_starts(["2026-02-26", "2026-02-27", "2026-03-02", "2026-03-03", "2026-04-01"]) == [0, 2, 4]
    assert cs.month_starts(["2026-03-02"]) == [0]
    assert cs.month_starts(["2025-12-31", "2026-01-02"]) == [0, 1]           # 해가 바뀌어도 달이 바뀐다


# ── 입력 결함 — 지어내지 않는다 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("change, code", [
    (lambda a: a.update(core=CORE[:3]), "length_mismatch"),
    (lambda a: a.update(sat=[0.01, math.nan, 0.0, 0.0]), "not_finite"),
    (lambda a: a.update(core=[0.01, -1.0, 0.0, 0.0]), "return_at_or_below_minus_one"),
    (lambda a: a.update(probs={0: (0.6, 0.6), 2: (0.0, 1.0)}), "probs_not_one"),
    (lambda a: a.update(table=(1.2, 0.1)), "table_out_of_range"),
    (lambda a: a.update(table=(0.3, -0.1)), "table_out_of_range"),
    (lambda a: a.update(probs={0: (1.0, 0.0)}), "probs_missing"),
    (lambda a: a.update(probs={0: (1.0, 0.0), 2: (0.0, 1.0, 0.0)}), "probs_shape"),
    (lambda a: a.update(cost=-0.001), "cost_out_of_range"),
    (lambda a: a.update(cost=1.0), "cost_out_of_range"),
    (lambda a: a.update(dates=[]), "empty"),
])
def test_bad_inputs_are_refused_not_made_up(change, code):
    args = {"dates": DATES, "core": CORE, "sat": SAT, "probs": PROBS, "table": TABLE, "cost": COST}
    change(args)
    if args["dates"] == []:
        args.update(core=[], sat=[])
    with pytest.raises(ValueError, match=code):
        cs.mix(args["dates"], args["core"], args["sat"], args["probs"], args["table"], args["cost"])


def test_a_probability_on_a_day_that_does_not_set_the_share_is_not_needed():
    """짝: 몫을 정하는 날(첫날 · 달의 첫 거래일)의 확률만 쓴다 — 다른 날의 확률이 없어도 돈다."""
    out = cs.mix(DATES, CORE, SAT, {0: (1.0, 0.0), 2: (0.0, 1.0)}, TABLE, COST)
    assert len(out["regime"]["equity"]) == 4
