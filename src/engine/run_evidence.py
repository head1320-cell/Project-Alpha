"""실행 하나의 **증거 롤업** — 네 축을 한 판정으로

문서: `docs/plans/2026-09-06-quant-db-infra-roadmap.md` 0단계

## 무엇을 답하나 — *"이 백테스트를 믿어도 되나"*

로드맵 0단계의 완료 판정은 **한 곳에서 넷을 동시에 읽는 것**이다:
가격 정의 상태 · 재무 공시일 출처 비율 · 매크로 빈티지 비율 · 유니버스 생존편향
보정 여부. 넷은 서로 다른 계층이 만들고(엔진·라우트·`price_quality`·
`universe_select`), 이 모듈은 **그것들을 판정하지 않고 번역해 모은다.**

★규칙을 새로 만들지 않는다★ 각 축의 등급은 이미 그 축의 주인이 매겼다:
`price_quality.basis_rollup` 의 `state` · `universe_select.survivorship_of` 의
네 값 · P4 의 `pit/live/blocked` · V4 의 `measured/estimated/unknown`.
여기서 하는 일은 그 어휘를 **공통 세 상태**로 옮기고 하나로 접는 것뿐이다.

## ★boolean 을 만들지 않는다★

`backtest_runs.is_pit_verified` 는 참/거짓 둘뿐이라 "검증됨" 과 "확인하지 못함" 을
구별할 수 없다 — 그리고 실제로 **그 컬럼을 쓰는 코드가 없어** 모든 실행이 항상
"PIT 미검증" 으로 표시됐다. 그래서 판정은 네 상태이고, 컬럼에는
`is_pit_verified_flag()` 가 `True`/`False`/`None`(미상) 으로 옮긴다.

## 축이 넷인 이유

`price` 와 `universe` 는 **모든** 백테스트에 적용된다. `macro` 와
`fundamentals` 는 그 토큰을 쓴 실행에만 적용되고, 안 쓴 실행에는 `None`
(해당 없음)이다 — ★안 쓴 것과 재서 나쁜 것을 구별한다.★

★필수 축은 값이 없어도 사라지지 않는다★ 측정이 없으면 `unknown` 으로 **남는다.**
빠지면 "가격을 못 쟀다" 가 "가격은 문제없다" 로 둔갑하고, 남은 축 하나가
깨끗하다는 이유로 실행 전체가 `verified` 로 보고된다.
"""
from __future__ import annotations

from typing import Any

# ── 축 상태 (셋) ────────────────────────────────────────────────────────────
AXIS_OK = "ok"              # 그 축은 시점 정합됐다
AXIS_DEGRADED = "degraded"  # ★관측된★ 결함이 있다
AXIS_UNKNOWN = "unknown"    # 재지 못했다 — ★통과가 아니다★

# ── 실행 판정 (넷) ──────────────────────────────────────────────────────────
STATUS_VERIFIED = "verified"      # 적용되는 축이 전부 `ok`
STATUS_PARTIAL = "partial"        # 일부만 `ok`
STATUS_UNVERIFIED = "unverified"  # `ok` 가 없고 관측된 결함이 있다
STATUS_UNKNOWN = "unknown"        # `ok` 도 관측된 결함도 없다 — 못 쟀다

#: 모든 실행에 적용되는 축. ★값이 없으면 `unknown` 으로 남긴다★
REQUIRED_AXES = ("price", "universe")

#: 화면·로그에서 축을 부르는 이름.
AXIS_LABELS = {"price": "가격 정의", "universe": "유니버스",
               "macro": "매크로 시점", "fundamentals": "재무 공시일"}

_NO_MEASUREMENT = "측정값이 없습니다 — 이 실행에서 재지 못했습니다."


def _axis(state: str, reason: str | None, **detail: Any) -> dict[str, Any]:
    return {"state": state, "reason": reason, **detail}


def rollup(axes: dict[str, dict | None],
           labels: dict[str, str]) -> dict[str, Any]:
    """축들 → 하나의 판정. ★규칙은 여기 한 곳에만 있다★

    백테스트(`pit_evidence`)와 결정 경로(`decision_evidence`)가 **같은 함수**를
    부른다. 두 곳에 복사하면 한쪽만 고쳐도 타입 에러가 나지 않고, 화면에 따라
    다른 판정이 나온다 — `allocation_pipeline` 머리글이 적어 둔 바로 그 사건이다.

    Args:
        axes: 축 이름 → `_axis(...)` 또는 `None`(해당 없음).
        labels: 축 이름 → 사람이 읽는 이름. 요약 문장에 쓴다.

    ★`None` 축은 판정에 들어가지 않는다★ — 안 쓴 것과 재서 나쁜 것은 다르다.
    """
    applicable = [n for n, a in axes.items() if a is not None]
    ok = [n for n in applicable if axes[n]["state"] == AXIS_OK]
    broken = [n for n in applicable if axes[n]["state"] == AXIS_DEGRADED]
    foggy = [n for n in applicable if axes[n]["state"] == AXIS_UNKNOWN]

    if ok and not broken and not foggy:
        status = STATUS_VERIFIED
    elif ok:
        status = STATUS_PARTIAL
    elif broken:
        status = STATUS_UNVERIFIED
    else:
        status = STATUS_UNKNOWN

    if status == STATUS_VERIFIED:
        summary = ("적용되는 모든 축이 시점 정합됐습니다: "
                   + " · ".join(labels[n] for n in ok))
    else:
        bits = []
        if broken:
            bits.append("결함 " + " · ".join(labels[n] for n in broken))
        if foggy:
            bits.append("미상 " + " · ".join(labels[n] for n in foggy))
        summary = " / ".join(bits)

    return {"status": status, "axes": axes,
            # ★안 쓴 축은 여기 없다★ — 매크로를 안 쓴 전략에 매크로 결함은 없다.
            "applicable": applicable, "ok_axes": ok,
            "broken_axes": broken, "unknown_axes": foggy,
            "summary": summary}


# ══════════════════════════════════════════════════════════════════════════
# 축별 번역 — ★판정하지 않고 옮긴다★
# ══════════════════════════════════════════════════════════════════════════

def _price_axis(meta: dict | None) -> dict[str, Any]:
    """`price_quality.basis_rollup` 의 `state` 를 그대로 쓴다."""
    if not meta:
        return _axis(AXIS_UNKNOWN, _NO_MEASUREMENT)
    state = meta.get("state")
    if state not in (AXIS_OK, AXIS_DEGRADED, AXIS_UNKNOWN):
        # ★모르는 값을 낙관하지 않는다★
        return _axis(AXIS_UNKNOWN, f"가격 정의 상태를 해석할 수 없습니다({state}).")
    return _axis(state, meta.get("reason"),
                 uniform_adjusted_pct=meta.get("uniform_adjusted_pct"))


def _universe_axis(meta: dict | None) -> dict[str, Any]:
    """`universe_select.survivorship_of` 의 네 값을 셋으로 접는다.

    ★`approximated` 는 `ok` 가 아니다★ 시총 상위 재구성은 지수 편입의 근사이고,
    그 차이가 곧 편입·편출 종목의 수익률이다.
    """
    if not meta:
        return _axis(AXIS_UNKNOWN, _NO_MEASUREMENT)
    from src.engine.universe_select import (
        SURVIVORSHIP_APPROXIMATED,
        SURVIVORSHIP_CORRECTED,
        SURVIVORSHIP_NOT_CORRECTED,
    )
    value = meta.get("survivorship")
    reason = meta.get("reason")
    if value == SURVIVORSHIP_CORRECTED:
        return _axis(AXIS_OK, reason, survivorship=value)
    if value in (SURVIVORSHIP_APPROXIMATED, SURVIVORSHIP_NOT_CORRECTED):
        return _axis(AXIS_DEGRADED, reason, survivorship=value)
    return _axis(AXIS_UNKNOWN, reason or _NO_MEASUREMENT, survivorship=value)


def _macro_axis(meta: dict | None) -> dict[str, Any] | None:
    """P4 의 `pit`/`live`/`blocked` → 셋. ★안 쓴 실행은 `None`(해당 없음).★"""
    if not meta:
        return None
    pit = int(meta.get("pit") or 0)
    live = int(meta.get("live") or 0)
    blocked = int(meta.get("blocked") or 0)
    if live > 0:
        return _axis(AXIS_DEGRADED,
                     f"매크로 토큰 {live}개가 현재 개정본으로 평가됐습니다 — "
                     "그 조건에는 룩어헤드가 있습니다.", pit_pct=meta.get("pit_pct"))
    if blocked > 0:
        # ★평가되지 못한 토큰은 룩어헤드도 시점 정합도 아니다 — 판정 불가다.★
        return _axis(AXIS_UNKNOWN,
                     f"매크로 토큰 {blocked}개가 값을 얻지 못해 평가되지 "
                     "않았습니다 — 그 조건은 판정에서 빠졌습니다.",
                     pit_pct=meta.get("pit_pct"))
    if pit > 0:
        return _axis(AXIS_OK, None, pit_pct=meta.get("pit_pct"))
    return _axis(AXIS_UNKNOWN, "매크로 토큰이 하나도 집계되지 않았습니다.")


def _fundamentals_axis(meta: dict | None) -> dict[str, Any] | None:
    """V4 의 `measured`/`estimated`/`unknown` → 셋. 안 쓴 실행은 `None`.

    ★관측된 열화가 미상보다 강한 진술이다★ 추정이 하나라도 있으면 `degraded` 다 —
    미상은 사라지지 않고 개수와 사유에 남는다(강등이지 삭제가 아니다).
    """
    if not meta:
        return None
    measured = int(meta.get("measured") or 0)
    estimated = int(meta.get("estimated") or 0)
    unknown = int(meta.get("unknown") or 0)
    if estimated > 0:
        return _axis(AXIS_DEGRADED,
                     f"(종목, 기간) {estimated}건이 실제 접수일 대신 정적 시차로 "
                     "추정됐습니다.", measured_pct=meta.get("measured_pct"))
    if unknown > 0:
        return _axis(AXIS_UNKNOWN,
                     f"(종목, 기간) {unknown}건에서 빈티지 유무를 확인하지 "
                     "못했습니다.", measured_pct=meta.get("measured_pct"))
    if measured > 0:
        return _axis(AXIS_OK, None, measured_pct=meta.get("measured_pct"))
    # 0/0 — ★비어 있는 것을 100% 로 읽지 않는다★
    return _axis(AXIS_UNKNOWN,
                 "재무 공시일을 한 건도 집계하지 못했습니다"
                 + (f" (재무가 없는 종목 {meta.get('tickers', {}).get('no_financials')}개)"
                    if (meta.get("tickers") or {}).get("no_financials") else "") + ".")


# ══════════════════════════════════════════════════════════════════════════
# 롤업
# ══════════════════════════════════════════════════════════════════════════

def pit_evidence(*, price_basis: dict | None, universe: dict | None,
                 macro_lookahead: dict | None,
                 fundamentals_pit: dict | None) -> dict[str, Any]:
    """네 축을 모아 실행 하나의 판정을 낸다.

    Returns:
        `{status, axes, applicable, ok_axes, broken_axes, unknown_axes,
          summary, note}`
    """
    axes: dict[str, dict | None] = {
        "price": _price_axis(price_basis),
        "universe": _universe_axis(universe),
        "macro": _macro_axis(macro_lookahead),
        "fundamentals": _fundamentals_axis(fundamentals_pit),
    }
    # ★필수 축은 절대 `None` 이 되지 않는다★ (위 두 함수가 그것을 보장한다)
    for name in REQUIRED_AXES:
        if axes.get(name) is None:
            axes[name] = _axis(AXIS_UNKNOWN, _NO_MEASUREMENT)

    rolled = rollup(axes, AXIS_LABELS)
    return {
        **rolled,
        # ★결론은 증거보다 강할 수 없다★ `verified` 도 보증 범위가 좁다.
        "note": ("이 판정은 **시점 정합**에 대한 것입니다 — 가격·유니버스·매크로·"
                 "재무의 *언제* 를 봅니다. `verified` 라도 값 자체의 정확성이나 "
                 "예측력·경제적 가치를 말하지 않습니다. 특히 재무는 접수일이 "
                 "실측이어도 `estimated` 기간의 **값**은 정정공시가 덮은 표에서 "
                 "옵니다."),
    }


def is_pit_verified_flag(status: str | None) -> bool | None:
    """판정 → 저장 컬럼(`backtest_runs.is_pit_verified`).

    ★미상은 거짓이 아니다★ 컬럼이 NULL 을 받을 수 있으므로 3-값 그대로 쓴다 —
    `unknown` 을 `False` 로 접으면 "확인 못 함" 이 "확인했더니 아님" 이 된다.
    """
    if status == STATUS_VERIFIED:
        return True
    if status in (STATUS_PARTIAL, STATUS_UNVERIFIED):
        return False
    return None
