"""드로다운 — ★모르면 `None` 이다. 0 이 아니다★ (P1-a)
==============================================================================
소비자: `execution/order_executor.py::_fetch_account_state` →
        `execution/kill_switch.py::should_auto_trigger` ·
        `execution/risk_gateway.py::_tier2_dynamic_checks` ⑨

## 왜 이 모듈이 생겼나 — ★서킷브레이커 둘이 발동할 수 없었다★

`_fetch_account_state()` 가 드로다운 두 칸을 **하드코딩 0** 으로 돌려줬다
(`# TODO: live monitor에서 계산`). 0 은 어떤 임계값도 넘지 못하므로
`auto_dd`(누적 -10%) · `auto_cb`(일중 -5%) 와 게이트웨이의 ⑨ 서킷브레이커가
★구조적으로 절대 발동할 수 없었다★. 예외 경로도 같은 0 을 돌려줘 **조회 실패가
"손실 0" 으로 보였다** — CLAUDE.md §4 가 금지한 *"타당성을 조용히 제조"* 다.

## 이 모듈이 하는 것 / ★하지 않는 것★

하는 것은 **미상을 미상으로 만드는 것**뿐이다. 드로다운을 실제로 **계산하려면
에쿼티 이력**이 필요하고, 그 이력(`live_daily_pnl`)에 ★쓰는 코드가 저장소에 없다★
(실측). 그래서 지금 이 함수는 거의 항상 `REASON_NO_HISTORY` 를 돌려준다.

★그것이 결함이 아니라 결과물이다.★ 이전에는 같은 상황이 "손실 0%" 로 보였다.

## 정의

    누적  = (정점 마감에쿼티 − 최근 마감에쿼티) / 정점 마감에쿼티
    일중  = (최근 시작에쿼티 − 최근 마감에쿼티) / 최근 시작에쿼티

둘 다 **양수 비율**(0.10 = 10% 하락)이다 — 소비자가 `abs()` 로 비교한다.
이익 구간은 0 으로 자른다(음수 드로다운은 없다).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: 에쿼티 이력이 한 행도 없다. ★`live_daily_pnl` 에 쓰는 코드가 아직 없다.★
REASON_NO_HISTORY = "no_equity_history"
#: 행은 있는데 양(+)의 에쿼티가 없다 — 분모가 0 이면 비율을 만들 수 없다.
REASON_NO_POSITIVE_EQUITY = "no_positive_equity"
#: 조회 자체가 실패했다. ★"잔고가 0" 과 다른 사실이다.★
REASON_FETCH_FAILED = "fetch_failed"

_QUERY = ("SELECT starting_equity_krw, ending_equity_krw FROM live_daily_pnl "
          "ORDER BY trade_date")


@dataclass(frozen=True)
class Drawdown:
    """`None` 은 ★0 이 아니라 미상★이다. `reason` 이 왜인지 말한다."""
    intraday_pct: float | None
    cumulative_pct: float | None
    reason: str | None

    @property
    def is_known(self) -> bool:
        return self.intraday_pct is not None and self.cumulative_pct is not None


def _unknown(reason: str) -> Drawdown:
    return Drawdown(intraday_pct=None, cumulative_pct=None, reason=reason)


def drawdown_from_history(engine) -> Drawdown:
    """에쿼티 이력에서 (일중, 누적) 드로다운. ★못 재면 `None` + 사유.★"""
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(_QUERY)).fetchall()
    except Exception as e:                               # noqa: BLE001
        # ★사유에 원인을 싣는다★ — 사유 없는 "unavailable" 은 금지(CLAUDE.md §4)
        return _unknown(f"{REASON_FETCH_FAILED}: {e}")

    if not rows:
        return _unknown(REASON_NO_HISTORY)

    ends = [float(r[1]) for r in rows if r[1] is not None]
    peak = max(ends) if ends else 0.0
    last_end = ends[-1] if ends else 0.0
    last_start = float(rows[-1][0]) if rows[-1][0] is not None else 0.0

    # ★분모 가드★ — 음수·0 에쿼티에서 비율을 만들지 않는다(CLAUDE.md §6 수치 안전)
    if peak <= 0 or last_start <= 0:
        return _unknown(REASON_NO_POSITIVE_EQUITY)

    cumulative = max(0.0, (peak - last_end) / peak)
    intraday = max(0.0, (last_start - last_end) / last_start)
    return Drawdown(intraday_pct=intraday, cumulative_pct=cumulative, reason=None)
