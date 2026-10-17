"""뷰 행(P) 의 단일 출처 — ★같은 규칙이 세 곳에 손으로 구현돼 있었다★
==============================================================================
계획: `docs/specs/2026-08-25-t3-transmission-study.md` §5·§6.4

## 왜 이 모듈이 생겼나

T3 연구가 자산군 **상대** 뷰를 가장 방어 가능한 전달 형태로 지목했는데, 현행 뷰
스키마는 그것을 **표현할 수 없었다**:

    row[idx[a]] = 1.0 / len(assets)        # 양수 · 등가중
    d = 1.0 if direction >= 0 else -1.0    # 방향은 스칼라

즉 `P` 행이 언제나 양수 등가중이라 `(+EQ, −FI)` 같은 스프레드를 못 만든다. 그리고
그 규칙이 **세 곳에 복사**돼 있었다:

| 위치 | 소비자 |
|---|---|
| `allocation_studio.build_user_views` | BL 사용자 뷰 → `P/Q/Ω` |
| `entropy_views._pickers` | EP 부등식 제약 |
| `risk_allocations` (매크로 틸트) | ★뷰 스키마가 아니라 틸트 맵★ |

셋이 주석으로 *"같은 규칙"* 이라 선언하고 손으로 세 번 구현돼 있었다. 부호를
넣으면서 둘만 고치면 같은 뷰가 BL 과 EP 에서 **다른 P 행**이 되고, 그 차이는 두
응답을 나란히 놓기 전에는 보이지 않는다.

★세 번째는 계약이 다르다★ `risk_allocations` 는 사용자 뷰가 아니라 매크로 틸트
맵에서 행을 만들고 Q 를 직접 정한다. 그래서 공유하는 것은 `build_view_rows` 가
아니라 **행 원시함수(`row_from_spec`)** 다 — 계약을 억지로 합치지 않되 행을 만드는
규칙은 갈라지지 않게 한다.

## 계약

| 입력 | P 행 | 용도 |
|---|---|---|
| `assets: [a, b]` | `[.5, .5, 0, …]` 양수 등가중 | 절대 뷰 (T3-A, **현행 기본**) |
| `weights: {a: +1/3, …, d: −1/3}` | 부호 그대로 | 상대·팩터 뷰 (T3-B/C) |

- **동시 지정 금지** — 어느 쪽이 이기는지 추측하게 두지 않는다.
- ★**재정규화하지 않는다**★ `Ω` 의 base 가 `diag(P τΣ Pᵀ)` 라 행 노름에 비례해 함께
  커지므로 자기정합적이다. 대신 `magnitude_pct` 는 **그 행의 단위**다 —
  스프레드 뷰의 3% 는 "EQ−FI 스프레드가 연 3%" 이지 "각 자산이 3%" 가 아니다.
- ★`direction` 은 **Q 에만** 곱한다★ 부호를 가중치에 이미 넣었다면 `direction=1` 로
  둔다. 양쪽에 넣으면 **상쇄된다**.
- 유니버스에 없는 자산은 버리되 `dropped_assets` 에 남긴다.
- `Σ|w| ≤ 1e-12` 또는 크기 0 이면 **스킵 + 사유** — 조용히 0 행을 넣지 않는다.

★EP 는 이미 준비돼 있었다★ `ep_posterior_mu` 는 `Rm @ row` 라는 선형 범함수만 쓰고
양수 가정이 없다. 막고 있던 것은 **행 생성기**뿐이었다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: `Σ|w|` 가 이보다 작으면 뷰가 아무것도 주장하지 않는 것이다.
GROSS_MIN = 1e-12

KIND_ABSOLUTE = "absolute"
KIND_WEIGHTED = "weighted"


@dataclass(frozen=True)
class ViewRow:
    """뷰 하나의 `P` 행 + Q 재료.

    frozen 인 이유는 `RegimeProbabilities` 와 같다 — 소비자가 행이나 방향을 나중에
    고쳐 계약을 우회하지 못하게 한다.
    """

    row: np.ndarray
    direction: float
    magnitude: float
    label: str
    kind: str
    dropped_assets: list[str] = field(default_factory=list)

    def as_tuple(self) -> tuple[np.ndarray, float, float, str]:
        """구 소비자 호환 — `(row, direction, magnitude, label)`."""
        return self.row, self.direction, self.magnitude, self.label


def row_from_spec(*, assets: list[str] | None, weights: dict[str, float] | None,
                  names: list[str]) -> tuple[np.ndarray | None, str, list[str]]:
    """★행 원시함수 — 세 소비자가 공유하는 유일한 규칙★

    Returns:
        `(row, kind, dropped)`. 쓸 수 있는 자산이 없으면 `row` 가 `None`.
    """
    idx = {t: i for i, t in enumerate(names)}
    row = np.zeros(len(names), dtype=float)
    dropped: list[str] = []

    if weights:
        for a, w in weights.items():
            if a in idx:
                row[idx[a]] += float(w)
            else:
                dropped.append(str(a))
        if float(np.abs(row).sum()) <= GROSS_MIN:
            return None, KIND_WEIGHTED, dropped
        return row, KIND_WEIGHTED, dropped

    picked = []
    for a in assets or []:
        (picked if a in idx else dropped).append(str(a))
    if not picked:
        return None, KIND_ABSOLUTE, dropped
    for a in picked:
        row[idx[a]] = 1.0 / len(picked)
    return row, KIND_ABSOLUTE, dropped


def build_view_rows(views: list[dict] | None, names: list[str]
                    ) -> tuple[list[ViewRow], list[dict[str, Any]]]:
    """뷰 목록 → `(ViewRow 목록, 스킵 사유)`. ★BL·EP 의 단일 출처★

    스킵은 조용하지 않다 — 어떤 뷰가 왜 빠졌는지 호출자가 응답에 실을 수 있게
    사유를 함께 돌려준다(기존 `build_user_views`·`_pickers` 규약 그대로).
    """
    out: list[ViewRow] = []
    skipped: list[dict[str, Any]] = []

    for v in views or []:
        assets = v.get("assets") or None
        weights = v.get("weights") or None
        if assets and weights:
            skipped.append({"view": v, "reason": (
                "`assets` 와 `weights` 를 **동시에** 지정했습니다 — 어느 쪽이 P 행을 "
                "정하는지 모호합니다. 부호 있는 뷰는 `weights` 만 쓰십시오.")})
            continue

        mag = abs(float(v.get("magnitude_pct") or 0.0)) / 100.0
        if mag == 0.0:
            skipped.append({"view": v, "reason": "크기가 0 인 뷰는 아무것도 주장하지 않습니다"})
            continue

        row, kind, dropped = row_from_spec(assets=assets, weights=weights,
                                           names=names)
        if row is None:
            skipped.append({"view": v, "reason": (
                "가중치 합(|w|)이 0 이거나 유니버스에 있는 대상 자산이 없습니다"
                + (f" (제외: {', '.join(dropped)})" if dropped else ""))})
            continue

        d = 1.0 if float(v.get("direction", 1)) >= 0 else -1.0
        label = (" · ".join(sorted(weights)) if weights
                 else " · ".join(a for a in (assets or []) if a in set(names)))
        out.append(ViewRow(row=row, direction=d, magnitude=mag, label=label,
                           kind=kind, dropped_assets=dropped))
    return out, skipped


def group_spread_row(names: list[str], groups: dict[str, str],
                     long_group: str, short_group: str) -> dict[str, float]:
    """그룹 상대 뷰의 가중치 — `+1/n_long` vs `−1/n_short`.

    ★자산군(EQ/FI/FX)이 아니라 **그룹 맵이 주는 무엇이든**이다.★ 현재 저장소의
    그룹 출처(`constrained_opt.sector_groups_for`)는 **섹터**를 준다. 진짜 자산군
    분류는 별개의 데이터 문제이고(T3 §6.4 항목 2), 여기서는 **행을 만들 수 있다는
    것**까지만 한다.

    Raises:
        ValueError: 어느 한쪽 그룹에 자산이 하나도 없을 때. 빈 그룹으로 스프레드를
            만들면 한쪽 다리만 있는 "상대 뷰" 가 되어 절대 뷰로 둔갑한다.
    """
    lo = [n for n in names if groups.get(n) == long_group]
    sh = [n for n in names if groups.get(n) == short_group]
    for g, members in ((long_group, lo), (short_group, sh)):
        if not members:
            raise ValueError(
                f"그룹 '{g}' 에 속한 자산이 유니버스에 없습니다 — 한쪽 다리만 있는 "
                f"스프레드는 상대 뷰가 아니라 절대 뷰가 됩니다.")
    w = {n: 1.0 / len(lo) for n in lo}
    w.update({n: -1.0 / len(sh) for n in sh})
    return w
