"""에쿼티 이력 — ★표도 리더도 있고, 쓰는 코드만 없었다★ (AI3)
==============================================================================
어휘: `src/domain/equity_observation.py` · 소비자: `src/execution/drawdown.py`
호출부: `src/startup/lifecycle.py::_risk_monitor_bg`

## 왜 이 모듈이 생겼나

킬스위치 자동 트리거 넷 중 둘(`auto_dd` 누적 -10% · `auto_cb` 일중 -5%)이 발동할 수
없는 이유는 하나였다: **에쿼티 이력이 비어 있다.** `live_daily_pnl` 표도,
`drawdown_from_history` 리더도, 보존정책도, 조회 라우트도 다 있는데 ★그 표에 쓰는
코드가 저장소에 없었다★ — `drawdown.py:18` 이 스스로 그렇게 적어 뒀다.

## ★`starting` 은 그날 첫 관측에만 쓴다★

일중 드로다운의 정의가 `(starting - ending) / starting` 이다. 매 틱마다 `starting`
을 현재 에쿼티로 덮으면 언제나 `starting == ending` 이 되어 ★일중 드로다운이 영원히
0★ 이고, `auto_cb` 는 다시 발동 불능이 된다. 그래서 갱신하는 것은 `ending` 뿐이다.

## ★조회 실패는 행을 만들지 않는다★

`_fetch_account_state()` 는 실패 시 `equity_krw=None` 을 돌려준다 — *"잔고가 0"* 과
*"못 읽었다"* 를 가르려고 애써 만든 구분이다. 그것을 0 으로 적으면 그 구분이
이력에서 무너지고, 드로다운은 **-100%** 를 보게 된다.

## ★mock 도 기록한다 — 다만 라벨한다★

안 쓰는 것이 아니라 출처를 붙여 쓴다. 기록하지 않으면 *"그날 감시가 돌았는데
mock 이었다"* 는 사실 자체가 사라진다. 그 행이 드로다운 계열에 못 들어가는 것은
리더(`drawdown_from_history`)가 `usable_for_drawdown` 으로 거르기 때문이다.

## ★이 모듈이 주장하지 않는 것★

- **킬스위치가 작동한다고 말하지 않는다** — 재는 것과 막는 것은 다르다.
- **과거를 복원하지 않는다** — 백필은 없다. 이력은 오늘부터 쌓인다.
"""
from __future__ import annotations

import logging
import math
from datetime import date as _date

from src.domain.equity_observation import SOURCE_BROKER, SOURCE_MOCK

logger = logging.getLogger(__name__)

#: 조회 실패 — `None` 을 0 으로 적으면 "실패" 가 "잔고 0" 이 된다.
REASON_NO_EQUITY = "no_equity_value"
#: 숫자가 아니거나 유한하지 않다. ★모양이 다르면 지어내지 않는다★
REASON_BAD_EQUITY = "unusable_equity_value"
#: 기록 자체가 실패했다(DB). ★판정을 막지는 않는다★
REASON_WRITE_FAILED = "write_failed"

_INSERT = (
    "INSERT INTO live_daily_pnl "
    "(trade_date, execution_mode, starting_equity_krw, ending_equity_krw, equity_source) "
    "VALUES (:d, :mode, :eq, :eq, :src)"
)

#: ★`starting` 을 건드리지 않는다★ — 그날 첫 관측값이 그대로 남아야 일중
#: 드로다운이 의미를 갖는다.
_UPDATE = (
    "UPDATE live_daily_pnl SET ending_equity_krw = :eq, execution_mode = :mode, "
    "equity_source = :src WHERE trade_date = :d"
)


def current_source() -> str:
    """지금 잔고를 **어디서 읽고 있나**. ★`mock_allowed()` 가 유일한 판정 기준★

    `get_kis_client()` 가 같은 게이트로 클라이언트를 고른다(`kis_client.py:919`).
    출처를 여기서 따로 판단하면 mock 클라이언트가 준 값에 `broker` 라벨이 붙는
    순간이 생기고, 그러면 킬스위치가 합성 숫자로 발동한다.
    """
    from src.data.mock_gate import mock_allowed
    return SOURCE_MOCK if mock_allowed() else SOURCE_BROKER


def _usable_equity(account_state: dict | None) -> tuple[float | None, str | None]:
    """계좌 상태 → 쓸 수 있는 에쿼티. ★못 쓰면 `None` + 사유★"""
    raw = (account_state or {}).get("equity_krw")
    if raw is None:
        return None, REASON_NO_EQUITY
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None, REASON_BAD_EQUITY
    value = float(raw)
    if not math.isfinite(value):
        return None, REASON_BAD_EQUITY
    return value, None


def record_observation(engine, *, account_state: dict | None,
                       execution_mode: str | None, source: str | None,
                       trade_date: str | None = None) -> dict:
    """오늘의 에쿼티를 한 행으로 남긴다. ★하루 한 행, `ending` 만 갱신★

    Returns:
        `{"written": bool, "reason": str | None, "trade_date": str, "equity_krw": float | None}`

    ★예외를 올리지 않는다★ — 이 함수의 호출부는 리스크 감시 루프이고, 기록 실패가
    판정을 멈추면 감시 자체가 죽는다(`risk_monitor.py:118` 이 세운 관용구).
    """
    day = trade_date or _date.today().isoformat()
    equity, reason = _usable_equity(account_state)
    if equity is None:
        return {"written": False, "reason": reason, "trade_date": day,
                "equity_krw": None}

    params = {"d": day, "mode": execution_mode, "eq": equity, "src": source}
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            updated = conn.execute(text(_UPDATE), params).rowcount
            if not updated:
                conn.execute(text(_INSERT), params)
    except Exception as e:                                   # noqa: BLE001
        logger.warning(f"에쿼티 이력 기록 실패(판정은 유효): {e}")
        return {"written": False, "reason": f"{REASON_WRITE_FAILED}: {e}",
                "trade_date": day, "equity_krw": equity}

    return {"written": True, "reason": None, "trade_date": day, "equity_krw": equity}
