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
    #: ★동일가중 기준 EW_t★ (BH2) — 그날 전략 수익률의 단순평균. 귀인 항등식
    #: `net = EW + alloc + cost (+ cash)` 의 첫 드라이버. `None` 은 기록하지 않은 옛 경로.
    baseline_effect:    float | None = None
    allocation_effect:  float = 0
    # ★기본이 `None` 이다★ (AL2) — 예전 기본 `0` 은 **상수가 관측 행세**를 했고,
    # `column_coverage` 가 `pd.notna` 로 세는 탓에 `coverage_complete` 가 거짓으로
    # 참이 되어 잔차가 `unexplained` 대신 `interaction`(복리)으로 이름 붙었다.
    selection_effect:   float | None = None
    macro_effect:       float = 0
    #: ★`None` 은 그날 네팅을 판정하지 못했다는 뜻★ (BG3) — 보유를 몰랐다.
    netting_effect:     float | None = 0
    #: 거래로 **나간** 돈만. ★현금이자를 여기 더하지 않는다★ (AL3)
    cost_effect:        float = 0
    #: 안 쓴 현금이 **번** 이자. ★`None` 은 그 엔진에 현금 모델이 없다는 뜻★ —
    #: 0 으로 적으면 "이자가 0 이었다" 는 관측이 되어 버린다.
    cash_effect:        float | None = None
    num_trades:         int = 0
    turnover_pct:       float = 0
    netting_savings:    float | None = 0
    #: 네팅을 판정하지 못한 사유(`netting_savings is None` 일 때만).
    netting_reason:     str | None = None
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

    def _ensure_schema(self) -> None:
        """저장 표가 없으면 만든다 — ★`/init-schema` 를 먼저 부르지 않아도 된다★ (BG5).

        예전에는 표가 없으면 저장·목록이 500 이었다. 이미 있으면 건드리지 않는
        DDL 이라 몇 번 불러도 같다.
        """
        from src.engine.multibacktest_schema import init_multibacktest_schema
        init_multibacktest_schema(self.engine)

    def run_and_save(self, config: BacktestConfig) -> dict:
        result = self.run(config)
        if not result["success"]:
            return result
        self._ensure_schema()
        run_id = self._persist(config, result)
        result["run_id"] = run_id
        return result

    def load_run(self, run_id: int) -> dict | None:
        self._ensure_schema()
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
        self._ensure_schema()
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

        # ★네팅의 재료★ (BG3) — 등록 때 재실행에서 나온 일별 종목 보유.
        holdings = self.registry.load_holdings(
            config.strategy_ids, config.start_date, config.end_date)

        return {
            "returns_matrix": returns_matrix,
            "strategies":     strategies,
            "strategy_names": strategy_names,
            "macro_df":       macro_df,
            "holdings":       holdings,
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

            # Attribution — ★항등식: net = EW + alloc + cost★ (BH2)
            baseline_ew = sum(day_returns.get(sid, 0) for sid in sids) / n_str
            alloc_diff = sum((current_weights.get(int(sid), 0) - 1/n_str) * day_returns.get(sid, 0) for sid in sids)
            macro_effect = sum(current_macro_adj.get(int(sid), 0) * day_returns.get(sid, 0) for sid in sids)

            # Cost + Netting
            turnover = 0.0
            cost_effect = 0.0

            if rebalanced_today and t > 0:
                prev_w = daily_records[-1].weights if daily_records else current_weights
                turnover = sum(abs(current_weights.get(int(sid), 0) - prev_w.get(int(sid), 0)) for sid in sids)
                total_rate = config.commission_rate + config.slippage_rate
                cost_effect = -turnover * total_rate

            # ★네팅은 실제 보유로 잰다★ (BG3) — 예전에는 리밸런싱 날에만
            # `(회전율 × 1.5 − 회전율) × 요율` 이라는 지어낸 수를 적었다. 전략들은
            # 매일 안에서 거래하므로 매일 잰다. ★보고 전용★ — 수익률에 안 더한다.
            netting_savings, netting_reason = self._netting(
                config, data, daily_records, current_weights, date, equity)

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
                # ★상수 0 을 싣지 않는다★ (AL2) — 이 엔진은 선택 효과를 재지
                # 않는다. Brinson 선택항은 전략별 벤치마크가 필요한데 그 계열이
                # 저장소에 없다. 재료가 `None` 이면 기존 커버리지 가드가 제대로
                # 작동해 잔차가 "복리" 로 오명명되지 않는다.
                baseline_effect=baseline_ew,
                allocation_effect=alloc_diff, selection_effect=None,
                macro_effect=macro_effect,
                netting_effect=(None if netting_savings is None
                                else (netting_savings / equity if equity > 0 else 0)),
                cost_effect=cost_effect,
                # ★이 엔진엔 현금 모델이 없다★ (AL3) — `cash` 라는 문자열이
                # 이 파일에 한 번도 없었다. 0 이 아니라 미측정이다.
                cash_effect=None,
                num_trades=int(round(turnover * len(sids))) if rebalanced_today else 0,
                turnover_pct=turnover * 100,
                netting_savings=netting_savings, netting_reason=netting_reason,
                rebalanced=rebalanced_today,
                weights=current_weights.copy(),
                base_weights=current_base_weights.copy(),
                macro_adj=current_macro_adj.copy(),
                strategy_returns=day_returns,
            )
            daily_records.append(record)
            equity = equity_new

        return daily_records, warnings

    def _netting(self, config, data, daily_records, current_weights, date,
                 equity) -> tuple[float | None, str | None]:
        """그날의 네팅 절감 — `(원화, None)` 또는 `(None, 사유)`. 꺼져 있으면 0(선택).

        realism 엔진도 이 메서드를 쓴다 — 두 벌을 두지 않는다.
        """
        # 첫날은 엔진이 비용도 물리지 않는 날(전날이 없다)이라 네팅도 0 이다 —
        # 요약은 이 날을 잰 날로 세지 않는다(`netting_summary`).
        if not config.netting_enabled or not daily_records:
            return 0.0, None
        prev = daily_records[-1]
        return self.netting_engine.savings(
            prev_weights=prev.weights, cur_weights=current_weights,
            holdings=data.get("holdings") or {},
            prev_date=str(pd.Timestamp(prev.date).date()),
            date=str(pd.Timestamp(date).date()), equity=equity,
            rate=config.commission_rate + config.slippage_rate)

    @staticmethod
    def netting_summary(records, enabled: bool) -> dict:
        """★잰 날과 못 잰 날을 함께★ — 합계만 내면 미상이 0 으로 녹는다."""
        from src.execution.order_netting import ASSUMPTIONS, NETTING_BASIS
        # ★첫날은 세지 않는다★ — 비교할 전날이 없어 잰 것도 못 잰 것도 아니다.
        known = [r.netting_savings for r in records[1:] if r.netting_savings is not None]
        unknown = [r for r in records[1:] if r.netting_savings is None]
        return {
            "enabled": bool(enabled),
            "basis": NETTING_BASIS if enabled else "off",
            "assumptions": list(ASSUMPTIONS) if enabled else [],
            "n_measured_days": len(known) if enabled else 0,
            "n_unmeasured_days": len(unknown),
            "first_unmeasured_reason": unknown[0].netting_reason if unknown else None,
        }

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
        # ★위험조정 지표를 여기서 다시 정의하지 않는다 (P1 잔여)★
        # 예전에는 `rf_daily = 0.025/252` 와 `excess.std()`(ddof=0)를 이 자리에서
        # 직접 썼다 — `allocation_backtest` 는 0.035·ddof=1 이라 같은 이름의
        # Sharpe 가 두 벌이었고, 어느 관례로 만든 수인지 리포트가 말하지 않았다.
        #
        # ★관례는 이 모듈이 쓰던 그대로 넘긴다 — 값이 바뀌지 않는다★
        # 무위험 0.025 · ddof 0 · **기하** 연율화(CAGR). 단일 출처가 기하
        # 연율화를 인자로 받게 된 뒤에야 이 이전이 가능해졌다(그 전에는 calmar 가
        # −0.470 → −0.515 로 바뀌었다).
        from src.engine.quant_metrics import risk_adjusted_ratios
        rar = risk_adjusted_ratios(
            rets, equities, periods_per_year=252, risk_free=0.025, ddof=0,
            annualization="geometric", starting_equity=config.initial_capital)
        # 미상은 `None` 인데 이 요약의 기존 계약은 `0` 이었으므로 그 자리에서만
        # 보존한다(스키마 호환) — 사유는 `rar["reasons"]` 에 남는다.
        sharpe = rar["sharpe_ratio"] or 0
        max_eq = np.maximum.accumulate(equities)
        dd = (equities/max_eq - 1) * 100
        mdd = float(dd.min())
        calmar = rar["calmar_ratio"] or 0
        # ★아는 날만 더한다★ (BG3) — 모르는 날을 0 으로 녹이지 않고 따로 센다.
        # 첫날은 엔진이 비용을 물리지 않는 날이라(전날이 없다) 네팅도 0 이다 — 그
        # 0 이 "잰 날" 로 세여 전부 미상인 실행의 합계를 0 으로 만들지 않게 뺀다.
        _ns = [r.netting_savings for r in records[1:] if r.netting_savings is not None]
        total_savings = float(sum(_ns)) if _ns else None

        cum_alloc = sum(r.allocation_effect for r in records) * 100
        cum_macro = sum(r.macro_effect for r in records) * 100
        cum_cost = sum(r.cost_effect for r in records) * 100
        _ne = [r.netting_effect for r in records[1:] if r.netting_effect is not None]
        cum_netting = (float(sum(_ne)) * 100) if _ne else None
        # ★현금이자는 비용이 아니다★ (AL3) — 한 행도 못 봤으면 `None` 이다.
        # 0 으로 적으면 "이자가 0 이었다" 는 **관측**이 되어 버린다.
        _cash = [r.cash_effect for r in records if r.cash_effect is not None]
        cum_cash = (float(sum(_cash)) * 100) if _cash else None

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
            # ★그 수를 만든 관례를 함께 싣는다 (P1)★ 무위험·ddof·연율화가
            # 모듈마다 갈라져 있었고, 관례를 안 적으면 두 리포트의 Sharpe 를
            # 비교할 수 없다. 표시 반올림과 달리 이 블록은 전정밀도다.
            "convention":             rar["convention"],
            "sharpe_ratio_full":      rar["sharpe_ratio"],
            "final_equity":           float(round(equities[-1], 2)),
            "total_trades":           int(sum(r.num_trades for r in records)),
            "total_turnover_pct":     float(round(sum(r.turnover_pct for r in records), 2)),
            "n_rebalances":           sum(1 for r in records if r.rebalanced),
            "n_trading_days":         n_days,
            "netting_total_savings":  (None if total_savings is None
                                       else float(round(total_savings, 2))),
            "netting": MultiStrategyBacktester.netting_summary(
                records, getattr(config, "netting_enabled", True)),
            "attribution": {
                "allocation_effect_pct": float(round(cum_alloc, 2)),
                "macro_effect_pct":      float(round(cum_macro, 2)),
                "netting_effect_pct":    (None if cum_netting is None
                                          else float(round(cum_netting, 2))),
                "cost_effect_pct":       float(round(cum_cost, 2)),
                "cash_effect_pct":       (None if cum_cash is None
                                          else float(round(cum_cash, 2))),
            },
            "regime_alpha": regime_alpha,
        }

    @staticmethod
    def _record_to_dict(r: DailyRecord) -> dict:
        """일별 기록 → dict. ★수익률·효과 칸은 반올림하지 않는다★ (BH2)

        예전에는 `round(…, 6)` 이었다 — 화면에는 무해하지만 이 dict 가 그대로 저장되어
        귀인 항등식 `net = EW + alloc + cost` 가 저장값에서 1e-6 만큼 어긋났다(검사 1e-9).
        """
        def _f(v):
            return None if v is None else float(v)

        return {
            "date":              str(r.date.date()),
            "portfolio_equity":  float(round(r.portfolio_equity, 2)),
            "portfolio_return":  float(r.portfolio_return),
            "cumulative_return": float(round(r.cumulative_return, 4)),
            "drawdown_pct":      float(round(r.drawdown_pct, 4)),
            "regime":            r.regime,
            "systemic_risk":     r.systemic_risk,
            "baseline_effect":   _f(r.baseline_effect),
            "allocation_effect": float(r.allocation_effect),
            "selection_effect":  _f(r.selection_effect),
            "macro_effect":      float(r.macro_effect),
            "netting_effect":    _f(r.netting_effect),
            "cost_effect":       float(r.cost_effect),
            "cash_effect":       _f(r.cash_effect),
            "num_trades":        r.num_trades,
            "turnover_pct":      float(round(r.turnover_pct, 4)),
            "netting_savings":   (None if r.netting_savings is None
                                  else float(round(r.netting_savings, 2))),
            "rebalanced":        r.rebalanced,
            "weights":           {str(k): float(round(v, 4)) for k, v in r.weights.items()},
            # ★저장이 상수 0 을 쓰지 않도록 재료를 싣는다★ (BH2) — 전략별 수익·기준 가중·
            # 매크로 조정. 반올림한 `weights` 와 따로 **정밀** 가중도 싣는다(기여 = w·r).
            "strategy_returns":  {str(k): float(v) for k, v in r.strategy_returns.items()},
            "weights_exact":     {str(k): float(v) for k, v in r.weights.items()},
            "base_weights":      {str(k): float(v) for k, v in r.base_weights.items()},
            "macro_adj":         {str(k): float(v) for k, v in r.macro_adj.items()},
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
                ) RETURNING id
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
            # ★`lastrowid` 는 PostgreSQL(psycopg2)에서 새 id 가 아니다★ (BG5) —
            # 두 방언 모두 되는 `RETURNING id` 로 받는다(SQLite ≥ 3.35).
            run_id = int(ins.scalar())

            daily_rows = []; strategy_daily_rows = []
            for r in result["daily_records"]:
                daily_rows.append({
                    "rid": run_id, "td": r["date"],
                    "pe": r["portfolio_equity"], "pr": r["portfolio_return"],
                    "cr": r["cumulative_return"], "dd": r["drawdown_pct"],
                    "rg": r.get("regime"), "sr": r.get("systemic_risk"),
                    # ★세 번째 상수 0 이 여기 있었다★ (AL2) — 레코드를 고쳐도
                    # 이 빌더가 `0` 을 덮어써서 DB 에는 여전히 거짓 관측이
                    # 들어갔다. 레코드가 말하는 것을 그대로 싣는다.
                    "be": r.get("baseline_effect"),
                    "ae": r["allocation_effect"], "se": r.get("selection_effect"),
                    "me": r["macro_effect"], "ne": r["netting_effect"],
                    "ce": r["cost_effect"], "cash": r.get("cash_effect"),
                    "nsa": len(r["weights"]),
                    "nt": r["num_trades"], "tp": r["turnover_pct"],
                    "ns": r["netting_savings"], "rb": int(r["rebalanced"]),
                })
                # ★상수 0 을 쓰지 않는다★ (BH2) — 예전 `"ma": 0, "sr_": 0, "c": 0` 은
                # 전략별 기여를 "0 으로 관측" 되게 만들었다(커버리지 1.0 · 값 0).
                exact = r.get("weights_exact") or r["weights"]
                rets = r.get("strategy_returns") or {}
                for sid_str, w in exact.items():
                    ret = rets.get(sid_str)
                    strategy_daily_rows.append({
                        "rid": run_id, "td": r["date"], "sid": int(sid_str),
                        "w": w,
                        "bw": (r.get("base_weights") or {}).get(sid_str),
                        "ma": (r.get("macro_adj") or {}).get(sid_str),
                        "sr_": ret,
                        "c": None if ret is None else w * ret,
                    })

            for i in range(0, len(daily_rows), 500):
                conn.execute(text("""
                    INSERT INTO multibacktest_daily (
                        run_id, trade_date, portfolio_equity, portfolio_return,
                        cumulative_return, drawdown_pct, regime, systemic_risk,
                        baseline_effect,
                        allocation_effect, selection_effect, macro_effect,
                        netting_effect, cost_effect, cash_effect,
                        num_strategies_active,
                        num_trades, turnover_pct, netting_savings, rebalanced
                    ) VALUES (:rid, :td, :pe, :pr, :cr, :dd, :rg, :sr, :be,
                              :ae, :se, :me, :ne, :ce, :cash, :nsa, :nt, :tp, :ns, :rb)
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
