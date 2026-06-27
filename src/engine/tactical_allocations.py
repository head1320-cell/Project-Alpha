"""택티컬 자산배분 13전략 — 현재 시점 보유자산·비중 계산 (jasan-calc 레퍼런스)
==========================================================================
각 전략의 표준 규칙(절대/상대 모멘텀·이동평균 타이밍·13612W 가속모멘텀)을 현재 시세에 적용해
'지금 무엇을 얼마나 보유하는가'를 산출한다. market="us"(원본 ETF) | "kr"(국내 ETF 매핑).
가격: etf_prices(load_ohlcv_unified). 데이터 없으면 결정론적 mock → 시그널은 항상 산출(실값은 GCP).

규칙 요약:
  · 절대모멘텀: N개월 수익률 > 0 (현금=BIL 대비) 이면 위험자산 보유, 아니면 현금/채권.
  · 상대모멘텀: 후보 중 수익률 1위 선택.
  · 13612W: 12·r1 + 4·r3 + 2·r6 + 1·r12 (가속 모멘텀 점수).
  · MA 타이밍: 종가 > N개월(또는 N일) 이동평균이면 보유.
"""

from __future__ import annotations

from datetime import datetime

from src.data.etf_prices import US_UNIVERSE, daily_closes, monthly_closes


# ── 모멘텀/타이밍 헬퍼 ─────────────────────────────────────────────────────────
def _ret(closes: list[float], months: int) -> float | None:
    if len(closes) < months + 1 or closes[-1 - months] <= 0:
        return None
    return closes[-1] / closes[-1 - months] - 1.0


def _abs_mom(t: str, mk: str, months: int = 12) -> float | None:
    return _ret(monthly_closes(t, mk), months)


def _score_13612(t: str, mk: str) -> float | None:
    c = monthly_closes(t, mk)
    s = 0.0
    for m, w in ((1, 12), (3, 4), (6, 2), (12, 1)):
        r = _ret(c, m)
        if r is None:
            return None
        s += w * r
    return s


def _accel(t: str, mk: str) -> float | None:
    c = monthly_closes(t, mk)
    s = 0.0
    for m in (1, 3, 6):
        r = _ret(c, m)
        if r is None:
            return None
        s += r
    return s


def _above_ma_m(t: str, mk: str, n: int = 10) -> bool | None:
    c = monthly_closes(t, mk, n + 2)
    if len(c) < n + 1:
        return None
    return c[-1] > sum(c[-n - 1:-1]) / n


def _above_ma_d(t: str, mk: str, n: int = 200) -> bool | None:
    c = daily_closes(t, mk, n + 20)
    if len(c) < n + 1:
        return None
    return c[-1] > sum(c[-n:]) / n


def _best(cands: list[str], mk: str, scorer, min_score: float = -1e9) -> str | None:
    scored = [(t, scorer(t, mk)) for t in cands]
    scored = [(t, s) for t, s in scored if s is not None and s > min_score]
    if not scored:
        return None
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0]


def _norm(w: dict[str, float]) -> dict[str, float]:
    tot = sum(v for v in w.values() if v > 0)
    if tot <= 0:
        return {"BIL": 100.0}
    return {k: round(v / tot * 100, 1) for k, v in w.items() if v > 0}


# ── 13 전략 ───────────────────────────────────────────────────────────────────
def s_classic_dm(mk: str) -> dict:
    spy = _abs_mom("SPY", mk, 12)
    if spy is None:
        return _norm({"AGG": 1})
    if spy > 0:
        win = "SPY" if (_abs_mom("SPY", mk, 12) or -9) >= (_abs_mom("EFA", mk, 12) or -9) else "EFA"
        return _norm({win: 1})
    return _norm({"AGG": 1})


def s_composite_dm(mk: str) -> dict:
    sleeves = [("SPY", "EFA"), ("HYG", "LQD"), ("REM", "VNQ"), ("GLD", "PDBC")]
    w: dict[str, float] = {}
    for a, b in sleeves:
        ra, rb = _abs_mom(a, mk, 12), _abs_mom(b, mk, 12)
        pick = a if (ra or -9) >= (rb or -9) else b
        rp = _abs_mom(pick, mk, 12)
        w[pick if (rp is not None and rp > 0) else "BIL"] = w.get(pick if (rp is not None and rp > 0) else "BIL", 0) + 0.25
    return _norm(w)


def s_accel_dm(mk: str) -> dict:
    win = _best(["SPY", "SCZ"], mk, _accel)
    if win and (_accel(win, mk) or -9) > 0:
        return _norm({win: 1})
    return _norm({"TLT": 1})


def s_permanent(_mk: str) -> dict:
    return {"SPY": 25.0, "TLT": 25.0, "GLD": 25.0, "BIL": 25.0}


def s_laa(mk: str) -> dict:
    risk_on = _above_ma_d("SPY", mk, 200)
    fourth = "QQQ" if (risk_on is None or risk_on) else "SHY"
    return {"IWD": 25.0, "GLD": 25.0, "IEF": 25.0, fourth: 25.0}


def s_raa(mk: str) -> dict:
    w: dict[str, float] = {}
    for t in ("QQQ", "IWN", "IEF", "TLT", "GLD"):
        r = _abs_mom(t, mk, 12)
        w[t if (r is not None and r > 0) else "BIL"] = w.get(t if (r is not None and r > 0) else "BIL", 0) + 0.2
    return _norm(w)


def s_gtaa(mk: str) -> dict:
    w: dict[str, float] = {}
    for t in ("SPY", "EFA", "IEF", "PDBC", "VNQ"):
        a = _above_ma_m(t, mk, 10)
        w[t if (a is None or a) else "BIL"] = w.get(t if (a is None or a) else "BIL", 0) + 0.2
    return _norm(w)


def s_paa(mk: str) -> dict:
    risky = ("SPY", "IWM", "QQQ", "EWJ", "EEM")
    good = [t for t in risky if (_above_ma_m(t, mk, 12) is not False)]
    n = len(risky)
    bond_frac = (n - len(good)) / n
    w: dict[str, float] = {"IEF": bond_frac}
    for t in good:
        w[t] = w.get(t, 0) + (1 - bond_frac) / max(1, len(good))
    return _norm(w)


def s_vaa(mk: str) -> dict:
    off = ["SPY", "EFA", "EEM", "AGG"]
    scores = {t: _score_13612(t, mk) for t in off}
    if all(s is not None and s > 0 for s in scores.values()):
        win = _best(off, mk, _score_13612)
        return _norm({win or "SPY": 1})
    win = _best(["LQD", "IEF", "SHY"], mk, _score_13612, min_score=-1e9)
    return _norm({win or "SHY": 1})


def s_faa(mk: str) -> dict:
    uni = ["VTI", "EFA", "EEM", "IEF", "TLT", "GLD", "PDBC", "VNQ"]
    scored = [(t, _ret(monthly_closes(t, mk), 4)) for t in uni]
    scored = [(t, s) for t, s in scored if s is not None]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = [t for t, s in scored[:3] if s > 0]
    if not top:
        return _norm({"BIL": 1})
    return _norm({t: 1 for t in top})


def s_aaa(mk: str) -> dict:
    uni = ["SPY", "EFA", "EEM", "VNQ", "GLD", "PDBC", "IEF", "TLT"]
    pos = [(t, _score_13612(t, mk)) for t in uni]
    pos = [(t, s) for t, s in pos if s is not None and s > 0]
    pos.sort(key=lambda x: x[1], reverse=True)
    chosen = pos[:4]
    if len(chosen) < 2:  # 위험회피 → 방어자산
        return _norm({"IEF": 0.89, "PDBC": 0.11})
    return _norm({t: 1 for t, _ in chosen})


def s_daa(mk: str) -> dict:
    canary_ok = all((_score_13612(t, mk) or -9) > 0 for t in ("EEM", "AGG"))
    if canary_ok:
        uni = ["SPY", "QQQ", "IWM", "EFA", "EEM", "VNQ", "GLD"]
        scored = [(t, _score_13612(t, mk)) for t in uni]
        scored = [(t, s) for t, s in scored if s is not None]
        scored.sort(key=lambda x: x[1], reverse=True)
        top = [t for t, _ in scored[:2]] or ["SPY"]
        return _norm({t: 1 for t in top})
    win = _best(["IEF", "LQD", "SHY"], mk, _score_13612)
    return _norm({win or "SHY": 1})


def s_bond_dynamic(mk: str) -> dict:
    uni = ["TLT", "HYG", "EMB", "IEF", "LQD"]
    scored = [(t, _abs_mom(t, mk, 6)) for t in uni]
    scored = [(t, s) for t, s in scored if s is not None]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = [t for t, s in scored[:3] if s > 0]
    if not top:
        return _norm({"BIL": 1})
    return _norm({t: 1 for t in top})


# (id, 이름, 설명, family, fn) — 기존 13은 전부 "momentum" family
STRATEGIES: list[tuple] = [
    ("classic_dm", "전통 듀얼모멘텀", "절대+상대 모멘텀 1자산 집중", "momentum", s_classic_dm),
    ("composite_dm", "종합 듀얼모멘텀", "4슬리브(주식·채권·부동산·대체) 듀얼모멘텀", "momentum", s_composite_dm),
    ("accel_dm", "가속 듀얼모멘텀", "1+3+6개월 가속 모멘텀", "momentum", s_accel_dm),
    ("permanent", "영구 포트폴리오", "주식·장기채·금·현금 25% 고정", "momentum", s_permanent),
    ("laa", "LAA", "정적 3자산 + 경기 스위치(QQQ/SHY)", "momentum", s_laa),
    ("raa", "RAA", "5자산 절대모멘텀 동일가중", "momentum", s_raa),
    ("gtaa", "GTAA", "5자산 10개월 이동평균 타이밍", "momentum", s_gtaa),
    ("paa", "PAA", "위험자산 MA 타이밍 + 채권 보호", "momentum", s_paa),
    ("vaa", "VAA", "공격/방어 13612W 카나리아", "momentum", s_vaa),
    ("faa", "FAA", "모멘텀 상위 3 동일가중", "momentum", s_faa),
    ("aaa", "AAA", "13612W 상위 + 위험회피 방어", "momentum", s_aaa),
    ("daa", "DAA", "카나리아(EEM·AGG) 공격/방어", "momentum", s_daa),
    ("bond_dynamic", "채권 동적배분", "채권 모멘텀 상위 3", "momentum", s_bond_dynamic),
]

# 리스크·최적화 9전략 합성 → compute_strategies/추천/콕핏이 22종 자동 인식
from src.engine.risk_allocations import RISK_STRATEGIES  # noqa: E402

ALL_STRATEGIES: list[tuple] = STRATEGIES + RISK_STRATEGIES


def _signal(weights: dict[str, float]) -> str:
    defensive = {"BIL", "SHY", "IEF", "TLT", "LQD", "AGG", "EMB", "HYG", "GLD"}
    risk = round(sum(v for k, v in weights.items() if k not in defensive), 0)
    if risk >= 80:
        return "공격적 (위험자산 비중 높음)"
    if risk <= 20:
        return "방어적 (현금·채권 비중 높음)"
    return "중립 (혼합)"


def compute_strategies(market: str = "kr") -> dict:
    """13전략의 현재 보유자산·비중 + 시그널. market: 'kr'(국내 ETF 실데이터, 기본) | 'us'(원본, KIS 미제공→mock)."""
    from src.data.etf_prices import resolve
    mk = "kr" if market == "kr" else "us"
    out = []
    for sid, name, desc, family, fn in ALL_STRATEGIES:
        try:
            weights = fn(mk)
        except Exception:
            weights = {"BIL": 100.0}
        holdings = [{"ticker": resolve(t, mk)[0], "label": resolve(t, mk)[1],
                     "us_ticker": t, "us_label": US_UNIVERSE.get(t, t), "weight": w}
                    for t, w in sorted(weights.items(), key=lambda x: -x[1])]
        out.append({"id": sid, "name": name, "description": desc, "family": family,
                    "signal": _signal(weights), "holdings": holdings})
    return {"market": mk, "as_of": datetime.now().strftime("%Y-%m-%d"), "strategies": out}
