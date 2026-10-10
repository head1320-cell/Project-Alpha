"""regime_drivers — 정확 Shapley 분해가 정말 정확한가 (A8).

★이 파일이 지키는 것★
1. **효율성 공리**: `Σφ_i = P(x) − P(∅)` 가 부동소수 오차 안에서 성립한다.
   이것이 워터폴의 존재 근거다 — 25% 에서 출발해 막대를 더하면 최종 확률에
   도달해야 하고, 도달하지 못하면 화면이 거짓말을 하는 것이다.
2. **기저가 정확히 0.25**: 모든 지표를 역사 평균에 두면 두 축이 0 이고 Φ(0)=0.5 라
   네 사분면이 각각 25% 다. 이 값이 흔들리면 워터폴의 시작점이 무의미해진다.
3. **대칭성·더미 공리**: 기여가 0 인 지표는 φ 도 0 이다.
4. 미가용은 사유와 함께 — 지표가 없으면 0 을 지어내지 않는다.
"""

from __future__ import annotations

import math
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.engine.regime_drivers import REGIMES, regime_drivers  # noqa: E402


class _S:
    """regime_axes 가 기대하는 최소 인터페이스 — `.values` 만 본다."""

    def __init__(self, values):
        self.values = values


def _series(n: int = 90) -> dict:
    """뚜렷한 성장 확장 + 물가 둔화 계열 (골디락스 쪽으로 기울게)."""
    g = [100 * (1 + 0.02 * i / 100) for i in range(n)]
    c = [100 * (1 + 0.004 * i / 100) for i in range(n)]
    return {
        "KR_LEADING_CYCLE": _S([1.0 + 0.002 * i for i in range(n)]),
        "KR_IP": _S(g),
        "KOSPI": _S(g),
        "KR_CPI": _S(c),
        "T10YIE": _S([2.2 - 0.004 * i for i in range(n)]),
    }


def test_efficiency_axiom_holds_exactly():
    """★워터폴이 최종 확률에 정확히 도달하는가★

    Shapley 값의 효율성 공리는 `Σφ = v(N) − v(∅)` 다. 근사 알고리즘(KernelSHAP)은
    이걸 표본오차만큼 어기지만, 완전열거는 어길 수 없다. 어긴다면 구현 버그다.
    """
    r = regime_drivers(_series(), "kr")
    assert r["available"] is True, r.get("reason")

    # ① 엄밀한 주장 — **반올림 전** 값으로 잰다. 공리는 오차 없이 성립해야 한다.
    assert abs(r["efficiency_residual"]) < 1e-9, r["efficiency_residual"]

    # ② 화면이 실제로 더하는 값 — 공개된 정밀도로 잰다.
    #    ★첫 판은 여기서 1e-6 을 요구해 실패했다★ φ 는 5자리, 확률·기저는 4자리로
    #    반올림해 내보내므로 5개를 더하면 최대 ~2.5e-5, 차이 쪽은 ~5e-5 의 반올림
    #    오차가 있다. 1e-6 은 공개 정밀도보다 촘촘한 요구였고, 엔진이 아니라 테스트가
    #    틀린 것이었다. 엄밀한 보장은 ①이 하고, 여기서는 화면에 보이는 자릿수에서
    #    워터폴이 맞아떨어지는지만 본다.
    total = sum(d["phi"] for d in r["drivers"])
    gap = r["probability"] - r["baseline"]
    assert total == pytest.approx(gap, abs=2e-4), (
        f"Σφ={total} 인데 P−기저={gap} 다 — 워터폴이 최종 확률에 도달하지 못한다")


def test_baseline_is_exactly_a_quarter():
    """★기저는 정확히 25% 다★ 모든 지표가 역사 평균이면 축이 0, Φ(0)=0.5, 사분면 곱 0.25.

    이 값이 0.25 가 아니면 '아무것도 모를 때의 확률' 이라는 워터폴의 시작점이
    의미를 잃는다.
    """
    for regime in REGIMES:
        r = regime_drivers(_series(), "kr", regime=regime)
        assert r["available"] is True
        assert r["baseline"] == pytest.approx(0.25, abs=1e-9), regime


def test_all_four_regimes_decompose_and_probabilities_sum_to_one():
    """네 국면 각각을 분해할 수 있고, 그 확률들의 합은 1 이다."""
    total = 0.0
    for regime in REGIMES:
        r = regime_drivers(_series(), "kr", regime=regime)
        assert r["available"] is True
        assert r["regime"] == regime
        total += r["probability"]
    assert total == pytest.approx(1.0, abs=1e-3), total


def test_exact_enumeration_not_sampling():
    """★근사하지 않는다★ 부분집합을 전부 셌다는 사실이 응답에 남아야 한다.

    표본추출로 바꾸면 이 수치가 맞지 않게 되고, 그때는 효율성도 오차만큼 깨진다.
    """
    r = regime_drivers(_series(), "kr")
    assert r["method"] == "exact-shapley-enumeration"
    assert r["n_coalitions"] == 2 ** r["n_features"]
    assert r["n_features"] == 5, "KR 축은 지표 5개(성장 3 + 물가 2)"


def test_zero_contribution_feature_gets_zero_phi():
    """★더미 공리★ 축 기여가 0 인 지표는 확률에도 기여하지 않는다.

    상수 계열은 z=0 이라 기여가 0 이다. 그런데도 φ 가 붙는다면 가치함수가
    그 지표를 통해 무언가를 새고 있다는 뜻이다.
    """
    s = _series()
    s["KOSPI"] = _S([100.0] * 90)          # 완전한 상수 → 변동 없음
    r = regime_drivers(s, "kr")
    assert r["available"] is True
    kospi = [d for d in r["drivers"] if d["key"] == "KOSPI"]
    if kospi:            # 상수 계열은 z 가 None 이라 아예 빠질 수도 있다
        assert kospi[0]["axis_contribution"] == pytest.approx(0.0, abs=1e-6)
        assert kospi[0]["phi"] == pytest.approx(0.0, abs=1e-6)


def test_no_indicators_is_unavailable_not_zero():
    """지표가 하나도 없으면 0 이 아니라 미가용 + 사유다."""
    r = regime_drivers({}, "kr")
    assert r["available"] is False
    assert r["reason"]
    assert "drivers" not in r, "미가용인데 드라이버 목록을 만들었다"


def test_sign_can_flip_between_axis_and_probability():
    """★두 층을 따로 보여 줘야 하는 이유가 여기 있다★

    골디락스는 성장↑ **물가↓** 다. 그래서 물가축을 **낮추는** 지표는 축 기여가
    음수이면서 골디락스 확률에는 **양의** 기여를 한다. 한 층만 보여 주면 화면이
    "물가가 골디락스를 깎았다" 로 읽히는데 사실은 정반대다.
    """
    r = regime_drivers(_series(), "kr", regime="Goldilocks")
    assert r["available"] is True
    infl = [d for d in r["drivers"] if d["axis"] == "inflation"]
    assert infl, "물가축 지표가 없다 — 검사 대상이 없다"
    flipped = [d for d in infl if d["axis_contribution"] < 0 < d["phi"]]
    assert flipped, (
        "물가축을 낮추는 지표가 골디락스 확률을 올리지 않았다 — "
        f"부호 관계가 뒤집혔거나 표본이 그렇지 않다: {infl}")


def test_phi_is_finite_and_bounded():
    """φ 는 유한하고 확률 범위를 넘지 않는다 (수치 안전)."""
    r = regime_drivers(_series(), "kr")
    for d in r["drivers"]:
        assert math.isfinite(d["phi"]), d
        assert -1.0 <= d["phi"] <= 1.0, d
