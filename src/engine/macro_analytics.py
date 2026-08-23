"""매크로 분석 — 자산 상관관계 추이 · 마켓타이밍 시점 · 국면 궤적
==========================================================================
자산배분 의사결정 직결 분석. 전부 현 데이터(daily_closes + 기존 매크로 시계열)로 산출.
  · correlation_panel: 13자산 상관행렬 + 롤링 주식-채권 상관 + 평균 페어상관(분산 국면).
  · timing_panel: 위험 온/오프 종합(200일선 breadth·모멘텀·수익률곡선·HY신용·VIX) + 자산별 추세표.
  · regime_trajectory: 테마-z 프록시로 최근 18개월 국면 경로 + 전환 시점.
DB가 쌓일수록(etf_prices ~5년 윈도우 + prewarm) 롤링 추이가 자동 장기화. mock도 ~5년 생성.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import numpy as np

from src.data.etf_prices import daily_closes, monthly_closes

logger = logging.getLogger(__name__)

# 확장 13자산 (주식·채권·신용·실물·물가)
_ANALYTICS_UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "LQD", "HYG", "GLD", "PDBC", "VNQ", "TIP"]
_LABELS = {
    "SPY": "미국 대형주", "QQQ": "나스닥100", "IWM": "미국 소형주", "EFA": "선진국(미국제외)", "EEM": "신흥국",
    "TLT": "미 장기국채", "IEF": "미 중기국채", "LQD": "IG 회사채", "HYG": "하이일드", "GLD": "금",
    "PDBC": "원자재", "VNQ": "미국 리츠", "TIP": "물가연동채",
}
_RISK_ASSETS = ["SPY", "QQQ", "IWM", "EFA", "EEM", "VNQ", "HYG"]  # breadth/모멘텀용 위험자산
_LOOKBACK = 1300  # 일간 룩백 (~5년, DB/mock 깊이만큼)
_PAIR_DEFS = [("SPY", "TLT", "주식-장기채"), ("SPY", "GLD", "주식-금"),
              ("SPY", "PDBC", "주식-원자재"), ("SPY", "EEM", "주식-신흥국"), ("SPY", "HYG", "주식-하이일드")]


def _real_prices() -> bool:
    return bool(os.getenv("KIS_APP_KEY"))


def _real_fred() -> bool:
    return bool(os.getenv("FRED_API_KEY"))


def _clamp1(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


# ── 수익률/상관 ──────────────────────────────────────────────────────────────
def _closes_map(tickers: list[str], mk: str, lookback: int) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for t in tickers:
        c = daily_closes(t, mk, lookback)
        if len(c) >= 80:
            out[t] = c
    return out


def _aligned_returns(closes_map: dict[str, list[float]]):
    names = list(closes_map.keys())
    if len(names) < 2:
        return [], None
    L = min(len(closes_map[t]) for t in names)
    cols = []
    for t in names:
        arr = np.asarray(closes_map[t][-L:], dtype=float)
        cols.append(arr[1:] / arr[:-1] - 1.0)
    return names, np.vstack(cols).T  # [obs, n]


def _rolling_corr(a: list[float], b: list[float], window: int = 60) -> list[float]:
    aa, bb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    n = len(aa)
    if n < window:
        return []
    out = []
    for i in range(window, n + 1):
        wa, wb = aa[i - window:i], bb[i - window:i]
        if wa.std() > 0 and wb.std() > 0:
            out.append(round(float(np.corrcoef(wa, wb)[0, 1]), 3))
        else:
            out.append(0.0)
    return out


def _rolling_avg_corr(R: np.ndarray, window: int = 60) -> list[float]:
    n = R.shape[0]
    if n < window:
        return []
    iu = np.triu_indices(R.shape[1], k=1)
    out = []
    for i in range(window, n + 1):
        C = np.corrcoef(R[i - window:i], rowvar=False)
        out.append(round(float(np.nanmean(C[iu])), 3))
    return out


def _series_with_dates(arr: list[float], max_points: int = 160) -> list[dict]:
    n = len(arr)
    if n == 0:
        return []
    step = max(1, n // max_points)
    today = datetime.now()
    out = []
    for i in range(0, n, step):
        days_back = int((n - 1 - i) * 1.45)  # 거래일→대략 캘린더일
        out.append({"t": (today - timedelta(days=days_back)).strftime("%y.%m"), "corr": arr[i]})
    if (n - 1) % step != 0:
        out.append({"t": today.strftime("%y.%m"), "corr": arr[-1]})
    return out


def correlation_panel(mk: str = "us") -> dict:
    cm = _closes_map(_ANALYTICS_UNIVERSE, mk, _LOOKBACK)
    names, R = _aligned_returns(cm)
    empty = {"matrix": {"tickers": [], "labels": [], "values": []}, "pairs": [], "avg_corr": [],
             "stock_bond_now": {"corr": None, "verdict": "중립"}, "sources": {"prices": _real_prices()}}
    if not names or R is None or R.shape[0] < 5:
        return empty
    recent = R[-252:] if R.shape[0] > 252 else R
    C = np.corrcoef(recent, rowvar=False)
    matrix = {"tickers": names, "labels": [_LABELS.get(t, t) for t in names],
              "values": [[round(float(C[i, j]), 3) for j in range(len(names))] for i in range(len(names))]}
    idx = {t: i for i, t in enumerate(names)}
    pairs = []
    for a, b, lbl in _PAIR_DEFS:
        if a in idx and b in idx:
            rc = _rolling_corr(list(R[:, idx[a]]), list(R[:, idx[b]]), 60)
            pairs.append({"key": f"{a}-{b}", "label": lbl, "series": _series_with_dates(rc)})
    avg_corr = _series_with_dates(_rolling_avg_corr(R, 60))
    sb = float(C[idx["SPY"], idx["TLT"]]) if ("SPY" in idx and "TLT" in idx) else None
    verdict = "헤지" if (sb is not None and sb < -0.2) else ("동조" if (sb is not None and sb > 0.2) else "중립")
    return {"matrix": matrix, "pairs": pairs, "avg_corr": avg_corr,
            "stock_bond_now": {"corr": round(sb, 3) if sb is not None else None, "verdict": verdict},
            "sources": {"prices": _real_prices()}}


# ── 마켓타이밍 ───────────────────────────────────────────────────────────────
def _rsi(arr: np.ndarray, n: int = 14):
    if len(arr) < n + 1:
        return None
    d = np.diff(arr[-(n + 1):])
    gains = float(d[d > 0].sum())
    losses = float(-d[d < 0].sum())
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100.0 - 100.0 / (1.0 + rs)


def _asset_trend(t: str, mk: str, closes: list[float] | None = None) -> dict:
    if closes is None:
        closes = daily_closes(t, mk, _LOOKBACK)
    label = _LABELS.get(t, t)
    base = {"ticker": t, "label": label, "vs_ma200_pct": None, "mom_12m": None,
            "dist_52w_high": None, "rsi": None, "trend": "중립"}
    if not closes or len(closes) < 30:
        return base
    arr = np.asarray(closes, dtype=float)
    price = float(arr[-1])
    ma200 = float(arr[-200:].mean()) if len(arr) >= 200 else float(arr.mean())
    vs_ma = (price / ma200 - 1) * 100 if ma200 > 0 else None
    mc = monthly_closes(t, mk, 14)
    mom = (mc[-1] / mc[-13] - 1) * 100 if (len(mc) >= 13 and mc[-13] > 0) else None
    hi52 = float(arr[-252:].max()) if len(arr) >= 252 else float(arr.max())
    dist = (price / hi52 - 1) * 100 if hi52 > 0 else None
    rsi = _rsi(arr, 14)
    above = vs_ma is not None and vs_ma > 0
    pos_mom = mom is not None and mom > 0
    trend = "상승" if (above and pos_mom) else ("하락" if (not above and not pos_mom) else "중립")
    return {"ticker": t, "label": label,
            "vs_ma200_pct": round(vs_ma, 1) if vs_ma is not None else None,
            "mom_12m": round(mom, 1) if mom is not None else None,
            "dist_52w_high": round(dist, 1) if dist is not None else None,
            "rsi": round(rsi, 1) if rsi is not None else None, "trend": trend}


def _breadth_above_ma(closes_map: dict[str, list[float]], n: int = 200):
    cnt = tot = 0
    for c in closes_map.values():
        if len(c) < 30:
            continue
        arr = np.asarray(c, dtype=float)
        ma = arr[-n:].mean() if len(arr) >= n else arr.mean()
        tot += 1
        cnt += 1 if arr[-1] > ma else 0
    return (cnt / tot * 100) if tot else None


def _breadth_pos_mom(tickers: list[str], mk: str):
    cnt = tot = 0
    for t in tickers:
        mc = monthly_closes(t, mk, 14)
        if len(mc) >= 13 and mc[-13] > 0:
            tot += 1
            cnt += 1 if (mc[-1] / mc[-13] - 1) > 0 else 0
    return (cnt / tot * 100) if tot else None


def _yc_score(spread):   # T10Y2Y: 정상(가파름)=온, 역전=오프
    return _clip((spread + 1.0) / 2.0 * 100)


def _credit_score(spread):  # HY 스프레드(%): 타이트=온
    return _clip((8.0 - spread) / 5.0 * 100)


def _vix_score(vix):     # VIX: 저=온
    return _clip((30.0 - vix) / 18.0 * 100)


def _macro_series():
    from src.services.macro_collector import MacroCollector
    return MacroCollector.get_default().collect_all().series


def _latest(series, sid):
    s = series.get(sid)
    return s.latest if s else None


def _or50(x):
    return x if x is not None else 50.0


def _breadth_at(closes_map, k, n=200):
    cnt = tot = 0
    for c in closes_map.values():
        arr = np.asarray(c, dtype=float)
        idx = len(arr) - 1 - k
        if idx < n:
            continue
        tot += 1
        cnt += 1 if arr[idx] > arr[idx - n + 1:idx + 1].mean() else 0
    return (cnt / tot * 100) if tot else None


def _mom_at(closes_map, k):
    cnt = tot = 0
    for c in closes_map.values():
        arr = np.asarray(c, dtype=float)
        idx = len(arr) - 1 - k
        if idx < 252:
            continue
        tot += 1
        cnt += 1 if (arr[idx] / arr[idx - 252] - 1) > 0 else 0
    return (cnt / tot * 100) if tot else None


def _timing_history(risk_cm, series, n_months: int = 18) -> list[dict]:
    def marr(sid):
        s = series.get(sid)
        vals = [v for v in (s.values if s else []) if v is not None]
        return vals[-n_months:] if vals else []
    yc_a, cr_a, vx_a = marr("T10Y2Y"), marr("BAMLH0A0HYM2"), marr("VIXCLS")
    m = min(len(yc_a), len(cr_a), len(vx_a), n_months)
    if m == 0:
        return []
    today = datetime.now()
    hist = []
    for j in range(m):
        back = m - 1 - j
        k = back * 21
        b = _or50(_breadth_at(risk_cm, k, 200))
        mo = _or50(_mom_at(risk_cm, k))
        yc, cr, vx = yc_a[len(yc_a) - m + j], cr_a[len(cr_a) - m + j], vx_a[len(vx_a) - m + j]
        comp = (b * 25 + mo * 20 + _yc_score(yc) * 20 + _credit_score(cr) * 20 + _vix_score(vx) * 15) / 100
        hist.append({"t": (today - timedelta(days=back * 30)).strftime("%y.%m"), "score": round(comp, 0)})
    return hist


def timing_panel(mk: str = "us") -> dict:
    cm = _closes_map(_ANALYTICS_UNIVERSE, mk, _LOOKBACK)
    assets = [_asset_trend(t, mk, cm.get(t)) for t in _ANALYTICS_UNIVERSE]
    risk_cm = {t: cm[t] for t in _RISK_ASSETS if t in cm}
    breadth = _breadth_above_ma(risk_cm, 200)
    mom_b = _breadth_pos_mom(_RISK_ASSETS, mk)
    series = _macro_series()
    yc, credit, vix = _latest(series, "T10Y2Y"), _latest(series, "BAMLH0A0HYM2"), _latest(series, "VIXCLS")
    components = [
        {"key": "breadth", "label": "200일선 상회 비율", "value": round(breadth, 0) if breadth is not None else None,
         "score": round(_or50(breadth), 0), "weight": 25},
        {"key": "mom_breadth", "label": "12개월 모멘텀 폭", "value": round(mom_b, 0) if mom_b is not None else None,
         "score": round(_or50(mom_b), 0), "weight": 20},
        {"key": "yield_curve", "label": "수익률곡선(T10Y2Y)", "value": round(yc, 2) if yc is not None else None,
         "score": round(_yc_score(yc) if yc is not None else 50, 0), "weight": 20},
        {"key": "credit", "label": "HY 신용 스프레드", "value": round(credit, 2) if credit is not None else None,
         "score": round(_credit_score(credit) if credit is not None else 50, 0), "weight": 20},
        {"key": "vix", "label": "VIX 변동성", "value": round(vix, 1) if vix is not None else None,
         "score": round(_vix_score(vix) if vix is not None else 50, 0), "weight": 15},
    ]
    score = sum(c["score"] * c["weight"] for c in components) / 100
    label = "위험 선호" if score >= 60 else ("위험 회피" if score <= 40 else "중립")
    return {"composite": {"score": round(score, 1), "label": label}, "components": components,
            "history": _timing_history(risk_cm, series), "assets": assets,
            "sources": {"prices": _real_prices(), "fred": _real_fred()}}


# ── 국면 궤적 — regime_axes 단일 정의 공유 (헤더 국면과 항상 일치) ────────────
def regime_trajectory(n_months: int = 18, market: str = "kr") -> dict:
    from src.engine.regime_axes import AXES, compute_axis, quadrant
    series = _macro_series()
    g_def, i_def = AXES.get(market, AXES["kr"])

    today = datetime.now()
    path = []
    for back in range(n_months - 1, -1, -1):
        g = _clamp1(compute_axis(series, g_def, back=back) / 2.0)
        infl = _clamp1(compute_axis(series, i_def, back=back) / 2.0)
        path.append({"t": (today - timedelta(days=back * 30)).strftime("%y.%m"),
                     "growth": round(g, 3), "inflation": round(infl, 3), "quadrant": quadrant(g, infl)})
    transitions = [{"t": path[i]["t"], "from": path[i - 1]["quadrant"], "to": path[i]["quadrant"]}
                   for i in range(1, len(path)) if path[i]["quadrant"] != path[i - 1]["quadrant"]]
    return {"path": path, "transitions": transitions, "market": market,
            "sources": {"fred": _real_fred(), "bok": bool(os.getenv("BOK_API_KEY"))}}
