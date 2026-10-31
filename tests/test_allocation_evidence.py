"""E1 — 정책 백테스트의 룩어헤드 축 롤업.

## 왜 이 파일이 생겼나

`PolicyBacktest.tsx:110` 이 **하드코딩 상수**로 이렇게 말하고 있었다:

    <span className="as-bt-badge ok">OOS · look-ahead 없음</span>

응답에 이 주장을 뒷받침할 필드가 **하나도 없었고**, 백엔드는 그 문장을 docstring
에만 적어 두었다. ★AL 의 `selection_effect=0`, AM 의 `"dev"` 와 같은 모양이다 —
상수가 관측 행세를 한다.★ 그리고 E2E 가 그 문장을 단정해 **테스트가 거짓 주장을
지키고 있었다**.

## ★주장의 절반은 참이다★ — 섞지 않는다

`plan_walk_forward` 의 `R_win = R[lo:t]`(t **미포함**)는 리밸런싱 가중치가 창 밖
데이터를 쓰지 않음을 구조적으로 보장한다. "OOS" 는 사실이다. 그러나 "look-ahead
없음" 은 네 축을 한꺼번에 주장하고 **둘은 이 경로가 재지 않는다**:

| 축 | 상태 |
|---|---|
| `window` 창 격리 | ok — 구조적으로 참 (가드 테스트가 지킨다) |
| `as_of` 절단일 고정 | ok / degraded — 고정하지 않았으면 고정이 아니다 |
| `universe` 생존편향 | **unknown** — R3 `survivorship_of` 를 안 통과한다 |
| `price` 가격 기준 | **unknown** — R2 `basis_rollup` 을 안 통과한다 |

★넷 중 둘이 미상이므로 이 롤업은 **절대 `verified` 가 될 수 없다**★ — 그것이 이
모듈의 산출이다. 지금 화면이 단정하는 것을 롤업은 `partial` 이라고 말한다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from src.engine.allocation_evidence import (
    LOOKAHEAD_AXES,
    LOOKAHEAD_AXIS_LABELS,
    UNMEASURED_AXES,
    as_of_axis,
    lookahead_evidence,
    window_axis,
)
from src.engine.run_evidence import (
    AXIS_DEGRADED,
    AXIS_OK,
    AXIS_UNKNOWN,
    STATUS_VERIFIED,
)

_MODULE = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "engine" / "allocation_evidence.py")


def _cov(**kw):
    base = {"source": "mock", "n_obs": 500,
            "as_of_requested": None, "as_of_effective": "2026-09-18"}
    base.update(kw)
    return base


# ═══════════════════════════════════════════════════════════════════════════
# 어휘 — ★테스트의 테스트★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_axes_are_registered_and_labelled():
    """비면 아래 전수 테스트가 전부 공허해진다."""
    assert LOOKAHEAD_AXES
    assert set(LOOKAHEAD_AXIS_LABELS) == set(LOOKAHEAD_AXES)
    assert all(LOOKAHEAD_AXIS_LABELS[a] for a in LOOKAHEAD_AXES)


def test_the_unmeasured_axes_are_registered_with_reasons():
    """★사유 없이 '안 잰다' 고만 적으면 갚을 수 없는 부채다★ (AJ·AL 선례)"""
    assert UNMEASURED_AXES
    assert set(UNMEASURED_AXES) <= set(LOOKAHEAD_AXES)
    for name, reason in UNMEASURED_AXES.items():
        assert reason and reason.strip(), name


def test_the_unmeasured_axes_are_a_strict_subset():
    """★짝★ 전부가 미상이면 롤업은 아무것도 말하지 않는 것과 같다."""
    assert set(UNMEASURED_AXES) < set(LOOKAHEAD_AXES)


def test_the_module_reuses_the_shared_vocabulary_and_rollup():
    """★어휘를 두 벌 만들지 않는다★ (CLAUDE.md §2) — 축 이름도 롤업도 공용이다."""
    src = _MODULE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = {n.module for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.module}
    assert "src.engine.run_evidence" in imported
    assert "rollup" in src
    # R2·R3 의 축 이름을 그대로 쓴다 — 새 이름을 지어내지 않는다.
    assert {"universe", "price"} <= set(LOOKAHEAD_AXES)


# ═══════════════════════════════════════════════════════════════════════════
# window — ★구조적 주장은 가드가 있을 때만 구조적이다★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_window_axis_is_ok_and_names_its_guard():
    ax = window_axis()
    assert ax["state"] == AXIS_OK
    assert ax["reason"], "구조적으로 참이라는 근거를 적어야 한다"
    assert "R[lo:t]" in ax["reason"] or "lo:t" in ax["reason"]


# ═══════════════════════════════════════════════════════════════════════════
# as_of — ★고정하지 않은 것은 고정이 아니다★
# ═══════════════════════════════════════════════════════════════════════════

def test_a_pinned_as_of_is_ok():
    ax = as_of_axis(_cov(as_of_requested="2025-06-30"))
    assert ax["state"] == AXIS_OK
    assert ax["as_of_requested"] == "2025-06-30"


def test_an_unpinned_as_of_is_a_degradation_not_a_pass():
    """★짝★ — 항상 `ok` 인 구현을 배제한다. 서버가 오늘로 잘랐다는 것은
    '고정했다' 가 아니라 '고정한 적이 없다' 는 뜻이다(P1-A 가 적어 둔 구분)."""
    ax = as_of_axis(_cov(as_of_requested=None))
    assert ax["state"] == AXIS_DEGRADED
    assert ax["reason"]
    assert ax["as_of_effective"] == "2026-09-18", "서버가 쓴 절단일은 남는다"


def test_an_empty_string_as_of_is_not_a_pin():
    assert as_of_axis(_cov(as_of_requested=""))["state"] == AXIS_DEGRADED


def test_a_missing_coverage_is_unknown_not_ok():
    """★미상은 통과가 아니다★ — coverage 가 없으면 잴 근거가 없다."""
    assert as_of_axis(None)["state"] == AXIS_UNKNOWN
    assert as_of_axis({})["state"] == AXIS_UNKNOWN


# ═══════════════════════════════════════════════════════════════════════════
# 롤업 — ★verified 가 나올 수 없다★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_unmeasured_axes_are_unknown_not_ok():
    ev = lookahead_evidence(_cov())
    for name in UNMEASURED_AXES:
        assert ev["axes"][name]["state"] == AXIS_UNKNOWN, name
        assert ev["axes"][name]["reason"]


def test_the_rollup_can_never_be_verified():
    """★이 모듈의 산출★ — 화면이 단정하던 것을 롤업은 단정하지 않는다.

    `as_of` 를 고정하든 안 하든, 재지 않는 두 축이 있는 한 `verified` 는 나올 수
    없다. ★미상은 통과가 아니다★
    """
    for pinned in (None, "2025-06-30"):
        ev = lookahead_evidence(_cov(as_of_requested=pinned))
        assert ev["status"] != STATUS_VERIFIED, pinned


def test_pinning_the_as_of_still_changes_something():
    """★짝★ — 항상 같은 값을 내는 구현을 배제한다.

    `verified` 가 못 되는 것과 **아무것도 안 바뀌는 것**은 다르다.
    """
    loose = lookahead_evidence(_cov(as_of_requested=None))
    pinned = lookahead_evidence(_cov(as_of_requested="2025-06-30"))
    assert loose["axes"]["as_of"]["state"] != pinned["axes"]["as_of"]["state"]


def test_every_axis_is_present_even_when_unmeasured():
    """★빠진 축은 0 이 아니라 부재이고, 부재는 보이지 않는다★ (AK 의 교훈)"""
    ev = lookahead_evidence(_cov())
    assert set(ev["axes"]) == set(LOOKAHEAD_AXES)


def test_the_evidence_lists_what_it_did_not_measure():
    ev = lookahead_evidence(_cov())
    assert set(ev["unmeasured"]) == set(UNMEASURED_AXES)


def test_the_note_does_not_claim_no_lookahead():
    """★결론은 증거보다 강할 수 없다★ (CLAUDE.md §2)

    이 note 가 "룩어헤드가 없다" 고 말하면 고치려던 바로 그 거짓말이 된다.

    ★이 테스트를 처음엔 틀리게 썼다★ — 부분문자열 `"룩어헤드가 없"` 을 금지했더니
    note 의 *"룩어헤드가 없다는 뜻이 **아닙니다**"* 라는 **부정문**이 걸렸다. E4 의
    검출기가 오탐 17건에서 배운 것과 같은 실수를 테스트가 먼저 저지른 셈이다:
    ★어휘만 보면 주장과 부정을 구별하지 못한다.★ 그래서 규칙을 바꾼다 — 배지가
    쓰던 **그 문구 자체**와 단정형만 금지하고, 부정이 실제로 있는지를 요구한다.
    """
    note = lookahead_evidence(_cov())["note"]
    assert note
    # 배지가 쓰던 문구 자체 · 단정형 — 이것이 있으면 거짓말이 돌아온 것이다.
    for banned in ("look-ahead 없음", "룩어헤드가 없습니다", "룩어헤드 없음"):
        assert banned not in note, banned
    # ★부정이 실제로 있어야 한다★ — 없으면 위 금지는 공허하다.
    assert "뜻이 아닙니다" in note
    assert "재지" in note or "안 잰" in note or "미상" in note


def test_a_missing_coverage_does_not_crash_and_is_not_a_pass():
    ev = lookahead_evidence(None)
    assert ev["status"] != STATUS_VERIFIED
    assert ev["axes"]["as_of"]["state"] == AXIS_UNKNOWN


@pytest.mark.parametrize("bad", [[], "문자열", 3, True])
def test_a_garbage_coverage_is_unknown_not_a_pass(bad):
    """★조용히 타당성을 제조하지 않는다★ (CLAUDE.md §4)"""
    ev = lookahead_evidence(bad)
    assert ev["status"] != STATUS_VERIFIED
    assert ev["axes"]["as_of"]["state"] == AXIS_UNKNOWN
