"""
Graph Strategy Runner
======================
React Flow 노드 그래프를 파싱 → 위상 정렬 → 지표 계산 → 시그널 생성 → 백테스트 실행.

Pipeline:
  GraphBacktestRequest
    → parse_graph()        : 노드/엣지 분류 + 의존관계 구축
    → topological_sort()   : Data → Indicator → Condition → Action 순서
    → build_dataframes()   : DB 또는 더미 OHLCV 로드
    → compute_indicators() : pandas 기반 지표 계산
    → generate_signals()   : 조건 평가 → BUY/SELL 시그널
    → run_backtest()       : 일별 시뮬레이션 → Equity Curve + 통계
    → GraphBacktestResponse
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from src.models.graph_schema import (
    ActionNodeData,
    BacktestStatistics,
    ConditionNodeData,
    DataSourceNodeData,
    GraphBacktestRequest,
    GraphBacktestResponse,
    IndicatorNodeData,
    TradeRecord,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Graph Parser — 노드/엣지 분류 + 위상 정렬
# ═══════════════════════════════════════════════════════════════════════════════

class ParsedGraph:
    """파싱된 그래프 구조."""

    def __init__(self):
        self.data_sources: list[tuple[str, DataSourceNodeData]] = []
        self.indicators: list[tuple[str, IndicatorNodeData]] = []
        self.conditions: list[tuple[str, ConditionNodeData]] = []
        self.actions: list[tuple[str, ActionNodeData]] = []
        self.adjacency: dict[str, list[str]] = defaultdict(list)   # source → [targets]
        self.reverse: dict[str, list[str]] = defaultdict(list)     # target → [sources]
        self.execution_order: list[str] = []
        self.node_map: dict[str, Any] = {}   # id → parsed data

    def to_dict(self) -> dict:
        return {
            "data_sources": [(id, d.model_dump()) for id, d in self.data_sources],
            "indicators":   [(id, d.model_dump()) for id, d in self.indicators],
            "conditions":   [(id, d.model_dump()) for id, d in self.conditions],
            "actions":      [(id, d.model_dump()) for id, d in self.actions],
            "execution_order": self.execution_order,
            "edge_count": sum(len(v) for v in self.adjacency.values()),
        }


def parse_graph(req: GraphBacktestRequest) -> ParsedGraph:
    """React Flow JSON → ParsedGraph."""
    g = ParsedGraph()

    # 노드 분류
    for node in req.nodes:
        try:
            parsed = node.parse_data()
        except Exception as e:
            logger.warning(f"Node {node.id} parse failed: {e}")
            continue

        g.node_map[node.id] = parsed

        if isinstance(parsed, DataSourceNodeData):
            g.data_sources.append((node.id, parsed))
        elif isinstance(parsed, IndicatorNodeData):
            g.indicators.append((node.id, parsed))
        elif isinstance(parsed, ConditionNodeData):
            g.conditions.append((node.id, parsed))
        elif isinstance(parsed, ActionNodeData):
            g.actions.append((node.id, parsed))

    # 엣지 → 인접 리스트
    for edge in req.edges:
        g.adjacency[edge.source].append(edge.target)
        g.reverse[edge.target].append(edge.source)

    # 위상 정렬 (Kahn's Algorithm)
    g.execution_order = _topological_sort(g)

    return g


def _topological_sort(g: ParsedGraph) -> list[str]:
    """
    Kahn's Algorithm — 의존관계 기반 실행 순서 결정.
    Data → Indicator → Condition → Action 순으로 정렬됨.
    """
    in_degree: dict[str, int] = defaultdict(int)
    all_nodes = set(g.node_map.keys())

    for node_id in all_nodes:
        if node_id not in in_degree:
            in_degree[node_id] = 0

    for _src, targets in g.adjacency.items():
        for tgt in targets:
            in_degree[tgt] += 1

    queue = deque([n for n in all_nodes if in_degree[n] == 0])
    order = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for neighbor in g.adjacency.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(order) != len(all_nodes):
        logger.warning("Graph has cycles — partial ordering used")

    return order


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Data Loading — DB 조회 또는 더미 데이터 생성
# ═══════════════════════════════════════════════════════════════════════════════

def _load_ohlcv(symbol: str, lookback: int, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    DB에서 OHLCV 로드. DB 연결 불가 시 시뮬레이션용 더미 데이터 생성.
    """
    # 1차: DB 조회 시도
    try:
        from sqlalchemy import text

        from src.database import get_sync_engine

        engine = get_sync_engine()
        query = """
            SELECT trade_date, open, high, low, close, volume
            FROM daily_prices
            WHERE ticker = :ticker
            ORDER BY trade_date DESC
            LIMIT :limit
        """
        with engine.connect() as conn:
            rows = conn.execute(text(query), {"ticker": symbol, "limit": lookback}).fetchall()

        if rows and len(rows) >= 20:
            df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            logger.info(f"Loaded {len(df)} rows for {symbol} from DB")
            return df
    except Exception as e:
        logger.debug(f"DB load failed for {symbol}: {e}")

    # 2차: 더미 데이터 생성 (GBM 시뮬레이션)
    logger.info(f"Generating dummy OHLCV for {symbol} ({lookback} days)")
    return _generate_dummy_ohlcv(symbol, lookback)


def _generate_dummy_ohlcv(symbol: str, days: int = 200) -> pd.DataFrame:
    """Geometric Brownian Motion 기반 현실적 더미 OHLCV."""
    np.random.seed(hash(symbol) % 2**31)

    # 초기 가격 (종목별로 다르게)
    prices_map = {
        "005930": 70000, "000660": 130000, "035420": 200000,
        "005380": 180000, "051910": 500000, "035720": 50000,
    }
    initial_price = prices_map.get(symbol, 50000 + np.random.randint(0, 100000))

    # GBM 파라미터
    mu = 0.0003       # 일별 기대수익률
    sigma = 0.02      # 일별 변동성

    dates = pd.bdate_range(end=datetime.now(), periods=days)
    returns = np.random.normal(mu, sigma, days)
    prices = initial_price * np.exp(np.cumsum(returns))

    # OHLCV 생성
    data = []
    for _i, (dt, close) in enumerate(zip(dates, prices)):
        intraday_vol = np.random.uniform(0.005, 0.02)
        o = close * (1 + np.random.normal(0, intraday_vol * 0.5))
        h = max(o, close) * (1 + np.random.uniform(0, intraday_vol))
        l = min(o, close) * (1 - np.random.uniform(0, intraday_vol))
        v = int(np.random.lognormal(15, 1))
        data.append({"date": dt, "open": o, "high": h, "low": l, "close": close, "volume": v})

    return pd.DataFrame(data)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Indicator Calculator — pandas 기반 지표 계산
# ═══════════════════════════════════════════════════════════════════════════════

def compute_indicator(df: pd.DataFrame, indicator: IndicatorNodeData) -> pd.Series:
    """지표 ID + 파라미터 → pandas Series 반환."""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]
    p = indicator.params

    calc_map = {
        "rsi":   lambda: _calc_rsi(close, int(p.get("period", 14))),
        "sma":   lambda: close.rolling(int(p.get("period", 20))).mean(),
        "ema":   lambda: close.ewm(span=int(p.get("period", 20)), adjust=False).mean(),
        "macd":  lambda: _calc_macd(close, int(p.get("fast", 12)), int(p.get("slow", 26)), int(p.get("signal", 9)), indicator.output),
        "bb":    lambda: _calc_bollinger(close, int(p.get("period", 20)), float(p.get("std", 2)), indicator.output),
        "atr":   lambda: _calc_atr(high, low, close, int(p.get("period", 14))),
        "stoch": lambda: _calc_stochastic(high, low, close, int(p.get("k", 14)), int(p.get("d", 3)), indicator.output),
        "adx":   lambda: _calc_adx(high, low, close, int(p.get("period", 14))),
        "cci":   lambda: _calc_cci(high, low, close, int(p.get("period", 20))),
        "obv":   lambda: _calc_obv(close, volume),
        "vwap":  lambda: (close * volume).cumsum() / volume.cumsum(),
        "mfi":   lambda: _calc_mfi(high, low, close, volume, int(p.get("period", 14))),
    }

    calc = calc_map.get(indicator.indicatorId)
    if calc is None:
        logger.warning(f"Unknown indicator: {indicator.indicatorId}, returning close")
        return close

    return calc()


def _calc_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def _calc_macd(close: pd.Series, fast: int, slow: int, signal: int, output: str) -> pd.Series:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {"value": macd_line, "signal": signal_line, "histogram": histogram}.get(output, macd_line)


def _calc_bollinger(close: pd.Series, period: int, std_dev: float, output: str) -> pd.Series:
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    return {"upper": upper, "middle": sma, "lower": lower}.get(output, upper)


def _calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    tr = pd.DataFrame({
        "hl": high - low,
        "hc": (high - close.shift(1)).abs(),
        "lc": (low - close.shift(1)).abs(),
    }).max(axis=1)
    return tr.rolling(period).mean()


def _calc_stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k: int, d: int, output: str) -> pd.Series:
    lowest = low.rolling(k).min()
    highest = high.rolling(k).max()
    stoch_k = 100 * (close - lowest) / (highest - lowest + 1e-10)
    stoch_d = stoch_k.rolling(d).mean()
    return {"value": stoch_k, "k": stoch_k, "d": stoch_d}.get(output, stoch_k)


def _calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    atr = _calc_atr(high, low, close, period)
    plus_di = 100 * plus_dm.rolling(period).mean() / (atr + 1e-10)
    minus_di = 100 * minus_dm.rolling(period).mean() / (atr + 1e-10)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    return dx.rolling(period).mean()


def _calc_cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    tp = (high + low + close) / 3
    sma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: (x - x.mean()).abs().mean(), raw=True)
    return (tp - sma) / (0.015 * mad + 1e-10)


def _calc_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    sign = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (sign * volume).cumsum()


def _calc_mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int) -> pd.Series:
    tp = (high + low + close) / 3
    mf = tp * volume
    positive = mf.where(tp > tp.shift(1), 0).rolling(period).sum()
    negative = mf.where(tp < tp.shift(1), 0).rolling(period).sum()
    ratio = positive / (negative + 1e-10)
    return 100 - (100 / (1 + ratio))


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Signal Generator — 조건 평가 + 매매 시그널
# ═══════════════════════════════════════════════════════════════════════════════

def generate_signals(
    df: pd.DataFrame,
    indicators: dict[str, pd.Series],
    graph: ParsedGraph,
) -> pd.Series:
    """
    그래프 연결 관계를 따라 매매 시그널 생성.
    반환: Series of "BUY" | "SELL" | "HOLD"
    """
    n = len(df)
    signals = pd.Series(["HOLD"] * n, index=df.index)

    # Action 노드에 연결된 Indicator를 추적
    for action_id, action_data in graph.actions:
        # 이 Action에 연결된 소스 노드들 (Indicator 또는 Condition)
        source_ids = graph.reverse.get(action_id, [])

        for src_id in source_ids:
            src_data = graph.node_map.get(src_id)

            if isinstance(src_data, IndicatorNodeData):
                # 직접 연결: Indicator → Action
                series = indicators.get(src_id)
                if series is None:
                    continue

                # 기본 조건: RSI < 30 → BUY, RSI > 70 → SELL (지표별 기본 임계값)
                buy_mask, sell_mask = _default_thresholds(src_data, series)

                if action_data.action == "BUY":
                    signals[buy_mask] = "BUY"
                elif action_data.action == "SELL":
                    signals[sell_mask] = "SELL"

            elif isinstance(src_data, ConditionNodeData):
                # Condition → Action: Condition에 연결된 Indicator 찾기
                cond_sources = graph.reverse.get(src_id, [])
                for cond_src in cond_sources:
                    cond_src_data = graph.node_map.get(cond_src)
                    if isinstance(cond_src_data, IndicatorNodeData):
                        series = indicators.get(cond_src)
                        if series is None:
                            continue

                        compare_val = src_data.compareValue if src_data.compareValue is not None else 0
                        mask = _apply_operator(series, src_data.operator, compare_val)

                        if action_data.action == "BUY":
                            signals[mask] = "BUY"
                        elif action_data.action == "SELL":
                            signals[mask] = "SELL"

    return signals


def _default_thresholds(ind: IndicatorNodeData, series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """지표별 기본 매수/매도 임계값."""
    defaults = {
        "rsi":   (30, 70),
        "stoch": (20, 80),
        "cci":   (-100, 100),
        "mfi":   (20, 80),
    }

    if ind.indicatorId in defaults:
        low, high = defaults[ind.indicatorId]
        return series < low, series > high

    # 이동평균류: 가격 > MA → 매수, 가격 < MA → 매도
    if ind.indicatorId in ("sma", "ema", "vwap"):
        return pd.Series(False, index=series.index), pd.Series(False, index=series.index)

    return pd.Series(False, index=series.index), pd.Series(False, index=series.index)


def _apply_operator(series: pd.Series, op: str, value: float) -> pd.Series:
    """연산자 적용."""
    ops = {
        ">":  series > value,
        "<":  series < value,
        ">=": series >= value,
        "<=": series <= value,
        "==": series == value,
        "crosses_above": (series > value) & (series.shift(1) <= value),
        "crosses_below": (series < value) & (series.shift(1) >= value),
    }
    return ops.get(op, pd.Series(False, index=series.index))


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Backtest Engine — 일별 시뮬레이션
# ═══════════════════════════════════════════════════════════════════════════════

def run_backtest(
    df: pd.DataFrame,
    signals: pd.Series,
    initial_capital: float = 100_000_000,
    commission_rate: float = 0.0015,
    slippage_rate: float = 0.0005,
    symbol: str = "005930",
    action_data: ActionNodeData | None = None,
) -> dict:
    """
    일별 백테스트 시뮬레이션.
    반환: statistics, equity_curve, trades, monthly_returns 등
    """
    capital = initial_capital
    position = 0          # 보유 수량
    avg_price = 0.0
    equity = []
    trades = []
    total_commission = 0.0
    total_slippage = 0.0

    stop_loss = (action_data.stopLoss / 100) if action_data and action_data.stopLoss else None
    take_profit = (action_data.takeProfit / 100) if action_data and action_data.takeProfit else None

    for i in range(len(df)):
        price = df.iloc[i]["close"]
        date_str = df.iloc[i]["date"].strftime("%Y-%m-%d") if hasattr(df.iloc[i]["date"], "strftime") else str(df.iloc[i]["date"])[:10]
        signal = signals.iloc[i] if i < len(signals) else "HOLD"

        # Stop loss / Take profit 체크
        if position > 0 and avg_price > 0:
            pnl_pct = (price - avg_price) / avg_price
            if stop_loss and pnl_pct <= -stop_loss:
                signal = "SELL"
            elif take_profit and pnl_pct >= take_profit:
                signal = "SELL"

        if signal == "BUY" and position == 0 and capital > price * 1.01:
            qty = int(capital * 0.95 / price)  # 자본의 95% 투입
            if qty <= 0:
                equity.append(capital)
                continue

            cost = qty * price
            comm = cost * commission_rate
            slip = cost * slippage_rate
            total_commission += comm
            total_slippage += slip

            capital -= (cost + comm + slip)
            position = qty
            avg_price = price

            trades.append(TradeRecord(
                date=date_str, ticker=symbol, side="buy",
                price=round(price, 0), quantity=qty,
                value=round(cost, 0), pnl=None, reason="Graph Signal BUY",
            ))

        elif signal == "SELL" and position > 0:
            revenue = position * price
            comm = revenue * commission_rate
            slip = revenue * slippage_rate
            total_commission += comm
            total_slippage += slip

            pnl = revenue - (position * avg_price) - comm - slip
            capital += revenue - comm - slip

            trades.append(TradeRecord(
                date=date_str, ticker=symbol, side="sell",
                price=round(price, 0), quantity=position,
                value=round(revenue, 0), pnl=round(pnl, 0),
                reason="Graph Signal SELL",
            ))

            position = 0
            avg_price = 0.0

        # Mark-to-market
        total_value = capital + (position * price)
        equity.append(total_value)

    # 마지막 포지션 강제 청산
    if position > 0:
        final_price = df.iloc[-1]["close"]
        revenue = position * final_price
        capital += revenue
        position = 0

    # ── 통계 계산 ────────────────────────────────────────────────────
    eq = np.array(equity)
    if len(eq) < 2:
        return _empty_result()

    dates = [
        (d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10])
        for d in df["date"]
    ]

    total_return = (eq[-1] / eq[0] - 1) * 100
    trading_days = len(eq)
    years = trading_days / 252
    cagr = ((eq[-1] / eq[0]) ** (1 / max(years, 0.01)) - 1) * 100 if eq[0] > 0 else 0

    # Drawdown
    running_max = np.maximum.accumulate(eq)
    drawdown = (eq - running_max) / running_max
    max_dd = float(drawdown.min()) * 100

    # Daily returns
    daily_ret = np.diff(eq) / eq[:-1]
    avg_ret = np.mean(daily_ret) if len(daily_ret) > 0 else 0
    std_ret = np.std(daily_ret) if len(daily_ret) > 0 else 1e-10

    sharpe = (avg_ret / std_ret) * np.sqrt(252) if std_ret > 1e-10 else 0
    neg_std = np.std(daily_ret[daily_ret < 0]) if np.any(daily_ret < 0) else 1e-10
    sortino = (avg_ret / neg_std) * np.sqrt(252) if neg_std > 1e-10 else 0
    calmar = cagr / abs(max_dd) if abs(max_dd) > 0.01 else 0

    # Trade stats
    wins = [t for t in trades if t.side == "sell" and t.pnl is not None and t.pnl > 0]
    losses = [t for t in trades if t.side == "sell" and t.pnl is not None and t.pnl <= 0]
    num_trades = len([t for t in trades if t.side == "sell"])
    win_rate = len(wins) / max(num_trades, 1) * 100
    total_wins = sum(t.pnl for t in wins) if wins else 0
    total_losses = abs(sum(t.pnl for t in losses)) if losses else 1
    profit_factor = total_wins / max(total_losses, 1)
    avg_trade = (total_return / max(num_trades, 1))

    # Monthly returns
    monthly = _calc_monthly_returns(df, eq)

    return {
        "statistics": BacktestStatistics(
            total_return_pct=round(total_return, 2),
            cagr=round(cagr, 2),
            max_drawdown_pct=round(max_dd, 2),
            sharpe_ratio=round(sharpe, 3),
            sortino_ratio=round(sortino, 3),
            calmar_ratio=round(calmar, 3),
            num_trades=len(trades),
            win_rate=round(win_rate, 1),
            profit_factor=round(profit_factor, 3),
            avg_trade_return=round(avg_trade, 3),
            total_commission=round(total_commission, 0),
            total_slippage=round(total_slippage, 0),
        ),
        "equity_curve": [round(v, 0) for v in equity],
        "equity_dates": dates[:len(equity)],
        "drawdown_curve": [round(float(v), 4) for v in drawdown],
        "trades": trades,
        "monthly_returns": monthly,
    }


def _calc_monthly_returns(df: pd.DataFrame, equity: np.ndarray) -> list[dict]:
    """월별 수익률 계산."""
    monthly = []
    try:
        dates = pd.to_datetime(df["date"])
        eq_series = pd.Series(equity[:len(dates)], index=dates)
        monthly_eq = eq_series.resample("M").last().dropna()
        monthly_ret = monthly_eq.pct_change().dropna()

        for dt, ret in monthly_ret.items():
            monthly.append({
                "year": dt.year,
                "month": dt.month,
                "return_pct": round(ret * 100, 2),
            })
    except Exception:
        pass
    return monthly


def _empty_result() -> dict:
    return {
        "statistics": BacktestStatistics(),
        "equity_curve": [],
        "equity_dates": [],
        "drawdown_curve": [],
        "trades": [],
        "monthly_returns": [],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Master Entry Point — 전체 파이프라인
# ═══════════════════════════════════════════════════════════════════════════════

def execute_graph_backtest(req: GraphBacktestRequest) -> GraphBacktestResponse:
    """
    전체 파이프라인:
      그래프 파싱 → 데이터 로드 → 지표 계산 → 시그널 → 백테스트 → 응답
    """
    try:
        # 1. 그래프 파싱
        graph = parse_graph(req)

        if not graph.data_sources:
            return GraphBacktestResponse(
                success=False,
                message="데이터 소스 노드가 없습니다. DataSource 노드를 추가하세요.",
                parsed_strategy=graph.to_dict(),
            )

        if not graph.actions:
            return GraphBacktestResponse(
                success=False,
                message="매매 실행 노드가 없습니다. Action 노드를 추가하세요.",
                parsed_strategy=graph.to_dict(),
            )

        # 2. 데이터 로드 (첫 번째 DataSource 사용)
        ds_id, ds_data = graph.data_sources[0]
        df = _load_ohlcv(
            symbol=ds_data.symbol,
            lookback=ds_data.lookback,
            start_date=req.start_date,
            end_date=req.end_date,
        )

        if df.empty or len(df) < 20:
            return GraphBacktestResponse(
                success=False,
                message=f"OHLCV 데이터가 부족합니다 ({ds_data.symbol}: {len(df)}행)",
                parsed_strategy=graph.to_dict(),
            )

        # 3. 지표 계산
        indicator_results: dict[str, pd.Series] = {}
        for ind_id, ind_data in graph.indicators:
            try:
                series = compute_indicator(df, ind_data)
                indicator_results[ind_id] = series
            except Exception as e:
                logger.warning(f"Indicator {ind_data.label} failed: {e}")

        # 4. 시그널 생성
        signals = generate_signals(df, indicator_results, graph)

        # 5. 백테스트 실행
        action_data = graph.actions[0][1] if graph.actions else None
        result = run_backtest(
            df=df,
            signals=signals,
            initial_capital=req.initial_capital,
            commission_rate=req.commission_rate,
            slippage_rate=req.slippage_rate,
            symbol=ds_data.symbol,
            action_data=action_data,
        )

        return GraphBacktestResponse(
            success=True,
            message=f"백테스트 완료: {ds_data.symbol}, {len(df)}일, {result['statistics'].num_trades}회 거래",
            parsed_strategy=graph.to_dict(),
            statistics=result["statistics"],
            equity_curve=result["equity_curve"],
            equity_dates=result["equity_dates"],
            drawdown_curve=result["drawdown_curve"],
            monthly_returns=result["monthly_returns"],
            trades=[t.model_dump() if hasattr(t, 'model_dump') else t for t in result["trades"]],
            symbol_results=[{
                "symbol": ds_data.symbol,
                "total_return_pct": result["statistics"].total_return_pct,
                "num_trades": result["statistics"].num_trades,
                "win_rate": result["statistics"].win_rate,
            }],
        )

    except Exception as e:
        logger.error(f"Graph backtest failed: {e}", exc_info=True)
        return GraphBacktestResponse(
            success=False,
            message=f"백테스트 실행 오류: {str(e)}",
        )
