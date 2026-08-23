"""경제노출 → 상장 상품 선택 (Brief §7.1/7.2 · CTO §26)

Brief §7.1 이 요구하는 분리:

    optimizer 는 **Economic Exposure** 를 결정하고,
    Implementation layer 가 실제 **listed instrument** 를 선택한다.

지금까지는 이 계층이 없어 "미국 대형주 노출 30%" 라는 **결정**과 "SPY 를 30% 산다"
라는 **실행**이 같은 것으로 뭉개져 있었다. 그래서 같은 노출을 더 싸게·더 유동적으로
구현할 수 있는지 아무도 묻지 않았다.

★노출 어휘를 새로 만들지 않는다★ `factor_exposure.FACTORS` 가 이미 노출 이름을
갖고 있다(`equity`·`duration`·`credit`·`commodity`·`usd`…). 팩터 모형이 노출을
**재고**, 이 모듈이 그 노출을 **구현**한다 — 이름이 같아야 둘이 이어진다.

★없는 것을 지어내지 않는다★ 이 저장소에는 ETF 메타데이터 저장소가 **없다**
(실측: `expense_ratio`·ETF `tracking_error` 심볼 0건). §7.2 가 요구한 기준 중
계산 가능한 것만 점수에 넣고 나머지는 **사유와 함께** `unavailable` 로 낸다.

★mock 에서 추적오차는 잡음이다★ 실측에서 같은 노출 후보끼리 상관이 거의 0 이었다
(SPY-VTI **+0.037**, 연 TE **39.95%**; VTI-QQQ 의 1.000/0.00% 는 시드 충돌이지
추적이 아니다). mock 로더가 티커마다 독립 난수walk 를 만들기 때문이다. 그래서 TE 는
계산하되 `source` 라벨을 달고 **mock 이면 순위에 쓰지 않는다.**
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 252
_ADV_WINDOW = 60
MARKETS = ("kr", "us")

# ★계산할 수 없는 기준 — 빈칸이 아니라 사유★ (P2-4 의 `_NO_CHANNEL` 관례)
UNAVAILABLE_CRITERIA: dict[str, str] = {
    "expense_ratio": ("운용보수 데이터가 이 저장소에 없습니다 — ETF 메타데이터 "
                      "저장소가 없어 벤더 연동이 필요합니다"),
    "corporate_actions": ("ETF 분배금·액면 이력이 없습니다 — 총수익 기준 비교를 "
                          "하려면 그 데이터가 먼저 필요합니다"),
}

# 경제노출 → 상장 후보. ★KR 상장 우선, 해외는 대안★ (사용자 결정)
# 코드는 `ticker_universe.TICKER_UNIVERSE` 의 카탈로그에서 온다.
EXPOSURES: dict[str, dict] = {
    "equity": {
        "label": "한국 대형주",
        "kr": ["069500"], "us": [],
        "note": "KODEX 200 — 국내 대표지수",
    },
    "equity_us": {
        "label": "미국 대형주",
        "kr": ["360750", "381180"], "us": ["SPY", "VTI", "DIA", "QQQ"],
        "note": "KR 상장 재간접(TIGER)과 미국 직상장이 같은 노출을 구현합니다",
    },
    "equity_small": {
        "label": "소형주",
        "kr": ["229200"], "us": ["IWM"],
        "note": "코스닥150 과 러셀2000 은 같은 소형주 노출이되 지역이 다릅니다",
    },
    "duration": {
        "label": "장기 금리(듀레이션)",
        "kr": [], "us": ["TLT"],
        "note": "국내 상장 장기채 ETF 가 카탈로그에 없습니다",
    },
    "credit": {
        "label": "신용",
        "kr": [], "us": ["HYG", "LQD"],
        "note": "HYG(하이일드)·LQD(투자등급) — 국내 후보 없음",
    },
    "commodity": {
        "label": "원자재",
        "kr": [], "us": ["GLD", "SLV"],
        "note": "금·은 — 국내 후보 없음",
    },
    "real_estate": {
        "label": "부동산",
        "kr": [], "us": ["VNQ"],
        "note": "리츠 — 국내 후보 없음",
    },
    "em": {
        "label": "신흥국",
        "kr": [], "us": ["EEM"],
        "note": "신흥국 주식 — 국내 후보 없음",
    },
}

# 해외 직상장을 고를 때 반드시 함께 나가는 라벨. ★세제 숫자는 보유하지 않는다★
FOREIGN_NOTE = ("해외 직상장은 환노출이 생기고 과세 체계가 국내 상장과 다릅니다 — "
                "이 저장소는 세율을 보유하지 않으므로 '고려해야 할 차이' 로만 "
                "알립니다")


def _source_label() -> str:
    """가격 출처 — `attribution._path_source()` 와 같은 관례."""
    try:
        from src.data.mock_gate import mock_allowed
        return "mock" if mock_allowed() else "db"
    except Exception:  # noqa: BLE001
        return "unknown"


def candidates(exposure: str, *, market: str = "kr") -> dict:
    """노출 → 후보 코드. ★KR 이 없으면 해외로 떨어지되 그 사실을 말한다★"""
    spec = EXPOSURES.get(exposure)
    if spec is None:
        return {"available": False,
                "reason": (f"'{exposure}' 는 알려진 경제노출이 아닙니다 — "
                           f"가능한 노출: {', '.join(sorted(EXPOSURES))}")}
    if market not in MARKETS and market != "any":
        return {"available": False, "reason": f"시장은 {MARKETS} 또는 'any' 입니다"}

    kr, us = list(spec["kr"]), list(spec["us"])
    fallback = None
    if market == "kr":
        primary, alternatives = kr, us
        if not kr and us:
            primary, alternatives = us, []
            fallback = (f"'{exposure}' 는 국내 상장 후보가 없어 해외 직상장으로 "
                        "구현합니다")
    elif market == "us":
        primary, alternatives = us, kr
        if not us and kr:
            primary, alternatives = kr, []
            fallback = f"'{exposure}' 는 해외 후보가 없어 국내 상장으로 구현합니다"
    else:
        primary, alternatives = kr + us, []

    if not primary:
        return {"available": False,
                "reason": f"'{exposure}' 에 대한 상장 후보가 카탈로그에 없습니다"}
    return {"available": True, "reason": None, "exposure": exposure,
            "label": spec["label"], "primary": primary,
            "alternatives": alternatives, "market": market,
            "market_fallback": fallback, "note": spec["note"]}


def _load(code: str, lookback_days: int):
    from datetime import datetime, timedelta

    from src.data.ohlcv_loader import load_ohlcv_unified
    end = datetime.now().date()
    start = end - timedelta(days=int(lookback_days * 1.6) + 30)
    return load_ohlcv_unified(str(code), start.isoformat(), end.isoformat(),
                              prefer="auto")


def score_instrument(code: str, *, lookback_days: int = DEFAULT_LOOKBACK_DAYS,
                     portfolio_value: float = 100_000_000.0,
                     target_weight_pct: float = 10.0) -> dict:
    """계산 가능한 기준만으로 상품을 잰다.

    ★점수 공식을 숨기지 않는다★ 항목별 값과 가중치를 함께 낸다 — 순위만 내면
    왜 그 상품이 뽑혔는지 되짚을 수 없다.
    """
    out: dict = {"code": str(code), "source": _source_label(),
                 "unavailable": dict(UNAVAILABLE_CRITERIA)}
    try:
        df = _load(code, lookback_days)
    except Exception as e:  # noqa: BLE001
        out.update(available=False, reason=f"시세를 불러오지 못했습니다: {type(e).__name__}")
        return out
    if df is None or len(df) == 0:
        out.update(available=False, reason="이 상품의 시세가 없습니다")
        return out

    close = df["close"].astype(float)
    vol = df["volume"].astype(float)
    bars = int(len(df))
    turnover = (close * vol).tail(_ADV_WINDOW)
    adv = float(turnover.mean()) if len(turnover) else 0.0

    # ★실행비용은 이미 있는 엔진이 낸다★ 새로 짓지 않는다.
    order_value = portfolio_value * max(target_weight_pct, 0.0) / 100.0
    est_cost_bp = None
    participation = None
    if adv > 0 and order_value > 0:
        try:
            from src.engine.market_impact import MarketImpactModel
            imp = MarketImpactModel.turnover_based_impact(
                turnover_pct=target_weight_pct, portfolio_equity=portfolio_value,
                avg_adv_krw=adv)
            est_cost_bp = imp.get("impact_bps")
            participation = imp.get("participation")
        except Exception:  # noqa: BLE001
            logger.debug("실행비용 추정 실패 %s", code, exc_info=True)

    rets = close.pct_change().dropna()
    coverage = round(float(len(rets) + 1) / max(bars, 1), 4)
    out.update(
        available=True, reason=None,
        adv_krw=round(adv, 0), bars=bars, coverage=coverage,
        est_cost_bp=est_cost_bp, participation=participation,
        annual_vol=(round(float(rets.std() * np.sqrt(252)), 4) if len(rets) > 2 else None),
    )
    return out


def tracking_error(code: str, reference: str, *,
                   lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> dict:
    """후보 vs 기준 상품의 연 추적오차.

    ★mock 이면 순위에 쓰지 않는다★ 실측에서 mock 로더는 티커마다 독립 난수walk 를
    만들어 같은 노출 후보끼리 상관이 0.037 이었다(TE 39.95%). 그 숫자로 "이 상품이
    더 잘 추종한다" 고 말하는 것은 잡음을 근거로 삼는 일이다.
    """
    src = _source_label()
    usable = src not in ("mock", "unknown")
    try:
        a, b = _load(code, lookback_days), _load(reference, lookback_days)
    except Exception as e:  # noqa: BLE001
        return {"available": False, "source": src, "usable": False,
                "reason": f"시세를 불러오지 못했습니다: {type(e).__name__}"}
    if a is None or b is None or len(a) == 0 or len(b) == 0:
        return {"available": False, "source": src, "usable": False,
                "reason": "두 상품의 시세를 모두 구하지 못했습니다"}

    ra = a["close"].astype(float).pct_change().dropna()
    rb = b["close"].astype(float).pct_change().dropna()
    x, y = ra.align(rb, join="inner")
    if len(x) < 30:
        return {"available": False, "source": src, "usable": False,
                "reason": f"겹치는 일수가 {len(x)}일뿐입니다 (최소 30일)"}

    te = float((x - y).std() * np.sqrt(252))
    return {
        "available": True, "reason": None,
        "reference": str(reference),
        "tracking_error": round(te, 4),
        "correlation": round(float(x.corr(y)), 4),
        "n_days": int(len(x)),
        "source": src, "usable": usable,
        "note": (None if usable else
                 ("합성(mock) 가격이라 추적오차가 잡음입니다 — 순위에 쓰지 "
                  "않습니다. 실데이터에서는 자동으로 반영됩니다")),
    }


# 점수 가중치 — ★공식을 숨기지 않는다★ 응답에 그대로 실어 보낸다.
WEIGHTS: dict[str, float] = {"liquidity": 0.5, "cost": 0.3, "history": 0.2}


def _rank(scored: list[dict], kr_codes: set[str]) -> list[dict]:
    """유동성·비용·이력으로 순위. 동점이면 KR 우선(사용자 결정)."""
    usable = [s for s in scored if s.get("available")]
    if not usable:
        return []
    max_adv = max((s.get("adv_krw") or 0.0) for s in usable) or 1.0
    max_bars = max((s.get("bars") or 0) for s in usable) or 1
    costs = [s.get("est_cost_bp") for s in usable if s.get("est_cost_bp") is not None]
    max_cost = max(costs) if costs else None

    for s in usable:
        liq = (s.get("adv_krw") or 0.0) / max_adv
        hist = (s.get("bars") or 0) / max_bars
        if s.get("est_cost_bp") is None or not max_cost:
            cost = None
        else:
            cost = 1.0 - (s["est_cost_bp"] / max_cost)   # 쌀수록 높다
        parts = {"liquidity": round(liq, 4), "history": round(hist, 4),
                 "cost": (round(cost, 4) if cost is not None else None)}
        total = sum(WEIGHTS[k] * v for k, v in parts.items() if v is not None)
        used = sum(WEIGHTS[k] for k, v in parts.items() if v is not None)
        s["score_parts"] = parts
        s["score_weights"] = dict(WEIGHTS)
        s["score"] = round(total / used, 4) if used > 0 else None
        s["is_kr"] = s["code"] in kr_codes
        s["skipped_criteria"] = [k for k, v in parts.items() if v is None]

    usable.sort(key=lambda s: (-(s["score"] or 0.0), not s["is_kr"], s["code"]))
    return usable


def select_instrument(exposure: str, *, market: str = "kr",
                      lookback_days: int = DEFAULT_LOOKBACK_DAYS,
                      portfolio_value: float = 100_000_000.0,
                      target_weight_pct: float = 10.0) -> dict:
    """한 경제노출을 구현할 상품을 고른다."""
    cand = candidates(exposure, market=market)
    if not cand["available"]:
        return cand

    spec = EXPOSURES[exposure]
    kr_codes = set(spec["kr"])
    scored = [score_instrument(c, lookback_days=lookback_days,
                               portfolio_value=portfolio_value,
                               target_weight_pct=target_weight_pct)
              for c in cand["primary"]]
    ranked = _rank(scored, kr_codes)
    rejected = [{"code": s["code"], "reason": s.get("reason")}
                for s in scored if not s.get("available")]
    if not ranked:
        return {"available": False, "exposure": exposure,
                "reason": "후보 중 어느 것도 시세를 내지 못했습니다",
                "rejected": rejected}

    chosen = ranked[0]
    te = None
    if len(ranked) > 1:
        te = tracking_error(chosen["code"], ranked[1]["code"],
                            lookback_days=lookback_days)

    foreign = not chosen["is_kr"]
    return {
        "available": True, "reason": None,
        "exposure": exposure, "label": cand["label"],
        "chosen": chosen["code"], "market": cand["market"],
        "ranked": ranked, "rejected": rejected,
        "alternatives": cand["alternatives"],
        "market_fallback": cand["market_fallback"],
        "tracking_error": te,
        "foreign_listing": foreign,
        "foreign_note": FOREIGN_NOTE if foreign else None,
        "unavailable": dict(UNAVAILABLE_CRITERIA),
        "note": cand["note"],
        "method": "liquidity_cost_history_weighted",
    }


def implement_exposures(exposure_weights: dict[str, float], *,
                        market: str = "kr", **kw) -> dict:
    """노출 비중 → 상품 비중. ★어느 노출에서 왔는지 함께 남긴다★

    합만 맞추면 "어느 노출을 구현한 비중인가" 가 사라진다 — 그러면 나중에
    노출이 바뀌었을 때 무엇을 갈아야 하는지 알 수 없다.
    """
    if not exposure_weights:
        return {"available": False, "reason": "노출 비중이 비어 있습니다"}

    holdings: dict[str, float] = {}
    lines: list[dict] = []
    unresolved: dict[str, str] = {}
    placed = 0.0
    for exposure, w in exposure_weights.items():
        weight = float(w)
        sel = select_instrument(exposure, market=market,
                                target_weight_pct=abs(weight), **kw)
        if not sel["available"]:
            unresolved[exposure] = sel["reason"]
            continue
        code = sel["chosen"]
        holdings[code] = round(holdings.get(code, 0.0) + weight, 6)
        placed += weight
        lines.append({"exposure": exposure, "weight_pct": weight,
                      "instrument": code, "market_fallback": sel["market_fallback"],
                      "foreign_listing": sel["foreign_listing"],
                      "score": sel["ranked"][0]["score"]})

    requested = sum(float(v) for v in exposure_weights.values())
    return {
        "available": bool(holdings), "reason": None if holdings else
        "어떤 노출도 구현할 수 없었습니다",
        "holdings": holdings, "lines": lines,
        "unresolved": unresolved,
        "requested_pct": round(requested, 6),
        "placed_pct": round(placed, 6),
        # ★구현하지 못한 비중을 조용히 재분배하지 않는다★
        "unplaced_pct": round(requested - placed, 6),
        "unavailable": dict(UNAVAILABLE_CRITERIA),
        "note": ("구현하지 못한 노출의 비중은 남은 상품에 재분배하지 않습니다 — "
                 "재분배하면 사용자가 요청하지 않은 노출이 커집니다"),
    }
