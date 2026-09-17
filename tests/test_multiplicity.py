"""AJ1 — 다중검정 어휘와 순수 산수 (순수 계층).

## ★두 축을 섞지 않는다★

    가족 크기를 어디서 아는가  ⟂  어떤 보정을 실제로 적용했는가

둘은 독립이다. **가족 크기를 알면서 보정을 안 할 수 있고**(`factor_exposure` ·
`macro_sensitivity` 가 정확히 그랬다 — `n_tested` 를 적고 경고만 했다),
**보정 이름을 적어 놓고 가족 크기를 모를 수도 있다**(매크로 타깃 검증의 BH 는
사전등록됐는데 그 검증 자체가 코드에 없다).

## ★핵심 불변식 — 가족 크기를 모르면 보정을 만들지 않는다★

미상을 `m=1` 로 접으면 결과가 **보정 없음과 수치적으로 같아진다**. 그것은
*"보정이 불필요하다"* 는 주장이고, 미상은 주장이 아니다 — CLAUDE.md §4
★침묵 폴백 금지★ 의 이 작업판이다.
"""
from __future__ import annotations

import ast
import dataclasses
import math
import pathlib

import pytest

from src.domain.multiplicity import (
    CORRECTION_BH,
    CORRECTION_BONFERRONI,
    CORRECTION_NONE,
    CORRECTION_SPA,
    CORRECTIONS,
    FAMILY_DECLARED,
    FAMILY_PREREGISTERED,
    FAMILY_SOURCES,
    FAMILY_UNKNOWN,
    Family,
    bh_reject,
    bonferroni_alpha,
    expected_max_z,
    multiplicity_label,
    two_sided_p_from_t,
)

_MODULE = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "domain" / "multiplicity.py")


# ═══════════════════════════════════════════════════════════════════════════
# ①② ★가족 크기를 모르면 보정을 만들지 않는다★ — 그리고 그 짝
# ═══════════════════════════════════════════════════════════════════════════

def test_an_unknown_family_produces_no_correction():
    """★미상을 m=1 로 접지 않는다★ — m=1 은 '보정이 불필요하다' 는 주장이다."""
    got = multiplicity_label(Family(source=FAMILY_UNKNOWN,
                                    reason="시행 횟수를 세는 자리가 없습니다"),
                             CORRECTION_BH, alpha=0.05)
    assert got["correction"] is None
    assert got["applied"] is False
    assert got["reason"], "사유 없는 미상은 침묵 폴백입니다"


def test_a_known_family_does_produce_a_correction():
    """★짝★ 언제나 거절하는 구현을 배제한다."""
    got = multiplicity_label(Family(size=20, source=FAMILY_PREREGISTERED),
                             CORRECTION_BONFERRONI, alpha=0.05)
    assert got["correction"] == CORRECTION_BONFERRONI
    assert got["applied"] is True
    assert got["corrected_alpha"] == pytest.approx(0.05 / 20)


def test_the_two_axes_are_independent():
    """가족 크기를 **알면서** 보정을 안 한 상태가 표현 가능해야 한다.

    ★그것이 `factor_exposure`·`macro_sensitivity` 의 실제 상태였다★ — `n_tested`
    를 적고 "보정 없이 유의하다고 말하는 것은 거짓" 이라고 경고만 했다.
    """
    got = multiplicity_label(Family(size=5, source=FAMILY_DECLARED),
                             CORRECTION_NONE, alpha=0.05)
    assert got["family_size"] == 5
    assert got["family_source"] == FAMILY_DECLARED
    assert got["correction"] == CORRECTION_NONE
    assert got["applied"] is False
    assert got["reason"], "보정을 안 했으면 왜 안 했는지가 있어야 합니다"


def test_a_nonpositive_family_size_is_not_a_family():
    for bad in (0, -1):
        got = multiplicity_label(Family(size=bad, source=FAMILY_DECLARED),
                                 CORRECTION_BH, alpha=0.05)
        assert got["correction"] is None and got["reason"]


# ═══════════════════════════════════════════════════════════════════════════
# ③④⑤ BH 절차 그 자체
# ═══════════════════════════════════════════════════════════════════════════

def test_bh_follows_the_textbook_procedure():
    """★최대 k 아래는 **전부** 기각한다★ — 개별 통과만 세면 BH 가 아니다.

    m=5, α=0.05. 임계 k·α/m = .01 .02 .03 .04 .05
    p = .009 .04 .041 .30 .80  →  정렬 후 k=3 (.03 ≤ .041?) 아니오,
    k=2 (.02 ≤ .04?) 아니오, k=1 (.01 ≤ .009?) 예 → 최대 k=1.
    """
    out = bh_reject([0.009, 0.04, 0.041, 0.30, 0.80], alpha=0.05)
    assert out["n"] == 5
    assert out["n_rejected"] == 1
    assert out["rejected"] == [True, False, False, False, False]


def test_bh_rejects_everything_below_the_largest_passing_k():
    """★여기가 BH 와 '개별 p < 임계' 를 가르는 자리★

    m=3, α=0.05 → 임계 .01667 .03333 .05
    p = .04 .002 .05 → 정렬 .002 .04 .05. k=3: .05 ≤ .05 참 → **셋 다** 기각.
    개별 비교였다면 .04 는 두 번째 임계 .0333 을 못 넘어 살아남는다.
    """
    out = bh_reject([0.04, 0.002, 0.05], alpha=0.05)
    assert out["n_rejected"] == 3
    assert out["rejected"] == [True, True, True]


def test_bh_is_never_stricter_than_bonferroni():
    """★짝★ BH 는 Bonferroni 보다 기각을 적게 하지 않는다."""
    ps = [0.001, 0.009, 0.02, 0.04, 0.2, 0.9]
    alpha = 0.05
    bonf_cut = bonferroni_alpha(alpha, len(ps))
    n_bonf = sum(1 for p in ps if p <= bonf_cut)
    assert bh_reject(ps, alpha=alpha)["n_rejected"] >= n_bonf


@pytest.mark.parametrize("ps,expect", [([1.0] * 4, 0), ([0.0] * 4, 4)])
def test_bh_is_not_constant(ps, expect):
    """★언제나 기각/언제나 통과인 구현을 배제한다★"""
    assert bh_reject(ps, alpha=0.05)["n_rejected"] == expect


def test_bh_on_an_empty_family_is_unknown_not_zero():
    """★가족이 없으면 '0개 기각' 이 아니라 미상이다★"""
    out = bh_reject([], alpha=0.05)
    assert out["n_rejected"] is None
    assert out["reason"]


def test_bonferroni_divides_not_multiplies():
    assert bonferroni_alpha(0.05, 10) == pytest.approx(0.005)
    assert bonferroni_alpha(0.05, 1) == pytest.approx(0.05)


def test_bonferroni_without_a_family_is_none():
    for m in (None, 0, -3):
        assert bonferroni_alpha(0.05, m) is None


# ═══════════════════════════════════════════════════════════════════════════
# ⑥ 선택편향 팽창항 — ★DSR 의 팽창항이 이미 저장소에 있었다★
# ═══════════════════════════════════════════════════════════════════════════

def test_expected_max_z_is_zero_for_a_single_trial():
    assert expected_max_z(1) == 0.0
    assert expected_max_z(0) == 0.0


def test_expected_max_z_grows_with_the_number_of_trials():
    """★상수 구현을 배제한다★"""
    vals = [expected_max_z(n) for n in (2, 10, 100, 1000)]
    assert vals == sorted(vals)
    assert len(set(vals)) == 4
    assert expected_max_z(100) == pytest.approx(math.sqrt(2 * math.log(100)))


# ═══════════════════════════════════════════════════════════════════════════
# t → p ★근사임을 밝힌다★
# ═══════════════════════════════════════════════════════════════════════════

def test_t_to_p_is_two_sided_and_symmetric():
    assert two_sided_p_from_t(1.959963984540054)["p"] == pytest.approx(0.05, abs=1e-6)
    assert (two_sided_p_from_t(-2.5)["p"]
            == pytest.approx(two_sided_p_from_t(2.5)["p"]))


def test_t_to_p_declares_it_is_an_approximation():
    """★정확하다고 말하지 않는다★ — dof 를 무시한 정규 근사다."""
    got = two_sided_p_from_t(2.0)
    assert got["approximation"] is True
    assert got["method"]


def test_a_missing_t_gives_no_p():
    """★미상은 p=1.0 이 아니다★ — 1.0 은 '전혀 유의하지 않다' 는 관측이다."""
    got = two_sided_p_from_t(None)
    assert got["p"] is None and got["reason"]


# ═══════════════════════════════════════════════════════════════════════════
# 타입·순수성
# ═══════════════════════════════════════════════════════════════════════════

def test_the_vocabularies_have_no_duplicates():
    assert len(set(FAMILY_SOURCES)) == len(FAMILY_SOURCES)
    assert len(set(CORRECTIONS)) == len(CORRECTIONS)
    assert set(FAMILY_SOURCES) == {FAMILY_PREREGISTERED, FAMILY_DECLARED,
                                   FAMILY_UNKNOWN}
    assert CORRECTION_SPA in CORRECTIONS, "이미 있는 보정(Hansen SPA)을 어휘에 올린다"


def test_the_family_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        Family(size=3).size = 9   # type: ignore[misc]


def test_an_empty_family_defaults_to_unknown_not_one():
    assert Family().source == FAMILY_UNKNOWN
    assert Family().size is None


def test_the_domain_module_stays_pure():
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for name in imported:
        for bad in ("sqlalchemy", "fastapi", "requests", "pandas", "numpy", "scipy",
                    "src.database", "src.data", "src.engine", "src.execution", "src.api"):
            assert not name.startswith(bad), f"순수 계층이 {name} 을 import 한다"
