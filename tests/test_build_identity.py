"""AM1 — 빌드 식별자와 그 신뢰도 (순수 계층).

## ★두 축을 섞지 않는다★

    무엇의 버전인가(kind)  ⟂  그 값을 어떻게 알았나(method)

그리고 method 와도 다른 셋째 사실이 있다 — **작업 트리가 깨끗한가**(tree).
SHA 는 ★커밋을 식별하지 트리를 식별하지 않는다★. 커밋 안 된 수정이 있으면
같은 SHA 두 개는 **같은 코드가 아니다**.

## ★`"dev"` 는 버전이 아니라 미상이다★

실측(2026-09-18): `research_runs` 6행 · `regime_snapshots` 656행 ·
`backtest_runs.engine_version` 39행 = **701행 전부 `"dev"`**. 그래서
`research_manifest` 의 재현성 검사가 `"dev" == "dev"` 로 **항상 참**이었다 —
가드는 있는데 도달할 수 없었다. AL 의 하드코딩 `0` 이 `coverage_complete` 를
거짓으로 참으로 만든 것과 **같은 모양**이다.

이 모듈의 전부는 그 두 가지를 가르는 것이다: **버전인 값 ⟂ 버전 행세하는 값**,
그리고 **비교 가능한 상태 ⟂ 비교 불가능한 상태**.
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from src.domain.build_identity import (
    KIND_CODE,
    KIND_COST_MODEL,
    KINDS,
    METHOD_DECLARED,
    METHOD_INJECTED,
    METHOD_MEASURED,
    METHOD_UNKNOWN,
    METHODS,
    NON_VERSIONS,
    TREE_CLEAN,
    TREE_DIRTY,
    TREE_UNKNOWN,
    TREES,
    BuildIdentity,
    identity_from,
    identity_label,
    is_version,
    versions_comparable,
)

_MODULE = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "domain" / "build_identity.py")

_SHA = "a1b2c3d4e5f6a7b8"
_OTHER = "0f0e0d0c0b0a0908"


def _ident(value=_SHA, method=METHOD_MEASURED, tree=TREE_CLEAN, reason=None):
    return BuildIdentity(value=value, method=method, tree=tree, reason=reason)


# ═══════════════════════════════════════════════════════════════════════════
# 어휘 — 축이 섞이지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_three_vocabularies_are_not_empty():
    """★테스트의 테스트★ — 비어 있으면 아래 전수 테스트가 전부 공허해진다."""
    assert KINDS and METHODS and TREES
    assert KIND_CODE in KINDS and KIND_COST_MODEL in KINDS
    assert set(METHODS) == {METHOD_MEASURED, METHOD_INJECTED, METHOD_DECLARED,
                            METHOD_UNKNOWN}
    assert set(TREES) == {TREE_CLEAN, TREE_DIRTY, TREE_UNKNOWN}


def test_a_tree_state_cannot_be_used_as_a_method():
    """★축을 섞으면 거부한다★ `clean` 은 방법이 아니다."""
    with pytest.raises(ValueError):
        BuildIdentity(value=_SHA, method=TREE_CLEAN, tree=TREE_CLEAN)
    with pytest.raises(ValueError):
        BuildIdentity(value=_SHA, method=TREE_DIRTY, tree=TREE_CLEAN)


def test_a_method_cannot_be_used_as_a_tree_state():
    with pytest.raises(ValueError):
        BuildIdentity(value=_SHA, method=METHOD_MEASURED, tree=METHOD_MEASURED)


def test_an_unknown_kind_is_refused():
    with pytest.raises(ValueError):
        BuildIdentity(value=_SHA, method=METHOD_MEASURED, tree=TREE_CLEAN,
                      kind="지어낸축")


def test_the_identity_is_frozen():
    """★동결★ — 도중에 바뀌면 식별자가 무의미하다."""
    ident = _ident()
    assert dataclasses.is_dataclass(ident)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ident.value = _OTHER  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════
# is_version — ★"dev" 는 버전이 아니다★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_non_versions_are_registered_and_include_dev():
    """★테스트의 테스트★ — 목록이 비면 `is_version` 이 항상 참인 구현과 같다."""
    assert NON_VERSIONS
    assert "dev" in NON_VERSIONS


@pytest.mark.parametrize("value", ["dev", "DEV", " dev ", "", "   ", "unknown",
                                   "none", "null", None, 0, 123, ["a"]])
def test_these_are_not_versions(value):
    assert is_version(value) is False


@pytest.mark.parametrize("value", [_SHA, "v1.2.3", "2026.09.18", "abc1234"])
def test_these_are_versions(value):
    """★짝★ — 항상 거짓을 돌려주는 구현을 배제한다."""
    assert is_version(value) is True


# ═══════════════════════════════════════════════════════════════════════════
# identity_from — 분기 전수
# ═══════════════════════════════════════════════════════════════════════════

def test_an_injected_sha_without_a_measurement_cannot_know_the_tree():
    ident = identity_from(env_sha=_SHA, probe_reason="git 을 읽을 수 없습니다")
    assert ident.value == _SHA
    assert ident.method == METHOD_INJECTED
    assert ident.tree == TREE_UNKNOWN
    assert ident.reason


def test_an_injected_sha_confirmed_by_a_clean_measurement_is_promoted():
    """측정이 주입을 **확인**하면 트리를 알게 된다 — 그때만 비교가 가능하다."""
    ident = identity_from(env_sha=_SHA, measured_sha=_SHA, measured_dirty=False)
    assert ident.method == METHOD_INJECTED
    assert ident.tree == TREE_CLEAN


def test_an_injected_sha_contradicted_by_the_measurement_says_so():
    """★조용히 삼키지 않는다★ 주입과 측정이 어긋난 것은 관측 가치가 크다."""
    ident = identity_from(env_sha=_SHA, measured_sha=_OTHER, measured_dirty=False)
    assert ident.value == _SHA, "주입은 운영자의 명시적 선언이라 이긴다"
    assert ident.tree == TREE_UNKNOWN, "어긋났으면 승격하지 않는다"
    assert ident.reason and _OTHER in ident.reason


def test_an_injected_sha_on_a_dirty_tree_is_dirty():
    ident = identity_from(env_sha=_SHA, measured_sha=_SHA, measured_dirty=True)
    assert ident.tree == TREE_DIRTY


def test_an_app_version_never_claims_to_know_the_tree():
    """★`APP_VERSION` 은 커밋을 식별하지 않는다★

    깨끗한 트리를 재도 `v1.0` 두 개가 같은 커밋이라는 보장이 없다 — 라벨이
    거칠어서다. 트리를 안다고 말하면 **하지 않은 주장**이 된다.
    """
    ident = identity_from(env_app="v1.0", measured_sha=_SHA, measured_dirty=False)
    assert ident.value == "v1.0"
    assert ident.method == METHOD_INJECTED
    assert ident.tree == TREE_UNKNOWN
    assert ident.reason


def test_the_git_sha_wins_over_the_app_version():
    ident = identity_from(env_sha=_SHA, env_app="v1.0")
    assert ident.value == _SHA


def test_a_clean_measurement_with_no_injection_is_measured():
    ident = identity_from(measured_sha=_SHA, measured_dirty=False)
    assert ident.value == _SHA
    assert ident.method == METHOD_MEASURED
    assert ident.tree == TREE_CLEAN


def test_a_dirty_measurement_is_measured_but_dirty():
    ident = identity_from(measured_sha=_SHA, measured_dirty=True)
    assert ident.method == METHOD_MEASURED
    assert ident.tree == TREE_DIRTY
    assert ident.reason, "더러운 트리는 사유 없이 지나가면 안 된다"


def test_a_measurement_of_unknown_cleanliness_does_not_claim_clean():
    ident = identity_from(measured_sha=_SHA, measured_dirty=None)
    assert ident.tree == TREE_UNKNOWN


def test_nothing_at_all_is_none_with_a_reason_not_dev():
    """★`"dev"` 를 만들지 않는다★ 이 프로그램의 전부다."""
    ident = identity_from(probe_reason="`.git` 이 없습니다")
    assert ident.value is None
    assert ident.method == METHOD_UNKNOWN
    assert ident.tree == TREE_UNKNOWN
    assert ident.reason and "git" in ident.reason


def test_an_unknown_identity_always_carries_a_reason_even_without_a_probe():
    """★사유 없는 미상은 금지★ — 프로브가 사유를 안 줘도 지어내지 않고 적는다."""
    ident = identity_from()
    assert ident.value is None
    assert ident.reason


@pytest.mark.parametrize("bad", ["dev", "", "  "])
def test_an_injected_non_version_is_not_treated_as_a_version(bad):
    """`GIT_SHA=dev` 로 지금 동작을 흉내 내도 미상이다."""
    ident = identity_from(env_sha=bad)
    assert ident.value is None
    assert ident.method == METHOD_UNKNOWN


# ═══════════════════════════════════════════════════════════════════════════
# versions_comparable — ★이 프로그램의 핵심 계약★
# ═══════════════════════════════════════════════════════════════════════════

def test_two_clean_identities_with_the_same_value_match():
    assert versions_comparable(_ident(), _ident()) is True


def test_two_clean_identities_with_different_values_do_not_match():
    """★짝★ — 항상 `True` 도, 항상 `None` 도 아니다."""
    assert versions_comparable(_ident(), _ident(value=_OTHER)) is False


@pytest.mark.parametrize("tree", [TREE_DIRTY, TREE_UNKNOWN])
def test_a_tree_that_is_not_clean_makes_the_comparison_impossible(tree):
    """★핵심★ 같은 dirty SHA 두 개는 **같은 코드가 아니다**."""
    assert versions_comparable(_ident(tree=tree), _ident()) is None
    assert versions_comparable(_ident(), _ident(tree=tree)) is None


@pytest.mark.parametrize("value", [None, "dev", ""])
def test_a_non_version_on_either_side_makes_the_comparison_impossible(value):
    """701행의 `"dev"` 가 서로 같다고 판정되지 않는다 — ★이것이 버그였다★."""
    assert versions_comparable(_ident(value=value), _ident()) is None
    assert versions_comparable(_ident(), _ident(value=value)) is None


def test_two_dev_rows_are_not_a_match():
    """회귀 방지 — 옛 구현은 여기서 `True` 를 돌려줬다."""
    assert versions_comparable(_ident(value="dev"), _ident(value="dev")) is not True


def test_a_bare_string_cannot_know_its_tree_so_it_is_not_comparable():
    """메니페스트의 문자열처럼 트리를 기록하지 않은 값은 **미상**이다."""
    assert versions_comparable(_SHA, _SHA) is None
    assert versions_comparable(_SHA, _ident()) is None


def test_the_comparison_is_symmetric():
    pairs = [(_ident(), _ident()), (_ident(), _ident(value=_OTHER)),
             (_ident(tree=TREE_DIRTY), _ident()), (_ident(value=None), _ident()),
             (_SHA, _ident())]
    for a, b in pairs:
        assert versions_comparable(a, b) == versions_comparable(b, a)


def test_the_clean_branch_is_actually_reachable():
    """★공허한 분기는 증거가 아니다★ (AL 의 변이 `d` 가 가르친 것)

    위 전수 테스트가 전부 `None` 만 낸다면 `versions_comparable` 은 상수
    `None` 구현과 구별되지 않는다. 세 결과가 **모두** 나오는지 못 박는다.
    """
    got = {versions_comparable(_ident(), _ident()),
           versions_comparable(_ident(), _ident(value=_OTHER)),
           versions_comparable(_ident(tree=TREE_DIRTY), _ident())}
    assert got == {True, False, None}


# ═══════════════════════════════════════════════════════════════════════════
# identity_label
# ═══════════════════════════════════════════════════════════════════════════

def test_all_clean_known_versions_are_identifiable():
    out = identity_label({"code": _ident(), "cost_model": _ident(value="c0ffee")})
    assert out["identifiable"] is True
    assert out["unknown"] == []
    assert sorted(out["known"]) == ["code", "cost_model"]
    assert out["note"]


def test_a_dirty_axis_makes_the_run_not_identifiable():
    out = identity_label({"code": _ident(tree=TREE_DIRTY)})
    assert out["identifiable"] is False


def test_a_missing_version_makes_the_run_not_identifiable():
    out = identity_label({"code": _ident(value="dev")})
    assert out["identifiable"] is False
    assert out["unknown"] == ["code"]


def test_an_unknown_tree_leaves_identifiability_unknown():
    """★미상은 실패가 아니고 통과도 아니다★"""
    out = identity_label({"code": _ident(tree=TREE_UNKNOWN)})
    assert out["identifiable"] is None


def test_no_axes_at_all_is_unknown_not_true():
    out = identity_label({})
    assert out["identifiable"] is None
    assert out["note"]


def test_the_label_carries_every_axis_verbatim():
    out = identity_label({"code": _ident(reason="사유")})
    assert out["versions"]["code"] == {
        "value": _SHA, "method": METHOD_MEASURED, "tree": TREE_CLEAN,
        "kind": KIND_CODE, "reason": "사유"}


# ═══════════════════════════════════════════════════════════════════════════
# ★순수 계층★ — 설정도 환경도 읽지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_module_reads_no_environment_and_runs_no_process():
    """어휘가 환경을 읽으면 **순수하지 않고 테스트할 수 없다**.

    측정의 부작용은 전부 `src/engine/build_probe.py` 에 있다.
    """
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"os", "subprocess", "src"}), imported
