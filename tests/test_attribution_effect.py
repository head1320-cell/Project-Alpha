"""AL1 — 귀인 효과와 그 상태 (순수 계층).

## ★두 축을 섞지 않는다★

    효과의 종류(무엇을 재나)  ⟂  그 효과의 상태(쟀나 · 안 쟀나 · 정의되지 않나)

## ★`unmeasured` 와 `not_applicable` 을 가르는 것이 요점★

둘 다 값이 없지만 앞은 **부채**(언젠가 재야 한다 — `selection` 이 그렇다)이고
뒤는 **부채가 아니다**(잴 대상 자체가 없다 — FX·국가). 한 상태로 접으면 채점표가
FX 를 `selection` 과 같은 결함으로 세게 되고, 그것은 ★갚을 수 없는 부채★ 다.

## ★`0.0` 은 `measured` 다★

관측된 0 과 안 잰 것을 가르는 것이 이 모듈의 전부이므로, 값이 0 이라는 이유로
상태를 내리면 스스로를 배반한다. `selection_effect = 0` 이 정확히 그 반대 방향의
사고였다 — **상수가 관측 행세를 했다**.
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from src.domain.attribution_effect import (
    EFFECTS,
    NOT_APPLICABLE_EFFECTS,
    STATE_MEASURED,
    STATE_NOT_APPLICABLE,
    STATE_UNKNOWN,
    STATE_UNMEASURED,
    STATES,
    AttributionEffect,
    attribution_label,
    effect_from_value,
    effect_label,
)

_MODULE = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "domain" / "attribution_effect.py")


# ═══════════════════════════════════════════════════════════════════════════
# ⑦ ★관측된 0 과 안 잰 것★
# ═══════════════════════════════════════════════════════════════════════════

def test_a_measured_zero_is_measured():
    """★상태를 값으로 내리지 않는다★ — 0 은 관측이다."""
    got = effect_from_value("cost", 0.0)
    assert got.state == STATE_MEASURED
    assert got.pct == 0.0
    assert got.reason is None


def test_a_missing_value_is_unmeasured_with_a_reason():
    got = effect_from_value("selection", None, reason="전략별 벤치마크가 없습니다")
    assert got.state == STATE_UNMEASURED
    assert got.pct is None
    assert got.reason


def test_a_missing_value_without_a_reason_still_says_something():
    """★사유 없는 미측정은 침묵 폴백★ (CLAUDE.md §4) — 기본 문장이라도 있어야 한다."""
    assert effect_from_value("selection", None).reason


def test_measured_and_unmeasured_are_different_states():
    """둘 다 '값이 0/없음' 으로 보이지만 다른 사실이다."""
    assert (effect_from_value("cost", 0.0).state
            != effect_from_value("cost", None).state)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "많음", True])
def test_an_unusable_value_is_not_measured(bad):
    """★모양이 다르면 지어내지 않는다★"""
    got = effect_from_value("cost", bad)
    assert got.state != STATE_MEASURED
    assert got.pct is None and got.reason


# ═══════════════════════════════════════════════════════════════════════════
# ⑧⑨ ★`not_applicable` 은 부채가 아니다★
# ═══════════════════════════════════════════════════════════════════════════

def test_not_applicable_is_its_own_state():
    got = AttributionEffect(name="fx", state=STATE_NOT_APPLICABLE,
                            reason="정의되지 않습니다")
    assert got.state not in (STATE_MEASURED, STATE_UNMEASURED, STATE_UNKNOWN)


def test_the_not_applicable_registry_is_not_empty():
    """★표가 비면 이 검사 전체가 공허하다★ (AG 의 사고)"""
    assert NOT_APPLICABLE_EFFECTS


def test_every_not_applicable_effect_carries_a_reason():
    for name, reason in NOT_APPLICABLE_EFFECTS.items():
        assert name and reason, name


def test_fx_is_listed_as_not_applicable():
    assert "fx" in NOT_APPLICABLE_EFFECTS


def test_the_fx_reason_is_the_same_sentence_the_repo_already_wrote():
    """★같은 것을 두 이름으로 부르지 않는다★

    AB 가 `daily_explanation.UNMEASURABLE_DRIVERS[DRIVER_FX]` 에 이미 사유를
    적어 두었다. 여기서 문장을 새로 쓰면 두 화면이 다른 이유를 말하게 된다.
    """
    from src.domain.daily_explanation import DRIVER_FX, UNMEASURABLE_DRIVERS
    assert NOT_APPLICABLE_EFFECTS["fx"] == UNMEASURABLE_DRIVERS[DRIVER_FX]


def test_a_not_applicable_effect_is_not_a_debt():
    """★갚을 수 없는 부채를 만들지 않는다★ — 라벨이 그 구분을 실어야 한다."""
    got = effect_label(AttributionEffect(name="fx", state=STATE_NOT_APPLICABLE,
                                         reason="…"))
    assert got["is_debt"] is False
    assert effect_label(effect_from_value("selection", None))["is_debt"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 롤업 라벨
# ═══════════════════════════════════════════════════════════════════════════

def _six(**over) -> list[AttributionEffect]:
    out = [effect_from_value(n, 0.1) for n in EFFECTS]
    for i, e in enumerate(out):
        if e.name in over:
            out[i] = over[e.name]
    return out


def test_the_label_counts_measured_and_unmeasured_separately():
    got = attribution_label(_six(selection=effect_from_value("selection", None)))
    assert got["n_measured"] == len(EFFECTS) - 1
    assert got["n_unmeasured"] == 1
    assert got["unmeasured"] == ["selection"]


def test_the_label_lists_not_applicable_apart_from_the_unmeasured():
    got = attribution_label(_six())
    assert set(got["not_applicable"]) == set(NOT_APPLICABLE_EFFECTS)
    assert not (set(got["not_applicable"]) & set(got["unmeasured"]))


def test_a_fully_measured_book_reports_no_debt():
    """★짝★ 언제나 부채가 있는 구현을 배제한다."""
    got = attribution_label(_six())
    assert got["n_unmeasured"] == 0 and got["unmeasured"] == []


def test_every_effect_appears_in_the_label():
    """★빠진 효과는 0 이 아니라 부재다★"""
    got = attribution_label(_six())
    assert set(got["effects"]) == set(EFFECTS)


# ═══════════════════════════════════════════════════════════════════════════
# 타입 · 순수성
# ═══════════════════════════════════════════════════════════════════════════

def test_the_effect_vocabulary_has_six_and_no_duplicates():
    assert len(set(EFFECTS)) == len(EFFECTS) == 6
    assert "cash" in EFFECTS, "현금이자는 비용이 아니라 제 칸을 갖는다"


def test_the_states_are_a_closed_vocabulary():
    assert len(set(STATES)) == len(STATES)
    assert {STATE_MEASURED, STATE_UNMEASURED, STATE_NOT_APPLICABLE,
            STATE_UNKNOWN} == set(STATES)


def test_the_effect_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        effect_from_value("cost", 0.0).pct = 9.9   # type: ignore[misc]


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
