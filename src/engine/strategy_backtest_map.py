"""전략 → 백테스터 셋업 매핑 (하이브리드) + 최적화 전략 충실 백테스트 어댑터
==========================================================================
매크로 콕핏 "백테스트" 버튼 → 전략 유형별로 백테스터를 가장 충실하게 구성:
  · 모멘텀 13 → 편집가능 조건식(custom ETF + buy_conditions + 정렬 상위N + 월 리밸런스)
  · 정적 2(permanent·equal_weight) → asset_alloc 바스켓
  · 최적화 7(공분산) → 조건식 표현 불가 → backtest_strategy 동적 엔진을 백테스트로 실행
유니버스: US 티커를 국내 ETF 코드로 매핑(US_TO_KR) — 백테스터가 KR 시세를 읽으므로.
"""

from __future__ import annotations

import math
import os
from datetime import datetime


# ── 모멘텀 조건식 빌더 (factor_expr 문법: 기간은 {N일} 브레이스, 비교는 > ) ──
def _mom(n: int) -> str:
    return f"변화율_기간({{종가}},{{{n}일}})"


def _above_ma(n: int) -> str:
    return f"{{종가}} - 이동평균({{종가}},{{{n}일}})"


_W13612 = f"12*{_mom(21)} + 4*{_mom(63)} + 2*{_mom(126)} + {_mom(252)}"   # 13612W 가속 모멘텀
_ACCEL = f"{_mom(21)} + {_mom(63)} + {_mom(126)}"                          # 1+3+6개월 가속

# sid → {universe(US), cond(산술 '값'식 — op:gt rhs:0으로 비교), sort(정렬값식|None), max(보유수)}
# ※ factor_expr는 산술 전용(비교 미지원) → cond는 '값', 비교는 op/rhs로.
_MOMENTUM: dict[str, dict] = {
    "classic_dm":   {"universe": ["SPY", "EFA", "AGG"], "cond": _mom(252), "sort": _mom(252), "max": 1},
    "composite_dm": {"universe": ["SPY", "EFA", "HYG", "LQD", "REM", "VNQ", "GLD", "PDBC"], "cond": _mom(252), "sort": _mom(252), "max": 4},
    "accel_dm":     {"universe": ["SPY", "SCZ", "TLT"], "cond": _ACCEL, "sort": _ACCEL, "max": 1},
    "raa":          {"universe": ["QQQ", "IWN", "IEF", "TLT", "GLD"], "cond": _mom(252), "sort": _mom(252), "max": 5},
    "gtaa":         {"universe": ["SPY", "EFA", "IEF", "PDBC", "VNQ"], "cond": _above_ma(200), "sort": None, "max": 5},
    "paa":          {"universe": ["SPY", "IWM", "QQQ", "EWJ", "EEM", "IEF"], "cond": _above_ma(252), "sort": None, "max": 6},
    "vaa":          {"universe": ["SPY", "EFA", "EEM", "AGG", "LQD", "IEF", "SHY"], "cond": _W13612, "sort": _W13612, "max": 1},
    "faa":          {"universe": ["VTI", "EFA", "EEM", "IEF", "TLT", "GLD", "PDBC", "VNQ"], "cond": _mom(84), "sort": _mom(84), "max": 3},
    "aaa":          {"universe": ["SPY", "EFA", "EEM", "VNQ", "GLD", "PDBC", "IEF", "TLT"], "cond": _W13612, "sort": _W13612, "max": 4},
    "daa":          {"universe": ["SPY", "QQQ", "IWM", "EFA", "EEM", "VNQ", "GLD", "IEF", "LQD", "SHY"], "cond": _W13612, "sort": _W13612, "max": 2},
    "bond_dynamic": {"universe": ["TLT", "HYG", "EMB", "IEF", "LQD"], "cond": _mom(126), "sort": _mom(126), "max": 3},
    "managed_futures": {"universe": ["SPY", "EFA", "EEM", "TLT", "IEF", "GLD", "PDBC", "VNQ"], "cond": _mom(252), "sort": _mom(252), "max": 8},
}
_STATIC = {"permanent", "equal_weight"}
# 엔진 모드 = 조건식·정적바스켓으로 표현 불가 → backtest_strategy 동적 실행.
#   최적화 7(공분산) + laa(타 자산 MA 참조 스위치라 종목별 조건 불가).
_ENGINE = {"risk_parity", "hrp", "min_var", "max_div", "max_sharpe", "black_litterman", "kelly", "laa"}


def _codes(us_tickers: list[str], mk: str) -> list[str]:
    from src.data.etf_prices import resolve
    out, seen = [], set()
    for t in us_tickers:
        code = resolve(t, mk)[0]
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def backtest_config(sid: str, market: str = "us") -> dict | None:
    """전략 id → 백테스터 셋업 구성 (mode + 파라미터)."""
    from src.engine.tactical_allocations import ALL_STRATEGIES
    entry = next((s for s in ALL_STRATEGIES if s[0] == sid), None)
    if entry is None:
        return None
    _id, name, _desc, family, _fn = entry
    mk = "kr" if market == "kr" else "us"
    base = {"id": sid, "name": name, "family": family, "market": mk}

    if sid in _MOMENTUM:
        spec = _MOMENTUM[sid]
        return {**base, "mode": "conditions",
                "universe_codes": _codes(spec["universe"], mk),
                "buy_conditions": [{"expr": spec["cond"], "op": "gt", "rhs": 0}],
                "buy_logic": None,
                "sort_expr": spec.get("sort"), "sort_desc": True,
                "max_tickers": spec["max"], "rebalance_period": "monthly",
                "note": "전략 핵심(모멘텀 랭킹·이동평균 타이밍)을 조건식으로 변환 — 편집 가능. 일부 정교한 로직(13612W 정확가중·카나리아)은 근사."}

    if sid in _STATIC:
        from src.engine.strategy_profiles import _strategy_holdings
        _n, _f, holdings = _strategy_holdings(sid, mk)
        basket = [{"ticker": h["ticker"], "name": h["label"], "weight_pct": h["weight"]} for h in (holdings or [])]
        return {**base, "mode": "asset_alloc", "basket": basket, "rebalance_months": 3,
                "note": "정적 비중 — ETF 바스켓 자산배분(가중 편집 가능)."}

    # 엔진 모드 (최적화 7 + laa): 현재 보유로 유니버스 표기, 실제 백테스트는 동적 엔진
    from src.engine.strategy_profiles import _strategy_holdings
    _n, _f, holdings = _strategy_holdings(sid, mk)
    codes = _codes([h["us_ticker"] for h in (holdings or [])], mk)
    return {**base, "mode": "engine", "engine_strategy": sid,
            "universe_codes": codes, "rebalance_months": 1,
            "note": "공분산 최적화/타이밍형 — 조건식 표현 불가. 실제 동적 엔진(시점평가)으로 충실 실행(조건 편집 불가)."}


# ── 최적화 전략 충실 백테스트 어댑터 (backtest_strategy → ScreenToBacktestResult 셰이프) ──
def _months_between(start: str, end: str) -> int:
    try:
        s = datetime.strptime(start[:10], "%Y-%m-%d")
        e = datetime.strptime(end[:10], "%Y-%m-%d")
        return max(6, (e.year - s.year) * 12 + (e.month - s.month))
    except Exception:
        return 48


def _iso(label: str) -> str:
    try:
        yy, mm = label.split(".")
        return f"20{yy}-{mm}-01"
    except Exception:
        return label


def _ds() -> dict:
    real = bool(os.getenv("KIS_APP_KEY"))
    return {"fundamentals": "mock", "market_data": "KIS" if real else "mock", "fully_real": real}


def _dd_curve(vals: list[float]) -> list[float]:
    out, peak = [], (vals[0] if vals else 1.0)
    for v in vals:
        peak = max(peak, v)
        out.append(round((v - peak) / peak, 4) if peak > 0 else 0.0)
    return out


def _full_stats(vals: list[float], port: list[float]) -> dict:
    total = (vals[-1] / vals[0] - 1) if vals and vals[0] > 0 else 0.0
    n_m = len(port)
    years = n_m / 12.0
    cagr = ((vals[-1] / vals[0]) ** (1 / years) - 1) if (years > 0 and vals and vals[0] > 0) else 0.0
    mean_m = sum(port) / n_m if n_m else 0.0
    var_m = sum((x - mean_m) ** 2 for x in port) / n_m if n_m else 0.0
    ann_ret, ann_vol = mean_m * 12, math.sqrt(var_m) * math.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    downs = [x for x in port if x < 0]
    dd_sd = math.sqrt(sum(x * x for x in downs) / len(downs)) * math.sqrt(12) if downs else 0.0
    sortino = ann_ret / dd_sd if dd_sd > 0 else 0.0
    peak, mdd = (vals[0] if vals else 1.0), 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, (v - peak) / peak)
    calmar = cagr / abs(mdd) if mdd != 0 else 0.0
    wins, losses = [x for x in port if x > 0], [x for x in port if x < 0]
    win_rate = len(wins) / n_m * 100 if n_m else 0.0
    pf = (sum(wins) / abs(sum(losses))) if losses else (999.0 if wins else 0.0)
    return {
        "total_return_pct": round(total * 100, 2), "cagr": round(cagr * 100, 2),
        "sharpe_ratio": round(sharpe, 3), "sortino_ratio": round(sortino, 3), "calmar_ratio": round(calmar, 3),
        "max_drawdown_pct": round(abs(mdd) * 100, 2), "num_trades": n_m,
        "win_rate": round(win_rate, 2), "profit_factor": round(pf, 3),
        "avg_trade_return": round(mean_m * 100, 4), "total_commission": 0.0, "total_slippage": 0.0,
    }


def run_tactical_backtest(sid: str, mk: str, start: str, end: str, capital: float) -> dict:
    """최적화/택티컬 전략의 충실 동적 백테스트 → screen-to-backtest 결과 셰이프로 반환."""
    from src.data.etf_prices import resolve
    from src.engine.strategy_profiles import _strategy_holdings, backtest_strategy
    mk = "kr" if mk == "kr" else "us"
    cap = float(capital or 0) or 10_000_000.0
    cfg = {"strategy": f"tactical:{sid}", "period": f"{start} ~ {end}", "initial_capital": cap}
    empty_bt = {"statistics": {}, "equity_curve": [], "equity_dates": [],
                "drawdown_curve": [], "monthly_returns": [], "trades": []}

    months = _months_between(start, end)
    bt = backtest_strategy(sid, mk, months)
    curve = bt.get("curve") or []
    if not curve:
        return {"error": True, "message": "전략 백테스트 데이터가 없습니다.", "screened_count": 0,
                "backtest": empty_bt, "backtest_config": cfg, "data_source": _ds()}

    vals = [pt["v"] for pt in curve]
    labels = [pt["t"] for pt in curve]
    port = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1] > 0]
    _n, _f, holdings = _strategy_holdings(sid, mk)
    screened = [{"stock_code": resolve(h["us_ticker"], mk)[0], "corp_name": h["us_label"], "composite_score": None}
                for h in (holdings or [])]
    return {
        "error": False, "screened_tickers": screened, "screened_count": len(screened),
        "backtest": {
            "statistics": _full_stats(vals, port),
            "equity_curve": [round(v / 100.0 * cap, 0) for v in vals],
            "equity_dates": [_iso(x) for x in labels],
            "drawdown_curve": _dd_curve(vals),
            "monthly_returns": [{"month": labels[i + 1], "return_pct": round(port[i] * 100, 2)} for i in range(len(port))],
            "trades": [],
        },
        "backtest_config": cfg, "data_source": _ds(),
    }
