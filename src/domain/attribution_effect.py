"""귀인 효과 — ★상수 0 이 관측 행세를 했다★ (AL1)
==============================================================================
설계: `docs/plans` AL · 롤업 `src/engine/attribution_evidence.py` ·
분해기 `src/engine/attribution_decomposer.py` · 문장 `src/domain/daily_explanation.py`

## 왜 이 모듈이 생겼나

채점표는 귀인을 *"5효과 + 커버리지 측정 + 잔차 라벨. ★FX·국가·현금 기여 없음★,
수수료는 `cost_effect` 하나로 뭉쳐 있다"* 라고 적었다. ★재보니 네 문장 중 셋이
틀렸거나 상황을 뒤집어 말한다.★

1. **"5효과" 는 4 측정 + 상수 1 이었다.** `selection_effect=0` 이 두 생산자에
   하드코딩돼 있었다(`realism_engine:409` · `multi_strategy_backtest:332`).
   ★그리고 그 상수가 가드를 무력화했다★ — `column_coverage` 는 `pd.notna` 로
   세므로 상수 `0` 도 "관측됨" 이 되고, `coverage_complete` 가 **거짓으로 참**이
   되어 잔차가 `unexplained_pct` 대신 `interaction_pct`(복리 효과)로 이름 붙었다.
   저장소가 *"커버리지가 불완전하면 잔차를 복리라고 부르기를 거부한다"* 며 만든
   바로 그 가드를, 하드코딩된 0 이 정확히 무력화하고 있었다.
2. **현금 기여는 "없는" 것이 아니라 비용에 섞여 있었다.** `realism_engine:412` 이
   `cost_effect + cash_yield` 를 한 칸에 넣고 화면이 "거래 비용" 이라 불렀다 —
   ★부호도 성격도 반대인 둘★ 이다.
3. **FX 는 "없는" 것이 아니라 정의되지 않는다.** 포지션이 통화를 안 들고
   (`currency` 필드 0건), 주문 경로가 KR 전용이며(`target_versions.untradable`),
   원화 상장 해외 ETF 는 환효과가 이미 가격에 들어 있다. AB 가 이미 그 사유를
   `daily_explanation.UNMEASURABLE_DRIVERS` 에 적어 두었다.

## ★두 축을 섞지 않는다★

    효과의 종류(무엇을 재나)  ⟂  그 효과의 상태(쟀나 · 안 쟀나 · 정의되지 않나)

Z·AA·AG·AH·AI·AJ·AK 와 같은 규율이다.

## ★`unmeasured` 와 `not_applicable` 을 가른다★

둘 다 값이 없지만 앞은 **부채**(언젠가 재야 한다)이고 뒤는 **부채가 아니다**
(잴 대상 자체가 없다). 한 상태로 접으면 채점표가 FX 를 `selection` 과 같은
결함으로 세게 되고, 그것은 ★갚을 수 없는 부채★ 다 — 지금 채점표가 정확히 그렇게
적혀 있다.

## ★`0.0` 은 `measured` 다★

관측된 0 과 안 잰 것을 가르는 것이 이 모듈의 전부이므로, 값이 0 이라는 이유로
상태를 내리면 스스로를 배반한다.

## ★이 모듈이 주장하지 않는 것★

- **분해가 옳다고 말하지 않는다.** Brinson 분해의 타당성은 벤치마크 정의에
  달려 있고, 이 저장소는 전략별 벤치마크 계열을 갖고 있지 않다.
- **`selection` 을 재게 됐다고 말하지 않는다.** 선택항 `Σ wᵢ(rᵢ − bᵢ)` 는 `bᵢ`
  를 요구하는데 그것이 없다 — ★없는 벤치마크로 낸 선택 효과는 날조다.★ 이
  모듈이 하는 일은 그 부재가 **0 인 척하지 못하게** 하는 것뿐이다.
- **FX 를 재게 됐다고 말하지 않는다.** 정의되지 않는다고 적을 뿐이다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# ── 축 ①  효과의 종류 ─────────────────────────────────────────────────────
#: 자산/전략 비중 선택의 기여.
EFFECT_ALLOCATION = "allocation"
#: 전략 **안**에서의 종목 선택 기여. ★현재 미측정★ — 전략별 벤치마크가 없다.
EFFECT_SELECTION = "selection"
#: 매크로 오버레이가 비중을 흔든 기여.
EFFECT_MACRO = "macro"
#: 전략 간 주문 상계로 아낀 비용.
EFFECT_NETTING = "netting"
#: 거래로 **나간** 돈(수수료·슬리피지·충격). ★음수★
EFFECT_COST = "cost"
#: 안 쓴 현금이 **번** 이자. ★양수이고 비용이 아니다★ (AL3)
EFFECT_CASH = "cash"

EFFECTS = (EFFECT_ALLOCATION, EFFECT_SELECTION, EFFECT_MACRO,
           EFFECT_NETTING, EFFECT_COST, EFFECT_CASH)

#: 환효과. ★이 책에서는 정의되지 않는다★ — 아래 `NOT_APPLICABLE_EFFECTS` 참조.
EFFECT_FX = "fx"
#: 국가 기여. 같은 이유로 정의되지 않는다.
EFFECT_COUNTRY = "country"

#: ★완전한 귀인이라면 있어야 할 축 전부★ — `EFFECTS`(이 책이 재는 여섯) +
#: 정의되지 않는 둘. 후보를 적어 두지 않으면 *"FX 를 왜 안 보나"* 라는 질문이
#: 코드 어디에도 남지 않고, 그것을 거르는 분기는 ★아무도 밟지 않는 공허한 분기★
#: 가 된다(변이 `d` 가 그렇게 살아남았다).
CANDIDATE_EFFECTS = (*EFFECTS, EFFECT_FX, EFFECT_COUNTRY)

# ── 축 ②  그 효과의 상태 ──────────────────────────────────────────────────
#: 관측해서 값이 있다. ★`0.0` 도 여기다★
STATE_MEASURED = "measured"
#: ★잴 수 있는데 안 쟀다★ — 부채다.
STATE_UNMEASURED = "unmeasured"
#: ★이 책에서는 정의되지 않는다★ — 부채가 아니다.
STATE_NOT_APPLICABLE = "not_applicable"
#: 물었는데 답을 못 얻었다(모양이 다르거나 유한하지 않다).
STATE_UNKNOWN = "unknown"

STATES = (STATE_MEASURED, STATE_UNMEASURED, STATE_NOT_APPLICABLE, STATE_UNKNOWN)

#: ★이 책에서는 정의되지 않는 효과★ — 사유와 함께.
#: `fx` 문장은 `daily_explanation.UNMEASURABLE_DRIVERS[DRIVER_FX]` 와 **같다**
#: (같은 것을 두 이름으로 부르지 않는다). 아래 `_sync_fx_reason()` 이 강제한다.
NOT_APPLICABLE_EFFECTS: dict[str, str] = {
    EFFECT_FX: "",  # ← import 시점에 `daily_explanation` 의 문장으로 채운다
    EFFECT_COUNTRY: (
        "국가 귀인을 낼 축이 없습니다 — 주문 경로가 국내 전용이라"
        "(`target_versions.untradable()` 이 6자리 코드가 아닌 것을 막습니다) "
        "모든 포지션이 한 국가에 있고, 원화 상장 해외 ETF 의 국가 노출은 "
        "룩스루 데이터가 없어 떼어 낼 수 없습니다. ★없는 것이 아니라 정의되지 "
        "않는 것입니다.★"),
}

_DEFAULT_UNMEASURED = (
    "이 실행에서 관측되지 않았습니다 — ★0 이 아니라 미상입니다.★ "
    "0 으로 적으면 '재봤더니 기여가 없었다' 는 관측이 되어 버립니다.")
_UNUSABLE = (
    "값이 숫자가 아니거나 유한하지 않아 관측으로 쓸 수 없습니다 — 지어내지 않습니다.")


def _sync_fx_reason() -> None:
    """FX 사유를 `daily_explanation` 에서 가져온다. ★문장은 한 곳에만 있다★

    ★순수성을 지킨다★ — `daily_explanation` 도 `src/domain/` 의 순수 모듈이라
    이 import 는 계층을 넘지 않는다.

    ★없는 키를 만들지 않는다★ — 예전에는 대입이라 표를 비워도 `fx` 가 되살아났고,
    그래서 "표를 비운다" 는 변이가 살아남았다(변이 `l`). 있는 키의 문장만 채운다.
    """
    from src.domain.daily_explanation import DRIVER_FX, UNMEASURABLE_DRIVERS
    if EFFECT_FX in NOT_APPLICABLE_EFFECTS:
        NOT_APPLICABLE_EFFECTS[EFFECT_FX] = UNMEASURABLE_DRIVERS[DRIVER_FX]


_sync_fx_reason()


@dataclass(frozen=True)
class AttributionEffect:
    """효과 하나의 판정. ★`pct is None` 만 보면 셋을 구별할 수 없다★"""

    name: str
    state: str
    pct: float | None = None
    reason: str | None = None

    @property
    def is_debt(self) -> bool:
        """언젠가 재야 하는가. ★`not_applicable` 은 부채가 아니다★"""
        return self.state == STATE_UNMEASURED

    def to_dict(self) -> dict:
        return {"name": self.name, "state": self.state, "pct": self.pct,
                "reason": self.reason, "is_debt": self.is_debt}


def effect_from_value(name: str, value, *, reason: str | None = None
                      ) -> AttributionEffect:
    """값 → 효과. ★`0.0` 은 관측이고 `None` 은 미측정이다★

    이 함수가 이 모듈의 요점을 짊어진다 — `selection_effect = 0` 이 관측 행세를
    한 사고를 되풀이하지 않으려면 **값과 상태를 다른 자리에서** 정해야 한다.
    """
    if name in NOT_APPLICABLE_EFFECTS:
        return AttributionEffect(name=name, state=STATE_NOT_APPLICABLE,
                                 reason=reason or NOT_APPLICABLE_EFFECTS[name])
    if value is None:
        return AttributionEffect(name=name, state=STATE_UNMEASURED,
                                 reason=reason or _DEFAULT_UNMEASURED)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return AttributionEffect(name=name, state=STATE_UNKNOWN,
                                 reason=reason or _UNUSABLE)
    v = float(value)
    if not math.isfinite(v):
        return AttributionEffect(name=name, state=STATE_UNKNOWN,
                                 reason=reason or _UNUSABLE)
    return AttributionEffect(name=name, state=STATE_MEASURED, pct=v,
                             reason=reason)


def effect_label(effect: AttributionEffect) -> dict:
    """효과 → 리포트 한 칸."""
    return effect.to_dict()


def attribution_label(effects) -> dict:
    """효과들 → 리포트 블록. ★부채와 '정의되지 않음' 을 따로 센다★

    섞으면 채점표가 FX 를 `selection` 과 같은 결함으로 세게 되고, 그것은 갚을 수
    없는 부채가 된다.
    """
    by = {e.name: e for e in effects}
    measured = sorted(n for n, e in by.items() if e.state == STATE_MEASURED)
    unmeasured = sorted(n for n, e in by.items() if e.state == STATE_UNMEASURED)
    unknown = sorted(n for n, e in by.items() if e.state == STATE_UNKNOWN)
    return {
        "effects": {n: effect_label(e) for n, e in by.items()},
        "measured": measured, "n_measured": len(measured),
        "unmeasured": unmeasured, "n_unmeasured": len(unmeasured),
        "unknown": unknown,
        # ★부채 목록과 섞지 않는다★
        "not_applicable": sorted(NOT_APPLICABLE_EFFECTS),
        "not_applicable_reasons": dict(NOT_APPLICABLE_EFFECTS),
    }
