"""③ 신호 관문 ★리포트 계약★ — 사전등록을 코드가 지킨다 (A4)
==============================================================================
사전등록: `docs/superpowers/specs/2026-08-30-signal-gate-preregistration.md`

문서는 코드를 강제하지 못한다. 그래서 주 통계·지평·임계·판정 규칙을 리포트에
**구조로** 싣고 테스트가 그것을 건다 — M3 에서 쓴 규율 그대로다.

★판정 함수는 순수 함수다★ 데이터를 만들어 규칙을 확인하려 하면 픽스처의 우연을
계약으로 착각한다(S6 에서 치른 값). 여기서는 규칙에 직접 값을 넣는다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from scripts.regime_signal_gate import (  # noqa: E402
    ARM_CONST,
    ARM_ON,
    DECISION_RULE,
    PRIMARY,
    THRESHOLD_PCT,
    decide_signal_verdict,
    eta_by_arm,
    run,
)

from src.engine import regime_surrogates as rs  # noqa: E402
from src.engine.regime_signal import (  # noqa: E402
    DECISIVE_HORIZON,
    HORIZON_CONTEMPORANEOUS,
    HORIZON_FORWARD,
)
from src.engine.research_verdict import (  # noqa: E402
    VERDICT_EVIDENCE_OF_NO_EFFECT,
    VERDICT_INCONCLUSIVE,
    VERDICT_NO_EVIDENCE,
    VERDICT_POSITIVE,
    VERDICT_UNDERPOWERED,
    require_power_fields,
)


# ══════════════════════════════════════════════════════════════════════════
# 사전등록된 상수 — ★결과를 보고 바꾸지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_preregistered_constants_are_what_the_document_says():
    assert PRIMARY == "eta_squared"
    assert THRESHOLD_PCT == (5.0, 95.0)
    assert DECISIVE_HORIZON == HORIZON_FORWARD == 1
    assert HORIZON_CONTEMPORANEOUS == 0


# ══════════════════════════════════════════════════════════════════════════
# ★판정 — 널 두 종류의 연언, 단측★
# ══════════════════════════════════════════════════════════════════════════
def _pcts(shift, markov):
    return {rs.NULL_SHIFT: shift, rs.NULL_MARKOV: markov}


def test_both_nulls_above_passes():
    v = decide_signal_verdict(_pcts(100.0, 98.0), power=0.9)
    assert v["passed"] is True and v["verdict"] == VERDICT_POSITIVE
    assert v["shift_above"] is True and v["markov_above"] is True


@pytest.mark.parametrize("shift,markov", [(100.0, 50.0), (50.0, 100.0)])
def test_only_one_null_above_is_inconclusive(shift, markov):
    """★연언이다★ — 하나만 넘으면 결론이 아니다."""
    v = decide_signal_verdict(_pcts(shift, markov), power=0.9)
    assert v["passed"] is False and v["verdict"] == VERDICT_INCONCLUSIVE


def test_neither_null_above_with_demonstrated_power_is_evidence_of_no_effect():
    v = decide_signal_verdict(_pcts(40.0, 40.0), power=0.95)
    assert v["verdict"] == VERDICT_EVIDENCE_OF_NO_EFFECT


def test_neither_null_above_without_power_is_not_evidence_of_no_effect():
    """★만다트 §4★ — 못 넘은 것과 효과가 없는 것은 다른 진술이다."""
    assert decide_signal_verdict(_pcts(40.0, 40.0),
                                 power=0.30)["verdict"] == VERDICT_UNDERPOWERED
    assert decide_signal_verdict(_pcts(40.0, 40.0),
                                 power=None)["verdict"] == VERDICT_NO_EVIDENCE


def test_the_gate_is_one_sided_being_far_below_does_not_pass():
    """★단측★ 진짜 라벨이 무작위보다 **덜** 설명하는 것은 스킬이 아니다.

    M1~M5 의 `sharpe_diff` 는 양측이었지만 η² 는 분산 설명 **비율**이라 통계의
    의미가 다르다. 이 짝이 없으면 `side != inside` 로 쓴 구현이 산다.
    """
    v = decide_signal_verdict(_pcts(0.0, 0.0), power=0.95)
    assert v["passed"] is False
    assert v["shift_above"] is False and v["markov_above"] is False
    assert any("아래" in r or "below" in r for r in v["why"]), v["why"]


def test_exactly_at_the_threshold_does_not_pass():
    """★경계를 못 박는다★ — 분위 95 **초과**여야 한다."""
    assert decide_signal_verdict(_pcts(95.0, 100.0), power=0.9)["passed"] is False
    assert decide_signal_verdict(_pcts(95.01, 100.0), power=0.9)["passed"] is True


def test_a_missing_percentile_cannot_pass():
    """★미상 ≠ 통과★ 널이 비면 분위가 없다."""
    v = decide_signal_verdict(_pcts(None, 100.0), power=0.9)
    assert v["passed"] is False and v["verdict"] == VERDICT_NO_EVIDENCE


def test_the_threshold_is_a_parameter_and_labelled_a_convention():
    """★같은 분위, 다른 관례 → 다른 판정★"""
    m = _pcts(93.0, 97.0)
    assert decide_signal_verdict(m, power=0.9)["passed"] is False
    loose = decide_signal_verdict(m, power=0.9, threshold_pct=(10.0, 90.0))
    assert loose["passed"] is True and loose["convention"] is True


def test_the_verdict_names_both_axes_and_does_not_call_them_spa():
    """★SPA 인 척하지 않는다★ — `classify` 의 인자 이름을 그대로 쓰면 오독된다."""
    v = decide_signal_verdict(_pcts(100.0, 100.0), power=0.9)
    assert v["gate_axes"] == {"primary_null": rs.NULL_SHIFT,
                              "secondary_null": rs.NULL_MARKOV}
    assert "spa" not in str(v["gate_axes"]).lower()


def test_the_verdict_carries_the_power_fields():
    v = decide_signal_verdict(_pcts(100.0, 100.0), power=0.9)
    assert require_power_fields(v) == []


# ══════════════════════════════════════════════════════════════════════════
# 팔별 η² — ★음성 통제는 보고하되 판정에 넣지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def _points(labels):
    return [{"t": f"2020-{i + 1:02d}", "regime": g} for i, g in enumerate(labels)]


def test_the_constant_arm_explains_nothing_by_construction():
    """국면이 하나뿐이면 국면 간 제곱합이 구조적으로 0 이다."""
    import numpy as np
    pts = _points(["G", "R", "S", "D"] * 6)
    m = np.random.default_rng(0).normal(0, 0.01, (len(pts), 3))
    out = eta_by_arm(pts, m, horizon=HORIZON_CONTEMPORANEOUS)
    assert out[ARM_CONST] == pytest.approx(0.0, abs=1e-12)
    assert out[ARM_ON] > out[ARM_CONST]


def test_the_real_arm_beats_the_constant_arm_when_labels_carry_signal():
    """★짝★ — 두 팔이 같은 값을 내는 구현을 배제한다."""
    import numpy as np
    labels = ["G"] * 12 + ["S"] * 12
    pts = _points(labels)
    m = np.array([[1.0]] * 12 + [[-1.0]] * 12)
    out = eta_by_arm(pts, m, horizon=HORIZON_CONTEMPORANEOUS)
    assert out[ARM_ON] == pytest.approx(1.0)
    assert out[ARM_CONST] == pytest.approx(0.0, abs=1e-12)


# ══════════════════════════════════════════════════════════════════════════
# 리포트 계약
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def report():
    return run(months=36, seed=20260825, power_scales=(1.0, 4.0),
               power_seeds=(0, 1), n_markov=20)


def test_the_report_carries_the_preregistration_in_its_own_body(report):
    """★사전등록을 리포트가 스스로 싣는다★ 문서는 코드를 강제하지 못한다."""
    pre = report["preregistered"]
    assert pre["primary_statistic"] == PRIMARY
    assert pre["decisive_horizon"] == DECISIVE_HORIZON
    assert pre["threshold_pct"] == [5.0, 95.0]
    assert pre["one_sided"] is True
    assert pre["decision_rule"] == DECISION_RULE
    assert pre["convention"] is True


def test_both_horizons_are_reported_but_only_forward_decides(report):
    """★①정보 표현력과 ③예측 스킬을 같은 리포트 안에서 가른다★"""
    hz = report["horizons"]
    assert set(hz) == {"0", "1"}
    assert hz["1"]["decisive"] is True
    assert hz["0"]["decisive"] is False
    assert "정보 표현력" in hz["0"]["question"]
    assert "예측 스킬" in hz["1"]["question"]
    assert report["verdict"]["horizon"] == DECISIVE_HORIZON


def test_the_report_is_labelled_synthetic_and_claims_nothing(report):
    assert report["evidence_grade"] == "E0"
    assert report["answers_question"] == "③ 예측 스킬"
    assert report["does_not_answer"] == ["① 정보 표현력", "② 전달 안정성",
                                         "④ 경제적 가치"]


def test_the_report_satisfies_the_power_field_requirement(report):
    assert require_power_fields(report["verdict"]) == []


def test_the_negative_control_is_reported_but_not_in_the_verdict(report):
    for h in ("0", "1"):
        arms = report["horizons"][h]["arms"]
        assert ARM_CONST in arms
        assert arms[ARM_CONST] == pytest.approx(0.0, abs=1e-12)
    assert ARM_CONST not in str(report["verdict"]["why"])


def test_the_power_is_measured_for_both_horizons(report):
    """★사전등록한 예측을 리포트가 스스로 검사할 수 있어야 한다★

    "선행의 MDE 가 동시대보다 클 것" 이라고 실행 전에 적었다. 결정적 지평의
    검정력만 실으면 그 예측이 맞았는지 리포트만 보고는 알 수 없다.
    """
    pbh = report["power_by_horizon"]
    assert set(pbh) == {"0", "1"}
    for h in ("0", "1"):
        assert require_power_fields(pbh[h]) == []
        assert report["horizons"][h]["power"] is pbh[h]
    assert report["power"] is pbh[str(DECISIVE_HORIZON)]


def test_the_verdict_uses_the_decisive_horizons_power(report):
    """★짝★ — 동시대의 (더 높은) 검정력으로 선행을 판정하지 않는다."""
    assert report["verdict"]["power"] == report["power_by_horizon"]["1"]["power"]


def test_the_two_horizons_actually_differ_in_this_fixture(report):
    """★아래 두 테스트가 공허하지 않다는 전제★

    두 지평이 우연히 같은 수를 내면 "선행을 썼다" 는 단언이 아무것도 걸지 못한다.
    이 저장소가 여러 번 치른 실수라 전제를 먼저 못 박는다.
    """
    a = report["horizons"]["0"]["pct_by_null"]
    b = report["horizons"]["1"]["pct_by_null"]
    assert a != b, "픽스처에서 두 지평이 같은 분위를 낸다 — 아래 단언이 공허해진다"
    assert report["horizons"]["0"]["arms"][ARM_ON] != \
        report["horizons"]["1"]["arms"][ARM_ON]


def test_the_verdict_reads_the_forward_horizons_percentiles(report):
    """★결정적 지평을 동시대로 바꾸는 변이를 죽인다 (G5)★"""
    assert report["verdict"]["percentile"] == report["horizons"]["1"]["pct_by_null"]
    assert report["verdict"]["percentile"] != report["horizons"]["0"]["pct_by_null"]


def test_the_nulls_are_drawn_at_the_same_horizon_as_the_arm():
    """★널을 진짜 팔과 **같은 방식으로** 돌린다 (G10)★

    널을 동시대로 뽑고 팔을 선행으로 재면 비교가 무의미하다 — 그런데 분위는
    멀쩡한 수로 나오므로 리포트만 보고는 알 수 없다.
    """
    import numpy as np
    from scripts.regime_signal_gate import null_draws
    pts = _points((["G"] * 3 + ["S"] * 3) * 5)
    m = np.random.default_rng(1).normal(0, 0.01, (len(pts), 3))
    kw = dict(method=rs.NULL_SHIFT, seed=7, n_markov=10)
    a, _, _ = null_draws(pts, m, horizon=0, **kw)
    b, _, _ = null_draws(pts, m, horizon=1, **kw)
    assert a != b, "지평이 널 추출에 반영되지 않는다"


def test_the_power_curve_is_not_degenerate(report):
    """★§42 probabilities hard-coded (G7)★

    시행이 언제나 통과/실패를 내면 곡선이 상수가 되고 MDE 가 무의미해진다.
    이 픽스처에서 곡선은 양끝을 **둘 다** 지나야 한다.
    """
    rates = [c["rate"] for c in report["power_by_horizon"]["1"]["curve"]]
    assert any(r is not None and r < 1.0 for r in rates), rates
    assert any(r is not None and r > 0.0 for r in rates), rates
    assert len(set(rates)) > 1, f"검정력 곡선이 상수다: {rates}"


def test_the_gate_is_research_only_and_no_engine_module_imports_it():
    """★배분 경로에 연결하지 않는다★ (사전등록 §6)

    S6 에서 쓴 규율과 같다 — 문서가 아니라 **정적 검사**가 강제한다. 문자열
    스캔까지 보는 이유는 동적 import 가 AST 를 피해 가기 때문이다(K11 이 찾아낸
    사각지대).
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src"
    offenders = [str(p.relative_to(root.parent))
                 for p in root.rglob("*.py")
                 if "regime_signal_gate" in p.read_text(encoding="utf-8")]
    assert offenders == [], f"연구 전용 하네스를 프로덕션이 참조한다: {offenders}"


def test_the_null_draws_are_enumerated_for_the_shift(report):
    n = report["horizons"]["1"]["nulls"][rs.NULL_SHIFT]
    assert n["decisive"] is True and n["enumerated"] is True
    assert n["stats"]["n"] > 10
    assert report["horizons"]["1"]["nulls"][rs.NULL_MARKOV]["decisive"] is True
