"""리밸런스 사유 — ★두 축을 갈라 놓는다★ (AA1)
==============================================================================
설계: `docs/plans` AA · 애드덤 합격기준 #8 · 도메인 아키텍처 §4
소비자: `src/engine/rebalance_policy.py`(생산) · `investment_decision.decide()`(기록)

## 왜 두 축인가

    trigger          왜 **검토**했는가   달력 · 괴리 · 국면 전환 · 변동성 급등
    decision reason  왜 **거래/보류/미정**인가

`rebalance_policy.detect_triggers` 가 이미 그 구분을 문장으로 적어 두었다 —
*"트리거는 검토 시점을 알릴 뿐 거래 근거가 아닙니다. 거래 여부는 편익 대 비용이
정합니다."* 한 목록에 넣으면 ★"국면이 바뀌어 **거래했다**" 와 "국면이 바뀌어
**들여다봤다**" 가 같은 값★이 된다. Z 에서 `kind`(무슨 성과) 와 `data_real`(무슨
데이터)을 가른 것과 같은 규율이다.

## ★설계 문서의 9개 목록을 실측이 고쳤다★

도메인 아키텍처 §4 는 상수 9개를 제안했다. 코드와 대조한 결과:

  · 결정 사유로 실재하는 것은 **둘**(`utility_gain` · `none_below_cost`)
  · 셋은 **트리거 축**이었다(`calendar` · `regime_change` · `volatility_spike`)
  · **넷은 생산자가 없었다** — `band_breach`(밴드 이탈은 TRADE 사유가 아니다.
    이탈해도 편익<비용이면 HOLD 다) · `constraint_binding`
    (`investment_decision._legs_from` 이 `[]` 로 고정) · `contribution` ·
    `glide_path`(적립금·생애주기 코드 자체가 없다)

반대로 **코드에는 있는데 목록에 없던 사유가 넷**이다 — `inside_band` 와
`undetermined` 3종. 그래서 이 모듈은 문서가 아니라 **코드를 따른다**.

★생산자 없는 상수는 만들지 않는다★ — Z 에서 `backtest_runs` 모드 컬럼을 만들지
않은 것과 같은 판단이다. (Z 의 `ra_testbed` 는 애드덤 §4 가 4종 분리를 **요구**해
어휘에 남긴 것이라 사정이 다르다.)
"""
from __future__ import annotations

# ══════════════════════════════════════════════════════════════════════════
# 축 ① — 왜 **검토**했는가 (trigger)
# ══════════════════════════════════════════════════════════════════════════
#: ★`src/engine/portfolio_rebalancer.py` 가 이미 내는 문자열 그대로다★
#: 이름을 `volatility_spike` 로 "고치면" 일곱 번째 어휘가 생긴다(채점표 §5-1).
#: `tests/test_rebalance_reason.py` 가 생산자 소스와 대조해 고정한다.
TRIGGER_CALENDAR = "calendar"
TRIGGER_DRIFT = "drift"
TRIGGER_REGIME_CHANGE = "regime_change"
TRIGGER_VOL_SPIKE = "vol_spike"

REBALANCE_TRIGGERS = (TRIGGER_CALENDAR, TRIGGER_DRIFT,
                      TRIGGER_REGIME_CHANGE, TRIGGER_VOL_SPIKE)

#: ★최소 간격 미달은 트리거가 아니라 **억제**다★ — `should_rebalance` 가
#: `triggers: []` 로 돌려주므로 목록에 없다. 트리거가 비었다는 사실과
#: "간격 때문에 눌렸다" 는 사실은 다르고, 후자는 그쪽 `reason` 문자열에만 있다.
TRIGGER_SUPPRESSED_NOTE = (
    "최소 간격 미달은 트리거 목록에 오르지 않습니다 — 억제이지 트리거가 아닙니다")


# ══════════════════════════════════════════════════════════════════════════
# 축 ② — 왜 **거래/보류/미정**인가 (decision reason)
# ══════════════════════════════════════════════════════════════════════════
#: 기대효용 개선이 비용 문턱을 넘었다.
REASON_UTILITY_GAIN = "utility_gain"
#: 문턱을 넘지 못했다. ★거래하지 않기로 한 것도 결정이다★ — 가장 자주 일어나는
#: 판단이고, 이름이 없으면 **가장 흔한 결정이 기록되지 않는다**.
REASON_BELOW_COST = "none_below_cost"
#: 모든 자산이 각자의 무거래 밴드 안이다(비용을 알아 밴드를 세울 수 있었을 때).
REASON_INSIDE_BAND = "inside_band"
#: 포트폴리오 평가액이 0 이하 — 문제를 세울 수조차 없다.
REASON_NO_PORTFOLIO_VALUE = "no_portfolio_value"
#: 거래비용을 계산하지 못했다.
REASON_COST_UNKNOWN = "cost_unknown"
#: 조건부 μ/Σ 가 없어 기대효용 개선을 계산하지 못했다.
#: ★트리거가 울려도 편익을 모르면 거래를 권하지 않는다★ — 그것이 이 사유의 요점이다.
REASON_BENEFIT_UNKNOWN = "benefit_unknown"

DECISION_REASONS = (
    REASON_UTILITY_GAIN, REASON_BELOW_COST, REASON_INSIDE_BAND,
    REASON_NO_PORTFOLIO_VALUE, REASON_COST_UNKNOWN, REASON_BENEFIT_UNKNOWN,
)

#: 사유 → 그 사유가 속한 결정. ★한 사유가 두 결정에 걸치지 않는다★ —
#: 걸치면 코드만 보고는 무엇이 일어났는지 알 수 없고, 그러면 코드를 둔 뜻이 없다.
#: 값은 `rebalance_policy.DECISION_*` 와 같은 문자열이다(새 어휘를 만들지 않는다).
REASON_DECISION = {
    REASON_UTILITY_GAIN: "trade",
    REASON_BELOW_COST: "hold",
    REASON_INSIDE_BAND: "hold",
    REASON_NO_PORTFOLIO_VALUE: "undetermined",
    REASON_COST_UNKNOWN: "undetermined",
    REASON_BENEFIT_UNKNOWN: "undetermined",
}

#: 화면·리포트가 쓰는 짧은 한국어 이름. ★판정을 담지 않는다★ — `none_below_cost`
#: 를 "거래 불필요" 로 적으면 *필요 없었다* 는 없는 판단이 생긴다.
REASON_LABELS = {
    REASON_UTILITY_GAIN: "효용 개선이 비용 문턱을 넘음",
    REASON_BELOW_COST: "효용 개선이 비용 문턱에 못 미침",
    REASON_INSIDE_BAND: "전 자산이 무거래 밴드 안",
    REASON_NO_PORTFOLIO_VALUE: "포트폴리오 평가액 없음",
    REASON_COST_UNKNOWN: "거래비용 미상",
    REASON_BENEFIT_UNKNOWN: "기대효용 개선 미상",
}
