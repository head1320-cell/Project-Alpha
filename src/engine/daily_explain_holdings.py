"""보유의 하루를 설명한다 — ★가격 축을 총합으로 승격하지 않는다★ (AB3)
==============================================================================
설계: `docs/plans` AB · 어휘는 `src/domain/daily_explanation.py`

## ★이 어댑터에는 독립적인 총변동이 없다★

백테스트 행에는 `portfolio_return` 이 5효과와 **따로** 기록돼 있어 잔차가 실재한다.
보유 경로에는 그런 관측이 없다 — 이 저장소에 체결·예수금 기록이 없고
(`live_daily_pnl` 은 비어 있다) 가격에서 계산한 값 하나뿐이다.

그래서 ★가격 기여를 "총변동" 이라 부르면 잔차가 **구조적으로 0** 이 되고, 그 0 은
"완전히 설명했다" 로 읽힌다.★ 실제로는 배당·수수료·매매가 빠진 한 축을 총합으로
승격한 것뿐이다. 이 모듈은 잔차를 **계산 불가**로 낸다 — 0 이 아니다.

## 무엇을 재고 무엇을 못 재나

    price      ✔ 두 거래일의 종가 변동 × 비중. ★어느 기준가인지 선언한다★
    rebalance  그날의 매매를 **받았을 때만**. 안 받았으면 "없음" 이 아니라 "모름"
    fee        위와 같음
    dividend   ✘ 일별 배당락·지급일 데이터가 없다(연간 DPS 공시뿐)
    fx         ✘ 해외 직접보유 데이터가 없다

## ★가격 로더를 바꾸지 않는다★

`kis_portfolio_analyzer.load_returns` 는 `close`(원주가일 수도 수정주가일 수도
있다 — 적재 경로에 달렸다)를 읽는다. `adj_close` 소비자 변경은 CLAUDE.md §3 의
별도 승인 사항이므로 **무엇을 썼는지 선언**만 한다.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from src.domain.daily_explanation import (
    DRIVER_FEE,
    DRIVER_PRICE,
    DRIVER_REBALANCE,
    DRIVER_SET_HOLDING,
    RESIDUAL_UNEXPLAINED,
    UNMEASURABLE_DRIVERS,
    DailyExplanation,
    fold_price_basis,
)

logger = logging.getLogger("engine.daily_explain")

#: ★잔차가 0 이 아니라 **불가산**인 이유★ — 이 모듈의 요점이다.
#: ★사유 문자열은 대시(`—`)로 시작하거나 품지 않는다★ — 템플릿이 하나 붙이므로
#: 여기서도 붙이면 "… — … — …" 가 된다(눈으로 보고 잡았다).
#: ★마크다운도 쓰지 않는다★ — 이 문자열은 API 응답으로 나가고 렌더러를 가정할 수 없다.
_NO_INDEPENDENT_TOTAL = (
    "실제 총변동을 독립적으로 관측하지 못했습니다(체결·예수금 기록이 없습니다). "
    "위 가격 기여는 총합이 아니라 가격 축만의 값이라 견줄 대상이 없습니다")

#: 가격조차 못 쟀을 때. ★"위 가격 기여" 를 가리킬 수 없다 — 그것이 없다.★
_NOTHING_TO_COMPARE = (
    "가격 기여도 실제 총변동도 관측하지 못해 견줄 두 값이 모두 없습니다")

_NO_PRICE_ROW = ("요청일 부근에 거래일 가격 행이 없어 가격 기여를 잴 수 "
                 "없습니다")
_NO_TRADES_GIVEN = ("그날의 매매를 받지 못했습니다. 매매가 없었다는 뜻이 "
                    "아닙니다")
_NO_FEE_GIVEN = "매매를 몰라 수수료와 세금을 잴 수 없습니다"


def _load_returns(tickers: list[str], start: str, end: str):
    """가격 로더 seam. ★테스트가 여기를 잡는다★ — 로직은 DB 없이 잰다."""
    from src.kis_portfolio_analyzer import load_returns
    return load_returns(tickers, start, end)


def _price_basis_of(tickers: list[str], *, engine=None) -> dict | None:
    """티커들의 가격 정의 상태. ★판정 불가면 `None`★

    `price_quality` 가 이미 재 놓은 것을 접기만 한다 — 새 규칙을 만들지 않는다.
    """
    try:
        from src.data.price_quality import adj_close_coverage, basis_rollup
        cov = adj_close_coverage(list(tickers), engine=engine)
        if not cov.get("available"):
            return None
        roll = basis_rollup(cov.get("basis_by_ticker") or {},
                            cov.get("by_ticker") or {})
        if roll is None:
            return None
        return {"basis": fold_price_basis(roll.get("basis")),
                "state": roll.get("state"), "reason": roll.get("reason")}
    except Exception as e:  # noqa: BLE001 — 기준을 몰라도 설명은 나가야 한다
        logger.warning("가격 기준 판정 실패: %s: %s", type(e).__name__, e)
        return None


def _weighted_price_return(returns, holdings: dict[str, float]):
    """(기여 %p, 실제로 쓴 날짜). 행이 없으면 `(None, None)`."""
    if returns is None or getattr(returns, "empty", True):
        return None, None
    row = returns.iloc[-1]
    used = returns.index[-1]
    total_w = sum(abs(float(v)) for v in holdings.values())
    if total_w <= 0:
        return None, None
    acc, covered = 0.0, 0.0
    for code, w in holdings.items():
        if code not in returns.columns:
            continue
        r = row.get(code)
        if r is None or r != r:          # NaN
            continue
        acc += (float(w) / total_w) * float(r)
        covered += abs(float(w)) / total_w
    if covered <= 0:
        return None, None
    return round(acc * 100.0, 4), used


def explain_holdings_day(holdings: dict[str, float], *, as_of: str | None = None,
                         trades: list[dict] | None = None,
                         portfolio_value: float | None = None,
                         lookback_days: int = 10,
                         engine=None) -> DailyExplanation:
    """임의의 보유 + 하루 → 설명.

    Args:
        trades: 그날의 매매. ★`None`(못 받음)과 `[]`(없었음)은 다른 사실이다★
        portfolio_value: 수수료를 %p 로 환산할 분모. 없으면 수수료는 미상.
    """
    codes = [str(c) for c in holdings]
    end = date.fromisoformat(as_of) if as_of else date.today()
    start = end - timedelta(days=max(int(lookback_days), 3))

    returns = _load_returns(codes, start.isoformat(), end.isoformat())
    price_pct, used = _weighted_price_return(returns, {str(k): v
                                                       for k, v in holdings.items()})

    drivers: dict[str, float | None] = {DRIVER_PRICE: price_pct}
    missing: dict[str, str] = {}
    if price_pct is None:
        missing[DRIVER_PRICE] = _NO_PRICE_ROW

    # ★"매매 없음" 과 "매매를 못 받음" 을 가른다★
    if trades is None:
        drivers[DRIVER_REBALANCE] = None
        drivers[DRIVER_FEE] = None
        missing[DRIVER_REBALANCE] = _NO_TRADES_GIVEN
        missing[DRIVER_FEE] = _NO_FEE_GIVEN
    else:
        # 매매 자체는 비중을 옮길 뿐 그날 수익률에 직접 더해지지 않는다 —
        # ★그 값은 0 이고, 그것은 관측된 0 이다.★
        drivers[DRIVER_REBALANCE] = 0.0
        pv = float(portfolio_value or 0.0)
        fee = sum(float(t.get("fee_krw") or 0.0) for t in trades)
        if pv > 0:
            drivers[DRIVER_FEE] = round(-fee / pv * 100.0, 4)
        else:
            drivers[DRIVER_FEE] = None
            missing[DRIVER_FEE] = ("포트폴리오 평가액을 몰라 수수료를 비율로 "
                                   "환산할 수 없습니다")

    # ★언제나 미측정인 둘★ — 데이터가 없어서다.
    for name, why in UNMEASURABLE_DRIVERS.items():
        drivers[name] = None
        missing[name] = why

    basis = _price_basis_of(codes, engine=engine) or {"basis": "unknown",
                                                      "state": "unknown",
                                                      "reason": None}
    effective = used.date().isoformat() if used is not None else None
    # ★요청일과 실제로 쓴 날을 **둘 다** 남긴다★ — 휴장일이면 자연히 다르다
    # (`_load_clean_returns` 가 이미 쓰는 관용구).
    # ★출처는 추론이 아니라 사실이다★ — `load_returns` 는 `daily_prices` **한
    # 곳만** 읽는다(mock 폴백이 없다). 행이 돌아왔다면 그것은 DB 에서 온 것이고,
    # 안 돌아왔으면 출처를 말할 수 없다.
    basis = {**basis, "as_of_requested": as_of,
             "as_of_effective": effective,
             "source": "db" if effective else None}

    return DailyExplanation(
        as_of=effective or (as_of or ""),
        scope="portfolio", scope_id=f"요청 보유 {len(codes)}종",
        driver_set=DRIVER_SET_HOLDING,
        # ★독립 관측이 아니다★ — 가격 축과 같은 값이고, 그 사실을 잔차가 말한다.
        total_change_pct=price_pct,
        drivers=drivers, missing_drivers=missing,
        residual_pct=None, residual_kind=RESIDUAL_UNEXPLAINED,
        # ★가격을 못 쟀으면 "위 가격 기여" 를 가리킬 수 없다★
        residual_reason=(_NO_INDEPENDENT_TOTAL if price_pct is not None
                         else _NOTHING_TO_COMPARE),
        price_basis=basis,
    )
