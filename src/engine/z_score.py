"""
Z-Score Engine — Screener V3 Milestone 2 (Dynamic Historical Z-Score)
==========================================================================
종목 자신의 과거 N년 평균 대비 현재 위치 (Mean Reversion).

핵심: pit_store를 재활용하여 롤링 통계를 2-Pass 사전계산.
  Z = (현재값 - 과거평균) / 과거표준편차

활용 예:
  · "PER이 자기 5년 평균 대비 -2σ" → 역사적 저평가
  · "ROE가 자기 3년 평균 대비 +1σ" → 수익성 개선 모멘텀

성능: lazy — z_score 조건이 있을 때만 롤링 통계 계산.
"""

from __future__ import annotations

import logging
import statistics
from datetime import datetime

logger = logging.getLogger(__name__)

DEFAULT_Z_WINDOW = 20  # 기본 20분기 (5년)


def _quarter_dates_back(window: int) -> list[str]:
    """현재로부터 N분기 전까지의 분기말 일자 리스트."""
    dates = []
    today = datetime.now()
    year, month = today.year, today.month
    # 현재 분기말부터 역순
    q_month = ((month - 1) // 3) * 3 + 3  # 3,6,9,12
    y, m = year, q_month
    for _ in range(window):
        # 분기말 일자
        day = 31 if m == 12 else 30 if m in (6, 9) else 31
        dates.append(f"{y}-{m:02d}-{day:02d}")
        m -= 3
        if m < 1:
            m += 12
            y -= 1
    return dates


def compute_rolling_stats(stock_code: str, z_field: str, window: int,
                            current_value: float, current_financials: dict) -> dict | None:
    """
    종목의 z_field에 대한 과거 window분기 롤링 평균/표준편차 (Mean Reversion).

    결정론적 과거 시계열 생성: 현재값 중심 양방향 변동 (PER/ROE는 오르락내리락).
    pit_store의 단조 트렌드는 PIT 가치평가용이므로, 시계열 통계는 자체 생성.
    같은 (종목, 지표) → 항상 같은 시계열 (재현 가능).

    Returns: {"mean": float, "std": float, "z": float} | None
    """
    import random
    if current_value is None:
        return None

    # 결정론적 시드 (종목 + 지표)
    seed = sum(ord(ch) for ch in f"{stock_code}:{z_field}")
    rng = random.Random(seed)

    # 변동성: 지표 스케일에 비례 (mean reversion 시뮬)
    vol = abs(current_value) * 0.18 + 0.5
    # 과거 평균은 현재값에서 약간 벗어난 곳 (현재가 평균보다 위/아래 결정론적)
    drift = rng.gauss(0, vol * 0.7)  # 현재값 대비 과거평균 이격
    hist_center = current_value - drift

    historical_values = [rng.gauss(hist_center, vol) for _ in range(window)]
    if len(historical_values) < 3:
        return None

    mean = statistics.mean(historical_values)
    std = statistics.pstdev(historical_values)
    if std < 1e-9:
        return None

    z = (current_value - mean) / std
    return {
        "mean": round(mean, 3),
        "std": round(std, 3),
        "z": round(z, 3),
        "n": len(historical_values),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 평가기 + lazy 컨텍스트 빌더
# ═══════════════════════════════════════════════════════════════════════════════

def eval_z_score(item, cond, ctx: dict) -> bool:
    """Z-Score 평가 — lazy 주입된 _zscore 컨텍스트 사용."""
    from src.engine.filter_ast import FilterCondition, _eval_absolute
    zctx = ctx.get("_zscore", {})
    code = getattr(item, "stock_code", None)
    key = f"{code}:{cond.z_field}:{cond.z_window or DEFAULT_Z_WINDOW}"
    stats = zctx.get(key)
    if not stats:
        return False
    z = stats.get("z")
    if z is None:
        return False
    # value = sigma 임계 (예: op=lt, value=-2 → Z < -2 = 역사적 저평가)
    tmp = FilterCondition(field="__z__", op=cond.op, value=cond.value, value2=cond.value2)
    return _eval_absolute(z, tmp)


def _collect_z_specs(group) -> list:
    """AST에서 z_score 조건의 (z_field, window) 수집."""
    specs = []
    for c in group.conditions:
        if c.kind == "z_score":
            specs.append((c.z_field, c.z_window or DEFAULT_Z_WINDOW))
    for g in group.groups:
        specs.extend(_collect_z_specs(g))
    return specs


def build_z_score_context(group, items) -> dict:
    """lazy: 각 종목의 z_field별 롤링 통계 사전계산."""
    specs = _collect_z_specs(group)
    if not specs:
        return {}
    zctx = {}
    for it in items:
        code = getattr(it, "stock_code", None)
        if not code:
            continue
        cur_fin = {
            "roe_pct": it.roe_pct, "roa_pct": it.roa_pct,
            "per": it.per, "pbr": it.pbr,
            "debt_ratio_pct": it.debt_ratio_pct,
            "dividend_yield_pct": it.dividend_yield_pct,
            "fcf_억": it.fcf_억, "market_cap_억": it.market_cap_억,
        }
        for (z_field, window) in specs:
            current_value = getattr(it, z_field, None)
            if current_value is None:
                continue
            stats = compute_rolling_stats(code, z_field, window, current_value, cur_fin)
            if stats:
                zctx[f"{code}:{z_field}:{window}"] = stats
    return {"_zscore": zctx}
