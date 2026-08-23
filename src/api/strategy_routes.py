"""전략 빌드·백테스트·최적화·파일 입출력 — main_api.py에서 분리(경로·동작 불변).
"""

import logging
from datetime import date

import pandas as pd
from fastapi import APIRouter, HTTPException

from src.api.legacy_schemas import (
    DSLBacktestRequest,
    DSLValidateRequest,
    GridSearchRequest,
    ImportAndBacktestRequest,
    KISBacktestRequest,
    KISBatchSignalRequest,
    KISSignalRequest,
    MultiConditionRequest,
    OptimizeRequest,
    PITBacktestRequest,
    PortfolioBacktestRequest,
    StrategyBuildRequest,
    StrategyRequest,
    VaRRequest,
    YamlImportRequest,
    YamlValidateRequest,
)
from src.data_loader import MarketDataLoader
from src.models.backtest import VaRBacktester
from src.models.parametric import ParametricRiskModel
from src.models.pit_backtest import PITBacktester
from src.models.signal_engine import (
    CONDITION_REGISTRY,
    multi_condition_backtest,
)
from src.models.strategy_builder import (
    STRATEGY_REGISTRY,
    compute_performance_metrics,
    compute_trade_metrics,
    grid_search,
    portfolio_backtest,
)

logger = logging.getLogger("api.strategy")
router = APIRouter(tags=["strategy"])


@router.post("/strategy-backtest")
def strategy_backtest(req: StrategyRequest):
    """Run a single strategy backtest with full performance metrics."""
    try:
        strategy_fn = STRATEGY_REGISTRY.get(req.strategy)
        if not strategy_fn:
            raise HTTPException(400, f"Unknown strategy: {req.strategy}. "
                                f"Available: {list(STRATEGY_REGISTRY.keys())}")

        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        prices = loader.fetch_prices()

        if len(prices) < 60:
            raise HTTPException(400, "Need at least 60 trading days of data")

        # Run strategy
        params = {**req.params, "commission": req.commission, "slippage": req.slippage}
        result = strategy_fn(prices, **params)

        # Compute metrics
        perf = compute_performance_metrics(
            result["equity_curve"],
            result["returns"],
            benchmark_returns=result["benchmark_returns"],
        )
        trade_stats = compute_trade_metrics(result["trades"])

        # Serialize equity curve
        eq = result["equity_curve"] * req.initial_capital
        dates = eq.index.strftime("%Y-%m-%d").tolist() if hasattr(eq.index, "strftime") \
            else list(range(len(eq)))

        # Benchmark equity
        bench_eq = ((1 + result["benchmark_returns"]).cumprod() * req.initial_capital)

        # Drawdown series
        rolling_max = eq.cummax()
        drawdown = ((eq - rolling_max) / rolling_max * 100)

        return {
            "ticker": req.ticker,
            "strategy": req.strategy,
            "params": result.get("params", {}),
            "performance": perf,
            "trades": trade_stats,
            "trade_list": result["trades"][:100],  # limit to 100 trades
            "equity_curve": {
                "dates": dates,
                "strategy": [round(float(v), 0) for v in eq.values],
                "benchmark": [round(float(v), 0) for v in bench_eq.values],
                "drawdown_pct": [round(float(v), 2) for v in drawdown.values],
            },
            "initial_capital": req.initial_capital,
            "n_days": len(prices),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/api/v1/strategies/build")
def kis_build_strategy(req: StrategyBuildRequest):
    """
    BuilderState → StrategySchema 변환.

    프론트엔드의 비주얼 빌더 상태를 SSoT StrategySchema로 변환합니다.
    응답에 YAML 문자열과 Python 미리보기 코드도 함께 반환합니다.
    """
    try:
        from src.kis_converters import from_dict
        from src.kis_yaml_io import StrategyFileSaver

        # BuilderState를 from_dict가 이해하는 형식으로 변환
        schema = from_dict(req.builder_state)

        # YAML 직렬화
        yaml_str = StrategyFileSaver.to_yaml_string(schema)

        return {
            "schema": schema.model_dump(),
            "yaml": yaml_str,
            "id": schema.id,
            "name": schema.name,
        }
    except Exception as e:
        logger.warning(f"입력 검증 실패: {e}")
        raise HTTPException(400, f"입력 오류: {e}")

@router.post("/api/v1/files/validate")
def kis_validate_yaml(req: YamlValidateRequest):
    """.kis.yaml 문자열 검증."""
    try:
        from src.kis_yaml_io import StrategyFileLoader
        errors = StrategyFileLoader.validate_content(req.content)
        return {"valid": len(errors) == 0, "errors": errors}
    except Exception as e:
        return {"valid": False, "errors": [str(e)]}

@router.post("/api/v1/files/import")
def kis_import_yaml(req: YamlImportRequest):
    """
    .kis.yaml 문자열 → StrategySchema.

    YAML을 파싱하여 SSoT 스키마로 변환 + YAML/Python 미리보기 반환.
    """
    try:
        from src.kis_yaml_io import StrategyFileLoader, StrategyFileSaver

        # 먼저 검증
        errors = StrategyFileLoader.validate_content(req.content)
        if errors:
            raise HTTPException(400, f"Invalid YAML: {'; '.join(errors)}")

        schema = StrategyFileLoader.load_schema_with_params(
            req.content, param_overrides=req.param_overrides or None
        )
        yaml_str = StrategyFileSaver.to_yaml_string(schema)

        return {
            "schema": schema.model_dump(),
            "yaml": yaml_str,
            "id": schema.id,
            "name": schema.name,
            "category": schema.category,
            "num_indicators": len(schema.indicators),
            "has_risk": schema.risk is not None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"입력 검증 실패: {e}")
        raise HTTPException(400, f"입력 오류: {e}")

@router.post("/api/v1/files/export")
def kis_export_yaml(req: StrategyBuildRequest):
    """
    BuilderState → .kis.yaml 문자열 다운로드.

    프론트엔드에서 Export 버튼 클릭 시 호출.
    """
    try:
        from src.kis_converters import from_dict
        from src.kis_yaml_io import StrategyFileSaver

        schema = from_dict(req.builder_state)
        yaml_str = StrategyFileSaver.to_yaml_string(schema)

        return {
            "filename": f"{schema.id}.kis.yaml",
            "content": yaml_str,
            "size": len(yaml_str.encode()),
        }
    except Exception as e:
        logger.warning(f"입력 검증 실패: {e}")
        raise HTTPException(400, f"입력 오류: {e}")

@router.get("/api/v1/strategies/templates")
def kis_list_templates():
    """10개 프리셋 전략의 .kis.yaml 템플릿 반환."""
    from src.kis_strategies.strategies import STRATEGY_REGISTRY, list_strategies
    from src.kis_yaml_io import StrategyFileSaver

    templates = []
    for strat_info in list_strategies():
        name = strat_info["name"]
        cls = STRATEGY_REGISTRY.get(name)
        if cls is None:
            continue
        try:
            instance = cls()
            yaml_str = StrategyFileSaver.to_yaml_string(_strategy_instance_to_schema(instance))
            templates.append({
                "id": strat_info["class"],
                "name": name,
                "required_days": strat_info["required_days"],
                "yaml": yaml_str,
            })
        except Exception:
            continue

    return {"templates": templates}

def _strategy_instance_to_schema(instance):
    """Strategy 인스턴스 → StrategySchema (간단한 변환)."""
    from src.kis_schema import (
        ConditionSchema,
        OperatorType,
        StrategySchema,
    )
    return StrategySchema(
        id=instance.__class__.__name__.lower().replace("strategy", ""),
        name=instance.name,
        category="custom",
        description=str(instance),
        indicators=[],
        entry=ConditionSchema(
            operator=OperatorType.GREATER_THAN, indicator="close", value=0
        ),
        exit=ConditionSchema(
            operator=OperatorType.LESS_THAN, indicator="close", value=99999999
        ),
    )

@router.post("/api/v1/strategies/import-and-backtest")
def kis_import_and_backtest(req: ImportAndBacktestRequest):
    """
    .kis.yaml Import → 즉시 백테스트 실행.

    Strategy Builder Export → Backtester의 완전한 워크플로우를 단일 API로 지원.
    """
    from src.kis_strategies.strategies import get_strategy
    from src.kis_yaml_io import StrategyFileLoader

    try:
        schema = StrategyFileLoader.load_schema_with_params(
            req.yaml_content, req.param_overrides or None
        )
    except Exception as e:
        raise HTTPException(400, f"Invalid YAML: {e}")

    end = req.end_date or str(date.today())
    strategy = get_strategy(schema.name) or get_strategy(schema.id)

    if strategy is None:
        raise HTTPException(400, f"Strategy '{schema.name}' not found. Use /api/v1/strategies/dsl/backtest for DSL.")

    try:
        from src.kis_backtest_engine import run_backtest
        return run_backtest(
            symbols=req.symbols,
            strategy_name=schema.name,
            start_date=req.start_date,
            end_date=end,
            initial_capital=req.initial_capital,
        )
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")

@router.post("/api/v1/strategies/backtest")
def kis_run_backtest(req: KISBacktestRequest):
    """
    KIS 전략 기반 순수 Python 백테스트.
    DB의 daily_prices에서 OHLCV를 읽어 날짜별 시뮬레이션을 수행합니다.
    Lean/Docker 의존성 없이 동작합니다.
    """
    try:
        from src.kis_backtest_engine import run_backtest
        return run_backtest(
            symbols=req.symbols,
            strategy_name=req.strategy,
            start_date=req.start_date,
            end_date=req.end_date,
            strategy_params=req.params,
            initial_capital=req.initial_capital,
            commission_rate=req.commission_rate,
            slippage_rate=req.slippage_rate,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
            max_positions=req.max_positions,
        )
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")

@router.post("/api/v1/strategies/optimize")
def kis_optimize(req: OptimizeRequest):
    """
    Grid Search 파라미터 최적화.
    param_ranges의 조합으로 백테스트를 순차 실행하고 Sharpe 최고값을 반환.
    최대 max_combinations 조합으로 제한.
    """
    try:
        import itertools

        from src.kis_backtest_engine import run_backtest

        # Build grid
        param_names = list(req.param_ranges.keys())
        param_values = []
        for _name, rng in req.param_ranges.items():
            mn, mx, step = rng["min"], rng["max"], rng.get("step", 1)
            vals = []
            v = float(mn)
            while v <= float(mx) + 1e-9:
                vals.append(round(v, 6))
                v += float(step)
            param_values.append(vals)

        all_combos = list(itertools.product(*param_values))
        if len(all_combos) > req.max_combinations:
            import random
            random.seed(42)
            all_combos = random.sample(all_combos, req.max_combinations)

        grid_results = []
        best = {"sharpe": -999, "params": {}, "return": 0, "drawdown": 0, "trades": 0}

        for combo in all_combos:
            params = dict(zip(param_names, combo))
            try:
                r = run_backtest(
                    symbols=req.symbols,
                    strategy_name=req.strategy,
                    start_date=req.start_date,
                    end_date=req.end_date,
                    strategy_params=params,
                    initial_capital=req.initial_capital,
                    commission_rate=req.commission_rate,
                )
                if r.get("error"):
                    continue
                stats = r["result"]["statistics"]
                sharpe = stats.get("sharpe_ratio", 0)
                ret    = stats.get("total_return_pct", 0)
                mdd    = stats.get("max_drawdown_pct", 0)
                trades = stats.get("num_trades", 0)

                grid_results.append({
                    "params": params,
                    "sharpe": round(sharpe, 4),
                    "return_pct": round(ret, 3),
                    "max_drawdown": round(mdd, 3),
                    "num_trades": trades,
                })

                if sharpe > best["sharpe"]:
                    best = {"sharpe": sharpe, "params": params,
                            "return": ret, "drawdown": mdd, "trades": trades}
            except Exception:
                continue

        return {
            "best_params":    best["params"],
            "best_sharpe":    round(best["sharpe"], 4),
            "best_return":    round(best["return"], 3),
            "best_drawdown":  round(best["drawdown"], 3),
            "total_tested":   len(grid_results),
            "grid":           grid_results,
        }
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")

@router.post("/api/v1/strategies/signal")
def kis_generate_signal(req: KISSignalRequest):
    """
    단일 종목에 대해 KIS 전략 시그널 생성.

    data_fetcher가 DB의 daily_prices를 읽으므로
    KIS API를 직접 호출하지 않습니다.
    """
    try:
        from src.kis_strategies.strategies import get_strategy
        strategy = get_strategy(req.strategy, **req.params)
        if strategy is None:
            raise HTTPException(400, f"Unknown strategy: {req.strategy}")

        signal = strategy.generate_signal(
            req.stock_code,
            req.stock_name or req.stock_code,
        )
        return {
            "stock_code": signal.stock_code,
            "stock_name": signal.stock_name,
            "action": signal.action.value,
            "strength": signal.strength,
            "reason": signal.reason,
            "is_actionable": signal.is_actionable(),
            "is_strong": signal.is_strong(),
            "strategy": strategy.name,
            "timestamp": signal.timestamp.isoformat(),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")

@router.post("/api/v1/strategies/batch-signal")
def kis_batch_signal(req: KISBatchSignalRequest):
    """
    여러 종목에 대해 시그널을 일괄 생성.
    BUY/SELL 시그널만 걸러서 반환합니다.
    """
    try:
        from src.kis_signal import Action
        from src.kis_strategies.strategies import get_strategy

        strategy = get_strategy(req.strategy, **req.params)
        if strategy is None:
            raise HTTPException(400, f"Unknown strategy: {req.strategy}")

        results = []
        for stock in req.stocks:
            code = stock.get("code", stock.get("ticker", ""))
            name = stock.get("name", code)
            if not code:
                continue
            try:
                signal = strategy.generate_signal(code, name)
                if signal.action != Action.HOLD:
                    results.append({
                        "stock_code": signal.stock_code,
                        "stock_name": signal.stock_name,
                        "action": signal.action.value,
                        "strength": signal.strength,
                        "reason": signal.reason,
                    })
            except Exception:
                continue

        # 강도 내림차순 정렬
        results.sort(key=lambda x: x["strength"], reverse=True)
        return {
            "strategy": strategy.name,
            "total_scanned": len(req.stocks),
            "signals": results,
            "buy_count": sum(1 for r in results if r["action"] == "buy"),
            "sell_count": sum(1 for r in results if r["action"] == "sell"),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")

@router.get("/api/v1/strategies/list")
def kis_list_strategies():
    """등록된 KIS 전략 목록과 파라미터 정보 반환."""
    from src.kis_strategies.strategies import list_strategies
    return {"strategies": list_strategies()}

@router.post("/api/v1/strategies/dsl/validate")
def dsl_validate(req: DSLValidateRequest):
    """DSL 수식 실시간 유효성 검사."""
    from src.kis_dsl_executor import parse_and_validate
    valid, msg = parse_and_validate(req.expression)
    return {"valid": valid, "message": msg}

@router.post("/api/v1/strategies/dsl/backtest")
def dsl_backtest(req: DSLBacktestRequest):
    """
    사용자 정의 DSL 수식으로 백테스트 실행.

    Example buy_condition: "ma(5) crosses_above ma(20)"
    Example sell_condition: "ma(5) crosses_below ma(20)"
    """
    try:
        from src.kis_backtest_engine import BacktestConfig, BacktestEngine
        from src.kis_dsl_executor import dsl_to_strategy

        strategy = dsl_to_strategy(req.name, req.buy_condition, req.sell_condition)

        # BacktestEngine에 DSL 전략 주입
        cfg = BacktestConfig(
            symbols=req.symbols,
            strategy_name="__dsl__",
            strategy_params={},
            start_date=req.start_date,
            end_date=req.end_date,
            initial_capital=req.initial_capital,
            commission_rate=req.commission_rate,
            slippage_rate=req.slippage_rate,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
            max_positions=req.max_positions,
        )
        engine = BacktestEngine(cfg)

        # strategy_name을 무시하고 주입된 strategy 객체 사용
        from datetime import datetime as _dt
        from datetime import timedelta

        import pandas as pd

        from src.kis_backtest_engine import load_ohlcv

        warmup_start = (
            _dt.strptime(req.start_date, "%Y-%m-%d")
            - timedelta(days=strategy.required_days + 30)
        ).strftime("%Y-%m-%d")

        ohlcv_map = {}
        for ticker in req.symbols:
            df = load_ohlcv(ticker, warmup_start, req.end_date)
            if not df.empty:
                ohlcv_map[ticker] = df

        if not ohlcv_map:
            raise HTTPException(400, "No OHLCV data found in DB")

        ref_ticker = max(ohlcv_map, key=lambda t: len(ohlcv_map[t]))
        all_dates = ohlcv_map[ref_ticker].index
        sim_dates = all_dates[all_dates >= pd.Timestamp(req.start_date)]

        from src.kis_signal import Action
        for sim_date in sim_dates:
            date_str = sim_date.strftime("%Y-%m-%d")
            for ticker, pos in list(engine.positions.items()):
                if ticker in ohlcv_map:
                    df_to = ohlcv_map[ticker].loc[:sim_date]
                    if not df_to.empty:
                        engine._check_risk_triggers(
                            ticker, pos, float(df_to["close"].iloc[-1]), date_str
                        )
            for ticker in req.symbols:
                if ticker not in ohlcv_map:
                    continue
                df_slice = ohlcv_map[ticker].loc[:sim_date]
                if len(df_slice) < strategy.required_days:
                    continue
                signal = engine._generate_signal_as_of(strategy, ticker, df_slice)
                if signal is None:
                    continue
                curr_price = float(df_slice["close"].iloc[-1])
                if signal.action == Action.BUY and signal.is_actionable():
                    engine._execute_buy(ticker, curr_price, date_str, signal.reason)
                elif signal.action == Action.SELL and signal.is_actionable():
                    engine._execute_sell(ticker, curr_price, date_str, signal.reason)
            equity = engine._calc_equity(ohlcv_map, sim_date)
            engine.equity_history.append((date_str, equity))

        return engine._build_result(0.0, ohlcv_map)

    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")

@router.post("/strategy-optimize")
def strategy_optimize(req: GridSearchRequest):
    """Grid search parameter optimization for a strategy."""
    try:
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        prices = loader.fetch_prices()

        if len(prices) < 60:
            raise HTTPException(400, "Need at least 60 trading days of data")

        # Convert param_grid values to proper types
        param_grid = {}
        for k, v in req.param_grid.items():
            if isinstance(v, list):
                param_grid[k] = [int(x) if isinstance(x, float) and x == int(x) else x
                                  for x in v]
            else:
                param_grid[k] = v

        result = grid_search(
            prices, req.strategy, param_grid,
            commission=req.commission, slippage=req.slippage,
            metric=req.metric,
        )

        if "error" in result:
            raise HTTPException(400, result["error"])

        # Don't return the full equity curve from grid search
        if result.get("best_result"):
            del result["best_result"]

        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/portfolio-backtest")
def run_portfolio_backtest(req: PortfolioBacktestRequest):
    """Multi-asset portfolio backtest with rebalancing."""
    try:
        if len(req.tickers) != len(req.weights):
            raise HTTPException(400, "Tickers and weights must have same length")
        if len(req.tickers) < 2:
            raise HTTPException(400, "Need at least 2 tickers")

        # Fetch prices for each ticker
        price_dict = {}
        for ticker in req.tickers:
            loader = MarketDataLoader(ticker, req.start_date, req.end_date)
            price_dict[ticker] = loader.fetch_prices()

        weights = dict(zip(req.tickers, req.weights))

        result = portfolio_backtest(
            price_dict, weights,
            rebalance_freq=req.rebalance_freq,
            commission=req.commission,
        )

        if "error" in result:
            raise HTTPException(400, result["error"])

        # Scale equity curve by initial capital
        eq = result["equity_curve"]
        eq["portfolio"] = [round(v * req.initial_capital, 0) for v in eq["portfolio"]]
        eq["benchmark"] = [round(v * req.initial_capital, 0) for v in eq["benchmark"]]

        result["initial_capital"] = req.initial_capital
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/multi-condition-backtest")
def run_multi_condition(req: MultiConditionRequest):
    """Multi-condition strategy backtest with advanced exit logic."""
    try:
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        prices = loader.fetch_prices()
        if len(prices) < 60:
            raise HTTPException(400, "Need at least 60 days of data")

        result = multi_condition_backtest(
            prices,
            entry_conditions=req.entry_conditions,
            entry_logic=req.entry_logic,
            exit_conditions=req.exit_conditions or None,
            exit_logic=req.exit_logic,
            trailing_stop_pct=req.trailing_stop_pct or None,
            take_profit_pct=req.take_profit_pct or None,
            stop_loss_pct=req.stop_loss_pct or None,
            time_exit_days=req.time_exit_days or None,
            commission=req.commission,
            slippage=req.slippage,
        )

        perf = compute_performance_metrics(
            result["equity_curve"], result["returns"],
            benchmark_returns=result["benchmark_returns"],
        )
        trade_stats = compute_trade_metrics(result["trades"])

        eq = result["equity_curve"] * req.initial_capital
        bench_eq = (1 + result["benchmark_returns"]).cumprod() * req.initial_capital
        rolling_max = eq.cummax()
        dd = ((eq - rolling_max) / rolling_max * 100)

        dates = eq.index.strftime("%Y-%m-%d").tolist() \
            if hasattr(eq.index, "strftime") else list(range(len(eq)))

        return {
            "ticker": req.ticker,
            "performance": perf,
            "trades": trade_stats,
            "trade_list": result["trades"][:100],
            "equity_curve": {
                "dates": dates,
                "strategy": [round(float(v), 0) for v in eq.values],
                "benchmark": [round(float(v), 0) for v in bench_eq.values],
                "drawdown_pct": [round(float(v), 2) for v in dd.values],
            },
            "entry_conditions": result["entry_conditions"],
            "exit_params": result["exit_params"],
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.get("/condition-registry")
def get_condition_registry():
    """Return available conditions with descriptions and recommended tickers."""
    return CONDITION_REGISTRY

@router.post("/backtest-var")
def backtest_var(req: VaRRequest):
    try:
        loader  = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        returns = loader.fetch_returns()

        model   = ParametricRiskModel(req.confidence_level, req.use_ewma)
        var_pct = model.calculate_var(returns)
        var_amt = var_pct * req.portfolio_value

        actual_pnl = returns * req.portfolio_value
        var_series = pd.Series(var_amt, index=returns.index)

        backtester = VaRBacktester(req.confidence_level)
        result     = backtester.run_kupiec_test(actual_pnl, var_series)
        basel      = backtester.basel_zone(result["exceptions"])
        christo    = backtester.christoffersen_test(actual_pnl, var_series)

        exceptions_dates = returns.index[result["exception_series"]].strftime("%Y-%m-%d").tolist()

        return {
            "kupiec":           {k: v for k, v in result.items() if k != "exception_series"},
            "basel":            basel,
            "christoffersen":   christo,
            "exception_dates":  exceptions_dates,
            "pnl_series":       actual_pnl.round(0).tolist(),
            "var_line":         (-var_series).tolist(),
            "dates":            returns.index.strftime("%Y-%m-%d").tolist(),
        }
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/backtest-pit")
def backtest_pit(req: PITBacktestRequest):
    """
    PIT-based VaR backtest: validates the ENTIRE forecasted distribution.

    Tests performed:
      - Kolmogorov-Smirnov (KS):  max CDF deviation from U[0,1]
      - Anderson-Darling (AD):    tail-weighted GoF (risk manager's choice)
      - Cramér-von Mises (CvM):   mean squared CDF deviation
      - Berkowitz Independence:    AR(1) serial correlation in PIT → N(0,1)

    Returns test results, QQ plot data, and PIT histogram for visualization.
    """
    try:
        loader  = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        returns = loader.fetch_returns()

        pit_tester = PITBacktester(req.confidence_level)
        result = pit_tester.run_full_pit_backtest(
            returns,
            window=req.rolling_window,
            use_ewma=req.use_ewma,
            ewma_lambda=req.ewma_lambda,
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/api/v1/backtest/graph")
def graph_backtest(req: dict):
    """
    React Flow 캔버스의 노드/엣지 JSON을 받아 DAG 백테스트 실행.
    Pipeline: DAG구축 → 순환검증 → 위상정렬 → 팩토리실행 → 벡터화백테스트
    """
    try:
        from src.engine.dag_runner import execute_dag_backtest
        from src.models.graph_schema import GraphBacktestRequest

        parsed_req = GraphBacktestRequest(**req)
        result = execute_dag_backtest(parsed_req)
        return result.model_dump()
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
