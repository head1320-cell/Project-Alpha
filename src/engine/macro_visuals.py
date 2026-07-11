"""매크로 시각화 데이터 엔진 — 밸리AI 거시경제 분석의 장점 흡수 (데이터 현실 내 정직 구현).

① cycle_strips   — 지표×월 '사이클 히트 스트립' (밸리 사이클 분석): 지표별 변환 z의
                   18개월 타임라인 → 확장/둔화 국면이 색 띠로 한눈에.
② axis_history   — 성장/물가 축의 월별 '하위요인 분해' (밸리 하위요인 분석):
                   compute_axis_detail(back=k)로 지표별 기여 스택 시계열.
③ asset_strips   — 자산군 '가격 위치 백분위' 스트립 (밸리 자산군 밸류에이션의 시세 기반
                   정직 버전 — 멀티플 데이터 없이 가능한 범위 명시).
④ kr_us_compare  — KR vs US 지표 나란히 비교 (밸리 국가경제 분석의 2국 정직 버전 —
                   다국 지표 소스 없음).

전부 순수 함수(스냅샷 입력) — regime_axes의 변환·z 정의를 재사용해 국면 엔진과 일치.
"""

from __future__ import annotations

import logging

from src.engine.regime_axes import AXES, compute_axis_detail, yoy_pct, zscore_at

logger = logging.getLogger(__name__)

# 사이클 스트립 지표 (시장별) — (key, label, transform, sign)
_STRIP_DEFS = {
    "kr": [
        ("KR_LEADING_CYCLE", "경기선행 순환변동", "level", 1),
        ("KR_IP", "산업생산 YoY", "yoy", 1),
        ("KOSPI", "KOSPI YoY", "yoy", 1),
        ("KR_CPI", "CPI YoY", "yoy", 1),
        ("KR_10Y", "국고 10Y", "level", 1),
        ("USD_KRW", "원/달러", "level", 1),
    ],
    "us": [
        ("INDPRO", "산업생산 YoY", "yoy", 1),
        ("PAYEMS", "고용 YoY", "yoy", 1),
        ("UNRATE", "실업률(역)", "level", -1),
        ("CPIAUCSL", "CPI YoY", "yoy", 1),
        ("T10YIE", "기대인플레", "level", 1),
        ("DGS10", "미 10Y", "level", 1),
        ("VIXCLS", "VIX", "level", 1),
        ("BAMLH0A0HYM2", "HY 스프레드", "level", 1),
    ],
}


def _month_labels(series_map: dict, months: int) -> list[str]:
    """대표 시리즈의 timestamps 마지막 months개 (없으면 T-k 표기)."""
    for s in series_map.values():
        ts = list(getattr(s, "timestamps", None) or [])
        if len(ts) >= months:
            return [str(t)[:7] for t in ts[-months:]]
    return [f"T-{months - 1 - k}" for k in range(months)]


def cycle_strips(series_map: dict, market: str = "kr", months: int = 18) -> dict:
    """지표×월 변환 z 그리드 — 색 스트립 타임라인용. 미가용 셀 None(정직)."""
    rows = []
    for key, label, transform, sign in _STRIP_DEFS.get(market, _STRIP_DEFS["kr"]):
        s = series_map.get(key)
        vals = list(getattr(s, "values", None) or [])
        if not vals:
            continue
        series = yoy_pct(vals) if transform == "yoy" else vals
        cells = []
        for k in range(months - 1, -1, -1):     # 과거 → 현재
            z = zscore_at(series, back=k)
            cells.append(round(sign * z, 2) if z is not None else None)
        if any(c is not None for c in cells):
            rows.append({"key": key, "label": label, "transform": transform, "cells": cells})
    return {"market": market, "months": _month_labels(series_map, months), "indicators": rows,
            "note": "셀 = 각 시점의 역사(60개월) 대비 z — 지수형은 YoY 변환(국면 축과 동일 정의)"}


def axis_history(series_map: dict, market: str = "kr", months: int = 18) -> dict:
    """성장/물가 축 스코어의 월별 하위요인(지표별 기여) 분해 — 스택 차트용."""
    g_def, i_def = AXES.get(market, AXES["kr"])
    labels = _month_labels(series_map, months)
    points = []
    for idx, k in enumerate(range(months - 1, -1, -1)):
        g = compute_axis_detail(series_map, g_def, back=k)
        i = compute_axis_detail(series_map, i_def, back=k)
        points.append({
            "t": labels[idx],
            "growth": g["score"], "inflation": i["score"],
            "growth_parts": {c["key"]: c["contribution"] for c in g["components"]},
            "inflation_parts": {c["key"]: c["contribution"] for c in i["components"]},
        })
    return {"market": market, "points": points,
            "note": "축 = 지표별 기여의 합 (레벨 z 75% + 3개월 모멘텀 z 25%, 가중 재정규화)"}


# 자산군 스트립 대상 (미국 티커 기준 — KR은 etf_prices.resolve가 KR ETF로 매핑)
_ASSETS = [("SPY", "S&P500"), ("QQQ", "나스닥100"), ("EFA", "선진국(ex-US)"),
           ("TLT", "미 장기채"), ("IEF", "미 중기채"), ("HYG", "하이일드"),
           ("GLD", "금"), ("DBC", "원자재"), ("VNQ", "리츠"), ("BIL", "현금성")]


def _monthly_closes(ticker: str, market: str, n: int) -> list[float]:
    from src.data.etf_prices import monthly_closes
    return monthly_closes(ticker, market, n=n)


def asset_strips(market: str = "kr", months: int = 18, window: int = 60) -> dict:
    """자산군 가격 위치 백분위(트레일링 window개월 내) 스트립.

    ★정직★: 시세 기반 '가격 위치'이지 멀티플(PER 등) 밸류에이션이 아님 — 라벨 명시.
    percentile 높음 = 역사 범위 상단(고점권), 낮음 = 하단(저점권)."""
    assets = []
    for tk, label in _ASSETS:
        try:
            closes = _monthly_closes(tk, market, months + window + 2)
        except Exception:
            closes = []
        closes = [c for c in (closes or []) if c and c > 0]
        if len(closes) < window // 2:
            continue
        cells = []
        for k in range(months - 1, -1, -1):
            idx = len(closes) - 1 - k
            if idx < 8:
                cells.append(None)
                continue
            seg = closes[max(0, idx - window + 1):idx + 1]
            cur = closes[idx]
            below = sum(1 for x in seg if x <= cur) / len(seg)
            cells.append(round(below * 100, 0))
        if any(c is not None for c in cells):
            assets.append({"ticker": tk, "label": label, "cells": cells,
                           "now": cells[-1] if cells else None})
    return {"market": market, "months": months, "assets": assets,
            "note": "가격 위치 백분위 (시세 기반 · 트레일링 5년) — 멀티플 밸류에이션 아님(정직). "
                    "상단=역사 고점권 · 하단=저점권"}


# KR vs US 비교 (동일 변환으로 나란히) — (label, kr_key, us_key, transform, sign)
_COMPARE = [
    ("CPI (YoY z)", "KR_CPI", "CPIAUCSL", "yoy", 1),
    ("산업생산 (YoY z)", "KR_IP", "INDPRO", "yoy", 1),
    ("주가지수 (YoY z)", "KOSPI", None, "yoy", 1),        # 미국 주가지수 시리즈 미수집 — 정직 None
    ("10Y 금리 (레벨 z)", "KR_10Y", "DGS10", "level", 1),
    ("고용 (YoY z)", None, "PAYEMS", "yoy", 1),
    ("실업률 (레벨 z·역)", None, "UNRATE", "level", -1),
]


def kr_us_compare(series_map: dict) -> dict:
    """KR vs US 핵심 지표 z 나란히 — 밸리 '국가경제 분석'의 2국 정직 버전."""
    def _z(key, transform, sign):
        if not key:
            return None
        s = series_map.get(key)
        vals = list(getattr(s, "values", None) or [])
        if not vals:
            return None
        series = yoy_pct(vals) if transform == "yoy" else vals
        z = zscore_at(series)
        return round(sign * z, 2) if z is not None else None

    rows = []
    for label, kr_key, us_key, transform, sign in _COMPARE:
        kr, us = _z(kr_key, transform, sign), _z(us_key, transform, sign)
        if kr is None and us is None:
            continue
        rows.append({"label": label, "kr": kr, "us": us,
                     "gap": round(kr - us, 2) if (kr is not None and us is not None) else None})
    return {"rows": rows,
            "note": "동일 변환(z) 기준 양국 비교 — 다국(중·일·유럽) 지표는 수집 소스 미연동(정직 범위)"}
