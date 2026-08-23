"""조건식 전략(ConditionStrategy) 단위 테스트 — 젠포트식 진입/청산.

매수(전조건 충족)/매도(하나라도 충족)/평가불가 무시/펀더멘털 게이트(옵트인)/
횡단면 순위·비율(3종목 패널)을 합성 OHLCV로 검증. DB·네트워크 불필요.
"""
import pandas as pd
import pytest

from src import kis_data_fetcher
from src.kis_signal import Action
from src.kis_strategies import condition_strategy as cs
from src.kis_strategies.strategies import STRATEGY_REGISTRY, get_strategy


# ─── 합성 OHLCV ──────────────────────────────────────────────────────────────
def make_rising_df(days: int = 60, start: float = 100.0) -> pd.DataFrame:
    """단조 상승 종가(+1/일), 거래량 고정 — date 컬럼 포함(전략 as_of용)."""
    dates = pd.date_range("2024-01-02", periods=days, freq="B")
    close = pd.Series([start + i for i in range(days)], index=dates)
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": [10_000] * days,
    }, index=dates)


@pytest.fixture
def rising_prices(monkeypatch):
    """get_daily_prices 를 합성 상승 OHLCV로 대체 (엔진의 monkey-patch 방식과 동일)."""
    df = make_rising_df()
    monkeypatch.setattr(kis_data_fetcher, "get_daily_prices", lambda code, days: df)
    return df


def cond(token: str, fn: str = "base", op: str = "gte", rhs: float = 0,
         rhs2: float | None = None, **params) -> dict:
    return {"factor_token": token, "function_id": fn,
            "params": {k: str(v) for k, v in params.items()},
            "op": op, "rhs": rhs, "rhs2": rhs2}


# ─── 레지스트리 ───────────────────────────────────────────────────────────────
def test_registry_self_registration():
    assert "Condition" in STRATEGY_REGISTRY
    s = get_strategy("Condition", buy_conditions=[cond("{종가}")], sell_conditions=[])
    assert isinstance(s, cs.ConditionStrategy)
    assert s.required_days >= 30


# ─── 매수/매도/HOLD ──────────────────────────────────────────────────────────
def test_buy_when_all_conditions_met(rising_prices):
    s = cs.ConditionStrategy(buy_conditions=[
        cond("{종가}", "ma", "gte", 0, n=5),        # 5일 이평 ≥ 0 (항상 참)
        cond("{종가}", "pct", "gte", 0.1, n=1),      # 1일 변화율 ≥ 0.1% (상승장 참)
    ])
    sig = s.generate_signal("000001", "테스트")
    assert sig.action == Action.BUY


def test_hold_when_any_condition_fails(rising_prices):
    s = cs.ConditionStrategy(buy_conditions=[
        cond("{종가}", "ma", "gte", 0, n=5),
        cond("{종가}", "base", "gte", 10_000_000),   # 불가능한 값 → 미충족
    ])
    sig = s.generate_signal("000001", "테스트")
    assert sig.action == Action.HOLD


def test_sell_takes_priority_over_buy(rising_prices):
    s = cs.ConditionStrategy(
        buy_conditions=[cond("{종가}", "base", "gte", 0)],          # 충족
        sell_conditions=[cond("{종가}", "pct", "gte", 0, n=1)],     # 충족 → SELL 우선
    )
    sig = s.generate_signal("000001", "테스트")
    assert sig.action == Action.SELL


def test_hold_on_insufficient_data(monkeypatch):
    monkeypatch.setattr(kis_data_fetcher, "get_daily_prices",
                        lambda code, days: pd.DataFrame())
    s = cs.ConditionStrategy(buy_conditions=[cond("{종가}")])
    assert s.generate_signal("000001", "테스트").action == Action.HOLD


# ─── 평가 불가 토큰 ───────────────────────────────────────────────────────────
def test_unevaluable_only_conditions_do_not_enter(rising_prices):
    """펀더멘털 토큰만 있으면(기본 OFF) 평가 가능한 조건이 없어 진입하지 않는다."""
    s = cs.ConditionStrategy(buy_conditions=[cond("{PER}", "base", "lte", 10)])
    assert s.generate_signal("000001", "테스트").action == Action.HOLD


def test_unevaluable_condition_skipped_among_evaluable(rising_prices):
    """평가 불가 조건은 건너뛰고, 평가 가능한 조건들로 판정한다."""
    s = cs.ConditionStrategy(buy_conditions=[
        cond("{PER}", "base", "lte", 10),            # 무시됨
        cond("{종가}", "base", "gte", 0),            # 충족
    ])
    assert s.generate_signal("000001", "테스트").action == Action.BUY


# ─── 펀더멘털 게이트 (옵트인 스냅샷) ──────────────────────────────────────────
def test_fundamental_gate_opt_in(rising_prices, monkeypatch):
    monkeypatch.setattr(cs, "_load_fundamentals",
                        lambda code: {"market_cap": 100.0, "net_income": 10.0})
    # OFF(기본): {PER} 평가 불가 → 진입 없음
    off = cs.ConditionStrategy(buy_conditions=[cond("{PER}", "base", "lte", 20)])
    assert off.generate_signal("000001", "테스트").action == Action.HOLD
    # ON: PER = 100/10 = 10 ≤ 20 → 진입
    on = cs.ConditionStrategy(buy_conditions=[cond("{PER}", "base", "lte", 20)],
                              allow_snapshot_fundamentals=True)
    assert on.generate_signal("000001", "테스트").action == Action.BUY
    # ON + 미충족: PER 10 ≤ 5 거짓 → HOLD
    strict = cs.ConditionStrategy(buy_conditions=[cond("{PER}", "base", "lte", 5)],
                                  allow_snapshot_fundamentals=True)
    assert strict.generate_signal("000001", "테스트").action == Action.HOLD


# ─── 연산자/함수 무크래시 + 수치 검증 ─────────────────────────────────────────
def test_between_ams_cntgt_no_crash(rising_prices):
    s = cs.ConditionStrategy(buy_conditions=[
        cond("{종가}", "base", "between", 0, rhs2=10_000_000),
        cond("{종가}", "ams", "gte", 50, n=10),       # 상승장 → 100%
        cond("{거래량}", "cntgt", "gte", 1, n=5, v=0),
    ])
    assert s.generate_signal("000001", "테스트").action == Action.BUY


def test_function_math_exact():
    df = make_rising_df(days=40)
    last_close = float(df["close"].iloc[-1])
    # past(1) = 어제 종가 = 마지막-1
    assert cs._eval_condition(df, cond("{종가}", "past", "eq", last_close - 1, n=1)) is True
    # delta(1) = +1
    assert cs._eval_condition(df, cond("{종가}", "delta", "eq", 1, n=1)) is True
    # 거래대금 = 종가 × 거래량
    assert cs._eval_condition(df, cond("{거래대금}", "base", "eq", last_close * 10_000)) is True
    # 평가 불가 → None
    assert cs._eval_condition(df, cond("{뉴지스코어}", "base", "gte", 0)) is None


# ─── 횡단면 순위/비율 (3종목 패널) ────────────────────────────────────────────
def _three_ticker_map() -> dict[str, pd.DataFrame]:
    """종가 수준 000111(300대) > 000222(200대) > 000333(100대)인 3종목 ohlcv_map."""
    out = {}
    for tk, base in (("000111", 300.0), ("000222", 200.0), ("000333", 100.0)):
        out[tk] = make_rising_df(days=30, start=base)
    return out


@pytest.mark.parametrize("fn,op,rhs,winners", [
    ("rank", "lte", 1, {"000111"}),             # 순위(종가,DESC) ≤ 1 → 최고가 종목만
    ("rank", "lte", 2, {"000111", "000222"}),
    ("ratio", "gte", 67, {"000111"}),           # 비율(종가,DESC) ≥ 67 → 상위 1/3
])
def test_cross_sectional_rank_ratio(monkeypatch, fn, op, rhs, winners):
    omap = _three_ticker_map()
    s = cs.ConditionStrategy(buy_conditions=[
        {"factor_token": "{종가}", "function_id": fn, "params": {"dir": "DESC"},
         "op": op, "rhs": rhs, "rhs2": None},
    ])
    s.prepare_panel(omap)  # 엔진이 봉 루프 전 1회 호출하는 seam과 동일
    actions = {}
    for tk, df in omap.items():
        monkeypatch.setattr(kis_data_fetcher, "get_daily_prices",
                            lambda code, days, _df=df: _df)
        actions[tk] = s.generate_signal(tk, tk).action
    assert {tk for tk, a in actions.items() if a == Action.BUY} == winners


def test_cross_sectional_without_panel_is_skipped(rising_prices):
    """prepare_panel 미호출(패널 없음) → 순위/비율 조건은 평가 불가로 건너뜀."""
    s = cs.ConditionStrategy(buy_conditions=[
        {"factor_token": "{종가}", "function_id": "rank", "params": {"dir": "DESC"},
         "op": "lte", "rhs": 1, "rhs2": None},
    ])
    assert s.generate_signal("000111", "테스트").action == Action.HOLD


# ─── 중첩(내부 지표) — 순위/비율의 랭킹 대상을 파생 지표로 ────────────────────
def make_trend_df(days: int, start: float, step: float) -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=days, freq="B")
    close = pd.Series([start + step * i for i in range(days)], index=dates)
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": close, "high": close, "low": close, "close": close,
        "volume": [10_000] * days,
    }, index=dates)


def _level_vs_momentum_map() -> dict[str, pd.DataFrame]:
    """가격 수준은 A>B>C, 20일 수익률(모멘텀)은 C>B>A — 두 랭킹이 정반대."""
    return {
        "000111": make_trend_df(30, 300.0, -1.0),  # 고가·하락 (모멘텀 최하)
        "000222": make_trend_df(30, 200.0, 0.0),   # 중간·횡보
        "000333": make_trend_df(30, 100.0, +2.0),  # 저가·급등 (모멘텀 최상)
    }


def nested_cond(fn: str, op: str, rhs: float, inner: str = "pct", inner_n: str = "20") -> dict:
    return {"factor_token": "{종가}", "function_id": fn, "params": {"dir": "DESC"},
            "op": op, "rhs": rhs, "rhs2": None,
            "inner_function_id": inner, "inner_params": {"n": inner_n}}


def _winners(monkeypatch, omap: dict, condition: dict) -> set:
    s = cs.ConditionStrategy(buy_conditions=[condition])
    s.prepare_panel(omap)
    out = set()
    for tk, df in omap.items():
        monkeypatch.setattr(kis_data_fetcher, "get_daily_prices",
                            lambda code, days, _df=df: _df)
        if s.generate_signal(tk, tk).action == Action.BUY:
            out.add(tk)
    return out


def test_nested_rank_ranks_derived_indicator_not_level(monkeypatch):
    """순위(변화율_기간(종가,20),DESC)≤1 → 모멘텀 1위(000333). bare 순위(종가)와 정반대."""
    omap = _level_vs_momentum_map()
    bare = {"factor_token": "{종가}", "function_id": "rank", "params": {"dir": "DESC"},
            "op": "lte", "rhs": 1, "rhs2": None}
    assert _winners(monkeypatch, omap, bare) == {"000111"}            # 가격 수준 1위
    assert _winners(monkeypatch, omap, nested_cond("rank", "lte", 1)) == {"000333"}  # 모멘텀 1위


def test_nested_ratio_percentile_of_derived(monkeypatch):
    """비율(변화율_기간(종가,20),DESC)≥67 → 모멘텀 상위 1/3 (000333)."""
    omap = _level_vs_momentum_map()
    assert _winners(monkeypatch, omap, nested_cond("ratio", "gte", 67)) == {"000333"}


def test_nested_single_ticker_condition():
    """단일종목 중첩: 이동평균(변화량_기간(종가,1), 5) — +1/일 상승장 → 정확히 1.0."""
    df = make_rising_df(days=40)
    c = {"factor_token": "{종가}", "function_id": "ma", "params": {"n": "5"},
         "op": "eq", "rhs": 1.0, "rhs2": None,
         "inner_function_id": "delta", "inner_params": {"n": "1"}}
    assert cs._eval_condition(df, c) is True


def test_inner_cross_function_is_invalid():
    """내부 지표로 횡단면 함수(rank/ratio)는 불가 → 평가 불가(None) → 건너뜀."""
    df = make_rising_df(days=40)
    c = {"factor_token": "{종가}", "function_id": "ma", "params": {"n": "5"},
         "op": "gte", "rhs": 0, "rhs2": None,
         "inner_function_id": "rank", "inner_params": {}}
    assert cs._eval_condition(df, c) is None


def test_required_days_covers_inner_period():
    """required_days 가 내부 함수 기간(n)도 반영 — 워밍업 부족 방지."""
    s = cs.ConditionStrategy(buy_conditions=[nested_cond("rank", "lte", 1, inner_n="60")])
    assert s.required_days >= 90  # 60 + 30


def test_cross_key_distinguishes_inner_params():
    """내부 함수·기간이 다르면 패널 캐시 키도 달라야 함 (pct5 vs pct20 별도 랭킹)."""
    s = cs.ConditionStrategy()
    k5 = s._cross_key(nested_cond("rank", "lte", 1, inner_n="5"))
    k20 = s._cross_key(nested_cond("rank", "lte", 1, inner_n="20"))
    bare = s._cross_key({"factor_token": "{종가}", "function_id": "rank", "params": {"dir": "DESC"}})
    assert len({k5, k20, bare}) == 3
