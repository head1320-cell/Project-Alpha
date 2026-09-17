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

from src.domain.equity_observation import SOURCE_MOCK, usable_for_drawdown

logger = logging.getLogger(__name__)

#: 에쿼티 이력이 한 행도 없다. ★`live_daily_pnl` 에 쓰는 코드가 아직 없다.★
REASON_NO_HISTORY = "no_equity_history"
#: ★합성 잔고뿐이다★ — mock 으로 만든 수치로 킬스위치를 발동시키지 않는다.
REASON_MOCK_ONLY = "mock_equity_only"
#: ★브로커 행과 합성 행이 섞여 있다★ — 조용히 broker 만 고르지 않는다.
REASON_MIXED_SOURCE = "mixed_equity_source"
#: 출처를 안 적은 행뿐이다. ★미상은 브로커가 아니다★ (AI 이전에 쓰인 행)
REASON_UNDECLARED_SOURCE = "undeclared_equity_source"
#: `equity_source` 컬럼 자체가 없다 — 어느 행이 실제 조회인지 **가릴 수 없다**.
REASON_NO_SOURCE_COLUMN = "no_equity_source_column"
#: 행은 있는데 양(+)의 에쿼티가 없다 — 분모가 0 이면 비율을 만들 수 없다.
REASON_NO_POSITIVE_EQUITY = "no_positive_equity"
#: 조회 자체가 실패했다. ★"잔고가 0" 과 다른 사실이다.★
REASON_FETCH_FAILED = "fetch_failed"

#: ★출처까지 함께 읽는다★ — 필터를 파이썬 쪽에서 하는 이유는 *"섞였다"* 를
#: 판정하려면 걸러내기 **전에** 무엇이 있었는지 알아야 하기 때문이다. SQL 에서
#: `WHERE equity_source='broker'` 로 잘라 버리면 mock 행이 있었다는 사실이 사라지고,
#: 그러면 조용히 broker 만 골라 쓰는 것과 구별되지 않는다.
_QUERY = ("SELECT starting_equity_krw, ending_equity_krw, equity_source "
          "FROM live_daily_pnl ORDER BY trade_date")

#: `equity_source` 컬럼이 아직 안 붙은 DB 를 위한 폴백(컬럼 없이도 조회는 된다).
_QUERY_NO_SOURCE = ("SELECT starting_equity_krw, ending_equity_krw FROM live_daily_pnl "
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
    has_source = True
    try:
        with engine.connect() as conn:
            try:
                rows = conn.execute(text(_QUERY)).fetchall()
            except Exception:                            # noqa: BLE001
                # 컬럼이 아직 안 붙은 DB — 조회 자체는 되지만 출처를 못 가린다.
                has_source = False
                rows = conn.execute(text(_QUERY_NO_SOURCE)).fetchall()
    except Exception as e:                               # noqa: BLE001
        # ★사유에 원인을 싣는다★ — 사유 없는 "unavailable" 은 금지(CLAUDE.md §4)
        return _unknown(f"{REASON_FETCH_FAILED}: {e}")

    if not rows:
        return _unknown(REASON_NO_HISTORY)

    # ★출처로 거른다 — 이 작업의 안전 핵심★
    # 판정은 `usable_for_drawdown` 한 곳에만 있다(복사하면 한쪽만 고쳐도 조용하다).
    if has_source:
        usable = [r for r in rows if usable_for_drawdown(r[2])]
        if not usable:
            # ★`mock` 과 `unknown` 을 같은 사유로 적지 않는다★ — 전자는 "합성이었다",
            # 후자는 "못 밝혔다" 이고 처방이 다르다.
            sources = {r[2] for r in rows}
            if sources == {SOURCE_MOCK}:
                return _unknown(REASON_MOCK_ONLY)
            if SOURCE_MOCK in sources:
                return _unknown(REASON_MIXED_SOURCE)
            return _unknown(REASON_UNDECLARED_SOURCE)
        if len(usable) != len(rows):
            # ★조용히 broker 만 고르지 않는다★ — 섞였다는 사실 자체가 상태다.
            return _unknown(REASON_MIXED_SOURCE)
        rows = usable
    else:
        # 컬럼이 없으면 어느 행이 실제 조회인지 **가릴 수 없다**. 숫자를 내면
        # 그것은 "출처를 확인했다" 는 없는 사실이 된다.
        return _unknown(REASON_NO_SOURCE_COLUMN)

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
