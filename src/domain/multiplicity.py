"""다중검정 — ★경고는 보정이 아니다★ (AJ1)
==============================================================================
설계: `docs/plans` AJ · 레지스트리 `src/engine/multiplicity_evidence.py` ·
소비자 `factor_exposure`·`macro_sensitivity`·`robust_opt`·`auto_alpha`

## 왜 이 모듈이 생겼나

채점표 §4 는 과최적화 진단을 *"PBO·deflated Sharpe·Bonferroni/FDR **없음**"* 이라고
적었다. ★재보니 그 문장이 절반만 말한다.★

1. **경고는 있고 보정이 없었다.** `factor_exposure`·`macro_sensitivity` 는 몇 개를
   동시에 봤는지(`n_tested`)를 적고 *"보정 없이 유의하다고 말하는 것은 거짓"* 이라고
   **스스로 경고**하면서 보정하지 않았다.
2. **깨진 사전등록이 있었다.** `docs/specs/2026-08-26-macro-target-validation.md`
   의 동결 표가 `가설 5 × 지평 4 = 20 → Benjamini–Hochberg` 를 사전등록했는데
   ★BH 는 저장소 어디에도 없었다★. 지키지 않은 등록은 등록이 아니라 등록했다는
   주장이다.
3. **보정이 필요한 결정 경로가 있었다.** `robust_opt._RESOLVABLE_T = 2.0` 이
   자산마다 `|μ|/SE ≥ 2` 를 **동시에** 판정하고 그 결과가 리밸런싱 밴드로 간다.

## ★두 축을 섞지 않는다★

    가족 크기를 어디서 아는가  ⟂  어떤 보정을 실제로 적용했는가

둘은 독립이다. 가족 크기를 **알면서** 보정을 안 할 수 있고(위 1번이 정확히 그것),
보정 이름을 적어 놓고 **가족 크기를 모를 수도** 있다(위 2번). 한 축으로 접으면
그 둘이 리포트에서 구별되지 않는다 — Z 의 `kind ⟂ data_real`, AA 의
`trigger ⟂ reason`, AG 의 `signal_lag ⟂ fill_type`, AH 의 `window ⟂ vintage`,
AI 의 `실행 모드 ⟂ 잔고 출처` 와 같은 규율이다.

## ★가족 크기를 모르면 보정을 만들지 않는다★

미상을 `m=1` 로 접으면 결과가 **보정 없음과 수치적으로 같아진다** — 즉 조용히
*"보정이 불필요하다"* 고 주장하게 된다. 미상은 주장이 아니다. `None` + 사유다
(CLAUDE.md §4 ★침묵 폴백 금지★).

## ★이 모듈이 주장하지 않는 것★

- **과최적화를 진단한다고 말하지 않는다.** 여기 있는 것은 산수이고, 무엇이
  가족인지는 호출부가 선언해야 한다 — ★가족을 잘못 세면 보정도 틀린다.★
- **보정 후 유의한 것이 투자 우위라고 말하지 않는다.** CLAUDE.md §2 의 네 질문 중
  ③(예측 스킬)의 통계적 타당성만 다루고 ④(경제적 가치)는 건드리지 않는다.
- **PBO·deflated Sharpe 를 만들지 않는다.** 둘 다 **시행 횟수 N** 을 요구하는데
  이 저장소에는 그것을 세는 자리가 없다(`backtest_runs` 31행이 전부 테스트 픽스처,
  `research_runs` 6행은 검정력이 전부 NULL). ★없는 N 으로 낸 DSR 은 숫자 모양의
  날조다.★ `expected_max_z` 가 그 팽창항을 계산하긴 하지만, 그것은 호출부가 센
  후보 수에 대한 경고이지 실행 이력에 대한 보정이 아니다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any

# ── 축 ①  가족 크기를 어디서 아는가 ───────────────────────────────────────
#: 문서가 **결과를 보기 전에** 못 박은 수. ★사후에 바꾸면 사전등록이 아니다★
FAMILY_PREREGISTERED = "preregistered"
#: 실행 시점에 코드가 실제로 센 수(`n_tested`·자산 수 등).
FAMILY_DECLARED = "declared"
#: ★세는 자리가 없다★ — 통과가 아니고 `1` 도 아니다.
FAMILY_UNKNOWN = "unknown"

FAMILY_SOURCES = (FAMILY_PREREGISTERED, FAMILY_DECLARED, FAMILY_UNKNOWN)

# ── 축 ②  어떤 보정을 실제로 적용했는가 ───────────────────────────────────
CORRECTION_BH = "benjamini_hochberg"
CORRECTION_BONFERRONI = "bonferroni"
#: ★이미 있는 보정을 새 이름으로 덮지 않는다★ — `scripts/regime_control.py` 의
#: Hansen SPA 는 여러 팔 중 최선을 탐색 보정해 판정한다. 어휘에 이름만 올린다.
CORRECTION_SPA = "hansen_spa"
#: 보정을 **하지 않았다**. ★경고만 한 것은 여기다.★
CORRECTION_NONE = "none"

CORRECTIONS = (CORRECTION_BH, CORRECTION_BONFERRONI, CORRECTION_SPA,
               CORRECTION_NONE)

_UNKNOWN_FAMILY_REASON = (
    "가족 크기를 모릅니다 — 몇 개를 동시에 봤는지 세는 자리가 없어 보정을 "
    "계산하지 않았습니다. ★미상을 m=1 로 접으면 '보정이 불필요하다' 고 조용히 "
    "주장하게 됩니다.★")
_NO_CORRECTION_REASON = (
    "가족 크기는 알지만 보정을 적용하지 않았습니다 — 개별 유의도를 그 사실과 "
    "함께 읽으십시오.")

#: t → p 는 자유도를 무시한 정규 근사다. ★정확하다고 말하지 않는다★
_P_METHOD = "정규분포 양측 근사(자유도 무시) — 표본이 작으면 p 가 낙관적입니다"

_NORMAL = NormalDist()


@dataclass(frozen=True)
class Family:
    """동시에 본 검정들의 **가족**. ★`None` 은 미상이지 1 이 아니다★"""

    size: int | None = None
    source: str = FAMILY_UNKNOWN
    label: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict:
        return {"family_size": self.size, "family_source": self.source,
                "family_label": self.label}


def _usable_size(family: Family) -> int | None:
    """가족 크기가 보정에 쓸 수 있는가. ★0 이나 음수는 가족이 아니다★"""
    size = family.size
    if size is None or isinstance(size, bool) or not isinstance(size, int):
        return None
    return size if size >= 1 else None


# ── 보정 산수 (순수) ──────────────────────────────────────────────────────
def bonferroni_alpha(alpha: float, m: int | None) -> float | None:
    """가족 전체 오류율 `alpha` 를 `m` 으로 **나눈다**. ★곱하지 않는다★

    `m` 을 모르면 `None` — 1 로 채우면 보정 없음과 같아진다.
    """
    if m is None or isinstance(m, bool) or not isinstance(m, int) or m < 1:
        return None
    return float(alpha) / float(m)


def bh_reject(p_values: list[float | None], alpha: float = 0.05) -> dict[str, Any]:
    """Benjamini–Hochberg 절차 — FDR 을 `alpha` 로 통제한다.

    ★핵심은 '최대 k 아래를 **전부** 기각' 이다.★ 개별로 `p ≤ k·α/m` 을 비교하면
    BH 가 아니라 그냥 눈금이 다른 개별검정이 된다 — 정렬 3위가 임계를 넘으면
    1·2위는 자기 임계를 못 넘었어도 함께 기각된다.

    Args:
        p_values: 가족의 p 값들. ★`None` 은 가족에서 빠진다★ — 1.0 으로 채우면
            *"재보니 전혀 유의하지 않았다"* 는 **관측**이 되어 버린다.

    Returns:
        `n`(쓸 수 있었던 개수) · `n_rejected` · `rejected`(입력과 같은 순서,
        `None` 자리는 `None`) · `critical` · `alpha` · `reason`.
    """
    usable = [(i, float(p)) for i, p in enumerate(p_values)
              if p is not None and not isinstance(p, bool)
              and isinstance(p, (int, float)) and math.isfinite(float(p))]
    n_dropped = len(p_values) - len(usable)
    m = len(usable)
    if m == 0:
        return {"n": 0, "n_rejected": None, "rejected": [None] * len(p_values),
                "critical": None, "alpha": float(alpha), "n_dropped": n_dropped,
                "reason": ("p 값을 하나도 내지 못해 보정할 가족이 없습니다 — "
                           "★'0개 기각' 이 아니라 미상입니다.★")}

    order = sorted(usable, key=lambda pair: pair[1])
    critical = [(k + 1) * float(alpha) / m for k in range(m)]
    max_k = 0
    for k in range(m, 0, -1):
        if order[k - 1][1] <= critical[k - 1]:
            max_k = k
            break

    rejected_idx = {i for i, _ in order[:max_k]}
    return {
        "n": m,
        "n_rejected": max_k,
        "rejected": [(None if p is None else (i in rejected_idx))
                     for i, p in enumerate(p_values)],
        "critical": [round(c, 6) for c in critical],
        "alpha": float(alpha),
        "n_dropped": n_dropped,
        "reason": (None if not n_dropped else
                   f"p 를 내지 못한 {n_dropped}개는 가족에서 뺐습니다 — "
                   f"1.0 으로 채우면 미상이 '불유의 관측' 이 됩니다"),
    }


def expected_max_z(n_trials: int | None) -> float:
    """N 개 표준정규 최댓값의 기대 `≈ sqrt(2·ln N)`. ★N≤1 이면 0★

    ★이것은 deflated Sharpe 의 팽창항 그 자체다★ — 그런데 DSR 을 만들려면 N 이
    **실행 이력에서** 나와야 하고, 이 저장소에는 그것을 세는 자리가 없다. 여기서
    받는 N 은 호출부가 한 번에 센 후보 수일 뿐이다(`auto_alpha`).
    """
    if n_trials is None or isinstance(n_trials, bool):
        return 0.0
    n = int(n_trials)
    return math.sqrt(2 * math.log(n)) if n > 1 else 0.0


def two_sided_p_from_t(t_stat: float | None) -> dict[str, Any]:
    """t → 양측 p. ★자유도를 무시한 정규 근사이고, 그 사실을 함께 낸다★

    `None` 이면 `p` 도 `None` — 1.0 으로 채우면 *"재봤더니 유의하지 않다"* 가 된다.
    """
    if (t_stat is None or isinstance(t_stat, bool)
            or not isinstance(t_stat, (int, float))
            or not math.isfinite(float(t_stat))):
        return {"p": None, "approximation": True, "method": _P_METHOD,
                "reason": "t 값이 없어 p 를 내지 않았습니다 — 미상은 p=1.0 이 아닙니다"}
    p = 2.0 * (1.0 - _NORMAL.cdf(abs(float(t_stat))))
    return {"p": min(max(p, 0.0), 1.0), "approximation": True,
            "method": _P_METHOD, "reason": None}


def corrected_t_threshold(alpha: float, m: int | None) -> float | None:
    """Bonferroni 하의 **양측 임계 t**(정규 근사). 가족을 모르면 `None`.

    ★이 값을 어디에도 적용하지 않는다★ — 현재 임계가 얼마나 느슨한지를 보고하기
    위한 수치다(`robust_opt` 의 `_RESOLVABLE_T=2.0` 은 그대로 둔다).
    """
    a = bonferroni_alpha(alpha, m)
    if a is None:
        return None
    return float(_NORMAL.inv_cdf(1.0 - a / 2.0))


# ── 라벨 ──────────────────────────────────────────────────────────────────
def multiplicity_label(family: Family, correction: str, *,
                       alpha: float = 0.05,
                       detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """가족 + 보정 → 리포트에 싣는 한 블록. ★두 축이 **따로** 실린다★

    `applied` 는 *"보정이 실제로 값을 만들었나"* 이지 *"보정 이름이 적혔나"* 가
    아니다 — 사전등록만 되고 구현이 없는 BH 는 `applied: False` 다.
    """
    size = _usable_size(family)
    base: dict[str, Any] = {**family.to_dict(), "alpha": float(alpha),
                            **(detail or {})}

    if size is None:
        return {**base, "correction": None, "applied": False,
                "corrected_alpha": None,
                "reason": family.reason or _UNKNOWN_FAMILY_REASON}

    if correction == CORRECTION_NONE:
        return {**base, "correction": CORRECTION_NONE, "applied": False,
                "corrected_alpha": None,
                "reason": family.reason or _NO_CORRECTION_REASON}

    out = {**base, "correction": correction, "applied": True,
           "reason": family.reason}
    if correction == CORRECTION_BONFERRONI:
        out["corrected_alpha"] = bonferroni_alpha(alpha, size)
    elif correction == CORRECTION_BH:
        # ★BH 에는 단일 임계가 없다★ — 눈금이 `k·α/m` 으로 올라간다. 가장 엄격한
        # 첫 칸(k=1)만 적고, 나머지는 `bh_reject` 의 `critical` 이 낸다.
        out["corrected_alpha"] = None
        out["smallest_critical"] = bonferroni_alpha(alpha, size)
    else:
        out["corrected_alpha"] = None
    return out


def bh_block(t_by_name: dict[str, float | None], *, family_size: int | None,
             family_source: str, alpha: float = 0.05,
             scope: str | None = None) -> dict[str, Any]:
    """t 값 가족 → 리포트에 싣는 **BH 블록**. ★두 축 + 절차 결과를 한 곳에★

    ★`family_size` 와 `n` 은 다른 수다★ — 앞은 *"몇 개를 보려 했나"*, 뒤는
    *"몇 개가 실제로 p 를 냈나"* 다. t 를 못 낸 자리는 가족에서 빠지고
    (`n_dropped`) 그 사실이 `reason` 에 남는다 — `p=1.0` 으로 채우면 미상이
    *"재봤더니 불유의"* 라는 **관측**으로 둔갑한다.
    """
    names = list(t_by_name)
    ps = [two_sided_p_from_t(t)["p"] for t in t_by_name.values()]
    bh = bh_reject(ps, alpha=alpha)
    label = multiplicity_label(
        Family(size=family_size, source=family_source, label=scope),
        CORRECTION_BH, alpha=alpha)
    return {
        **label,
        "scope": scope,
        "n": bh["n"], "n_rejected": bh["n_rejected"],
        "n_dropped": bh["n_dropped"], "critical": bh["critical"],
        "p_values": {n: (None if p is None else round(p, 6))
                     for n, p in zip(names, ps)},
        "rejected": {n: r for n, r in zip(names, bh["rejected"])},
        "approximation": True, "p_method": _P_METHOD,
        "reason": bh["reason"] or label.get("reason"),
    }
