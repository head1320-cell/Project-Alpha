"""가격 품질 관측 — ★몇 %가 조정되지 않았는지가 보이지 않으면 아무도 모른다★
==============================================================================
감사: [`데이터 추출 감사`](../../docs/specs/2026-08-26-data-extraction-audit.md) §3.1
모범: `source_coverage` · `exposure_taxonomy.coverage()` 와 **같은 모양**의 블록

## 왜 이 모듈이 생겼나

`daily_prices` 에 writer 가 둘이다:

    krx_ingest.bulk_upsert        → OHLCV + return_1d + trading_value + mktcap
    ohlcv_loader.ingest_df_to_db  → OHLCV                        ← return_1d 없음

`rebuild_adj_close()` 는 `return_1d` 체인으로 분할·증자 점프를 지운다. 예전에는
등락률이 없으면 **원주가 비율로 폴백**했고, 그 폴백이 지우려던 점프를 다시
집어넣었다. 지금은 체인이 끊기고 그 아래가 `NULL` 이 된다.

★그 결과 커버리지가 떨어진다 — 그것이 요점이다.★ 조용히 틀린 값이 정직한 빈칸이
되었으니, 이제 **그 빈칸이 얼마나 되는지 말할 수 있어야** 한다. 말하지 않으면
"수정주가가 있다" 고 믿은 채로 백테스트를 돌리게 된다.

## 세 상태를 구분한다

| `adj_close` | 뜻 |
|---|---|
| 값 있음 | ★조정됨★ |
| `NULL` (같은 티커에 조정된 행이 **있다**) | 체인이 끊겼다 — **모른다** |
| `NULL` (같은 티커가 **전부** NULL) | `rebuild_adj_close` 를 아직 안 돌렸다 |

"데이터가 없다" 와 "계산을 안 했다" 는 다른 사실이고, 섞으면 고칠 방법이 달라진다.

★판정은 **행이 아니라 티커** 단위다★ 처음에는 행의 `return_1d` 유무로 갈랐는데
**틀렸다** — 체인이 위에서 끊기면 그 아래 행들은 `return_1d` 를 **가지고 있으면서도**
`adj_close` 가 NULL 이다. 그 행들을 "계산 안 함" 으로 세면 이미 돌린 재구성을 안
돌렸다고 보고하게 된다. 재구성이 돌았는지는 **그 티커에 조정된 행이 하나라도
있는가**로만 알 수 있다.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: 이 보고서의 판본. 규칙(체인 끊김 처리)이 바뀌면 올린다.
QUALITY_VERSION = "2026.1"

#: 미조정 사유 — ★사유 없는 빈칸은 블랙박스다★
UNADJUSTED_CHAIN_BROKEN = "chain_broken"        # return_1d 결측으로 체인이 끊겼다
UNADJUSTED_NOT_REBUILT = "not_rebuilt"          # 재료는 있는데 아직 안 돌렸다

_REASON_TEXT = {
    UNADJUSTED_CHAIN_BROKEN: (
        "등락률(return_1d)이 없어 수정주가 체인이 끊겼습니다 — 그날 기업행위가 "
        "있었는지 알 수 없으므로 추정하지 않습니다"),
    UNADJUSTED_NOT_REBUILT: (
        "등락률은 있으나 `rebuild_adj_close()` 를 아직 실행하지 않았습니다"),
}


def _engine(engine=None):
    if engine is not None:
        return engine
    try:
        from src.database import get_engine
        return get_engine()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"엔진을 얻지 못했습니다: {e}")
        return None


def adj_close_coverage(tickers: list[str] | None = None, engine=None
                       ) -> dict[str, Any]:
    """수정주가 커버리지 블록.

    ★DB 가 없으면 `{available: False, reason}` 이다 — 0 이 아니다.★
    0 은 "조정된 행이 없다" 는 판단이고, 여기서는 **재지 못한 것**이다.

    Returns:
        `{available, rows, adjusted, unadjusted, adjusted_pct, by_source,
          reasons, unadjusted_tickers, tickers, version}`
    """
    from sqlalchemy import text

    eng = _engine(engine)
    if eng is None:
        return {"available": False,
                "reason": "DB 엔진이 없습니다 — 커버리지를 계산할 수 없습니다.",
                "version": QUALITY_VERSION}

    where, params = "", {}
    if tickers:
        keys = [f"t{i}" for i in range(len(tickers))]
        where = " WHERE ticker IN (" + ", ".join(f":{k}" for k in keys) + ")"
        params = dict(zip(keys, [str(t) for t in tickers], strict=True))

    try:
        with eng.connect() as conn:
            rows = conn.execute(text(
                "SELECT ticker, source, adj_close, return_1d "
                f"FROM daily_prices{where}"), params).fetchall()
    except Exception as e:  # noqa: BLE001
        return {"available": False,
                "reason": f"daily_prices 조회 실패({type(e).__name__}) — {e}",
                "version": QUALITY_VERSION}

    total = len(rows)
    adjusted = 0
    reasons: dict[str, int] = {}
    by_source: dict[str, dict[str, int]] = {}
    bad: set[str] = set()
    seen: set[str] = set()

    # ★티커별로 "재구성이 돌았는가" 를 먼저 정한다★ (독스트링의 판정 규칙)
    rebuilt: dict[str, bool] = {}
    for ticker, _source, adj, _ret in rows:
        tk = str(ticker)
        rebuilt[tk] = rebuilt.get(tk, False) or (adj is not None)

    for ticker, source, adj, _ret in rows:
        tk = str(ticker)
        seen.add(tk)
        src = source or "unknown"          # ★NULL 을 'krx' 로 추정하지 않는다★
        slot = by_source.setdefault(src, {"rows": 0, "adjusted": 0})
        slot["rows"] += 1
        if adj is not None:
            adjusted += 1
            slot["adjusted"] += 1
            continue
        reason = (UNADJUSTED_CHAIN_BROKEN if rebuilt[tk]
                  else UNADJUSTED_NOT_REBUILT)
        reasons[reason] = reasons.get(reason, 0) + 1
        bad.add(tk)

    return {
        "available": True,
        "rows": total,
        "adjusted": adjusted,
        "unadjusted": total - adjusted,
        "adjusted_pct": round(100.0 * adjusted / total, 2) if total else None,
        "by_source": by_source,
        "reasons": {k: {"rows": v, "note": _REASON_TEXT[k]}
                    for k, v in sorted(reasons.items())},
        # ★이름으로 낸다★ 개수만 내면 어느 종목을 고쳐야 하는지 알 수 없다.
        "unadjusted_tickers": sorted(bad),
        "tickers": len(seen),
        "version": QUALITY_VERSION,
    }
