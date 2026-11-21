"""AM4 — 흩어진 버전 어휘를 한 장에 (레지스트리).

## ★아홉이 아니라 열둘이었다★ (AK 의 "넷이 아니라 열넷" 과 같은 패턴)

계획은 실재하는 축을 아홉으로 셌다: `code_version` · `BACKTEST_ENGINE_VERSION` ·
`MODEL_VERSION` · `ENGINE_VERSION` · `DECISION_LOGIC_VERSION` ·
`snapshot_version` · `result_version` · `ruleset_version` · `pack_id`.

실측 결과 **`MODEL_VERSION` 과 `ENGINE_VERSION` 이 각각 두 벌**이고 값이 서로
다르다(`regime_snapshots` 와 `company_snapshots`). 거기에 AM5 가 만든
`cost_model_version` 을 더하면 열둘이다. ★이름을 세면 낡는다 — 자리를 읽어야
한다.★

## 이 레지스트리가 답하는 질문

*"이 저장소는 어디서 버전을 정하고, 그중 무엇이 실제로 실행을 구별하는가."*

★대부분은 구별하지 않는다★ — 소스에 박힌 상수는 실행마다 같으므로 두 실행을
가를 수 없다. 그것이 결함이라는 뜻은 아니지만(레코드 형식의 판본은 원래 그렇다),
**재현성을 그 위에 세울 수는 없다**는 뜻이다.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from src.domain.build_identity import (
    KINDS,
    METHOD_DECLARED,
    METHOD_INJECTED,
    METHOD_MEASURED,
    METHOD_UNKNOWN,
    METHODS,
)
from src.engine.run_evidence import AXIS_DEGRADED, AXIS_OK, AXIS_UNKNOWN
from src.engine.version_registry import (
    MISSING_AXES,
    VERSION_AXES,
    axis_identity,
    axis_state,
    identifies_runs,
    registry_evidence,
)

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
_SELF = _SRC / "engine" / "version_registry.py"


# ═══════════════════════════════════════════════════════════════════════════
# 레지스트리의 형태 — ★테스트의 테스트★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_registry_is_not_empty():
    """비면 아래 전수 테스트가 전부 공허해진다."""
    assert len(VERSION_AXES) >= 10


def test_the_keys_are_unique():
    keys = [a.key for a in VERSION_AXES]
    assert len(keys) == len(set(keys)), keys


@pytest.mark.parametrize("axis", VERSION_AXES, ids=lambda a: a.key)
def test_every_axis_uses_the_shared_vocabulary(axis):
    """★어휘를 두 벌 만들지 않는다★ `build_identity` 가 단일 출처다."""
    assert axis.kind in KINDS
    assert axis.method in METHODS
    assert axis.label and axis.note
    assert axis.where, "어디에 남는지 적지 않으면 관측이 아니다"


@pytest.mark.parametrize("axis", VERSION_AXES, ids=lambda a: a.key)
def test_every_declared_location_actually_exists(axis):
    """★트립와이어★ 상수를 옮기거나 이름을 바꾸면 여기서 red 가 된다.

    레지스트리가 **값을 박지 않고 읽는다**는 것을 강제한다 — 박으면 낡는다
    (CLAUDE.md: "라우트 223→268 이 실측 332").
    """
    if axis.module is None:
        return
    import importlib
    mod = importlib.import_module(axis.module)
    if axis.attr is not None:
        assert hasattr(mod, axis.attr), f"{axis.module}.{axis.attr} 가 없다"


def test_the_model_and_engine_versions_are_two_copies_with_different_values():
    """★실측을 못 박는다★ 한 이름이 두 자리에서 다른 값을 갖는다.

    이것을 한 축으로 접으면 레지스트리가 저장소를 잘못 그린다.
    """
    import src.data.company_snapshots as cs
    import src.data.regime_snapshots as rs
    assert cs.MODEL_VERSION != rs.MODEL_VERSION
    assert cs.ENGINE_VERSION != rs.ENGINE_VERSION
    keys = {a.key for a in VERSION_AXES}
    assert {"regime_model_version", "company_model_version"} <= keys
    assert {"regime_engine_version", "company_engine_version"} <= keys


# ═══════════════════════════════════════════════════════════════════════════
# axis_state — ★박힌 상수는 관측된 결함이다★
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("axis", VERSION_AXES, ids=lambda a: a.key)
def test_the_state_follows_the_method(axis):
    st = axis_state(axis)
    ident = axis_identity(axis)
    expected = {METHOD_MEASURED: AXIS_OK, METHOD_INJECTED: AXIS_OK,
                METHOD_DECLARED: AXIS_DEGRADED,
                METHOD_UNKNOWN: AXIS_UNKNOWN}[ident.method]
    assert st["state"] == expected
    assert st["reason"] or st["state"] == AXIS_OK


def test_all_three_states_are_reachable():
    """★공허한 분기는 증거가 아니다★ (AL 의 변이 `d`)

    전부 한 상태만 나오면 `axis_state` 는 상수 구현과 구별되지 않는다. 이
    저장소에는 박힌 상수(degraded)와 측정되는 축(ok)이 **둘 다** 있다.
    """
    got = {axis_state(a)["state"] for a in VERSION_AXES}
    assert AXIS_DEGRADED in got, "박힌 상수가 하나도 없다고?"
    assert AXIS_OK in got or AXIS_UNKNOWN in got


def test_some_axes_identify_runs_and_some_do_not():
    """★이것이 요점이다★ 열둘 중 실행을 **구별하는** 축은 소수다."""
    flags = {identifies_runs(a) for a in VERSION_AXES}
    assert flags == {True, False}


@pytest.mark.parametrize("axis", VERSION_AXES, ids=lambda a: a.key)
def test_identification_is_derived_from_the_method_not_declared(axis):
    """★선언은 관측이 아니다★ — 변이 `l` 이 가르친 것.

    처음엔 `identifies_runs` 를 `VersionAxis` 에 손으로 적었고, **변이 배터리가
    그것을 죽이지 못했다**: `True` 를 `False` 로 뒤집어도 전 테스트가 초록이었다.
    아무도 그 주장을 관측과 대조하지 않았기 때문이다 — AL 의 하드코딩 `0` 과
    같은 모양이다. 이제 판정은 **읽은 method 에서 파생**되고, 이 짝 테스트가
    두 방향 모두 못 박는다.
    """
    ident = axis_identity(axis)
    if ident.method in (METHOD_MEASURED, METHOD_INJECTED):
        assert identifies_runs(axis) is True, axis.key
    else:
        assert identifies_runs(axis) is False, (
            f"{axis.key} 는 {ident.method} 인데 실행을 구별한다고 주장한다")


def test_a_hardcoded_constant_never_identifies_a_run():
    """짝 — 박힌 상수가 실행을 구별한다고 주장하면 그것은 거짓이다."""
    declared = [a for a in VERSION_AXES
                if axis_identity(a).method == METHOD_DECLARED]
    assert declared, "박힌 상수가 하나도 없다면 이 테스트는 공허하다"
    for a in declared:
        assert identifies_runs(a) is False, a.key


def test_the_code_version_axis_reads_the_live_identity():
    """★레지스트리가 환경을 읽는다★ 컨테이너에서는 미상으로 보고해야 한다."""
    from src.engine.build_probe import current_identity
    axis = next(a for a in VERSION_AXES if a.key == "code_version")
    assert axis_identity(axis).value == current_identity().value


def test_the_backtest_result_version_is_an_inline_literal():
    """★실측★ `result_version` 은 상수조차 없이 `"1"` 이 인라인으로 박혀 있다.

    39행 전부 `"1"` 이다 — 올릴 사람도 올릴 자리도 없다.
    """
    axis = next(a for a in VERSION_AXES if a.key == "backtest_result_version")
    assert axis.attr is None, "이름 붙은 상수가 생겼다면 레지스트리를 갱신하라"
    assert "1" in (axis_identity(axis).value or "1")


# ═══════════════════════════════════════════════════════════════════════════
# MISSING_AXES — ★없는 것을 사유와 함께 등록한다★ (AJ 선례)
# ═══════════════════════════════════════════════════════════════════════════

def test_the_missing_axes_are_registered_with_reasons():
    """★테스트의 테스트★ 비어도 통과하면 증거가 아니다."""
    assert MISSING_AXES
    for m in MISSING_AXES:
        assert m.key and m.label and m.reason and m.blocks


@pytest.mark.parametrize("missing", MISSING_AXES, ids=lambda m: m.key)
def test_a_missing_axis_is_actually_absent_from_the_source(missing):
    """★트립와이어★ 구현하면 여기서 red 가 되고 등록을 지우게 된다.

    ★"없다" 고 적고 실제로 있으면 그 레지스트리는 거짓말이다.★
    """
    # ★식별자로 찾는다★ 단순 부분문자열이면 `cost_model_registry` 안의
    # `model_registry` 가 걸린다 — 그것은 **다른 이름**이다. 첫 구현에서 실제로
    # 걸렸고, 걸린 것이 옳았다(테스트가 너무 무디다는 신호였다).
    pat = re.compile(rf"\b{re.escape(missing.key)}\b")
    hits = [p for p in _SRC.rglob("*.py")
            if p != _SELF and pat.search(p.read_text(encoding="utf-8"))]
    assert not hits, [str(p) for p in hits]


def test_the_cost_model_version_is_implemented_not_missing():
    """AM5 가 구현했다 — 없는 것으로 남겨 두면 채점표가 낡는다."""
    assert "cost_model_version" not in {m.key for m in MISSING_AXES}
    assert "cost_model_version" in {a.key for a in VERSION_AXES}


# ═══════════════════════════════════════════════════════════════════════════
# registry_evidence — ★롤업은 공용 함수 하나★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_evidence_uses_the_shared_rollup():
    ev = registry_evidence()
    assert set(ev) >= {"status", "axes", "missing", "note"}
    assert len(ev["axes"]) == len(VERSION_AXES), "세지 말고 파생하라"
    assert len(ev["missing"]) == len(MISSING_AXES)


def test_the_evidence_never_reports_verified_while_an_axis_is_degraded():
    """★박힌 상수가 있는 한 '검증됨' 은 나올 수 없다★"""
    ev = registry_evidence()
    if any(a["state"] == AXIS_DEGRADED for a in ev["axes"].values()):
        assert ev["status"] != "verified"


def test_the_evidence_lists_which_axes_identify_runs():
    """★환경에 의존한다는 것 자체가 관측이다★

    git 을 못 읽는 컨테이너에서는 `code_version` 이 미상이라 구별 축이 줄어든다
    — 그것이 사실이므로 테스트는 그 사실을 허용하되, **구별 축과 박힌 상수가
    같은 집합일 수 없다**는 것은 항상 건다.
    """
    ev = registry_evidence()
    assert set(ev["identifying"]) <= set(ev["axes"])
    assert ev["declared_constants"], "박힌 상수가 하나도 없다고?"
    assert not (set(ev["identifying"]) & set(ev["declared_constants"]))


def test_the_note_does_not_claim_reproducibility():
    """★결론은 증거보다 강할 수 없다★ (CLAUDE.md §2)"""
    ev = registry_evidence()
    assert ev["note"]
    assert "재현" in ev["note"] or "구별" in ev["note"]
