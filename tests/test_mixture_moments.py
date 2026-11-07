"""국면혼합 적률 — ★불변식 I1~I4 는 성능이 아니라 항등식이다★ (MS1-a 커밋 1)
==============================================================================
계획: `docs/plans/2026-08-25-macro-vnext-plan.md` §1.3(정확식) · §1.10.0(불변식)

★왜 허용오차가 기계 정밀도인가★
아래 대부분은 통계적 근사가 아니라 **대수적 항등식**이다. 국면 간 차이가 없으면
(I1) 전이행렬이 무엇이든 결과가 흔들릴 수 없고, `P = I` 면 (I3) 국면 간 누적항이
정확히 `h²·D` 다. 느슨한 허용오차를 주면 **상수를 맞춰 넣은 구현**이 통과한다.

★짝 테스트★ "같아야 한다" 만 걸면 입력을 무시하는 구현이 전부 통과한다. 그래서
`test_absorbing_*`(같다)에는 `test_non_absorbing_*`(다르다)가, 월별·일별 동치에는
"국면을 매일 재추첨하면 국면 간 항이 지워진다" 가 짝으로 붙는다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.engine.conditional_market import (
    conditional_moments,
    mixture_from_moments,
    regime_mixture_moments,
)

REGIMES = ["A", "B"]
MONTHS_PER_YEAR = 12.0

# ── 통제 fixture ──────────────────────────────────────────────────────────
# ★날짜 의존 mock 을 쓰지 않는다★ 이전 슬라이스에서 mock 상관이 날이 바뀌며
# 0.094 로 떨어져 가드가 깨진 적이 있다. 아래는 전부 손으로 지정한 값이다.
MU_A_ANN = np.array([0.180, -0.024])          # 연율
MU_B_ANN = np.array([-0.096, 0.072])
SIG_A_ANN = np.array([[0.030, 0.006], [0.006, 0.0108]])
SIG_B_ANN = np.array([[0.0588, -0.012], [-0.012, 0.0192]])

P_PERSIST = np.array([[0.85, 0.15], [0.25, 0.75]])   # 행 = 출발
PI0 = np.array([0.6, 0.4])


def _mu_map(a=MU_A_ANN, b=MU_B_ANN):
    return {"A": np.asarray(a, dtype=float), "B": np.asarray(b, dtype=float)}


def _sig_map(a=SIG_A_ANN, b=SIG_B_ANN):
    return {"A": np.asarray(a, dtype=float), "B": np.asarray(b, dtype=float)}


def _pi_path(P, pi0, h):
    """π_j = π₀·P^j — 구현과 **독립적으로** 테스트가 직접 만든다."""
    return [pi0 @ np.linalg.matrix_power(np.asarray(P, dtype=float), j)
            for j in range(1, h + 1)]


def _dispersion(pi, mu_map):
    """D = Σ π_r μ_r μ_rᵀ − μ̄ μ̄ᵀ (월간 단위)."""
    M = np.array([mu_map[r] for r in REGIMES]) / MONTHS_PER_YEAR
    bar = np.asarray(pi, dtype=float) @ M
    return sum(pi[i] * np.outer(M[i], M[i]) for i in range(len(REGIMES))) - np.outer(bar, bar)


def _call(P, pi_path, h, mu_map=None, sig_map=None):
    return mixture_from_moments(
        mu_by_regime=mu_map or _mu_map(),
        sigma_by_regime=sig_map or _sig_map(),
        pi_path=[dict(zip(REGIMES, p, strict=True)) for p in pi_path],
        transition=np.asarray(P, dtype=float).tolist(),
        regimes=REGIMES,
        h_hold=h,
    )


# ══════════════════════════════════════════════════════════════════════════
# I1 · 동일국면 불변식
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("h", [1, 3, 6])
def test_identical_regimes_reduce_to_common_moments(h):
    """★I1★ 모든 국면의 μ·Σ 가 같으면 혼합은 그것으로 **정확히** 환원된다.

    국면 간 차이가 0이면 전이행렬이 무엇이든 결과가 흔들릴 수 없다 — 흔들리면
    π 나 P 가 **잘못 곱해진** 것이다. 허용오차는 기계 정밀도다.
    """
    mu0 = np.array([0.12, -0.024])
    sig0 = np.array([[0.030, 0.006], [0.006, 0.0108]])
    out = _call(P_PERSIST, _pi_path(P_PERSIST, PI0, h), h,
                mu_map={"A": mu0, "B": mu0.copy()},
                sig_map={"A": sig0, "B": sig0.copy()})

    assert out["available"] is True
    np.testing.assert_allclose(out["mu"], mu0, rtol=0, atol=1e-15)
    np.testing.assert_allclose(out["sigma"], sig0, rtol=0, atol=1e-15)
    # 국면 간 누적항은 정확히 0 — "거의 0" 이 아니라 0 이다.
    assert np.abs(np.asarray(out["A_h"])).max() < 1e-15
    assert out["A_contribution_pct"] == pytest.approx(0.0, abs=1e-12)


# ══════════════════════════════════════════════════════════════════════════
# I2 · 확정국면 불변식 (짝: 흡수는 같다 / 비흡수는 다르다)
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("h", [1, 3])
def test_absorbing_regime_equals_hard_moments(h):
    """★I2★ 흡수 국면(P[r][r]=1)에 π₀=e_r 이면 하드 라벨 적률과 원소별 동일.

    ★`π(S_t)=e_r` 만으로는 부족하다★ 홀딩 기간 내내 원핫이려면 흡수여야 한다.
    """
    P_abs = np.array([[1.0, 0.0], [0.3, 0.7]])
    out = _call(P_abs, _pi_path(P_abs, np.array([1.0, 0.0]), h), h)

    np.testing.assert_allclose(out["mu"], MU_A_ANN, rtol=0, atol=1e-15)
    np.testing.assert_allclose(out["sigma"], SIG_A_ANN, rtol=0, atol=1e-15)
    assert np.abs(np.asarray(out["A_h"])).max() < 1e-15


def test_non_absorbing_onehot_must_differ_from_hard():
    """★I2 의 짝★ 비흡수 P 에 π₀=e_r 이면 하드와 **달라야 한다**.

    같게 나오면 `P` 를 쓰지 않고 있다는 뜻이다 — 오늘 국면을 확실히 알아도
    3개월 뒤는 모른다는 것이 이 슬라이스의 존재 이유다.
    """
    h = 3
    out = _call(P_PERSIST, _pi_path(P_PERSIST, np.array([1.0, 0.0]), h), h)

    assert not np.allclose(out["mu"], MU_A_ANN, atol=1e-6)
    assert np.abs(np.asarray(out["A_h"])).max() > 1e-6
    # π₁ 이 이미 원핫이 아니다 — 그것이 차이의 출처다.
    assert out["pi_path"][0]["A"] == pytest.approx(0.85)


# ══════════════════════════════════════════════════════════════════════════
# I2b · π_path 와 P 의 상호일관성
# ══════════════════════════════════════════════════════════════════════════
def test_pi_path_inconsistent_with_transition_is_refused():
    """★I2b★ π_{j+1} ≠ π_j·P 이면 A_h 가 공분산이 아니게 된다 — 계산하지 않는다.

    강제로 계산하면 음의 고유값(실측 −3.94e−4)이 나오고, 그 행렬이 최적화기로
    가면 음의 분산을 최소화하려 든다. 조용히 넘기지 않고 사유를 돌려준다.
    """
    h = 3
    onehot = [np.array([1.0, 0.0])] * h        # P 와 맞지 않는 경로
    out = _call(P_PERSIST, onehot, h)

    assert out["available"] is False
    assert out["mu"] is None and out["sigma"] is None
    assert "일관" in (out["reason"] or "")


def test_consistent_pi_path_is_accepted():
    """짝 — 일관된 경로는 통과해야 한다(위 가드가 전부를 막지 않도록)."""
    h = 3
    out = _call(P_PERSIST, _pi_path(P_PERSIST, PI0, h), h)
    assert out["available"] is True


# ══════════════════════════════════════════════════════════════════════════
# I3 · 전이극한 불변식
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("h", [2, 3, 4])
def test_identity_transition_recovers_persistent_limit(h):
    """★I3★ P = I → A_h = h²·D (완전지속 상한)."""
    P = np.eye(2)
    out = _call(P, _pi_path(P, PI0, h), h)
    expected = (h ** 2) * _dispersion(PI0, _mu_map())
    np.testing.assert_allclose(out["A_h"], expected, rtol=0, atol=1e-18)


@pytest.mark.parametrize("h", [2, 3, 4])
def test_memoryless_transition_recovers_redraw_limit(h):
    """★I3★ P 의 모든 행이 π 와 같으면 → A_h = h·D (독립재추첨 하한)."""
    P = np.tile(PI0, (2, 1))
    out = _call(P, _pi_path(P, PI0, h), h)
    expected = h * _dispersion(PI0, _mu_map())
    np.testing.assert_allclose(out["A_h"], expected, rtol=0, atol=1e-18)


def test_real_transition_lies_strictly_between_the_two_limits():
    """지속성 있는 P 는 두 극한 **사이**다 — 어느 한쪽으로 붙으면 근사를 쓴 것이다."""
    h = 3
    out = _call(P_PERSIST, _pi_path(P_PERSIST, PI0, h), h)
    A = np.diag(np.asarray(out["A_h"]))
    D = np.diag(_dispersion(PI0, _mu_map()))
    assert np.all(A < (h ** 2) * D - 1e-12)      # h²D 보다 작다
    assert np.all(A > h * D + 1e-12)             # hD 보다 크다


# ══════════════════════════════════════════════════════════════════════════
# I4 · 연율화 / 시간해상도 일관성
# ══════════════════════════════════════════════════════════════════════════
def _daily_reference(P, pi0, mu_map, sig_map, h, days_per_month, resolution):
    """★독립 참조 구현★ — 일별 스텝으로 적률을 만든다. 국면의 시간해상도가 인자다.

    - `"month"`  한 달의 영업일이 **같은 국면 라벨**을 공유한다 (★옳다★).
    - `"day"`    월간 전이행렬을 **매일** 적용한다 (틀렸다).
    - `"day_iid"` 국면을 매일 **독립 재추첨**한다 (틀렸다).

    두 오답을 모두 만드는 이유: "일별로 내려간 것" 자체가 틀린 게 아니라 **국면의
    시간해상도까지 일별로 바꾼 것**이 틀렸다는 점을 테스트가 구분해야 하기 때문이다.
    """
    M = np.array([mu_map[r] for r in REGIMES]) / MONTHS_PER_YEAR / days_per_month
    S = np.array([sig_map[r] for r in REGIMES]) / MONTHS_PER_YEAR / days_per_month
    n_steps = h * days_per_month
    P_step = P
    if resolution == "month":
        pis = [pi0 @ np.linalg.matrix_power(P, 1 + i // days_per_month) for i in range(n_steps)]
        lag = lambda a, b: abs(a // days_per_month - b // days_per_month)  # noqa: E731
    elif resolution == "day":
        pis = [pi0 @ np.linalg.matrix_power(P, 1 + i) for i in range(n_steps)]
        lag = lambda a, b: abs(a - b)                                     # noqa: E731
    elif resolution == "day_iid":
        P_step = np.tile(pi0, (len(REGIMES), 1))
        pis = [np.asarray(pi0, dtype=float)] * n_steps
        lag = lambda a, b: abs(a - b)                                     # noqa: E731
    else:                                                                  # pragma: no cover
        raise ValueError(resolution)
    E = [p @ M for p in pis]
    W = sum(np.einsum("s,sij->ij", p, S) for p in pis)
    A = np.zeros((M.shape[1], M.shape[1]))
    for a in range(n_steps):
        for b in range(n_steps):
            T = np.linalg.matrix_power(P_step, lag(a, b))
            J = (np.einsum("s,st->st", pis[a], T) if (b >= a)
                 else np.einsum("t,ts->st", pis[b], T))
            A += np.einsum("st,si,tj->ij", J, M, M) - np.outer(E[a], E[b])
    return sum(E), W, A


def test_daily_and_monthly_steps_agree_when_regime_is_month_blocked():
    """★I4★ 국면의 시간해상도를 유지하면 일별 스텝과 월별 스텝이 **같은 적률**을 낸다.

    독립 참조 구현(위 `_daily_reference`)과 대조한다 — 같은 식을 두 번 쓰는 것이
    아니라 **다른 시간축**에서 세운 계산과 맞춘다.
    """
    h, dpm = 3, 21
    out = _call(P_PERSIST, _pi_path(P_PERSIST, PI0, h), h)
    mu_d, W_d, A_d = _daily_reference(P_PERSIST, PI0, _mu_map(), _sig_map(),
                                      h, dpm, resolution="month")
    ann = MONTHS_PER_YEAR / h
    np.testing.assert_allclose(out["mu"], mu_d * ann, rtol=0, atol=1e-14)
    np.testing.assert_allclose(out["W_h"], W_d, rtol=0, atol=1e-14)
    np.testing.assert_allclose(out["A_h"], A_d, rtol=0, atol=1e-14)


@pytest.mark.parametrize("resolution", ["day", "day_iid"])
def test_daily_regime_resolution_erases_the_between_regime_term(resolution):
    """★I4 의 짝★ 국면의 시간해상도를 일별로 바꾸면 국면 간 항이 대부분 지워진다.

    프로덕션이 그 구현이 **아님**을 확인한다 — 만약 그랬다면 위 동치 테스트가
    아니라 이쪽과 맞아떨어졌을 것이다.

    ★배수를 못박지 않는다★ 이 fixture 에서는 `day` 11.2배 · `day_iid` 42.3배지만,
    앞선 조사에서 다른 fixture 는 889배였다. **배수는 fixture 의 성질이고 불변식이
    아니다.** 불변식은 "월 블록과 정확히 같고, 일별 해상도와는 크게 다르다" 이며,
    정확한 쪽은 `test_daily_and_monthly_steps_agree_*` 가 1e−14 로 못박는다.
    """
    h, dpm = 3, 21
    out = _call(P_PERSIST, _pi_path(P_PERSIST, PI0, h), h)
    _, _, A_bad = _daily_reference(P_PERSIST, PI0, _mu_map(), _sig_map(),
                                   h, dpm, resolution=resolution)
    ratio = np.diag(np.asarray(out["A_h"])) / np.diag(A_bad)
    assert np.all(ratio > 2.0), f"국면 해상도가 일별로 뭉개졌다({resolution}): 비율 {ratio}"


def test_annualization_identity_between_cumulative_and_rate():
    """★I4★ 응답 안에서 h개월 누적(W_h+A_h)과 연율 Σ 가 서로 정합해야 한다.

    스케일링 버그를 직접 잡는다 — 둘 중 하나만 틀려도 여기서 죽는다.
    """
    h = 3
    out = _call(P_PERSIST, _pi_path(P_PERSIST, PI0, h), h)
    cum = np.asarray(out["W_h"]) + np.asarray(out["A_h"])
    np.testing.assert_allclose(out["sigma"], cum * (MONTHS_PER_YEAR / h),
                               rtol=0, atol=1e-15)


def test_scale_homogeneity():
    """μ 를 c 배, Σ 를 c² 배 하면 출력도 정확히 c · c² 배 — 차원이 맞는지 본다."""
    h, c = 3, 3.0
    pis = _pi_path(P_PERSIST, PI0, h)
    base = _call(P_PERSIST, pis, h)
    scaled = _call(P_PERSIST, pis, h,
                   mu_map={r: v * c for r, v in _mu_map().items()},
                   sig_map={r: v * c * c for r, v in _sig_map().items()})
    np.testing.assert_allclose(scaled["mu"], np.asarray(base["mu"]) * c, rtol=1e-14, atol=0)
    np.testing.assert_allclose(scaled["sigma"], np.asarray(base["sigma"]) * c * c,
                               rtol=1e-14, atol=0)


# ══════════════════════════════════════════════════════════════════════════
# μ 는 종단이 아니라 시간평균 · 국면 간 항은 리스크를 키운다
# ══════════════════════════════════════════════════════════════════════════
def test_mu_uses_time_average_not_terminal_distribution():
    """μ̄ 는 `π̄`(시간평균) 기반이다. `π_h` 만 쓰면 다른 값이 나온다.

    실데이터에서 그 차이가 Goldilocks 기준 9.2%p 였다.
    """
    h = 3
    pis = _pi_path(P_PERSIST, np.array([1.0, 0.0]), h)
    out = _call(P_PERSIST, pis, h)

    M = np.array([MU_A_ANN, MU_B_ANN])
    from_bar = np.mean(pis, axis=0) @ M
    from_terminal = pis[-1] @ M
    np.testing.assert_allclose(out["mu"], from_bar, rtol=0, atol=1e-14)
    assert not np.allclose(out["mu"], from_terminal, atol=1e-6)
    np.testing.assert_allclose([out["pi_bar"][r] for r in REGIMES],
                               np.mean(pis, axis=0), rtol=0, atol=1e-14)


def test_between_regime_term_raises_risk():
    """국면별 μ 가 다르면 혼합 Σ 는 국면 내 평균보다 **크다** — 산포가 리스크로 간다."""
    h = 3
    out = _call(P_PERSIST, _pi_path(P_PERSIST, PI0, h), h)
    W_ann = np.asarray(out["W_h"]) * (MONTHS_PER_YEAR / h)
    assert np.trace(np.asarray(out["sigma"])) > np.trace(W_ann) + 1e-12
    assert out["A_contribution_pct"] > 0.0


# ══════════════════════════════════════════════════════════════════════════
# 실패상태 — 클립하지 않고 사유를 돌려준다
# ══════════════════════════════════════════════════════════════════════════
def test_non_psd_result_is_reported_not_clipped():
    """최소고유값이 음수면 값을 고쳐 내보내지 않고 `available: False` 로 보고한다."""
    h = 2
    bad = np.array([[0.03, 0.20], [0.20, 0.01]])       # 명백히 비-PSD
    out = _call(P_PERSIST, _pi_path(P_PERSIST, PI0, h), h,
                sig_map={"A": bad, "B": bad.copy()})
    assert out["available"] is False
    assert out["sigma"] is None
    assert "양정치" in (out["reason"] or "") or "고유값" in (out["reason"] or "")


def test_horizon_must_be_positive_integer_months():
    """`h_hold` 는 개월이고 1 이상이다 — 기대 지속기간(2.5~5.0)을 흘려 넣지 못하게."""
    for bad_h in (0, -1):
        out = _call(P_PERSIST, _pi_path(P_PERSIST, PI0, 1), bad_h)
        assert out["available"] is False


def test_horizon_length_must_match_pi_path():
    """π_path 길이와 `h_hold` 가 어긋나면 계산하지 않는다."""
    out = _call(P_PERSIST, _pi_path(P_PERSIST, PI0, 2), 3)
    assert out["available"] is False


# ══════════════════════════════════════════════════════════════════════════
# 래퍼 — 표본에서 국면별 적률을 뽑아 위 수학에 넘긴다
# ══════════════════════════════════════════════════════════════════════════
def _returns_frame(months: int = 24, seed: int = 7):
    """월별 국면 라벨이 붙는 일별 수익률 — 두 국면이 번갈아 12개월씩."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=months * 21, freq="C")
    R = rng.normal(0.0, 0.01, size=(len(idx), 2))
    df = pd.DataFrame(R, index=idx, columns=["X", "Y"])
    by_month = {}
    for i, m in enumerate(sorted({d.strftime("%Y-%m") for d in idx})):
        by_month[m] = "A" if i < months // 2 else "B"
    return df, by_month


def test_wrapper_absorbing_regime_equals_conditional_moments():
    """★I2 (래퍼)★ 흡수 국면이면 래퍼 결과가 기존 `conditional_moments` 와 동일.

    ★새 추정기를 만들지 않는다는 것이 이 테스트의 내용이다★ — 게이트·수축·진단이
    전부 기존 경로를 그대로 탄다.
    """
    df, by_month = _returns_frame()
    h = 3
    P_abs = [[1.0, 0.0], [0.3, 0.7]]
    pis = [{"A": 1.0, "B": 0.0} for _ in range(h)]

    hard = conditional_moments(df, by_month, "A")
    assert hard["available"] is True

    mix = regime_mixture_moments(df, by_month, pis, P_abs, REGIMES, h_hold=h)
    assert mix["available"] is True
    np.testing.assert_allclose(mix["mu"], hard["mu"], rtol=0, atol=1e-14)
    np.testing.assert_allclose(mix["sigma"], hard["sigma"], rtol=0, atol=1e-14)
    assert mix["names"] == hard["names"]


def test_wrapper_drops_unavailable_regime_and_says_so():
    """표본이 없는 국면은 π 에서 빼고 재정규화하되 **뺐다는 사실을 적는다**."""
    df, by_month = _returns_frame()
    by_month = {m: "A" for m in by_month}          # B 국면 표본이 하나도 없다
    h = 2
    P = [[0.8, 0.2], [0.3, 0.7]]
    pi0 = np.array([1.0, 0.0])
    pis = [dict(zip(REGIMES, pi0 @ np.linalg.matrix_power(np.array(P), j), strict=True))
           for j in (1, 2)]

    out = regime_mixture_moments(df, by_month, pis, P, REGIMES, h_hold=h)
    assert out["available"] is True
    assert "B" in out["dropped_regimes"]
    assert out["pi_path"][0]["A"] == pytest.approx(1.0)   # 재정규화됐다


def test_wrapper_reports_when_all_regimes_drop():
    """전부 빠지면 숫자를 지어내지 않고 `available: False`."""
    df, by_month = _returns_frame()
    # 어느 달도 A/B 로 분류되지 않는다 — 두 국면 다 표본이 0이다.
    out = regime_mixture_moments(df, {m: "C" for m in by_month},
                                 [{"A": 1.0, "B": 0.0}], [[1.0, 0.0], [0.0, 1.0]],
                                 REGIMES, h_hold=1)
    assert out["available"] is False
    assert out["reason"]
