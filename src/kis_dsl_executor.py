"""
KIS DSL Runtime Executor
==========================
DSL 문자열(예: "ma(5) crosses_above ma(20)")을 파싱하여
실제 OHLCV 데이터에 대해 평가하는 런타임.

strategy_builder/strategy_core/executor.py 에 해당하는 모듈.

KIS 원본과의 차이:
  - data_fetcher: DB(daily_prices) 기반 (live API 아님)
  - 생성된 전략 코드를 exec()로 즉시 실행 (파일 저장 불필요)
  - BaseStrategy 인터페이스와 호환 — 기존 백테스트 엔진에 그대로 투입 가능
"""

from __future__ import annotations

import logging

from src import kis_data_fetcher as data_fetcher
from src import kis_indicators as indicators
from src.kis_candlestick import PATTERN_DETECTORS, detect_pattern
from src.kis_dsl_parser import (
    ArithmeticExpr,
    CompositeCondition,
    LogicalOperator,
    Operator,
    StrategyDSLParser,
    Value,
)
from src.kis_dsl_parser import (
    Indicator as DSLIndicator,
)
from src.kis_signal import Action, Signal

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# DSL Evaluator — AST → bool (단일 날짜 슬라이스 기준)
# ═══════════════════════════════════════════════════════════════════════════════

def _eval_indicator(node: DSLIndicator, df) -> object:
    """Indicator AST 노드를 pandas Series 또는 scalar로 평가."""
    import pandas as pd

    name = node.name
    p = node.params

    # helper
    def _p(idx, default):
        return p[idx] if len(p) > idx else default

    # 지표별 평가 — kis_indicators.py의 함수 매핑 (원본 parser.py indicator_map과 1:1)
    dispatch = {
        "ma":         lambda: indicators.calc_ma(df, int(_p(0, 20))),
        "ema":        lambda: indicators.calc_ema(df, int(_p(0, 20))),
        "std":        lambda: indicators.calc_std(df, int(_p(0, 20))),
        "returns":    lambda: indicators.calc_returns(df, int(_p(0, 1))),
        "disparity":  lambda: indicators.calc_disparity(df, int(_p(0, 20))),
        "volatility": lambda: indicators.calc_volatility(df, int(_p(0, 10))),
        "consecutive": lambda: indicators.calc_consecutive_days(df, str(_p(0, "up"))),
        "change":     lambda: indicators.calc_daily_change(df),
        "high":       lambda: indicators.calc_high_since(df, int(_p(0, 20))),
        "low":        lambda: indicators.calc_low_since(df, int(_p(0, 20))),
        "close":      lambda: indicators.get_latest_close(df),
        "prev_close": lambda: indicators.get_prev_close(df),
        "rsi":        lambda: indicators.calc_rsi(df, int(_p(0, 14))),
        "macd":       lambda: indicators.calc_macd(df, int(_p(0, 12)), int(_p(1, 26)), int(_p(2, 9))),
        "macd_signal": lambda: indicators.calc_macd_signal(df, int(_p(0, 12)), int(_p(1, 26)), int(_p(2, 9))),
        "macd_hist":  lambda: indicators.calc_macd_histogram(df, int(_p(0, 12)), int(_p(1, 26)), int(_p(2, 9))),
        "bb_upper":   lambda: indicators.calc_bb_upper(df, int(_p(0, 20)), float(_p(1, 2.0))),
        "bb_lower":   lambda: indicators.calc_bb_lower(df, int(_p(0, 20)), float(_p(1, 2.0))),
        "bb_middle":  lambda: indicators.calc_bb_middle(df, int(_p(0, 20))),
        "volume":     lambda: float(df["volume"].iloc[-1]),
        "volume_ma":  lambda: indicators.calc_volume_ma(df, int(_p(0, 20))),
        "atr":        lambda: indicators.calc_atr(df, int(_p(0, 14))),
        "stoch_k":    lambda: indicators.calc_stochastic_k(df, int(_p(0, 14))),
        "stoch_d":    lambda: indicators.calc_stochastic_d(df, int(_p(0, 14)), int(_p(1, 3))),
        "cci":        lambda: indicators.calc_cci(df, int(_p(0, 20))),
        "adx":        lambda: indicators.calc_adx(df, int(_p(0, 14))),
        "williams_r": lambda: indicators.calc_williams_r(df, int(_p(0, 14))),
        "obv":        lambda: indicators.calc_obv(df),
        "mfi":        lambda: indicators.calc_mfi(df, int(_p(0, 14))),
        "vwap":       lambda: indicators.calc_vwap(df),
        "highest":    lambda: indicators.calc_high_since(df, int(_p(0, 20))),
        "lowest":     lambda: indicators.calc_low_since(df, int(_p(0, 20))),
        "roc":        lambda: indicators.calc_roc(df, int(_p(0, 10))),
        "ibs":        lambda: indicators.calc_strong_close_ratio(df),
        "momentum":   lambda: indicators.calc_momentum(df, int(_p(0, 10))),
        "hma":        lambda: indicators.calc_hma(df, int(_p(0, 20))),
        "dema":       lambda: indicators.calc_dema(df, int(_p(0, 20))),
        "tema":       lambda: indicators.calc_tema(df, int(_p(0, 20))),
        "kama":       lambda: indicators.calc_kama(df, int(_p(0, 20))),
        "cmf":        lambda: indicators.calc_cmf(df, int(_p(0, 20))),
        "natr":       lambda: indicators.calc_natr(df, int(_p(0, 14))),
        "supertrend": lambda: indicators.calc_supertrend(df, int(_p(0, 10))),
        "sar":        lambda: indicators.calc_sar(df),
        "ichimoku_tenkan": lambda: indicators.calc_ichimoku_tenkan(df, int(_p(0, 9))),
        "ichimoku_kijun":  lambda: indicators.calc_ichimoku_kijun(df, int(_p(0, 26))),
        "logr":       lambda: indicators.calc_logr(df),
        "bop":        lambda: indicators.calc_bop(df),
        "regression_slope": lambda: indicators.calc_regression_slope(df, int(_p(0, 20))),
        "pivot":      lambda: indicators.calc_pivot(df),
    }

    # ── Candlestick patterns (65개) ───────────────────────────────────────
    # DSL 예시: doji > 0  (bullish detected)
    #            engulfing > 0  (bullish engulfing)
    #            evening_star < 0  (bearish evening star)
    if name in PATTERN_DETECTORS:
        return float(detect_pattern(df, name))

    fn = dispatch.get(name)
    if fn is None:
        raise ValueError(f"Unknown indicator in DSL: '{name}'")

    result = fn()
    if isinstance(result, pd.Series):
        return float(result.iloc[-1]) if not result.empty else None
    return result


def _eval_node(node, df) -> float:
    """Evaluate any AST node to a scalar float."""
    if isinstance(node, DSLIndicator):
        v = _eval_indicator(node, df)
        return float(v) if v is not None else float("nan")
    elif isinstance(node, Value):
        return float(node.value)
    elif isinstance(node, ArithmeticExpr):
        left = _eval_node(node.left, df)
        right = _eval_node(node.right, df)
        op = node.operator.value
        if op == "*":   return left * right
        if op == "/":   return left / right if right != 0 else float("nan")
        if op == "+":   return left + right
        if op == "-":   return left - right
    return float("nan")


def _eval_condition(cond, df, df_prev=None) -> bool:
    """Evaluate a single Condition or CompositeCondition."""
    if isinstance(cond, CompositeCondition):
        left_val = _eval_condition(cond.left, df, df_prev)
        right_val = _eval_condition(cond.right, df, df_prev)
        if cond.operator == LogicalOperator.AND:
            return left_val and right_val
        return left_val or right_val

    # Single Condition
    import math
    op = cond.operator

    if op in (Operator.CROSSES_ABOVE, Operator.CROSSES_BELOW, Operator.BREAKS):
        # Need previous bar for crossover
        if df_prev is None or df_prev.empty:
            return False
        curr_left = _eval_node(cond.left, df)
        curr_right = _eval_node(cond.right, df)
        prev_left = _eval_node(cond.left, df_prev)
        prev_right = _eval_node(cond.right, df_prev)
        if any(math.isnan(v) for v in [curr_left, curr_right, prev_left, prev_right]):
            return False
        if op == Operator.CROSSES_ABOVE:
            return prev_left <= prev_right and curr_left > curr_right
        elif op == Operator.CROSSES_BELOW:
            return prev_left >= prev_right and curr_left < curr_right
        else:  # BREAKS (same as crosses_above)
            return prev_left <= prev_right and curr_left > curr_right

    left_val = _eval_node(cond.left, df)
    right_val = _eval_node(cond.right, df)
    if math.isnan(left_val) or math.isnan(right_val):
        return False

    if op == Operator.GT:   return left_val > right_val
    if op == Operator.LT:   return left_val < right_val
    if op == Operator.GTE:  return left_val >= right_val
    if op == Operator.LTE:  return left_val <= right_val
    if op == Operator.EQ:   return left_val == right_val
    if op == Operator.NEQ:  return left_val != right_val
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# DSL Strategy — BaseStrategy 호환 클래스
# ═══════════════════════════════════════════════════════════════════════════════

class DSLStrategy:
    """
    사용자가 입력한 DSL 문자열로 동작하는 전략.

    BaseStrategy 인터페이스와 호환:
      - generate_signal(stock_code, stock_name) → Signal
      - name, required_days 속성

    백테스트 엔진에 그대로 투입 가능.
    """

    def __init__(
        self,
        name: str,
        buy_condition: str,
        sell_condition: str = "",
        required_days: int | None = None,
    ):
        self._name = name
        parser = StrategyDSLParser()
        self._buy_ast = parser.parse(buy_condition)
        self._sell_ast = parser.parse(sell_condition) if sell_condition.strip() else None
        self._required_days = required_days or (
            max(
                self._buy_ast.get_required_days(),
                self._sell_ast.get_required_days() if self._sell_ast else 10,
            ) + 5
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def required_days(self) -> int:
        return self._required_days

    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        import pandas as pd

        df = data_fetcher.get_daily_prices(stock_code, self._required_days)
        if df.empty or len(df) < max(self._required_days - 5, 5):
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="데이터 부족")

        df_prev = df.iloc[:-1] if len(df) > 1 else pd.DataFrame()

        try:
            buy_triggered = _eval_condition(self._buy_ast, df, df_prev)
        except Exception as e:
            logger.warning(f"Buy condition eval error ({stock_code}): {e}")
            buy_triggered = False

        try:
            sell_triggered = _eval_condition(self._sell_ast, df, df_prev) \
                if self._sell_ast else False
        except Exception as e:
            logger.warning(f"Sell condition eval error ({stock_code}): {e}")
            sell_triggered = False

        if buy_triggered:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.BUY, strength=0.75,
                          reason=f"[DSL BUY] {self._name}")
        if sell_triggered:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.SELL, strength=0.75,
                          reason=f"[DSL SELL] {self._name}")

        return Signal(stock_code=stock_code, stock_name=stock_name,
                      action=Action.HOLD, strength=0.0, reason="DSL 조건 미충족")


# ═══════════════════════════════════════════════════════════════════════════════
# Public helpers
# ═══════════════════════════════════════════════════════════════════════════════

def parse_and_validate(expression: str) -> tuple[bool, str]:
    """DSL 수식의 유효성 검사. (프론트엔드 실시간 검증용)"""
    try:
        StrategyDSLParser().parse(expression)
        return True, "Valid"
    except SyntaxError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Parse error: {e}"


def dsl_to_strategy(
    name: str,
    buy_expr: str,
    sell_expr: str = "",
) -> DSLStrategy:
    """DSL 표현식으로 전략 객체 생성."""
    return DSLStrategy(name=name, buy_condition=buy_expr, sell_condition=sell_expr)
