"""
체결가 결정 계층 (Fill Price Resolver)
=====================================
백테스트에서 "어느 가격에 체결할 것인가"를 추상화한다.

젠포트처럼 다양한 체결가 유형을 지원:
  · 종가/시가류: 당일종가, 당일시초가, 전일종가, 전일시초가, 전일고가, 전일저가
  · 피벗류: 피벗 기준선, 1·2차 지지선, 1·2차 저항선 (전일 H/L/C로 계산)
  · TWAP: 분봉 평균 (현재는 종가 근사 — 분봉 API 연결 시 실데이터)

설계 원칙:
  - 입력은 OHLCV 시계열(과거→현재 순)과 현재 시점 인덱스
  - KIS 일봉(OHLC)만으로 종가류·피벗류는 실데이터 계산 가능
  - DEFAULT("close")는 기존 백테스트 동작과 정확히 동일 (회귀 불변)

모든 함수는 순수 함수 — 가격 시계열만 받아 float 반환. mock/실데이터 무관하게 동작.
"""

from __future__ import annotations

from enum import Enum


class FillPriceType(str, Enum):
    """체결가 유형."""
    # 종가/시가류
    CLOSE = "close"                  # 당일 종가 (기본 — 기존 동작)
    OPEN = "open"                    # 당일 시초가
    PREV_CLOSE = "prev_close"        # 전일 종가
    PREV_OPEN = "prev_open"          # 전일 시초가
    PREV_HIGH = "prev_high"          # 전일 고가
    PREV_LOW = "prev_low"            # 전일 저가
    # 피벗류 (전일 고/저/종으로 계산)
    PIVOT = "pivot"                  # 피벗 기준선 = (H+L+C)/3
    PIVOT_R1 = "pivot_r1"            # 1차 저항선 = 2*P - L
    PIVOT_R2 = "pivot_r2"            # 2차 저항선 = P + (H-L)
    PIVOT_S1 = "pivot_s1"            # 1차 지지선 = 2*P - H
    PIVOT_S2 = "pivot_s2"            # 2차 지지선 = P - (H-L)
    # 평균류
    TWAP = "twap"                    # 분봉 시간가중평균 (분봉 연결 전엔 OHLC 근사)
    VWAP = "vwap"                    # 거래량가중평균 (체결량 연결 전엔 (H+L+C)/3 근사)


# 체결가 유형 메타 (UI 드롭다운용)
FILL_PRICE_LABELS: dict[str, str] = {
    "close": "당일 종가",
    "open": "당일 시초가",
    "prev_close": "전일 종가",
    "prev_open": "전일 시초가",
    "prev_high": "전일 고가",
    "prev_low": "전일 저가",
    "pivot": "피벗 기준선",
    "pivot_r1": "피벗 1차 저항선",
    "pivot_r2": "피벗 2차 저항선",
    "pivot_s1": "피벗 1차 지지선",
    "pivot_s2": "피벗 2차 지지선",
    "twap": "TWAP (시간가중)",
    "vwap": "VWAP (거래량가중)",
}

# 카테고리 (UI 그룹화)
FILL_PRICE_GROUPS = [
    {"id": "current", "label": "당일", "types": ["close", "open"]},
    {"id": "prev", "label": "전일", "types": ["prev_close", "prev_open", "prev_high", "prev_low"]},
    {"id": "pivot", "label": "피벗", "types": ["pivot", "pivot_r1", "pivot_r2", "pivot_s1", "pivot_s2"]},
    {"id": "avg", "label": "평균가", "types": ["twap", "vwap"]},
]


def _pivot_base(h: float, low: float, c: float) -> float:
    """피벗 기준선 = (고가 + 저가 + 종가) / 3."""
    return (h + low + c) / 3.0


def resolve_fill_price(
    price_type: str,
    today_open: float, today_high: float, today_low: float, today_close: float,
    prev_open: float | None = None, prev_high: float | None = None,
    prev_low: float | None = None, prev_close: float | None = None,
) -> float:
    """체결가 유형 + 당일/전일 OHLC → 체결 기준가.

    분할매수/슬리피지 적용 전의 '기준 가격'을 반환한다.
    데이터 부족(전일 없음 등) 시 당일 종가로 안전 폴백.
    """
    t = price_type or "close"

    # 종가/시가류
    if t == "close":
        return today_close
    if t == "open":
        return today_open
    if t == "prev_close":
        return prev_close if prev_close is not None else today_close
    if t == "prev_open":
        return prev_open if prev_open is not None else today_open
    if t == "prev_high":
        return prev_high if prev_high is not None else today_high
    if t == "prev_low":
        return prev_low if prev_low is not None else today_low

    # 피벗류 — 전일 H/L/C 필요
    if t in ("pivot", "pivot_r1", "pivot_r2", "pivot_s1", "pivot_s2"):
        if prev_high is None or prev_low is None or prev_close is None:
            return today_close  # 전일 데이터 없으면 폴백
        p = _pivot_base(prev_high, prev_low, prev_close)
        if t == "pivot":
            return p
        if t == "pivot_r1":
            return 2 * p - prev_low
        if t == "pivot_r2":
            return p + (prev_high - prev_low)
        if t == "pivot_s1":
            return 2 * p - prev_high
        if t == "pivot_s2":
            return p - (prev_high - prev_low)

    # 평균류 (분봉/체결량 연결 전 근사)
    if t == "twap":
        # 분봉 미연결 → 당일 (시+고+저+종)/4 근사
        return (today_open + today_high + today_low + today_close) / 4.0
    if t == "vwap":
        # 체결량 미연결 → (고+저+종)/3 근사
        return (today_high + today_low + today_close) / 3.0

    return today_close


def resolve_from_slice(price_type: str, df_slice, has_today: bool = True) -> float:
    """OHLCV 슬라이스(과거→현재)에서 체결가 계산.

    df_slice: 'open','high','low','close' 컬럼을 가진 DataFrame (과거→현재 정렬)
    has_today: 마지막 행이 '당일'인지 (True) — 보통 True
    """
    if df_slice is None or len(df_slice) == 0:
        return 0.0
    last = df_slice.iloc[-1]
    prev = df_slice.iloc[-2] if len(df_slice) >= 2 else None

    return resolve_fill_price(
        price_type,
        today_open=float(last["open"]), today_high=float(last["high"]),
        today_low=float(last["low"]), today_close=float(last["close"]),
        prev_open=float(prev["open"]) if prev is not None else None,
        prev_high=float(prev["high"]) if prev is not None else None,
        prev_low=float(prev["low"]) if prev is not None else None,
        prev_close=float(prev["close"]) if prev is not None else None,
    )
