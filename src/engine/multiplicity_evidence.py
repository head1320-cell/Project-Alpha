"""다중검정 레지스트리 — ★어디서 여러 가설을 동시에 보는가★ (AJ2)
==============================================================================
설계: `docs/plans` AJ · 어휘 `src/domain/multiplicity.py` · 롤업
`src/engine/run_evidence.rollup` (★`pit_evidence`·`decision_evidence`·
`estimator_evidence` 와 **같은 함수**★)

## 왜 이 모듈이 생겼나

채점표 §4 는 과최적화 진단을 *"PBO·deflated Sharpe·Bonferroni/FDR **없음**"* 이라고
적었다. 재보니 **없는 것보다 복잡한 상태**였다:

| 상태 | 자리 |
|---|---|
| 보정이 **있다** | `scripts/regime_control.py` 의 Hansen SPA 하나 |
| 가족 크기를 적고 ★경고만 한다★ | `factor_exposure` · `macro_sensitivity` · `auto_alpha` |
| 가족 크기조차 선언이 없고 ★결정에 닿는다★ | `robust_opt` 의 `|μ|/SE ≥ 2` |
| ★사전등록했는데 구현이 없다★ | 매크로 타깃 검증의 Benjamini–Hochberg |

없던 것은 보정 산수만이 아니라 **어휘·판정·롤업**이었다 — 네 방언이라 기계가 셀 수
없고, 화면이 비교할 수 없었다. AH2(`estimator_evidence`)와 같은 관용구다.

## ★시행 횟수를 세는 자리가 없다★ — 그래서 (실행 이력 전체의) PBO·DSR 을 만들지 않는다

BO O3(2026-09-28) — 캔버스 **갈래 비교**에서만은 사람이 나란히 둔 원본 + 갈래 수를 N 의 **하한**으로 쓴 DSR 을
`src/engine/deflated_sharpe.py` 가 보인다(그 전에 바꿔 보고 지운 설정은 세지 않아 보정이 약한 쪽으로 틀린다 — 응답이 그렇게 말한다).
이 레지스트리의 판정(자리별 보정 여부)은 바뀌지 않는다.

둘 다 *"몇 개를 시도했나"* 의 N 을 요구한다. 실측(2026-09-15): `backtest_runs`
31행이 **전부 테스트 픽스처**(`테스트전략`·`결과없는실행`·`귀인테스트`…),
`research_runs` 6행은 `mde`·`power`·`n_eff` 가 **전부 NULL**, `alpha_registry` 6행은
버전 레지스트리이지 시행 이력이 아니다. ★어느 것을 N 으로 써도 날조다.★
`auto_alpha.selection_bias_note` 가 이미 `sqrt(2·ln N)` — DSR 의 팽창항 — 을
계산하지만 그 N 은 그 호출이 방금 센 후보 수다.

## ★이 모듈이 주장하지 않는 것★

- **과최적화를 진단했다고 말하지 않는다.** 다중검정이 일어나는 자리를 세고 각
  자리가 보정하는지를 적을 뿐이다.
- **전부 찾았다고 말하지 않는다.** `EXCLUDED_SITES` 가 **안 잰 것을 사유와 함께**
  든다 — 그것이 없으면 이 레지스트리가 "다 봤다" 로 읽힌다.
- **보정하면 타당해진다고 말하지 않는다.** 가족을 잘못 세면 보정도 틀리고,
  보정 후 유의한 것이 경제적 가치라는 뜻은 더더욱 아니다(CLAUDE.md §2).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.domain.multiplicity import (
    CORRECTION_BH,
    CORRECTION_NONE,
    CORRECTION_SPA,
    CORRECTIONS,
    FAMILY_DECLARED,
    FAMILY_PREREGISTERED,
    FAMILY_SOURCES,
    FAMILY_UNKNOWN,
)
from src.engine.run_evidence import AXIS_DEGRADED, AXIS_OK, AXIS_UNKNOWN, rollup

_NOTE = (
    "이 판정은 **몇 개를 동시에 봤고 그것을 보정했나**만 말합니다. 데이터의 시점 "
    "정합은 `pit_evidence`, 추정 누출은 `estimator_evidence` 가 답하는 다른 "
    "질문입니다. ★실행 이력 전체에 대한 PBO·deflated Sharpe 는 여전히 없습니다★ — 둘 다 "
    "시행 횟수 N 을 요구하는데 이 저장소에는 실행 이력의 N 을 세는 자리가 없어, 지금 N 을 "
    "만들면 그것이 날조입니다. (캔버스 갈래 비교만은 남아 있는 갈래 수를 N 의 **하한**으로 "
    "쓴 DSR 을 따로 보입니다 — `deflated_sharpe`.)")

_REASON_UNKNOWN_FAMILY = (
    "몇 개를 동시에 봤는지 선언하지 않습니다 — 보정 여부를 판정할 수 없습니다. "
    "★미상은 '보정 불필요' 가 아닙니다.★")
_REASON_NOT_CORRECTED = (
    "가족 크기는 선언하지만 보정하지 않습니다 — ★경고는 보정이 아닙니다.★ "
    "개별 유의도를 동시에 본 개수와 함께 읽으십시오.")
_REASON_NOT_APPLIED = (
    "보정이 **이름으로만** 있습니다 — 사전등록되었을 뿐 값을 만든 적이 없습니다. "
    "★지키지 않은 등록은 등록이 아니라 등록했다는 주장입니다.★")


@dataclass(frozen=True)
class SearchSite:
    """여러 가설을 동시에 보는 한 자리. ★두 축이 따로 실린다★"""

    key: str
    site: str
    label: str
    family_source: str = FAMILY_UNKNOWN
    correction: str = CORRECTION_NONE
    #: 이 자리의 판정이 **비중·주문에 되먹임되나**. 리포트 전용과 구별된다.
    decision_touching: bool = False
    #: 보정이 **실제로 값을 만드나**. 사전등록만 된 보정은 `False` 다.
    applied: bool = True
    note: str = ""


# ═══════════════════════════════════════════════════════════════════════════
# 레지스트리 — 2026-09-15 실측
# ═══════════════════════════════════════════════════════════════════════════

SEARCH_SITES: tuple[SearchSite, ...] = (
    SearchSite(
        key="mu_resolvability",
        site="src/engine/robust_opt.py:mu_standard_errors",
        label="기대수익 해상도(자산별 |μ|/SE)",
        family_source=FAMILY_DECLARED, correction=CORRECTION_NONE,
        decision_touching=True,
        note=("자산마다 `|μ|/SE ≥ 2` 를 **동시에** 판정하고, 그 결과가 "
              "`uncertainty_scalar` 를 거쳐 리밸런싱 밴드(`1+u` 배)로 간다. "
              "임계 2.0 은 **단일검정** 양측 95% 라 자산 수가 늘수록 잡음이 "
              "`resolvable` 로 새어 들어온다. ★임계는 바꾸지 않았다★ — 배분 동작 "
              "변경은 별도 승인이고(CLAUDE.md §3), 이 작업은 관측·라벨만 한다."),
    ),
    SearchSite(
        key="factor_betas",
        site="src/engine/factor_exposure.py:asset_factor_betas",
        label="팩터 베타(자산 × 팩터)",
        family_source=FAMILY_DECLARED, correction=CORRECTION_BH,
        decision_touching=False,
        note=("팩터마다 t 를 내고 `multiple_testing.n_tested` 로 가족 크기를 이미 "
              "선언하고 있었다. ★경고만 하고 보정하지 않던 자리★ 이고, AJ3 에서 "
              "BH 블록이 붙었다 — 기존 `beta`·`t_stat`·`n_tested` 는 불변이다. "
              "리포트 전용이라 `constrained_solve` 에 닿지 않는다."),
    ),
    SearchSite(
        key="macro_betas",
        site="src/engine/valuation/macro_sensitivity.py:statistical_sensitivity",
        label="매크로 민감도(코어 계열)",
        family_source=FAMILY_DECLARED, correction=CORRECTION_BH,
        decision_touching=False,
        note=("코어 계열을 코드에 고정해 전부 보고하고 `n_tested` 를 적는다 — "
              "61계열을 훑어 큰 것만 내는 것을 막는 좋은 규율이지만, 고정된 "
              "가족에도 다중검정은 그대로 있다. AJ3 에서 BH 가 붙었다."),
    ),
    SearchSite(
        key="auto_alpha_search",
        site="src/engine/auto_alpha.py:selection_bias_note",
        label="알파 후보 탐색(선택편향)",
        family_source=FAMILY_DECLARED, correction=CORRECTION_NONE,
        decision_touching=False,
        note=("`sqrt(2·ln N)` 로 **팽창량을 보고**하지만 그것은 보정이 아니다 — "
              "임계를 올려 주지 않고, 스스로 '이 편향은 자동 보정되지 않습니다' "
              "라고 적는다. 스테이징 상한이 `experimental` 이라 자동 채택은 없다."),
    ),
    SearchSite(
        key="regime_spa",
        site="scripts/regime_control.py:_spa_pvalue",
        label="국면 팔 비교(Hansen SPA)",
        family_source=FAMILY_DECLARED, correction=CORRECTION_SPA,
        decision_touching=False,
        note=("★저장소에서 보정이 **실제로** 있는 유일한 자리★ — 여러 팔 중 최선이 "
              "벤치마크를 이기는가를 탐색 보정 후에 묻는다. 못 돌리면 사유와 함께 "
              "`None` 이다. 다만 `scripts/` 에 있어 `src/api` 에서 닿지 않는다."),
    ),
    SearchSite(
        key="macro_target_bh",
        site="docs/specs/2026-08-26-macro-target-validation.md:Benjamini",
        label="매크로 타깃 검증(가설 5 × 지평 4)",
        family_source=FAMILY_PREREGISTERED, correction=CORRECTION_BH,
        decision_touching=False, applied=False,
        note=("동결 표가 `가설 5 × 지평 4 = 20 → Benjamini–Hochberg` 를 "
              "**결과를 보기 전에** 못 박았다. ★그런데 그 검증 하네스가 코드에 "
              "없어 BH 가 보정할 p 값 집합이 한 번도 생산된 적이 없다.★ "
              "채점표는 이 사실을 적지 않고 'Bonferroni/FDR 없음' 이라고만 했다."),
    ),
)

#: ★안 잰 것을 적는다★ — 이것이 없으면 위 표가 "다 봤다" 로 읽힌다.
EXCLUDED_SITES: tuple[dict[str, str], ...] = (
    {"site": "src/engine/research_verdict.py:classify",
     "reason": "판정 **어휘**이지 검정이 아니다. 다중검정은 상류(SPA)가 처리하고 "
               "여기서는 그 결과를 다섯 분류로 옮길 뿐이다."},
    {"site": "src/engine/research_power.py:power_curve",
     "reason": "검정력·MDE 는 *'찾을 힘이 있었나'* 이고 다중검정은 *'여러 개를 봤나'* "
               "다 — 다른 축이다. 섞으면 `underpowered` 와 `보정 후 불유의` 가 "
               "구별되지 않는다."},
    {"site": "src/engine/valuation/screener_ranking.py",
     "reason": "스크리너는 가설 검정이 아니라 **필터**다. 유의도를 주장하지 않으므로 "
               "보정할 α 가 없다 — 대신 유동성 게이트와 3-레이어 구조가 다룬다."},
    {"site": "src/models/*",
     "reason": "학습기의 하이퍼파라미터 탐색은 다중검정의 한 형태이지만, 이 셋은 "
               "시간순 분할 안에서만 돌고 결과가 배분 결정에 되먹임되지 않는다. "
               "★안 쟀다는 뜻이지 문제없다는 뜻이 아니다.★"},
    {"site": "src/engine/backtest_attribution.py:factor_attribution",
     "reason": "끝난 실행에 대한 사후 귀인이라 결정에 되먹임되지 않는다 — "
               "`estimator_evidence.EXCLUDED_SITES` 가 같은 이유로 뺀 자리다."},
)

#: ★사전등록됐는데 구현이 없는 보정★ — 단순 부재보다 나쁘다.
#: 구현이 생기면 ★여기서 빼야 하고★, 트립와이어가 그때 그 사실을 알려준다.
UNIMPLEMENTED_PREREGISTRATIONS: tuple[dict[str, Any], ...] = (
    {
        "doc": "docs/specs/2026-08-26-macro-target-validation.md",
        "section": "§4 프로토콜 동결",
        "method": CORRECTION_BH,
        "family_size": 20,
        "evidence": "Benjamini–Hochberg",
        "reason": ("가설 5 × 지평 4 = 20칸을 전부 보고하고 BH 로 보정하기로 "
                   "**결과를 보기 전에** 동결했는데, 그 검증 하네스가 저장소에 "
                   "없다 — 보정할 p 값 집합이 한 번도 생산된 적이 없다. "
                   "★BH 산수는 AJ1 에서 생겼지만 이 검증에 배선되지 않았다★ — "
                   "패널과 자산군 스프레드 계열이 필요하고 그것이 Phase 8 본체다."),
    },
)


# ═══════════════════════════════════════════════════════════════════════════
# 축 · 롤업 — ★규칙은 `run_evidence.rollup` 한 곳에만 있다★
# ═══════════════════════════════════════════════════════════════════════════

def site_axis(site: SearchSite) -> dict[str, Any]:
    """한 자리 → 축. ★못 잰 것과 재서 나쁜 것을 가른다★

    · 가족 크기를 모른다 → `unknown`. **통과가 아니다.**
    · 가족은 아는데 보정이 없다 → `degraded`. **관측된 결함이다.**
    · 보정 이름은 있는데 적용된 적이 없다 → `degraded`. 사전등록은 적용이 아니다.
    · 보정이 실제로 값을 만든다 → `ok`.
    """
    common = {"site": site.site, "family_source": site.family_source,
              "correction": site.correction, "applied": site.applied,
              "decision_touching": site.decision_touching}
    if site.family_source == FAMILY_UNKNOWN:
        return {"state": AXIS_UNKNOWN, "reason": _REASON_UNKNOWN_FAMILY, **common}
    if site.correction == CORRECTION_NONE:
        return {"state": AXIS_DEGRADED, "reason": _REASON_NOT_CORRECTED, **common}
    if not site.applied:
        return {"state": AXIS_DEGRADED, "reason": _REASON_NOT_APPLIED, **common}
    return {"state": AXIS_OK, "reason": None, **common}


def rollup_sites(sites: tuple[SearchSite, ...]) -> dict[str, Any]:
    """자리들 → 하나의 판정. 축 이름·라벨은 레지스트리에서 나온다."""
    axes = {s.key: site_axis(s) for s in sites}
    labels = {s.key: s.label for s in sites}
    return rollup(axes, labels)


def registry_evidence() -> dict[str, Any]:
    """저장소 전체의 다중검정 상태 한 장.

    ★실행 하나에 대한 판정이 아니다★ — 이것은 *"이 저장소가 어디서 여러 가설을
    보고 그것을 보정하는가"* 라는 **구조**에 대한 관측이다.
    """
    return {
        **rollup_sites(SEARCH_SITES),
        "decision_touching": [s.key for s in SEARCH_SITES if s.decision_touching],
        "unimplemented_preregistrations": [dict(p) for p in
                                           UNIMPLEMENTED_PREREGISTRATIONS],
        "excluded": [dict(e) for e in EXCLUDED_SITES],
        "note": _NOTE,
    }


def _assert_vocabulary() -> None:
    """★어휘 밖의 값이 레지스트리에 들어오면 import 시점에 터진다★"""
    for s in SEARCH_SITES:
        if s.family_source not in FAMILY_SOURCES or s.correction not in CORRECTIONS:
            raise ValueError(f"레지스트리가 어휘 밖의 값을 쓴다: {s.site}")


_assert_vocabulary()
