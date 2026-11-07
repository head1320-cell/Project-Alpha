"""추정 적합 — ★어느 창·어느 빈티지 위에 섰나★ (AH1)
==============================================================================
설계: `docs/plans` AH · 채점표 `docs/specs/2026-09-12-addendum-scorecard.md` §4

## 왜 이 모듈이 생겼나 — ★채점표가 틀린 곳을 가리키고 있었다★

채점표 §4 `bias 검사` 행은 이렇게 적혀 있었다:

    ★데이터 누출 축이 없다★ — GARCH·DCC·MarkovRegression·GaussianMixture·
    DynamicFactor·genpareto·LedoitWolf 가 **전체표본 적합**이고 어느 축도
    그것을 보지 않는다.

재보니 ★그 일곱 중 어느 것도 백테스트·배분 결정에 닿지 않는다.★ GARCH 는 손수
구현된 리포트 루트이고(`arch_model` 은 저장소에 아예 없다), `regime_ensemble` 은
자기 모듈에 *"배분에 쓰이지 않습니다 — 진단 전용"* 을 이미 들고 있으며,
`kis_backtest_engine` 의 engine-layer import 는 `quant_metrics`·`fill_price`·
`pit_store`·`execution_assumption`·`price_quality` 뿐이다. 배분에 닿는 것은
`LedoitWolf` 하나인데 그것은 **후행 252일 창**이고 워크포워드에서 `R_win = R[lo:t]`
로 잘린다.

결정에 실제로 닿는 누출은 따로 있고, ★여섯 중 넷이 이미 자기 누출을 알고 산문으로
적어 뒀다★(`path_source:"recomputed"` · `revision_bias` · 대리계열 선택 노트 …).
없는 것은 누출 자체가 아니라 **어휘·판정·롤업·기록**이었다. 여섯 방언이라 기계가
셀 수 없고, 화면이 비교할 수 없고, 실행 기록에 남지 않는다.

## ★두 축을 섞지 않는다★

    적합 창(window)  ⟂  값의 빈티지(vintage)

실측이 그것을 요구했다. `regime_axes.zscore_at` 은 **창은 후행(깨끗)인데 값이 현재
빈티지**이고, `reverse_stress.factor_covariance` 는 **창은 as-of 인데 표준화가
전체표본**이다. 하나로 뭉치면 그 구분이 사라지고, 그러면 어디를 고쳐야 하는지
아무도 모른다. Z 의 `kind ⟂ data_real`, AA 의 `trigger ⟂ reason`, AG 의
`signal_lag ⟂ fill_type` 과 같은 규율이다.

## ★`trailing` 은 `bounded` 가 아니다★

라이브 배분에서 *"최근 252일"* 은 **옳다**. 같은 코드가 과거 시점 재현에 쓰이면
**틀린다**. 둘을 같은 칸에 넣으면 어느 쪽이었는지 영원히 못 가른다 — 그래서
별개 상태이고, ★`ok` 가 아니다★.

## ★이 모듈이 주장하지 않는 것★

- **`bounded` 가 편향 없음이 아니다.** `etf_prices.as_of()` 의 절단은 ★월×21봉
  근사★(`etf_prices.py:131-133`)이지 날짜 정확이 아니다.
- **상태가 좋다고 추정이 옳다는 뜻이 아니다.** 창과 빈티지는 *"언제 것을 봤나"* 이지
  *"모형이 맞나"* 가 아니다.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── 축 ① 적합 창 — 결정 시점까지로 잘렸나 ──────────────────────────────────

#: as-of / 워크포워드로 **결정 시점까지** 잘렸다.
WINDOW_BOUNDED = "bounded"
#: 최근 N개 — ★라이브에선 옳고 과거 재현엔 틀리다★. 통과가 아니다.
WINDOW_TRAILING = "trailing"
#: 전체표본에 적합했다.
WINDOW_FULL_SAMPLE = "full_sample"
#: 재지 못했다. ★통과가 아니다★
WINDOW_UNMEASURED = "unmeasured"

WINDOW_STATES = (WINDOW_BOUNDED, WINDOW_TRAILING, WINDOW_FULL_SAMPLE, WINDOW_UNMEASURED)

# ── 축 ② 값의 빈티지 — 창 안의 값이 그때 값인가 ────────────────────────────

#: 그 시점에 알 수 있었던 값(빈티지 재현).
VINTAGE_AS_OF = "as_of"
#: 현재 개정본 — ★창이 깨끗해도 값이 미래를 안다★.
VINTAGE_CURRENT = "current"
#: 재지 못했다. ★통과가 아니다★
VINTAGE_UNMEASURED = "unmeasured"

VINTAGE_STATES = (VINTAGE_AS_OF, VINTAGE_CURRENT, VINTAGE_UNMEASURED)

# ── 판정 어휘 ──────────────────────────────────────────────────────────────
#: ★`run_evidence` 와 **같은 문자열**★ — 축 상태 어휘를 두 벌 만들지 않는다.
#: 순수 계층이라 `src.engine` 을 import 하지 않고, 대신 테스트가 두 값이 같음을
#: 못 박는다(`test_estimator_fit.py`).
STATE_OK = "ok"
STATE_DEGRADED = "degraded"
STATE_UNKNOWN = "unknown"

_WINDOW_REASON = {
    WINDOW_TRAILING: ("적합 창이 후행 N개입니다 — 라이브 판단에는 맞지만 과거 시점을 "
                      "재현한 것은 아닙니다."),
    WINDOW_FULL_SAMPLE: ("적합 창이 전체표본입니다 — 추정이 결정 시점 이후의 관측까지 "
                         "보고 있습니다."),
    WINDOW_UNMEASURED: "적합 창을 재지 못했습니다 — 잘렸는지 아닌지 알 수 없습니다.",
}

_VINTAGE_REASON = {
    VINTAGE_CURRENT: ("값이 현재 빈티지입니다 — 창이 잘려 있어도 그 안의 수치는 "
                      "이후 개정을 반영한 값입니다."),
    VINTAGE_UNMEASURED: ("값의 빈티지를 재지 못했습니다 — 당시 값인지 현재 개정본인지 "
                         "알 수 없습니다."),
}


@dataclass(frozen=True)
class EstimatorFit:
    """한 추정 자리의 적합 조건. ★`None` 은 미상이지 통과가 아니다★"""

    site: str | None = None
    window: str | None = None
    vintage: str | None = None
    consumer: str | None = None      # "allocation" | "backtest"
    note: str | None = None

    def to_dict(self) -> dict:
        return {"site": self.site, "window": self.window, "vintage": self.vintage,
                "consumer": self.consumer, "note": self.note}


def _unmeasured(value: str | None, unmeasured: str) -> bool:
    return value is None or value == unmeasured


def fit_state(window: str | None, vintage: str | None) -> str:
    """두 축 → 하나의 상태. ★둘 중 나쁜 쪽이고, 미상은 통과가 아니다★

    하나라도 못 쟀으면 `unknown` 이다 — `degraded` 로 접으면 "재봤더니 샌다" 는
    없는 사실이 생기고, `ok` 로 접으면 "깨끗하다" 는 없는 사실이 생긴다.
    `run_evidence.AXIS_UNKNOWN` 이 통과가 아닌 것과 같은 규율이다.
    """
    if _unmeasured(window, WINDOW_UNMEASURED) or _unmeasured(vintage, VINTAGE_UNMEASURED):
        return STATE_UNKNOWN
    if window == WINDOW_BOUNDED and vintage == VINTAGE_AS_OF:
        return STATE_OK
    return STATE_DEGRADED


def fit_reason(window: str | None, vintage: str | None) -> str | None:
    """왜 통과가 아닌가 — ★어느 축이 문제인지 이름을 댄다★

    사유가 "누출 가능" 뿐이면 어디를 고쳐야 할지 알 수 없다. 두 축이 다 문제면
    둘 다 적는다.
    """
    bits = []
    w = WINDOW_UNMEASURED if window is None else window
    v = VINTAGE_UNMEASURED if vintage is None else vintage
    if w in _WINDOW_REASON:
        bits.append(_WINDOW_REASON[w])
    if v in _VINTAGE_REASON:
        bits.append(_VINTAGE_REASON[v])
    return " / ".join(bits) if bits else None


def fit_label(fit: EstimatorFit) -> dict:
    """적합 조건 → 상태와 사유. ★두 축을 **실은 채로** 판정한다★"""
    return {
        "state": fit_state(fit.window, fit.vintage),
        "reason": fit_reason(fit.window, fit.vintage),
        **fit.to_dict(),
    }
