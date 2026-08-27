"""가격 품질 — ★조정 상태를 관측 가능하고 강제 가능하게★
==============================================================================
감사: [`데이터 추출 감사`](../../docs/specs/2026-08-26-data-extraction-audit.md) §3.1 ·
[`능력 6상태 행렬`](../../docs/specs/2026-08-27-capability-states-matrix.md)
모범: `source_coverage` · `exposure_taxonomy.coverage()` 와 **같은 모양**의 블록

## 왜 이 모듈이 생겼나

`daily_prices` 에 writer 가 둘이다:

    krx_ingest.bulk_upsert        → OHLCV + return_1d + trading_value + mktcap
    ohlcv_loader.ingest_df_to_db  → OHLCV                        ← return_1d 없음

`rebuild_adj_close()` 는 `return_1d` 체인으로 분할·증자 점프를 지운다. 예전에는
등락률이 없으면 **원주가 비율로 폴백**했고, 그 폴백이 지우려던 점프를 다시
집어넣었다. 지금은 체인이 끊기고 그 아래가 `NULL` 이 된다.

★그리고 감사가 더 큰 것을 찾았다★ — **`adj_close` 를 읽는 코드가 하나도 없다.**
정본 로더 `kis_backtest_engine.load_ohlcv` 가 `close`(원주가)를 고르고 26개 파일이
그 위에 있다. 즉 **모든 수익률이 미조정 가격 위에서** 돈다.

소비자를 바꾸는 것(`close → adj_close`)은 배분 결정 경로를 건드리므로 별개 결정이다.
이 모듈은 그 전환의 **선행 조건**을 만든다 — 상태를 재고, 등급을 매기고, 거부한다.

## 네 상태 — ★티커 단위로 배타적★

| 상태 | 판정 | 고치는 방법 |
|---|---|---|
| `adjusted` | 그 티커의 **모든** 행에 `adj_close` 가 있다 | — |
| `chain_broken` | 일부만 있다 — 체인이 중간에서 끊겼다 | 그 구간 KRX 재적재 |
| `raw` | **하나도** 없다 (하위 사유 둘) | ↓ |
| `missing` | 행이 **하나도 없다** | 적재 |

★`missing` 이 왜 따로인가★ 현행 구현은 **존재하는 행만** 봤다. 요청한 티커가 DB 에
아예 없으면 커버리지 100% 로 보인다 — **공허한 참**이다.

★`raw` 의 하위 사유를 접지 않는다★ `not_rebuilt`(재료는 있다 —
`rebuild_adj_close()` 만 돌리면 된다)와 `no_return_data`(등락률 자체가 없다 —
KRX 적재가 필요하다)는 **고치는 사람이 다르다**.

★`raw` 는 실질적으로 "재구성이 돈 적이 없다" 를 뜻한다★ `rebuild_adj_close` 는
앵커(최신 봉)를 `adj = close` 로 **언제나** 채운다 — 그것이 체인의 기준점이기
때문이다. 따라서 재구성이 한 번이라도 돈 티커는 최소 한 행이 `adjusted` 이고,
등락률이 전혀 없어도 `raw` 가 아니라 `chain_broken` 으로 분류된다(체인이 첫
걸음에서 끊긴 것). 이 사실을 모르면 "KIS 전용 티커는 raw 여야 하지 않나" 로
헷갈린다 — 그 티커는 `chain_broken` 이고, 그것이 정확한 서술이다.

## ★임계값을 지어내지 않는다★

기존 계약은 전부-아니면-전무다 — `pit_macro.derive_usage` 는 비율을 모르고,
`timing_rules_v2` 는 `all(bool(o.vintage_id) for o in obs)` 다. 그래서 여기도
**모든 행이 `adjusted` 일 때만** `BACKTEST_ELIGIBLE` 이다. "커버리지 95%" 같은
숫자를 새로 만들면 그 숫자의 근거를 아무도 대지 못한다.

## ★두 번째 등급 체계를 만들지 않는다★

등급은 `pit_macro.derive_usage()` 를 **호출해서** 받는다. 매크로 팩터가 이미
그 어휘(`UNAVAILABLE`/`FORWARD_ONLY`/`BACKTEST_ELIGIBLE`)를 쓰고
`assert_backtest_eligible` → `ForwardOnlyError` → 422 까지 배선돼 있다.
가격이 별도 등급을 만들면 두 체계가 반드시 갈라진다.
"""

from __future__ import annotations

import logging
from typing import Any

from src.data.pit_macro import ForwardOnlyError, ResearchUsage, derive_usage

logger = logging.getLogger(__name__)

#: 이 보고서의 판본. 상태 규칙이 바뀌면 올린다.
QUALITY_VERSION = "2026.2"

# ── 네 상태 (티커 단위 배타) ────────────────────────────────────────────────
STATE_ADJUSTED = "adjusted"
STATE_CHAIN_BROKEN = "chain_broken"
STATE_RAW = "raw"
STATE_MISSING = "missing"
STATES = (STATE_ADJUSTED, STATE_CHAIN_BROKEN, STATE_RAW, STATE_MISSING)

# ── `raw` 의 하위 사유 — ★고치는 사람이 다르다★ ────────────────────────────
RAW_NOT_REBUILT = "not_rebuilt"          # 등락률은 있다 → rebuild_adj_close()
RAW_NO_RETURN_DATA = "no_return_data"    # 등락률 자체가 없다 → KRX 적재

_STATE_TEXT = {
    STATE_ADJUSTED: "모든 행에 수정주가가 있습니다",
    STATE_CHAIN_BROKEN: (
        "수정주가 체인이 중간에서 끊겼습니다 — 등락률이 없는 봉 아래를 추정하지 "
        "않습니다(그날 기업행위가 있었는지 알 수 없습니다)"),
    STATE_RAW: "수정주가가 하나도 없습니다 — 원주가만 있습니다",
    STATE_MISSING: "`daily_prices` 에 행이 하나도 없습니다",
}

_RAW_REASON_TEXT = {
    RAW_NOT_REBUILT: (
        "등락률(return_1d)은 있으나 `rebuild_adj_close()` 를 아직 실행하지 "
        "않았습니다"),
    RAW_NO_RETURN_DATA: (
        "등락률이 아예 없습니다 — KIS 경로로만 적재된 티커입니다. KRX 적재가 "
        "있어야 수정주가를 만들 수 있습니다"),
}

#: 출처 미상 라벨. ★`NULL` 을 `krx` 로 추정하지 않는다★ — 통계가 거짓말을 한다.
SOURCE_UNKNOWN = "unknown"


def _engine(engine=None):
    if engine is not None:
        return engine
    try:
        from src.database import get_engine
        return get_engine()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"엔진을 얻지 못했습니다: {e}")
        return None


def _unavailable(reason: str) -> dict[str, Any]:
    """★재지 못한 것을 0 으로 적지 않는다★ 0 은 '조정된 행이 없다' 는 판단이다."""
    return {"available": False, "reason": reason, "version": QUALITY_VERSION}


def _fetch(tickers, start, end, eng) -> list[tuple] | str:
    """행 조회. 실패하면 사유 문자열을 돌려준다(예외를 위로 던지지 않는다)."""
    from sqlalchemy import text

    where: list[str] = []
    params: dict[str, Any] = {}
    if tickers:
        keys = [f"t{i}" for i in range(len(tickers))]
        where.append("ticker IN (" + ", ".join(f":{k}" for k in keys) + ")")
        params.update(dict(zip(keys, [str(t) for t in tickers], strict=True)))
    if start:
        where.append("trade_date >= :start")
        params["start"] = str(start)
    if end:
        where.append("trade_date <= :end")
        params["end"] = str(end)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    try:
        with eng.connect() as conn:
            return conn.execute(text(
                "SELECT ticker, source, adj_close, return_1d, trade_date "
                f"FROM daily_prices{clause}"), params).fetchall()
    except Exception as e:  # noqa: BLE001
        return f"daily_prices 조회 실패({type(e).__name__}) — {e}"


def adj_close_coverage(tickers: list[str] | None = None, *,
                       start: str | None = None, end: str | None = None,
                       engine=None) -> dict[str, Any]:
    """수정주가 커버리지 — ★네 상태를 티커 단위로 배타 분류한다★

    `tickers` 를 주면 `missing`(행이 없는 티커)을 셀 수 있다. 주지 않으면
    "요청한 티커" 라는 개념이 없으므로 `missing` 은 언제나 0 이고, 그 사실을
    `missing_measurable` 로 **선언**한다 — 0 을 "없다" 로 읽지 않게.

    Returns:
        `{available, rows, tickers, ticker_states, row_states, raw_reasons,
          by_source, missing_tickers, unadjusted_tickers, adjusted_pct,
          missing_measurable, earliest, version}`
    """
    eng = _engine(engine)
    if eng is None:
        return _unavailable("DB 엔진이 없습니다 — 커버리지를 계산할 수 없습니다.")

    rows = _fetch(tickers, start, end, eng)
    if isinstance(rows, str):
        return _unavailable(rows)

    # ── 1차: 티커별 사실 수집 ────────────────────────────────────────────────
    seen: dict[str, dict[str, Any]] = {}
    by_source: dict[str, dict[str, int]] = {}
    earliest: str | None = None
    for ticker, source, adj, ret, trade_date in rows:
        tk = str(ticker)
        f = seen.setdefault(tk, {"rows": 0, "adjusted": 0, "has_return": False})
        f["rows"] += 1
        if adj is not None:
            f["adjusted"] += 1
        if ret is not None:
            f["has_return"] = True
        src = source or SOURCE_UNKNOWN
        slot = by_source.setdefault(src, {"rows": 0, "adjusted": 0})
        slot["rows"] += 1
        if adj is not None:
            slot["adjusted"] += 1
        d = str(trade_date)[:10]
        if earliest is None or d < earliest:
            earliest = d

    # ── 2차: 티커 상태 (★배타★) ─────────────────────────────────────────────
    ticker_states = dict.fromkeys(STATES, 0)
    raw_reasons: dict[str, int] = {}
    by_ticker: dict[str, str] = {}
    missing: list[str] = []
    bad: list[str] = []

    requested = [str(t) for t in (tickers or [])]
    for tk in requested:
        if tk not in seen:
            ticker_states[STATE_MISSING] += 1
            by_ticker[tk] = STATE_MISSING
            missing.append(tk)
            bad.append(tk)

    for tk, f in seen.items():
        if f["adjusted"] == f["rows"]:
            state = STATE_ADJUSTED
        elif f["adjusted"] > 0:
            state = STATE_CHAIN_BROKEN
        else:
            state = STATE_RAW
            reason = RAW_NOT_REBUILT if f["has_return"] else RAW_NO_RETURN_DATA
            raw_reasons[reason] = raw_reasons.get(reason, 0) + 1
        ticker_states[state] += 1
        by_ticker[tk] = state
        if state is not STATE_ADJUSTED:
            bad.append(tk)

    # ── 3차: 행 상태 (★`missing` 은 정의상 행이 없다★) ──────────────────────
    total = len(rows)
    adjusted_rows = sum(f["adjusted"] for f in seen.values())
    broken_rows = sum(f["rows"] - f["adjusted"] for f in seen.values()
                      if 0 < f["adjusted"] < f["rows"])
    raw_rows = sum(f["rows"] for f in seen.values() if f["adjusted"] == 0)

    return {
        "available": True,
        "rows": total,
        "tickers": len(seen),
        "ticker_states": ticker_states,
        "row_states": {STATE_ADJUSTED: adjusted_rows,
                       STATE_CHAIN_BROKEN: broken_rows,
                       STATE_RAW: raw_rows},
        "raw_reasons": {k: {"tickers": v, "note": _RAW_REASON_TEXT[k]}
                        for k, v in sorted(raw_reasons.items())},
        "state_notes": dict(_STATE_TEXT),
        "by_source": by_source,
        "by_ticker": by_ticker,
        # ★이름으로 낸다★ 개수만 내면 어느 종목을 고쳐야 하는지 알 수 없다.
        "missing_tickers": sorted(missing),
        "unadjusted_tickers": sorted(set(bad)),
        "adjusted_pct": round(100.0 * adjusted_rows / total, 2) if total else None,
        # ★0 을 "없다" 로 읽지 않게 선언한다★ 티커 목록을 안 주면 못 재는 값이다.
        "missing_measurable": bool(requested),
        "earliest": earliest,
        "version": QUALITY_VERSION,
    }


def price_usage(tickers: list[str], *, start: str | None = None,
                end: str | None = None, engine=None) -> dict[str, Any]:
    """가격 적격성 — ★`pit_macro.derive_usage` 를 **호출**한다★

    등급 규칙을 다시 쓰지 않는다. 매크로 팩터가 쓰는 어휘를 그대로 쓴다.

    매핑:
        `has_vintage` ↔ **모든 티커가 `adjusted`** — 기업행위가 제거된 계열인가
        `depth_ok`    ↔ `start` 를 이력이 덮는가
        `lag_known`   ↔ ★가격은 언제나 True★ — 장 마감으로 확정되고 공표지연이
                        없다. 매크로 계열의 "공표 시각이 관측기간 이후인가" 에
                        해당하는 문제가 가격에는 존재하지 않는다.
        `has_source`  ↔ 요청한 티커에 행이 있는가

    Returns:
        `{usage, reason, coverage}` — `usage` 는 `ResearchUsage` 값 문자열.
    """
    cov = adj_close_coverage(tickers, start=start, end=end, engine=engine)
    if not cov.get("available"):
        return {"usage": ResearchUsage.UNAVAILABLE.value,
                "reason": cov.get("reason"), "coverage": cov}

    st = cov["ticker_states"]
    requested = len(tickers or [])
    has_source = requested > 0 and st[STATE_MISSING] == 0 and cov["rows"] > 0
    # ★전부-아니면-전무★ 하나라도 adjusted 가 아니면 백테스트 부적격이다.
    all_adjusted = has_source and st[STATE_ADJUSTED] == requested
    depth_ok = (not start) or (cov["earliest"] is not None
                               and cov["earliest"] <= str(start))

    usage = derive_usage(has_vintage=all_adjusted, depth_ok=depth_ok,
                         lag_known=True, has_source=has_source)

    if usage is ResearchUsage.BACKTEST_ELIGIBLE:
        reason = None
    elif not has_source:
        reason = ("요청한 티커에 가격 행이 없습니다"
                  + (f" (없음: {', '.join(cov['missing_tickers'][:5])})"
                     if cov["missing_tickers"] else ""))
    else:
        missing_bits = [n for n, ok in (("수정주가 전량", all_adjusted),
                                        ("이력 길이", depth_ok)) if not ok]
        reason = (f"{' · '.join(missing_bits)} 이(가) 충족되지 않았습니다 — "
                  f"미조정 티커: {', '.join(cov['unadjusted_tickers'][:5])}")
    return {"usage": usage.value, "reason": reason, "coverage": cov}


def assert_prices_backtest_eligible(tickers: list[str], *,
                                    start: str | None = None,
                                    end: str | None = None, engine=None) -> None:
    """과거 시뮬레이션 진입 게이트 — 부적격이면 ★올린다★.

    `pit_macro.assert_backtest_eligible` 과 같은 계약이고 같은 예외를 쓴다
    (`ForwardOnlyError` 는 `ValueError` 라 라우트가 422 로 옮긴다).

    ★조용한 폴백을 두지 않는다★ 미조정 가격으로 과거를 채점하면 분할일 하나가
    수십 % 수익률로 잡히고, 그 이상치 하나가 공분산·팩터 추정을 흔든다.

    Raises:
        ForwardOnlyError: 적격이 아닐 때.
    """
    got = price_usage(tickers, start=start, end=end, engine=engine)
    if got["usage"] != ResearchUsage.BACKTEST_ELIGIBLE.value:
        raise ForwardOnlyError(
            f"가격이 과거 시뮬레이션에 적격하지 않습니다({got['usage']}): "
            f"{got['reason']}")


def adj_status_of(ticker: str, *, engine=None) -> str:
    """티커 하나의 네 상태 중 하나. ★조회 실패도 상태로 낸다★

    `ohlcv_loader` 가 `df.attrs` 에 실을 값이다.
    """
    cov = adj_close_coverage([ticker], engine=engine)
    if not cov.get("available"):
        return STATE_MISSING
    return cov["by_ticker"].get(str(ticker), STATE_MISSING)
