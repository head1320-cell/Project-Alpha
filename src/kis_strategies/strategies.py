"""
KIS Strategy Engine
====================
KIS open-trading-api의 strategy_builder를 그대로 이식.
원본의 `from core import data_fetcher, indicators` 를
우리 플랫폼의 DB-backed 버전으로 교체했습니다.

원본 파일:
  strategy_builder/strategy/base_strategy.py
  strategy_builder/strategy/strategy_01_golden_cross.py
  ~ strategy_10_trend_filter.py

변경 사항:
  - `from core import data_fetcher` → `from src import kis_data_fetcher as data_fetcher`
  - `from core import indicators`   → `from src import kis_indicators as indicators`
  - `from core.signal import ...`   → `from src.kis_signal import ...`
  - 전략 로직(generate_signal) 내용: 원본 그대로
"""

from abc import ABC, abstractmethod

from src import kis_data_fetcher as data_fetcher
from src import kis_indicators as indicators
from src.kis_signal import Action, Signal

# ═══════════════════════════════════════════════════════════════════════════════
# BaseStrategy — 원본 그대로
# ═══════════════════════════════════════════════════════════════════════════════

class BaseStrategy(ABC):
    """
    모든 전략의 베이스 클래스 (KIS 원본)

    - 전략은 다른 전략을 참조하지 않는다
    - 전략 간 상태 공유 금지
    - 전략은 data_fetcher와 indicators만 사용
    """

    @abstractmethod
    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def required_days(self) -> int:
        pass

    def __str__(self) -> str:
        return f"{self.name} (required_days={self.required_days})"


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 01: 골든크로스 (Golden Cross) — 원본 그대로
# ═══════════════════════════════════════════════════════════════════════════════

class GoldenCrossStrategy(BaseStrategy):
    """골든크로스 전략 — MA(short) × MA(long)"""

    def __init__(self, short_period: int = 5, long_period: int = 20):
        self.short_period = short_period
        self.long_period = long_period

    @property
    def name(self) -> str:
        return "골든크로스"

    @property
    def required_days(self) -> int:
        return self.long_period + 10

    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)
        if df.empty or len(df) < self.long_period + 1:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="데이터 부족")

        ma_short = indicators.calc_ma(df, self.short_period)
        ma_long = indicators.calc_ma(df, self.long_period)
        prev_short, curr_short = ma_short.iloc[-2], ma_short.iloc[-1]
        prev_long, curr_long = ma_long.iloc[-2], ma_long.iloc[-1]

        if prev_short < prev_long and curr_short > curr_long:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.BUY, strength=0.7,
                          reason=f"골든크로스 (MA{self.short_period} > MA{self.long_period})")
        if prev_short > prev_long and curr_short < curr_long:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.SELL, strength=0.7,
                          reason=f"데드크로스 (MA{self.short_period} < MA{self.long_period})")

        return Signal(stock_code=stock_code, stock_name=stock_name,
                      action=Action.HOLD, strength=0.0, reason="크로스 조건 미충족")


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 02: 모멘텀 (Momentum)
# ═══════════════════════════════════════════════════════════════════════════════

class MomentumStrategy(BaseStrategy):
    """60일 수익률 모멘텀 전략"""

    def __init__(self, lookback_days: int = 60,
                 buy_threshold: float = 0.30,
                 sell_threshold: float = -0.20):
        self.lookback_days = lookback_days
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    @property
    def name(self) -> str:
        return "모멘텀"

    @property
    def required_days(self) -> int:
        return self.lookback_days + 10

    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)
        if df.empty or len(df) < self.lookback_days + 1:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="데이터 부족")

        returns = indicators.calc_returns(df, self.lookback_days)
        if returns.empty:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="수익률 계산 불가")

        ret = returns.iloc[-1]
        if ret >= self.buy_threshold:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.BUY, strength=min(ret / (self.buy_threshold * 2), 1.0),
                          reason=f"{self.lookback_days}일 수익률 {ret:.1%} (기준 {self.buy_threshold:.0%})")
        if ret <= self.sell_threshold:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.SELL, strength=0.7,
                          reason=f"{self.lookback_days}일 수익률 {ret:.1%} (기준 {self.sell_threshold:.0%})")

        return Signal(stock_code=stock_code, stock_name=stock_name,
                      action=Action.HOLD, strength=0.0,
                      reason=f"수익률 {ret:.1%} — 조건 미충족")


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 03: 52주 신고가
# ═══════════════════════════════════════════════════════════════════════════════

class Week52HighStrategy(BaseStrategy):
    """현재가 > 52주 최고가 돌파"""

    def __init__(self, breakout_margin: float = 0.0):
        self.breakout_margin = breakout_margin

    @property
    def name(self) -> str:
        return "52주 신고가"

    @property
    def required_days(self) -> int:
        return 260

    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        price_info = data_fetcher.get_current_price(stock_code)
        if not price_info:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="현재가 조회 실패")

        current = price_info.get("price", 0)
        w52_high = price_info.get("w52_high", 0)
        if not current or not w52_high:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="52주 데이터 없음")

        threshold = w52_high * (1 + self.breakout_margin / 100)
        if current > threshold:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.BUY, strength=0.8,
                          reason=f"52주 신고가 돌파 (현재가 {current:,} > 52주고가 {w52_high:,})")

        return Signal(stock_code=stock_code, stock_name=stock_name,
                      action=Action.HOLD, strength=0.0,
                      reason=f"52주 신고가 미돌파 ({current:,} / {w52_high:,})")


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 04: 연속 상승/하락
# ═══════════════════════════════════════════════════════════════════════════════

class ConsecutiveStrategy(BaseStrategy):
    """N일 연속 상승 매수 / N일 연속 하락 매도"""

    def __init__(self, buy_days: int = 5, sell_days: int = 5):
        self.buy_days = buy_days
        self.sell_days = sell_days

    @property
    def name(self) -> str:
        return "연속 상승/하락"

    @property
    def required_days(self) -> int:
        return max(self.buy_days, self.sell_days) + 5

    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)
        if df.empty or len(df) < 2:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="데이터 부족")

        up_count = indicators.calc_consecutive_days(df, "up")
        down_count = indicators.calc_consecutive_days(df, "down")

        if up_count >= self.buy_days:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.BUY, strength=min(up_count / (self.buy_days * 1.5), 1.0),
                          reason=f"{up_count}일 연속 상승 (기준 {self.buy_days}일)")
        if down_count >= self.sell_days:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.SELL, strength=0.7,
                          reason=f"{down_count}일 연속 하락 (기준 {self.sell_days}일)")

        return Signal(stock_code=stock_code, stock_name=stock_name,
                      action=Action.HOLD, strength=0.0,
                      reason=f"상승 {up_count}일 / 하락 {down_count}일")


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 05: 이격도 (Disparity)
# ═══════════════════════════════════════════════════════════════════════════════

class DisparityStrategy(BaseStrategy):
    """이격도 < oversold → BUY / > overbought → SELL"""

    def __init__(self, period: int = 20,
                 oversold_threshold: float = 90.0,
                 overbought_threshold: float = 110.0):
        self.period = period
        self.oversold_threshold = oversold_threshold
        self.overbought_threshold = overbought_threshold

    @property
    def name(self) -> str:
        return "이격도"

    @property
    def required_days(self) -> int:
        return self.period + 5

    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)
        if df.empty or len(df) < self.period:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="데이터 부족")

        disparity = indicators.calc_disparity(df, self.period)
        if disparity.empty:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="이격도 계산 불가")

        d = disparity.iloc[-1]
        if d < self.oversold_threshold:
            strength = min((self.oversold_threshold - d) / 20, 1.0)
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.BUY, strength=strength,
                          reason=f"이격도 과매도 ({d:.1f} < {self.oversold_threshold})")
        if d > self.overbought_threshold:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.SELL, strength=0.7,
                          reason=f"이격도 과매수 ({d:.1f} > {self.overbought_threshold})")

        return Signal(stock_code=stock_code, stock_name=stock_name,
                      action=Action.HOLD, strength=0.0, reason=f"이격도 {d:.1f} — 중립")


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 06: 돌파 실패 (Breakout Fail) — 매도 전용
# ═══════════════════════════════════════════════════════════════════════════════

class BreakoutFailStrategy(BaseStrategy):
    """전고점 돌파 후 N일 내 하락 → SELL"""

    def __init__(self, lookback_days: int = 20,
                 fail_within_days: int = 3,
                 fail_threshold: float = -0.03):
        self.lookback_days = lookback_days
        self.fail_within_days = fail_within_days
        self.fail_threshold = fail_threshold

    @property
    def name(self) -> str:
        return "돌파 실패"

    @property
    def required_days(self) -> int:
        return self.lookback_days + self.fail_within_days + 5

    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)
        if df.empty or len(df) < self.lookback_days + self.fail_within_days:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="데이터 부족")

        # 기준 시점: fail_within_days 전
        ref_idx = -(self.fail_within_days + 1)
        ref_df = df.iloc[:ref_idx]
        ref_high = indicators.calc_high_since(ref_df, self.lookback_days)
        if ref_high is None:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="전고점 계산 불가")

        ref_close = indicators.get_latest_close(ref_df)
        if ref_close is None or ref_close <= ref_high:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="전고점 돌파 없음")

        # 이후 N일간 하락
        curr_close = indicators.get_latest_close(df)
        if curr_close is None:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="현재가 없음")

        change = (curr_close - ref_close) / ref_close
        if change <= self.fail_threshold:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.SELL, strength=0.8,
                          reason=f"돌파 실패 ({change:.1%} ≤ {self.fail_threshold:.0%})")

        return Signal(stock_code=stock_code, stock_name=stock_name,
                      action=Action.HOLD, strength=0.0, reason="돌파 실패 조건 미충족")


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 07: 강한 종가 (Strong Close)
# ═══════════════════════════════════════════════════════════════════════════════

class StrongCloseStrategy(BaseStrategy):
    """종가가 (고가-저가) 범위의 상위 N% 이상 → BUY"""

    def __init__(self, min_close_ratio: float = 0.8):
        self.min_close_ratio = min_close_ratio

    @property
    def name(self) -> str:
        return "강한 종가"

    @property
    def required_days(self) -> int:
        return 5

    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)
        if df.empty:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="데이터 부족")

        ratio = indicators.calc_strong_close_ratio(df)
        if ratio is None:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="종가 비율 계산 불가")

        if ratio >= self.min_close_ratio:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.BUY, strength=ratio,
                          reason=f"강한 종가 (비율 {ratio:.2f} ≥ {self.min_close_ratio})")

        return Signal(stock_code=stock_code, stock_name=stock_name,
                      action=Action.HOLD, strength=0.0,
                      reason=f"종가 비율 {ratio:.2f} — 조건 미충족")


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 08: 변동성 확장 (Volatility Expansion)
# ═══════════════════════════════════════════════════════════════════════════════

class VolatilityStrategy(BaseStrategy):
    """N일 변동성 최저 + 당일 M% 이상 상승 → BUY"""

    def __init__(self, lookback_days: int = 10, breakout_pct: float = 3.0):
        self.lookback_days = lookback_days
        self.breakout_pct = breakout_pct

    @property
    def name(self) -> str:
        return "변동성 확장"

    @property
    def required_days(self) -> int:
        return self.lookback_days + 20

    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)
        if df.empty or len(df) < self.lookback_days + 5:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="데이터 부족")

        vol = indicators.calc_volatility(df, self.lookback_days)
        if vol.empty:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="변동성 계산 불가")

        curr_vol = vol.iloc[-1]
        min_vol_prev = vol.iloc[:-1].min()
        if curr_vol > min_vol_prev:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="변동성 최저 조건 미충족")

        daily_change = indicators.calc_daily_change(df)
        if daily_change is None:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="등락률 계산 불가")

        if daily_change >= self.breakout_pct:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.BUY, strength=min(daily_change / (self.breakout_pct * 2), 1.0),
                          reason=f"변동성 확장 돌파 ({daily_change:.1f}% ≥ {self.breakout_pct}%)")

        return Signal(stock_code=stock_code, stock_name=stock_name,
                      action=Action.HOLD, strength=0.0,
                      reason=f"등락률 {daily_change:.1f}% — 조건 미충족")


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 09: 평균회귀 (Mean Reversion)
# ═══════════════════════════════════════════════════════════════════════════════

class MeanReversionStrategy(BaseStrategy):
    """N일 평균 대비 -M% 이하 → BUY, +M% 이상 → SELL"""

    def __init__(self, period: int = 5,
                 buy_threshold: float = -3.0,
                 sell_threshold: float = 3.0):
        self.period = period
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    @property
    def name(self) -> str:
        return "평균회귀"

    @property
    def required_days(self) -> int:
        return self.period + 5

    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)
        if df.empty or len(df) < self.period:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="데이터 부족")

        ma = indicators.calc_ma(df, self.period)
        if ma.empty or ma.iloc[-1] == 0:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="이동평균 계산 불가")

        curr_close = df["close"].iloc[-1]
        deviation_pct = (curr_close - ma.iloc[-1]) / ma.iloc[-1] * 100

        if deviation_pct <= self.buy_threshold:
            strength = min(abs(deviation_pct) / abs(self.buy_threshold * 2), 1.0)
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.BUY, strength=strength,
                          reason=f"평균 대비 {deviation_pct:.1f}% 이탈 (기준 {self.buy_threshold}%)")
        if deviation_pct >= self.sell_threshold:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.SELL, strength=0.7,
                          reason=f"평균 대비 +{deviation_pct:.1f}% 이탈 (기준 {self.sell_threshold}%)")

        return Signal(stock_code=stock_code, stock_name=stock_name,
                      action=Action.HOLD, strength=0.0,
                      reason=f"평균 대비 {deviation_pct:.1f}% — 중립")


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy 10: 추세 필터 (Trend Filter)
# ═══════════════════════════════════════════════════════════════════════════════

class TrendFilterStrategy(BaseStrategy):
    """장기 추세(MA200) 확인 후 단기 신호(RSI) 적용"""

    def __init__(self, trend_period: int = 60,
                 rsi_period: int = 14,
                 rsi_buy: float = 40.0,
                 rsi_sell: float = 60.0):
        self.trend_period = trend_period
        self.rsi_period = rsi_period
        self.rsi_buy = rsi_buy
        self.rsi_sell = rsi_sell

    @property
    def name(self) -> str:
        return "추세 필터"

    @property
    def required_days(self) -> int:
        return self.trend_period + self.rsi_period + 10

    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)
        if df.empty or len(df) < self.trend_period:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="데이터 부족")

        ma_trend = indicators.calc_ma(df, self.trend_period)
        rsi = indicators.calc_rsi(df, self.rsi_period)
        if ma_trend.empty or rsi.empty:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.HOLD, strength=0.0, reason="지표 계산 불가")

        curr_close = df["close"].iloc[-1]
        is_uptrend = curr_close > ma_trend.iloc[-1]
        curr_rsi = rsi.iloc[-1]

        if is_uptrend and curr_rsi <= self.rsi_buy:
            strength = min((self.rsi_buy - curr_rsi) / 30, 1.0)
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.BUY, strength=strength,
                          reason=f"상승추세 + RSI 과매도 (RSI {curr_rsi:.1f})")
        if not is_uptrend and curr_rsi >= self.rsi_sell:
            return Signal(stock_code=stock_code, stock_name=stock_name,
                          action=Action.SELL, strength=0.7,
                          reason=f"하락추세 + RSI 과매수 (RSI {curr_rsi:.1f})")

        trend_str = "상승" if is_uptrend else "하락"
        return Signal(stock_code=stock_code, stock_name=stock_name,
                      action=Action.HOLD, strength=0.0,
                      reason=f"{trend_str}추세 / RSI {curr_rsi:.1f} — 중립")


# ═══════════════════════════════════════════════════════════════════════════════
# Registry — 이름으로 전략 클래스 조회
# ═══════════════════════════════════════════════════════════════════════════════

STRATEGY_REGISTRY: dict[str, type] = {
    "골든크로스":    GoldenCrossStrategy,
    "모멘텀":        MomentumStrategy,
    "52주 신고가":   Week52HighStrategy,
    "연속 상승/하락": ConsecutiveStrategy,
    "이격도":        DisparityStrategy,
    "돌파 실패":     BreakoutFailStrategy,
    "강한 종가":     StrongCloseStrategy,
    "변동성 확장":   VolatilityStrategy,
    "평균회귀":      MeanReversionStrategy,
    "추세 필터":     TrendFilterStrategy,
    # English aliases
    "GoldenCross":   GoldenCrossStrategy,
    "Momentum":      MomentumStrategy,
    "Week52High":    Week52HighStrategy,
    "Consecutive":   ConsecutiveStrategy,
    "Disparity":     DisparityStrategy,
    "BreakoutFail":  BreakoutFailStrategy,
    "StrongClose":   StrongCloseStrategy,
    "Volatility":    VolatilityStrategy,
    "MeanReversion": MeanReversionStrategy,
    "TrendFilter":   TrendFilterStrategy,
}


def get_strategy(name: str, **kwargs) -> BaseStrategy | None:
    """이름으로 전략 인스턴스 생성. kwargs는 전략 파라미터.

    특수 케이스: name이 "__custom__" 또는 "DslStrategy"이면
    kwargs['spec'](BuilderState dict)로 커스텀 전략을 만든다.
    """
    if name in ("__custom__", "DslStrategy", "커스텀"):
        spec = kwargs.get("spec")
        if not spec:
            return None
        from src.kis_strategies.dsl_strategy import DslStrategy
        return DslStrategy(spec)
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        return None
    return cls(**kwargs)


def list_strategies() -> list[dict]:
    """등록된 전략 목록 반환."""
    seen = set()
    result = []
    for _name, cls in STRATEGY_REGISTRY.items():
        if cls in seen:
            continue
        seen.add(cls)
        instance = cls()
        result.append({
            "name": instance.name,
            "class": cls.__name__,
            "required_days": instance.required_days,
        })
    return result
