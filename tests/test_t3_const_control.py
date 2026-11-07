"""T3-D `-const` 대조군 계약 — ★인과 귀속이 성립하는지를 구조로 증명한다★
==============================================================================
계획: 매크로 → 포트폴리오 정보 계약 패스 Phase 1.

## 왜 이 파일이 따로 있나

T3-D 의 결론은 **뺄셈 두 개**에 걸려 있다:

    정책 가치       = D-const  − D-open
    동적 매크로 가치 = D-regime − D-const     ← ★이것이 매크로의 기여다★

`D-regime − D-open` 을 쓰면 세 가지가 뭉쳐진다 — 제약이 있다는 것의 값,
그 제약 **수준**의 값, 그리고 **국면에 따라 변한다는 것**의 값. 앞의 둘은 매크로가
아니라 **포트폴리오 정책**이다.

그러므로 `-const` 는 "적당히 상수인 팔" 이면 안 되고 **동적 팔과 구조적으로 같은
제약을, 국면 의존 상태만 얼려서** 써야 한다. 그렇지 않으면 뺄셈의 두 항이 다른
것을 재게 되고 차이는 매크로 기여가 아니다.

## 직전 라운드의 결함 (이 파일이 고치는 것)

`test_t3_arch_arms.test_const_arm_freezes_the_budget` 은 **D1 만** 보고
"예산이 상수" 만 확인했다. ★`-const` 가 `-open` 으로 폴백해도 예산은 여전히
상수라 그 테스트는 통과한다.★ D2-const 테스트는 **하나도 없었다**.

## `-const` 가 얼리는 것의 정의 (문서와 동일하게 유지할 것)

    `-const` 는 제약 구성 **입력 전체**를 첫 적용 리밸런싱 시점에 얼린다.
    ★제약 *객체*가 상수다 — 비중은 여전히 움직일 수 있다.★
    Σ 추정은 모든 팔의 공통 입력이지 제약이 아니다.

그래서 아래 테스트는 **비중의 상수성이 아니라 `signature` 의 상수성**을 본다.
"상수 팔인데 비중이 움직인다" 는 결함이 아니다.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import sys

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_t3():
    """★`sys.modules` 등록이 필수★ `from __future__ import annotations` 아래의
    `@dataclass` 가 `sys.modules[cls.__module__].__dict__` 를 되짚는다."""
    spec = importlib.util.spec_from_file_location(
        "t3_transmission", _ROOT / "scripts" / "t3_transmission.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


t3 = _load_t3()

#: (동적 팔, 얼린 대조군, 규칙 없는 대조군) — 두 계열을 같은 규격으로 돌린다.
FAMILIES = [
    pytest.param("T3-D1", "T3-D1-const", "T3-D1-open", id="D1-risk-budget"),
    pytest.param("T3-D2", "T3-D2-const", "T3-D2-open", id="D2-group-bounds"),
]


@pytest.fixture(scope="module")
def panel():
    names, R, dates, points, beta = t3.build_panel(months=36)
    return {"names": names, "R": R, "dates": dates, "points": points, "beta": beta}


def _run(arch, panel, R=None):
    return t3.run_arch(arch, panel["names"], panel["R"] if R is None else R,
                       panel["dates"], panel["points"], panel["beta"])


def _sigs(rec) -> list[str]:
    return [r["signature"] for r in rec["constraint_audit"]]


# ══════════════════════════════════════════════════════════════════════════
# C1·C2 — 구조적 동일성과 그 짝
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(("dyn", "const", "_open"), FAMILIES)
def test_const_and_regime_are_identical_at_the_first_rebalance(panel, dyn, const, _open):
    """★C1 — 구조적 동일성★

    첫 적용 리밸런싱에서는 얼릴 것이 아직 없으므로 두 팔이 **정확히 같은 제약**을
    만들어야 한다. 다르면 `-const` 가 제2 구현이라는 뜻이고, 그 순간 뺄셈의 두 항이
    다른 것을 재게 된다.
    """
    a, _ = _run(dyn, panel)
    b, _ = _run(const, panel)
    assert _sigs(a)[0] == _sigs(b)[0]
    np.testing.assert_allclose(a["w"][0], b["w"][0], atol=1e-12)


@pytest.mark.parametrize(("dyn", "const", "_open"), FAMILIES)
def test_only_the_time_varying_component_differs(panel, dyn, const, _open):
    """★C2 — C1 의 짝★

    C1 만 있으면 "두 팔이 언제나 같다"(= `-const` 가 동적 팔로 폴백)도 통과한다.
    국면이 변하는 패널에서는 **뒤로 갈수록 갈라져야** 한다.
    """
    a, _ = _run(dyn, panel)
    b, _ = _run(const, panel)
    assert _sigs(a)[-1] != _sigs(b)[-1], "얼린 팔이 동적 팔과 끝까지 같다 — 폴백이다"
    assert len(set(_sigs(a))) > 1, "동적 팔의 제약이 상수면 대조가 성립하지 않는다"


@pytest.mark.parametrize(("dyn", "const", "_open"), FAMILIES)
def test_identical_paths_when_the_conditional_state_never_moves(panel, dyn, const,
                                                                _open, monkeypatch):
    """★C1 강화판 — "국면 의존 상태를 고정하면 두 팔이 같다" 를 **경로 전체**로★

    첫 리밸런싱 일치만으로는 약하다. 제약 생성 입력을 시점 불변으로 만들면
    `-const` 와 동적 팔의 **모든 리밸런싱 비중이 원소별 같아야** 한다 — 두 팔의
    유일한 차이가 *언제 생성기를 부르는가* 임을 직접 보이는 테스트다.
    """
    real = t3.build_constraint
    first: dict = {}

    def frozen_inputs(family, sigma, sigma_uncond, names, *, regime_informed):
        # ★제약 **입력**만 고정한다★ 생성기 자체는 그대로 탄다(제2 구현 아님).
        key = (family, regime_informed)
        if key not in first:
            first[key] = (np.array(sigma, copy=True),
                          np.array(sigma_uncond, copy=True))
        s0, u0 = first[key]
        return real(family, s0, u0, names, regime_informed=regime_informed)

    monkeypatch.setattr(t3, "build_constraint", frozen_inputs)
    a, _ = _run(dyn, panel)
    b, _ = _run(const, panel)
    assert len(set(_sigs(a))) == 1, "입력을 고정했는데 동적 팔의 제약이 변한다"
    for i, (wa, wb) in enumerate(zip(a["w"], b["w"], strict=True)):
        np.testing.assert_allclose(wa, wb, atol=1e-12,
                                   err_msg=f"{i}번째 리밸런싱에서 갈라졌다")


# ══════════════════════════════════════════════════════════════════════════
# C3·C4 — ★미래 국면을 읽지 않는다★
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(("dyn", "const", "_open"), FAMILIES)
def test_const_freezes_at_the_first_rebalance_not_the_last(panel, dyn, const, _open):
    """★C3★ 얼린 값이 동적 팔의 **첫** 값과 같고 **마지막** 값과는 다르다.

    마지막 값으로 얼리면 그것은 대조군이 아니라 **미래를 아는 팔**이다.
    """
    a, _ = _run(dyn, panel)
    b, _ = _run(const, panel)
    assert _sigs(b)[0] == _sigs(a)[0]
    assert _sigs(b)[-1] == _sigs(a)[0], "얼린 값이 첫 값이 아니다"
    assert _sigs(b)[-1] != _sigs(a)[-1], "얼린 값이 마지막 값과 같다 — 미래를 봤다"
    assert {r["frozen_at"] for r in b["constraint_audit"]} == {b["months"][0]}


@pytest.mark.parametrize(("dyn", "const", "_open"), FAMILIES)
def test_const_is_invariant_to_future_data(panel, dyn, const, _open):
    """★C4 — 룩어헤드 직접 반증★

    패널 **뒷부분만** 바꾼다. 얼린 제약은 첫 훈련창에서 나왔으므로 **불변**이어야
    하고, 동적 팔의 마지막 제약은 **바뀌어야** 한다(아니면 교란이 약한 것이다).
    """
    R2 = panel["R"].copy()
    half = R2.shape[0] // 2
    R2[half:] *= 3.0                       # 뒤쪽 변동성을 3배로

    b0, _ = _run(const, panel)
    b1, _ = _run(const, panel, R=R2)
    assert _sigs(b1)[0] == _sigs(b0)[0], "미래 데이터가 얼린 제약을 바꿨다"

    a0, _ = _run(dyn, panel)
    a1, _ = _run(dyn, panel, R=R2)
    assert _sigs(a1)[-1] != _sigs(a0)[-1], "교란이 동적 팔조차 바꾸지 못했다(공허)"


# ══════════════════════════════════════════════════════════════════════════
# C5·C6 — 진짜 상수인가 / ★`-open` 으로 폴백하지 않았는가★
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(("_dyn", "const", "_open"), FAMILIES)
def test_const_is_constant_across_every_rebalance(panel, _dyn, const, _open):
    """★C5★ 서명이 **하나**여야 한다. 그리고 리밸런싱이 **여럿**이어야 한다.

    두 번째 단언이 없으면 리밸런싱이 1회일 때 공허하게 통과한다(`len(set)==1`).
    """
    rec, rb = _run(const, panel)
    sigs = _sigs(rec)
    assert len(rb) > 1 and len(sigs) > 1, "리밸런싱이 하나면 상수성 검사가 공허하다"
    assert len(set(sigs)) == 1, f"얼린 팔의 제약이 {len(set(sigs))}가지다"
    assert {r["regime_dependency"] for r in rec["constraint_audit"]} == {t3.REGIME_FROZEN}
    assert all(r["dynamic"] is False for r in rec["constraint_audit"])


@pytest.mark.parametrize(("_dyn", "const", "open_"), FAMILIES)
def test_const_is_not_open(panel, _dyn, const, open_):
    """★C6 — 요구 4 의 직접 답★

    `-const` 가 조용히 `-open` 으로 떨어지면 "정책 가치" 항이 0 이 되고 뺄셈 두 개가
    **동시에** 틀린다. 그런데 둘 다 서명이 하나뿐이라 상수성 검사로는 잡히지 않는다
    — **값이 달라야** 한다.
    """
    c, _ = _run(const, panel)
    o, _ = _run(open_, panel)
    assert _sigs(c)[0] != _sigs(o)[0], f"{const} 의 제약이 {open_} 과 같다 — 폴백이다"
    assert {r["regime_dependency"] for r in o["constraint_audit"]} == {t3.REGIME_NONE}
    # 그리고 비중이 실제로 갈라져야 한다 — 서명만 다르고 결과가 같으면 무의미하다
    l1 = float(np.mean([np.abs(a - b).sum()
                        for a, b in zip(c["w"], o["w"], strict=True)]))
    assert l1 > 1e-6, f"{const} 와 {open_} 의 비중이 사실상 같다 (L1 {l1:.2e})"


# ══════════════════════════════════════════════════════════════════════════
# C7·C8 — 제2 구현 금지 / 감사 완결성
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(("dyn", "const", "open_"), FAMILIES)
def test_all_three_arms_declare_the_same_constraint_source(panel, dyn, const, open_):
    """★C7 — 요구 2★ 셋이 같은 생성기를 탄다는 것을 **값으로** 증언한다."""
    srcs = set()
    for arch in (dyn, const, open_):
        rec, _ = _run(arch, panel)
        srcs |= {r["source"] for r in rec["constraint_audit"]}
        assert {r["kind"] for r in rec["constraint_audit"]} == \
            {rec["constraint_audit"][0]["kind"]}
    assert len(srcs) == 1, f"세 팔이 서로 다른 생성기를 쓴다: {srcs}"


@pytest.mark.parametrize("arch", list(t3.ARCH_BUDGET))
def test_audit_row_exists_for_every_rebalance(panel, arch):
    """★C8★ 감사가 리밸런싱마다 있어야 한다 — 빠진 줄은 보이지 않는 결정이다."""
    rec, rb = _run(arch, panel)
    assert len(rec["constraint_audit"]) == len(rb)
    for r in rec["constraint_audit"]:
        assert r["source"] and r["kind"]
        assert r["regime_dependency"] in (
            t3.REGIME_PER_REBALANCE, t3.REGIME_FROZEN, t3.REGIME_NONE)
        assert r["evidence_grade"] == t3.EVIDENCE_SYNTHETIC
        assert set(r["effective_bounds"]) == {"EQ", "FI"}


def test_effective_bounds_always_carry_a_lower_bound(panel):
    """★계약 공백의 상시 증거★

    `Constraints` 에는 그룹 **하한이 없다**. 감사행이 하한을 언제나 `0.0` 으로
    인쇄하게 두어, "FI ≥ 40%" 를 표현할 수 없다는 사실이 화면에서 사라지지 않게 한다.
    이 테스트는 하한 칸이 **존재하고 0** 임을 못 박는다 — 나중에 하한이 생기면
    여기가 red 가 되어 계약이 바뀐 것을 알린다.
    """
    rec, _ = _run("T3-D2", panel)
    for r in rec["constraint_audit"]:
        for _g, (lo, hi) in r["effective_bounds"].items():
            assert lo == 0.0, "하한이 생겼다면 이 테스트와 계약 문서를 함께 고칠 것"
            assert 0.0 < hi <= 100.0


def test_group_bounds_arm_reports_which_group_binds(panel):
    """★D2 의 이득이 EQ 상한이 아니라 **FI 상한**에서 온다는 것을 감사가 말한다★

    `Σw = 1` 에서 FI 상한은 EQ **하한**으로 작동한다. 그것이 "국면 정보" 로 오독되던
    이득의 정체이므로, 어느 그룹이 물렸는지가 기록에 남아야 한다.
    """
    rec, _ = _run("T3-D2", panel)
    bound = [g for r in rec["constraint_audit"] for g in r["binding"]]
    assert bound, "한 번도 물리지 않았다면 D2 는 D2-open 과 같다"
    assert set(bound) <= {"EQ", "FI"}


def test_risk_budget_arm_reports_the_budget_not_just_bounds(panel):
    """D1 은 경계가 언제나 `(0,100)` 이라 **예산**이 감사의 본체다."""
    rec, _ = _run("T3-D1", panel)
    for r in rec["constraint_audit"]:
        bg = r["risk_budget_by_group"]
        assert bg is not None and set(bg) == {"EQ", "FI"}
        assert sum(bg.values()) == pytest.approx(1.0, abs=1e-9)
    rec2, _ = _run("T3-D2", panel)
    assert all(r["risk_budget_by_group"] is None for r in rec2["constraint_audit"])


def test_open_arm_is_named_open_not_flat():
    """어휘 정렬 — `-flat` 별칭을 남기지 않는다(두 이름이 살면 보고서가 갈라진다)."""
    assert "T3-D1-open" in t3.ARCH_BUDGET
    assert not any(a.endswith("-flat") for a in t3.ARCH_ALL)
