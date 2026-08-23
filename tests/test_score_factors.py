"""점수 팩터 근사 (뉴지랭크 공개 레시피) — 합성·방향·정직성·전략 통합·등가성.

① 패널 합성: 상승 종목의 가격점수 > 하락 종목 / 종합 = (모멘텀+펀더멘탈)/2
② 정직성: 펀더멘털 없으면 성장·가치·펀더멘탈·종합 패널 없음 (정의를 조용히 안 바꿈)
③ 방향: PER 낮을수록 가치점수↑ / PER≤0 제외 (가이드 명시)
④ 전략 통합: 점수 토큰 + 함수 체인(이동평균) / required_days 워밍업 / 등가성
⑤ 토큰 등록: token_support 'score' 그룹 + 워밍업 봉수
"""
import numpy as np
import pandas as pd

from src import kis_data_fetcher
from src.kis_strategies import condition_strategy as cs
from src.kis_strategies.factor_tokens import token_min_bars, token_support
from src.kis_strategies.score_factors import SCORE_TOKENS, build_score_panels


def make_map(n: int = 220) -> dict:
    rng = np.random.RandomState(3)
    omap = {}
    for i, tk in enumerate(["000111", "000222", "000333"]):
        idx = pd.bdate_range("2023-06-01", periods=n)
        drift = [0.4, 0.05, -0.3][i]          # 상승 / 횡보 / 하락
        close = pd.Series(100 + np.cumsum(rng.normal(drift, 1.2, n)), index=idx).clip(lower=20)
        omap[tk] = pd.DataFrame({"open": close * 0.999, "high": close * 1.01,
                                 "low": close * 0.99, "close": close,
                                 "volume": rng.randint(10_000, 90_000, n).astype(float)},
                                index=idx)
    return omap


FUNDS = {
    "000111": {"roe": 15.0, "per": 8.0, "pbr": 0.9,
               "revenue_growth_yoy": 20.0, "op_growth_yoy": 30.0, "eps_growth_yoy": 25.0},
    "000222": {"roe": 8.0, "per": 15.0, "pbr": 1.5,
               "revenue_growth_yoy": 5.0, "op_growth_yoy": 3.0, "eps_growth_yoy": 4.0},
    "000333": {"roe": 2.0, "per": -3.0, "pbr": 3.0,   # 적자(PER<0) — PER 제외돼야 함
               "revenue_growth_yoy": -10.0, "op_growth_yoy": -20.0, "eps_growth_yoy": -15.0},
}


# ─── ① 합성 ──────────────────────────────────────────────────────────────────
def test_price_score_ranks_uptrend_higher():
    panels = build_score_panels(make_map())
    # 단일 봉은 노이즈 — 최근 60봉 평균으로 구조적 우위 확인
    avg = panels["가격점수"].tail(60).mean()
    assert avg["000111"] > avg["000222"] > avg["000333"]   # 상승 > 횡보 > 하락


def test_total_is_mean_of_momentum_and_fundamental():
    panels = build_score_panels(make_map(), FUNDS)
    assert set(panels) == set(SCORE_TOKENS)           # 7종 전부
    m, f, t = panels["모멘텀점수"], panels["펀더멘탈점수"], panels["종합점수"]
    expect = (m + f) / 2.0
    pd.testing.assert_frame_equal(t, expect, check_like=True)


# ─── ② 정직성 ────────────────────────────────────────────────────────────────
def test_without_fundamentals_only_momentum_leg():
    panels = build_score_panels(make_map())
    assert set(panels) == {"가격점수", "수급점수", "모멘텀점수"}


# ─── ③ 방향 ──────────────────────────────────────────────────────────────────
def test_value_direction_and_per_exclusion():
    panels = build_score_panels(make_map(), FUNDS)
    last = panels["가치점수"].iloc[-1]
    # ROE 높고 PER/PBR 낮은 000111이 최고
    assert last["000111"] > last["000222"] > last["000333"]
    # 적자(PER<0) 종목도 ROE/PBR로 가치점수는 정의됨 (PER 요소만 제외)
    assert not pd.isna(last["000333"])


# ─── ④ 전략 통합 ─────────────────────────────────────────────────────────────
def test_strategy_with_score_and_function_chain():
    omap = make_map()
    cond = [{"factor_token": "{모멘텀점수}", "function_id": "ma", "params": {"n": "5"},
             "op": "gte", "rhs": 60}]                 # 이동평균({모멘텀점수},5) >= 60
    s = cs.ConditionStrategy(buy_conditions=cond)
    assert s.required_days >= 85 + 10                 # 점수 워밍업 반영
    s.prepare_panel(omap)
    s.precompute_signals(omap)
    acts = {tk: [s.signal_at(tk, d).action.name for d in df.index[s.required_days:]]
            for tk, df in omap.items()}
    n_buy = {tk: a.count("BUY") for tk, a in acts.items()}
    assert n_buy["000111"] > n_buy["000333"]          # 상승 종목이 더 자주 매수
    assert n_buy["000111"] > 0


def engine_format_slice(df, upto, ticker):
    s = df.iloc[:upto + 1]
    out = pd.DataFrame({"date": s.index.strftime("%Y%m%d"),
                        "open": s["open"].values, "high": s["high"].values,
                        "low": s["low"].values, "close": s["close"].values,
                        "volume": s["volume"].values})
    out.attrs["ticker"] = ticker
    return out


def test_score_equivalence_per_bar_vs_vectorized(monkeypatch):
    omap = make_map(160)
    cond = [{"factor_token": "{가격점수}", "function_id": "base", "params": {},
             "op": "gte", "rhs": 55}]
    s = cs.ConditionStrategy(buy_conditions=cond)
    s.prepare_panel(omap)
    s.precompute_signals(omap)
    mismatches = []
    for tk, df in omap.items():
        for t in range(s.required_days, len(df), 3):
            sl = engine_format_slice(df, t, tk)
            monkeypatch.setattr(kis_data_fetcher, "get_daily_prices",
                                lambda code, days, _sl=sl: _sl)
            per_bar = s.generate_signal(tk, tk).action
            vec = s.signal_at(tk, df.index[t])
            if vec is None or vec.action != per_bar:
                mismatches.append((tk, str(df.index[t].date())))
    assert mismatches == [], f"불일치 {len(mismatches)}건"


# ─── ⑤ 토큰 등록 ─────────────────────────────────────────────────────────────
def test_token_support_registration():
    sup = token_support()
    for t in SCORE_TOKENS:
        assert sup["supported"].get(t) == "score"
        assert t not in sup["unsupported"]
    assert "score_note" in sup and "근사" in sup["score_note"]
    assert token_min_bars("{종합점수}") == 85
