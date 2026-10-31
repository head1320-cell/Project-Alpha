"""AO3 — 글라이드패스 증거 롤업. ★미선언 축은 `ok` 로 접히지 않는다★

`run_evidence.rollup` 의 **아홉 번째** 호출자다. 같은 함수를 부르는지도 함께
건다 — 복사되면 화면마다 다른 판정이 난다.

★짝을 붙인다★ — "X 여야 한다" 마다 "X 가 아니어야 한다" 를 둔다. 항상-`ok`·
항상-`unknown` 구현이 통과하지 못하게 하는 유일한 방법이다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from src.domain.contribution import BUCKET_RISKY, BUCKET_SAFE, months_to_close
from src.domain.glide_path import GlidePoint, years_remaining
from src.engine.glide_evidence import (
    AXIS_CONTRIBUTION,
    AXIS_CURVE,
    AXIS_HORIZON,
    AXIS_RISKY_CLASS,
    GLIDE_AXES,
    GLIDE_AXIS_LABELS,
    contribution_axis,
    curve_axis,
    glide_evidence,
    horizon_axis,
    risky_class_axis,
)
from src.engine.risky_share import risky_share_interval
from src.engine.run_evidence import (
    AXIS_DEGRADED,
    AXIS_OK,
    AXIS_UNKNOWN,
    STATUS_VERIFIED,
)

_MODULE = pathlib.Path("src/engine/glide_evidence.py")

CURVE = [GlidePoint(years_to_target=0.0, risky_target_pct=30.0),
         GlidePoint(years_to_target=20.0, risky_target_pct=80.0)]


# ── horizon ────────────────────────────────────────────────────────────────

def test_the_horizon_axis_is_ok_when_the_period_is_declared():
    axis = horizon_axis(10.0, None)
    assert axis["state"] == AXIS_OK
    assert axis["years"] == 10.0


def test_the_horizon_axis_is_unknown_when_nothing_was_declared():
    """★짝★ — 선언이 없으면 `ok` 가 아니다. 사유는 도메인이 준 것을 옮긴다."""
    years, reason = years_remaining()
    assert years is None
    axis = horizon_axis(years, reason)
    assert axis["state"] == AXIS_UNKNOWN
    assert axis["reason"] == reason


def test_the_horizon_axis_is_unknown_when_the_two_inputs_disagree():
    years, reason = years_remaining(horizon_days=365,
                                    target_retirement_year=2046)
    assert years is None
    assert horizon_axis(years, reason)["state"] == AXIS_UNKNOWN


def test_the_horizon_axis_is_degraded_when_the_target_date_already_passed():
    """선언은 됐지만 **관측된 결함**이다 — 미상이 아니라 열화다."""
    years, reason = years_remaining(target_retirement_year=2000)
    assert years == 0.0 and reason is not None
    assert horizon_axis(years, reason)["state"] == AXIS_DEGRADED


# ── curve ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("curve", [None, [], [CURVE[0]]])
def test_the_curve_axis_is_unknown_when_fewer_than_two_points(curve):
    axis = curve_axis(curve, years=10.0)
    assert axis["state"] == AXIS_UNKNOWN
    assert axis["points"] == (0 if not curve else len(curve))
    assert axis["reason"]


def test_the_curve_axis_is_ok_when_two_points_cover_the_remaining_years():
    axis = curve_axis(CURVE, years=10.0)
    assert axis["state"] == AXIS_OK
    assert axis["points"] == 2
    assert axis["range"] == {"lo": 0.0, "hi": 20.0}


def test_the_curve_axis_is_degraded_when_the_remaining_years_fall_outside():
    """★외삽하지 않고 고정했다★ — 고정했다는 사실이 판정에 남는다."""
    axis = curve_axis(CURVE, years=30.0)
    assert axis["state"] == AXIS_DEGRADED
    assert axis["clamped"] is True


def test_the_curve_axis_is_degraded_when_a_year_is_declared_twice():
    curve = [*CURVE, GlidePoint(years_to_target=0.0, risky_target_pct=99.0)]
    axis = curve_axis(curve, years=10.0)
    assert axis["state"] == AXIS_DEGRADED
    assert axis["reason"]


def test_the_curve_axis_judges_the_declaration_when_the_period_is_unknown():
    """★곡선 ⟂ 기간★ — 기간을 모르는 것은 **기간 축**의 결함이다."""
    axis = curve_axis(CURVE, years=None)
    assert axis["state"] == AXIS_OK
    assert axis["clamped"] is False


# ── risky_class ────────────────────────────────────────────────────────────

def test_the_risky_class_axis_is_unknown_when_the_classification_is_undeclared():
    risky = risky_share_interval({"069500": 1.0}, None)
    axis = risky_class_axis(risky)
    assert axis["state"] == AXIS_UNKNOWN
    assert axis["reason"] == risky["reason"]


def test_the_risky_class_axis_is_degraded_when_some_holdings_are_unassigned():
    """미배정분은 비중을 구간으로 벌린다 — ★관측된 열화★."""
    risky = risky_share_interval({"069500": 0.5, "005930": 0.5}, ["EQUITY"])
    assert risky["available"] and risky["unassigned_pct"] > 0
    assert risky_class_axis(risky)["state"] == AXIS_DEGRADED


def test_the_risky_class_axis_is_degraded_when_a_declared_class_is_unknown():
    risky = risky_share_interval({"069500": 1.0}, ["EQUTIY"])
    assert risky["unknown_classes"]
    assert risky_class_axis(risky)["state"] == AXIS_DEGRADED


def test_the_risky_class_axis_is_unknown_when_there_are_no_holdings():
    axis = risky_class_axis(risky_share_interval({}, ["EQUITY"]))
    assert axis["state"] == AXIS_UNKNOWN


# ── contribution ───────────────────────────────────────────────────────────

def _months(bucket, *, lo=70.0, hi=70.0, target=50.0):
    return months_to_close(target_pct=target, observed_lo=lo, observed_hi=hi,
                           monthly_krw=1_000_000, portfolio_value_krw=100_000_000,
                           bucket=bucket)


def test_the_contribution_axis_is_ok_when_the_plan_closes_the_gap():
    axis = contribution_axis(_months(BUCKET_SAFE))
    assert axis["state"] == AXIS_OK


def test_the_contribution_axis_is_degraded_when_the_plan_widens_the_gap():
    """★짝★ — 대상만 바꿔도 같은 계획이 결함이 된다."""
    axis = contribution_axis(_months(BUCKET_RISKY))
    assert axis["state"] == AXIS_DEGRADED
    assert axis["direction"] == "widens"


def test_the_contribution_axis_is_unknown_when_the_bucket_is_undeclared():
    axis = contribution_axis(_months(None))
    assert axis["state"] == AXIS_UNKNOWN


def test_the_contribution_axis_is_unknown_when_it_was_not_computed_at_all():
    axis = contribution_axis(None)
    assert axis["state"] == AXIS_UNKNOWN
    assert axis["reason"]


# ── 롤업 ───────────────────────────────────────────────────────────────────

def _all_declared() -> dict:
    years, reason = years_remaining(horizon_days=3650)
    risky = risky_share_interval({"069500": 0.7, "153130": 0.3}, ["EQUITY"])
    return {
        "years": years, "years_reason": reason, "curve": CURVE,
        "risky": risky,
        "contribution": _months(BUCKET_SAFE),
    }


def test_the_rollup_reaches_verified_only_when_all_four_axes_are_ok():
    ev = glide_evidence(**_all_declared())
    assert set(ev["axes"]) == set(GLIDE_AXES)
    assert ev["unknown_axes"] == [] and ev["broken_axes"] == []
    assert ev["status"] == STATUS_VERIFIED


@pytest.mark.parametrize("drop", list(GLIDE_AXES))
def test_the_rollup_never_folds_an_unknown_axis_into_ok(drop):
    """★핵심 계약★ — 축 하나만 미선언이어도 `verified` 가 되지 않는다."""
    kw = _all_declared()
    if drop == AXIS_HORIZON:
        kw["years"], kw["years_reason"] = years_remaining()
    elif drop == AXIS_CURVE:
        kw["curve"] = None
    elif drop == AXIS_RISKY_CLASS:
        kw["risky"] = risky_share_interval({"069500": 1.0}, None)
    else:
        kw["contribution"] = _months(None)

    ev = glide_evidence(**kw)
    assert ev["axes"][drop]["state"] == AXIS_UNKNOWN
    assert drop in ev["unknown_axes"]
    assert ev["status"] != STATUS_VERIFIED


def test_no_axis_is_ever_dropped_from_the_rollup():
    """★빠진 축은 '문제없다' 로 읽힌다★ — 전제가 하나도 없어도 넷이 남는다."""
    ev = glide_evidence(years=None, years_reason=None, curve=None,
                        risky=None, contribution=None)
    assert set(ev["axes"]) == set(GLIDE_AXES)
    assert all(a is not None for a in ev["axes"].values())
    assert sorted(ev["unknown_axes"]) == sorted(GLIDE_AXES)
    assert ev["status"] != STATUS_VERIFIED


def test_every_axis_has_a_label_and_no_label_is_orphaned():
    """★테스트의 테스트★ — 축 등록을 비우면 이것이 죽는다."""
    assert set(GLIDE_AXIS_LABELS) == set(GLIDE_AXES)
    assert len(GLIDE_AXES) == 4
    assert all(GLIDE_AXIS_LABELS[a] for a in GLIDE_AXES)


def test_the_rollup_is_the_shared_function_not_a_copy():
    """★규칙은 한 곳에만 있다★ — AST 로 **import 와 호출**을 본다."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    froms = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
             for a in n.names}
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "src.engine.run_evidence" in froms
    assert "rollup" in names and "rollup" in called


def test_the_note_says_the_optimizer_does_not_know_this_target():
    ev = glide_evidence(**_all_declared())
    assert "최적화기" in ev["note"]
