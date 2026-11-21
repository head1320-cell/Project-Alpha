"""시계열용 등각 — 적응형 등각 추론(ACI · Gibbs & Candès 2021) (G7 ② · 2026-11-19)
==============================================================================
split 등각(`conformal.split_conformal`)의 보장은 점수가 ★교환가능할 때만★ 선다. 리밸런스 쌍처럼 시간 순서가 있는 자료는
국면이 바뀌면 그 가정이 깨진다. ACI 는 걸음마다 목표 오차율 α_t 를 고친다 — 놓치면 낮춰 구간을 넓히고 덮으면 높여 좁힌다:

    α_{t+1} = α_t + γ (α − err_t)

★보장(어떤 수열에서도 · 결정적)★ α_1 = α 이면  |(1/T) Σ err_t − α| ≤ (max(α, 1 − α) + γ) / (γ T).
대가: 장기 평균 놓침률만 말한다(구간 하나하나의 적중이 아니다) · T 가 짧으면 이 상한이 자명한 폭 max(α, 1 − α) 를 넘어 공허하다.
유도는 계획 문서 §7.2a(논문 본문은 이 환경에서 열리지 않았다 — 갱신식과 실험 γ = 0.005 만 검색 요약으로 확인).

이 파일이 거는 계약
  1. 손 계산 — 점수 다섯(α = 0.2 · γ = 0.1)의 걸음마다 α_t · 순위 · 구간 · 놓침 · 다음 구간.
  2. 유한표본 순위 하나가 세 경우를 가른다 — 순위 > m 이면 실수 전체(덮음) · 순위 ≤ 0 이면 빈 집합(놓침). 자르지 않는다.
  3. 보장 상한이 ★모든 접두 T 에서★ 선다 — 무작위 · 교대 · 추세 · 분산 이동 · 적대적 수열(늘 놓치게 · 늘 덮게).
  4. 상한이 자명한 폭 이상이면 '보장이 서지 않는다'(짝: 긴 수열은 선다) · 크기 표(36 · 80 · 1,810 쌍).
  5. 입력 검사 — 길이 · 빈 입력 · 유한하지 않은 값 · α · γ 범위 → 값 없음 + 사유(조용히 빼지 않는다).
  6. 기존 split 함수 넷은 바뀌지 않는다(변경 전 동작 사진 `tests/golden/conformal_split_g7.json`).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from src.engine import conformal as cf

GOLDEN = Path(__file__).parent / "golden" / "conformal_split_g7.json"

# ── 1. 손 계산 ────────────────────────────────────────────────────────────────
# 점수 |y − ŷ| = 3, 1, 4, 1, 5 · α = 0.2 · γ = 0.1 (손으로 따라간 값 — 아래 주석)
#   t=1  m=0  α=0.20  순위 ⌈1·0.80⌉=1 > 0 → 실수 전체 · 덮음      → α=0.22
#   t=2  m=1  α=0.22  순위 ⌈2·0.78⌉=⌈1.56⌉=2 > 1 → 실수 전체 · 덮음 → α=0.24
#   t=3  m=2  α=0.24  순위 ⌈3·0.76⌉=⌈2.28⌉=3 > 2 → 실수 전체 · 덮음 → α=0.26
#   t=4  m=3  α=0.26  순위 ⌈4·0.74⌉=⌈2.96⌉=3 ≤ 3 → 앞 점수 [1,3,4] 의 셋째 = 4 · 점수 1 ≤ 4 덮음 → α=0.28
#        (α 를 0.2 로 묶어 두면 ⌈4·0.8⌉=⌈3.2⌉=4 > 3 이라 이 걸음도 실수 전체였다 — 고친 α 가 구간을 만든 걸음)
#   t=5  m=4  α=0.28  순위 ⌈5·0.72⌉=⌈3.6⌉=4 → [1,1,3,4] 의 넷째 = 4 · 점수 5 > 4 놓침 → α=0.28+0.1·(0.2−1)=0.20
#   다음 m=5  α=0.20  순위 ⌈6·0.80⌉=⌈4.8⌉=5 → [1,1,3,4,5] 의 다섯째 = 5 → 60 ± 5
PRED = [10.0, 20.0, 30.0, 40.0, 50.0]
ACTUAL = [13.0, 19.0, 34.0, 39.0, 55.0]
SCORES = [3.0, 1.0, 4.0, 1.0, 5.0]


def test_the_hand_computed_path_of_five_scores():
    steps, alpha_next = cf.aci_steps(SCORES, alpha=0.2, gamma=0.1)
    assert [s["t"] for s in steps] == [1, 2, 3, 4, 5]
    assert [s["m"] for s in steps] == [0, 1, 2, 3, 4]
    assert [s["alpha_t"] for s in steps] == pytest.approx([0.20, 0.22, 0.24, 0.26, 0.28])
    assert [s["rank"] for s in steps] == [1, 2, 3, 3, 4]
    assert [s["kind"] for s in steps] == ["infinite", "infinite", "infinite", "finite", "finite"]
    assert [s["q"] for s in steps] == [None, None, None, 4.0, 4.0]
    assert [s["score"] for s in steps] == SCORES
    assert [s["err"] for s in steps] == [0, 0, 0, 0, 1]
    assert alpha_next == pytest.approx(0.20)


def test_the_hand_computed_summary_and_next_interval():
    out = cf.adaptive_conformal(ACTUAL, PRED, 60.0, alpha=0.2, gamma=0.1)
    assert out["available"] is True and out["method"] == "aci"
    assert (out["alpha"], out["gamma"], out["n"]) == (0.2, 0.1, 5)
    assert out["alpha_next"] == pytest.approx(0.20)
    on = out["online"]
    assert (on["n"], on["hits"], on["misses"]) == (5, 4, 1)
    assert on["coverage"] == pytest.approx(0.8)
    assert (on["n_infinite"], on["n_finite"], on["n_empty"]) == (3, 2, 0)
    assert on["mean_width"] == pytest.approx(8.0)          # 유한한 두 걸음의 너비 2·4 · 2·4 — 무한 구간은 평균에 넣지 않는다
    nx = out["next"]
    assert nx["kind"] == "finite" and (nx["rank"], nx["m"]) == (5, 5)
    assert (nx["point"], nx["lower"], nx["upper"], nx["half_width"]) == (60.0, 55.0, 65.0, 5.0)
    assert nx["sentence"] is None
    b = out["bound"]
    assert b["value"] == pytest.approx(0.9 / 0.5)           # (max(0.2, 0.8) + 0.1) / (0.1 · 5) = 1.8
    assert b["trivial"] == pytest.approx(0.8)
    assert b["informative"] is False
    assert "보장이 서지 않습니다" in b["sentence"] and "5쌍" in b["sentence"]
    assert out["note"] and "교환가능성" in out["note"]


def test_the_half_width_is_the_rank_th_smallest_past_score_not_the_rank_th_in_time():
    """점수 5, 1, 4, 1, 3(α = 0.2 · γ = 0.1): 넷째 걸음의 반폭은 앞 점수 [5,1,4] 를 줄 세운 셋째 = 5 · 다음 구간은 ⌈6·0.7⌉ = 5 번째로 작은 5
    (시간 순서의 다섯째 점수 3 이 아니다). 짝: 위 손 계산(3,1,4,1,5)과 같은 순위에서 다른 반폭이 나온다."""
    steps, a_next = cf.aci_steps([5.0, 1.0, 4.0, 1.0, 3.0], alpha=0.2, gamma=0.1)
    assert [s["q"] for s in steps] == [None, None, None, 5.0, 5.0]
    assert [s["err"] for s in steps] == [0, 0, 0, 0, 0]
    assert a_next == pytest.approx(0.30)
    out = cf.adaptive_conformal([5.0, 1.0, 4.0, 1.0, 3.0], [0.0] * 5, 0.0, alpha=0.2, gamma=0.1)
    assert (out["next"]["rank"], out["next"]["half_width"]) == (5, 5.0)


def test_the_score_of_a_step_is_compared_with_the_interval_inclusively():
    """점수가 반폭과 같으면 덮음이다(split 의 실측 적중률 `measure_coverage` 가 경계를 넣는 것과 같다)."""
    steps, _ = cf.aci_steps([2.0, 2.0, 2.0, 2.0], alpha=0.5, gamma=0.01)
    finite = [s for s in steps if s["kind"] == "finite"]
    assert finite and all(s["q"] == 2.0 and s["err"] == 0 for s in finite)


# ── 2. 무한 · 빈 구간 — 유한표본 순위 하나가 가른다 ───────────────────────────────

def test_the_first_steps_are_the_whole_line_and_count_as_covered():
    steps, _ = cf.aci_steps([5.0, 5.0, 5.0], alpha=0.1, gamma=0.005)
    assert [s["kind"] for s in steps] == ["infinite"] * 3
    assert [s["err"] for s in steps] == [0, 0, 0]
    assert all(s["q"] is None and s["rank"] > s["m"] for s in steps)


def test_an_alpha_driven_to_one_gives_an_empty_interval_that_counts_as_a_miss():
    """α = 0.25 · γ = 0.5 · 점수가 모두 0 이면 늘 덮어 α 가 0.125 씩 올라 일곱째 걸음에 정확히 1 이 된다(이진수로 딱 떨어지는 값)."""
    steps, alpha_next = cf.aci_steps([0.0] * 8, alpha=0.25, gamma=0.5)
    assert [s["alpha_t"] for s in steps] == [0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0, 0.625]
    assert [s["kind"] for s in steps] == ["infinite", "infinite", "finite", "finite", "finite", "finite", "empty", "finite"]
    assert [s["err"] for s in steps] == [0, 0, 0, 0, 0, 0, 1, 0]
    assert steps[6]["rank"] <= 0 and steps[6]["q"] is None
    assert alpha_next == 0.75


def test_the_next_interval_uses_the_alpha_after_the_last_update():
    """짝: 마지막 걸음의 α(=1 · 빈 집합)가 아니라 그 걸음을 반영한 α(=0.625)로 다음 구간을 짓는다."""
    out = cf.adaptive_conformal([0.0] * 7, [0.0] * 7, 1.0, alpha=0.25, gamma=0.5)
    assert out["alpha_next"] == 0.625
    assert out["online"]["n_empty"] == 1 and out["online"]["misses"] == 1
    nx = out["next"]
    assert (nx["kind"], nx["rank"], nx["m"]) == ("finite", 3, 7)   # ⌈8 · 0.375⌉ = 3
    assert (nx["lower"], nx["upper"], nx["half_width"]) == (1.0, 1.0, 0.0)


def test_an_infinite_next_interval_is_a_sentence_not_a_number():
    out = cf.adaptive_conformal([1.0], [0.0], 5.0, alpha=0.1, gamma=0.005)
    nx = out["next"]
    assert nx["kind"] == "infinite" and nx["rank"] > nx["m"] == 1
    assert nx["lower"] is None and nx["upper"] is None and nx["half_width"] is None
    assert nx["point"] == 5.0
    assert nx["sentence"] and "실수 전체" in nx["sentence"]


def test_an_empty_next_interval_is_a_sentence_not_a_number():
    out = cf.adaptive_conformal([0.0] * 6, [0.0] * 6, 2.0, alpha=0.25, gamma=0.5)
    assert out["alpha_next"] == 1.0                              # 여섯 걸음 모두 덮어 0.25 + 6 · 0.125
    nx = out["next"]
    assert nx["kind"] == "empty" and nx["rank"] <= 0
    assert nx["lower"] is None and nx["upper"] is None and nx["half_width"] is None
    assert nx["sentence"] and "비어 있습니다" in nx["sentence"]


@pytest.mark.parametrize("m", [0, 1, 5, 50])
def test_the_rank_rule_alone_separates_the_three_cases(m):
    assert cf.aci_rank(m, 0.0)[0] == "infinite"
    assert cf.aci_rank(m, -0.003)[0] == "infinite"
    assert cf.aci_rank(m, 1.0) == ("empty", 0)
    assert cf.aci_rank(m, 1.004)[0] == "empty"
    kind, rank = cf.aci_rank(m, 0.5)
    assert rank == math.ceil((m + 1) * 0.5)
    assert kind == ("finite" if 1 <= rank <= m else "infinite")


# ── 3. 보장 상한 — 모든 접두에서 ────────────────────────────────────────────────

def _adversarial(n: int, *, alpha: float, gamma: float, miss: bool) -> list[float]:
    """걸음마다 그때의 구간을 보고 점수를 고른다 — miss=True 면 유한 구간 바로 바깥(늘 놓치게) · False 면 0(늘 덮게)."""
    scores: list[float] = []
    for _ in range(n):
        steps, a_next = (cf.aci_steps(scores, alpha=alpha, gamma=gamma) if scores else ([], alpha))
        kind, rank = cf.aci_rank(len(scores), a_next)
        if not miss:
            scores.append(0.0)
        elif kind == "finite":
            scores.append(sorted(scores)[rank - 1] + 1.0)
        else:
            scores.append(0.0)
    return scores


def _sequences(n: int, alpha: float, gamma: float) -> dict[str, list[float]]:
    rng = np.random.default_rng(1119)
    t = np.arange(n)
    return {
        "iid": np.abs(rng.normal(0.0, 1.0, n)).round(6).tolist(),
        "alternating": [0.0 if i % 2 else 100.0 for i in range(n)],
        "trend": (0.01 * t + np.abs(rng.normal(0.0, 0.1, n))).round(6).tolist(),
        "shift": np.concatenate([np.abs(rng.normal(0, 1, n // 2)), np.abs(rng.normal(0, 8, n - n // 2))]).round(6).tolist(),
        "adv_miss": _adversarial(n, alpha=alpha, gamma=gamma, miss=True),
        "adv_cover": _adversarial(n, alpha=alpha, gamma=gamma, miss=False),
    }


@pytest.mark.parametrize("alpha,gamma,n", [(0.1, 0.005, 240), (0.1, 0.05, 240), (0.2, 0.1, 160), (0.05, 0.02, 200)])
def test_the_bound_holds_at_every_prefix_of_every_sequence(alpha, gamma, n):
    for name, scores in _sequences(n, alpha, gamma).items():
        steps, _ = cf.aci_steps(scores, alpha=alpha, gamma=gamma)
        errs = np.array([s["err"] for s in steps], dtype=float)
        for T in range(1, n + 1):
            gap = abs(errs[:T].mean() - alpha)
            assert gap <= cf.aci_bound(T, alpha=alpha, gamma=gamma) + 1e-12, (name, T, gap)
        # 보조 정리 — α_t 는 [−γ, 1 + γ] 밖으로 나가지 않는다
        a = np.array([s["alpha_t"] for s in steps])
        assert a.min() >= -gamma - 1e-12 and a.max() <= 1 + gamma + 1e-12, name


def test_the_adversaries_really_push_alpha_to_both_walls():
    """적대적 수열이 공허하지 않다 — 늘 놓치게 하면 α_t ≤ 0(실수 전체)에 닿고, 늘 덮게 하면 α_t ≥ 1(빈 집합)에 닿는다."""
    alpha, gamma, n = 0.2, 0.1, 160
    seqs = _sequences(n, alpha, gamma)
    miss_steps, _ = cf.aci_steps(seqs["adv_miss"], alpha=alpha, gamma=gamma)
    cover_steps, _ = cf.aci_steps(seqs["adv_cover"], alpha=alpha, gamma=gamma)
    assert any(s["alpha_t"] <= 0 and s["kind"] == "infinite" and s["err"] == 0 for s in miss_steps)
    assert all(s["err"] == 1 for s in miss_steps if s["kind"] == "finite")
    assert any(s["alpha_t"] >= 1 and s["kind"] == "empty" and s["err"] == 1 for s in cover_steps)
    assert all(s["err"] == 0 for s in cover_steps if s["kind"] != "empty")


def test_after_a_variance_shift_split_loses_coverage_while_the_aci_bound_holds():
    """교환가능성이 깨진 자료 — 앞 절반으로 보정한 split 구간은 뒤 절반을 거의 덮지 못한다. ACI 의 놓침률은 상한 안이다."""
    rng = np.random.default_rng(7)
    n = 1000
    scores = np.concatenate([np.abs(rng.normal(0, 1, n // 2)), np.abs(rng.normal(0, 5, n // 2))])
    q = cf.conformal_quantile(scores[: n // 2], 0.1)["q"]
    split_cov = float(np.mean(scores[n // 2:] <= q))
    assert split_cov < 0.5, split_cov
    steps, _ = cf.aci_steps(scores.tolist(), alpha=0.1, gamma=0.05)
    miss = np.mean([s["err"] for s in steps])
    assert abs(miss - 0.1) <= cf.aci_bound(n, alpha=0.1, gamma=0.05) + 1e-12
    assert cf.aci_bound(n, alpha=0.1, gamma=0.05) < 0.02


# ── 4. 상한의 크기 — 보장이 서는 길이 ───────────────────────────────────────────

@pytest.mark.parametrize("n,expected", [(36, 0.905 / 0.18), (80, 0.905 / 0.4), (1810, 0.1)])
def test_the_bound_sizes_for_the_product_gamma(n, expected):
    assert cf.ACI_GAMMA == 0.005
    assert cf.aci_bound(n, alpha=0.1, gamma=cf.ACI_GAMMA) == pytest.approx(expected)


def test_the_bound_becomes_informative_exactly_past_the_trivial_width():
    """짝: 201쌍은 상한 0.9005 ≥ 0.9(공허) · 202쌍은 0.8960 < 0.9."""
    def run(n):
        return cf.adaptive_conformal([0.0] * n, [0.0] * n, 0.0, alpha=0.1, gamma=0.005)["bound"]
    short, long_ = run(201), run(202)
    assert short["value"] >= short["trivial"] == pytest.approx(0.9) and short["informative"] is False
    assert long_["value"] < long_["trivial"] and long_["informative"] is True
    assert "보장이 서지 않습니다" in short["sentence"]
    assert "보장이 서지 않습니다" not in long_["sentence"] and "202쌍" in long_["sentence"]


# ── 5. 입력 검사 — 값 없음 + 사유 ────────────────────────────────────────────────

@pytest.mark.parametrize("actual,pred,test_pred,kw,needle", [
    ([1.0, 2.0], [1.0], 0.0, {}, "길이"),
    ([], [], 0.0, {}, "쌍이 없습니다"),
    ([1.0, float("nan")], [1.0, 1.0], 0.0, {}, "유한하지 않은"),
    ([1.0, 2.0], [1.0, float("inf")], 0.0, {}, "유한하지 않은"),
    ([1.0], [1.0], float("nan"), {}, "다음 구간의 예측"),
    ([1.0], [1.0], 0.0, {"alpha": 0.0}, "α"),
    ([1.0], [1.0], 0.0, {"alpha": 1.0}, "α"),
    ([1.0], [1.0], 0.0, {"gamma": 0.0}, "γ"),
    ([1.0], [1.0], 0.0, {"gamma": -0.1}, "γ"),
    ([1.0], [1.0], 0.0, {"gamma": 1.0}, "γ"),
])
def test_bad_input_is_a_reason_not_a_number(actual, pred, test_pred, kw, needle):
    out = cf.adaptive_conformal(actual, pred, test_pred, **kw)
    assert out["available"] is False and out["method"] == "aci"
    assert needle in out["reason"]
    assert "next" not in out and "online" not in out and "bound" not in out


def test_good_input_next_to_each_bad_one_is_accepted():
    """짝: 같은 꼴의 바른 입력은 받는다(검사가 늘 거절하는 검사가 아니다)."""
    out = cf.adaptive_conformal([1.0, 2.0], [1.0, 1.5], 0.0, alpha=0.5, gamma=0.5)
    assert out["available"] is True and out["n"] == 2


@pytest.mark.parametrize("scores", [[1.0, -0.5], [1.0, float("nan")], [float("inf")]])
def test_the_step_function_refuses_scores_that_are_not_sizes(scores):
    with pytest.raises(ValueError):
        cf.aci_steps(scores, alpha=0.1, gamma=0.005)


# ── 6. 기존 split 함수 넷은 바뀌지 않는다 ────────────────────────────────────────

def _close(got, want, path="$"):
    """정수 · 글 · 참거짓은 그대로 · 실수는 상대 1e-12(같은 식의 끝자리 차이만 허용 — 뜻이 바뀌면 그보다 훨씬 크게 갈린다)."""
    if isinstance(want, dict):
        assert isinstance(got, dict) and set(got) == set(want), (path, sorted(got), sorted(want))
        for k in want:
            _close(got[k], want[k], f"{path}.{k}")
    elif isinstance(want, list):
        assert isinstance(got, list) and len(got) == len(want), path
        for i, (g, w) in enumerate(zip(got, want, strict=True)):
            _close(g, w, f"{path}[{i}]")
    elif isinstance(want, float):
        assert got == pytest.approx(want, rel=1e-12, abs=1e-15), (path, got, want)
    else:
        assert got == want and type(got) is type(want), (path, got, want)


def _json(x):
    return json.loads(json.dumps(x, ensure_ascii=False))


R_SEG = [-0.00624, 0.003411, -0.002034, -0.004979, -0.002219, -0.000182, 0.00514, 0.002006,
         0.000284, -0.004459, 0.002021, -0.005446, -0.005596, -0.01187, 0.001915, 0.001133]
PREDS = [-0.000703, 0.002569, 0.000887, -2.6e-05, -0.001954, 0.002255, 0.00189, 0.003572, 0.001499,
         0.002104, 0.001225, 0.002543, -0.000415, -0.003738, 0.001925, -0.000817, -0.001849]
SPAN = 3


def _block_inputs():
    eq = [1.0]
    for r in R_SEG:
        for _ in range(SPAN):
            eq.append(eq[-1] * (1.0 + r))
    return np.array(eq), [i * SPAN for i in range(len(R_SEG) + 1)]


def test_the_split_functions_behave_exactly_as_before():
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    _close({str(a): cf.required_calibration_size(a) for a in (0.5, 0.2, 0.1, 0.05, 0.01)}, want["required"])
    r = np.array([0.5, 0.1, 0.9, 0.3, 0.7, 0.2, 0.8, 0.4, 0.6, 1.0, 0.25, 0.75])
    _close(_json(cf.conformal_quantile(r, 0.2)), want["quantile_ok"])
    _close(_json(cf.conformal_quantile(r[:3], 0.1)), want["quantile_short"])
    _close(_json(cf.conformal_quantile(np.array([0.1, -0.2]), 0.1)), want["quantile_neg"])
    _close(_json(cf.conformal_quantile(np.array([]), 0.1)), want["quantile_empty"])
    a = np.array([1.0, 2.5, 2.0, 4.5, 5.0, 5.5, 7.0, 8.5, 9.0, 10.5])
    p = np.array([1.5, 2.0, 3.0, 4.0, 5.5, 6.0, 6.5, 8.0, 9.5, 10.0])
    _close(_json(cf.split_conformal(a, p, np.array([11.0, 12.0]), alpha=0.2)), want["split_ok"])
    _close(_json(cf.split_conformal(a, p[:3], np.array([1.0]), alpha=0.2)), want["split_len"])
    _close(_json(cf.measure_coverage(np.array([1.0, 2.0, 3.0, 4.0]), np.array([0.5, 2.5, 2.0, 3.0]),
                                     np.array([1.5, 3.0, 3.5, 4.0]))), want["coverage"])
    _close(_json(cf.measure_coverage(np.array([1.0]), np.array([0.5, 1.0]), np.array([1.5]))), want["coverage_len"])
    _close(_json(cf.measure_coverage(np.array([]), np.array([]), np.array([]))), want["coverage_empty"])


def test_the_block_keeps_every_old_key_byte_for_byte_and_adds_only_adaptive():
    from src.engine.allocation_backtest import _conformal_block
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    eq, at = _block_inputs()
    got = _json(_conformal_block(PREDS, at, eq, 0))
    assert set(got) - set(want["block"]) == {"adaptive"}
    _close({k: v for k, v in got.items() if k != "adaptive"}, want["block"])
    short = _json(_conformal_block(PREDS[:6], at[:6], eq[: 5 * SPAN + 1], 0))
    _close(short, want["block_short"])                        # 쌍이 모자라면 예전처럼 블록 전체가 사유 — adaptive 도 없다
