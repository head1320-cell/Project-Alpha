"""심은 효과의 척도 — ★양성 통제의 손잡이★ (A3-a)
==============================================================================
검정력을 재려면 "정답이 있다" 는 것을 아는 패널에서 **효과 크기를 바꿔 가며**
관문을 돌려야 한다. `t3_transmission.build_panel` 은 수익을 `_PROF[regime]` 에서
만드는 이미 심어진 패널이므로, 필요한 것은 손잡이 하나뿐이다.

★두 가지가 계약이다★

⑴ `scale=1.0` 이 현행과 **비트 동일**해야 한다. 아니면 M1~M5·T3 의 기존 결과가
   조용히 달라진다.
⑵ 척도만 변하고 **잡음 실현은 고정**되어야 한다. `rng.normal(mu, sd)` 는 mu·sd
   와 무관하게 같은 수의 난수를 소비하므로 성립한다 — 이것을 테스트가 건다.
   고정되지 않으면 검정력 곡선의 차이가 효과 때문인지 다른 난수 때문인지 모른다.
"""

from __future__ import annotations

import hashlib
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import scripts.t3_transmission as t3  # noqa: E402
from scripts.t3_transmission import build_panel, scaled_profiles  # noqa: E402

SCALED_KEYS = (0, 2, 3)      # 공통 드리프트 · EQ 틸트 · FI 틸트
FIXED_KEYS = (1, 4)          # 공통 변동성 · 특이 변동성


def _hash(a: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(a, dtype=np.float64).tobytes()).hexdigest()


# ══════════════════════════════════════════════════════════════════════════
# ★비트 동일 — 기존 결과를 조용히 바꾸지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_scale_one_reproduces_the_profile_values():
    """값은 같지만 ★마지막 비트까지는 아니다★ — 아래 두 테스트가 그 차이를 다룬다."""
    out = scaled_profiles(1.0)
    assert set(out) == set(t3._PROF)
    for k in t3._PROF:
        assert out[k] == pytest.approx(t3._PROF[k], abs=1e-18)


def test_the_general_formula_is_not_bit_exact_at_scale_one():
    """★단축 분기가 왜 필요한지를 못 박는다★

    `m + 1.0·(p − m)` 는 부동소수에서 `p` 로 정확히 돌아오지 않는다 —
    `Goldilocks[3]` 과 `Stagflation[0]` 이 1 ulp 어긋난다. 그 어긋남이
    `rng.normal(mu, sd)` 를 통과해 패널 전체를 바꾼다. 이 사실이 바뀌면
    `build_panel` 의 단축을 지울 수 있다는 뜻이므로 여기서 알려 준다.
    """
    assert scaled_profiles(1.0) != t3._PROF


#: ★동결 해시★ `_PROF` 경로로 만든 패널의 sha256. `build_panel(36)` 과
#: `build_panel(36, scale=1.0)` 을 서로 비교하면 **둘 다 scale=1.0 이라 공허하다**
#: — 실제로 그렇게 썼다가 변이 P3(단축 제거)이 살아남아서 발견했다.
FROZEN = {36: "31c8a87614b931e4ed0a34686542db161e08131ec25011050169fe2d7d6e62e2",
          84: "abcec5cfd0d3a39c0d1fec5bc6d297bc8421ebc928ff3c6cfe1f1bdd3b65d2a3"}


@pytest.mark.parametrize("months", [36, 84])
def test_the_default_panel_matches_the_frozen_hash(months):
    """★골든★ 이것이 깨지면 M1~M5(`13ba50a`)와 T3 의 기존 결과가 달라진다."""
    assert _hash(build_panel(months=months)[1]) == FROZEN[months]


@pytest.mark.parametrize("months", [36, 84])
def test_an_explicit_scale_of_one_also_matches_the_frozen_hash(months):
    """명시적 `scale=1.0` 도 같은 패널이어야 한다 — 단축 분기의 계약."""
    assert _hash(build_panel(months=months, scale=1.0)[1]) == FROZEN[months]


def test_a_scale_away_from_one_changes_the_panel():
    """★짝★ — 해시 테스트를 통과시키려고 척도를 무시하는 구현을 배제한다."""
    assert _hash(build_panel(months=36, scale=2.0)[1]) != FROZEN[36]


def test_the_default_signature_still_works_positionally():
    """기존 호출부(`research_panel.synthetic_panel` · t3 테스트 3종)를 깨지 않는다."""
    names, R, dates, points, beta = build_panel(36)
    assert len(names) == 6 and R.shape[1] == 6
    assert len(R) == 36 * 21                 # 영업일 수는 정확하다
    assert len(points) == len({d.strftime("%Y-%m") for d in dates})


# ══════════════════════════════════════════════════════════════════════════
# ★1차 모멘트만 늘린다★ — ③ 예측 스킬을 리스크 국면 인식과 섞지 않는다
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("scale", [0.0, 0.5, 2.0, 4.0])
def test_only_the_first_moment_parameters_are_scaled(scale):
    base, out = t3._PROF, scaled_profiles(scale)
    assert set(out) == set(base)
    for j in FIXED_KEYS:
        for k in base:
            assert out[k][j] == base[k][j], f"{k}[{j}] 가 움직였다"


@pytest.mark.parametrize("scale", [0.0, 0.5, 2.0, 4.0])
def test_the_cross_regime_mean_is_preserved(scale):
    """★평균 둘레로 늘린다★ — 전체 수준이 아니라 **국면 간 차이**만 바꾼다.

    수준까지 움직이면 척도를 올릴 때 전략 전체의 수익이 좋아져 관문이 국면
    정보가 아니라 드리프트를 보고 통과한다.
    """
    base, out = t3._PROF, scaled_profiles(scale)
    for j in SCALED_KEYS:
        b = np.mean([base[k][j] for k in base])
        o = np.mean([out[k][j] for k in out])
        assert o == pytest.approx(b, abs=1e-15)


def test_a_scale_of_zero_erases_every_regime_difference():
    """★음성 통제의 극단★ — 척도 0 이면 국면이 아무것도 가르지 않는다."""
    out = scaled_profiles(0.0)
    for j in SCALED_KEYS:
        vals = {round(out[k][j], 15) for k in out}
        assert len(vals) == 1, f"index {j} 에 아직 국면 차이가 남았다"


def test_scaling_widens_the_regime_spread_monotonically():
    """★짝★ — 상수를 내는 구현을 배제한다."""
    def spread(scale):
        p = scaled_profiles(scale)
        return max(p[k][0] for k in p) - min(p[k][0] for k in p)
    assert spread(0.0) < spread(1.0) < spread(2.0) < spread(4.0)
    assert spread(2.0) == pytest.approx(2 * spread(1.0))


# ══════════════════════════════════════════════════════════════════════════
# ★잡음 실현은 척도에 대해 고정★ — 실험 설계의 핵심
# ══════════════════════════════════════════════════════════════════════════
def test_the_regime_path_is_identical_across_scales():
    """국면 경로는 `_P_TRUE` 에서 나오므로 척도와 무관해야 한다."""
    a = build_panel(months=36, scale=1.0)[3]
    b = build_panel(months=36, scale=5.0)[3]
    assert [p["regime"] for p in a] == [p["regime"] for p in b]


def test_the_noise_realisation_is_held_fixed_across_scales():
    """★차이가 효과에서만 온다★

    `rng.normal(mu, sd)` 는 mu·sd 와 무관하게 같은 난수를 소비하므로, 두 척도의
    수익 차이는 **심은 효과의 차이 그대로**여야 한다. 잔차가 남으면 난수 소비가
    갈라진 것이고, 그러면 검정력 곡선의 차이를 효과 탓으로 돌릴 수 없다.
    """
    _, R1, _, points, beta = build_panel(months=36, scale=1.0)
    _, R3, _, _, _ = build_panel(months=36, scale=3.0)
    diff = R3 - R1
    # 심은 효과의 차이만 남는다 — 각 행이 (드리프트차·beta + 틸트차) 로 설명된다.
    assert diff.shape == R1.shape
    assert np.abs(diff).max() > 0                       # 실제로 달라지긴 한다
    # 같은 달의 모든 영업일에서 차이가 **동일**하다(잡음이 상쇄됐다는 뜻).
    import pandas as pd
    idx = pd.DatetimeIndex(build_panel(months=36)[2])
    mo = pd.Series(idx).dt.strftime("%Y-%m").values
    for m in np.unique(mo)[:6]:
        rows = diff[mo == m]
        assert np.allclose(rows, rows[0], atol=1e-15), f"{m} 에서 잡음이 남았다"


def test_scaling_does_not_touch_the_module_constant():
    """★전역을 오염시키지 않는다★ — 순수 함수다."""
    before = dict(t3._PROF)
    scaled_profiles(7.0)
    build_panel(months=12, scale=7.0)
    assert t3._PROF == before
