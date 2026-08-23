"""리밸런싱 정책 엔진 — ★거래 **여부**를 판단한다★ (Brief §10)

감사(`docs/specs/2026-08-22-dynamic-portfolio-audit.md` §3.1)가 "진짜로 없는 것"
으로 지목한 칸이다: **거래해야 하는지를 아무도 판단하지 않는다.**

`portfolio_rebalancer.py`(341줄)는 **트리거 탐지기**다 — 달력·drift·국면변경·변동성
급등을 감지한다. 그러나 Brief §10 의 핵심 규칙

    Trade if expected utility improvement > transaction cost + hysteresis

은 그 모듈에 없다. 게다가 기본값 `drift_threshold=0.05` 는 Brief §10 이 명시적으로
금지한 **"고정 ±5% 밴드"** 그 자체다. 이 모듈은 그 위에 **결정 계층**을 얹는다.

    트리거(언제 볼까)      ← portfolio_rebalancer.should_rebalance  (재사용)
    비용(얼마나 드나)      ← execution_plan.build_plan              (재사용)
    편익(얼마나 좋아지나)  ← 조건부 μ/Σ 로 계산한 효용 개선          (여기)
    판단(그래서 거래하나)  ← 편익 > 비용 + 히스테리시스              (여기)

★편익을 모르면 거래 판단을 하지 않는다★ μ/Σ 가 없으면 `decision="undetermined"`
로 답한다. 트리거만 보고 "거래하라"고 말하는 것이 지금까지의 결함이었다.

★연율과 일회성을 그냥 비교하지 않는다★ 효용 개선은 **연율**이고 거래비용은
**일회성**이다. 둘을 비교하려면 보유기간 가정이 필요하므로 `horizon_days` 를
명시적으로 받고 그 사실을 출력에 남긴다. 이 가정을 숨기면 임의의 기간을 골라
어떤 거래든 정당화할 수 있다.
"""
from __future__ import annotations

from typing import Any

import numpy as np

# allocation_routes 의 `delta` 기본값과 같은 값 — 두 곳이 다른 위험회피를 쓰면
# 같은 포트폴리오가 화면마다 다른 판단을 받는다.
DEFAULT_RISK_AVERSION = 2.5

# ★정책 선택이지 측정이 아니다★ 비용의 몇 배만큼 더 좋아져야 움직이는가.
# 0 이면 비용과 편익이 같을 때도 거래해 왕복(flip-flop)이 생긴다.
DEFAULT_HYSTERESIS_MULT = 0.5

DEFAULT_HORIZON_DAYS = 63          # ≈ 1분기. 가정이므로 출력에 남긴다.
TRADING_DAYS = 252

# 무거래 구간(no-trade band)의 하한/상한. 밴드가 여기 걸리면 **말한다**(조용히 자르지 않는다).
_BAND_FLOOR_PCT = 1.0
_BAND_CEIL_PCT = 20.0

DECISION_TRADE = "trade"
DECISION_HOLD = "hold"
DECISION_UNDETERMINED = "undetermined"


def _weights_vector(names: list[str], w: dict[str, float]) -> np.ndarray:
    """퍼센트(0~100) dict → 소수 벡터. 없는 자산은 0."""
    return np.array([float(w.get(n, 0.0)) / 100.0 for n in names], dtype=float)


def utility(w: np.ndarray, mu: np.ndarray, sigma: np.ndarray,
            risk_aversion: float) -> float:
    """평균-분산 효용 `μ'w − (λ/2)·w'Σw` (연율, 소수)."""
    return float(mu @ w - 0.5 * risk_aversion * (w @ sigma @ w))


def expected_utility_gain(current: dict[str, float], target: dict[str, float], *,
                          names: list[str], mu, sigma,
                          risk_aversion: float = DEFAULT_RISK_AVERSION,
                          horizon_days: int = DEFAULT_HORIZON_DAYS) -> dict:
    """목표로 옮겼을 때의 효용 개선.

    ★없으면 지어내지 않는다★ μ/Σ 가 없으면 사유를 돌려준다 — 0 으로 채우면
    "편익이 없다"(=거래하지 마라)로 읽히는데 그것은 **모른다**와 다른 진술이다.
    """
    if mu is None or sigma is None:
        return {"available": False,
                "reason": "조건부 μ/Σ 가 없어 효용 개선을 계산할 수 없습니다"}
    if not names:
        return {"available": False, "reason": "자산 목록이 비어 있습니다"}
    if horizon_days <= 0:
        return {"available": False, "reason": "보유기간(horizon_days)은 1 이상이어야 합니다"}

    mu = np.asarray(mu, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    n = len(names)
    if mu.shape != (n,) or sigma.shape != (n, n):
        return {"available": False,
                "reason": f"μ/Σ 모양이 자산 수({n})와 맞지 않습니다: "
                          f"mu{mu.shape} sigma{sigma.shape}"}
    if not np.all(np.isfinite(mu)) or not np.all(np.isfinite(sigma)):
        return {"available": False, "reason": "μ/Σ 에 유한하지 않은 값이 있습니다"}

    w_c = _weights_vector(names, current)
    w_t = _weights_vector(names, target)
    u_c = utility(w_c, mu, sigma, risk_aversion)
    u_t = utility(w_t, mu, sigma, risk_aversion)

    annual = u_t - u_c
    # ★연율 → 보유기간 환산★ 이 한 줄이 가정이다. 숨기지 않는다.
    scaled = annual * (horizon_days / TRADING_DAYS)
    return {
        "available": True, "reason": None,
        "utility_current": round(u_c, 6), "utility_target": round(u_t, 6),
        "gain_annual": round(annual, 6),
        "gain_pct": round(scaled * 100.0, 4),
        "horizon_days": int(horizon_days),
        "risk_aversion": float(risk_aversion),
        "note": (f"효용 개선은 연율이고 거래비용은 일회성입니다 — "
                 f"{horizon_days}영업일 보유를 가정해 환산했습니다"),
    }


def dynamic_band(*, cost_pct: float, target_weight_pct: float,
                 risk_aversion: float = DEFAULT_RISK_AVERSION,
                 uncertainty: float | None = None,
                 participation: float | None = None) -> dict:
    """자산 하나의 무거래 밴드 — ★고정 ±5% 를 기본값으로 두지 않는다★ (Brief §10)

        half_band ≈ ( (3/(2λ)) · c · w²(1−w)² ) ^ (1/3)

    비례 거래비용이 있는 최적 거래 문제의 알려진 결과(Constantinides 1986 계열)다.
    밴드는 **비용의 세제곱근**에 비례하고 **포지션 크기에 의존**한다 — 0% 나 100%
    근처에서는 좁고 중간에서 가장 넓다.

    ★σ² 로 나누는 형태를 쓰지 않는다★ 처음에 그렇게 짰더니 어떤 포지션에서도
    같은 값(20%p, 상한 포화)이 나왔다 — 이름만 동적이고 실제로는 고정 밴드였다.
    변동성은 이 식에 직접 들어가지 않는다. 목표 비중 w* 를 정할 때 optimizer 가
    이미 Σ 를 썼기 때문이다.

    여기에 두 배수를 곱한다: 목표가 불확실할수록, 유동성이 나쁠수록 넓힌다.

    ★수치 안전★ 세제곱근 인자가 음수가 되지 않도록 입력을 먼저 검사한다(CLAUDE.md).
    """
    if cost_pct is None or cost_pct < 0:
        return {"available": False, "reason": "거래비용을 알 수 없어 밴드를 정할 수 없습니다"}
    if risk_aversion <= 0:
        return {"available": False, "reason": "위험회피 계수는 0보다 커야 합니다"}
    w = float(target_weight_pct) / 100.0
    if not (0.0 <= w <= 1.0):
        return {"available": False,
                "reason": f"목표 비중이 0~100% 밖입니다: {target_weight_pct}"}

    c = max(float(cost_pct), 0.0) / 100.0
    raw = ((1.5 / risk_aversion) * c * (w ** 2) * ((1.0 - w) ** 2)) ** (1.0 / 3.0)
    half_pct = raw * 100.0

    unc_mult = 1.0 + max(uncertainty or 0.0, 0.0)
    liq_mult = 1.0 + min(max(participation or 0.0, 0.0), 1.0) * 2.0
    half_pct *= unc_mult * liq_mult

    clamped = None
    if half_pct < _BAND_FLOOR_PCT:
        clamped = f"계산값 {round(half_pct, 3)}%p 가 하한 {_BAND_FLOOR_PCT}%p 아래라 하한을 씁니다"
        half_pct = _BAND_FLOOR_PCT
    elif half_pct > _BAND_CEIL_PCT:
        clamped = f"계산값 {round(half_pct, 3)}%p 가 상한 {_BAND_CEIL_PCT}%p 위라 상한을 씁니다"
        half_pct = _BAND_CEIL_PCT

    return {
        "available": True, "reason": None,
        "half_width_pct": round(half_pct, 3),
        # ★Brief §9 — 점 하나가 아니라 구간★ "SPY target 30%, range 25~34%"
        "low_pct": round(max(float(target_weight_pct) - half_pct, 0.0), 3),
        "high_pct": round(min(float(target_weight_pct) + half_pct, 100.0), 3),
        "inputs": {"cost_pct": round(float(cost_pct), 4),
                   "target_weight_pct": round(float(target_weight_pct), 4),
                   "risk_aversion": float(risk_aversion),
                   "uncertainty": uncertainty, "participation": participation},
        "multipliers": {"uncertainty": round(unc_mult, 3), "liquidity": round(liq_mult, 3)},
        "clamped": clamped is not None, "clamp_reason": clamped,
        "note": "밴드는 비용의 세제곱근에 비례하고 포지션 크기에 의존합니다 — 고정 ±5% 가 아닙니다",
    }


def gradual_target(current: dict[str, float], target: dict[str, float],
                   confidence: float | None) -> dict:
    """점진 이동 — `trade_target = current + α(confidence)·(target − current)`

    ★신뢰도가 낮으면 목표까지 즉시 가지 않는다★ (Brief §10) 확신이 없는 목표로
    전량 이동하면 다음 달 되돌리는 비용을 두 번 낸다.

    `confidence` 가 없으면 α 를 **1 로 가정하지 않고** 사유와 함께 전량 이동을
    돌려준다 — 가정을 숨기지 않기 위해서다.
    """
    keys = sorted(set(current) | set(target))
    if confidence is None:
        alpha, reason = 1.0, "신뢰도가 주어지지 않아 목표까지 전량 이동합니다"
    else:
        alpha = min(max(float(confidence), 0.0), 1.0)
        reason = None
    moved = {k: round(float(current.get(k, 0.0))
                      + alpha * (float(target.get(k, 0.0)) - float(current.get(k, 0.0))), 4)
             for k in keys}
    return {"available": True, "alpha": round(alpha, 4), "reason": reason,
            "weights": moved,
            "note": "신뢰도가 낮을수록 목표의 일부만 이동합니다"}


def _cost_block(current: dict[str, float], target: dict[str, float],
                portfolio_value: float, *, price_of=None, adv_of=None) -> dict:
    """거래비용 — ★`execution_plan.build_plan` 을 재사용한다★ 비용 산수를 두 곳에 두지 않는다.

    `build_plan` 은 수수료·거래세·스프레드·시장충격을 이미 계산하고 참여율까지 낸다.
    """
    try:
        from src.engine.execution_plan import build_plan
        plan = build_plan(current, target, portfolio_value,
                          price_of=price_of, adv_of=adv_of)
    except Exception as e:  # noqa: BLE001
        return {"available": False,
                "reason": f"거래비용을 계산하지 못했습니다: {type(e).__name__}"}

    summary = plan.get("summary") or {}
    est_cost = float(summary.get("est_cost") or 0.0)
    parts = [o.get("participation") for o in (plan.get("orders") or [])
             if o.get("participation") is not None]
    return {
        "available": True, "reason": None,
        "cost_krw": round(est_cost, 0),
        "cost_pct": round(est_cost / portfolio_value * 100.0, 4) if portfolio_value else None,
        "cost_bp": summary.get("est_cost_bp"),
        "turnover_pct": summary.get("turnover_pct"),
        "n_orders": summary.get("n_orders"),
        "max_participation": round(max(parts), 6) if parts else None,
        "missing_price": plan.get("missing_price") or [],
    }


def detect_triggers(current_weights: dict[str, float], target_weights: dict[str, float], *,
                    as_of=None, policy=None, current_regime: str | None = None,
                    previous_regime: str | None = None,
                    last_rebalance_date=None, recent_returns=None) -> dict:
    """★`portfolio_rebalancer.py` 를 실제로 호출한다★ — 341줄 호출자 0 이던 모듈이다.

    그 모듈은 **언제 볼지**(달력·drift·국면변경·변동성 급등)를 안다. 그것은 버리지
    않는다. 다만 그 판정만으로 거래하지 않는다 — 트리거는 **검토의 시작**이지
    거래의 근거가 아니다. 근거는 `rebalance_decision` 의 편익 대 비용이다.
    """
    import pandas as pd

    from src.engine.portfolio_rebalancer import PortfolioRebalancer, RebalancePolicy
    try:
        rb = PortfolioRebalancer(policy or RebalancePolicy())
        when = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.now()
        last = pd.Timestamp(last_rebalance_date) if last_rebalance_date is not None else None
        out = rb.should_rebalance(
            when,
            {k: float(v) / 100.0 for k, v in current_weights.items()},
            {k: float(v) / 100.0 for k, v in target_weights.items()},
            current_regime=current_regime, previous_regime=previous_regime,
            last_rebalance_date=last, recent_returns=recent_returns)
    except Exception as e:  # noqa: BLE001 — 트리거 실패가 결정을 죽이지 않는다
        return {"available": False,
                "reason": f"트리거를 판정하지 못했습니다: {type(e).__name__}"}
    out["available"] = True
    out["note"] = ("트리거는 검토 시점을 알릴 뿐 거래 근거가 아닙니다 — "
                   "거래 여부는 편익 대 비용이 정합니다")
    return out


def rebalance_decision(current_weights: dict[str, float],
                       target_weights: dict[str, float], *,
                       portfolio_value: float,
                       names: list[str] | None = None,
                       mu=None, sigma=None,
                       risk_aversion: float = DEFAULT_RISK_AVERSION,
                       horizon_days: int = DEFAULT_HORIZON_DAYS,
                       hysteresis_mult: float = DEFAULT_HYSTERESIS_MULT,
                       uncertainty: float | None = None,
                       confidence: float | None = None,
                       triggers: dict | None = None,
                       price_of=None, adv_of=None) -> dict[str, Any]:
    """★거래할 가치가 있는가★ — Brief §21 이 시스템에 묻는 그 질문.

        Trade if expected utility improvement > transaction cost + hysteresis

    반환 `decision` 은 셋 중 하나다:
      · `trade`        — 편익이 비용+히스테리시스를 넘는다
      · `hold`         — 넘지 못한다(또는 밴드 안이다)
      · `undetermined` — ★편익을 계산할 수 없다★ 트리거가 울려도 거래를 권하지 않는다
    """
    pv = float(portfolio_value or 0.0)
    if pv <= 0:
        return {"decision": DECISION_UNDETERMINED, "available": False,
                "reason": "포트폴리오 평가액이 0 이하입니다"}

    cost = _cost_block(current_weights, target_weights, pv,
                       price_of=price_of, adv_of=adv_of)
    benefit = expected_utility_gain(current_weights, target_weights, names=names or [],
                                    mu=mu, sigma=sigma, risk_aversion=risk_aversion,
                                    horizon_days=horizon_days)

    # ★밴드는 자산마다 다르다★ 포지션 크기에 의존하므로 하나로 뭉치면 정보가 사라진다.
    keys = sorted(set(current_weights) | set(target_weights))
    bands: dict[str, dict] = {}
    outside: list[str] = []
    if cost["available"]:
        for k in keys:
            b = dynamic_band(cost_pct=cost.get("cost_pct") or 0.0,
                             target_weight_pct=float(target_weights.get(k, 0.0)),
                             risk_aversion=risk_aversion, uncertainty=uncertainty,
                             participation=cost.get("max_participation"))
            bands[k] = b
            gap = abs(float(target_weights.get(k, 0.0)) - float(current_weights.get(k, 0.0)))
            if b.get("available") and gap >= b["half_width_pct"]:
                outside.append(k)
    band = {"available": bool(bands), "by_asset": bands, "outside": outside,
            "reason": None if bands else "비용을 몰라 동적 밴드를 정할 수 없습니다"}

    max_gap = max((abs(float(target_weights.get(k, 0.0)) - float(current_weights.get(k, 0.0)))
                   for k in keys), default=0.0)

    out: dict[str, Any] = {
        "available": True, "reason": None,
        "max_gap_pct": round(max_gap, 4),
        "cost": cost, "benefit": benefit, "band": band,
        "triggers": triggers,
        "gradual": gradual_target(current_weights, target_weights, confidence),
        "hysteresis_mult": float(hysteresis_mult),
    }

    if not cost["available"]:
        out.update(decision=DECISION_UNDETERMINED, reason=cost["reason"])
        return out
    if not benefit["available"]:
        # ★트리거만 보고 거래하라고 말하지 않는다★ 이것이 기존 결함이었다.
        out.update(decision=DECISION_UNDETERMINED, reason=benefit["reason"],
                   note="트리거가 울려도 편익을 모르면 거래를 권하지 않습니다")
        return out

    # ★모든 자산이 자기 밴드 안이면 거래하지 않는다★ 밴드를 알 때만 적용한다.
    if band["available"] and not outside:
        out.update(decision=DECISION_HOLD,
                   reason=(f"자산 {len(keys)}종 전부가 각자의 무거래 밴드 안입니다 "
                           f"(최대 괴리 {round(max_gap, 2)}%p)"))
        return out

    gain_pct = float(benefit["gain_pct"])
    cost_pct = float(cost["cost_pct"] or 0.0)
    threshold = cost_pct * (1.0 + float(hysteresis_mult))
    out["threshold_pct"] = round(threshold, 4)
    out["net_pct"] = round(gain_pct - threshold, 4)

    if gain_pct > threshold:
        out.update(decision=DECISION_TRADE,
                   reason=(f"{horizon_days}영업일 기준 효용 개선 {round(gain_pct, 3)}% > "
                           f"비용 {round(cost_pct, 3)}% × (1+{hysteresis_mult}) "
                           f"= {round(threshold, 3)}%"))
    else:
        out.update(decision=DECISION_HOLD,
                   reason=(f"{horizon_days}영업일 기준 효용 개선 {round(gain_pct, 3)}% 가 "
                           f"비용 문턱 {round(threshold, 3)}% 를 넘지 못합니다"))
    return out
