"""
Portfolio Analyzer & Rebalancer
================================
KIS backtester/kis_backtest/portfolio/analyzer.py + rebalance.py 이식.

원본 그대로의 로직:
  PortfolioAnalyzer   — 상관관계, 분산비율, 효율적 프론티어, 리스크 기여도
  PortfolioRebalancer — 주기적 리밸런싱 시뮬레이션

DB 연동:
  daily_prices 테이블에서 수익률 시계열 자동 로드.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)

TRADING_DAYS = 252


# ═══════════════════════════════════════════════════════════════════════════════
# DB 수익률 로더
# ═══════════════════════════════════════════════════════════════════════════════

def load_returns(
    tickers: list[str],
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    DB에서 종목별 일별 수익률 로드.

    Returns:
        DataFrame: index=날짜, columns=종목코드, values=일별 수익률
    """
    try:
        from src.database import get_engine
        engine = get_engine()
    except Exception:
        return pd.DataFrame()

    codes = [t.replace(".KS", "").replace(".KQ", "") for t in tickers]
    placeholders = ",".join(f"'{c}'" for c in codes)
    sql = text(f"""
        SELECT ticker, trade_date, close
        FROM daily_prices
        WHERE ticker IN ({placeholders})
          AND trade_date BETWEEN :start AND :end
        ORDER BY ticker, trade_date ASC
    """)
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, {"start": start_date, "end": end_date}).fetchall()

        if not rows:
            return pd.DataFrame()

        df_raw = pd.DataFrame(rows, columns=["ticker", "date", "close"])
        df_raw["date"] = pd.to_datetime(df_raw["date"])
        pivot = df_raw.pivot(index="date", columns="ticker", values="close")
        returns = pivot.pct_change().dropna(how="all")
        return returns

    except Exception as e:
        logger.error(f"load_returns error: {e}")
        return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════════════════
# Data models
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PortfolioMetrics:
    """포트폴리오 분석 결과 — KIS 원본과 동일한 구조."""
    correlation_matrix: pd.DataFrame
    returns: pd.DataFrame
    volatilities: pd.Series
    portfolio_return: float
    portfolio_volatility: float
    portfolio_sharpe: float
    diversification_ratio: float
    risk_contributions: pd.Series
    weights: pd.Series
    covariance_matrix: pd.DataFrame
    efficient_frontier: pd.DataFrame | None = None
    optimal_weights: pd.Series | None = None

    def summary(self) -> dict[str, float]:
        return {
            "기대수익률": round(self.portfolio_return * 100, 2),
            "변동성": round(self.portfolio_volatility * 100, 2),
            "샤프비율": round(self.portfolio_sharpe, 3),
            "분산비율": round(self.diversification_ratio, 3),
        }

    def to_api_dict(self) -> dict:
        """API 응답용 직렬화."""
        return {
            "statistics": self.summary(),
            "correlation": self.correlation_matrix.round(4).to_dict(),
            "volatilities": {k: round(float(v) * 100, 2)
                             for k, v in self.volatilities.items()},
            "risk_contributions": {k: round(float(v) * 100, 2)
                                    for k, v in self.risk_contributions.items()},
            "weights": {k: round(float(v) * 100, 2)
                         for k, v in self.weights.items()},
            "efficient_frontier": (
                self.efficient_frontier.round(4).to_dict("records")
                if self.efficient_frontier is not None else []
            ),
            "optimal_weights": (
                {k: round(float(v) * 100, 2)
                 for k, v in self.optimal_weights.items()}
                if self.optimal_weights is not None else {}
            ),
        }


@dataclass
class RebalanceResult:
    """리밸런싱 시뮬레이션 결과 — KIS 원본과 동일."""
    equity_curve: pd.Series
    no_rebalance_curve: pd.Series
    final_return: float
    no_rebalance_return: float
    rebalance_benefit: float
    rebalance_dates: list
    rebalance_count: int
    turnover: float
    transaction_cost: float

    def summary(self) -> dict[str, float]:
        return {
            "리밸런싱_수익률": round(self.final_return * 100, 2),
            "BuyHold_수익률": round(self.no_rebalance_return * 100, 2),
            "리밸런싱_효과": round(self.rebalance_benefit * 100, 2),
            "리밸런싱_횟수": self.rebalance_count,
            "총_회전율": round(self.turnover * 100, 2),
            "거래비용": round(self.transaction_cost, 0),
        }

    def to_api_dict(self) -> dict:
        return {
            "summary": self.summary(),
            "equity_curve": {
                "dates": [d.strftime("%Y-%m-%d") for d in self.equity_curve.index],
                "rebalanced": [round(float(v), 0) for v in self.equity_curve.values],
                "buy_hold": [round(float(v), 0) for v in self.no_rebalance_curve.values],
            },
            "rebalance_dates": [
                d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                for d in self.rebalance_dates
            ],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Portfolio Analyzer — KIS 원본 로직 그대로
# ═══════════════════════════════════════════════════════════════════════════════

class PortfolioAnalyzer:
    """
    포트폴리오 분석기 — KIS 원본 그대로.

    상관관계 분석, 분산 효과, 효율적 프론티어, 리스크 기여도 계산.
    """

    def __init__(
        self,
        returns: pd.DataFrame,
        weights: dict[str, float] | None = None,
        risk_free_rate: float = 0.035,
        trading_days: int = TRADING_DAYS,
    ):
        self.returns = returns.dropna()
        self.symbols = list(returns.columns)
        self.risk_free_rate = risk_free_rate
        self.trading_days = trading_days

        if weights is None:
            n = len(self.symbols)
            self.weights = pd.Series({s: 1 / n for s in self.symbols})
        else:
            self.weights = pd.Series(weights)
            self.weights = self.weights / self.weights.sum()

    def analyze(self) -> PortfolioMetrics:
        """전체 분석 실행 — 원본 그대로."""
        corr = self.returns.corr()
        volatilities = self.returns.std() * np.sqrt(self.trading_days)
        cov = self.returns.cov() * self.trading_days
        mean_returns = self.returns.mean() * self.trading_days

        w = self.weights.reindex(self.symbols).fillna(0).values
        portfolio_return = float(np.dot(w, mean_returns.reindex(self.symbols).fillna(0).values))
        portfolio_volatility = float(np.sqrt(np.dot(w.T, np.dot(cov.values, w))))

        if portfolio_volatility > 0:
            portfolio_sharpe = (portfolio_return - self.risk_free_rate) / portfolio_volatility
        else:
            portfolio_sharpe = 0.0

        weighted_vol = float((volatilities * self.weights.reindex(self.symbols).fillna(0)).sum())
        diversification_ratio = (weighted_vol / portfolio_volatility
                                  if portfolio_volatility > 0 else 1.0)

        if portfolio_volatility > 0:
            marginal = np.dot(cov.values, w) / portfolio_volatility
            risk_contributions = pd.Series(w * marginal, index=self.symbols)
        else:
            risk_contributions = pd.Series(0.0, index=self.symbols)

        return PortfolioMetrics(
            correlation_matrix=corr,
            returns=self.returns,
            volatilities=volatilities,
            portfolio_return=portfolio_return,
            portfolio_volatility=portfolio_volatility,
            portfolio_sharpe=portfolio_sharpe,
            diversification_ratio=diversification_ratio,
            risk_contributions=risk_contributions,
            weights=self.weights.reindex(self.symbols).fillna(0),
            covariance_matrix=cov,
        )

    def efficient_frontier(
        self,
        n_points: int = 30,
        allow_short: bool = False,
    ) -> pd.DataFrame:
        """효율적 프론티어 — KIS 원본 그대로 (scipy minimize)."""
        try:
            from scipy.optimize import minimize
        except ImportError:
            logger.warning("scipy required for efficient frontier")
            return pd.DataFrame()

        n = len(self.symbols)
        cov = self.returns.cov().values * self.trading_days
        mean_returns = self.returns.mean().values * self.trading_days

        bounds = ((-1.0, 1.0) if allow_short else (0.0, 1.0),) * n
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        frontier = []
        for target in np.linspace(mean_returns.min(), mean_returns.max(), n_points):
            constraints_with_return = constraints + [
                {"type": "eq", "fun": lambda w, t=target: np.dot(w, mean_returns) - t}
            ]
            result = minimize(
                lambda w: np.sqrt(np.dot(w.T, np.dot(cov, w))),
                x0=np.ones(n) / n,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints_with_return,
                options={"ftol": 1e-9, "maxiter": 500},
            )
            if result.success:
                vol = float(np.sqrt(np.dot(result.x.T, np.dot(cov, result.x))))
                sharpe = (target - self.risk_free_rate) / vol if vol > 0 else 0.0
                row = {"return": round(target * 100, 3),
                       "volatility": round(vol * 100, 3),
                       "sharpe": round(sharpe, 4)}
                for i, s in enumerate(self.symbols):
                    row[f"w_{s}"] = round(float(result.x[i]) * 100, 2)
                frontier.append(row)

        return pd.DataFrame(frontier)

    def optimal_weights(self, method: str = "max_sharpe") -> pd.Series:
        """최적 비중 계산 (max_sharpe 또는 min_volatility)."""
        try:
            from scipy.optimize import minimize
        except ImportError:
            return self.weights

        n = len(self.symbols)
        cov = self.returns.cov().values * self.trading_days
        mean_returns = self.returns.mean().values * self.trading_days

        bounds = ((0.0, 1.0),) * n
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        if method == "max_sharpe":
            def neg_sharpe(w):
                ret = np.dot(w, mean_returns)
                vol = np.sqrt(np.dot(w.T, np.dot(cov, w)))
                return -(ret - self.risk_free_rate) / (vol + 1e-9)
            obj = neg_sharpe
        else:
            def min_vol(w):
                return np.sqrt(np.dot(w.T, np.dot(cov, w)))
            obj = min_vol

        result = minimize(
            obj, x0=np.ones(n) / n,
            method="SLSQP", bounds=bounds, constraints=constraints,
        )
        if result.success:
            return pd.Series(result.x, index=self.symbols)
        return self.weights


# ═══════════════════════════════════════════════════════════════════════════════
# Portfolio Rebalancer — KIS 원본 그대로
# ═══════════════════════════════════════════════════════════════════════════════

class PortfolioRebalancer:
    """
    리밸런싱 시뮬레이터 — KIS 원본 로직 그대로.

    리밸런싱 포트폴리오 vs Buy & Hold 비교.
    """

    def __init__(
        self,
        returns: pd.DataFrame,
        target_weights: dict[str, float],
        initial_capital: float = 100_000_000,
        commission_rate: float = 0.0015,
    ):
        self.returns = returns.dropna()
        self.symbols = list(returns.columns)
        w = pd.Series(target_weights).reindex(self.symbols).fillna(0)
        self.target_weights = w / w.sum()
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate

    def simulate(
        self,
        frequency: str = "monthly",
    ) -> RebalanceResult:
        """주기적 리밸런싱 시뮬레이션 — KIS 원본과 동일 로직."""
        freq_map = {"monthly": "ME", "quarterly": "QE", "annually": "YE"}
        resample_freq = freq_map.get(frequency, "ME")

        w = self.target_weights.reindex(self.symbols).fillna(0).values

        portfolio_value = float(self.initial_capital)
        current_holdings = w * portfolio_value

        rebalance_dates = []
        turnover_total = 0.0
        commission_total = 0.0

        # 리밸런싱 날짜 집합
        rebalance_schedule = set(
            self.returns.resample(resample_freq).last().index
        )

        eq_dict: dict = {self.returns.index[0]: portfolio_value}
        bh_holdings = w * float(self.initial_capital)
        bh_dict: dict = {self.returns.index[0]: float(self.initial_capital)}

        for dt, row in self.returns.iterrows():
            rets = row.reindex(self.symbols).fillna(0).values

            # 리밸런싱 포트폴리오
            current_holdings = current_holdings * (1 + rets)
            portfolio_value = float(current_holdings.sum())

            if dt in rebalance_schedule:
                target_holdings = w * portfolio_value
                diff = np.abs(target_holdings - current_holdings)
                commission = float(diff.sum()) * self.commission_rate
                turnover_total += float(diff.sum()) / (portfolio_value + 1e-9)
                commission_total += commission
                portfolio_value -= commission
                current_holdings = w * portfolio_value
                rebalance_dates.append(dt)

            eq_dict[dt] = portfolio_value

            # Buy & Hold
            bh_holdings = bh_holdings * (1 + rets)
            bh_dict[dt] = float(bh_holdings.sum())

        equity_curve = pd.Series(eq_dict, dtype=float)
        bh_curve = pd.Series(bh_dict, dtype=float)

        final_ret = (equity_curve.iloc[-1] / self.initial_capital) - 1
        bh_ret = (bh_curve.iloc[-1] / self.initial_capital) - 1

        return RebalanceResult(
            equity_curve=equity_curve,
            no_rebalance_curve=bh_curve,
            final_return=float(final_ret),
            no_rebalance_return=float(bh_ret),
            rebalance_benefit=float(final_ret - bh_ret),
            rebalance_dates=rebalance_dates,
            rebalance_count=len(rebalance_dates),
            turnover=float(turnover_total),
            transaction_cost=float(commission_total),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Public Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_portfolio(
    tickers: list[str],
    start_date: str,
    end_date: str,
    weights: dict[str, float] | None = None,
    compute_frontier: bool = True,
    compute_optimal: bool = True,
    n_frontier_points: int = 30,
) -> dict:
    """
    메인 포트폴리오 분석 함수 — API 엔드포인트에서 직접 호출.

    Returns:
        to_api_dict() 형식의 직렬화된 결과
    """
    returns = load_returns(tickers, start_date, end_date)
    if returns.empty:
        return {"error": "No data found for given tickers/range"}

    # 데이터 있는 종목만
    available = [t for t in tickers if t in returns.columns]
    returns = returns[available].dropna()
    if len(returns) < 30:
        return {"error": f"Insufficient data: {len(returns)} days (need >=30)"}

    analyzer = PortfolioAnalyzer(returns=returns, weights=weights)
    metrics = analyzer.analyze()

    if compute_frontier and len(available) >= 2:
        try:
            ef = analyzer.efficient_frontier(n_points=n_frontier_points)
            metrics.efficient_frontier = ef if not ef.empty else None
        except Exception as e:
            logger.warning(f"Efficient frontier failed: {e}")

    if compute_optimal and len(available) >= 2:
        try:
            ow = analyzer.optimal_weights("max_sharpe")
            metrics.optimal_weights = ow
        except Exception as e:
            logger.warning(f"Optimal weights failed: {e}")

    return metrics.to_api_dict()


def simulate_rebalancing(
    tickers: list[str],
    start_date: str,
    end_date: str,
    weights: dict[str, float] | None = None,
    frequency: str = "monthly",
    initial_capital: float = 100_000_000,
    commission_rate: float = 0.0015,
) -> dict:
    """리밸런싱 시뮬레이션 — API 엔드포인트에서 직접 호출."""
    returns = load_returns(tickers, start_date, end_date)
    if returns.empty:
        return {"error": "No data found"}

    available = [t for t in tickers if t in returns.columns]
    returns = returns[available].dropna()
    if len(returns) < 30:
        return {"error": "Insufficient data"}

    n = len(available)
    target_w = weights or {t: 1 / n for t in available}

    rebalancer = PortfolioRebalancer(
        returns=returns,
        target_weights=target_w,
        initial_capital=initial_capital,
        commission_rate=commission_rate,
    )
    result = rebalancer.simulate(frequency=frequency)
    return result.to_api_dict()
