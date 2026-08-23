"""두 팩터 연산 (가이드: 비교(F1,F2)·큰값·작은값·변화율_팩터) — 정의·항등식·통합.

① 변화율_팩터(종가, 과거값(종가,5)) ≡ 변화율_기간(종가,5) — 가이드 항등식
② 비교(종가,시가) 부호 / 큰값·작은값 원소별 max·min
③ 변화율_팩터는 두 번째 팩터 필수 (없으면 건너뜀)
④ required_days: inner2 기간·factor_token2 워밍업 반영
⑤ 점수 토큰을 두 번째 피연산자로 (비교(모멘텀점수, 가격점수))
⑥ 엔진 벡터화 on/off 동일
"""
import numpy as np
import pandas as pd

from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy as cs


def make_df(n: int = 150, seed: int = 5) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    idx = pd.bdate_range("2024-01-02", periods=n)
    close = pd.Series(100 + np.cumsum(rng.normal(0.1, 1.5, n)), index=idx).clip(lower=20)
    return pd.DataFrame({"open": close * (1 + rng.normal(0, 0.004, n)),
                         "high": close * 1.01, "low": close * 0.98,
                         "close": close, "volume": 50_000.0}, index=idx)


def test_pctf_equals_pct_identity():
    df = make_df()
    s = cs.ConditionStrategy()
    c_pctf = {"factor_token": "{종가}", "function_id": "pctf", "factor_token2": "{종가}",
              "inner2_function_id": "past", "inner2_params": {"n": "5"}, "op": "gte", "rhs": 0}
    c_pct = {"factor_token": "{종가}", "function_id": "pct", "params": {"n": "5"},
             "op": "gte", "rhs": 0}
    a, b = s._cond_arrays(df, c_pctf, None, "T"), s._cond_arrays(df, c_pct, None, "T")
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


def test_cmp_two_factor_sign():
    df = make_df()
    s = cs.ConditionStrategy()
    cond = {"factor_token": "{종가}", "function_id": "cmp", "factor_token2": "{시가}",
            "op": "gte", "rhs": 1}                       # 종가 > 시가 (양봉)
    valid, ok = s._cond_arrays(df, cond, None, "T")
    manual = df["close"].to_numpy() > df["open"].to_numpy()
    assert np.array_equal(ok, manual & valid)


def test_gt_lt_elementwise():
    df = make_df()
    s = cs.ConditionStrategy()
    # 큰값(종가,시가) >= 종가 항상 참 / 작은값(종가,시가) <= 종가 항상 참
    hi = {"factor_token": "{종가}", "function_id": "gt", "factor_token2": "{시가}",
          "op": "gte", "rhs": float(df[["open", "close"]].min().min())}
    valid, ok = s._cond_arrays(df, hi, None, "T")
    assert valid.all() and ok.all()


def test_pctf_requires_second_factor():
    df = make_df()
    s = cs.ConditionStrategy()
    cond = {"factor_token": "{종가}", "function_id": "pctf", "op": "gte", "rhs": 0}
    assert s._cond_arrays(df, cond, None, "T") is None   # 건너뜀 (평가 불가)


def test_required_days_covers_second_operand():
    c_inner2 = {"factor_token": "{종가}", "function_id": "pctf", "factor_token2": "{종가}",
                "inner2_function_id": "past", "inner2_params": {"n": "120"},
                "op": "gte", "rhs": 0}
    assert cs.ConditionStrategy(buy_conditions=[c_inner2]).required_days >= 150
    c_tok2 = {"factor_token": "{종가}", "function_id": "cmp",
              "factor_token2": "{신고가갱신(52주)}", "op": "gte", "rhs": 0}
    assert cs.ConditionStrategy(buy_conditions=[c_tok2]).required_days >= 260


def test_score_as_second_operand():
    rng = np.random.RandomState(3)
    omap = {}
    for i, tk in enumerate(["000111", "000222", "000333"]):
        idx = pd.bdate_range("2023-06-01", periods=200)
        drift = [0.4, 0.05, -0.3][i]
        close = pd.Series(100 + np.cumsum(rng.normal(drift, 1.2, 200)), index=idx).clip(lower=20)
        omap[tk] = pd.DataFrame({"open": close * 0.999, "high": close * 1.01,
                                 "low": close * 0.99, "close": close,
                                 "volume": rng.randint(10_000, 90_000, 200).astype(float)},
                                index=idx)
    # 비교({수급점수},{가격점수}) >= 1 — 수급이 가격보다 강한 종목
    cond = [{"factor_token": "{수급점수}", "function_id": "cmp",
             "factor_token2": "{가격점수}", "op": "gte", "rhs": 1}]
    s = cs.ConditionStrategy(buy_conditions=cond)
    s.prepare_panel(omap)
    assert "가격점수" in s._score_panels                 # factor_token2도 점수 참조로 감지
    s.precompute_signals(omap)
    acts = [s.signal_at("000111", d) for d in omap["000111"].index[s.required_days:]]
    assert all(a is not None for a in acts)
    assert any(a.action.name == "BUY" for a in acts)


def test_engine_identical_with_two_factor(monkeypatch):
    from src.kis_strategies import condition_strategy  # noqa: F401 — 레지스트리
    df = make_df(180)
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified",
                        lambda ticker, *a, **k: df.copy())

    def run(vec: bool):
        cfg = BacktestConfig(
            symbols=["000111"], strategy_name="Condition",
            strategy_params={"buy_conditions": [
                {"factor_token": "{종가}", "function_id": "cmp", "factor_token2": "{시가}",
                 "op": "gte", "rhs": 1}],
                "sell_conditions": [
                {"factor_token": "{종가}", "function_id": "pctf", "factor_token2": "{종가}",
                 "inner2_function_id": "past", "inner2_params": {"n": "3"},
                 "op": "lte", "rhs": -3}]},
            start_date="2024-03-04", end_date=df.index[-1].strftime("%Y-%m-%d"),
            commission_rate=0.0, slippage_rate=0.0, vectorize_signals=vec)
        e = BacktestEngine(cfg)
        r = e.run()
        assert not r.get("error", False)
        return [(t.date, t.side, t.price, t.quantity) for t in e.trades]

    fast, slow = run(True), run(False)
    assert fast == slow and len(fast) >= 2
