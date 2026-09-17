"""귀인 증거 — ★안 잰 것과 정의되지 않는 것을 가른다★ (AL4)
==============================================================================
설계: `docs/plans` AL · 어휘 `src/domain/attribution_effect.py` · 롤업
`src/engine/run_evidence.rollup` (★`pit_evidence`·`decision_evidence`·
`estimator_evidence`·`multiplicity_evidence`·`cost_model_registry` 와 **같은
함수**★)

## 왜 이 모듈이 생겼나

분해기는 **커버리지**(몇 행을 봤나)를 재고 있었지만, *"이 효과는 왜 값이
없는가"* 는 묻지 않았다. 그래서 세 가지가 한 자리에 뭉쳤다:

| 실제 사실 | 예전 표현 |
|---|---|
| 잴 수 있는데 **안 쟀다**(`selection`) | 상수 `0` — ★관측 행세★ |
| 이 책에서는 **정의되지 않는다**(FX·국가) | 채점표에 *"없음"* — ★결함처럼★ |
| 재서 **0 이었다**(`netting`) | `0` — 위 둘과 구별 불가 |

## ★`not_applicable` 은 축이 아니다★

`fx`·`country` 를 결함 축에 넣으면 ★갚을 수 없는 부채★ 가 생긴다 — 포지션이
통화를 안 들고 주문 경로가 국내 전용인 책에서 환효과를 "언젠가 재겠다" 고 적는
것은 지키지 못할 약속이다. 그래서 축에서 빼고 **사유와 함께 따로** 싣는다.
`estimator_evidence` 의 `EXCLUDED_SITES` 와 같은 규율이다.

## ★이 모듈이 주장하지 않는 것★

- **귀인이 완성됐다고 말하지 않는다.** 여섯 중 `selection` 은 여전히 미측정이고,
  이 모듈은 그것이 **0 인 척하지 못하게** 할 뿐이다.
- **분해가 옳다고 말하지 않는다.** Brinson 선택항은 전략별 **벤치마크**를
  요구하는데 그 계열이 저장소에 없다.
"""
from __future__ import annotations

from typing import Any

from src.domain.attribution_effect import (
    CANDIDATE_EFFECTS,
    NOT_APPLICABLE_EFFECTS,
    STATE_MEASURED,
    STATE_UNKNOWN,
    STATE_UNMEASURED,
    effect_from_value,
)
from src.engine.run_evidence import AXIS_DEGRADED, AXIS_OK, AXIS_UNKNOWN, rollup

#: 축 이름 → 사람이 읽는 이름. ★`rollup` 이 하드 인덱싱하므로 빠지면 KeyError★
ATTRIBUTION_AXIS_LABELS = {
    "allocation": "배분 효과",
    "selection": "전략 선택",
    "macro": "매크로 오버레이",
    "netting": "청산 효과",
    "cost": "거래 비용",
    "cash": "현금 이자",
}

_NOTE = (
    "이 판정은 **어느 효과를 쟀고 어느 효과를 안 쟀나**만 말합니다. ★분해가 옳다는 "
    "뜻이 아닙니다★ — Brinson 선택항은 전략별 **벤치마크**를 요구하는데 그 계열이 "
    "저장소에 없어 `selection` 은 계산되지 않습니다(예전에는 그 자리에 상수 `0` 이 "
    "들어가 커버리지를 거짓으로 완전하게 만들었고, 잔차가 '복리 효과' 로 "
    "오명명됐습니다). FX·국가는 결함이 아니라 ★이 책에서 정의되지 않는 축★ 이라 "
    "따로 싣습니다.")

_STATE_TO_AXIS = {
    STATE_MEASURED: AXIS_OK,
    STATE_UNMEASURED: AXIS_DEGRADED,
    STATE_UNKNOWN: AXIS_UNKNOWN,
}


def attribution_evidence(cumulative: dict | None) -> dict[str, Any]:
    """누적 분해(`_cumulative_attribution`) → 효과별 상태 판정.

    Args:
        cumulative: `allocation_effect_pct` … `cash_effect_pct` 를 담은 dict.
            키가 없으면 그 효과는 **미측정**이다(0 이 아니다).
    """
    cum = cumulative or {}
    axes: dict[str, dict | None] = {}
    unmeasured: list[str] = []
    # ★후보 전부를 돌면서 거른다★ — `EFFECTS` 만 돌면 FX·국가가 애초에 등장하지
    # 않아 아래 필터가 **아무도 밟지 않는 분기**가 된다(변이 `d` 가 그렇게
    # 살아남았다). 후보를 돌아야 *"왜 안 보나"* 가 코드에 남는다.
    for name in CANDIDATE_EFFECTS:
        if name in NOT_APPLICABLE_EFFECTS:
            continue          # ★축이 아니다 — 갚을 수 없는 부채를 만들지 않는다★
        effect = effect_from_value(name, cum.get(f"{name}_effect_pct"))
        axes[name] = {"state": _STATE_TO_AXIS[effect.state],
                      "reason": effect.reason, "pct": effect.pct,
                      "effect_state": effect.state}
        if effect.state == STATE_UNMEASURED:
            unmeasured.append(name)

    return {
        **rollup(axes, ATTRIBUTION_AXIS_LABELS),
        "unmeasured": sorted(unmeasured),
        # ★결함 목록과 섞지 않는다★ — 사유와 함께 따로.
        "not_applicable": dict(NOT_APPLICABLE_EFFECTS),
        "note": _NOTE,
    }
