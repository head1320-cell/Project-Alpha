"""순차 증거(e-값) — 손실 상한을 둔 베팅 e-과정 (묶음 G · G1).

계약(구현 계획 §2): 하루 손익 x 를 상한 c 에서 잘라 r = max(x, −c)/c 로 두고 E_t = 평균_f ∏(1 + f·r_i), f ∈ {0.05 … 0.95}.
"잘라낸 하루 손익의 기댓값이 0 이하"라는 가설 아래 ★어느 날에 멈춰도★ E_t ≥ 1/α 일 확률이 α 이하다(분포 가정 없음).
★이 시험들이 재는 것은 도구의 통계 성질이다 — 어떤 규칙의 가치도 말하지 않는다.★
"""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from src.engine import evalue

CAP = 10_000.0


def e_of(values, **kw):
    return evalue.evidence(values, cap=kw.pop("cap", CAP), **kw)


# ── 손 계산 ────────────────────────────────────────────────────────────────────

def test_the_grid_is_the_declared_one_and_never_bets_everything():
    assert evalue.FRACTIONS == tuple(k / 20 for k in range(1, 20))
    assert 0 < min(evalue.FRACTIONS) and max(evalue.FRACTIONS) < 1          # 1 이면 상한만큼 잃은 날에 0 이 된다


@pytest.mark.parametrize("r", [1.0, 0.4, 0.0, -0.4, -1.0])
def test_one_day_is_one_plus_half_the_capped_return(r):
    out = e_of([r * CAP])
    assert out["e_value"] == pytest.approx(1 + 0.5 * r) and out["peak"] == pytest.approx(max(1.0, 1 + 0.5 * r))
    assert out["days"] == 1 and out["cap"] == CAP and out["reason"] is None


@pytest.mark.parametrize("r1,r2", [(1.0, 1.0), (1.0, -1.0), (0.5, 0.2), (-0.3, -0.7)])
def test_two_days_match_the_hand_formula(r1, r2):
    """격자의 평균은 0.5 · 제곱 평균은 0.325 → 1 + 0.5(r₁+r₂) + 0.325 r₁r₂."""
    out = e_of([r1 * CAP, r2 * CAP])
    assert out["e_value"] == pytest.approx(1 + 0.5 * (r1 + r2) + 0.325 * r1 * r2)


def test_the_value_does_not_depend_on_the_unit_of_money():
    won = e_of([3_000.0, -2_000.0, 5_000.0], cap=10_000.0)
    thousand = e_of([3.0, -2.0, 5.0], cap=10.0)
    assert won["e_value"] == pytest.approx(thousand["e_value"]) and won["peak"] == pytest.approx(thousand["peak"])


def test_the_peak_is_kept_after_the_value_falls_back():
    out = e_of([CAP, CAP, CAP, -CAP, -CAP, -CAP])
    assert out["peak"] == pytest.approx(e_of([CAP, CAP, CAP])["e_value"])
    assert out["e_value"] < out["peak"]                                     # 넘은 적이 있다는 사실은 그 뒤에 내려와도 남는다


def test_nothing_looks_ahead__adding_days_does_not_change_the_earlier_path():
    values = [1200.0, -800.0, 0.0, 4000.0, -9000.0, 300.0, 2500.0]
    whole = evalue.log_path(values, CAP)
    for k in range(1, len(values)):
        assert whole[:k] == pytest.approx(evalue.log_path(values[:k], CAP))


# ── 상한: 자르고 · 세고 · 통과시키지 않는다 ─────────────────────────────────────

def test_a_loss_beyond_the_cap_is_cut_at_the_cap_and_counted():
    inside = e_of([-CAP])
    beyond = e_of([-3 * CAP])
    assert beyond["e_value"] == pytest.approx(inside["e_value"])            # 계산은 상한에서 자른 값으로
    assert inside["exceeded_days"] == 0 and beyond["exceeded_days"] == 1
    assert beyond["worst"] == -3 * CAP and inside["worst"] == -CAP


def test_a_day_exactly_at_the_cap_is_not_an_exceedance():
    assert e_of([-CAP, -CAP + 1])["exceeded_days"] == 0
    assert e_of([-CAP - 1])["exceeded_days"] == 1


def test_evidence_with_an_exceeded_cap_never_passes__and_says_why():
    """상한을 넘은 날이 있으면 '잘라낸 손익'의 증거가 실제 손익의 증거가 아니다 — 통과가 아니다(짝: 넘은 날이 없으면 통과)."""
    winning = [0.9 * CAP] * 30
    clean = e_of(winning)
    broken = e_of([*winning, -5 * CAP])
    assert clean["passed"] is True and clean["reason"] is None
    assert broken["peak"] >= broken["threshold"]                           # 숫자는 기준을 넘었다
    assert broken["passed"] is False and broken["reason"] == evalue.REASONS["cap_exceeded"]


def test_every_available_value_carries_the_assumption():
    for values in ([100.0], [0.9 * CAP] * 30, [-5 * CAP]):
        out = e_of(values)
        assert out["e_value"] is not None and out["assumption"] == evalue.ASSUMPTION


# ── 시행 횟수 ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("trials,want", [(1, 20.0), (3, 60.0), (10, 200.0)])
def test_the_threshold_is_the_number_of_trials_over_alpha(trials, want):
    assert e_of([0.0], trials=trials)["threshold"] == pytest.approx(want)


def test_the_same_flow_stops_passing_when_more_trials_were_made():
    flow = [0.9 * CAP] * 7                                                  # 손 계산: 평균_f (1 + 0.9 f)^7 ≈ 22.4
    one, many = e_of(flow, trials=1), e_of(flow, trials=2)
    assert one["peak"] == pytest.approx(22.369, abs=1e-3)
    assert one["passed"] is True and many["passed"] is False               # 같은 흐름 · 같은 값 · 기준만 올랐다
    assert one["e_value"] == pytest.approx(many["e_value"]) and many["reason"] is None


@pytest.mark.parametrize("kw", [{"trials": 0}, {"trials": -2}, {"alpha": 0.0}, {"alpha": 1.0}, {"alpha": float("nan")}])
def test_a_meaningless_trial_count_or_level_is_an_error_not_a_quiet_default(kw):
    """시행 0회를 1회로 고쳐 계산하면 기준이 조용히 낮아진다 — 부르는 쪽의 결함은 결함으로 드러낸다(값이 없을 때도)."""
    for values in ([100.0], None):
        with pytest.raises(ValueError):
            evalue.evidence(values, cap=CAP, **kw)


def test_a_flat_or_losing_flow_does_not_pass():
    assert e_of([0.0] * 50)["passed"] is False and e_of([0.0] * 50)["e_value"] == pytest.approx(1.0)
    losing = e_of([-0.5 * CAP] * 200)                                       # 손 계산 ≈ 3.3e-4
    assert losing["passed"] is False and losing["e_value"] < 1e-3 and losing["peak"] == pytest.approx(1.0)


# ── 값이 없을 때 — 1 이나 0 으로 내지 않는다 ────────────────────────────────────

@pytest.mark.parametrize("values,cap,code", [
    (None, CAP, "no_values"), ([], CAP, "no_days"), ([1.0, 2.0], None, "no_cap"), ([1.0], 0.0, "no_cap"), ([1.0], -5.0, "no_cap"),
    ([1.0, float("nan")], CAP, "bad_values"), ([1.0, float("inf")], CAP, "bad_values"), ([1.0], float("nan"), "no_cap"),
])
def test_what_cannot_be_computed_is_absent_with_a_reason(values, cap, code):
    out = evalue.evidence(values, cap=cap)
    assert out["e_value"] is None and out["peak"] is None and out["passed"] is None
    assert out["reason"] == evalue.REASONS[code] and out["assumption"] is None
    assert out["threshold"] == pytest.approx(20.0)                           # 기준은 값이 없어도 말한다


def test_a_huge_value_is_reported_as_a_finite_number_and_marked():
    out = e_of([50 * CAP] * 400)
    assert math.isfinite(out["e_value"]) and math.isfinite(out["peak"]) and out["saturated"] is True
    assert out["e_value"] == evalue.SATURATION
    json.dumps(out, allow_nan=False)                                        # 답에 inf · nan 이 없다
    assert e_of([CAP] * 5)["saturated"] is False


# ── ★언제 멈춰도★ — 귀무 아래 한 번이라도 기준을 넘을 확률 ≤ α ──────────────────

PATHS, DAYS = 2000, 250
SLACK = 3 * math.sqrt(0.05 * 0.95 / PATHS)                                  # 모의 오차(3σ)


def crossing_rate(X: np.ndarray, cap: float, trials: int = 1) -> tuple[float, float]:
    """(기준을 한 번이라도 넘은 경로의 비율, 그 가운데 상한을 넘은 날이 없던 경로의 비율)."""
    hit = clean = 0
    for row in X:
        out = evalue.evidence(row.tolist(), cap=cap, trials=trials)
        crossed = out["peak"] >= out["threshold"]
        hit += crossed
        clean += bool(out["passed"])
    return hit / len(X), clean / len(X)


def nulls(rng) -> dict[str, tuple[np.ndarray, float]]:
    """평균 0 인 하루 손익의 분포 다섯과 그 손실을 덮는 상한."""
    shape = (PATHS, DAYS)
    heavy = np.clip(rng.standard_t(3, shape), -6.0, None)
    heavy = heavy - heavy.mean()                                           # 자른 뒤의 표본 평균을 0 에 맞춘다(귀무의 경계)
    return {
        "정규": (np.clip(rng.standard_normal(shape), -4.0, None), 4.0),
        "두꺼운 꼬리": (heavy, 8.0),
        "0 이 섞인 것": (np.where(rng.random(shape) < 0.7, 0.0, np.clip(rng.standard_normal(shape), -4.0, None)), 4.0),
        "드물게 크게 번다": (np.where(rng.random(shape) < 0.9, -1.0, 9.0), 1.0),
        "드물게 크게 잃는다": (np.where(rng.random(shape) < 0.9, 1.0, -9.0), 9.0),
    }


def test_under_no_edge_the_threshold_is_rarely_ever_crossed__whatever_the_shape():
    """★분포의 꼴을 가리지 않는다★ — 자주 조금 벌고 드물게 크게 잃는 꼴에서도(대칭 가정의 통계량은 여기서 22~25% 였다 · 계획 §2.0)."""
    rng = np.random.default_rng(20261116)
    for name, (X, cap) in nulls(rng).items():
        rate, _ = crossing_rate(X, cap)
        assert rate <= evalue.ALPHA + SLACK, f"{name}: {rate:.3%}"


def test_under_no_edge_more_trials_only_make_crossing_rarer():
    X, cap = nulls(np.random.default_rng(7))["드물게 크게 잃는다"]
    one, _ = crossing_rate(X[:800], cap, trials=1)
    five, _ = crossing_rate(X[:800], cap, trials=5)
    assert five <= one and five <= evalue.ALPHA / 5 + 3 * math.sqrt(0.01 * 0.99 / 800)


def test_with_a_real_edge_the_threshold_is_crossed():
    """짝 — 늘 거부하는 장치가 아니다: 일 샤프 0.3 · 상한 4σ 면 250일 안에 대부분 넘는다."""
    rng = np.random.default_rng(3)
    X = np.clip(rng.standard_normal((400, DAYS)) + 0.3, -4.0, None)
    rate, clean = crossing_rate(X, 4.0)
    assert rate >= 0.9 and clean >= 0.9


def test_when_losses_break_the_cap_the_number_inflates_but_the_days_are_counted_and_nothing_passes():
    """상한 가정이 틀린 세계(평균 0 · 손실 −9 · 상한 3): 숫자는 부푼다 — 그러나 넘은 날이 세어져 통과가 아니다.
    ★한계★: 그 손실을 표본 안에서 보기 전에는 도구가 알 수 없다(문장 `ASSUMPTION` 이 늘 붙는 까닭)."""
    rng = np.random.default_rng(11)
    X = np.where(rng.random((400, DAYS)) < 0.9, 1.0, -9.0)
    rate, clean = crossing_rate(X, 3.0)
    assert rate > 0.5                                                       # 가정이 틀리면 오류율 보장은 없다
    assert clean <= evalue.ALPHA                                           # 상한을 넘은 날이 보인 경로는 통과가 아니다


# ── 부호(G2 · 괴리 보고) — 짝마다 +1 · −1 · 0 의 순차 증거 ──────────────────────────
# 계약(구현 계획 §3): s_i ∈ {−1, 0, +1} 은 그 자체로 [−1, 1] 에 갇혀 상한 가정이 필요 없다 → E_n = 평균_f ∏(1 + f·s_i)(같은 격자).
# 가설 "짝마다 그때까지를 알고도 E[s | 과거] ≤ 0"(불리할 확률이 유리할 확률보다 크지 않다) 아래 어느 짝에서 멈춰도 E ≥ 1/α 일 확률 ≤ α.

def test_signs_run_on_the_same_engine_as_capped_values_with_cap_one():
    """새 엔진을 만들지 않는다 — `log_path(signs, 1)` 그대로다."""
    signs = [1, -1, 0, 1, 1, -1, 0, 1]
    out = evalue.sign_evidence(signs)
    assert math.log(out["e_value"]) == pytest.approx(evalue.log_path(signs, 1.0)[-1])
    assert out["method"] == evalue.SIGN_METHOD and out["method"] != evalue.METHOD


@pytest.mark.parametrize("signs,e,peak", [
    ([1], 1.5, 1.5),                    # 1 + 평균 f
    ([-1], 0.5, 1.0),                   # 1 − 평균 f · 최고값은 시작값 1
    ([0], 1.0, 1.0),                    # 같은 체결은 곱에 1 — 정보가 없다
    ([1, 1], 2.325, 2.325),             # 1 + 2·0.5 + 0.325
    ([1, -1], 0.675, 1.5),              # 1 − 평균 f² = 1 − 0.325
    ([1, -1, 1], 0.9375, 1.5),          # 1 + 0.5 − 0.325 − 평균 f³(0.2375)
])
def test_hand_computed_signs(signs, e, peak):
    out = evalue.sign_evidence(signs)
    assert out["e_value"] == pytest.approx(e) and out["peak"] == pytest.approx(peak)
    assert out["pairs"] == len(signs) and out["reason"] is None


def test_the_counts_are_the_signs_and_even_pairs_change_nothing():
    """같은 체결(0)은 곱에 1 이다 — 붙여도 값이 그대로다(짝: 같은 자리에 +1 을 붙이면 값이 오른다)."""
    plain, padded = evalue.sign_evidence([1, -1, 1]), evalue.sign_evidence([1, 0, -1, 0, 0, 1])
    assert padded["e_value"] == pytest.approx(plain["e_value"]) and padded["peak"] == pytest.approx(plain["peak"])
    assert (padded["adverse"], padded["favorable"], padded["even"], padded["pairs"]) == (2, 1, 3, 6)
    assert evalue.sign_evidence([1, 1, -1, 1])["e_value"] > plain["e_value"]


def test_the_threshold_is_one_over_alpha_at_the_boundary():
    """불리 여섯 = 17.43(미달) ↔ 일곱 = 30.25(통과) — 기준이 20 이다(두 배면 일곱도 미달)."""
    six, seven = evalue.sign_evidence([1] * 6), evalue.sign_evidence([1] * 7)
    assert six["threshold"] == pytest.approx(20.0) and six["alpha"] == evalue.ALPHA
    assert six["peak"] == pytest.approx(17.428, abs=1e-3) and six["passed"] is False
    assert seven["peak"] == pytest.approx(30.2546, abs=1e-3) and seven["passed"] is True
    assert evalue.sign_evidence([1] * 7, alpha=0.025)["passed"] is False           # 기준 40


def test_crossing_once_is_kept_even_when_later_pairs_bring_the_value_down():
    """판정은 최고값으로 한다 — '어느 짝에서든 넘을 확률'이 α 이하라 넘은 사실은 그 뒤에 내려와도 남는다."""
    out = evalue.sign_evidence([1] * 7 + [-1] * 7)
    assert out["e_value"] < 1.0 and out["peak"] == pytest.approx(30.2546, abs=1e-3) and out["passed"] is True


def test_the_order_of_pairs_is_the_evidence__reversed_it_does_not_cross():
    """곱은 순서와 무관하지만 지나온 길(최고값)은 순서를 탄다 — 짝은 시각 순이어야 한다."""
    forward, backward = evalue.sign_evidence([1] * 7 + [-1] * 7), evalue.sign_evidence([-1] * 7 + [1] * 7)
    assert forward["e_value"] == pytest.approx(backward["e_value"])
    assert forward["passed"] is True and backward["passed"] is False and backward["peak"] == pytest.approx(1.0)


def test_a_huge_sign_value_is_finite_and_marked():
    out = evalue.sign_evidence([1] * 400)
    assert out["saturated"] is True and out["e_value"] == evalue.SATURATION
    json.dumps(out, allow_nan=False)
    assert evalue.sign_evidence([1] * 7)["saturated"] is False


def test_no_signs_is_absent_with_a_reason_not_one():
    out = evalue.sign_evidence([])
    assert out["e_value"] is None and out["peak"] is None and out["passed"] is None
    assert out["reason"] == evalue.REASONS["no_signs"] and out["pairs"] == 0 and out["threshold"] == pytest.approx(20.0)


@pytest.mark.parametrize("bad", [[2], [1, 0.5], [float("nan")], [-3, 1], [1, None]])
def test_a_value_that_is_not_a_sign_is_the_callers_defect(bad):
    """크기를 부호로 몰래 바꾸지 않는다 — 부르는 쪽이 부호를 넘겨야 한다."""
    with pytest.raises(ValueError):
        evalue.sign_evidence(bad)


@pytest.mark.parametrize("alpha", [0.0, 1.0, float("nan"), -0.1])
def test_a_meaningless_level_is_an_error(alpha):
    with pytest.raises(ValueError):
        evalue.sign_evidence([1, -1], alpha=alpha)


PAIRS = 300


def sign_crossing_rate(S: np.ndarray) -> float:
    return sum(bool(evalue.sign_evidence(row.tolist())["passed"]) for row in S) / len(S)


def sign_nulls(rng) -> dict[str, np.ndarray]:
    """불리할 확률이 유리할 확률보다 크지 않은 세계 넷(★조건부★ — 앞 짝에 기대는 꼴 하나 포함)."""
    shape = (PATHS, PAIRS)
    u = rng.random(shape)
    markov = np.zeros(shape, dtype=int)
    for t in range(PAIRS):
        prev_even = markov[:, t - 1] == 0 if t else np.ones(PATHS, dtype=bool)
        moving = np.where(prev_even, rng.random(PATHS) < 0.2, rng.random(PATHS) < 0.9)     # 같은 체결이 몰려 온다
        markov[:, t] = np.where(moving, np.where(rng.random(PATHS) < 0.5, 1, -1), 0)       # 움직이면 반반 — 조건부 평균 0
    return {
        "반반": np.where(u < 0.5, 1, -1),
        "같은 체결이 30% 섞인 반반": np.where(u < 0.3, 0, np.where(u < 0.65, 1, -1)),
        "유리가 잦다(0.4 · 0.6)": np.where(u < 0.4, 1, -1),
        "같은 체결이 몰려 오는 의존": markov,
    }


def test_signs_under_no_systematic_disadvantage_rarely_ever_cross():
    rng = np.random.default_rng(20261119)
    for name, S in sign_nulls(rng).items():
        rate = sign_crossing_rate(S)
        assert rate <= evalue.ALPHA + SLACK, f"{name}: {rate:.3%}"


def test_signs_with_a_real_disadvantage_do_cross():
    """짝 — 늘 거부하는 장치가 아니다: 불리할 확률 0.65 면 200짝 안에 대부분 넘는다(모의 2026-11-19 · 94%)."""
    rng = np.random.default_rng(5)
    S = np.where(rng.random((400, 200)) < 0.65, 1, -1)
    assert sign_crossing_rate(S) >= 0.85
