"""
Multi-Strategy Unified Backtest Engine — Phase A
=================================================
PIT-safe daily simulation loop with 5-Factor Attribution.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Config + Records
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class BacktestConfig:
    strategy_ids:           list[int]
    start_date:             str
    end_date:               str
    initial_capital:        float = 1_000_000
    allocation_method:      str = "hrp_macro"
    rebalance_policy:       str = "monthly"
    netting_enabled:        bool = True
    macro_overlay_enabled:  bool = True
    commission_rate:        float = 0.00015
    slippage_rate:          float = 0.0005
    lookback_days:          int = 252
    max_weight:             float = 0.50
    min_weight:             float = 0.02
    run_name:               str | None = None


@dataclass
class DailyRecord:
    date:               pd.Timestamp
    portfolio_equity:   float
    portfolio_return:   float
    cumulative_return:  float
    drawdown_pct:       float
    regime:             str | None = None
    systemic_risk:      float | None = None
    growth_signal:      float | None = None
    inflation_signal:   float | None = None
    allocation_effect:  float = 0
    selection_effect:   float = 0
    macro_effect:       float = 0
    netting_effect:     float = 0
    cost_effect:        float = 0
    num_trades:         int = 0
    turnover_pct:       float = 0
    netting_savings:    float = 0
    rebalanced:         bool = False
    weights:            dict = field(default_factory=dict)
    base_weights:       dict = field(default_factory=dict)
    macro_adj:          dict = field(default_factory=dict)
    strategy_returns:   dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# MultiStrategyBacktester
# ═══════════════════════════════════════════════════════════════════════════════

class MultiStrategyBacktester:

    def __init__(self, db_engine):
        self.engine = db_engine
        from src.engine.allocator import MultiStrategyAllocator
        from src.engine.strategy_registry import StrategyRegistry
        from src.execution.order_netting import OrderNettingEngine
        self.registry = StrategyRegistry(db_engine)
        self.allocator = MultiStrategyAllocator(db_engine)
        self.netting_engine = OrderNettingEngine(db_engine=None)

    # ─── 메인 진입점 ─────────────────────────────────────────────────────

    def run(self, config: BacktestConfig) -> dict:
        t_start = time.perf_counter()

        validation = self._validate_config(config)
        if not validation["ok"]:
            return {"success": False, "message": validation["error"]}

        try:
            data = self._load_data(config)
        except Exception as e:
            return {"success": False, "message": f"데이터 로드 실패: {e}"}

        if data["returns_matrix"].empty:
            return {"success": False, "message": "Returns 매트릭스 비어있음"}

        try:
            daily_records, errors = self._simulate(config, data)
        except Exception as e:
            logger.error(f"Simulation failed: {e}", exc_info=True)
            return {"success": False, "message": f"시뮬레이션 실패: {e}"}

        if not daily_records:
            return {"success": False, "message": "시뮬레이션 결과 없음"}

        summary = self._compute_summary(daily_records, config)
        duration = time.perf_counter() - t_start

        return {
            "success":             True,
            "config":              config.__dict__,
            "summary":             summary,
            "daily_records":       [self._record_to_dict(r) for r in daily_records],
            "strategy_names":      data["strategy_names"],
            "n_trading_days":      len(daily_records),
            "duration_seconds":    round(duration, 3),
            "warnings":            errors,
        }

    def run_and_save(self, config: BacktestConfig) -> dict:
        result = self.run(config)
        if not result["success"]:
            return result
        run_id = self._persist(config, result)
        result["run_id"] = run_id
        return result

    def load_run(self, run_id: int) -> dict | None:
        with self.engine.connect() as conn:
            run_row = conn.execute(text("SELECT * FROM multibacktest_runs WHERE id = :rid"),
                                    {"rid": run_id}).fetchone()
            if not run_row:
                return None
            daily = conn.execute(text(
                "SELECT * FROM multibacktest_daily WHERE run_id = :rid ORDER BY trade_date"
            ), {"rid": run_id}).fetchall()
            strategy_daily = conn.execute(text(
                "SELECT * FROM multibacktest_strategy_daily WHERE run_id = :rid ORDER BY trade_date, strategy_id"
            ), {"rid": run_id}).fetchall()

        return {
            "run":            dict(run_row._mapping),
            "daily":          [dict(r._mapping) for r in daily],
            "strategy_daily": [dict(r._mapping) for r in strategy_daily],
        }

    def list_runs(self, limit: int = 50) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, run_name, strategy_ids, start_date, end_date,
                       allocation_method, status, total_return_pct,
                       sharpe_ratio, max_drawdown_pct, netting_total_savings,
                       n_trading_days, created_at, duration_seconds
                FROM multibacktest_runs
                ORDER BY created_at DESC LIMIT :n
            """), {"n": limit}).fetchall()
        return [dict(r._mapping) for r in rows]

    def delete_run(self, run_id: int) -> bool:
        try:
            with self.engine.begin() as conn:
                conn.execute(text("DELETE FROM multibacktest_strategy_daily WHERE run_id = :rid"), {"rid": run_id})
                conn.execute(text("DELETE FROM multibacktest_daily WHERE run_id = :rid"), {"rid": run_id})
                conn.execute(text("DELETE FROM multibacktest_runs WHERE id = :rid"), {"rid": run_id})
            return True
        except Exception as e:
            logger.error(f"Delete failed: {e}")
            return False

    # ─── Validation + Data Load ──────────────────────────────────────────

    def _validate_config(self, config: BacktestConfig) -> dict:
        if not config.strategy_ids:
            return {"ok": False, "error": "전략 ID 비어있음"}
        for sid in config.strategy_ids:
            if not self.registry.get(sid):
                return {"ok": False, "error": f"전략 {sid} 미존재"}
        if pd.to_datetime(config.start_date) >= pd.to_datetime(config.end_date):
            return {"ok": False, "error": "start_date >= end_date"}
        if config.allocation_method not in ("inverse_vol", "hrp", "hrp_macro"):
            return {"ok": False, "error": f"알 수 없는 method: {config.allocation_method}"}
        if config.rebalance_policy not in ("daily","weekly","monthly","quarterly","regime_change"):
            return {"ok": False, "error": f"알 수 없는 정책: {config.rebalance_policy}"}
        return {"ok": True}

    def _load_data(self, config: BacktestConfig) -> dict:
        returns_matrix = self.registry.load_returns_matrix(
            strategy_ids=config.strategy_ids,
            start_date=config.start_date, end_date=config.end_date,
            drop_na_rows=True,
        )
        strategies = []
        strategy_names = {}
        for sid in config.strategy_ids:
            s = self.registry.get(sid)
            if s:
                strategies.append(s)
                strategy_names[sid] = s.get("name", f"#{sid}")

        macro_df = pd.DataFrame()
        if config.macro_overlay_enabled and config.allocation_method == "hrp_macro":
            try:
                from src.data.macro_feed import MacroFeedCollector
                start_macro = pd.to_datetime(config.start_date) - timedelta(days=400)
                collector = MacroFeedCollector(self.engine)
                macro_df = collector.build_macro_matrix(start_macro, config.end_date)
            except Exception as e:
                logger.warning(f"Macro data unavailable: {e}")

        return {
            "returns_matrix": returns_matrix,
            "strategies":     strategies,
            "strategy_names": strategy_names,
            "macro_df":       macro_df,
        }

    # ─── 핵심 시뮬레이션 루프 ─────────────────────────────────────────

    def _simulate(self, config, data) -> tuple[list[DailyRecord], list[str]]:
        returns_matrix = data["returns_matrix"]
        strategies = data["strategies"]
        macro_df = data["macro_df"]
        sids = config.strategy_ids

        rebalance_dates = self._compute_rebalance_dates(
            list(returns_matrix.index), config.rebalance_policy,
        )

        equity = config.initial_capital
        max_equity = equity
        n_str = len(sids)
        current_weights = {int(sid): 1.0/n_str for sid in sids}
        current_base_weights = current_weights.copy()
        current_macro_adj = {int(sid): 0.0 for sid in sids}
        current_regime = None

        daily_records = []
        warnings = []
        cumulative_savings = 0.0

        for t, date in enumerate(returns_matrix.index):
            rebalanced_today = False

            # 리밸런싱 트리거
            should_rebal = (
                date in rebalance_dates
                or (config.rebalance_policy == "regime_change" and current_regime is None)
            )

            if should_rebal and t > 0:
                past_returns = returns_matrix.iloc[:t]
                if len(past_returns) >= 20:
                    try:
                        alloc_result = self.allocator.compute(
                            returns_matrix=past_returns,
                            method=config.allocation_method,
                            strategies=strategies,
                            as_of_date=str(date.date()),
                            lookback_days=config.lookback_days,
                            max_weight=config.max_weight,
                            min_weight=config.min_weight,
                        )
                        if alloc_result.get("available"):
                            current_weights = {int(k): float(v) for k, v in alloc_result["weights"].items()}
                            current_base_weights = {int(k): float(v) for k, v in alloc_result.get("base_weights", {}).items()}
                            current_macro_adj = {int(k): float(v) for k, v in alloc_result.get("macro_adjustments", {}).items()}
                            current_regime = alloc_result.get("regime")
                            rebalanced_today = True
                            for sid in sids:
                                if int(sid) not in current_weights:
                                    current_weights[int(sid)] = 0.0
                                    current_base_weights[int(sid)] = 0.0
                                    current_macro_adj[int(sid)] = 0.0
                    except Exception as e:
                        warnings.append(f"{date.date()}: 리밸런싱 실패 {e}")

            # 매크로 정보 (PIT-safe)
            regime_info = None
            if config.macro_overlay_enabled and not macro_df.empty:
                try:
                    from src.engine.regime_model import MultiRegimeModel
                    past_macro = macro_df[macro_df["date"] < date] if "date" in macro_df.columns else pd.DataFrame()
                    if not past_macro.empty:
                        regime_info = MultiRegimeModel.classify_at_date(past_macro, str(date.date()))
                except Exception:
                    pass

            day_returns = returns_matrix.iloc[t].to_dict()
            portfolio_ret = sum(current_weights.get(int(sid), 0) * day_returns.get(sid, 0) for sid in sids)

            # Attribution
            alloc_diff = sum((current_weights.get(int(sid), 0) - 1/n_str) * day_returns.get(sid, 0) for sid in sids)
            macro_effect = sum(current_macro_adj.get(int(sid), 0) * day_returns.get(sid, 0) for sid in sids)

            # Cost + Netting
            turnover = 0.0
            cost_effect = 0.0
            netting_savings = 0.0

            if rebalanced_today and t > 0:
                prev_w = daily_records[-1].weights if daily_records else current_weights
                turnover = sum(abs(current_weights.get(int(sid), 0) - prev_w.get(int(sid), 0)) for sid in sids)
                total_rate = config.commission_rate + config.slippage_rate
                cost_effect = -turnover * total_rate

                if config.netting_enabled:
                    estimated_raw_turnover = turnover * 1.5
                    estimated_savings_pct = (estimated_raw_turnover - turnover) * total_rate
                    netting_savings = estimated_savings_pct * equity
                    cumulative_savings += netting_savings

            net_return = portfolio_ret + cost_effect
            equity_new = equity * (1 + net_return)
            max_equity = max(max_equity, equity_new)
            drawdown = (equity_new / max_equity - 1) * 100
            cum_return = (equity_new / config.initial_capital - 1) * 100

            record = DailyRecord(
                date=date, portfolio_equity=equity_new,
                portfolio_return=net_return,
                cumulative_return=cum_return,
                drawdown_pct=drawdown,
                regime=regime_info.get("regime") if regime_info else current_regime,
                systemic_risk=regime_info.get("systemic_risk_score") if regime_info else None,
                growth_signal=regime_info.get("growth_signal") if regime_info else None,
                inflation_signal=regime_info.get("inflation_signal") if regime_info else None,
                allocation_effect=alloc_diff, selection_effect=0,
                macro_effect=macro_effect,
                netting_effect=netting_savings/equity if equity > 0 else 0,
                cost_effect=cost_effect,
                num_trades=int(round(turnover * len(sids))) if rebalanced_today else 0,
                turnover_pct=turnover * 100,
                netting_savings=netting_savings, rebalanced=rebalanced_today,
                weights=current_weights.copy(),
                base_weights=current_base_weights.copy(),
                macro_adj=current_macro_adj.copy(),
                strategy_returns=day_returns,
            )
            daily_records.append(record)
            equity = equity_new

        return daily_records, warnings

    @staticmethod
    def _compute_rebalance_dates(trading_days, policy) -> set:
        if not trading_days:
            return set()
        if policy == "daily":
            return set(trading_days)
        dates = set([trading_days[0]])
        if policy == "weekly":
            seen = set()
            for d in trading_days:
                wk = (d.year, d.isocalendar().week)
                if wk not in seen:
                    dates.add(d); seen.add(wk)
        elif policy in ("monthly", "regime_change"):
            seen = set()
            for d in trading_days:
                key = (d.year, d.month)
                if key not in seen:
                    dates.add(d); seen.add(key)
        elif policy == "quarterly":
            seen = set()
            for d in trading_days:
                key = (d.year, (d.month-1)//3)
                if key not in seen:
                    dates.add(d); seen.add(key)
        return dates

    @staticmethod
    def _compute_summary(records, config) -> dict:
        if not records:
            return {}
        rets = np.array([r.portfolio_return for r in records])
        equities = np.array([r.portfolio_equity for r in records])
        total_return_pct = (equities[-1]/config.initial_capital - 1) * 100
        n_days = len(rets)
        n_years = n_days / 252
        annualized = ((equities[-1]/config.initial_capital) ** (1/n_years) - 1) * 100 if n_years > 0 else 0
        rf_daily = 0.025 / 252
        excess = rets - rf_daily
        sharpe = (excess.mean()/excess.std() * np.sqrt(252)) if excess.std() > 0 else 0
        max_eq = np.maximum.accumulate(equities)
        dd = (equities/max_eq - 1) * 100
        mdd = float(dd.min())
        calmar = annualized / abs(mdd) if abs(mdd) > 0 else 0
        total_savings = sum(r.netting_savings for r in records)

        cum_alloc = sum(r.allocation_effect for r in records) * 100
        cum_macro = sum(r.macro_effect for r in records) * 100
        cum_cost = sum(r.cost_effect for r in records) * 100
        cum_netting = sum(r.netting_effect for r in records) * 100

        regime_alpha = {}
        for regime in ["GOLDILOCKS", "REFLATION", "STAGFLATION", "DEFLATION"]:
            r_rets = [r.portfolio_return for r in records if r.regime == regime]
            if r_rets:
                avg_ret = np.mean(r_rets)
                vol = np.std(r_rets)
                regime_alpha[regime] = {
                    "n_days": len(r_rets),
                    "avg_return_pct": float(round(avg_ret * 252 * 100, 2)),
                    "volatility_pct": float(round(vol * np.sqrt(252) * 100, 2)),
                    "sharpe": float(round(avg_ret/vol*np.sqrt(252), 2)) if vol > 0 else 0,
                }

        return {
            "total_return_pct":       float(round(total_return_pct, 2)),
            "annualized_return_pct":  float(round(annualized, 2)),
            "sharpe_ratio":           float(round(sharpe, 3)),
            "max_drawdown_pct":       float(round(mdd, 2)),
            "calmar_ratio":           float(round(calmar, 2)),
            "final_equity":           float(round(equities[-1], 2)),
            "total_trades":           int(sum(r.num_trades for r in records)),
            "total_turnover_pct":     float(round(sum(r.turnover_pct for r in records), 2)),
            "n_rebalances":           sum(1 for r in records if r.rebalanced),
            "n_trading_days":         n_days,
            "netting_total_savings":  float(round(total_savings, 2)),
            "attribution": {
                "allocation_effect_pct": float(round(cum_alloc, 2)),
                "macro_effect_pct":      float(round(cum_macro, 2)),
                "netting_effect_pct":    float(round(cum_netting, 2)),
                "cost_effect_pct":       float(round(cum_cost, 2)),
            },
            "regime_alpha": regime_alpha,
        }

    @staticmethod
    def _record_to_dict(r: DailyRecord) -> dict:
        return {
            "date":              str(r.date.date()),
            "portfolio_equity":  float(round(r.portfolio_equity, 2)),
            "portfolio_return":  float(round(r.portfolio_return, 6)),
            "cumulative_return": float(round(r.cumulative_return, 4)),
            "drawdown_pct":      float(round(r.drawdown_pct, 4)),
            "regime":            r.regime,
            "systemic_risk":     r.systemic_risk,
            "allocation_effect": float(round(r.allocation_effect, 6)),
            "macro_effect":      float(round(r.macro_effect, 6)),
            "netting_effect":    float(round(r.netting_effect, 6)),
            "cost_effect":       float(round(r.cost_effect, 6)),
            "num_trades":        r.num_trades,
            "turnover_pct":      float(round(r.turnover_pct, 4)),
            "netting_savings":   float(round(r.netting_savings, 2)),
            "rebalanced":        r.rebalanced,
            "weights":           {str(k): float(round(v, 4)) for k, v in r.weights.items()},
        }

    def _persist(self, config, result) -> int:
        s = result["summary"]
        with self.engine.begin() as conn:
            ins = conn.execute(text("""
                INSERT INTO multibacktest_runs (
                    run_name, strategy_ids, start_date, end_date, initial_capital,
                    allocation_method, rebalance_policy,
                    netting_enabled, macro_overlay_enabled,
                    commission_rate, slippage_rate,
                    total_return_pct, annualized_return_pct, sharpe_ratio,
                    max_drawdown_pct, calmar_ratio,
                    netting_total_savings, total_trades, total_turnover_pct,
                    n_rebalances, n_trading_days,
                    config_json, status, duration_seconds, completed_at
                ) VALUES (
                    :rn, :sids, :sd, :ed, :cap, :am, :rp, :ne, :me, :cr, :sr,
                    :tr, :ar, :sh, :mdd, :cal, :nts, :tt, :ttp, :nr, :ntd,
                    :cj, 'completed', :ds, CURRENT_TIMESTAMP
                )
            """), {
                "rn": config.run_name or f"Backtest {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                "sids": json.dumps(config.strategy_ids),
                "sd": config.start_date, "ed": config.end_date,
                "cap": config.initial_capital,
                "am": config.allocation_method, "rp": config.rebalance_policy,
                "ne": int(config.netting_enabled), "me": int(config.macro_overlay_enabled),
                "cr": config.commission_rate, "sr": config.slippage_rate,
                "tr": s["total_return_pct"], "ar": s["annualized_return_pct"],
                "sh": s["sharpe_ratio"],
                "mdd": s["max_drawdown_pct"], "cal": s["calmar_ratio"],
                "nts": s["netting_total_savings"],
                "tt": s["total_trades"], "ttp": s["total_turnover_pct"],
                "nr": s["n_rebalances"], "ntd": s["n_trading_days"],
                "cj": json.dumps(config.__dict__),
                "ds": result["duration_seconds"],
            })
            run_id = int(ins.lastrowid)

            daily_rows = []; strategy_daily_rows = []
            for r in result["daily_records"]:
                daily_rows.append({
                    "rid": run_id, "td": r["date"],
                    "pe": r["portfolio_equity"], "pr": r["portfolio_return"],
                    "cr": r["cumulative_return"], "dd": r["drawdown_pct"],
                    "rg": r.get("regime"), "sr": r.get("systemic_risk"),
                    "ae": r["allocation_effect"], "se": 0,
                    "me": r["macro_effect"], "ne": r["netting_effect"],
                    "ce": r["cost_effect"], "nsa": len(r["weights"]),
                    "nt": r["num_trades"], "tp": r["turnover_pct"],
                    "ns": r["netting_savings"], "rb": int(r["rebalanced"]),
                })
                for sid_str, w in r["weights"].items():
                    strategy_daily_rows.append({
                        "rid": run_id, "td": r["date"], "sid": int(sid_str),
                        "w": w, "bw": w, "ma": 0, "sr_": 0, "c": 0,
                    })

            for i in range(0, len(daily_rows), 500):
                conn.execute(text("""
                    INSERT INTO multibacktest_daily (
                        run_id, trade_date, portfolio_equity, portfolio_return,
                        cumulative_return, drawdown_pct, regime, systemic_risk,
                        allocation_effect, selection_effect, macro_effect,
                        netting_effect, cost_effect, num_strategies_active,
                        num_trades, turnover_pct, netting_savings, rebalanced
                    ) VALUES (:rid, :td, :pe, :pr, :cr, :dd, :rg, :sr,
                              :ae, :se, :me, :ne, :ce, :nsa, :nt, :tp, :ns, :rb)
                """), daily_rows[i:i+500])

            for i in range(0, len(strategy_daily_rows), 500):
                conn.execute(text("""
                    INSERT INTO multibacktest_strategy_daily (
                        run_id, trade_date, strategy_id,
                        weight, base_weight, macro_adjustment,
                        strategy_return, contribution
                    ) VALUES (:rid, :td, :sid, :w, :bw, :ma, :sr_, :c)
                """), strategy_daily_rows[i:i+500])

        return run_id
