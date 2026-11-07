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

★`raw` 는 글자 그대로 "조정된 행이 하나도 없다" 를 뜻한다★ 등락률이 전혀 없는
티커(KIS 경로로만 적재된 경우)는 `rebuild_adj_close` 가 앵커를 세울 근거 자체가
없어 전량 `NULL` 이고, 따라서 `raw` 다.

★한때는 그렇지 않았다★ 예전 재구성은 앵커를 **무조건 최신 봉**에 놓고 `adj = close`
로 채웠기 때문에, 등락률이 하나도 없어도 한 행이 `adjusted` 로 남아 그 티커가
`chain_broken` 으로 잡혔다 — "그 구간을 재적재하라" 는 **틀린 조치**를 안내한 것이다.
지금은 앵커가 "등락률을 쓸 수 있는 가장 최신 행" 이라 그 예외가 사라졌다
(`krx_ingest.rebuild_adj_close` 독스트링).

## ★임계값을 지어내지 않는다★

기존 계약은 전부-아니면-전무다 — `pit_macro.derive_usage` 는 비율을 모르고,
`timing_rules_v2` 는 `all(bool(o.vintage_id) for o in obs)` 다. 그래서 여기도
**모든 행이 `adjusted` 일 때만** `BACKTEST_ELIGIBLE` 이다. "커버리지 95%" 같은
숫자를 새로 만들면 그 숫자의 근거를 아무도 대지 못한다.

## ★다섯째 사실 — 가격 **정의**(basis) 는 조정 커버리지와 다른 축이다★

위 네 상태는 *"`adj_close` 가 채워졌는가"* 를 묻는다. 그런데 그보다 **앞서는**
질문이 있다 — *"`close` 가 무엇인가."* 같은 컬럼에 두 정의가 섞여 있다:

    source='krx' → 원주가   (KRX 시세는 수정주가가 아니다)
    source='kis' → 수정주가 (`kis_client.DAILY_ADJ_PRC_FLAG="0"` 로 요청)

소스 경계를 넘는 티커의 `close` 계열에는 **정의 점프**가 생긴다 — 기업행위 점프가
아니라 **누적 수정계수 전체**다. 그리고 정본 로더가 고르는 것이 바로 그 `close` 다.

★그래서 상태를 다섯 개로 늘리지 않고 축을 하나 더한다★ 두 사실은 서로를 대체하지
않는다(Phase 1 에서 `not_ingested` 가 '미검증' 을 덮어써 가드가 죽은 적이 있다).

## ★단정하지 않는 것★

*"KIS 가 준 값이 실제로 수정주가다"* 는 **여기에 적지 않는다.** 근거가 코드 주석
하나뿐이고 이 환경은 외부 호출이 막혀 있다. `price_basis` 가 적는 것은 좁다 —
**우리가 무엇을 요청했는가**. 그 요청이 실제로 수정주가를 돌려주는지는
`basis_overlap_check()` 가 연속 종가의 수익률과 KRX 등락률이 맞는지 보고 나서 말한다.
그때까지 KIS 행의 `adj_close` 는 **채우지 않는다**.

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
        "등락률이 아예 없어 역산 앵커를 세울 수 없습니다 — KIS 경로로만 적재된 "
        "티커입니다. `adj_close` 를 **역산**하려면 KRX 적재가 필요합니다. 다만 "
        "KIS 는 수정주가로 요청해 받으므로(`kis_client.DAILY_ADJ_PRC_FLAG`) "
        "`close` 자체가 이미 조정된 값일 수 있습니다 — 그 여부는 확인되지 "
        "않았고, `basis_overlap_check()` 가 실데이터에서 판정합니다"),
}

#: 출처 미상 라벨. ★`NULL` 을 `krx` 로 추정하지 않는다★ — 통계가 거짓말을 한다.
SOURCE_UNKNOWN = "unknown"

# ── 다섯째 축: 가격 정의 일관성 (★네 상태와 직교★) ─────────────────────────
BASIS_UNIFORM_RAW = "uniform_raw"            # 그 티커 행이 전부 원주가
BASIS_UNIFORM_ADJUSTED = "uniform_adjusted"  # 전부 수정주가
BASIS_MIXED = "mixed"                        # ★두 정의가 섞였다★
BASIS_UNKNOWN = "unknown"                    # 전부 NULL — 레거시 행
BASIS_CONSISTENCY = (BASIS_UNIFORM_RAW, BASIS_UNIFORM_ADJUSTED,
                     BASIS_MIXED, BASIS_UNKNOWN)

_BASIS_TEXT = {
    BASIS_UNIFORM_RAW: "모든 행이 원주가입니다",
    BASIS_UNIFORM_ADJUSTED: "모든 행이 수정주가로 요청되어 적재됐습니다",
    BASIS_MIXED: (
        "★한 티커의 `close` 에 원주가와 수정주가가 섞여 있습니다★ 소스 경계에서 "
        "계열이 점프합니다 — 기업행위 점프가 아니라 누적 수정계수 전체입니다"),
    BASIS_UNKNOWN: (
        "가격 정의가 기록되지 않은 레거시 행뿐입니다 — 소급 추정하지 않습니다"),
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
                "SELECT ticker, source, adj_close, return_1d, trade_date, "
                "price_basis "
                f"FROM daily_prices{clause}"), params).fetchall()
    except Exception as e:  # noqa: BLE001
        return f"daily_prices 조회 실패({type(e).__name__}) — {e}"


def _basis_of(bases: set) -> str:
    """티커 하나의 가격 정의 일관성. ★NULL 을 추정하지 않는다★

    - 알려진 정의가 **둘 이상**이면 `mixed`.
    - 알려진 정의가 하나뿐이면 `uniform_*` — NULL 이 섞여 있어도 그렇게 부른다.
      NULL 은 "다른 정의" 가 아니라 "모른다" 이므로 혼합의 **증거가 아니다**.
      대신 그 사실은 `basis_unknown_rows` 로 **따로** 보고한다(사실을 대체하지
      않고 더한다).
    - 알려진 정의가 하나도 없으면 `unknown`.
    """
    known = {b for b in bases if b}
    if len(known) > 1:
        return BASIS_MIXED
    if not known:
        return BASIS_UNKNOWN
    only = next(iter(known))
    return (BASIS_UNIFORM_ADJUSTED if only == "adjusted"
            else BASIS_UNIFORM_RAW if only == "raw"
            else BASIS_UNKNOWN)


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
    for ticker, source, adj, ret, trade_date, basis in rows:
        tk = str(ticker)
        f = seen.setdefault(tk, {"rows": 0, "adjusted": 0, "has_return": False,
                                 "bases": set()})
        f["rows"] += 1
        # ★`None` 을 그대로 담는다★ NULL 은 "모른다" 이지 "원주가" 가 아니다.
        f["bases"].add(basis if basis is None else str(basis))
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

    basis_states = dict.fromkeys(BASIS_CONSISTENCY, 0)
    basis_by_ticker: dict[str, str] = {}
    mixed: list[str] = []

    for tk, f in seen.items():
        b = _basis_of(f["bases"])
        basis_states[b] += 1
        basis_by_ticker[tk] = b
        if b is BASIS_MIXED:
            mixed.append(tk)
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
        # ★네 상태와 직교하는 축★ 조정 여부를 따지기 전에 `close` 가 무엇인가.
        "basis_states": basis_states,
        "basis_by_ticker": basis_by_ticker,
        "basis_notes": dict(_BASIS_TEXT),
        # ★이름으로 낸다★ 어느 종목의 계열이 점프하는지 알아야 고칠 수 있다.
        "mixed_basis_tickers": sorted(mixed),
        # NULL basis 행 수 — `mixed` 를 대체하지 않고 **더한다**.
        "basis_unknown_rows": sum(
            1 for r in rows if r[5] is None),
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
        `has_vintage` ↔ **모든 티커가 `adjusted`** **그리고** 가격 정의가 균일한가
        `depth_ok`    ↔ `start` 를 이력이 덮는가
        `lag_known`   ↔ ★가격은 언제나 True★ — 장 마감으로 확정되고 공표지연이
                        없다. 매크로 계열의 "공표 시각이 관측기간 이후인가" 에
                        해당하는 문제가 가격에는 존재하지 않는다.
        `has_source`  ↔ 요청한 티커에 행이 있는가

    ★왜 정의 균일성이 `has_vintage` 에 들어가나★ 두 조건은 같은 질문의 두 면이다 —
    *"이 계열이 기업행위에 일관된 하나의 값인가."* 원주가와 수정주가가 섞인 계열은
    모든 행에 `adj_close` 가 있어도 그 조건을 만족하지 않는다. 새 등급도 새 임계값도
    만들지 않고 기존 전부-아니면-전무 계약을 그대로 쓴다.

    ★단, `reason` 은 어느 조건이 깨졌는지 이름으로 구분한다★ 둘을 한 문장으로
    뭉치면 고치는 사람이 어디를 봐야 할지 알 수 없다.

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
    # ★정의가 섞인 티커가 하나라도 있으면 부적격★ 같은 전부-아니면-전무 계약.
    basis_uniform = has_source and not cov["mixed_basis_tickers"]
    depth_ok = (not start) or (cov["earliest"] is not None
                               and cov["earliest"] <= str(start))

    usage = derive_usage(has_vintage=all_adjusted and basis_uniform,
                         depth_ok=depth_ok, lag_known=True,
                         has_source=has_source)

    if usage is ResearchUsage.BACKTEST_ELIGIBLE:
        reason = None
    elif not has_source:
        reason = ("요청한 티커에 가격 행이 없습니다"
                  + (f" (없음: {', '.join(cov['missing_tickers'][:5])})"
                     if cov["missing_tickers"] else ""))
    else:
        # ★사유를 뭉치지 않는다★ 각 조건에 그것을 고칠 단서를 붙인다.
        bits: list[str] = []
        if not all_adjusted:
            bits.append("수정주가 전량 — 미조정 티커: "
                        + ", ".join(cov["unadjusted_tickers"][:5]))
        if not basis_uniform:
            bits.append("가격 정의 균일 — 원주가·수정주가 혼합 티커: "
                        + ", ".join(cov["mixed_basis_tickers"][:5]))
        if not depth_ok:
            bits.append(f"이력 길이 — 최초 관측 {cov['earliest']} > 요청 {start}")
        reason = "충족되지 않은 조건: " + " · ".join(bits)
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


def adj_status_of(ticker: str, *, engine=None) -> str | None:
    """티커 하나의 네 상태 중 하나, **또는 판정 불가면 `None`**.

    `ohlcv_loader` 가 `df.attrs["adj_status"]` 에 실을 값이다.

    ★이전 판은 조회 실패도 `missing` 으로 냈다 — 그것을 고친다.★
    `missing` 은 "`daily_prices` 에 행이 하나도 없습니다" 라는 **판단**이다.
    커버리지 리포트 자체를 얻지 못한 경우(DB 없음·쿼리 실패)에 그 값을 내면
    하지 않은 진술이 보고서에 실린다.

    ★실제로 그렇게 나갔다★ — 0단계에서 목업 백테스트를 눈으로 확인하니 DB 없는
    실행의 진단이 "수정주가 아님(91종목) — 000100, 000270, …" 이었다. 그 91종목에
    대해 이 시스템은 아무것도 읽지 못했는데, 화면에는 확정된 결함으로 나갔다.
    미상 ≠ 0 · 미검증 ≠ 검증 · 미적재 ≠ 제공자 미지원 과 같은 부류다.

    Returns:
        `STATES` 중 하나, 또는 리포트를 얻지 못했으면 `None`.
        ★리포트를 얻었는데 그 티커가 없으면 그것은 진짜 `missing` 이다.★
    """
    cov = adj_close_coverage([ticker], engine=engine)
    if not cov.get("available"):
        return None
    return cov["by_ticker"].get(str(ticker), STATE_MISSING)


# ══════════════════════════════════════════════════════════════════════════
# 실행 단위 롤업 — ★백테스트가 실제로 로드한 프레임의 라벨을 센다★
# ══════════════════════════════════════════════════════════════════════════
#: 라벨이 **아예 없는** 티커. ★`STATES` 의 다섯째가 아니다★ — `STATES` 는 배타
#: 분류이고 그 넷은 전부 *DB 를 읽고 내린 판단*이다. `unlabeled` 은 판단이 아니라
#: **판단이 없음**이다(태깅 실패, `attrs` 유실, 로더를 안 거친 프레임).
#:
#: ★왜 `missing` 에 합치지 않나★ `missing` 은 "`daily_prices` 에 행이 하나도
#: 없다" 는 진술이다. DB 를 못 읽은 실행을 그 칸에 세면, 하지 않은 진술이 보고서에
#: 실린다 — "이 종목들은 데이터가 없습니다" 라고.
ROLLUP_UNLABELED = "unlabeled"

#: 사유에 실을 종목 이름 개수. `price_usage` 의 `[:5]` 와 같은 값이다.
_ROLLUP_SAMPLE_CAP = 5


def _sample(names: list[str]) -> list[str]:
    """★결정론적 표본★ — 가장 작은 것부터. 개수는 따로(정확하게) 보고한다."""
    return sorted(names)[:_ROLLUP_SAMPLE_CAP]


def basis_rollup(basis_by_ticker: dict[str, str | None],
                 adj_by_ticker: dict[str, str | None]) -> dict[str, Any] | None:
    """실행 하나의 **가격 정의 상태**. ★순수 함수 — DB 를 보지 않는다★

    입력은 `ohlcv_loader._tag` 가 프레임에 붙여 둔 두 라벨의 티커별 맵이다.
    로더가 티커마다 이미 `adj_status_of()` / `adj_close_coverage()` 를 부르므로
    **값은 이미 지불됐다** — 여기서는 세기만 하고 왕복을 늘리지 않는다.

    ★등급 규칙을 새로 만들지 않는다★ 판정은 `price_usage()` 와 같은
    **전부-아니면-전무** 계약이다: 모든 티커가 `adjusted` 이고 **그리고** 정의가
    섞이지 않았을 때만 깨끗하다.

    세 상태:
        `ok`        전부 라벨이 있고 전부 `adjusted` 이며 `mixed` 가 없다
        `degraded`  ★관측된★ 결함이 있다(`mixed`·`chain_broken`·`raw`·`missing`)
        `unknown`   관측된 결함은 없지만 **못 잰 것**이 있다(`unknown`·라벨 없음)

    ★`unknown` 은 절대 `ok` 로 세지 않는다★ — 미상은 통과가 아니다.
    ★관측된 결함이 미상보다 강한 진술이다★ — 둘 다 있으면 `degraded` 이고,
    미상은 사라지지 않고 개수와 사유에 남는다(강등이지 삭제가 아니다).

    Returns:
        프레임이 하나도 없으면 `None` — ★안 잰 것과 재서 0 인 것을 구별한다.★
        `{unit, tickers, basis, adj_status, uniform_adjusted_pct, adjusted_pct,
          mixed_tickers, unadjusted_tickers, unlabeled_tickers, state, reason,
          source, version, note}`
    """
    tickers = sorted(set(basis_by_ticker) | set(adj_by_ticker))
    if not tickers:
        return None

    basis_counts = dict.fromkeys(BASIS_CONSISTENCY, 0)
    basis_counts[ROLLUP_UNLABELED] = 0
    adj_counts = dict.fromkeys(STATES, 0)
    adj_counts[ROLLUP_UNLABELED] = 0

    mixed: list[str] = []
    unadjusted: list[str] = []
    unlabeled: list[str] = []

    for tk in tickers:
        b = basis_by_ticker.get(tk)
        a = adj_by_ticker.get(tk)
        # ★모르는 라벨을 아는 칸에 넣지 않는다★ 값이 없거나 어휘 밖이면 `unlabeled`.
        bk = str(b) if b in BASIS_CONSISTENCY else ROLLUP_UNLABELED
        ak = str(a) if a in STATES else ROLLUP_UNLABELED
        basis_counts[bk] += 1
        adj_counts[ak] += 1

        if ROLLUP_UNLABELED in (bk, ak):
            unlabeled.append(tk)
        if bk == BASIS_MIXED:
            mixed.append(tk)
        if ak in (STATE_CHAIN_BROKEN, STATE_RAW, STATE_MISSING):
            unadjusted.append(tk)

    total = len(tickers)
    known_defect = bool(mixed or unadjusted)
    unmeasured = bool(unlabeled) or basis_counts[BASIS_UNKNOWN] > 0

    if known_defect:
        state = "degraded"
    elif unmeasured:
        state = "unknown"
    else:
        state = "ok"

    # ★사유를 뭉치지 않는다★ 각 조건에 그것을 고칠 단서를 붙인다 —
    # `price_usage` 가 쓰는 형식 그대로.
    bits: list[str] = []
    if mixed:
        bits.append(f"가격 정의 혼합({len(mixed)}종목) — 원주가·수정주가가 한 계열에 "
                    f"섞였습니다: {', '.join(_sample(mixed))}")
    if unadjusted:
        bits.append(f"수정주가 아님({len(unadjusted)}종목) — {', '.join(_sample(unadjusted))}")
    if basis_counts[BASIS_UNKNOWN]:
        bits.append(f"정의 미기록({basis_counts[BASIS_UNKNOWN]}종목) — 레거시 행이라 "
                    "소급 추정하지 않습니다")
    if unlabeled:
        bits.append(f"라벨 없음({len(unlabeled)}종목) — 프레임에 품질 태그가 없습니다"
                    "(DB 를 못 읽었거나 로더를 거치지 않았습니다): "
                    f"{', '.join(_sample(unlabeled))}")

    return {
        # ★세는 단위를 밝힌다★ 봉도 행도 아니고 티커다.
        "unit": "ticker",
        "tickers": total,
        "basis": basis_counts,
        "adj_status": adj_counts,
        "uniform_adjusted_pct": round(
            basis_counts[BASIS_UNIFORM_ADJUSTED] / total * 100, 1),
        "adjusted_pct": round(adj_counts[STATE_ADJUSTED] / total * 100, 1),
        # ★이름을 낸다★ 개수만으로는 어느 종목을 고칠지 알 수 없다. 다만 이름은
        # **표본**이고(위 개수가 정확하다) 가장 작은 것부터 결정론적으로 고른다.
        "mixed_tickers": _sample(mixed),
        "unadjusted_tickers": _sample(unadjusted),
        "unlabeled_tickers": _sample(unlabeled),
        "state": state,
        "reason": " · ".join(bits) if bits else None,
        # ★`attrs` 는 권위가 아니라 힌트다★(`ohlcv_loader._tag` 독스트링).
        # 게이트를 세울 때는 `price_usage()` / `assert_prices_backtest_eligible()`
        # 을 직접 부를 것 — 이 롤업은 **보고**다.
        "source": "loader_attrs",
        "version": QUALITY_VERSION,
        "note": ("`state` 는 `price_usage()` 와 같은 전부-아니면-전무 계약입니다 — "
                 "한 종목이라도 수정주가가 아니거나 정의가 섞이면 깨끗하지 "
                 "않습니다. `unknown` 은 결함이 없다는 뜻이 아니라 **재지 못했다**는 "
                 "뜻입니다."),
    }


# ══════════════════════════════════════════════════════════════════════════
# 겹침 검증 — ★가정을 데이터가 판정하게 한다★
# ══════════════════════════════════════════════════════════════════════════
#: 구현 중 **실측**으로 확인한 사실 — `daily_prices` 의 PK 는 `(ticker, trade_date)`
#: 라서 한 티커가 같은 날짜에 원주가 행과 수정주가 행을 **함께 가질 수 없다**.
#: KIS 적재는 기존 KRX 행을 UPSERT 로 **덮는다**. 그때 남는 것이 이렇다:
#:
#:     close       ← KIS (수정주가로 요청한 값)
#:     return_1d   ← KRX (기업행위가 제거된 등락률) ★UPSERT 가 건드리지 않는다★
#:
#: ★즉 겹침은 행과 행 사이가 아니라 **한 행 안에** 있다.★ 그래서 검증은
#: "연속한 `close` 가 만드는 수익률이 기록된 `return_1d` 와 맞는가" 가 된다.
#: KIS 종가가 정말 수정주가라면 둘은 같아야 하고, 원주가라면 기업행위가 있던
#: 날에 **정확히 그 배수만큼** 어긋난다.
BASIS_RETURN_TOL = 5e-3   # 상대 허용오차(반올림·단위 차이 흡수). ★적격성 임계값이 아니다★

BASIS_MATCH = "consistent"        # 수익률 일치 — "KIS=수정주가" 가 뒷받침된다
BASIS_MISMATCH = "inconsistent"   # ★가정 중 하나가 틀렸다★


def basis_overlap_check(tickers: list[str] | None = None, *,
                        engine=None) -> dict[str, Any]:
    """`close` 가 정말 그 정의인지 **데이터에게** 묻는다.

    대상은 `price_basis='adjusted'` 이면서 `return_1d` 가 있는 행뿐이다 — 그 행이
    KIS 종가와 KRX 등락률을 **함께** 들고 있는 유일한 자리다(위 상수 주석 참조).

    ★`raw` 행에는 판정을 내리지 않는다★ 원주가 수익률이 등락률과 어긋나는 것은
    **기업행위가 있었다는 뜻**이지 정의가 틀렸다는 뜻이 아니다. 그 구분을 접으면
    분할이 있는 모든 티커가 거짓 양성으로 뜬다.

    ★이 함수는 아무것도 고치지 않는다★ 판정에 따라 KIS 행의 `adj_close` 를
    채울지는 **별개 결정**이고, 그 결정 전까지는 채우지 않는다.

    Returns:
        `{available, checked, verdict_by_ticker, consistent, inconsistent,
          tolerance, note, version}` — 비교할 행이 없으면 `{available: False, reason}`.
        ★재지 못한 것을 "일치" 로 적지 않는다.★
    """
    from sqlalchemy import text

    eng = _engine(engine)
    if eng is None:
        return _unavailable("DB 엔진이 없습니다 — 정의를 검증할 수 없습니다.")

    where = ""
    params: dict[str, Any] = {}
    if tickers:
        keys = [f"t{i}" for i in range(len(tickers))]
        where = " AND ticker IN (" + ", ".join(f":{k}" for k in keys) + ")"
        params.update(dict(zip(keys, [str(t) for t in tickers], strict=True)))
    try:
        with eng.connect() as conn:
            rows = conn.execute(text(
                "SELECT ticker, trade_date, close, return_1d, price_basis "
                "FROM daily_prices WHERE close IS NOT NULL" + where +
                " ORDER BY ticker, trade_date"), params).fetchall()
    except Exception as e:  # noqa: BLE001
        return _unavailable(f"daily_prices 조회 실패({type(e).__name__}) — {e}")

    per: dict[str, list[tuple]] = {}
    for ticker, trade_date, close, ret, basis in rows:
        per.setdefault(str(ticker), []).append(
            (str(trade_date)[:10], float(close), ret, basis))

    verdict: dict[str, dict[str, Any]] = {}
    for tk, series in per.items():
        checked = 0
        worst = 0.0
        worst_date = None
        for i in range(1, len(series)):
            _, prev_close, _, _ = series[i - 1]
            d, close, ret, basis = series[i]
            # ★수정주가로 **선언된** 행만 판정한다★ raw 행의 불일치는 기업행위다.
            if basis != "adjusted" or ret is None or not prev_close:
                continue
            implied = (close / prev_close - 1.0) * 100.0
            gap = abs(implied - float(ret)) / max(1.0, abs(float(ret)))
            checked += 1
            if gap > worst:
                worst, worst_date = gap, d
        if checked:
            verdict[tk] = {
                "verdict": BASIS_MATCH if worst <= BASIS_RETURN_TOL else BASIS_MISMATCH,
                "points": checked,
                "worst_gap": round(worst, 6),
                "worst_date": worst_date,
            }

    if not verdict:
        return _unavailable(
            "수정주가로 선언된 행 중 KRX 등락률(`return_1d`)을 함께 가진 행이 "
            "없습니다 — 두 정의가 한 행에서 만나야 비교할 수 있습니다. "
            "(KIS 적재가 기존 KRX 행을 덮은 적이 없으면 이 상태가 정상입니다.)")

    good = sorted(t for t, v in verdict.items() if v["verdict"] == BASIS_MATCH)
    bad = sorted(t for t, v in verdict.items() if v["verdict"] == BASIS_MISMATCH)
    return {
        "available": True,
        "checked": len(verdict),
        "verdict_by_ticker": verdict,
        "consistent": good,
        "inconsistent": bad,
        "tolerance": BASIS_RETURN_TOL,
        "note": ("연속 종가가 만드는 수익률이 KRX 등락률과 맞으면 KIS 종가가 "
                 "수정주가라는 것이 데이터로 뒷받침됩니다. 어긋나면 가정 중 "
                 "하나가 틀린 것이며, 그 경우 KIS 행의 `adj_close` 를 채워서는 "
                 "안 됩니다."),
        "version": QUALITY_VERSION,
    }
