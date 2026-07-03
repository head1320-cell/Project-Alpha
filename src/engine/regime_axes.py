"""국면 축 단일 진실 공급원 — 변환(YoY)·z·축 정의·사분면.

지수형 시리즈(CPI/산업생산/GDP/고용/KOSPI)는 레벨이 항상 우상향이라 레벨 z-score가
구조적으로 +로 고정된다(과거 'Stagflation 고정' 버그의 원인). 여기서 YoY %로 변환 후
z-score한다. collector/차트는 원시값을 유지 — 변환은 이 모듈에서만 수행한다.

축 구성은 성장×물가 2×2 (Bridgewater 4국면 / 경기사이클 분석의 표준 관행):
  성장 = 실물 활동(산업생산·고용·GDP·경기선행) YoY의 역사 대비 z
  물가 = CPI YoY z + 기대인플레이션 레벨 z
regime_analyzer(헤더)와 macro_analytics(국면 궤적)가 이 정의를 공유해 서로 일치한다.
"""
from __future__ import annotations

import math

# (series_key, transform, sign, weight) — transform: "yoy"(지수→전년比%) | "level"
US_GROWTH = [("INDPRO", "yoy", 1, 0.35), ("PAYEMS", "yoy", 1, 0.25),
             ("UNRATE", "level", -1, 0.20), ("GDPC1", "yoy", 1, 0.20)]
US_INFLATION = [("CPIAUCSL", "yoy", 1, 0.60), ("T10YIE", "level", 1, 0.40)]
KR_GROWTH = [("KR_LEADING_CYCLE", "level", 1, 0.40), ("KR_IP", "yoy", 1, 0.30),
             ("KOSPI", "yoy", 1, 0.30)]
KR_INFLATION = [("KR_CPI", "yoy", 1, 0.70), ("T10YIE", "level", 1, 0.30)]

AXES = {"kr": (KR_GROWTH, KR_INFLATION), "us": (US_GROWTH, US_INFLATION)}


def yoy_pct(values, lag: int = 12) -> list:
    """지수 레벨 시계열 → 전년동기比 % 시계열 (선두 lag개는 None)."""
    out = []
    for i, v in enumerate(values):
        prev = values[i - lag] if i >= lag else None
        ok = v is not None and prev is not None and prev > 0
        out.append((v / prev - 1) * 100 if ok else None)
    return out


def zscore_at(vals, back: int = 0, window: int = 60) -> float | None:
    """시계열의 -1-back 시점 값의 z (직전 window 표본 기준). 표본<8이면 None."""
    idx = len(vals) - 1 - back
    if idx < 0:
        return None
    x = vals[idx]
    if x is None:
        return None
    seg = [v for v in vals[max(0, idx - window + 1):idx + 1] if v is not None]
    if len(seg) < 8:
        return None
    mean = sum(seg) / len(seg)
    var = sum((v - mean) ** 2 for v in seg) / len(seg)
    std = math.sqrt(var)
    return (x - mean) / std if std > 1e-12 else 0.0


def compute_axis(series_map: dict, axis_def: list, back: int = 0) -> float:
    """가중 z 평균. 시리즈 미가용/표본 부족은 제외하고 가중치 재정규화(허위값 금지)."""
    acc, wsum = 0.0, 0.0
    for key, transform, sign, weight in axis_def:
        s = series_map.get(key)
        vals = list(getattr(s, "values", None) or [])
        if not vals:
            continue
        series = yoy_pct(vals) if transform == "yoy" else vals
        z = zscore_at(series, back=back)
        if z is None:
            continue
        acc += sign * z * weight
        wsum += weight
    return acc / wsum if wsum > 0 else 0.0


def quadrant(growth: float, inflation: float) -> str:
    """성장×물가 사분면 — 전 모듈 공용 명칭."""
    if growth >= 0:
        return "Reflation" if inflation >= 0 else "Goldilocks"
    return "Stagflation" if inflation >= 0 else "Deflation"
