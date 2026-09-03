"""③ 신호 수준 관문의 순수 부품 — ★국면이 **다음 달** 수익을 설명하는가★ (A4)
==============================================================================
감사(`7313371`)가 낸 연구 부채: 신호 수준(③) 관문이 **하중이 아니고**,
국면→자산수익 관문은 아예 없었다. 배분 성과(④)로만 판정하면 국면 정보가 하나도
없어도 비용·제약 구조가 Sharpe 를 움직여 통과할 수 있다 — M1~M5 의 널 중앙값이
**양수**(+0.021)였던 것이 바로 그 구조적 효과다.

★동시대와 선행을 반드시 가른다★

| 지평 | 묻는 것 | 어느 질문 |
|---|---|---|
| `horizon=0` 동시대 | 라벨 t 가 수익 t 를 설명하는가 | ①정보 표현력 |
| `horizon=1` **선행** | 라벨 t 가 수익 **t+1** 을 설명하는가 | ★③예측 스킬★ |

합성 패널에서 둘이 비슷하게 나오는 이유는 국면 과정이 **지속적**이기 때문이다
(`_P_TRUE` 대각 0.65~0.75) — 라벨 t 가 라벨 t+1 을 잘 맞히니 t+1 수익도
설명한다. 그 사실을 모른 채 동시대 η² 을 "예측력" 으로 읽으면 정확히 만다트가
금지한 혼동이다. ★두 수를 **둘 다** 내고 어느 쪽이 ③ 인지 적는다.★

★널은 새로 만들지 않는다★ 서로게이트는 `regime_surrogates`, 분위·방향은
`null_stats` 가 이미 단일 출처다. 여기는 **통계와 정렬**만 맡는다.
"""

from __future__ import annotations

from typing import Any

HORIZON_CONTEMPORANEOUS = 0
HORIZON_FORWARD = 1

#: ★결정적 지평★ — 이 관문이 답하는 질문은 ③ 예측 스킬이다.
DECISIVE_HORIZON = HORIZON_FORWARD


def monthly_matrix(R: Any, dates: Any) -> Any:
    """일수익 행렬 → **월 합계** 행렬 (월 오름차순).

    로그수익이 아니라 단순 합이다 — 관문이 재는 것은 수준이 아니라 **국면 간
    분산 분해**라 단조 변환에 둔감하다. 그래도 관례이므로 적어 둔다.
    """
    import numpy as np
    import pandas as pd

    a = np.asarray(R, dtype=float)
    idx = pd.DatetimeIndex(dates)
    if a.shape[0] != len(idx):
        raise ValueError(f"수익 행 {a.shape[0]} 과 날짜 {len(idx)} 가 다릅니다")
    key = pd.Series(idx).dt.strftime("%Y-%m").values
    months = sorted(set(key))
    return np.array([a[key == m].sum(axis=0) for m in months], dtype=float)


def align(labels: list[str], monthly: Any, *, horizon: int) -> tuple[list[str], Any]:
    """라벨과 월수익을 지평만큼 어긋나게 짝짓는다.

    ★선행에서 마지막 라벨은 버린다★ 짝지을 수익이 없기 때문이다. 라벨을 그대로
    두고 수익만 밀면 라벨 t 가 수익 t 를 보는 셈이 되어 **룩어헤드**가 된다
    (만다트 §42 *future observation introduced*).
    """
    import numpy as np

    h = int(horizon)
    if h < 0:
        raise ValueError("음의 지평은 미래 라벨로 과거를 설명하는 것입니다 — 룩어헤드")
    m = np.asarray(monthly, dtype=float)
    n = min(len(labels), m.shape[0]) - h
    if n <= 0:
        return [], m[:0]
    return list(labels[:n]), m[h:h + n]


def eta_squared(labels: list[str], monthly: Any) -> float | None:
    """국면이 설명하는 **분산의 비율** η² ∈ [0, 1]. 설명할 분산이 없으면 `None`.

    ★자산 내 디민 후 풀링한다★ 자산 간 수준 차이(예: EQ 가 FI 보다 늘 높다)는
    국면과 아무 상관이 없는데, 디민하지 않으면 그것이 국면 간 제곱합으로 흘러들어
    η² 을 부풀린다.

    ★미상 ≠ 0★ 전체 제곱합이 0 이면 비율이 정의되지 않는다. 그때 `0.0` 을 내면
    "국면이 아무것도 설명하지 않는다" 는 **하지 않은 진술**이 된다.
    """
    import numpy as np

    m = np.asarray(monthly, dtype=float)
    if m.ndim != 2:
        m = m.reshape(len(m), -1) if m.size else m.reshape(0, 0)
    if len(labels) != m.shape[0]:
        raise ValueError(f"라벨 {len(labels)} 과 관측 {m.shape[0]} 이 다릅니다")
    if m.shape[0] < 2 or m.size == 0:
        return None

    x = m - m.mean(axis=0, keepdims=True)          # ★자산 내 디민★
    total = float((x ** 2).sum())
    if not np.isfinite(total) or total <= 0.0:
        return None

    lab = np.asarray(labels, dtype=object)
    between = 0.0
    for g in np.unique(lab):
        sel = lab == g
        between += int(sel.sum()) * float((x[sel].mean(axis=0) ** 2).sum())
    return float(min(1.0, max(0.0, between / total)))
