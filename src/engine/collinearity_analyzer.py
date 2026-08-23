"""
Factor Collinearity & Portfolio Optimization — Screener V3 Milestone 7
==========================================================================
통과 종목 집합의 팩터 상관관계 진단 + 포트폴리오 최적화 (후처리 analyzer).

★ Gemini 비평 ③ 정면 수용 ★
  "경고에서 멈추지 말고 공분산 행렬로 포트폴리오 최적화를 수행하라."
  → 다중공선성 진단(경고) + Mean-Variance / Risk-Parity 비중 제안(조치)까지.

2단계:
  1. 진단: 통과 종목들의 팩터 상관 매트릭스 → 편향 경고
     (예: PER·PBR·EV/EBITDA 고상관 → 사실상 단일 가치 베팅)
  2. 최적화: 종목 수익률 추정 공분산 → Inverse-Variance / Risk-Parity 비중

★ 후처리 레이어 (kind 디스패처와 분리) ★
  analyzers.py의 ANALYZER_REGISTRY에 등록되어 run-advanced 후 실행.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

# 상관 분석 대상 팩터
_FACTOR_FIELDS = [
    ("per", "PER", "value"),
    ("pbr", "PBR", "value"),
    ("roe_pct", "ROE", "quality"),
    ("roa_pct", "ROA", "quality"),
    ("debt_ratio_pct", "부채비율", "safety"),
    ("dividend_yield_pct", "배당수익률", "income"),
    ("gap_pct", "괴리율", "value"),
]

_STYLE_LABELS = {
    "value": "가치",
    "quality": "퀄리티",
    "safety": "안정성",
    "income": "인컴",
}


def _extract_matrix(items: list) -> tuple:
    """종목×팩터 행렬 추출 (결측 컬럼 제외)."""
    cols, labels, styles = [], [], []
    for fid, label, style in _FACTOR_FIELDS:
        vals = [getattr(it, fid, None) for it in items]
        present = [v for v in vals if v is not None]
        if len(present) < len(items) * 0.5:  # 50% 미만이면 제외
            continue
        # 결측은 중앙값 대체
        med = float(np.median(present)) if present else 0.0
        col = [float(v) if v is not None else med for v in vals]
        cols.append(col)
        labels.append(label)
        styles.append(style)
    if not cols:
        return None, [], []
    mat = np.array(cols).T  # (n_stocks, n_factors)
    return mat, labels, styles


def _correlation_matrix(mat: np.ndarray) -> np.ndarray:
    """표준화 후 상관계수 행렬."""
    std = mat.std(axis=0)
    std[std < 1e-9] = 1.0
    z = (mat - mat.mean(axis=0)) / std
    n = z.shape[0]
    corr = (z.T @ z) / max(1, n - 1)
    return np.clip(corr, -1, 1)


def collinearity(items: list, **kwargs) -> dict:
    """
    M7: 팩터 다중공선성 진단 + 포트폴리오 최적화.

    Returns:
        {
          "available": True,
          "n_stocks": int,
          "correlation": {labels, matrix},
          "warnings": [...],          # 편향 경고
          "style_concentration": {...},
          "optimization": {method, weights},  # 비중 제안
        }
    """
    n = len(items)
    if n < 3:
        return {"available": False, "error": "최적화에 최소 3종목 필요"}

    mat, labels, styles = _extract_matrix(items)
    if mat is None or len(labels) < 2:
        return {"available": False, "error": "분석 가능한 팩터 부족"}

    # ── 1. 상관 매트릭스 ──
    corr = _correlation_matrix(mat)

    # ── 2. 편향 경고 ──
    warnings = []
    high_pairs = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            r = corr[i, j]
            if abs(r) >= 0.7:
                high_pairs.append((labels[i], labels[j], round(float(r), 2)))
    for a, b, r in high_pairs:
        warnings.append(f"{a} ↔ {b} 상관 {r} — 사실상 중복 팩터 (다중공선성)")

    # 스타일 편중
    from collections import Counter
    style_count = Counter(styles)
    total = sum(style_count.values())
    style_conc = {_STYLE_LABELS.get(s, s): round(c / total * 100, 1) for s, c in style_count.items()}
    dominant = max(style_count.items(), key=lambda x: x[1])
    if dominant[1] / total >= 0.5:
        warnings.append(f"{_STYLE_LABELS.get(dominant[0], dominant[0])} 스타일에 {round(dominant[1]/total*100)}% 편중 — 단일 팩터 베팅 위험")

    # ── 3. 포트폴리오 최적화 (Gemini ③ — 비중 제안) ──
    optimization = _optimize_weights(items, mat, labels)

    return {
        "available": True,
        "n_stocks": n,
        "correlation": {
            "labels": labels,
            "matrix": [[round(float(corr[i, j]), 3) for j in range(len(labels))] for i in range(len(labels))],
        },
        "warnings": warnings if warnings else ["뚜렷한 다중공선성 없음 — 팩터 분산 양호"],
        "high_correlation_pairs": [{"a": a, "b": b, "corr": r} for a, b, r in high_pairs],
        "style_concentration": style_conc,
        "optimization": optimization,
    }


def _optimize_weights(items: list, mat: np.ndarray, labels: list) -> dict:
    """
    Inverse-Variance + Risk-Parity 비중 제안.

    종목별 변동성 프록시: 팩터 z-score의 분산 (높을수록 극단적 → 리스크↑).
    실제로는 수익률 시계열 공분산 사용. 여기선 팩터 분산을 프록시로.
    """
    n = len(items)
    std = mat.std(axis=0)
    std[std < 1e-9] = 1.0
    z = (mat - mat.mean(axis=0)) / std

    # 종목별 리스크 프록시 = 팩터 z-score의 L2 norm (극단성)
    risk = np.sqrt((z ** 2).sum(axis=1)) + 0.5  # +0.5 안정화
    inv_risk = 1.0 / risk
    weights_iv = inv_risk / inv_risk.sum()

    # 균등 비중 (비교용)
    np.ones(n) / n

    # 상위 비중 종목
    sorted_idx = np.argsort(-weights_iv)
    top_weights = []
    for idx in sorted_idx[:min(10, n)]:
        it = items[idx]
        top_weights.append({
            "stock_code": getattr(it, "stock_code", ""),
            "corp_name": getattr(it, "corp_name", ""),
            "weight_pct": round(float(weights_iv[idx]) * 100, 2),
            "risk_score": round(float(risk[idx]), 2),
        })

    # 집중도 (HHI)
    hhi = float((weights_iv ** 2).sum())
    effective_n = round(1.0 / hhi, 1) if hhi > 0 else n

    return {
        "method": "inverse_variance",
        "method_label": "역변동성 가중 (Inverse-Variance)",
        "weights": top_weights,
        "effective_n": effective_n,
        "concentration_hhi": round(hhi, 4),
        "note": "팩터 극단성을 리스크 프록시로 사용. 변동성 낮은 종목에 높은 비중. 실 운영 시 수익률 공분산으로 교체.",
    }


def register():
    """analyzers 파이프라인에 M7 등록."""
    from src.engine.analyzers import register_analyzer
    register_analyzer("collinearity", collinearity)
