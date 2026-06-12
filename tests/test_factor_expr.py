"""자유 산술 팩터식 (D-12) + 우선순위식 (D-11) + AI 변환 (D-14).

① 파서: 우선순위·괄호·인용부호·기간/정렬 인자·가이드 예시 5종·오류
② 평가: 함수 경로와의 항등식, 가이드 40일 신고가 식 수동 일치, 0나눗셈 NaN
③ 횡단면 expr: 비율내림차순 — 패널 경유
④ 엔진 우선순위식: max_positions=1에서 식 값 높은 종목 먼저 매수
⑤ 검증·AI 엔드포인트
"""
import numpy as np
import pandas as pd
import pytest

from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy as cs
from src.kis_strategies.factor_expr import (
    canonical,
    expr_lookback,
    expr_tokens,
    parse_expr,
)


# ─── ① 파서 ──────────────────────────────────────────────────────────────────
def test_parser_guide_examples():
    cases = {
        "({분기영업현금흐름}-{분기순이익})": 0,
        "{종가} / 과거값('최고값({고가},{40일})',{1일})": 41,
        "(1/표준편차({일별주가상승률},{20일}))*100": 20,
        "비율내림차순('{시가총액}*1')": 0,
        "큰개수('{일별주가상승률}+1',{10일},{0})": 10,
    }
    for expr, lb in cases.items():
        ast = parse_expr(expr)
        assert expr_lookback(ast) == lb, expr


def test_parser_precedence_and_units():
    ast = parse_expr("{종가}+{시가}*2")
    assert ast[1] == "+" and ast[3][1] == "*"          # * 가 먼저
    assert parse_expr("과거값({당기순이익},{1년})")[3]["n"] == 252  # 1년=252거래일


@pytest.mark.parametrize("expr,msg", [
    ("{종가} +", "피연산자"),
    ("이동평균({종가})", "기간 인자"),
    ("({종가}", "닫히지"),
    ("5+3", "팩터가 없습니다"),
    ("미지의함수({종가})", "알 수 없는 이름"),
    ("{종가} @ 2", "해석할 수 없는 문자"),
])
def test_parser_errors(expr, msg):
    with pytest.raises(ValueError, match=msg):
        parse_expr(expr)


def test_nested_cross_rejected_at_strategy():
    with pytest.raises(ValueError, match="중첩"):
        cs.ConditionStrategy(buy_conditions=[
            {"expr": "순위내림차순('비율내림차순({종가})')", "op": "lte", "rhs": 5}])


def test_canonical_stable():
    a = canonical(parse_expr("비율내림차순({종가})"))
    b = canonical(parse_expr("비율내림차순( {종가} )"))
    assert a == b
    assert expr_tokens(parse_expr("{종가}/{시가}")) == {"종가", "시가"}


# ─── ② 평가 ──────────────────────────────────────────────────────────────────
def make_df(seed=5, n=140, mult=1.0):
    rng = np.random.RandomState(seed)
    idx = pd.bdate_range("2024-01-02", periods=n)
    close = pd.Series(100 + np.cumsum(rng.normal(0.1, 1.5, n)), index=idx).clip(lower=20) * mult
    return pd.DataFrame({"open": close * 0.99, "high": close * 1.02,
                         "low": close * 0.98, "close": close, "volume": 50_000.0}, index=idx)


def test_expr_equals_function_path():
    df = make_df()
    s = cs.ConditionStrategy(buy_conditions=[{"expr": "변화율_기간({종가},{5일})", "op": "gte", "rhs": 0}])
    a = s._cond_arrays(df, s.buy_conditions[0], None, "T")
    b = s._cond_arrays(df, {"factor_token": "{종가}", "function_id": "pct",
                            "params": {"n": "5"}, "op": "gte", "rhs": 0}, None, "T")
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


def test_expr_breakout_formula_matches_manual():
    df = make_df()
    s = cs.ConditionStrategy(buy_conditions=[
        {"expr": "{종가}/과거값('최고값({고가},{40일})',{1일})", "op": "gte", "rhs": 1.0}])
    ser = s._eval_expr_series(s.buy_conditions[0]["_expr_ast"], df, None, "T")
    manual = df["close"] / df["high"].rolling(40).max().shift(1)
    assert np.allclose(ser.dropna(), manual.dropna())


def test_expr_division_by_zero_is_nan_skip():
    df = make_df()
    s = cs.ConditionStrategy(buy_conditions=[
        {"expr": "{종가}/({종가}-{종가})", "op": "gte", "rhs": 0}])
    pair = s._cond_arrays(df, s.buy_conditions[0], None, "T")
    assert pair is not None and not pair[0].any()       # 전 봉 평가 불가 (NaN)


def test_expr_unknown_token_skips():
    df = make_df()
    s = cs.ConditionStrategy(buy_conditions=[{"expr": "{뉴지스코어}*2", "op": "gte", "rhs": 0}])
    assert s._cond_arrays(df, s.buy_conditions[0], None, "T") is None


# ─── ③ 횡단면 expr ───────────────────────────────────────────────────────────
def make_map():
    return {tk: make_df(mult=1 + 0.2 * i) for i, tk in enumerate(["000111", "000222", "000333"])}


def test_cross_expr_top_percentile():
    omap = make_map()
    s = cs.ConditionStrategy(buy_conditions=[{"expr": "비율내림차순({종가})", "op": "gte", "rhs": 99}])
    s.prepare_panel(omap)
    s.precompute_signals(omap)
    last = omap["000333"].index[-1]
    assert s.signal_at("000333", last).action.name == "BUY"   # 최고가 종목
    assert s.signal_at("000111", last).action.name == "HOLD"


# ─── ④ 엔진 우선순위식 ───────────────────────────────────────────────────────
def test_buy_sort_expr_orders_buys(monkeypatch):
    from src.kis_strategies import condition_strategy  # noqa: F401
    omap = make_map()  # 000333이 종가 최고
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified",
                        lambda ticker, *a, **k: omap.get(str(ticker), make_df(9)).copy())

    def run(desc: bool):
        cfg = BacktestConfig(
            symbols=["000111", "000222", "000333"], strategy_name="Condition",
            strategy_params={"buy_conditions": [
                {"factor_token": "{종가}", "function_id": "base", "params": {},
                 "op": "gte", "rhs": 0}]},          # 매일 전 종목 매수 신호
            start_date="2024-04-01", end_date="2024-07-01",
            commission_rate=0.0, slippage_rate=0.0, max_positions=1,
            buy_sort_expr="{종가}", buy_sort_desc=desc)
        e = BacktestEngine(cfg)
        r = e.run()
        assert not r.get("error", False)
        return [t.ticker for t in e.trades if t.side == "buy"][0]

    assert run(True) == "000333"                     # 높은순 → 최고가 종목 먼저
    assert run(False) == "000111"                    # 낮은순 → 최저가 종목 먼저


# ─── ⑤ 검증·AI 엔드포인트 ────────────────────────────────────────────────────
def test_validate_expr_endpoint():
    from src.api.screener_routes import ExprValidateRequest, validate_factor_expr
    ok = validate_factor_expr(ExprValidateRequest(expr="이동평균({거래대금},{5일})/1000000"))
    assert ok["ok"] is True and ok["lookback"] == 5 and "거래대금" in ok["tokens"]
    bad = validate_factor_expr(ExprValidateRequest(expr="{종가}+"))
    assert bad["ok"] is False
    warn = validate_factor_expr(ExprValidateRequest(expr="{뉴지스코어}*1"))
    assert warn["ok"] is True and warn["unknown_tokens"] == ["뉴지스코어"]


def test_condition_nl_endpoint():
    from src.api.screener_routes import ConditionNLRequest, condition_from_nl
    r = condition_from_nl(ConditionNLRequest(query="ROE 높은 우량주"))
    assert isinstance(r["conditions"], list)
    # rank_mode(top_pct) → 비율내림차순 산술식으로 변환
    exprs = [c.get("expr") for c in r["conditions"] if c.get("expr")]
    assert any("비율내림차순" in (e or "") for e in exprs) or r["conditions"] == []
    assert "note" in r
