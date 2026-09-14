"""추정 누출 증거 — ★여섯 방언을 한 어휘로★ (AH2)
==============================================================================
설계: `docs/plans` AH · 어휘 `src/domain/estimator_fit.py` · 롤업
`src/engine/run_evidence.rollup` (★`pit_evidence`·`decision_evidence` 와 **같은 함수**★)

## 왜 이 모듈이 생겼나

채점표 §4 는 `GARCH`·`DCC`·`MarkovRegression`·`GaussianMixture`·`DynamicFactor`·
`genpareto`·`LedoitWolf` 가 전체표본 적합이라 배분이 오염된다고 적어 뒀다.
★재보니 그 일곱 중 어느 것도 백테스트·배분 **결정**에 닿지 않는다★ — 전부 리포트
루트이고, `kis_backtest_engine` 의 engine-layer import 는 `quant_metrics`·
`fill_price`·`pit_store`·`execution_assumption`·`price_quality` 뿐이다.
그 사실은 `EXCLUDED_SITES` 에 **사유와 함께** 적어 둔다.

결정에 닿는 누출은 `LEAKAGE_SITES` 의 여섯이고, ★그중 넷은 이미 자기 누출을 알고
산문으로 적어 뒀다★(`path_source:"recomputed"` · `revision_bias` · `as_of_honored`).
없는 것은 누출 자체가 아니라 **어휘·판정·롤업·기록**이었다 — 여섯 방언이라 기계가
셀 수 없고, 화면이 비교할 수 없고, 실행 기록에 남지 않는다.

## ★`pit_evidence` 와 섞지 않는다★

저것은 *"데이터가 시점 정합인가"*(빈티지·공표일)이고 이것은 *"추정이 어느 창·어느
빈티지 위에 섰나"* 다. 다른 질문이라 다른 블록이다. 다만 **판정 규칙은 공유**한다 —
`rollup()` 이 한 곳에만 있어야 화면에 따라 다른 판정이 나오지 않는다.

## ★이 모듈이 주장하지 않는 것★

- **누출을 고쳤다고 말하지 않는다.** 여섯은 그대로 있고, 바뀌는 것은 그 사실이
  기계가 읽을 수 있게 보이는가뿐이다.
- **누출을 다 찾았다고 말하지 않는다.** 배분·백테스트에 닿는 자리를 훑었고 리포트
  전용은 **의도적으로 안 쟀다** — `EXCLUDED_SITES` 가 그 사실을 적는다.
"""
from __future__ import annotations

from typing import Any

from src.domain.estimator_fit import (
    VINTAGE_AS_OF,
    VINTAGE_CURRENT,
    WINDOW_BOUNDED,
    WINDOW_TRAILING,
    EstimatorFit,
    fit_label,
)
from src.engine.run_evidence import AXIS_UNKNOWN, rollup

#: 축 이름 → 사람이 읽는 이름. ★`rollup` 이 하드 인덱싱하므로 빠지면 KeyError★
ESTIMATOR_AXIS_LABELS = {
    "covariance": "공분산 추정",
    "regime_path": "국면 경로",
    "proxies": "대리계열 선택",
}

#: ★공분산은 언제나 축이다★ — 어떤 배분이든 Σ 를 쓴다. 값이 없으면 `unknown` 으로
#: **남는다**. 빠지면 "못 쟀다" 가 "문제없다" 가 된다.
ESTIMATOR_REQUIRED_AXES = ("covariance",)

#: ★`regime_path`·`proxies` 는 해당할 때만 축이다★ 무조건부 배분은 국면 경로를
#: 쓰지 않고, 귀인이 아닌 표면은 대리계열을 쓰지 않는다. 축을 **생략**하면 해당
#: 없음이고, `None` 을 명시하면 "물었는데 못 쟀다" 는 미상이다 — 다른 사실이다.
OPTIONAL_AXES = ("regime_path", "proxies")

_NO_MEASUREMENT = "측정값이 없습니다 — 이 실행에서 재지 못했습니다."

_NOTE = ("이 판정은 **추정이 어느 창·어느 빈티지 위에 섰나**만 말합니다. "
         "데이터의 시점 정합(공표일·빈티지)은 별개 축이고 `pit_evidence` 가 답합니다. "
         "`bounded` 라도 절단이 월 단위 근사일 수 있습니다.")


# ═══════════════════════════════════════════════════════════════════════════
# 레지스트리 — ★결정에 닿는 자리★ (2026-09-14 실측)
# ═══════════════════════════════════════════════════════════════════════════

#: 여기 적힌 것이 **배분·백테스트 결정에 닿는** 추정 자리다. 각 항목의 `window`·
#: `vintage` 는 그 자리의 **기본 성질**이고, 한 실행이 실제로 무엇을 탔는지는
#: `estimator_evidence()` 가 실행 메타에서 읽는다 — 둘은 다른 질문이다.
LEAKAGE_SITES: tuple[EstimatorFit, ...] = (
    EstimatorFit(
        site="src/api/allocation_pipeline.py:_regime_path_for",
        window=WINDOW_TRAILING, vintage=VINTAGE_CURRENT, consumer="allocation",
        note=("국면 경로를 현재 데이터로 다시 계산한다(`collect_all(use_cache=True)` "
              "+ 최근 60개월). 이미 `path_source:\"recomputed\"` 와 `path_note` 로 "
              "고백하고 있고, `mode==\"backtest\"` 는 아예 막혀 있다."),
    ),
    EstimatorFit(
        site="src/engine/regime_axes.py:zscore_at",
        window=WINDOW_TRAILING, vintage=VINTAGE_CURRENT, consumer="allocation",
        note=("z 창은 후행 60개월이라 인과적으로 깨끗하지만, 매크로 계열 자체가 "
              "현재 빈티지다. 모듈이 `revision_bias`·`path_uses_vintage`·"
              "`blocked_permanently` 로 이미 그렇게 말하고 있다."),
    ),
    EstimatorFit(
        site="src/engine/conditional_market.py:_shrunk_cov",
        window=WINDOW_BOUNDED, vintage=VINTAGE_AS_OF, consumer="allocation",
        note=("워크포워드에서는 `R_win = R[lo:t]` 로 잘리고 국면 경로도 "
              "`_truncated_points` 로 잘린다. `/analyze` 경로에서는 수익률은 "
              "`as_of` 로 잘리지만 국면 경로가 안 잘린다 — 그 사실은 위 "
              "`_regime_path_for` 축이 든다."),
    ),
    EstimatorFit(
        site="src/engine/risk_allocations.py:_cov",
        window=WINDOW_TRAILING, vintage=VINTAGE_AS_OF, consumer="allocation",
        note=("Ledoit-Wolf 를 후행 252일에 적합한다. `etf_prices.as_of()` 컨텍스트 "
              "안에서 부르면 잘리지만(전략 프로파일 백테스트가 그렇게 한다), "
              "라이브 배분은 컨텍스트 없이 부른다 — 라이브에선 그것이 옳다. "
              "★절단은 월×21봉 근사이지 날짜 정확이 아니다★"),
    ),
    EstimatorFit(
        site="src/engine/reverse_stress.py:factor_covariance",
        window=WINDOW_BOUNDED, vintage=VINTAGE_AS_OF, consumer="allocation",
        note=("상류 `resolve_proxies(as_of=)` 로 창은 잘리지만, 수축 **전** 표준화 "
              "`Z = (X - X.mean(axis=0)) / sd_raw` 가 전체 공통월 표본이다. "
              "★이 자리는 지금까지 아무 선언도 없었다★"),
    ),
    EstimatorFit(
        site="src/api/backtest_run_routes.py:_proxy_selection",
        window=WINDOW_TRAILING, vintage=VINTAGE_AS_OF, consumer="backtest",
        note=("계수에는 룩어헤드가 없지만 **어느 대리계열을 쓸지**를 오늘까지의 "
              "관측 수로 고른다. `truncate_to_window` 기본값이 `False` 이고, "
              "라우트가 이미 그 사실을 `reason` 에 길게 적어 두었다."),
    ),
)

#: ★안 잰 것을 적는다★ — 채점표가 이름을 댄 일곱 계열은 전부 여기에 있다.
#: 이것이 없으면 축이 "다 봤다" 로 읽히고, 그것이 거짓말이 된다.
EXCLUDED_SITES: tuple[dict[str, str], ...] = (
    {"site": "src/models/garch.py:GARCH11.fit", "family": "GARCH",
     "reason": "전체표본 적합이 맞지만 `/garch-compare` 리포트 전용이다 — "
               "엔진·배분에서 도달하는 import 가 없다."},
    {"site": "src/models/dcc_garch_wwr.py:DCCGARCH.fit", "family": "DCC-GARCH",
     "reason": "무조건부 상관 목표 `Q̄` 가 전체표본이지만 `/dcc-garch` 크레딧 "
               "리포트 전용이다."},
    {"site": "src/engine/regime_ensemble.py:_markov_probs", "family": "MarkovRegression",
     "reason": "평활 확률이 양방향이라 전체표본이지만, 모듈이 `USAGE_NOTE` 로 "
               "★배분에 쓰이지 않는다★ 고 선언하고 engine importer 가 0 이다."},
    {"site": "src/engine/regime_ensemble.py:_cluster_probs", "family": "GaussianMixture",
     "reason": "마지막 점을 포함해 적합한 뒤 그 점을 채점하지만, 같은 모듈이라 "
               "진단 전용이다."},
    {"site": "src/engine/macro_models/tsfm_latent.py:run", "family": "DynamicFactor",
     "reason": "표준화와 부호 고정이 전체표본이지만 매크로 스튜디오 리포트 전용이다."},
    {"site": "src/engine/macro_models/pinn_tail.py:run", "family": "genpareto",
     "reason": "임계값을 전체표본 90분위로 고르지만 매크로 스튜디오 리포트 전용이고, "
               "저장소 문서가 이미 '미연결' 로 기록하고 있다."},
    {"site": "src/engine/backtest_attribution.py:factor_attribution", "family": "OLS/VIF",
     "reason": "끝난 실행에 대한 사후 귀인이라 결정에 되먹임되지 않는다. 대리계열 "
               "**선택**의 누출만 `_proxy_selection` 축으로 센다."},
)


# ═══════════════════════════════════════════════════════════════════════════
# 롤업
# ═══════════════════════════════════════════════════════════════════════════

def _axis(fit: EstimatorFit | None) -> dict[str, Any]:
    """적합 조건 → 축. ★`None` 은 '물었는데 못 쟀다' 이지 '해당 없음' 이 아니다★"""
    if fit is None:
        return {"state": AXIS_UNKNOWN, "reason": _NO_MEASUREMENT,
                "window": None, "vintage": None}
    label = fit_label(fit)
    return {"state": label["state"], "reason": label["reason"],
            "window": label["window"], "vintage": label["vintage"],
            "site": label["site"]}


_ABSENT = object()


def estimator_evidence(*, covariance: EstimatorFit | None = None,
                       regime_path: EstimatorFit | None | Any = _ABSENT,
                       proxies: EstimatorFit | None | Any = _ABSENT) -> dict[str, Any]:
    """축들 → 하나의 판정. ★규칙은 `run_evidence.rollup` 한 곳에만 있다★

    선택 축은 **생략**하면 해당 없음(축에서 빠진다)이고, `None` 을 명시하면
    "물었는데 못 쟀다" 는 미상이다 — `decision_evidence` 와 같은 규율이다.
    """
    axes: dict[str, dict | None] = {"covariance": _axis(covariance)}
    if regime_path is not _ABSENT:
        axes["regime_path"] = _axis(regime_path)
    if proxies is not _ABSENT:
        axes["proxies"] = _axis(proxies)
    return {**rollup(axes, ESTIMATOR_AXIS_LABELS), "note": _NOTE}
