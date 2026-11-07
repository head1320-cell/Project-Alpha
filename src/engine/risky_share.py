"""위험자산 비중 — ★비중은 관측, 분류는 선언★ (AD3)
==============================================================================
설계: `docs/plans/2026-09-12-ra-product-roadmap.md` P3 · 어휘: `domain/account_policy`
재사용: `src/data/exposure_taxonomy.asset_class_of()` — 미배정을 **조용히 빠뜨리지
        않는** 유일한 분류 경로다(`sector_groups_for` 는 빠뜨린다).

## 왜 둘로 가르나

"IRP 위험자산 70% 한도" 를 재려면 두 가지가 필요하다:

    ① 보유가 어느 자산군에 있는가   ← **데이터**. `exposure_taxonomy` 가 답한다.
    ② 어느 자산군이 '위험자산' 인가  ← ★규제 판단★. 이 저장소가 답할 수 없다.

②를 코드에 박으면 그 순간 이 모듈이 "금융당국은 이것을 위험자산으로 본다" 고
**주장**하게 된다. 그래서 ②는 **요청이 선언**하고, 선언이 없으면 비중을 계산하지
않는다 — 계산해 놓고 "참고용" 이라고 적는 것보다 아예 내지 않는 것이 정직하다.

## ★미배정분이 비중을 **구간**으로 만든다★

보유의 일부가 자산군 미배정이면(`exposure_taxonomy` 가 그것을 숨기지 않는다) 위험자산
비중은 점이 아니다:

    lo = 미배정을 **전부 안전자산**으로 봤을 때
    hi = 미배정을 **전부 위험자산**으로 봤을 때

★점추정 하나로 "70% 이하입니다" 라고 말하면 미배정분을 0 으로 접는 것★이고, 그것이
CLAUDE.md §4 의 `미상 ≠ 0` 위반이다. 구간이 한도를 걸치면 `judge_limit` 이
`UNDETERMINED` 를 낸다(AD1).
"""
from __future__ import annotations

from typing import Any

from src.data.exposure_taxonomy import AssetClass, asset_class_of

#: 위험자산 분류가 선언되지 않았을 때의 사유. ★고정 문구★
RISKY_UNDECLARED_REASON = (
    "위험자산 분류가 선언되지 않았습니다 — 어느 자산군이 위험자산인지는 "
    "규제 판단이라 이 저장소가 정할 수 없습니다. 요청이 선언해야 합니다."
)

_EMPTY_REASON = "보유가 비어 있거나 가중치 합이 0 입니다 — 비중을 잴 대상이 없습니다."

_LO_ASSUMES = "미배정 자산군을 전부 안전자산으로 가정한 하한입니다."
_HI_ASSUMES = "미배정 자산군을 전부 위험자산으로 가정한 상한입니다."


def _known_class_names() -> frozenset[str]:
    return frozenset(c.value for c in AssetClass)


def asset_class_mix(holdings: dict[str, float]) -> dict[str, Any]:
    """보유 → 자산군 구성(%). ★미배정을 별도 항목으로 낸다★

    `holdings` 는 티커 → 가중치(단위 무관, 내부에서 정규화). 음수는 다루지 않는다 —
    이 관문은 롱온리 계좌 제약을 위한 것이고, 숏이 섞인 보유의 '비중' 은 다른 질문이다.
    """
    positive = {t: float(w) for t, w in holdings.items() if float(w) > 0}
    total = sum(positive.values())
    if not positive or total <= 0:
        return {"available": False, "reason": _EMPTY_REASON,
                "by_class": {}, "unassigned_pct": None, "unassigned": [],
                "assigned_pct": None}

    groups, missing = asset_class_of(list(positive))

    by_class: dict[str, float] = {}
    assigned_weight = 0.0
    for ticker, weight in positive.items():
        klass = groups.get(ticker)
        if klass is None:
            continue
        by_class[klass] = by_class.get(klass, 0.0) + weight
        assigned_weight += weight

    scale = 100.0 / total
    return {
        "available": True,
        "reason": None,
        "by_class": {k: v * scale for k, v in sorted(by_class.items())},
        "assigned_pct": assigned_weight * scale,
        "unassigned_pct": (total - assigned_weight) * scale,
        # ★왜 배정되지 않았는지가 함께 온다★
        "unassigned": missing,
    }


def risky_share_interval(holdings: dict[str, float],
                         risky_classes: list[str] | None) -> dict[str, Any]:
    """보유 + **선언된** 위험자산 자산군 → 위험자산 비중 구간.

    `risky_classes=None` 은 "선언하지 않았다" 이고, `[]` 는 "위험자산이 없다고
    선언했다" 다. ★둘은 다른 사실이라 다르게 다룬다.★
    """
    mix = asset_class_mix(holdings)
    base = {
        "available": False, "interval": None, "unknown_classes": [],
        "mix": mix, "unassigned_pct": mix.get("unassigned_pct"),
    }

    if risky_classes is None:
        return {**base, "reason": RISKY_UNDECLARED_REASON}
    if not mix["available"]:
        return {**base, "reason": mix["reason"]}

    known = _known_class_names()
    declared = [str(c).strip().upper() for c in risky_classes]
    unknown = sorted({c for c in declared if c not in known})

    risky_pct = sum(pct for name, pct in mix["by_class"].items() if name in declared)
    unassigned = float(mix["unassigned_pct"])

    reason = None
    if unknown:
        # ★조용히 무시하지 않는다★ — 오타 하나가 곧 잘못된 판정이다.
        reason = (f"선언에 알 수 없는 자산군이 있습니다: {unknown} — "
                  f"허용: {sorted(known)}. 해당 이름은 비중에 반영되지 않았습니다.")

    return {
        "available": True,
        "reason": reason,
        "unknown_classes": unknown,
        "declared_risky_classes": sorted(set(declared)),
        "unassigned_pct": unassigned,
        "interval": {
            "lo": risky_pct,
            "hi": risky_pct + unassigned,
            "lo_assumes": _LO_ASSUMES,
            "hi_assumes": _HI_ASSUMES,
        },
        "mix": mix,
    }
