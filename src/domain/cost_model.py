"""거래비용 — ★안 켠 것과 못 잰 것은 같은 0원이 아니다★ (AK1)
==============================================================================
설계: `docs/plans` AK · 레지스트리 `src/engine/cost_model_registry.py` ·
요율 출처 `src/data/market_rules.py`(★엔진 경계에서 읽는다 — 여기서는 안 읽는다★)

## 왜 이 모듈이 생겼나

채점표 #6 은 *"비용 모델이 **넷**이고 수수료 기본값이 10배 다르다"* 고 적었다.
★재보니 그 수도, 그 진단도 절반만 맞았다.★

1. **넷이 아니라 열넷이다.** 그리고 API 스키마 기본값끼리도 갈라져서 ★같은
   백테스트를 `stage11` 로 부르면 1.5bp, `screener`·`legacy` 로 부르면 15bp★ 다.
2. **더 큰 것은 불일치가 아니라 누락이다.** 실행 준비실(`execution_plan`)은
   `market_rules` 에서 수수료 + **증권거래세 18bp(매도 편도)** + 스프레드 +
   시장충격을 전부 계산하는데, 백테스트 쪽은 수수료 + 슬리피지뿐이고 ★나머지가
   전부 0★ 이었다. 18bp 매도세는 두 수수료 후보 **어느 쪽보다도 크다.**
3. **어느 값이 옳은지 이 저장소는 재지 않았다.** `market_rules` 스스로 근사라고
   적어 두었다 — 그래서 기본값을 통일하지 않는다. 안 재본 값으로 수렴시키면
   불일치가 ★거짓 합의★ 가 될 뿐이다.

## ★두 축을 섞지 않는다★

    비용 성분(무엇을 재나)  ⟂  그 성분의 상태(부과했나 · 껐나 · 못 쟀나)

Z(`kind ⟂ data_real`) · AA(`trigger ⟂ reason`) · AG(`signal_lag ⟂ fill_type`) ·
AH(`window ⟂ vintage`) · AI(`실행 모드 ⟂ 잔고 출처`) · AJ(`가족 크기 ⟂ 보정`)와
같은 규율이다.

## ★`off` 와 `unmeasurable` 이 이 모듈의 요점★

둘 다 **0원을 부과**하지만 뜻이 정반대다. **끈 것**은 사용자의 선택이고,
**못 잰 것**은 ★비용이 실제보다 싸게 나왔다는 경고★ 다. 한 상태로 접으면
*"시장충격을 안 켰다"* 와 *"켰는데 거래대금이 없어 못 쟀다"* 가 구별되지 않고,
뒤쪽은 **조용히 싼 백테스트**가 된다 — CLAUDE.md §4 가 금지하는 침묵 폴백이
비용에서 나타나는 형태다.

## ★이 모듈이 주장하지 않는 것★

- **요율이 옳다고 말하지 않는다.** 요율은 호출부가 넣고, 그 출처는
  `market_rules` 이며 그 모듈 스스로 *"기본값은 근사이며 실제 체결·정산은
  브로커 확정값을 따라야 함"* 이라고 적었다.
- **시장충격이 옳다고 말하지 않는다.** `k·√참여율` 은 문헌 근사이고 `k` 는
  ★측정치가 아니라 설정값★ 이다 — `policy_label` 이 그 사실을 함께 낸다.
- **백테스트가 현실적이 된다고 말하지 않는다.** 체결 가능성·부분체결·틱 정렬·
  가격제한은 비용이 아니라 체결 모델이고 여기서 다루지 않는다.
- **설정을 읽지 않는다.** 도메인이 설정 계층을 import 하면 같은 산수가
  환경변수에 따라 다른 답을 내고, 순수 함수를 설정 없이 시험할 수 없다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# ── 축 ①  비용 성분 ───────────────────────────────────────────────────────
#: 매매 수수료(편도, 양방향 부과).
COMPONENT_COMMISSION = "commission"
#: 체결 미끄러짐 근사(편도, 양방향).
COMPONENT_SLIPPAGE = "slippage"
#: 증권거래세 + 농특세. ★매도에만 붙는다★
COMPONENT_TAX = "tax"
#: 호가 스프레드 비용 프록시. 편도에 **절반**이 붙는다.
COMPONENT_SPREAD = "spread"
#: 시장충격 `k·√참여율`. ★참여율을 모르면 못 잰다 — 0 이 아니다★
COMPONENT_IMPACT = "impact"

#: ★다섯이 언제나 실린다★ — 빠진 성분은 0 이 아니라 부재이고, 부재는 보이지 않는다.
COMPONENTS = (COMPONENT_COMMISSION, COMPONENT_SLIPPAGE, COMPONENT_TAX,
              COMPONENT_SPREAD, COMPONENT_IMPACT)

# ── 축 ②  그 성분의 상태 ──────────────────────────────────────────────────
#: 재서 부과했다(금액이 0 일 수도 있다 — 매수의 매도세처럼).
STATE_CHARGED = "charged"
#: ★껐다 — 선택이지 부재가 아니다★
STATE_OFF = "off"
#: ★켰는데 재료가 없다 — 0 이 아니라 미상이다★
STATE_UNMEASURABLE = "unmeasurable"
#: 이 비용 모델에 그 성분 자체가 없다(다른 엔진을 레지스트리에 적을 때 쓴다).
STATE_UNSUPPORTED = "unsupported"

STATES = (STATE_CHARGED, STATE_OFF, STATE_UNMEASURABLE, STATE_UNSUPPORTED)

_OFF_REASON = "이 실행에서 껐습니다 — 부과하지 않기로 **선택**한 것이지 비용이 없다는 뜻이 아닙니다."
_NO_RATE = "켜져 있으나 요율을 읽지 못했습니다 — 지어내지 않고 미상으로 둡니다."
_NO_PARTICIPATION = ("켜져 있으나 참여율(주문금액/거래대금)을 구하지 못했습니다 — "
                     "★0 으로 부과하면 '충격이 없었다' 는 관측이 되어 비용이 조용히 "
                     "싸집니다.★")
_BUY_HAS_NO_TAX = "증권거래세는 매도에만 부과됩니다 — 매수의 0 원은 미상이 아닙니다."
_IMPACT_COEFF_NOTE = ("시장충격 계수는 ★측정치가 아니라 설정값★ 입니다 — "
                      "`impact_bp = k·√참여율` 은 문헌 근사이고 k 는 관측된 적이 없습니다.")
_ROUND_TRIP_REASON = ("왕복은 같은 금액의 매수 + 매도를 가정합니다. ★시장충격은 "
                      "참여율에 달려 있어 제외★ 했으므로 실제 왕복은 이보다 큽니다.")


@dataclass(frozen=True)
class CostComponent:
    """성분 하나의 판정. ★`krw == 0` 만 보면 셋을 구별할 수 없다★"""

    name: str
    state: str
    bps: float = 0.0
    krw: float = 0.0
    reason: str | None = None

    def to_dict(self) -> dict:
        return {"state": self.state, "bps": round(self.bps, 4),
                "krw": round(self.krw, 4), "reason": self.reason}


@dataclass(frozen=True)
class CostPolicy:
    """이 실행이 어떤 비용을 부과하는가. ★요율은 호출부가 넣는다★

    옵트인 셋은 **기본 꺼짐**이다 — 켜는 순간 저장된 실행과 골든의 뜻이 바뀐다.
    """

    commission_bps: float = 0.0
    slippage_bps: float = 0.0
    charge_tax: bool = False
    charge_spread: bool = False
    charge_impact: bool = False
    tax_bps: float | None = None
    spread_bps: float | None = None
    impact_coeff: float | None = None


@dataclass(frozen=True)
class CostBreakdown:
    """한 거래의 비용 분해. 다섯 성분이 **언제나** 들어 있다."""

    components: tuple[CostComponent, ...] = field(default_factory=tuple)
    total_krw: float = 0.0
    total_bps: float = 0.0
    n_unmeasurable: int = 0


def _finite(x) -> float | None:
    """숫자이고 유한한가. ★불리언은 숫자가 아니다★"""
    if x is None or isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    v = float(x)
    return v if math.isfinite(v) else None


def _charged(name: str, value: float, bps: float,
             reason: str | None = None) -> CostComponent:
    return CostComponent(name=name, state=STATE_CHARGED, bps=bps,
                         krw=value * bps / 1e4, reason=reason)


def _impact(value: float, policy: CostPolicy, participation) -> CostComponent:
    """시장충격 — `impact_bp = k·√참여율`. `execution_plan:89` 와 **같은 식**이다.

    ★음수·NaN 이 제곱근에 못 들어간다★ (CLAUDE.md §6) — 적자·결측 실데이터에서만
    터지는 종류의 버그라 mock 으로는 잡히지 않는다.
    """
    if not policy.charge_impact:
        return CostComponent(COMPONENT_IMPACT, STATE_OFF, reason=_OFF_REASON)
    coeff = _finite(policy.impact_coeff)
    if coeff is None:
        return CostComponent(COMPONENT_IMPACT, STATE_UNMEASURABLE, reason=_NO_RATE)
    p = _finite(participation)
    if p is None or p < 0:
        return CostComponent(COMPONENT_IMPACT, STATE_UNMEASURABLE,
                             reason=_NO_PARTICIPATION)
    return _charged(COMPONENT_IMPACT, value, coeff * math.sqrt(p))


def _tax(value: float, side: str, policy: CostPolicy) -> CostComponent:
    if not policy.charge_tax:
        return CostComponent(COMPONENT_TAX, STATE_OFF, reason=_OFF_REASON)
    rate = _finite(policy.tax_bps)
    if rate is None:
        return CostComponent(COMPONENT_TAX, STATE_UNMEASURABLE, reason=_NO_RATE)
    if side != "sell":
        return CostComponent(COMPONENT_TAX, STATE_CHARGED, reason=_BUY_HAS_NO_TAX)
    return _charged(COMPONENT_TAX, value, rate)


def _spread(value: float, policy: CostPolicy) -> CostComponent:
    """★편도에 스프레드의 **절반**★ — `execution_plan:73` 의 `* 0.5` 와 같은 뜻."""
    if not policy.charge_spread:
        return CostComponent(COMPONENT_SPREAD, STATE_OFF, reason=_OFF_REASON)
    rate = _finite(policy.spread_bps)
    if rate is None:
        return CostComponent(COMPONENT_SPREAD, STATE_UNMEASURABLE, reason=_NO_RATE)
    return _charged(COMPONENT_SPREAD, value, rate * 0.5)


def trade_cost(value: float, side: str, policy: CostPolicy,
               participation=None) -> CostBreakdown:
    """거래 하나의 비용. ★다섯 성분이 언제나 실리고, 0 원에도 이유가 있다★

    Args:
        value: 거래 금액(원).
        side: `"buy"` | `"sell"` — ★증권거래세가 갈리는 유일한 축★.
        participation: 주문금액 / 평균 거래대금. `None` 이면 충격은 **미상**이다.
    """
    v = _finite(value) or 0.0
    comps = (
        _charged(COMPONENT_COMMISSION, v, _finite(policy.commission_bps) or 0.0),
        _charged(COMPONENT_SLIPPAGE, v, _finite(policy.slippage_bps) or 0.0),
        _tax(v, side, policy),
        _spread(v, policy),
        _impact(v, policy, participation),
    )
    total = sum(c.krw for c in comps)
    return CostBreakdown(
        components=comps, total_krw=total,
        total_bps=(total / v * 1e4) if v > 0 else 0.0,
        n_unmeasurable=sum(1 for c in comps if c.state == STATE_UNMEASURABLE),
    )


def cost_label(breakdown: CostBreakdown) -> dict:
    """분해 → 리포트 블록. ★못 잰 성분 수가 총액 옆에 실린다★"""
    return {
        "components": {c.name: c.to_dict() for c in breakdown.components},
        "total_krw": round(breakdown.total_krw, 2),
        "total_bps": round(breakdown.total_bps, 4),
        "n_unmeasurable": breakdown.n_unmeasurable,
    }


def policy_label(policy: CostPolicy) -> dict:
    """정책 → 리포트 블록. ★설정값을 측정치처럼 적지 않는다★"""
    return {
        "commission_bps": policy.commission_bps,
        "slippage_bps": policy.slippage_bps,
        "charge_tax": policy.charge_tax, "tax_bps": policy.tax_bps,
        "charge_spread": policy.charge_spread, "spread_bps": policy.spread_bps,
        "charge_impact": policy.charge_impact, "impact_coeff": policy.impact_coeff,
        "impact_coeff_note": _IMPACT_COEFF_NOTE,
    }


def round_trip_bps(policy: CostPolicy) -> dict:
    """★같은 왕복을 이 정책으로 재면 몇 bp인가★ — 모델끼리 비교하는 단일 자.

    시장충격은 참여율에 달려 있어 **제외**하고, 그 사실을 함께 낸다.
    """
    quiet = CostPolicy(
        commission_bps=policy.commission_bps, slippage_bps=policy.slippage_bps,
        charge_tax=policy.charge_tax, tax_bps=policy.tax_bps,
        charge_spread=policy.charge_spread, spread_bps=policy.spread_bps,
        charge_impact=False)
    buy = trade_cost(1e8, "buy", quiet).total_bps
    sell = trade_cost(1e8, "sell", quiet).total_bps
    return {"buy_bps": round(buy, 4), "sell_bps": round(sell, 4),
            "round_trip_bps": round(buy + sell, 4),
            "impact_excluded": True, "reason": _ROUND_TRIP_REASON}
