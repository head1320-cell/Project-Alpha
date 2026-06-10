"""
DAG Strategy Execution Engine — Enterprise Grade
==================================================
NetworkX 방향성 비순환 그래프(DAG) 기반 전략 실행 엔진.

Architecture:
  GraphBacktestRequest
    → DAGBuilder.build()          : NetworkX DiGraph 구축 + 순환 검증
    → nx.topological_sort()       : 실행 순서 결정
    → NodeProcessorFactory        : 노드별 프로세서 팩토리
    → VectorizedIndicatorEngine   : pandas 벡터화 지표 계산
    → ASTEvaluator                : 안전한 조건 평가 (eval 금지)
    → VectorizedBacktestEngine    : 벡터화 백테스트 시뮬레이션
    → GraphBacktestResponse

Performance:
  - 모든 지표/시그널 계산은 pandas 벡터화 연산 (for 루프 금지)
  - 백테스트 시뮬레이션만 순차 처리 (포지션 상태 의존)
"""

from __future__ import annotations

import abc
import logging
from datetime import datetime
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd

from src.engine.ast_evaluator import (
    combine_masks,
    evaluate_condition,
    get_default_masks,
)
from src.models.graph_schema import (
    ActionNodeData,
    BacktestStatistics,
    ConditionNodeData,
    DataSourceNodeData,
    GraphBacktestRequest,
    GraphBacktestResponse,
    IndicatorNodeData,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. DAG Builder — NetworkX DiGraph 구축 + 순환 검증
# ═══════════════════════════════════════════════════════════════════════════════

class CyclicGraphError(Exception):
    """그래프에 순환 참조가 발견됨."""
    pass


class DAGBuilder:
    """React Flow 노드/엣지 → NetworkX DAG 변환."""

    @staticmethod
    def build(req: GraphBacktestRequest) -> tuple[nx.DiGraph, dict[str, Any]]:
        """
        그래프 구축 + 검증.

        Returns:
            (dag, node_data_map)
            - dag: NetworkX DiGraph (위상 정렬 가능)
            - node_data_map: {node_id: parsed_data} 매핑

        Raises:
            CyclicGraphError: 순환 참조 발견 시
            ValueError: 노드 파싱 실패 시
        """
        dag = nx.DiGraph()
        node_data_map: dict[str, Any] = {}

        # 노드 추가 + 데이터 파싱
        for node in req.nodes:
            parsed = node.parse_data()
            node_data_map[node.id] = parsed
            dag.add_node(node.id, data=parsed, node_type=type(parsed).__name__)

        # 엣지 추가
        for edge in req.edges:
            dag.add_edge(edge.source, edge.target)

        # ── 순환 검증 (핵심) ──────────────────────────────────────────
        if not nx.is_directed_acyclic_graph(dag):
            cycles = list(nx.simple_cycles(dag))
            cycle_str = " → ".join(cycles[0]) if cycles else "unknown"
            raise CyclicGraphError(
                f"순환 참조 발견: {cycle_str}. "
                f"DAG(방향성 비순환 그래프)만 허용됩니다."
            )

        return dag, node_data_map

    @staticmethod
    def get_execution_order(dag: nx.DiGraph) -> list[str]:
        """위상 정렬 — 의존관계 기반 실행 순서."""
        return list(nx.topological_sort(dag))

    @staticmethod
    def get_predecessors(dag: nx.DiGraph, node_id: str) -> list[str]:
        """특정 노드의 모든 선행 노드 (입력 소스)."""
        return list(dag.predecessors(node_id))

    @staticmethod
    def get_successors(dag: nx.DiGraph, node_id: str) -> list[str]:
        """특정 노드의 모든 후행 노드 (출력 대상)."""
        return list(dag.successors(node_id))

    @staticmethod
    def classify_nodes(
        node_data_map: dict[str, Any],
    ) -> dict[str, list[tuple[str, Any]]]:
        """노드를 타입별로 분류."""
        classified = {
            "datasource": [],
            "indicator": [],
            "condition": [],
            "action": [],
        }
        for nid, data in node_data_map.items():
            if isinstance(data, DataSourceNodeData):
                classified["datasource"].append((nid, data))
            elif isinstance(data, IndicatorNodeData):
                classified["indicator"].append((nid, data))
            elif isinstance(data, ConditionNodeData):
                classified["condition"].append((nid, data))
            elif isinstance(data, ActionNodeData):
                classified["action"].append((nid, data))
        return classified


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Node Processor — Factory Pattern
# ═══════════════════════════════════════════════════════════════════════════════

class ExecutionContext:
    """노드 실행 중 공유되는 컨텍스트."""
    def __init__(self):
        self.dataframes: dict[str, pd.DataFrame] = {}     # node_id → OHLCV
        self.indicators: dict[str, pd.Series] = {}         # node_id → 지표 시리즈
        self.masks: dict[str, pd.Series] = {}              # node_id → bool mask
        self.signals: pd.Series | None = None           # 최종 BUY/SELL/HOLD
        self.primary_df: pd.DataFrame | None = None     # 첫 번째 데이터소스
        self.primary_symbol: str = ""


class NodeProcessor(abc.ABC):
    """노드 프로세서 추상 클래스."""
    @abc.abstractmethod
    def process(
        self, node_id: str, data: Any,
        dag: nx.DiGraph, ctx: ExecutionContext,
    ) -> None:
        ...


class DataSourceProcessor(NodeProcessor):
    """데이터 소스 노드 처리 — OHLCV 로드."""

    def process(self, node_id: str, data: DataSourceNodeData,
                dag: nx.DiGraph, ctx: ExecutionContext) -> None:
        df = _load_ohlcv(data.symbol, data.lookback)
        ctx.dataframes[node_id] = df
        if ctx.primary_df is None:
            ctx.primary_df = df
            ctx.primary_symbol = data.symbol
        logger.info(f"[{node_id}] Loaded {len(df)} rows for {data.symbol}")


class IndicatorProcessor(NodeProcessor):
    """지표 노드 처리 — 벡터화 계산."""

    def process(self, node_id: str, data: IndicatorNodeData,
                dag: nx.DiGraph, ctx: ExecutionContext) -> None:
        df = ctx.primary_df
        if df is None or df.empty:
            logger.warning(f"[{node_id}] No DataFrame available")
            return

        series = VectorizedIndicatorEngine.compute(df, data)
        ctx.indicators[node_id] = series
        logger.info(f"[{node_id}] Computed {data.label} ({data.indicatorId})")


class ConditionProcessor(NodeProcessor):
    """조건 노드 처리 — AST 평가기로 Boolean Mask 생성."""

    def process(self, node_id: str, data: ConditionNodeData,
                dag: nx.DiGraph, ctx: ExecutionContext) -> None:
        predecessors = DAGBuilder.get_predecessors(dag, node_id)
        masks: list[pd.Series] = []

        for pred_id in predecessors:
            series = ctx.indicators.get(pred_id)
            if series is None:
                continue

            if data.compareValue is not None:
                mask = evaluate_condition(series, data.operator, data.compareValue)
            elif data.compareIndicator and data.compareIndicator in ctx.indicators:
                other = ctx.indicators[data.compareIndicator]
                mask = evaluate_condition(series, data.operator, other)
            else:
                mask = evaluate_condition(series, data.operator, data.compareValue or 0)

            masks.append(mask)

        if masks:
            ctx.masks[node_id] = combine_masks(masks, data.logic)
            logger.info(f"[{node_id}] Condition evaluated: {data.operator} {data.compareValue}")
        else:
            logger.warning(f"[{node_id}] No input indicators found")


class ActionProcessor(NodeProcessor):
    """액션 노드 처리 — 시그널 시리즈 생성."""

    def process(self, node_id: str, data: ActionNodeData,
                dag: nx.DiGraph, ctx: ExecutionContext) -> None:
        if ctx.primary_df is None:
            return

        n = len(ctx.primary_df)
        if ctx.signals is None:
            ctx.signals = pd.Series(["HOLD"] * n, index=ctx.primary_df.index)

        predecessors = DAGBuilder.get_predecessors(dag, node_id)

        for pred_id in predecessors:
            # Case 1: Condition → Action
            if pred_id in ctx.masks:
                mask = ctx.masks[pred_id]
                if data.action in ("BUY", "SELL"):
                    ctx.signals[mask] = data.action

            # Case 2: Indicator → Action (직접 연결, 기본 임계값 사용)
            elif pred_id in ctx.indicators:
                series = ctx.indicators[pred_id]
                pred_data = dag.nodes[pred_id].get("data")
                if isinstance(pred_data, IndicatorNodeData):
                    buy_mask, sell_mask = get_default_masks(
                        pred_data.indicatorId, series
                    )
                    if data.action == "BUY":
                        ctx.signals[buy_mask] = "BUY"
                    elif data.action == "SELL":
                        ctx.signals[sell_mask] = "SELL"

        logger.info(f"[{node_id}] Action applied: {data.action}")


# ── Factory ──────────────────────────────────────────────────────────────────

class NodeProcessorFactory:
    """노드 타입 → 프로세서 매핑 팩토리."""

    _registry: dict[type, type[NodeProcessor]] = {
        DataSourceNodeData: DataSourceProcessor,
        IndicatorNodeData:  IndicatorProcessor,
        ConditionNodeData:  ConditionProcessor,
        ActionNodeData:     ActionProcessor,
    }

    @classmethod
    def get_processor(cls, data: Any) -> NodeProcessor:
        proc_cls = cls._registry.get(type(data))
        if proc_cls is None:
            raise ValueError(f"No processor for {type(data).__name__}")
        return proc_cls()

    @classmethod
    def register(cls, data_type: type, processor_type: type[NodeProcessor]) -> None:
        """커스텀 노드 프로세서 등록 (확장용)."""
        cls._registry[data_type] = processor_type


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Vectorized Indicator Engine — 100% pandas 벡터화
# ═══════════════════════════════════════════════════════════════════════════════

class VectorizedIndicatorEngine:
    """지표 계산 — 모든 연산이 pandas/numpy 벡터화."""

    @staticmethod
    def compute(df: pd.DataFrame, ind: IndicatorNodeData) -> pd.Series:
        close = df["close"].astype(float)
        high  = df["high"].astype(float)
        low   = df["low"].astype(float)
        volume = df["volume"].astype(float)
        p = ind.params

        dispatch = {
            "rsi":   lambda: VectorizedIndicatorEngine._rsi(close, int(p.get("period", 14))),
            "sma":   lambda: close.rolling(int(p.get("period", 20)), min_periods=1).mean(),
            "ema":   lambda: close.ewm(span=int(p.get("period", 20)), adjust=False).mean(),
            "macd":  lambda: VectorizedIndicatorEngine._macd(close, int(p.get("fast", 12)), int(p.get("slow", 26)), int(p.get("signal", 9)), ind.output),
            "bb":    lambda: VectorizedIndicatorEngine._bollinger(close, int(p.get("period", 20)), float(p.get("std", 2)), ind.output),
            "atr":   lambda: VectorizedIndicatorEngine._atr(high, low, close, int(p.get("period", 14))),
            "stoch": lambda: VectorizedIndicatorEngine._stochastic(high, low, close, int(p.get("k", 14)), int(p.get("d", 3)), ind.output),
            "adx":   lambda: VectorizedIndicatorEngine._adx(high, low, close, int(p.get("period", 14))),
            "cci":   lambda: VectorizedIndicatorEngine._cci(high, low, close, int(p.get("period", 20))),
            "obv":   lambda: VectorizedIndicatorEngine._obv(close, volume),
            "vwap":  lambda: (close * volume).cumsum() / volume.cumsum().replace(0, 1),
            "mfi":   lambda: VectorizedIndicatorEngine._mfi(high, low, close, volume, int(p.get("period", 14))),
        }

        calc = dispatch.get(ind.indicatorId)
        if calc is None:
            logger.warning(f"Unknown indicator '{ind.indicatorId}', returning close")
            return close
        return calc()

    # ── 모든 지표: 100% 벡터화 (for 루프 없음) ─────────────────────────

    @staticmethod
    def _rsi(close: pd.Series, period: int) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        rs = gain / loss.replace(0, 1e-10)
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def _macd(close: pd.Series, fast: int, slow: int, signal: int, output: str) -> pd.Series:
        ema_f = close.ewm(span=fast, adjust=False).mean()
        ema_s = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_f - ema_s
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return {"value": macd_line, "signal": signal_line, "histogram": histogram}.get(output, macd_line)

    @staticmethod
    def _bollinger(close: pd.Series, period: int, std_dev: float, output: str) -> pd.Series:
        sma = close.rolling(period, min_periods=1).mean()
        std = close.rolling(period, min_periods=1).std().fillna(0)
        return {"upper": sma + std_dev * std, "middle": sma, "lower": sma - std_dev * std}.get(output, sma + std_dev * std)

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        prev_close = close.shift(1)
        tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

    @staticmethod
    def _stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k: int, d: int, output: str) -> pd.Series:
        lowest  = low.rolling(k, min_periods=1).min()
        highest = high.rolling(k, min_periods=1).max()
        stoch_k = 100.0 * (close - lowest) / (highest - lowest).replace(0, 1e-10)
        stoch_d = stoch_k.rolling(d, min_periods=1).mean()
        return {"value": stoch_k, "k": stoch_k, "d": stoch_d}.get(output, stoch_k)

    @staticmethod
    def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        plus_dm = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)
        atr = VectorizedIndicatorEngine._atr(high, low, close, period)
        plus_di = 100.0 * plus_dm.ewm(alpha=1/period, min_periods=period, adjust=False).mean() / atr.replace(0, 1e-10)
        minus_di = 100.0 * minus_dm.ewm(alpha=1/period, min_periods=period, adjust=False).mean() / atr.replace(0, 1e-10)
        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10)
        return dx.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

    @staticmethod
    def _cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        tp = (high + low + close) / 3.0
        sma = tp.rolling(period, min_periods=1).mean()
        mad = tp.rolling(period, min_periods=1).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        return (tp - sma) / (0.015 * mad).replace(0, 1e-10)

    @staticmethod
    def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
        sign = np.sign(close.diff()).fillna(0)
        return (sign * volume).cumsum()

    @staticmethod
    def _mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int) -> pd.Series:
        tp = (high + low + close) / 3.0
        mf = tp * volume
        pos = mf.where(tp > tp.shift(1), 0).rolling(period, min_periods=1).sum()
        neg = mf.where(tp < tp.shift(1), 0).rolling(period, min_periods=1).sum()
        ratio = pos / neg.replace(0, 1e-10)
        return 100.0 - (100.0 / (1.0 + ratio))


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Data Loader
# ═══════════════════════════════════════════════════════════════════════════════

def _load_ohlcv(symbol: str, lookback: int) -> pd.DataFrame:
    """DB 조회 → 실패 시 GBM 더미 데이터 자동 생성."""
    try:
        from sqlalchemy import text

        from src.database import get_sync_engine
        engine = get_sync_engine()
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT trade_date, open, high, low, close, volume "
                "FROM daily_prices WHERE ticker = :t "
                "ORDER BY trade_date DESC LIMIT :n"
            ), {"t": symbol, "n": lookback}).fetchall()
        if rows and len(rows) >= 20:
            df = pd.DataFrame(rows, columns=["date","open","high","low","close","volume"])
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)
    except Exception as e:
        logger.debug(f"DB load failed for {symbol}: {e}")

    return _generate_gbm(symbol, lookback)


def _generate_gbm(symbol: str, days: int) -> pd.DataFrame:
    """GBM 기반 현실적 더미 OHLCV."""
    np.random.seed(hash(symbol) % 2**31)
    initial = {"005930": 70000, "000660": 130000, "035420": 200000}.get(
        symbol, 50000 + np.random.randint(0, 100000)
    )
    mu, sigma = 0.0003, 0.02
    dates = pd.bdate_range(end=datetime.now(), periods=days)
    log_returns = np.random.normal(mu, sigma, days)
    prices = initial * np.exp(np.cumsum(log_returns))
    vol = np.random.uniform(0.005, 0.02, days)
    opens  = prices * (1 + np.random.normal(0, vol * 0.5))
    highs  = np.maximum(opens, prices) * (1 + np.random.uniform(0, vol))
    lows   = np.minimum(opens, prices) * (1 - np.random.uniform(0, vol))
    vols   = np.random.lognormal(15, 1, days).astype(int)
    return pd.DataFrame({"date": dates, "open": opens, "high": highs, "low": lows, "close": prices, "volume": vols})


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Vectorized Backtest Engine
# ═══════════════════════════════════════════════════════════════════════════════

def run_vectorized_backtest(
    df: pd.DataFrame,
    signals: pd.Series,
    initial_capital: float,
    commission_rate: float,
    slippage_rate: float,
    symbol: str,
    action_data: ActionNodeData | None = None,
) -> dict:
    """일별 백테스트 시뮬레이션 (포지션 상태 의존이므로 순차)."""
    capital = initial_capital
    position = 0
    avg_price = 0.0
    equity = np.empty(len(df))
    trades: list[dict] = []
    total_comm = 0.0
    total_slip = 0.0
    stop_loss = (action_data.stopLoss / 100) if action_data and action_data.stopLoss else None
    take_profit = (action_data.takeProfit / 100) if action_data and action_data.takeProfit else None
    close_arr = df["close"].values
    date_arr = df["date"].values

    for i in range(len(df)):
        price = float(close_arr[i])
        dt = str(date_arr[i])[:10]
        sig = signals.iloc[i] if i < len(signals) else "HOLD"

        if position > 0 and avg_price > 0:
            pnl_pct = (price - avg_price) / avg_price
            if stop_loss and pnl_pct <= -stop_loss:
                sig = "SELL"
            elif take_profit and pnl_pct >= take_profit:
                sig = "SELL"

        if sig == "BUY" and position == 0 and capital > price * 1.01:
            qty = int(capital * 0.95 / price)
            if qty > 0:
                cost = qty * price
                c = cost * commission_rate
                s = cost * slippage_rate
                total_comm += c; total_slip += s
                capital -= (cost + c + s)
                position = qty; avg_price = price
                trades.append({"date": dt, "ticker": symbol, "side": "buy", "price": round(price), "quantity": qty, "value": round(cost), "pnl": None, "reason": "DAG BUY"})

        elif sig == "SELL" and position > 0:
            revenue = position * price
            c = revenue * commission_rate
            s = revenue * slippage_rate
            total_comm += c; total_slip += s
            pnl = revenue - (position * avg_price) - c - s
            capital += revenue - c - s
            trades.append({"date": dt, "ticker": symbol, "side": "sell", "price": round(price), "quantity": position, "value": round(revenue), "pnl": round(pnl), "reason": "DAG SELL"})
            position = 0; avg_price = 0.0

        equity[i] = capital + position * price

    # ── Statistics (벡터화) ───────────────────────────────────────────
    if len(equity) < 2:
        return _empty_result()

    eq = equity
    total_ret = (eq[-1] / eq[0] - 1) * 100
    years = len(eq) / 252
    cagr = ((eq[-1] / eq[0]) ** (1 / max(years, 0.01)) - 1) * 100 if eq[0] > 0 else 0
    running_max = np.maximum.accumulate(eq)
    dd = (eq - running_max) / np.where(running_max > 0, running_max, 1)
    max_dd = float(dd.min()) * 100
    daily_ret = np.diff(eq) / eq[:-1]
    avg_r = np.mean(daily_ret)
    std_r = np.std(daily_ret) if np.std(daily_ret) > 1e-10 else 1e-10
    sharpe = (avg_r / std_r) * np.sqrt(252)
    neg_std = np.std(daily_ret[daily_ret < 0]) if np.any(daily_ret < 0) else 1e-10
    sortino = (avg_r / neg_std) * np.sqrt(252)
    calmar = cagr / abs(max_dd) if abs(max_dd) > 0.01 else 0

    sells = [t for t in trades if t["side"] == "sell"]
    wins = [t for t in sells if t["pnl"] is not None and t["pnl"] > 0]
    losses = [t for t in sells if t["pnl"] is not None and t["pnl"] <= 0]
    wr = len(wins) / max(len(sells), 1) * 100
    tw = sum(t["pnl"] for t in wins) if wins else 0
    tl = abs(sum(t["pnl"] for t in losses)) if losses else 1
    pf = tw / max(tl, 1)
    avg_tr = total_ret / max(len(sells), 1)

    dates = [str(d)[:10] for d in df["date"].values]

    # Monthly returns (벡터화)
    monthly = []
    try:
        eq_s = pd.Series(equity[:len(dates)], index=pd.to_datetime(dates[:len(equity)]))
        m_eq = eq_s.resample("ME").last().dropna()
        m_ret = m_eq.pct_change().dropna()
        monthly = [{"year": dt.year, "month": dt.month, "return_pct": round(r * 100, 2)} for dt, r in m_ret.items()]
    except Exception:
        pass

    return {
        "statistics": BacktestStatistics(
            total_return_pct=round(total_ret, 2), cagr=round(cagr, 2),
            max_drawdown_pct=round(max_dd, 2), sharpe_ratio=round(sharpe, 3),
            sortino_ratio=round(sortino, 3), calmar_ratio=round(calmar, 3),
            num_trades=len(trades), win_rate=round(wr, 1),
            profit_factor=round(pf, 3), avg_trade_return=round(avg_tr, 3),
            total_commission=round(total_comm), total_slippage=round(total_slip),
        ),
        "equity_curve": [round(v) for v in equity],
        "equity_dates": dates[:len(equity)],
        "drawdown_curve": [round(float(v), 4) for v in dd],
        "trades": trades,
        "monthly_returns": monthly,
    }


def _empty_result() -> dict:
    return {"statistics": BacktestStatistics(), "equity_curve": [], "equity_dates": [], "drawdown_curve": [], "trades": [], "monthly_returns": []}


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Master Entry Point — DAG 실행 파이프라인
# ═══════════════════════════════════════════════════════════════════════════════

def execute_dag_backtest(req: GraphBacktestRequest) -> GraphBacktestResponse:
    """
    엔터프라이즈 DAG 백테스트 파이프라인:
      1. DAG 구축 + 순환 검증
      2. 위상 정렬
      3. 팩토리 기반 노드 순차 실행
      4. 벡터화 백테스트
      5. 결과 반환
    """
    try:
        # ── 1. DAG 구축 ──────────────────────────────────────────────
        dag, node_data_map = DAGBuilder.build(req)
        classified = DAGBuilder.classify_nodes(node_data_map)
        execution_order = DAGBuilder.get_execution_order(dag)

        logger.info(
            f"DAG built: {dag.number_of_nodes()} nodes, "
            f"{dag.number_of_edges()} edges, "
            f"order={execution_order}"
        )

        # 기본 검증
        if not classified["datasource"]:
            return GraphBacktestResponse(
                success=False,
                message="데이터 소스 노드가 없습니다.",
                parsed_strategy=_strategy_summary(classified, execution_order),
            )
        if not classified["action"]:
            return GraphBacktestResponse(
                success=False,
                message="매매 실행 노드가 없습니다.",
                parsed_strategy=_strategy_summary(classified, execution_order),
            )

        # ── 2. 실행 컨텍스트 초기화 ──────────────────────────────────
        ctx = ExecutionContext()

        # ── 3. 위상 정렬 순서로 노드 실행 (Factory Pattern) ──────────
        for node_id in execution_order:
            data = node_data_map.get(node_id)
            if data is None:
                continue

            processor = NodeProcessorFactory.get_processor(data)
            processor.process(node_id, data, dag, ctx)

        # ── 4. 시그널 검증 ───────────────────────────────────────────
        if ctx.signals is None or ctx.primary_df is None:
            return GraphBacktestResponse(
                success=False,
                message="시그널이 생성되지 않았습니다. 노드 연결을 확인하세요.",
                parsed_strategy=_strategy_summary(classified, execution_order),
            )

        # ── 5. 벡터화 백테스트 ───────────────────────────────────────
        action_data = classified["action"][0][1] if classified["action"] else None
        result = run_vectorized_backtest(
            df=ctx.primary_df,
            signals=ctx.signals,
            initial_capital=req.initial_capital,
            commission_rate=req.commission_rate,
            slippage_rate=req.slippage_rate,
            symbol=ctx.primary_symbol,
            action_data=action_data,
        )

        return GraphBacktestResponse(
            success=True,
            message=(
                f"DAG 백테스트 완료: {ctx.primary_symbol}, "
                f"{len(ctx.primary_df)}일, "
                f"{result['statistics'].num_trades}회 거래"
            ),
            parsed_strategy=_strategy_summary(classified, execution_order),
            statistics=result["statistics"],
            equity_curve=result["equity_curve"],
            equity_dates=result["equity_dates"],
            drawdown_curve=result["drawdown_curve"],
            monthly_returns=result["monthly_returns"],
            trades=result["trades"],
            symbol_results=[{
                "symbol": ctx.primary_symbol,
                "total_return_pct": result["statistics"].total_return_pct,
                "num_trades": result["statistics"].num_trades,
                "win_rate": result["statistics"].win_rate,
            }],
        )

    except CyclicGraphError as e:
        return GraphBacktestResponse(success=False, message=str(e))
    except ValueError as e:
        return GraphBacktestResponse(success=False, message=f"Validation error: {e}")
    except Exception as e:
        logger.error(f"DAG backtest failed: {e}", exc_info=True)
        return GraphBacktestResponse(success=False, message=f"실행 오류: {e}")


def _strategy_summary(classified: dict, order: list[str]) -> dict:
    return {
        "data_sources": [(nid, d.model_dump()) for nid, d in classified["datasource"]],
        "indicators":   [(nid, d.model_dump()) for nid, d in classified["indicator"]],
        "conditions":   [(nid, d.model_dump()) for nid, d in classified["condition"]],
        "actions":      [(nid, d.model_dump()) for nid, d in classified["action"]],
        "execution_order": order,
        "node_count": sum(len(v) for v in classified.values()),
    }
