"""매크로 인과 그래프 — 그레인저(Granger) 예측 인과 기반 방향성 엣지.

CIO 혁신과제 §2(Causal AI): 상관 히트맵을 넘어 '어느 변수가 어느 변수를 선행 예측하는가'를
방향성 노드-엣지로 시각화. DoWhy/CausalML 같은 구조적 인과 추론 대신 statsmodels의
그레인저 검정을 사용 — 정직 라벨: **예측적(Granger) 인과이며 구조적 인과가 아님**.

입력: macro_collector 시계열(월간, 72개월) — 지수형은 regime_axes.yoy_pct로 변환 후 검정.
출력: 노드(변수) + 엣지(from→to, 최적 lag, p-value) — p<0.10만.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# (key, label, transform) — 검정 대상 변수 (성장·물가·금리·시장)
_VARS = [
    ("KR_CPI", "KR 물가(YoY)", "yoy"),
    ("KR_10Y", "KR 국채10Y", "level"),
    ("KOSPI", "KOSPI(YoY)", "yoy"),
    ("USD_KRW", "원/달러", "level"),
    ("CPIAUCSL", "US CPI(YoY)", "yoy"),
    ("DGS10", "US 10Y", "level"),
    ("VIXCLS", "VIX", "level"),
    ("INDPRO", "US 산업생산(YoY)", "yoy"),
]
_MAX_LAG = 3
_P_CUT = 0.10
_MIN_OBS = 30


def _prep(series_map: dict) -> dict[str, list[float]]:
    from src.engine.regime_axes import yoy_pct
    out = {}
    for key, label, transform in _VARS:
        s = series_map.get(key)
        vals = list(getattr(s, "values", None) or [])
        if not vals:
            continue
        series = yoy_pct(vals) if transform == "yoy" else vals
        clean = [v for v in series if v is not None]
        if len(clean) >= _MIN_OBS:
            out[key] = clean
    return out


def granger_edges(series_map: dict) -> dict:
    """전 변수쌍 그레인저 검정 → 유의 엣지 목록. statsmodels 미가용/표본 부족은 정직 제외."""
    try:
        import numpy as np
        from statsmodels.tsa.stattools import grangercausalitytests
    except Exception:
        return {"available": False, "note": "statsmodels 미설치", "nodes": [], "edges": []}

    data = _prep(series_map)
    labels = {k: lb for k, lb, _ in _VARS}
    nodes = [{"id": k, "label": labels[k]} for k in data]
    edges = []
    keys = list(data)
    for src in keys:
        for dst in keys:
            if src == dst:
                continue
            n = min(len(data[src]), len(data[dst]))
            x = np.column_stack([data[dst][-n:], data[src][-n:]])   # [피설명, 설명]
            if n < _MIN_OBS:
                continue
            try:
                res = grangercausalitytests(x, maxlag=_MAX_LAG, verbose=False)
                best_lag, best_p = None, 1.0
                for lag, r in res.items():
                    p = r[0]["ssr_ftest"][1]
                    if p < best_p:
                        best_lag, best_p = lag, p
                if best_p < _P_CUT:
                    edges.append({"from": src, "to": dst, "from_label": labels[src],
                                  "to_label": labels[dst], "lag": int(best_lag),
                                  "p": round(float(best_p), 4)})
            except Exception as e:
                logger.debug(f"granger 실패 [{src}→{dst}]: {e}")
    edges.sort(key=lambda e: e["p"])
    return {"available": True, "nodes": nodes, "edges": edges[:24],
            "method": f"그레인저 검정 (maxlag {_MAX_LAG}, p<{_P_CUT}) — 예측적 인과",
            "note": "★그레인저 인과 = '선행 예측력'이며 구조적 인과가 아님 (정직 라벨)"}
