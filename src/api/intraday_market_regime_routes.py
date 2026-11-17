"""시장 국면(일)의 문 (설계 2026-11-17 §2 · 구현 계획 §7.1 · K1).

- `GET /market-regime?index=KOSPI|KOSDAQ&k=2..4&from&to` — 판정 기간의 거래일마다 국면 소속 확률(읽기만 · 쓰기 0).

지수 일봉은 `ohlcv_loader.load_index_daily` 한 길로 읽는다 — mock 게이트면 기존 길(저장소 → 합성), ★운영은 저장소만★(증권사 호출 0).
운영의 지수 일봉은 KRX 적재(`krx_ingest.backfill_index`)가 `daily_prices` 에 종목 'KOSPI' · 'KOSDAQ' 로 넣은 행이다 —
증권사 클라이언트의 일봉 조회는 국내주식 기간별시세(시장 코드 J)라 지수를 주지 않는다(감사 · 2026-11-17).
적합 창(750거래일)과 특징 창(20거래일)을 위해 판정 시작일의 `HISTORY_CALENDAR_DAYS` 앞부터 읽는다 — 적재가 그만큼 덮지 못하면
엔진이 그 달을 미상 + 사유로 두고, 이 문은 로더의 덮음 사유를 그대로 싣는다(조용히 짧은 창으로 적합하지 않는다).
운영에서 출처가 합성이면 국면을 내지 않는다(빈 값 + 사유 — 로더가 이미 막지만 문이 한 번 더 본다). mock 이면 등급 E0 과 화면 맨 위 알림.

★도구는 국면 수를 고르지 않는다★ — k 는 받은 그대로이고 BIC 는 나란히 적을 뿐이다. ★예측이 아니다★ — 그날의 확률은 전 거래일 종가까지로 계산한다.
계산은 `src/engine/market_regime`, 이 문은 ⑴ 로그인 ⑵ 인자와 기간 상한 ⑶ 읽기와 출처 등급 ⑷ 게이트만 맡는다. 주문 경로 · 증권사 클라이언트를 들이지 않는다.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.auth import require_login
from src.data.mock_gate import mock_allowed
from src.data.ohlcv_loader import load_index_daily
from src.engine import market_regime as mr

logger = logging.getLogger("api.intraday.market_regime")
router = APIRouter(prefix="/api/v1/intraday", tags=["intraday"])

INDEXES = {"KOSPI": "코스피", "KOSDAQ": "코스닥"}
MAX_RANGE_DAYS = 366
#: 적합 창 750 + 특징 창 20 + 여유 40 = 810거래일. 한국 거래일은 한 해 약 248일이라 810 × 365 / 248 ≈ 1,192 달력일 → 1,250(공휴일 여유).
HISTORY_CALENDAR_DAYS = 1250
GRADE_REAL, GRADE_SYNTHETIC = "E3", "E0"
GRADE_UNKNOWN = "일봉의 출처 표시가 없어 등급을 매기지 않았습니다."

REASONS = {
    "bad_range": "시작일이 종료일보다 늦습니다.",
    "range_too_long": f"기간은 {MAX_RANGE_DAYS}일까지 볼 수 있습니다.",
}
EMPTY = {
    "not_loaded": "이 기간의 {name} 일봉이 적재돼 있지 않습니다.",
    "synthetic_in_production": "운영에서는 합성 지수 일봉으로 국면을 계산하지 않습니다.",
    "bad_dates": "같은 날짜의 일봉이 둘 이상 있어 계산하지 않았습니다.",
    "store_error": "가격 저장소를 읽지 못해 계산하지 않았습니다. 적재가 없다는 뜻이 아닙니다.",
}
#: 답에 늘 싣는 사실 — 이 국면이 무엇이 아닌지. 화면은 이 글을 그대로 보인다.
NOTES = (
    "국면은 지수의 20거래일 수익과 실현 변동성이 닮은 날끼리 묶은 이름표입니다. 다음 날의 국면이나 수익을 예측한다는 뜻이 아닙니다.",
    "국면 번호는 변동성이 낮은 것부터 매겼습니다. 번호에 다른 뜻은 없습니다.",
    "그날의 확률은 전 거래일 종가까지의 값으로 계산합니다. 그날 종가는 쓰지 않습니다.",
    "적합은 달마다 그달 첫 거래일 전의 750거래일로 다시 합니다. 750거래일이 모자라는 달은 계산하지 않습니다. 같은 종가에서는 같은 날이 언제 다시 봐도 같은 값입니다.",
    "BIC 는 같은 자료에서 국면 수 2 · 3 · 4 를 나란히 적은 것입니다. 국면 수를 고르지 않습니다.",
    "난수 시드 일치도가 높다고 국면이 있다는 뜻이 아닙니다. 국면이 없는 합성 자료(변동성이 일정한 걸음)에서도 일치도가 1 에 가깝게 나온 경우가 있었습니다(잰 값).",
)


def _refuse(code: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "reason": REASONS[code], **extra})


def _limits() -> dict[str, Any]:
    return {"range_days": MAX_RANGE_DAYS, "k": list(mr.K_RANGE), "fit_days": mr.FIT_DAYS, "window": mr.WINDOW,
            "seeds": mr.SEEDS, "history_calendar_days": HISTORY_CALENDAR_DAYS,
            "indexes": [{"code": c, "name": n} for c, n in INDEXES.items()]}


def _grade(source: str | None) -> tuple[str | None, str | None]:
    if source == "mock":
        return GRADE_SYNTHETIC, None
    if source == "db":                         # 운영의 지수 일봉은 KRX 적재뿐(증권사 경로 없음)
        return GRADE_REAL, None
    return None, GRADE_UNKNOWN


@router.get("/market-regime/limits")
def market_regime_limits(user: str = Depends(require_login)) -> dict[str, Any]:
    """상한 — 상수뿐(읽기 · 외부 호출 0). 화면의 국면 수 고르기 · 지수 목록 · 상한 줄이 이 답으로만 그린다."""
    return _limits()


@router.get("/market-regime")
def market_regime(index: Literal["KOSPI", "KOSDAQ"] = Query(...),
                  k: int = Query(..., ge=mr.K_RANGE[0], le=mr.K_RANGE[1]),
                  from_: date = Query(..., alias="from"),
                  to: date = Query(...),
                  user: str = Depends(require_login)) -> dict[str, Any]:
    if from_ > to:
        raise _refuse("bad_range")
    span = (to - from_).days + 1
    if span > MAX_RANGE_DAYS:
        raise _refuse("range_too_long", limit=MAX_RANGE_DAYS, days=span)

    mock = mock_allowed()
    start, end = from_.isoformat(), to.isoformat()
    df = load_index_daily(index, (from_ - timedelta(days=HISTORY_CALENDAR_DAYS)).isoformat(), end)
    attrs = dict(getattr(df, "attrs", {}) or {})
    source = attrs.get("source")
    grade, grade_reason = _grade(source)
    shared: dict[str, Any] = {
        "index": index, "name": INDEXES[index], "k": k, "from": start, "to": end, "mock": mock,
        "coverage": {"ok": attrs.get("coverage_ok"), "reason": attrs.get("coverage_reason")},
        "notes": list(NOTES), "limits": _limits(),
    }
    nothing = {"days": [], "states": [], "transitions": None, "bic": None, "agreement": None, "fit": None,
               "grade": None, "grade_reason": None, "source": source}

    if attrs.get("db_error"):
        logger.warning("지수 일봉 저장소 조회 실패 — 국면을 내지 않는다(%s)", index)
        return {**shared, **nothing, "empty": {"reason": "store_error", "message": EMPTY["store_error"]}}
    if source == "mock" and not mock:
        logger.warning("운영에서 합성 지수 일봉이 문까지 왔다 — 국면을 내지 않는다(%s)", index)
        return {**shared, **nothing, "empty": {"reason": "synthetic_in_production", "message": EMPTY["synthetic_in_production"]}}
    if df is None or df.empty or "close" not in df.columns:
        return {**shared, **nothing, "empty": {"reason": "not_loaded", "message": EMPTY["not_loaded"].format(name=INDEXES[index])}}

    df = df.sort_index()
    dates = [d.strftime("%Y-%m-%d") for d in df.index]
    if len(set(dates)) != len(dates):
        return {**shared, **nothing, "empty": {"reason": "bad_dates", "message": EMPTY["bad_dates"]}}
    if not any(start <= d <= end for d in dates):
        return {**shared, **nothing, "empty": {"reason": "not_loaded", "message": EMPTY["not_loaded"].format(name=INDEXES[index])}}

    closes = df["close"].to_numpy(dtype=float, na_value=np.nan)
    out = mr.regime_days(dates, closes, k=k, start=start, end=end)
    return {**shared, **out, "grade": grade, "grade_reason": grade_reason, "source": source, "empty": None}
