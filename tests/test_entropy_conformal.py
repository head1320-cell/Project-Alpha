"""Entropy Pooling + Conformal — L2 사다리 칸을 채운다 (M1-T)
==============================================================================
M1-C 의 능력 사다리가 실측으로 드러낸 구멍: **L1 은 통과인데 L2 가 실패**였다
(`conformal`·`entropy_pooling` 부재). 사다리의 요점은 "위가 죽으면 아래로" 인데
아래 칸이 비면 한 칸 강등이 아니라 L3 까지 추락한다. 이 파일이 그 칸을 잠근다.

★커버리지는 주장하지 않고 잰다★ Conformal 의 (1−α) 는 이론 하한이다. 유한표본에서
실제로 얼마인지는 **세 봐야** 알고, 이 저장소의 규칙은 재서 적는 것이다.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.engine.conformal import (
    conformal_quantile,
    measure_coverage,
    required_calibration_size,
    split_conformal,
)
from src.engine.entropy_pooling import entropy_pool, pool_weights

# ═══════════════════════════════════════════════════════════════════════════════
# Entropy Pooling
# ═══════════════════════════════════════════════════════════════════════════════


def test_no_views_leaves_the_prior_untouched():
    """뷰가 없으면 사후 = 사전. 이건 실패가 아니라 **정답**이다."""
    p = np.array([0.2, 0.3, 0.5])
    out = entropy_pool(p)
    assert out["available"] and out["feasible"]
    assert np.allclose(out["posterior"], p)
    assert out["kl"] == pytest.approx(0.0, abs=1e-12)


def test_an_equality_view_is_met_exactly():
    """E_q[x] = 목표를 실제로 맞춘다 — 맞췄다고 적기만 하지 않는다."""
    x = np.linspace(-0.2, 0.2, 201)
    p = np.exp(-0.5 * (x / 0.05) ** 2)
    p /= p.sum()
    out = entropy_pool(p, eq=(x.reshape(-1, 1), np.array([0.03])))
    assert out["available"] and out["feasible"], out.get("violations")
    q = np.asarray(out["posterior"])
    assert float(q @ x) == pytest.approx(0.03, abs=1e-6)
    assert out["kl"] > 0, "분포를 옮겼는데 KL 이 0 이다"


def test_the_posterior_is_the_closest_one_that_meets_the_view():
    """★엔트로피 풀링의 요점★ 제약을 만족하는 다른 분포보다 KL 이 작아야 한다."""
    x = np.linspace(-0.2, 0.2, 201)
    p = np.ones_like(x) / x.size
    out = entropy_pool(p, eq=(x.reshape(-1, 1), np.array([0.05])))
    q = np.asarray(out["posterior"])
    kl_q = float(np.sum(q * np.log(q / p)))

    # 같은 평균을 갖지만 더 비튼 분포 — 반드시 KL 이 크다.
    alt = p * np.exp(3.0 * x)
    alt /= alt.sum()
    shift = 0.05 - float(alt @ x)
    alt = alt * np.exp(50.0 * shift * x)
    alt /= alt.sum()
    if abs(float(alt @ x) - 0.05) < 1e-3:      # 대안이 실제로 제약을 만족할 때만 비교
        assert kl_q <= float(np.sum(alt * np.log(alt / p))) + 1e-9


def test_a_slack_inequality_does_not_move_the_prior():
    """이미 만족하는 부등식 뷰는 아무것도 바꾸지 않는다 — 회전율 0."""
    x = np.linspace(-0.2, 0.2, 101)
    p = np.ones_like(x) / x.size
    # E[x] = 0 이고 뷰는 "≤ 0.1" — 이미 참이다.
    out = entropy_pool(p, ineq=(x.reshape(-1, 1), np.array([0.1])))
    assert out["feasible"]
    assert out["kl"] == pytest.approx(0.0, abs=1e-8), "여유 있는 뷰가 분포를 옮겼다"


# ── ★모순된 뷰를 성공으로 위장하지 않는다★ ─────────────────────────────────
def test_contradictory_views_are_reported_not_swallowed():
    """모순된 뷰는 λ 를 무한대로 밀며 '수렴한 것처럼' 끝난다. 풀고 나서 실제로
    검사하지 않으면 화면에 그럴듯한 사후분포가 뜬다."""
    x = np.linspace(-0.1, 0.1, 101)      # 지지집합이 [-0.1, 0.1]
    p = np.ones_like(x) / x.size
    # 지지집합 밖을 요구한다 — 어떤 분포로도 만족할 수 없다.
    out = entropy_pool(p, eq=(x.reshape(-1, 1), np.array([0.5])))
    assert out["available"] is True, "풀려고는 했다"
    assert out["feasible"] is False, "불가능한 뷰를 만족했다고 답했다"
    assert out["violations"], "실현 불가인데 어느 제약인지 말하지 않는다"
    assert out["note"] and "배분하지 마세요" in out["note"]


def test_a_collapsed_posterior_says_the_views_are_too_strong():
    """★숫자가 멀쩡해도 표본 몇 개에 기대는 상태일 수 있다★ ENS 가 그것을 드러낸다."""
    x = np.linspace(-0.1, 0.1, 201)
    p = np.ones_like(x) / x.size
    out = entropy_pool(p, eq=(x.reshape(-1, 1), np.array([0.0995])))  # 거의 끝값
    assert out["feasible"], out.get("violations")
    assert out["ens"] < out["ens_prior"], "분포를 극단으로 밀었는데 ENS 가 안 줄었다"
    assert out["note"] and "유효 시나리오" in out["note"]


def test_asset_views_move_the_expected_return_in_the_stated_direction():
    rng = np.random.default_rng(42)
    R = rng.normal(0.0, 0.02, size=(2000, 3))
    out = pool_weights(R, views=[{"asset": 0, "direction": 1, "value": 0.01}])
    assert out["available"] and out["feasible"], out.get("violations")
    assert out["posterior_mean"][0] == pytest.approx(0.01, abs=1e-3)
    # ★건드리지 않은 자산은 거의 그대로다★ 뷰가 요구한 것 이상은 바꾸지 않는다.
    for i in (1, 2):
        assert abs(out["posterior_mean"][i] - out["prior_mean"][i]) < 0.004


def test_a_view_on_a_nonexistent_asset_is_refused():
    R = np.zeros((10, 2))
    out = pool_weights(R, views=[{"asset": 7, "direction": 1, "value": 0.01}])
    assert out["available"] is False and "자산" in out["reason"]


# ═══════════════════════════════════════════════════════════════════════════════
# Conformal Prediction
# ═══════════════════════════════════════════════════════════════════════════════


def test_the_finite_sample_limit_is_stated_not_hidden():
    """★n 이 모자라면 유한한 구간을 만들 수 없다★ 조용히 최대 잔차로 때우면
    "95% 구간" 이라고 적힌 구간이 실제로는 95% 를 못 준다."""
    assert required_calibration_size(0.05) == 19
    assert required_calibration_size(0.01) == 99

    out = conformal_quantile(np.abs(np.random.default_rng(0).normal(size=10)), alpha=0.05)
    assert out["available"] is False
    assert out["required_n"] == 19
    assert "부족" in out["reason"]

    # 딱 채우면 열린다 — 경계가 실제로 그 자리에 있는지 확인한다.
    ok = conformal_quantile(np.abs(np.random.default_rng(0).normal(size=19)), alpha=0.05)
    assert ok["available"] is True and ok["rank"] == 19


def test_signed_residuals_are_refused():
    """부호를 남기면 이 분위수는 대칭 구간의 반폭이 아니라 한쪽 꼬리를 잰 값이 된다."""
    out = conformal_quantile(np.array([-1.0, 0.5, 2.0]), alpha=0.2)
    assert out["available"] is False and "음수" in out["reason"]


# ── ★커버리지를 주장하지 않고 잰다★ ────────────────────────────────────────
@pytest.mark.parametrize(("alpha", "n_cal"), [(0.1, 500), (0.1, 100), (0.05, 500)])
def test_measured_coverage_matches_the_finite_sample_theory(alpha, n_cal):
    """이론 (1−α) 는 하한이다. 실제로 몇 %인지는 **세 봐야** 안다.

    ★관대한 허용치 대신 이론값과 표본오차로 판정한다★
    처음에는 시행 40회에 `>= (1−α) − 0.01` 로 썼는데, 측정이 0.8966(목표 0.90)으로
    나와 통과했다. 그 통과는 "맞다" 가 아니라 "허용치가 넉넉하다" 였다 — 그래서
    시행을 400회로 늘려 재 봤더니 **0.8994, 이론 하한 0.9002 대비 0.6 SE** 였다.
    off-by-one 이 아니라 표본 변동이었다.

    유한표본 하한은 `⌈(n+1)(1−α)⌉ / (n+1)` 이다. 여기서는 그 값과 대조하고
    허용치를 **측정된 표본오차에서 파생**시킨다.

    ★off-by-one 을 잡는 것은 `n_cal=100` 케이스다 (프로브로 확인)★
    인덱스 한 칸의 효과는 `1/(n+1)` 이라 n 이 커질수록 **작아진다**: n=100 이면
    0.0099 로 잡히지만 n=500 이면 0.002 라 4 SE(≈0.005) 아래로 묻힌다. 그래서
    파라미터에 작은 n 을 넣어 둔다 — 큰 n 만 재면 이 가드는 인덱스 오류를 놓친다.
    (실제로 인덱스를 한 칸 밀어 보니 n=100 만 빨개졌다.)
    """
    trials = 400
    rng = np.random.default_rng(7)
    covs, widths = [], []
    for _ in range(trials):
        cal = rng.normal(0.0, 1.0, size=n_cal)
        test = rng.normal(0.0, 1.0, size=200)
        # 예측기는 상수 0 — 잔차 = |y|. conformal 은 모델 품질과 무관하게 작동한다.
        out = split_conformal(cal, np.zeros_like(cal), np.zeros_like(test), alpha=alpha)
        assert out["available"], out.get("reason")
        m = measure_coverage(test, out["lower"], out["upper"])
        covs.append(m["coverage"]); widths.append(m["mean_width"])

    rank = math.ceil((n_cal + 1) * (1 - alpha))
    theory = rank / (n_cal + 1)
    mean_cov = float(np.mean(covs))
    se = float(np.std(covs)) / math.sqrt(trials)
    tol = max(4 * se, 0.002)      # 4 SE — 인덱스 한 칸(≈1/(n+1))보다 좁다

    print(f"\n[측정] alpha={alpha} n_cal={n_cal} → 커버리지 {mean_cov:.4f} "
          f"(이론 {theory:.4f}, SE {se:.4f}, 평균폭 {np.mean(widths):.3f})")
    assert abs(mean_cov - theory) <= tol, \
        f"측정 {mean_cov:.4f} 가 유한표본 이론값 {theory:.4f} 에서 {tol:.4f} 넘게 벗어났다"


def test_a_heavy_tailed_distribution_still_gets_its_coverage():
    """★분포 가정이 없다는 것이 요점이다★ 정규가 아니어도 커버리지가 성립한다."""
    rng = np.random.default_rng(11)
    covs = []
    for _ in range(40):
        cal = rng.standard_t(df=2, size=600)      # 두꺼운 꼬리
        test = rng.standard_t(df=2, size=600)
        out = split_conformal(cal, np.zeros_like(cal), np.zeros_like(test), alpha=0.1)
        m = measure_coverage(test, out["lower"], out["upper"])
        covs.append(m["coverage"])
    assert float(np.mean(covs)) >= 0.89


def test_mismatched_lengths_are_refused():
    out = split_conformal(np.zeros(5), np.zeros(4), np.zeros(3), alpha=0.1)
    assert out["available"] is False and "길이" in out["reason"]


# ── 사다리 칸이 실제로 채워졌는지 ───────────────────────────────────────────
def test_the_l2_rung_is_now_intact():
    """★M1-C 가 드러낸 구멍이 닫혔는지 사다리에게 직접 묻는다★"""
    from src.engine.capability import resolve
    r = resolve()
    assert r["levels"]["L2"]["ok"] is True, \
        f"L2 가 아직 비어 있다: {r['levels']['L2']['failed']}"
