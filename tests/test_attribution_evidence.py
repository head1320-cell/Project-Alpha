"""AL4 — 효과별 상태 롤업.

AJ2(`multiplicity_evidence`)·AK2(`cost_model_registry`)의 관용구 그대로이고
★판정은 `run_evidence.rollup` 한 곳에만 있다★.

## 이 파일이 거는 계약

  · `measured` → `ok` · `unmeasured` → `degraded` · `unknown` → `unknown`
  · ★`not_applicable` 은 **축에서 빠진다**★ — 결함 목록에 섞으면 갚을 수 없는
    부채가 생긴다. 대신 사유와 함께 **따로** 실린다.
"""
from __future__ import annotations

import pytest

from src.domain.attribution_effect import NOT_APPLICABLE_EFFECTS
from src.engine.attribution_evidence import attribution_evidence
from src.engine.run_evidence import (
    AXIS_DEGRADED,
    AXIS_OK,
    AXIS_UNKNOWN,
    STATUS_UNKNOWN,
    STATUS_VERIFIED,
)

_ALL = {"allocation_effect_pct": 0.3, "selection_effect_pct": 0.1,
        "macro_effect_pct": -0.02, "netting_effect_pct": 0.0,
        "cost_effect_pct": -0.08, "cash_effect_pct": 0.04}


def _cum(**over) -> dict:
    return {**_ALL, **over}


# ═══════════════════════════════════════════════════════════════════════════
# ⑬ 축 상태 — 세 갈래가 실제로 나온다
# ═══════════════════════════════════════════════════════════════════════════

def test_a_measured_effect_is_ok():
    got = attribution_evidence(_cum())
    assert got["axes"]["allocation"]["state"] == AXIS_OK
    assert got["status"] == STATUS_VERIFIED


def test_a_measured_zero_is_still_ok():
    """★0 은 관측이다★ — 값이 0 이라는 이유로 상태를 내리지 않는다."""
    assert attribution_evidence(_cum(netting_effect_pct=0.0))["axes"]["netting"]["state"] == AXIS_OK


def test_an_unmeasured_effect_is_degraded():
    """`selection` 이 `None` 이면 ★관측된 결함★ 이다 — 미상이 아니다."""
    axis = attribution_evidence(_cum(selection_effect_pct=None))["axes"]["selection"]
    assert axis["state"] == AXIS_DEGRADED
    assert axis["reason"]


def test_an_unusable_value_is_unknown():
    axis = attribution_evidence(_cum(cost_effect_pct=float("nan")))["axes"]["cost"]
    assert axis["state"] == AXIS_UNKNOWN
    assert axis["reason"]


def test_the_three_states_all_occur():
    """★짝★ 언제나 한 상태인 구현을 배제한다."""
    got = attribution_evidence(_cum(selection_effect_pct=None,
                                    cost_effect_pct=float("inf")))
    states = {a["state"] for a in got["axes"].values()}
    assert states == {AXIS_OK, AXIS_DEGRADED, AXIS_UNKNOWN}


def test_an_all_missing_book_rolls_up_to_unknown_or_unverified():
    got = attribution_evidence({k: None for k in _ALL})
    assert got["status"] != STATUS_VERIFIED
    assert got["broken_axes"] or got["status"] == STATUS_UNKNOWN


# ═══════════════════════════════════════════════════════════════════════════
# ⑧ ★`not_applicable` 은 부채가 아니다★
# ═══════════════════════════════════════════════════════════════════════════

def test_not_applicable_effects_never_become_axes():
    got = attribution_evidence(_cum())
    for name in NOT_APPLICABLE_EFFECTS:
        assert name not in got["axes"], f"{name} 이 결함 축이 됐다"
    assert not (set(got["broken_axes"]) & set(NOT_APPLICABLE_EFFECTS))


def test_not_applicable_effects_are_reported_separately_with_reasons():
    got = attribution_evidence(_cum())
    assert set(got["not_applicable"]) == set(NOT_APPLICABLE_EFFECTS)
    for name, reason in got["not_applicable"].items():
        assert reason, name


def test_a_clean_book_is_verified_even_though_fx_is_not_applicable():
    """★정의되지 않는 것이 판정을 끌어내리지 않는다★"""
    assert attribution_evidence(_cum())["status"] == STATUS_VERIFIED


# ═══════════════════════════════════════════════════════════════════════════
# 표면
# ═══════════════════════════════════════════════════════════════════════════

def test_the_block_names_the_unmeasured_effects():
    got = attribution_evidence(_cum(selection_effect_pct=None))
    assert got["unmeasured"] == ["selection"]
    assert got["summary"]


def test_the_note_does_not_claim_attribution_is_complete():
    note = attribution_evidence(_cum())["note"]
    assert "벤치마크" in note or "완성" in note


def test_an_empty_input_does_not_fabricate_a_verdict():
    got = attribution_evidence({})
    assert got["status"] != STATUS_VERIFIED


def test_the_decomposer_attaches_the_evidence():
    """★분해 결과가 스스로 상태를 말한다★"""
    import numpy as np
    import pandas as pd

    from src.engine.attribution_decomposer import (
        EFFECT_COLUMNS,
        AttributionDecomposer,
    )
    base = {**{e: 0.0 for e in EFFECT_COLUMNS}, "portfolio_return": 0.01,
            "netting_savings": 0.0, "cumulative_return": 1.0}
    base["selection_effect"] = np.nan
    df = pd.DataFrame([base])
    df["trade_date"] = pd.to_datetime(pd.date_range("2026-01-05", periods=1))
    cum = AttributionDecomposer._cumulative_attribution(df)
    ev = attribution_evidence(cum)
    assert ev["axes"]["selection"]["state"] == AXIS_DEGRADED
    assert cum["coverage_complete"] is False


def test_the_evidence_uses_the_shared_rollup():
    """★규칙은 `run_evidence.rollup` 한 곳에만 있다★"""
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "engine" / "attribution_evidence.py").read_text(encoding="utf-8")
    names = {n.module for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.ImportFrom) and n.module}
    assert "src.engine.run_evidence" in names


# ═══════════════════════════════════════════════════════════════════════════
# ★검사의 검사★ — 필터가 공허하지 않은지
# ═══════════════════════════════════════════════════════════════════════════

def test_the_candidate_set_is_larger_than_the_measured_set():
    """★그래야 `not_applicable` 필터가 실제로 무언가를 거른다★

    변이 `d`(필터를 없앤다)가 처음에 살아남은 이유가 이것이었다 — `fx` 가 애초에
    루프에 등장하지 않아 **아무도 밟지 않는 분기**였다.
    """
    from src.domain.attribution_effect import CANDIDATE_EFFECTS, EFFECTS
    assert set(EFFECTS) < set(CANDIDATE_EFFECTS)
    assert set(CANDIDATE_EFFECTS) - set(EFFECTS) == set(NOT_APPLICABLE_EFFECTS)


def test_removing_the_filter_would_change_the_axes():
    """필터가 거르는 대상이 **실제로 후보에 있다**."""
    from src.domain.attribution_effect import CANDIDATE_EFFECTS
    got = attribution_evidence(_cum())
    assert len(got["axes"]) == len(CANDIDATE_EFFECTS) - len(NOT_APPLICABLE_EFFECTS)
    assert len(got["axes"]) < len(CANDIDATE_EFFECTS), "거른 것이 없다 — 필터가 공허하다"
