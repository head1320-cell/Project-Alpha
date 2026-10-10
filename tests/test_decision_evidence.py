"""결정이 ★무엇을 근거로 섰는가★ — 결정측 증거 축 (AA3)

설계: `docs/plans` AA · 애드덤 합격기준 #10

## ★로드맵 문장이 그대로는 실행 불가였다★

로드맵은 *"`run_evidence.pit_evidence` 를 `RebalanceProposal` 에 실어 나른다"* 고
적었다. 그런데 그 함수가 요구하는 네 축(`price_basis`·`universe`·
`macro_lookahead`·`fundamentals_pit`)은 **백테스트 엔진 산출물**이고 결정 경로에는
생산자가 **하나도 없다**. 없는 것을 나를 수는 없다.

그래서 **어휘는 재사용하고 축은 결정 경로가 실제로 아는 것으로 세운다** —
`run_evidence.rollup()` 을 **같은 함수로** 부르므로 두 판정이 갈라지지 않는다.

## ★`macro` 축이 진짜 look-ahead 를 잡는다★

`allocation_pipeline._regime_path_for` 는 스냅샷이 없으면 **현재 데이터로 국면
경로를 재계산**하고 `path_source: "recomputed"` 와 함께 *"결정 시점에 알 수 있었던
분류가 아닙니다"* 라고 이미 적고 있었다. 그것은 관측된 결함이므로 `degraded` 다.
계획 초안은 이 축을 "`mes_id` 를 넘겼는가" 로 쓰려 했는데, 실측이 더 나은 축을 줬다.
"""
from __future__ import annotations

import pytest

from src.engine.decision_evidence import (
    DECISION_AXIS_LABELS,
    DECISION_REQUIRED_AXES,
    OPTIONAL_AXES,
    decision_evidence,
)
from src.engine.run_evidence import (
    AXIS_DEGRADED,
    AXIS_OK,
    AXIS_UNKNOWN,
    STATUS_PARTIAL,
    STATUS_UNVERIFIED,
)

_DB = {"source": "db", "end": "2026-09-11", "as_of_effective": "2026-09-11"}
_FIXED_PATH = {"path_source": "mes", "path_note": None, "reason": None}


def _ev(**kw):
    base = {"coverage": dict(_DB), "as_of_requested": "2026-09-11",
            "target_source": "optimize:mvo", "regime_path": dict(_FIXED_PATH)}
    base.update(kw)
    return decision_evidence(**base)


# ═══════════════════════════════════════════════════════════════════════════
# ⑧⑨ 가격 축 — mock 은 결함이고 db 는 아니다
# ═══════════════════════════════════════════════════════════════════════════
def test_mock_prices_are_a_degraded_axis():
    out = _ev(coverage={**_DB, "source": "mock"})
    assert out["axes"]["price"]["state"] == AXIS_DEGRADED
    assert out["axes"]["price"]["reason"]


def test_db_prices_are_ok():
    """★짝★ 항상-degraded 구현을 배제한다."""
    assert _ev()["axes"]["price"]["state"] == AXIS_OK


def test_an_unnamed_price_source_is_unknown_not_degraded():
    """★재지 못한 것과 재서 나쁜 것은 다르다★"""
    out = _ev(coverage={"end": "2026-09-11", "as_of_effective": "2026-09-11"})
    assert out["axes"]["price"]["state"] == AXIS_UNKNOWN


# ═══════════════════════════════════════════════════════════════════════════
# ⑦ as_of 축 — ★미요청은 통과가 아니다★
# ═══════════════════════════════════════════════════════════════════════════
def test_no_requested_cutoff_is_unknown_not_ok():
    """결함은 아니지만 "시점 정합됐다" 는 **하지 않은 진술**이다."""
    out = _ev(as_of_requested=None)
    axis = out["axes"]["as_of"]
    assert axis["state"] == AXIS_UNKNOWN, "미요청을 ok 로 접었습니다"
    assert axis["state"] != AXIS_OK
    assert "요청" in (axis["reason"] or "")


def test_a_honoured_cutoff_is_ok():
    assert _ev()["axes"]["as_of"]["state"] == AXIS_OK


def test_a_broken_cutoff_is_degraded_and_names_both_values():
    out = _ev(as_of_requested="2026-06-30")
    axis = out["axes"]["as_of"]
    assert axis["state"] == AXIS_DEGRADED
    assert "2026-06-30" in axis["reason"] and "2026-09-11" in axis["reason"]


# ═══════════════════════════════════════════════════════════════════════════
# macro 축 — ★재계산된 국면 경로는 관측된 look-ahead 다★
# ═══════════════════════════════════════════════════════════════════════════
def test_a_recomputed_regime_path_is_degraded():
    out = _ev(regime_path={"path_source": "recomputed",
                           "path_note": "이 경로는 **현재 데이터로** 다시 계산했습니다",
                           "reason": None})
    axis = out["axes"]["macro"]
    assert axis["state"] == AXIS_DEGRADED, "재계산을 결함으로 보지 않았습니다"
    assert "현재 데이터" in (axis["reason"] or "")


@pytest.mark.parametrize("src", ["mes", "regime_snapshot"])
def test_a_frozen_regime_path_is_ok(src):
    """★짝★ 굳혀진 경로는 그 시점에 알 수 있었던 분류다."""
    out = _ev(regime_path={"path_source": src, "path_note": None, "reason": None})
    assert out["axes"]["macro"]["state"] == AXIS_OK


def test_an_empty_regime_path_is_unknown():
    """★물었는데 못 만든 것★ — 이건 미상이다."""
    out = _ev(regime_path={"path_source": None, "path_note": None,
                           "reason": "성장·물가 축이 둘 다 산출된 달이 없어…"})
    assert out["axes"]["macro"]["state"] == AXIS_UNKNOWN
    assert "성장·물가" in out["axes"]["macro"]["reason"], "상류 사유가 전달되지 않았습니다"


def test_a_decision_that_never_asked_has_no_macro_axis():
    """★"묻지 않은 것" 과 "물었는데 실패한 것" 은 다르다★ (실측이 정한 구분)

    `build_belief` 는 `conditional` 을 요청하지 않으면 `_NO_BELIEF` 를 돌려주고
    국면 경로를 **만들지 않는다**. 그 결정에 "국면 미상" 을 매기면 하지 않은
    시도를 실패로 적는 것이다 — `run_evidence` 가 `macro`·`fundamentals` 를
    `None` 으로 두는 규율과 같다.
    """
    out = _ev(regime_path=None)
    assert out["axes"]["macro"] is None
    assert "macro" not in out["applicable"]
    assert "macro" not in out["unknown_axes"], "안 쓴 축을 미상으로 셌습니다"


def test_a_never_asked_macro_does_not_block_verified():
    """★안 쓴 축이 판정을 끌어내리지 않는다★ — 나머지가 깨끗하면 `verified` 다."""
    from src.engine.run_evidence import STATUS_VERIFIED
    out = _ev(regime_path=None)
    assert out["status"] == STATUS_VERIFIED


# ═══════════════════════════════════════════════════════════════════════════
# target 축
# ═══════════════════════════════════════════════════════════════════════════
def test_an_undeclared_target_source_is_unknown():
    assert _ev(target_source=None)["axes"]["target"]["state"] == AXIS_UNKNOWN


def test_an_optimizer_target_is_ok():
    assert _ev(target_source="optimize:bl")["axes"]["target"]["state"] == AXIS_OK


# ═══════════════════════════════════════════════════════════════════════════
# ⑩ 롤업은 `run_evidence` 와 **같은 함수**다
# ═══════════════════════════════════════════════════════════════════════════
def test_the_rollup_is_the_shared_one():
    """★규칙을 복사하지 않는다★ — 복사하면 한쪽만 고쳐도 타입 에러가 안 난다."""
    import inspect

    from src.engine import decision_evidence as de
    src = inspect.getsource(de)
    assert "rollup(" in src, "공용 롤업을 부르지 않습니다"
    for copied in ("STATUS_VERIFIED\n", "elif ok:"):
        assert copied not in src, f"롤업 규칙을 복사했습니다: {copied!r}"


def test_a_mixed_verdict_is_partial_not_verified():
    out = _ev(as_of_requested=None)          # as_of 만 unknown
    assert out["status"] == STATUS_PARTIAL


def test_all_broken_is_unverified():
    out = _ev(coverage={**_DB, "source": "mock"}, as_of_requested="2026-06-30",
              target_source=None,
              regime_path={"path_source": "recomputed",
                           "path_note": "현재 데이터로 다시 계산", "reason": None})
    assert out["status"] == STATUS_UNVERIFIED


# ═══════════════════════════════════════════════════════════════════════════
# ★필수 축은 사라지지 않는다★
# ═══════════════════════════════════════════════════════════════════════════
def test_required_axes_never_vanish():
    """빠지면 "못 쟀다" 가 "문제없다" 로 둔갑한다(run_evidence 와 같은 규율)."""
    out = decision_evidence(coverage=None, as_of_requested=None,
                            target_source=None, regime_path=None)
    for name in DECISION_REQUIRED_AXES:
        assert out["axes"].get(name) is not None, name
        assert out["axes"][name]["state"] == AXIS_UNKNOWN
    for opt in OPTIONAL_AXES:
        assert opt not in DECISION_REQUIRED_AXES, (
            f"{opt} 는 그 표면에 해당할 때만 축이 된다")


# ═══════════════════════════════════════════════════════════════════════════
# ★"묻지 않았다"(ABSENT) 와 "물었는데 없었다"(None) 는 다르다★
# ═══════════════════════════════════════════════════════════════════════════
def test_an_omitted_target_is_not_an_axis_at_all():
    """보유 진단 표면처럼 **목표를 다루지 않는** 곳에 "목표 미상" 을 달지 않는다.

    ★눈으로 보고 찾은 결함이다★ — 첫 판은 `target` 을 필수 축으로 두어,
    목표가 없는 진단 표면이 "어느 최적화기가 낸 목표인지 알 수 없습니다" 를
    달고 다녔다. 묻지 않은 것을 못 쟀다고 적는 것이다.
    """
    out = decision_evidence(coverage=dict(_DB), as_of_requested="2026-09-11")
    assert out["axes"]["target"] is None
    assert "target" not in out["applicable"]
    assert "target" not in out["unknown_axes"]


def test_an_explicit_none_target_is_unknown():
    """★짝★ 목표를 **받는** 경로에서 출처가 비면 그것은 진짜 미상이다."""
    out = decision_evidence(coverage=dict(_DB), as_of_requested="2026-09-11",
                            target_source=None)
    assert out["axes"]["target"]["state"] == AXIS_UNKNOWN


def test_omitting_both_optional_axes_can_still_be_verified():
    """둘 다 해당 없고 필수 둘이 깨끗하면 `verified` 다."""
    from src.engine.run_evidence import STATUS_VERIFIED
    out = decision_evidence(coverage=dict(_DB), as_of_requested="2026-09-11")
    assert out["status"] == STATUS_VERIFIED
    assert out["applicable"] == ["price", "as_of"]


def test_every_axis_has_a_label():
    """★이름 없는 축은 요약 문장에서 KeyError 가 된다★"""
    out = _ev()
    for name in out["axes"]:
        assert name in DECISION_AXIS_LABELS, name


def test_freshness_is_attached_not_judged():
    """★`_freshness` 의 note 를 존중한다★ — 문턱을 지어내지 않는다."""
    out = _ev(freshness={"stale_days": 40, "reason": None})
    assert out["freshness"]["stale_days"] == 40
    assert "freshness" not in out["axes"], "신선도를 축으로 판정했습니다"


def test_the_note_does_not_overclaim():
    out = _ev()
    assert "예측" not in out["note"] and "정확" in out["note"]
