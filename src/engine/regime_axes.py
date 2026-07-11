"""국면 축 단일 진실 공급원 — 변환(YoY)·z·모멘텀 블렌드·축 분해·사분면·확률.

지수형 시리즈(CPI/산업생산/GDP/고용/KOSPI)는 레벨이 항상 우상향이라 레벨 z-score가
구조적으로 +로 고정된다(과거 'Stagflation 고정' 버그의 원인). 여기서 YoY %로 변환 후
z-score한다. collector/차트는 원시값을 유지 — 변환은 이 모듈에서만 수행한다.

★ CIO 리팩토링 반영 ★
· 축 = (1-w)·z(레벨/YoY) + w·z(3개월 모멘텀) — 레벨이 높아도 급감속이면 축이 낮아짐.
  ("CPI 레벨 z +2.17σ vs 물가 축 -0.28 모순"의 해소: 축 입력은 YoY z이며, 지표별 분해를
  compute_axis_detail로 투명 공개 — UI가 레벨 z를 축 입력인 것처럼 보여주던 표시 불일치 제거)
· 사분면 명명 통일(전 모듈 공용): Goldilocks(성장↑물가↓) / Reflation(성장↑물가↑) /
  Stagflation(성장↓물가↑) / Disinflation(성장↓물가↓).
  'Deflation' 제거 — 물가 z<0은 '상승 둔화(디스인플레이션)'이지 물가 하락이 아님.
· quadrant_probs: 축 불확실성(se) 기반 사분면 확률(합=1) — 정적 신뢰도% 대체.

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

# 레벨 vs 모멘텀 블렌드 — 표준 관행: 레벨이 주, 3개월 변화(방향)가 보조
MOMENTUM_WEIGHT = 0.25
MOMENTUM_LAG = 3            # 개월
SE_FLOOR = 0.25             # 축 불확실성 하한 (지표 1~2개일 때 과신 방지)

QUADRANTS = ("Goldilocks", "Reflation", "Stagflation", "Disinflation")


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


def _momentum_series(vals, lag: int = MOMENTUM_LAG) -> list:
    """변환 시계열의 lag개월 차분 — 모멘텀(가속/감속) 원천."""
    out = []
    for i, v in enumerate(vals):
        prev = vals[i - lag] if i >= lag else None
        out.append((v - prev) if (v is not None and prev is not None) else None)
    return out


def compute_axis_detail(series_map: dict, axis_def: list, back: int = 0,
                        momentum_weight: float = MOMENTUM_WEIGHT) -> dict:
    """축 스코어 + 지표별 분해 + 불확실성(se).

    지표 기여 = sign·weight·[(1-mw)·z(변환 레벨) + mw·z(3개월 모멘텀)] / Σweight.
    미가용/표본 부족 지표는 제외하고 가중 재정규화(허위값 금지).
    se = 지표 기여 스코어의 가중 표준편차/√n (지표 간 불일치가 클수록 불확실) — 하한 SE_FLOOR.
    """
    comps: list[dict] = []
    for key, transform, sign, weight in axis_def:
        s = series_map.get(key)
        vals = list(getattr(s, "values", None) or [])
        if not vals:
            continue
        series = yoy_pct(vals) if transform == "yoy" else vals
        z = zscore_at(series, back=back)
        if z is None:
            continue
        z_mom = zscore_at(_momentum_series(series), back=back)
        blend = (1 - momentum_weight) * z + momentum_weight * (z_mom if z_mom is not None else z)
        comps.append({"key": key, "transform": transform, "sign": sign, "weight": weight,
                      "z": round(z, 3), "z_mom": round(z_mom, 3) if z_mom is not None else None,
                      "blend": sign * blend})
    wsum = sum(c["weight"] for c in comps)
    if wsum <= 0:
        return {"score": 0.0, "se": SE_FLOOR, "components": []}
    score = sum(c["blend"] * c["weight"] for c in comps) / wsum
    for c in comps:
        c["contribution"] = round(c["blend"] * c["weight"] / wsum, 4)
        c["blend"] = round(c["blend"], 3)
    # 지표 간 분산 → 불확실성 (n=1이면 하한)
    if len(comps) >= 2:
        var = sum(c["weight"] * (c["blend"] - score) ** 2 for c in comps) / wsum
        se = math.sqrt(var) / math.sqrt(len(comps))
    else:
        se = SE_FLOOR
    return {"score": round(score, 4), "se": round(max(SE_FLOOR, se), 4), "components": comps}


def compute_axis(series_map: dict, axis_def: list, back: int = 0) -> float:
    """가중 z 평균 (하위호환 래퍼 — compute_axis_detail의 score)."""
    return compute_axis_detail(series_map, axis_def, back=back)["score"]


def quadrant(growth: float, inflation: float) -> str:
    """성장×물가 사분면 — 전 모듈 공용 명칭 (Deflation 아님 — Disinflation)."""
    if growth >= 0:
        return "Reflation" if inflation >= 0 else "Goldilocks"
    return "Stagflation" if inflation >= 0 else "Disinflation"


def _phi(x: float) -> float:
    """표준정규 CDF."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def quadrant_probs(growth: float, inflation: float,
                   se_g: float = SE_FLOOR, se_i: float = SE_FLOOR) -> dict:
    """축 불확실성 기반 사분면 확률 (독립 가우시안 가정, 합=1).

    P(성장>0)=Φ(g/se_g), P(물가>0)=Φ(i/se_i) → 4사분면 곱.
    정적 '신뢰도 80%' 텍스트를 확률 분포로 대체(CIO 확률적 비중 제시)."""
    pg = _phi(growth / max(1e-9, se_g))
    pi = _phi(inflation / max(1e-9, se_i))
    return {"Reflation": round(pg * pi, 4), "Goldilocks": round(pg * (1 - pi), 4),
            "Stagflation": round((1 - pg) * pi, 4), "Disinflation": round((1 - pg) * (1 - pi), 4)}
