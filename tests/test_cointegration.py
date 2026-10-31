"""공적분 → VECM / 차분 VAR 분기 + 코어 변수 제한 (P4-M1).

왜 이 파일이 있는가
------------------------------------------------------------------------------
금리·물가·환율·주가는 **레벨이 비정상이고 장기균형을 공유**하는 전형적 조합이다.
그레인저를 레벨에 그대로 걸면 허위회귀(spurious regression)가 된다 — 실측:
`coint` 0곳 · `VECM` 0곳, 즉 이 저장소는 그 검정을 한 번도 하지 않았다.

★외부 리뷰 지적 2 — 자유도 붕괴★
D1+D2 가 계열을 40+ 개로 늘렸다. VECM(K변수, p시차)의 모수는 대략 K²p 이므로
K=40·p=1 이면 **1,600 모수 vs 240 관측**이다. 공분산이 특이에 가까워지고 결과는
노이즈다. 그래서 공적분 검정 **앞에** 강제 스크리닝을 둔다: `K ≤ 7`.
(K=7·p=2 → 98모수 vs 240관측 — 여유롭진 않지만 추정 가능한 구간.)

★PCA/FAVAR 로 줄이지 않는다★ 리뷰가 대안으로 제시했지만 요인은 **해석을 잃는다**.
A8 이 Shapley 로 "무엇이 국면을 움직였나" 를 이름으로 답하게 만들어 놨고, "주성분
3번이 움직였다" 는 그 계약을 깬다. 게다가 `tsfm_latent` 스튜디오가 이미 요인 추출을
담당한다 — 거기서 하는 일을 VECM 앞단에 복제하지 않는다. **차원 축소가 아니라
변수 절제로 푼다.**

★코어 셋은 통계가 아니라 경제로 고른다★ 통계로 고르면 그 선택 자체가 표본을 쓰고
(사후선택 편향) 검정의 p값이 더는 p값이 아니다. 사전 지정이 정직하다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.cointegration import (  # noqa: E402
    MAX_CORE_VARS,
    CoreVariableError,
    analyze_long_run,
    default_core_variables,
)


def _cointegrated(n: int = 240, seed: int = 7):
    """★공통 확률추세를 공유하는 3계열★ — 각자는 비정상인데 선형결합은 정상이다.

    이것이 공적분의 정의이고, 검정이 실제로 작동하는지 재려면 정답을 아는 입력이
    필요하다. 랜덤워크 하나(`trend`)를 셋이 나눠 갖고 잡음만 다르다.
    """
    rng = np.random.default_rng(seed)
    trend = np.cumsum(rng.normal(0, 1.0, n))
    return {
        "A": (trend + rng.normal(0, 0.30, n)).tolist(),
        "B": (0.5 * trend + rng.normal(0, 0.30, n)).tolist(),
        "C": (2.0 * trend + rng.normal(0, 0.30, n)).tolist(),
    }


def _independent_walks(n: int = 240, seed: int = 11):
    """짝 — 공통 추세가 **없는** 랜덤워크들. 공적분이 있으면 안 된다."""
    rng = np.random.default_rng(seed)
    return {k: np.cumsum(rng.normal(0, 1.0, n)).tolist() for k in ("A", "B", "C")}


# ─────────────────────────────────────────────────────────────────────────────
# 1. ★분기 — 그리고 어느 쪽을 왜 골랐는지 응답에 있다★
# ─────────────────────────────────────────────────────────────────────────────
def test_cointegrated_series_take_the_vecm_branch_and_say_why():
    """공통 추세를 공유하면 VECM 이다. 그 판단이 응답에 **글로** 남아야 한다."""
    out = analyze_long_run(_cointegrated())
    assert out["available"] is True, out.get("reason")
    assert out["model"] == "vecm"
    assert out["coint_rank"] >= 1
    assert out["reason"], "어느 모형을 왜 골랐는지 안 적혀 있다"


def test_independent_walks_fall_back_to_a_differenced_var():
    """★짝★ 없으면 무조건 VECM 을 돌려도 위 테스트가 통과한다.

    공적분이 없는데 VECM 을 물리면 존재하지 않는 장기균형을 추정하게 된다.
    """
    out = analyze_long_run(_independent_walks())
    assert out["available"] is True, out.get("reason")
    assert out["model"] == "diff_var"
    assert out["coint_rank"] == 0
    assert out["reason"]


def test_the_branch_records_the_test_it_actually_ran():
    """판정 근거(검정통계량·임계값)를 함께 낸다 — 결론만 내면 블랙박스다."""
    out = analyze_long_run(_cointegrated())
    ev = out["evidence"]
    assert ev["test"] == "johansen_trace"
    assert len(ev["trace_stat"]) == len(ev["crit_95"]) > 0
    assert any(s > c for s, c in zip(ev["trace_stat"], ev["crit_95"], strict=True))


# ─────────────────────────────────────────────────────────────────────────────
# 2. ★코어 변수 제한 — 자유도 붕괴를 계산 전에 막는다★
# ─────────────────────────────────────────────────────────────────────────────
def test_too_many_variables_are_refused_before_any_estimation():
    """★리뷰 지적 2★ 40변수를 그대로 넣으면 추정하지 않고 **거부**한다.

    "돌긴 도는데 노이즈" 가 가장 위험하다 — 숫자가 나오면 사람은 그것을 믿는다.
    """
    many = {f"V{i}": np.cumsum(np.random.default_rng(i).normal(0, 1, 240)).tolist()
            for i in range(MAX_CORE_VARS + 1)}
    with pytest.raises(CoreVariableError) as e:
        analyze_long_run(many)
    msg = str(e.value)
    assert str(MAX_CORE_VARS) in msg, "상한이 몇인지 안 알려준다"
    assert str(MAX_CORE_VARS + 1) in msg, "몇 개를 넣었는지 안 알려준다"


def test_exactly_the_limit_is_allowed():
    """짝 — 상한 자체는 통과한다. 안 그러면 상한이 사실상 K−1 이다."""
    exact = {f"V{i}": np.cumsum(np.random.default_rng(i).normal(0, 1, 240)).tolist()
             for i in range(MAX_CORE_VARS)}
    assert analyze_long_run(exact)["available"] in (True, False)


def test_the_limit_is_small_enough_to_be_estimable_at_this_sample_size():
    """★상한이 근거를 갖는다★ K²p 모수가 관측보다 충분히 적어야 한다.

    상한을 20 으로 올려 놓고 "제한했다" 고 말하면 제한이 아니다.
    """
    assert MAX_CORE_VARS <= 7
    assert MAX_CORE_VARS ** 2 * 2 < 240 / 2, "K=상한, p=2 에서 자유도가 부족하다"


def test_the_default_core_set_is_economically_specified_not_statistically_picked():
    """★통계로 고르면 사후선택 편향이 생긴다★ 사전 지정이 정직하다.

    기본 셋은 데이터를 보지 않고 정해지므로 **입력과 무관하게 같아야** 한다.
    """
    assert default_core_variables() == default_core_variables()
    core = default_core_variables()
    assert 0 < len(core) <= MAX_CORE_VARS
    for expected in ("KR_BASE_RATE", "KR_CPI", "USD_KRW", "KOSPI"):
        assert expected in core, f"{expected} 가 코어에 없다"


def test_every_default_core_variable_is_a_declared_series():
    """짝 — 코어에 적어 놓고 수집되지 않는 키면 그 축은 영원히 빈다."""
    from src.data.source_registry import all_specs
    declared = {s.key for s in all_specs()}
    for key in default_core_variables():
        assert key in declared, f"{key}: 코어인데 레지스트리에 없다"


# ─────────────────────────────────────────────────────────────────────────────
# 3. 표본·입력이 모자라면 숫자를 내지 않는다
# ─────────────────────────────────────────────────────────────────────────────
def test_short_samples_are_refused_with_a_reason_not_a_number():
    """★관측이 모자라면 사유를 낸다★ 짧은 표본의 VECM 은 그럴듯한 노이즈다."""
    short = {k: v[:20] for k, v in _cointegrated().items()}
    out = analyze_long_run(short)
    assert out["available"] is False
    assert out["reason"]
    assert "model" not in out or out.get("coint_rank") is None


def test_a_single_variable_cannot_have_a_long_run_relationship():
    """공적분은 둘 이상 사이의 관계다 — 하나로는 정의되지 않는다."""
    out = analyze_long_run({"A": _cointegrated()["A"]})
    assert out["available"] is False
    assert out["reason"]


def test_the_span_says_how_many_observations_were_actually_used():
    """A8 규칙 — 요청보다 짧으면 응답이 그 사실을 말한다."""
    out = analyze_long_run(_cointegrated(n=240))
    assert out["span"]["n"] == 240
    assert out["span"]["k"] == 3
