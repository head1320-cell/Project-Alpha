"""논리 조건식 (젠포트 논리 레이어) — 파서·Kleene 3치 평가·전략 통합·등가성.

① 파서: 우선순위(and>or)·괄호·not 양형·한정사 중첩(상위 호환)·오류 메시지
② eval_logic: every/any/before 윈도(워밍업 0.5)·Kleene 진리표
③ 전략: "A or B"(기존 AND로는 불가능한 식)·not 제외·every 연속성
④ 등가성: per-bar(generate_signal, 엔진 포맷) == 벡터화(signal_at) — 시장 토큰 포함
   (시장·매크로·수급 토큰이 per-bar 경로에서 1970 epoch 정렬로 죽던 버그 회귀)
⑤ 엔진 on/off 동일 + API 검증 엔드포인트
"""
import numpy as np
import pandas as pd
import pytest

from src import kis_data_fetcher
from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy as cs
from src.kis_strategies.condition_logic import eval_logic, max_lookback, parse_logic

START = "2024-06-03"


# ─── ① 파서 ──────────────────────────────────────────────────────────────────
def test_parser_precedence_and_parens():
    A, B, C = ("label", 0), ("label", 1), ("label", 2)
    assert parse_logic("A or B and C", 3) == ("or", A, ("and", B, C))
    assert parse_logic("(A or B) and C", 3) == ("and", ("or", A, B), C)
    assert parse_logic("not(A) and not B", 2) == ("and", ("not", A), ("not", B))
    assert parse_logic("every(A, 3) and (B or C)", 3) == \
        ("and", ("every", A, 3), ("or", B, C))
    # 한정사 중첩 허용 (가이드 Tip 4의 과거값 우회와 동일 의미 — 상위 호환)
    assert parse_logic("before(every(a,2),1)", 1) == ("before", ("every", A, 2), 1)


@pytest.mark.parametrize("expr,msg", [
    ("D and A", "조건 D"),            # 라벨 범위 초과
    ("A and", "'and' 뒤에"),
    ("every(A)", "쉼표"),
    ("A B", "남았습니다"),
    ("every(A, 0)", "1~500"),
    ("foo(A,3)", "알 수 없는 키워드"),
    ("", "비어"),
    ("A @ B", "해석할 수 없는 문자"),
])
def test_parser_errors(expr, msg):
    with pytest.raises(ValueError, match=msg):
        parse_logic(expr, 3)


def test_max_lookback():
    assert max_lookback(parse_logic("A and B", 2)) == 0
    assert max_lookback(parse_logic("every(A,5) or B", 2)) == 5
    assert max_lookback(parse_logic("before(every(A,5),3)", 1)) == 8


# ─── ② Kleene 3치 평가 ───────────────────────────────────────────────────────
def _arr(*v):
    return np.array(v, dtype=float)


def test_kleene_truth_table():
    env = [_arr(1), _arr(0), _arr(0.5)]  # A=참, B=거짓, C=평가불가

    def ev(e: str) -> float:
        return eval_logic(parse_logic(e, 3), env)[0]

    assert ev("A and C") == 0.5     # and(T,U)=U
    assert ev("B and C") == 0.0     # and(F,U)=F
    assert ev("A or C") == 1.0      # or(T,U)=T
    assert ev("B or C") == 0.5      # or(F,U)=U
    assert ev("not C") == 0.5       # not(U)=U
    assert ev("not B") == 1.0


def test_temporal_windows():
    env = [_arr(1, 1, 0, 1, 1)]
    assert list(eval_logic(parse_logic("every(A,2)", 1), env)) == [0.5, 1, 0, 0, 1]
    env = [_arr(0, 0, 1, 0, 0)]
    assert list(eval_logic(parse_logic("any(A,2)", 1), env)) == [0.5, 0, 1, 1, 0]
    env = [_arr(1, 0, 0, 0)]
    assert list(eval_logic(parse_logic("before(A,2)", 1), env)) == [0.5, 0.5, 1, 0]
    # 윈도 내 평가 불가(U) 전파: False는 없고 U가 있으면 U
    env = [_arr(1, 0.5, 1)]
    assert list(eval_logic(parse_logic("every(A,2)", 1), env)) == [0.5, 0.5, 0.5]


# ─── ③ 전략 통합 (synthetic OHLCV) ───────────────────────────────────────────
def make_df(closes, warmup: int = 60, drift: float = 0.0) -> pd.DataFrame:
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=warmup)
    idx = idx.append(pd.bdate_range(start=START, periods=len(closes)))
    w = [100.0 * (1 + drift) ** i for i in range(warmup)]
    close = pd.Series(w + [float(c) for c in closes], index=idx)
    return pd.DataFrame({"open": close * 0.999, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": 50_000.0}, index=idx)


CLOSES = [100, 100, 100, 100, 100, 110, 110, 110, 110, 110,
          110, 110, 110, 110, 110, 97.9, 97.9, 97.9, 97.9, 97.9]
COND_JUMP = {"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
             "op": "gte", "rhs": 5}      # A: +5%↑ (bar5에서만 true)
COND_DROP = {"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
             "op": "lte", "rhs": -5}     # B: -5%↓ (bar15에서만 true)


def actions(strategy, df, tk="000111"):
    strategy.prepare_panel({tk: df})
    strategy.precompute_signals({tk: df})
    return {i: strategy.signal_at(tk, df.index[i]).action.name
            for i in range(60, len(df))}


def test_or_logic_buys_on_either_condition():
    df = make_df(CLOSES)
    s = cs.ConditionStrategy(buy_conditions=[COND_JUMP, COND_DROP], buy_logic="A or B")
    act = actions(s, df)
    assert act[65] == "BUY" and act[75] == "BUY"          # 점프·급락 둘 다 매수
    assert all(v == "HOLD" for i, v in act.items() if i not in (65, 75))
    # 대조: 논리식 없으면 AND — 동시에 성립할 수 없으니 매수 0회
    legacy = cs.ConditionStrategy(buy_conditions=[COND_JUMP, COND_DROP])
    assert all(v == "HOLD" for v in actions(legacy, df).values())


def test_not_logic_excludes():
    df = make_df(CLOSES)
    s = cs.ConditionStrategy(buy_conditions=[COND_JUMP], buy_logic="not A")
    act = actions(s, df)
    assert act[65] == "HOLD"                              # A 성립일은 제외
    assert act[66] == "BUY" and act[75] == "BUY"          # 그 외는 매수


def test_every_requires_consecutive():
    # 하락 추세 속 bar5~9만 +2%씩 상승 → pct(1)>=1.5 가 5일 연속
    closes, v = [], 100.0
    for i in range(20):
        v = v * (1.02 if 5 <= i <= 9 else 0.995)
        closes.append(v)
    df = make_df(closes, drift=-0.005)
    cond = {"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
            "op": "gte", "rhs": 1.5}
    s = cs.ConditionStrategy(buy_conditions=[cond], buy_logic="every(A,3)")
    act = actions(s, df)
    buys = sorted(i for i, v in act.items() if v == "BUY")
    assert buys == [67, 68, 69]                           # 3연속 충족부터 (bar7,8,9)


def test_sell_logic_and():
    # 매도: A and B (둘 다 충족하는 봉에만 청산 신호)
    df = make_df(CLOSES)
    s = cs.ConditionStrategy(
        buy_conditions=[COND_JUMP],
        sell_conditions=[COND_DROP,
                         {"factor_token": "{거래량}", "function_id": "base",
                          "params": {}, "op": "gte", "rhs": 1}],
        sell_logic="A and B")
    act = actions(s, df)
    assert act[75] == "SELL"                              # 급락+거래량≥1 동시 충족
    assert act[74] == "HOLD"


def test_unevaluable_in_logic_is_conservative():
    # 평가 불가 토큰이 and로 묶이면 식 전체가 미지(0.5) → 매매 보류 (Kleene)
    df = make_df(CLOSES)
    s = cs.ConditionStrategy(
        buy_conditions=[COND_JUMP,
                        {"factor_token": "{뉴지스코어}", "function_id": "base",
                         "params": {}, "op": "gte", "rhs": 0}],
        buy_logic="A and B")
    assert all(v == "HOLD" for v in actions(s, df).values())
    # or라면 A 성립으로 충분
    s2 = cs.ConditionStrategy(
        buy_conditions=[COND_JUMP,
                        {"factor_token": "{뉴지스코어}", "function_id": "base",
                         "params": {}, "op": "gte", "rhs": 0}],
        buy_logic="A or B")
    assert actions(s2, df)[65] == "BUY"


def test_invalid_label_raises_at_init():
    with pytest.raises(ValueError, match="조건 C"):
        cs.ConditionStrategy(buy_conditions=[COND_JUMP, COND_DROP], buy_logic="A and C")


# ─── ④ 등가성: per-bar == 벡터화 (시장 토큰 + 횡단면 + 한정사 혼합) ──────────
def engine_format_slice(df: pd.DataFrame, upto: int, ticker: str) -> pd.DataFrame:
    s = df.iloc[:upto + 1]
    out = pd.DataFrame({
        "date": s.index.strftime("%Y%m%d"),
        "open": s["open"].values, "high": s["high"].values,
        "low": s["low"].values, "close": s["close"].values,
        "volume": s["volume"].values,
    })
    out.attrs["ticker"] = ticker
    return out


def test_equivalence_per_bar_vs_vectorized(monkeypatch):
    rng = np.random.RandomState(7)
    omap = {}
    for k, tk in enumerate(["000111", "000222", "000333"]):
        idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=60)
        idx = idx.append(pd.bdate_range(start=START, periods=140))
        close = pd.Series(100 + np.cumsum(rng.normal(0.1, 1.5, 200)), index=idx).clip(lower=20)
        omap[tk] = pd.DataFrame({"open": close * 0.999, "high": close * 1.01,
                                 "low": close * 0.99, "close": close,
                                 "volume": rng.randint(10_000, 90_000, 200).astype(float)},
                                index=idx)
    conds = [
        {"factor_token": "{종가}", "function_id": "pct", "params": {"n": "3"},
         "op": "gte", "rhs": 0},                                   # A
        {"factor_token": "{종가}", "function_id": "rank",
         "params": {"dir": "DESC"}, "op": "lte", "rhs": 2},        # B (횡단면)
        {"factor_token": "{KOSPI지수_종가}", "function_id": "base",
         "params": {}, "op": "gte", "rhs": 0},                     # C (시장 토큰 — per-bar 정렬 회귀)
    ]
    s = cs.ConditionStrategy(buy_conditions=conds,
                             sell_conditions=[COND_DROP],
                             buy_logic="every(A,2) and (B or C)")
    s.prepare_panel(omap)
    s.precompute_signals(omap)

    mismatches = []
    for tk, df in omap.items():
        for t in range(s.required_days, len(df)):
            sl = engine_format_slice(df, t, tk)
            monkeypatch.setattr(kis_data_fetcher, "get_daily_prices",
                                lambda code, days, _sl=sl: _sl)
            per_bar = s.generate_signal(tk, tk).action
            vec = s.signal_at(tk, df.index[t])
            if vec is None or vec.action != per_bar:
                mismatches.append((tk, str(df.index[t].date()), per_bar,
                                   None if vec is None else vec.action))
    assert mismatches == [], f"불일치 {len(mismatches)}건: {mismatches[:5]}"


# ─── ⑤ 엔진 on/off + API ─────────────────────────────────────────────────────
def test_engine_identical_with_logic(monkeypatch):
    from src.kis_strategies import condition_strategy  # noqa: F401
    df = make_df(CLOSES)
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified",
                        lambda ticker, *a, **k: df.copy())

    def run(vec: bool):
        cfg = BacktestConfig(
            symbols=["000111"], strategy_name="Condition",
            strategy_params={"buy_conditions": [COND_JUMP, COND_DROP],
                             "sell_conditions": [COND_DROP], "buy_logic": "A or B"},
            start_date=START, end_date=df.index[-1].strftime("%Y-%m-%d"),
            commission_rate=0.0, slippage_rate=0.0, vectorize_signals=vec)
        e = BacktestEngine(cfg)
        r = e.run()
        assert not r.get("error", False)
        return [(t.date, t.side, t.price, t.quantity) for t in e.trades]

    fast, slow = run(True), run(False)
    assert fast == slow and len(fast) >= 2     # OR 매수 + 급락 매도 발생


def test_validate_endpoint():
    from src.api.screener_routes import LogicValidateRequest, validate_condition_logic
    ok = validate_condition_logic(LogicValidateRequest(expr="every(A,3) and B", n_conditions=2))
    assert ok == {"ok": True, "lookback": 3, "empty": False}
    bad = validate_condition_logic(LogicValidateRequest(expr="A and", n_conditions=2))
    assert bad["ok"] is False and "and" in bad["error"]
    empty = validate_condition_logic(LogicValidateRequest(expr="  ", n_conditions=0))
    assert empty["ok"] is True and empty["empty"] is True
