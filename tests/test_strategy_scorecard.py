"""AE2 — 평가 카드의 계약: ★세 축을 보존하고, 합치지 않는다★.

`alpha_registry` 의 `retired` 는 **생애주기**(폐기했다)이고 `strategy_health` 의
`retired` 는 **건강도 판정**이다. 이름이 같아 합치고 싶어지는데, 합치면 Z(kind ⟂
data_real)·AA(trigger ⟂ decision reason)에서 피한 축 섞기를 되풀이한다.

그리고 ★합성 등급을 만들지 않는다★ — 세 축을 한 글자로 뭉개는 순간 가중치를
지어내게 되고, 그것이 CLAUDE.md §2 의 "결론은 증거보다 강할 수 없다" 위반이다.
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from src.domain.distribution_gate import DISTRIBUTION_BLOCKED
from src.domain.strategy_scorecard import (
    AXIS_EVIDENCE,
    AXIS_HEALTH,
    AXIS_LIFECYCLE,
    SCORECARD_AXES,
    Scorecard,
    unmeasured_from_signals,
)

_MODULE = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "domain" / "strategy_scorecard.py")

#: 합성 등급 냄새가 나는 이름들. ★하나라도 필드로 생기면 실패★
_COMPOSITE_NAMES = ("grade", "score", "rating", "stars", "rank", "overall", "total")


def _card(**kw) -> Scorecard:
    base = dict(
        strategy_id="a1",
        lifecycle={"status": "approved", "reason": None, "usable_for_portfolio": True},
        health={"status": "healthy", "signals": []},
        evidence={"status": "ok", "reason": None, "axes": {}},
        unmeasured=[],
        distribution={"state": DISTRIBUTION_BLOCKED, "reason": "…"},
        as_of="2026-09-13",
    )
    return Scorecard(**{**base, **kw})


# ── 세 축 ───────────────────────────────────────────────────────────────────

def test_the_three_axes_are_the_vocabulary():
    assert SCORECARD_AXES == (AXIS_LIFECYCLE, AXIS_HEALTH, AXIS_EVIDENCE)


def test_a_card_carries_each_axis_separately():
    card = _card().to_dict()
    for axis in SCORECARD_AXES:
        assert axis in card, f"{axis} 축이 카드에 없다"


def test_the_two_retired_meanings_stay_in_different_fields():
    """★축 섞기 배제★ — 같은 문자열이지만 다른 사실이다."""
    card = _card(
        lifecycle={"status": "retired", "reason": "폐기됨", "usable_for_portfolio": False},
        health={"status": "healthy", "signals": []},
    ).to_dict()
    assert card[AXIS_LIFECYCLE]["status"] == "retired"
    assert card[AXIS_HEALTH]["status"] == "healthy"
    assert card[AXIS_LIFECYCLE]["status"] != card[AXIS_HEALTH]["status"]


def test_the_reverse_pairing_is_also_possible():
    """★짝★ — 두 축이 늘 같이 움직인다는 가정을 배제한다."""
    card = _card(
        lifecycle={"status": "approved", "reason": None, "usable_for_portfolio": True},
        health={"status": "retired", "signals": []},
    ).to_dict()
    assert card[AXIS_LIFECYCLE]["status"] == "approved"
    assert card[AXIS_HEALTH]["status"] == "retired"


# ── ★합성 등급을 만들지 않는다★ ──────────────────────────────────────────

def test_the_card_has_no_composite_grade_field():
    """★전수★ — 세 축을 한 값으로 뭉개는 필드가 없다."""
    names = {f.name.lower() for f in dataclasses.fields(Scorecard)}
    bad = {n for n in names if any(c in n for c in _COMPOSITE_NAMES)}
    assert not bad, f"합성 등급으로 보이는 필드가 있다: {bad}"


def test_the_serialised_card_has_no_composite_grade_key():
    keys = {k.lower() for k in _card().to_dict()}
    bad = {k for k in keys if any(c in k for c in _COMPOSITE_NAMES)}
    assert not bad, f"합성 등급으로 보이는 키가 있다: {bad}"


def test_the_module_defines_no_weighting_table():
    """가중치 딕트가 생기면 그것이 곧 지어낸 숫자다."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                name = (getattr(target, "id", "") or "").lower()
                if "weight" in name:
                    pytest.fail(f"가중치 테이블이 있다: {name}")


def test_the_composite_detector_actually_detects():
    """★테스트의 테스트★"""
    assert any(c in "overall_grade" for c in _COMPOSITE_NAMES)
    assert _COMPOSITE_NAMES, "금지 목록이 비면 검사가 언제나 통과한다"


# ── ★못 잰 것이 사라지지 않는다★ ────────────────────────────────────────

def test_unmeasured_signals_are_extracted_by_name_and_reason():
    signals = [
        {"key": "ic_icir", "label": "IC/ICIR", "status": "ok", "basis": "real"},
        {"key": "capacity", "label": "캐파 악화", "status": "unmeasured",
         "basis": "unavailable"},
        {"key": "borrow", "label": "차입 가능성 악화", "status": "unmeasured",
         "basis": "unavailable"},
    ]
    out = unmeasured_from_signals(signals)
    keys = {u["key"] for u in out}
    assert keys == {"capacity", "borrow"}
    assert all(u["label"] for u in out), "미측정 항목에 이름이 없다"


def test_measured_signals_do_not_leak_into_unmeasured():
    """★짝★ — 전부-미측정 구현을 배제한다."""
    signals = [{"key": "ic_icir", "label": "IC/ICIR", "status": "ok", "basis": "real"}]
    assert unmeasured_from_signals(signals) == []


def test_the_six_known_unmeasured_signals_survive_the_round_trip():
    """★`strategy_health._UNMEASURED` 여섯이 카드에 전부 실린다★.

    이 저장소가 **재지 못한다고 스스로 적어 둔** 것들이다. 카드에서 빠지면
    "이만큼 확인했다" 로 읽힌다.
    """
    from src.engine.strategy_health import _UNMEASURED

    signals = [{"key": k, "label": label, "status": "unmeasured",
                "basis": "unavailable"} for k, label in _UNMEASURED]
    out = unmeasured_from_signals(signals)
    assert {u["key"] for u in out} == {k for k, _ in _UNMEASURED}
    assert len(out) == 6


def test_an_empty_signal_list_yields_an_empty_list_not_none():
    assert unmeasured_from_signals([]) == []
    assert unmeasured_from_signals(None) == []


# ── 유통은 카드의 한 축이 아니라 ★관문★ 이다 ───────────────────────────

def test_every_card_carries_the_distribution_gate_result():
    assert _card().to_dict()["distribution"]["state"] == DISTRIBUTION_BLOCKED


def test_distribution_is_not_one_of_the_three_axes():
    """★유통은 평가가 아니다★ — 축에 섞으면 '유통 가능성' 이 품질처럼 읽힌다."""
    assert "distribution" not in SCORECARD_AXES


# ── 타입 ────────────────────────────────────────────────────────────────────

def test_a_card_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _card().strategy_id = "a2"  # type: ignore[misc]


def test_unmeasured_is_a_required_part_of_the_card():
    assert "unmeasured" in {f.name for f in dataclasses.fields(Scorecard)}
    assert "unmeasured" in _card().to_dict()


def test_the_domain_module_stays_pure():
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for name in imported:
        for bad in ("sqlalchemy", "fastapi", "requests", "src.database",
                    "src.data", "src.engine"):
            assert not name.startswith(bad), f"순수 계층이 {name} 을 import 한다"
