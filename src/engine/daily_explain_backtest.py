"""백테스트 하루를 설명한다 — ★5효과를 문장으로★ (AB3)
==============================================================================
설계: `docs/plans` AB · 어휘는 `src/domain/daily_explanation.py`
입력: `attribution_decomposer._daily_attribution` 이 낸 행 하나

## ★이 어댑터에는 독립적인 총변동이 있다★

`multibacktest_daily.portfolio_return` 은 5효과와 **따로** 기록된다. 그래서
잔차(총변동 − Σ축)가 실재하는 값이고, 그 잔차의 **이름**은 커버리지가 정한다 —
완전하면 복리 `interaction`, 불완전하면 복리와 미관측이 섞인 `unexplained`.
`AttributionDecomposer` 의 누적 경로가 쓰는 구분 그대로다(새 규칙 0개).

보유 어댑터(`daily_explain_holdings`)는 **그 총변동이 없다** — 두 어댑터가 깊게
다른 지점이고, 그 차이를 가리면 거짓말이 된다.
"""
from __future__ import annotations

from typing import Any

from src.domain.daily_explanation import (
    DRIVER_SET_STRATEGY,
    RESIDUAL_INTERACTION,
    RESIDUAL_UNEXPLAINED,
    STRATEGY_DRIVERS,
    DailyExplanation,
)

#: ★사유는 대시를 품지 않는다★ — 템플릿이 하나 붙인다(전수 테스트가 지킨다).
_MISSING_EFFECT = "이 실행의 그날 행에서 관측되지 않았습니다(0 이 아니라 미상입니다)"

_NO_TOTAL = ("그날의 포트폴리오 수익률이 기록되지 않아 축의 합과 견줄 총변동이 "
             "없습니다")


def explain_backtest_day(row: dict[str, Any], *, run_id: int | str) -> DailyExplanation:
    """일별 귀인 행 하나 → 설명.

    Args:
        row: `_daily_attribution` 의 원소. `coverage` 를 들고 있어야 한다
            (AB2 가 붙였다) — 없으면 관측된 효과 수로 되센다.
    """
    drivers: dict[str, float | None] = {
        c: (None if row.get(c) is None else float(row[c])) for c in STRATEGY_DRIVERS
    }
    missing = {c: _MISSING_EFFECT for c, v in drivers.items() if v is None}

    cov = row.get("coverage") or {}
    complete = bool(cov.get("complete", not missing))

    total = row.get("portfolio_return")
    total = None if total is None else float(total)

    if total is None:
        residual_pct, residual_kind, residual_reason = None, None, _NO_TOTAL
    else:
        known = [v for v in drivers.values() if v is not None]
        residual_pct = round(total - float(sum(known)), 4)
        if complete:
            residual_kind, residual_reason = RESIDUAL_INTERACTION, None
        else:
            residual_kind = RESIDUAL_UNEXPLAINED
            names = ", ".join(sorted(missing)) or "일부 축"
            # ★커버리지가 불완전하면 잔차를 "복리" 라고 부르기를 거부한다★
            # (`AttributionDecomposer._cumulative` 의 같은 문장)
            residual_reason = (
                f"{names} 의 커버리지가 불완전해 잔차가 복리 효과와 미관측분의 "
                "혼합입니다(복리 효과로 읽을 수 없습니다)")

    return DailyExplanation(
        as_of=str(row.get("date") or ""),
        scope="run", scope_id=f"멀티백테스트 실행 #{run_id}",
        driver_set=DRIVER_SET_STRATEGY,
        total_change_pct=total,
        drivers=drivers, missing_drivers=missing,
        residual_pct=residual_pct, residual_kind=residual_kind,
        residual_reason=residual_reason,
        price_basis=None,   # ★전략 분해는 가격 축을 다루지 않는다★
    )
