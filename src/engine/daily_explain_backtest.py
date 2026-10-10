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
    DRIVER_LABELS,
    DRIVER_SET_STRATEGY,
    RESIDUAL_CLOSED,
    RESIDUAL_UNEXPLAINED,
    STRATEGY_DRIVERS,
    DailyExplanation,
)

#: ★사유는 대시를 품지 않는다★ — 템플릿이 하나 붙인다(전수 테스트가 지킨다).
_MISSING_EFFECT = "이 실행의 그날 행에서 관측되지 않았습니다(0 이 아니라 미상입니다)"

_NOT_MODELED = ("이 엔진에는 이 축의 모델이 없고 수익률에도 들어 있지 않습니다"
                "(미상이 아니라 없는 축입니다)")

_NO_TOTAL = ("그날의 포트폴리오 수익률이 기록되지 않아 축의 합과 견줄 총변동이 "
             "없습니다")


def explain_backtest_day(row: dict[str, Any], *, run_id: int | str) -> DailyExplanation:
    """일별 귀인 행 하나 → 설명.

    ★항등식 기준★ (BH2) — 드라이버는 `net = EW + alloc + cost (+ cash)` 의 넷이다.
    행의 `identity`(`_daily_attribution` 이 붙인다)가 그 날 항등식이 닫히는지와 이
    실행에 **없는 축**(`not_modeled`)을 말한다. 닫히면 잔차는 `closed`(하루엔 복리가
    없다), 아니면 `unexplained` + 사유다.
    """
    ident = row.get("identity") or {}
    not_modeled_keys = set(ident.get("not_modeled") or [])
    drivers: dict[str, float | None] = {
        c: (None if row.get(c) is None else float(row[c]))
        for c in STRATEGY_DRIVERS if c not in not_modeled_keys
    }
    missing = {c: _MISSING_EFFECT for c, v in drivers.items() if v is None}
    not_modeled = {c: _NOT_MODELED for c in sorted(not_modeled_keys)}

    total = row.get("portfolio_return")
    total = None if total is None else float(total)

    if total is None:
        residual_pct, residual_kind, residual_reason = None, None, _NO_TOTAL
    else:
        known = [v for v in drivers.values() if v is not None]
        residual_pct = round(total - float(sum(known)), 6)
        if not missing and ident.get("closes"):
            residual_kind, residual_reason = RESIDUAL_CLOSED, None
        else:
            residual_kind = RESIDUAL_UNEXPLAINED
            if missing:
                names = ", ".join(DRIVER_LABELS.get(c, c) for c in sorted(missing))
                residual_reason = (f"그날 관측되지 않은 축({names})이 있어 축의 합이 실제 "
                                   "변동과 맞는지 확인할 수 없습니다")
            else:
                residual_reason = ("축을 다 알아도 합이 실제 변동과 맞지 않습니다(수익률에 "
                                   "드라이버 밖의 무엇이 들어 있습니다)")

    return DailyExplanation(
        as_of=str(row.get("date") or ""),
        scope="run", scope_id=f"멀티백테스트 실행 #{run_id}",
        driver_set=DRIVER_SET_STRATEGY,
        total_change_pct=total,
        drivers=drivers, missing_drivers=missing,
        residual_pct=residual_pct, residual_kind=residual_kind,
        residual_reason=residual_reason,
        not_modeled=not_modeled,
        price_basis=None,   # ★전략 분해는 가격 축을 다루지 않는다★
    )
