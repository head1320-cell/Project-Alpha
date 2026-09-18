"""정책 백테스트의 룩어헤드 증거 — ★상수 배지가 단정하던 것을 잰다★ (E1)
==============================================================================
설계: `docs/superpowers/specs/2026-09-18-evidence-claim-design.md` · 롤업
`src/engine/run_evidence.rollup` (★`pit_evidence`·`decision_evidence`·
`estimator_evidence`·`multiplicity_evidence`·`cost_model_registry`·
`attribution_evidence`·`version_registry` 와 **같은 함수**★)

## 왜 이 모듈이 생겼나

`frontend/src/widgets/allocation/PolicyBacktest.tsx` 가 **하드코딩 상수**로 이렇게
말하고 있었다:

    <span className="as-bt-badge ok">OOS · look-ahead 없음</span>

응답에 이 주장을 뒷받침할 필드가 **하나도 없었고**, 라우트는 그 문장을 docstring
에만 적어 두었다. ★AL 의 `selection_effect=0`, AM 의 `"dev"` 와 같은 모양이다 —
상수가 관측 행세를 한다.★ 더구나 E2E(`allocation-backtest.spec.ts`)가 그 문장을
단정해서 **테스트가 거짓 주장을 지키고 있었다.**

## ★주장의 절반은 참이다 — 섞지 않는다★ (CLAUDE.md §2)

`allocation_backtest.plan_walk_forward` 의 `R_win = R[lo:t]`(t **미포함**)는
리밸런싱 가중치가 창 밖 데이터를 쓰지 않음을 구조적으로 보장한다. 그러니 "OOS" 는
사실이다. 그러나 "look-ahead 없음" 은 **네 축을 한꺼번에** 주장하고, 그중 둘은 이
경로가 아예 재지 않는다.

    window    창 격리        ok       — 구조적으로 참 (가드 테스트가 지킨다)
    as_of     절단일 고정    ok/degraded — 고정하지 않은 것은 고정이 아니다
    universe  생존편향       unknown  — R3 `survivorship_of` 를 안 통과한다
    price     가격 기준      unknown  — R2 `basis_rollup` 을 안 통과한다

★넷 중 둘이 미상이므로 이 롤업은 절대 `verified` 가 될 수 없다★ — 그것이 이
모듈의 산출이다. 화면이 단정하던 것을 롤업은 `partial` 이라고 말한다.

## ★이 모듈이 주장하지 않는 것★

- **룩어헤드가 없다고 말하지 않는다.** 네 축 중 둘을 **재지 않는다**고 말할 뿐이고,
  하는 일은 그 둘이 참인 척하지 못하게 하는 것이다.
- **생존편향·가격 기준을 재지 않는다.** 재려면 `_load_clean_returns` 를 고쳐야 하고
  그것은 **배분 결정 경로**라 별도 승인 사항이다(CLAUDE.md §3). 이 모듈은
  관측·기록만 한다 — 같은 문장이 *"관측·검증·기록은 자유"* 라고 적는다.
- **`window` 가 영원히 참이라고 말하지 않는다.** 구조적 주장은 **가드가 있을 때만**
  구조적이다 — `tests/test_allocation_walk_forward_guard.py` 가 슬라이스를 지킨다.
"""
from __future__ import annotations

from typing import Any

from src.engine.run_evidence import (
    AXIS_DEGRADED,
    AXIS_OK,
    AXIS_UNKNOWN,
    rollup,
)

#: 룩어헤드를 가르는 네 축. ★`universe`·`price` 는 `run_evidence.AXIS_LABELS` 의
#: 이름을 그대로 쓴다★ — 같은 것을 두 이름으로 부르지 않는다(CLAUDE.md §2).
AXIS_WINDOW = "window"
AXIS_AS_OF = "as_of"
AXIS_UNIVERSE = "universe"
AXIS_PRICE = "price"

LOOKAHEAD_AXES = (AXIS_WINDOW, AXIS_AS_OF, AXIS_UNIVERSE, AXIS_PRICE)

LOOKAHEAD_AXIS_LABELS = {
    AXIS_WINDOW: "학습창 격리",
    AXIS_AS_OF: "절단일 고정",
    AXIS_UNIVERSE: "생존편향",
    AXIS_PRICE: "가격 정의",
}

#: ★이 경로가 **재지 않는** 축과 그 사유★ (AJ 의 `UNIMPLEMENTED_PREREGISTRATIONS`·
#: AL 의 `NOT_APPLICABLE_EFFECTS` 선례). 사유 없이 "안 잰다" 고만 적으면 다음
#: 사람이 무엇을 해야 하는지 모른다.
UNMEASURED_AXES: dict[str, str] = {
    AXIS_UNIVERSE: (
        "이 경로는 유니버스를 **사용자가 지금 담은 바구니**로 받습니다 — 그 바구니는 "
        "오늘 살아 있는 종목으로 골라졌고, R3 의 `universe_select.survivorship_of` "
        "판정을 통과하지 않습니다. ★생존편향이 없다는 뜻이 아니라 재지 않았다는 "
        "뜻입니다.★"),
    AXIS_PRICE: (
        "이 경로는 수익률을 `load_returns` 로 바로 받고 R2 의 "
        "`price_quality.basis_rollup`(원주가/수정주가 혼합 판정)을 통과하지 "
        "않습니다. ★수정주가는 기업행위로 **소급 개정**되므로 과거 시점에 알 수 "
        "없던 값일 수 있습니다 — 그 폭을 재지 않았습니다.★"),
}

_WINDOW_REASON = (
    "리밸런싱 시점 t 의 가중치는 `R_win = R[lo:t]`(t **미포함**)로만 계산됩니다 — "
    "창 밖 데이터를 쓰지 않는 것이 구조적으로 보장됩니다"
    "(`allocation_backtest.plan_walk_forward`). ★이 주장은 슬라이스를 지키는 "
    "가드 테스트가 있을 때만 구조적입니다.★")

_AS_OF_LOOSE = (
    "요청이 절단일을 고정하지 않았습니다 — 서버가 **오늘**로 잘랐습니다. "
    "★고정하지 않은 것은 고정한 것이 아닙니다★: 같은 요청을 내일 다시 내면 다른 "
    "구간이 됩니다. 재현하려면 `as_of` 를 주십시오.")

_AS_OF_UNKNOWN = (
    "이 실행의 데이터 좌표(`coverage`)를 받지 못해 절단일을 고정했는지 **알 수 "
    "없습니다** — ★미상은 통과가 아닙니다★.")

_NOTE = (
    "이 판정은 **이 실행이 룩어헤드를 어디까지 통제했는가**만 말합니다. "
    "★룩어헤드가 없다는 뜻이 아닙니다★ — 네 축 중 생존편향과 가격 정의는 이 경로가 "
    "아예 재지 않으며, 재지 않은 것은 깨끗한 것이 아니라 미상입니다. 학습창 격리는 "
    "구조적으로 보장되지만 그것은 **한 축**일 뿐이고, 예측력이나 경제적 가치는 "
    "이 판정과 무관합니다.")


def _axis(state: str, reason: str | None, **detail: Any) -> dict[str, Any]:
    return {"state": state, "reason": reason, **detail}


def window_axis() -> dict[str, Any]:
    """학습창이 미래를 보지 않는가. ★구조적으로 참★ — 가드가 지킨다."""
    return _axis(AXIS_OK, _WINDOW_REASON, slice="R[lo:t]",
                 guard="tests/test_allocation_walk_forward_guard.py")


def as_of_axis(coverage: Any) -> dict[str, Any]:
    """절단일을 **고정했는가**. ★서버가 오늘로 자른 것은 고정이 아니다★

    `_load_clean_returns` 가 P1-A 에서 이미 두 사실을 갈라 두었다 —
    `as_of_requested`(사용자가 고정했나)와 `as_of_effective`(서버가 실제로 쓴 날).
    여기서는 **앞의 것**이 판정을 정하고, 뒤의 것은 기록으로 남는다.
    """
    if not isinstance(coverage, dict) or not coverage:
        return _axis(AXIS_UNKNOWN, _AS_OF_UNKNOWN,
                     as_of_requested=None, as_of_effective=None)
    requested = coverage.get("as_of_requested")
    effective = coverage.get("as_of_effective")
    common = {"as_of_requested": requested or None,
              "as_of_effective": effective or None}
    if isinstance(requested, str) and requested.strip():
        return _axis(AXIS_OK, None, **common)
    return _axis(AXIS_DEGRADED, _AS_OF_LOOSE, **common)


def _unmeasured_axis(name: str) -> dict[str, Any]:
    """★안 잰 축은 사라지지 않는다★ — 빠지면 '문제없다' 로 읽힌다."""
    return _axis(AXIS_UNKNOWN, UNMEASURED_AXES[name], measured=False)


def lookahead_evidence(coverage: Any = None) -> dict[str, Any]:
    """이 정책 백테스트가 룩어헤드를 어디까지 통제했나.

    Args:
        coverage: `_load_clean_returns` 가 돌려준 데이터 좌표. 없으면 `as_of` 축이
            미상이 된다 — ★통과가 아니다★.
    """
    axes: dict[str, dict | None] = {
        AXIS_WINDOW: window_axis(),
        AXIS_AS_OF: as_of_axis(coverage),
        **{name: _unmeasured_axis(name) for name in UNMEASURED_AXES},
    }
    return {
        **rollup(axes, LOOKAHEAD_AXIS_LABELS),
        "axes": axes,
        # ★무엇을 안 쟀는지 목록으로 말한다★ — 롤업 문장만으로는 묻힌다.
        "unmeasured": sorted(UNMEASURED_AXES),
        "note": _NOTE,
    }
