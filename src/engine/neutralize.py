"""포트폴리오 중립화 — 베타/섹터 중립 + 페어/스프레드 (Full Expansion P3 잔여)
==============================================================================
지시서 §8 검증: "베타중립·섹터중립·페어스프레드 결과가 목표 노출을 허용오차 내로
달성한다." 그리고 NeutralizationSpec 데이터 모델.

접근(정직):
  · 베타중립 = 등식제약 사영(최소 편차). w0에서 가장 가까우면서 βᵀw=target_beta,
    1ᵀw=gross(롱온리) 또는 0(달러중립)을 정확히 만족. 롱온리는 베타 0을 완전히 달성
    못할 수 있음(모든 β>0) → 음수 발생 시 정직 보고(진짜 중립은 롱숏 필요).
  · 섹터중립 = 섹터별 총비중을 균등(또는 목표)으로 재분배(섹터 내 상대비중 보존).
  · 페어/스프레드 = 베타중립 헤지비율(β_long/β_short)로 롱1·숏h 구성.

betas/sectors 주입 가능(테스트) — 미주입 시 price_factors(beta_1y)·genport(섹터).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

TOL = 1e-6


def _load_beta(code: str) -> float | None:
    try:
        from src.data.price_factors_store import PriceFactorsStore
        f = PriceFactorsStore.get_default().get_factors(code, None) or {}
        b = f.get("beta_1y")
        return float(b) if isinstance(b, (int, float)) else None
    except Exception:
        return None


def _load_sector(code: str) -> str | None:
    try:
        from src.data.genport_themes import build_group_assignment
        from src.data.stock_master import load_master_flags
        flags = load_master_flags() or {}
        gmap = build_group_assignment(flags)
        return gmap.get(code)
    except Exception:
        return None


def beta_neutralize(weights: dict[str, float], betas: dict[str, float],
                    target_beta: float = 0.0, dollar_neutral: bool = False) -> dict[str, Any]:
    """등식제약 사영으로 βᵀw=target_beta 정확 달성(최소 편차). 롱온리 gross=1,
    dollar_neutral이면 net=0(롱숏)."""
    codes = [c for c in weights if c in betas and betas[c] is not None]
    if len(codes) < 2:
        return {"error": True, "message": "베타 가용 종목 2개 미만 — 중립화 불가."}
    w0 = np.array([max(weights[c], 0.0) for c in codes], dtype=float)
    s = w0.sum()
    w0 = w0 / s if s > 0 else np.ones(len(codes)) / len(codes)
    beta = np.array([betas[c] for c in codes], dtype=float)

    gross_target = 0.0 if dollar_neutral else 1.0
    # 제약 A^T w = b : [1; beta]
    A = np.vstack([np.ones(len(codes)), beta]).T          # n×2
    b = np.array([gross_target, target_beta])
    # 사영: w = w0 - A (AᵀA)^-1 (Aᵀw0 - b)
    try:
        M = np.linalg.solve(A.T @ A, A.T @ w0 - b)
        w = w0 - A @ M
    except np.linalg.LinAlgError:
        return {"error": True, "message": "제약 특이 — 베타 분산 부족."}

    achieved_beta = float(beta @ w)
    achieved_gross = float(w.sum())
    min_w = float(w.min())
    long_only_ok = min_w >= -TOL
    return {
        "error": False,
        "weights": {c: round(float(w[i]) * 100, 4) for i, c in enumerate(codes)},
        "target_beta": target_beta,
        "achieved_beta": round(achieved_beta, 6),
        "beta_hit": abs(achieved_beta - target_beta) < 1e-4,
        "gross": round(achieved_gross, 4),
        "dollar_neutral": dollar_neutral,
        "long_only_feasible": long_only_ok,
        "note": ("롱온리로 목표 베타 달성(음수 없음)." if long_only_ok else
                 "일부 음수 비중 발생 — 진짜 베타중립은 롱숏(공매도)이 필요(정직). "
                 "dollar_neutral=true로 롱숏 허용하거나, 롱온리는 저베타 틸트로 근사."),
    }


def sector_neutralize(weights: dict[str, float], sectors: dict[str, str],
                      target: dict[str, float] | None = None) -> dict[str, Any]:
    """섹터별 총비중을 목표(기본 균등)로 재분배 — 섹터 내 상대비중 보존."""
    codes = [c for c in weights if c in sectors and sectors[c]]
    if len(codes) < 2:
        return {"error": True, "message": "섹터 가용 종목 2개 미만."}
    w = {c: max(weights[c], 0.0) for c in codes}
    tot = sum(w.values()) or 1.0
    w = {c: v / tot for c, v in w.items()}

    by_sector: dict[str, list[str]] = {}
    for c in codes:
        by_sector.setdefault(sectors[c], []).append(c)
    secs = sorted(by_sector)
    tgt = target or {s: 1.0 / len(secs) for s in secs}
    tsum = sum(tgt.get(s, 0) for s in secs) or 1.0

    before = {s: round(sum(w[c] for c in by_sector[s]) * 100, 2) for s in secs}
    out: dict[str, float] = {}
    for s in secs:
        members = by_sector[s]
        cur = sum(w[c] for c in members)
        share = tgt.get(s, 0) / tsum
        for c in members:
            rel = (w[c] / cur) if cur > 0 else 1.0 / len(members)
            out[c] = share * rel
    after = {s: round(sum(out[c] for c in by_sector[s]) * 100, 2) for s in secs}
    max_dev = max(abs(after[s] - tgt.get(s, 0) / tsum * 100) for s in secs)
    return {
        "error": False,
        "weights": {c: round(v * 100, 4) for c, v in out.items()},
        "sector_before_pct": before, "sector_after_pct": after,
        "target_pct": {s: round(tgt.get(s, 0) / tsum * 100, 2) for s in secs},
        "max_deviation_pct": round(max_dev, 4),
        "neutral": max_dev < 1e-2,
        "note": "섹터별 총비중을 목표로 맞춤(섹터 내 상대비중 보존). 목표 미지정 시 균등.",
    }


def pair_spread(long_code: str, short_code: str, betas: dict[str, float],
                hedge_ratio: float | None = None) -> dict[str, Any]:
    """동일 업종 페어 — 베타중립 헤지비율(β_long/β_short)로 롱1·숏h."""
    bl, bs = betas.get(long_code), betas.get(short_code)
    if hedge_ratio is None:
        if not bl or not bs or bs == 0:
            return {"error": True, "message": "베타 미보유 — 헤지비율 산출 불가(직접 지정 필요)."}
        hedge_ratio = bl / bs
    net_beta = (bl or 0) - hedge_ratio * (bs or 0)
    return {
        "error": False,
        "long": long_code, "short": short_code,
        "hedge_ratio": round(float(hedge_ratio), 4),
        "weights": {long_code: 100.0, short_code: round(-float(hedge_ratio) * 100, 2)},
        "net_beta": round(float(net_beta), 6),
        "beta_neutral": abs(net_beta) < 1e-4,
        "basis": "beta" if betas.get(long_code) is not None else "manual",
        "note": "베타중립 헤지비율 = β_long/β_short. 코인티그레이션·상대강도 기반은 별도 지정. "
                "페어 붕괴·유동성·차입 불가 시 청산 룰은 실행계획에서 관리.",
    }


def neutralize_portfolio(weights: dict[str, float], mode: str = "beta",
                         target_beta: float = 0.0, dollar_neutral: bool = False,
                         beta_of: Callable[[str], float | None] | None = None,
                         sector_of: Callable[[str], str | None] | None = None,
                         sector_target: dict[str, float] | None = None) -> dict[str, Any]:
    """중립화 오케스트레이터. mode: beta | sector | both."""
    beta_of = beta_of or _load_beta
    sector_of = sector_of or _load_sector
    result: dict[str, Any] = {"mode": mode}

    cur = dict(weights)
    if mode in ("beta", "both"):
        betas = {c: beta_of(c) for c in cur}
        bn = beta_neutralize(cur, {k: v for k, v in betas.items() if v is not None},
                             target_beta=target_beta, dollar_neutral=dollar_neutral)
        result["beta"] = bn
        if not bn.get("error"):
            cur = {c: v / 100.0 for c, v in bn["weights"].items()}
    if mode in ("sector", "both"):
        sectors = {c: sector_of(c) for c in cur}
        sn = sector_neutralize(cur, {k: v for k, v in sectors.items() if v},
                               target=sector_target)
        result["sector"] = sn
        if not sn.get("error"):
            cur = {c: v / 100.0 for c, v in sn["weights"].items()}

    result["weights"] = {c: round(v * 100, 4) for c, v in cur.items()}
    return result
