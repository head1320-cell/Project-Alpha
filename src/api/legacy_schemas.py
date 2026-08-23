"""main_api.py에 있던 요청/응답 Pydantic 모델 모음 (레거시 엔드포인트용).

도메인별로 쪼개지 않고 한 파일에 둔다 — VaRRequest처럼 여러 도메인 라우터가
공유하는 모델이 있어, 분할하면 라우터 간 상호 import가 생긴다.
"""

from datetime import date

from pydantic import BaseModel


class VaRRequest(BaseModel):
    ticker: str
    portfolio_value: float
    confidence_level: float = 0.99
    holding_period: int = 1
    use_ewma: bool = True
    start_date: str = "2023-01-01"
    end_date: str = str(date.today())

class PortfolioVaRRequest(BaseModel):
    tickers: list[str]
    weights: list[float]
    portfolio_value: float
    confidence_level: float = 0.99
    use_ewma: bool = True
    start_date: str = "2023-01-01"
    end_date: str = str(date.today())

class StressRequest(BaseModel):
    equity_value: float
    bond_value: float = 0.0
    fx_value: float = 0.0
    portfolio_beta: float = 1.2
    modified_duration: float = 7.0

class OptionRequest(BaseModel):
    S: float; K: float; T: float; r: float; sigma: float
    option_type: str = "call"

class BondRequest(BaseModel):
    face_value: float
    coupon_rate: float
    ytm: float
    years_to_maturity: int
    freq: int = 2

class HedgeRequest(BaseModel):
    portfolio_value: float
    current_beta: float
    target_beta: float = 0.0
    futures_price: float
    multiplier: int = 250000

class AggregateVaRRequest(BaseModel):
    individual_vars: list[float]
    correlation_matrix: list[list[float]]

class AutoTradingConfig(BaseModel):
    auto_mode: bool
    var_limit: float
    username: str = "admin"

class MCVaRRequest(BaseModel):
    ticker: str
    portfolio_value: float
    confidence_level: float = 0.99
    holding_period: int = 1
    n_simulations: int = 10000
    use_ewma: bool = True
    ewma_lambda: float = 0.94
    start_date: str = "2023-01-01"
    end_date: str = str(date.today())

class MCPortfolioVaRRequest(BaseModel):
    tickers: list[str]
    weights: list[float]
    portfolio_value: float
    confidence_level: float = 0.99
    holding_period: int = 1
    n_simulations: int = 10000
    use_ewma: bool = True
    ewma_lambda: float = 0.94
    start_date: str = "2023-01-01"
    end_date: str = str(date.today())

class GARCHRequest(BaseModel):
    ticker: str
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())
    ewma_lambda: float = 0.94

class FRTBRequest(BaseModel):
    ticker: str
    portfolio_value: float
    risk_factor_type: str = "large_cap_equity"
    start_date: str = "2018-01-01"
    end_date: str = str(date.today())

class CVARequest(BaseModel):
    notional: float
    maturity_years: float = 5.0
    cds_spread_bps: float = 150.0
    recovery_rate: float = 0.40
    risk_free_rate: float = 0.03
    position_type: str = "irs"
    volatility: float = 0.02
    bank_cds_spread_bps: float = 50.0
    bank_recovery: float = 0.40
    spread_shock_bps: float = 100.0
    cds_1y: float = 0.0
    cds_3y: float = 0.0
    cds_5y: float = 0.0
    cds_10y: float = 0.0

class IRCPositionInput(BaseModel):
    name: str
    rating: str = "BBB"
    notional: float = 1_000_000_000
    modified_duration: float = 5.0
    recovery_rate: float = 0.40
    liquidity_horizon_months: int = 3

class IRCRequest(BaseModel):
    positions: list[IRCPositionInput]
    n_simulations: int = 50000

class DCCRequest(BaseModel):
    tickers: list[str]
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())

class BondInput(BaseModel):
    name: str
    face_value: float
    coupon_rate: float
    maturity_years: int
    ytm: float = 0.0

class VaRMappingRequest(BaseModel):
    bonds: list[BondInput]
    zero_var_pct: dict[str, float]   # JSON keys must be strings
    spot_rates: dict[str, float] = {}

class AICompareRequest(BaseModel):
    ticker: str
    window: int = 20
    lstm_epochs: int = 30
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())

class LSTMForecastRequest(BaseModel):
    ticker: str
    n_steps: int = 5
    window: int = 20
    epochs: int = 30
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())

class MultiFeatureRequest(BaseModel):
    ticker: str
    model_type: str = "random_forest"   # or "gradient_boosting"
    vol_window: int = 20
    use_vix: bool = True
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())

class MonitorRequest(BaseModel):
    ticker: str
    vol_window: int = 20
    initial_train_ratio: float = 0.6
    refit_every: int = 20
    use_vix: bool = True
    start_date: str = "2021-01-01"
    end_date: str = str(date.today())

class StrategyRequest(BaseModel):
    ticker: str
    strategy: str = "SMA Crossover"
    params: dict = {}
    commission: float = 0.001
    slippage: float = 0.0005
    initial_capital: float = 100000000
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())

class StrategyBuildRequest(BaseModel):
    """전략 빌드 요청 — builder_state JSON → StrategySchema"""
    builder_state: dict             # 프론트엔드 BuilderState
    param_overrides: dict = {}      # 파라미터 오버라이드

class YamlImportRequest(BaseModel):
    content: str                    # .kis.yaml 문자열
    param_overrides: dict = {}

class YamlValidateRequest(BaseModel):
    content: str

class PresetsRequest(BaseModel):
    strategy_id: str
    param_overrides: dict = {}

class ImportAndBacktestRequest(BaseModel):
    yaml_content: str
    symbols: list = ["005930"]
    start_date: str = "2022-01-01"
    end_date: str | None = None
    initial_capital: float = 100_000_000
    param_overrides: dict = {}

class KISBacktestRequest(BaseModel):
    symbols: list[str]
    strategy: str
    params: dict = {}
    start_date: str = "2022-01-01"
    end_date: str = str(date.today())
    initial_capital: float = 100_000_000
    commission_rate: float = 0.0015
    slippage_rate: float = 0.0005
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_positions: int = 5

class OptimizeRequest(BaseModel):
    symbols: list[str]
    strategy: str
    param_ranges: dict   # {"short_period": {"min":2,"max":20,"step":1}, ...}
    start_date: str = "2022-01-01"
    end_date: str = str(date.today())
    initial_capital: float = 100_000_000
    commission_rate: float = 0.0015
    max_combinations: int = 200   # safety cap

class KISSignalRequest(BaseModel):
    stock_code: str           # 종목코드 (6자리)
    stock_name: str = ""
    strategy: str             # 전략명 (STRATEGY_REGISTRY 키)
    params: dict = {}         # 전략 파라미터 (선택)

class KISBatchSignalRequest(BaseModel):
    stocks: list[dict]        # [{"code": "005930", "name": "삼성전자"}, ...]
    strategy: str
    params: dict = {}

class DSLValidateRequest(BaseModel):
    expression: str

class DSLBacktestRequest(BaseModel):
    name: str = "Custom DSL Strategy"
    buy_condition: str
    sell_condition: str = ""
    symbols: list[str]
    start_date: str = "2022-01-01"
    end_date: str = str(date.today())
    initial_capital: float = 100_000_000
    commission_rate: float = 0.0015
    slippage_rate: float = 0.0005
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_positions: int = 5

class PortfolioAnalyzeRequest(BaseModel):
    tickers: list[str]
    start_date: str = "2022-01-01"
    end_date: str = str(date.today())
    weights: dict | None = None
    compute_frontier: bool = True
    compute_optimal: bool = True

class RebalanceRequest(BaseModel):
    tickers: list[str]
    start_date: str = "2022-01-01"
    end_date: str = str(date.today())
    weights: dict | None = None
    frequency: str = "monthly"   # monthly | quarterly | annually
    initial_capital: float = 100_000_000
    commission_rate: float = 0.0015

class GridSearchRequest(BaseModel):
    ticker: str
    strategy: str = "SMA Crossover"
    param_grid: dict = {"fast_period": [10, 20, 30], "slow_period": [40, 50, 60]}
    commission: float = 0.001
    slippage: float = 0.0005
    metric: str = "sharpe_ratio"
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())

class PortfolioBacktestRequest(BaseModel):
    tickers: list[str]
    weights: list[float]
    rebalance_freq: str = "monthly"
    commission: float = 0.001
    initial_capital: float = 100000000
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())

class MultiConditionRequest(BaseModel):
    ticker: str
    entry_conditions: list[dict]
    entry_logic: str = "AND"
    exit_conditions: list[dict] = []
    exit_logic: str = "OR"
    trailing_stop_pct: float = 0
    take_profit_pct: float = 0
    stop_loss_pct: float = 0
    time_exit_days: int = 0
    commission: float = 0.001
    slippage: float = 0.0005
    initial_capital: float = 100000000
    start_date: str = "2015-01-01"
    end_date: str = str(date.today())

class EfficientFrontierRequest(BaseModel):
    tickers: list[str]
    n_portfolios: int = 3000
    risk_free_rate: float = 0.03
    start_date: str = "2015-01-01"
    end_date: str = str(date.today())

class RankingRequest(BaseModel):
    tickers: list[str]
    method: str = "momentum_12m"
    top_n: int = 5
    start_date: str = "2015-01-01"
    end_date: str = str(date.today())

class HoldingPeriodVaRRequest(BaseModel):
    ticker: str
    holding_periods: list[int] = [1, 5, 10, 20]
    confidence_levels: list[float] = [0.95, 0.99]
    portfolio_value: float = 100000000
    method: str = "parametric"
    start_date: str = "2015-01-01"
    end_date: str = str(date.today())

class MCPathRequest(BaseModel):
    ticker: str
    n_paths: int = 500
    n_days: int = 252
    start_date: str = "2015-01-01"
    end_date: str = str(date.today())

class RollingStatsRequest(BaseModel):
    ticker: str
    window: int = 252
    start_date: str = "2015-01-01"
    end_date: str = str(date.today())

class ScreenerRequest(BaseModel):
    universe: str  # "equity" or "ficc"
    conditions: dict  # {"A": {"field": "per", "operator": "<", "value": 15}, ...}
    logic_expression: str
    sort_by: str = None
    limit: int = 100

class PITBacktestRequest(BaseModel):
    ticker: str
    confidence_level: float = 0.99
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())
    use_ewma: bool = True
    ewma_lambda: float = 0.94
    rolling_window: int = 60

class OrderRequest(BaseModel):
    stock_code: str
    stock_name: str = ""
    action: str           # "buy" | "sell"
    quantity: int | None = None
    target_price: float | None = None
    strength: float = 1.0

class BatchOrderRequest(BaseModel):
    orders: list[OrderRequest]
