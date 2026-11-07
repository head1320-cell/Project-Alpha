"""국면확률 출처 계약 — ★배분에 닿을 수 있는 것은 하나뿐★ (MS1-a 커밋 2)
==============================================================================
계획: `docs/plans/2026-08-25-macro-vnext-plan.md` §1.5 · §1.10.0 I5

저장소는 같은 4국면 분류체계 위에 확률 객체를 **셋** 갖고 있고 셋 다 다른 답을 낸다
(실측: 축확률 0.535 · Markov 0.964 · k단계 0.601). 그런데 최적화기에는 **하드 라벨
1.000** 이 간다. 이 계약은 그 넷 중 **k단계 예측만** 배분에 닿게 한다.

★이름이 아니라 값으로 거른다★ `"forecast" 가 이름에 있으면 통과` 같은 규약은
리팩터 한 번에 조용히 깨진다. `usage` 는 **생성 함수가 정하고 호출자가 바꿀 수 없다**.
"""

from __future__ import annotations

import dataclasses

import pytest

from src.engine.regime_probability import (
    USAGE_DIAGNOSTIC,
    USAGE_FORBIDDEN,
    USAGE_PORTFOLIO,
    RegimeProbabilities,
    from_axis,
    from_k_step_forecast,
    from_markov,
    from_smoothed,
    require_portfolio_source,
)

REGIMES = ["Goldilocks", "Reflation", "Stagflation", "Disinflation"]


def _rows():
    """`transition_posterior` 가 내는 모양의 최소 fixture.

    ★`k_step_forecast` 는 `mean` 이 아니라 `counts` 로 사후 α 를 되짚는다★
    (`regime_transitions.py:197`). 처음에 `mean` 만 넣었다가 `KeyError: 'counts'` 로
    잡혔다 — 실제 소비 필드를 넣어야 fixture 가 계약을 대변한다.
    """
    stay, off = 14, 2       # 지속 선호 · 행 합 20
    return [{"from": r,
             "counts": [(stay if q == r else off) for q in REGIMES],
             "n": stay + off * 3,
             "mean": {q: ((stay if q == r else off) / 20.0) for q in REGIMES},
             "shrunk": False}
            for r in REGIMES]


# ══════════════════════════════════════════════════════════════════════════
# 세 출처가 서로 다른 usage 를 갖는다
# ══════════════════════════════════════════════════════════════════════════
def test_three_sources_have_declared_usage():
    fc = from_k_step_forecast(_rows(), "Goldilocks", k=3, mode="live")
    ax = from_axis({"probs": {r: 0.25 for r in REGIMES},
                    "detail": {"growth": 0.18, "inflation": -0.15}})
    mk = from_markov({"probs": {"Goldilocks": 0.96, "Reflation": 0.0,
                                "Stagflation": 0.0, "Disinflation": 0.04}})

    assert fc.usage == USAGE_PORTFOLIO
    assert ax.usage == USAGE_DIAGNOSTIC
    assert mk.usage == USAGE_DIAGNOSTIC
    assert from_smoothed({r: 0.25 for r in REGIMES}, t_index=5).usage == USAGE_FORBIDDEN


def test_forecast_carries_step_and_interval():
    fc = from_k_step_forecast(_rows(), "Goldilocks", k=3, mode="live")
    assert fc.step_months == 3
    assert fc.ci90 is not None            # 사후예측 구간을 버리지 않는다
    assert fc.source == "k_step_forecast"
    assert abs(sum(fc.probs.values()) - 1.0) < 1e-6


# ══════════════════════════════════════════════════════════════════════════
# ★I5★ 구조적 차단
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("maker", [
    lambda: from_axis({"probs": {r: 0.25 for r in REGIMES}, "detail": {}}),
    lambda: from_markov({"probs": {r: 0.25 for r in REGIMES}}),
    lambda: from_smoothed({r: 0.25 for r in REGIMES}, t_index=5),
])
def test_portfolio_path_rejects_non_portfolio_usage(maker):
    """★I5★ `usage != portfolio` 는 배분 경로에서 **거부**된다 — 조용히 통과 금지."""
    with pytest.raises(ValueError) as e:
        require_portfolio_source(maker())
    assert "배분" in str(e.value)


def test_portfolio_path_accepts_forecast():
    """짝 — 가드가 전부를 막으면 안 된다."""
    fc = from_k_step_forecast(_rows(), "Goldilocks", k=1, mode="live")
    assert require_portfolio_source(fc) is fc


def test_filtered_sources_cannot_be_marked_portfolio():
    """★I5★ `usage` 는 생성 함수가 정한다 — 호출자가 바꿀 수 없다.

    dataclass 가 frozen 이므로 대입이 막히고, `dataclasses.replace` 로 우회한
    객체는 배분 경로가 다시 거부한다(값 검사이지 신뢰가 아니다).
    """
    ax = from_axis({"probs": {r: 0.25 for r in REGIMES}, "detail": {}})
    with pytest.raises(dataclasses.FrozenInstanceError):
        ax.usage = USAGE_PORTFOLIO                     # type: ignore[misc]

    # 우회로 만들어도 출처가 남아 있으므로 거부된다.
    forged = dataclasses.replace(ax, usage=USAGE_PORTFOLIO)
    with pytest.raises(ValueError) as e:
        require_portfolio_source(forged)
    assert "filtered_axis" in str(e.value)


def test_smoothed_is_forbidden_even_when_labelled_portfolio():
    forged = dataclasses.replace(
        from_smoothed({r: 0.25 for r in REGIMES}, t_index=5), usage=USAGE_PORTFOLIO)
    with pytest.raises(ValueError):
        require_portfolio_source(forged)


def test_last_index_smoothed_is_named_filtered_not_smoothed():
    """마지막 시점의 smoothed 는 filtered 와 같다 — 그러면 **filtered 라고 부른다**.

    `"smoothed"` 라는 이름이 배분 근처에 나타나지 않게 하는 것이 목적이다.
    """
    obj = from_smoothed({r: 0.25 for r in REGIMES}, t_index=5, t_last=5)
    assert obj.source == "filtered_markov"
    assert obj.usage == USAGE_DIAGNOSTIC        # 여전히 배분 금지
    assert "smoothed" not in obj.source


# ══════════════════════════════════════════════════════════════════════════
# 불일치를 숨기지 않는다 · 날카로움
# ══════════════════════════════════════════════════════════════════════════
def test_sharpness_is_one_for_hard_label_and_lower_when_diffuse():
    """`sharpness = 1 − H(π)/ln R` — 하드 라벨 1.0, 퍼진 분포일수록 낮다."""
    hard = RegimeProbabilities(
        source="k_step_forecast", step_months=1,
        probs={"Goldilocks": 1.0, "Reflation": 0.0,
               "Stagflation": 0.0, "Disinflation": 0.0},
        usage=USAGE_PORTFOLIO, mode="live")
    flat = RegimeProbabilities(
        source="k_step_forecast", step_months=1,
        probs={r: 0.25 for r in REGIMES}, usage=USAGE_PORTFOLIO, mode="live")

    assert hard.sharpness == pytest.approx(1.0, abs=1e-12)
    assert flat.sharpness == pytest.approx(0.0, abs=1e-12)
    measured = RegimeProbabilities(
        source="k_step_forecast", step_months=3,
        probs={"Goldilocks": 0.6007, "Reflation": 0.1332,
               "Stagflation": 0.0974, "Disinflation": 0.1687},
        usage=USAGE_PORTFOLIO, mode="live")
    assert 0.15 < measured.sharpness < 0.30      # 실측 0.206 근방


def test_disagreement_between_sources_is_surfaced_not_hidden():
    """축확률과 예측이 갈리면 **둘 다** 실린다 — 하나를 골라 지우지 않는다."""
    from src.engine.regime_probability import disagreement_block
    ax = from_axis({"probs": {"Goldilocks": 0.535, "Reflation": 0.2074,
                              "Stagflation": 0.072, "Disinflation": 0.1856},
                    "detail": {}})
    fc = from_k_step_forecast(_rows(), "Goldilocks", k=3, mode="live")
    blk = disagreement_block(portfolio=fc, diagnostics=[ax])

    assert blk["portfolio"]["source"] == "k_step_forecast"
    assert any(d["source"] == "filtered_axis" for d in blk["diagnostics"])
    assert "max_abs_gap" in blk


def test_to_dict_round_trips_the_contract_fields():
    fc = from_k_step_forecast(_rows(), "Goldilocks", k=2, mode="backtest")
    d = fc.to_dict()
    for key in ("source", "step_months", "probs", "usage", "mode", "sharpness"):
        assert key in d
    assert d["usage"] == USAGE_PORTFOLIO
    assert d["mode"] == "backtest"


def test_unavailable_forecast_is_reported_not_faked():
    """`k_step_forecast` 가 못 내면 확률을 지어내지 않는다."""
    with pytest.raises(ValueError) as e:
        from_k_step_forecast(_rows(), "없는국면", k=3, mode="live")
    assert "없는국면" in str(e.value) or "국면" in str(e.value)
