"""
Attribution Decomposer — 5-Factor Brinson 분해
=================================================
멀티 전략 백테스트의 5가지 의사결정 효과 분해 (Allocation/Selection/Macro/Netting/Cost).
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _sanitize_for_json(obj):
    """재귀적 NaN/Inf → 0 (JSON 안전)."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
    return obj


class AttributionDecomposer:
    """멀티 전략 백테스트 결과의 5-Factor 정밀 분해."""

    def __init__(self, engine):
        self.engine = engine

    def decompose(self, run_id: int, include_daily: bool = False) -> dict:
        run_info, daily_df, strategy_daily_df = self._load_run_data(run_id)
        if run_info is None or daily_df.empty:
            return {"available": False, "message": f"Run {run_id} 데이터 없음"}

        strategy_ids = list(strategy_daily_df["strategy_id"].unique()) if not strategy_daily_df.empty else []
        strategy_names = self._load_strategy_names(strategy_ids)

        cumulative = self._cumulative_attribution(daily_df)
        waterfall = self._build_waterfall(cumulative)
        monthly = self._aggregate_period(daily_df, "ME")
        quarterly = self._aggregate_period(daily_df, "QE")
        regime_breakdown = self._regime_breakdown(daily_df)
        strategy_contribution = self._strategy_contribution(strategy_daily_df, strategy_names)

        result = {
            "available":              True,
            "run_id":                 run_id,
            "run_name":               run_info.get("run_name"),
            "start_date":             run_info.get("start_date"),
            "end_date":               run_info.get("end_date"),
            "allocation_method":      run_info.get("allocation_method"),
            "n_trading_days":         len(daily_df),
            "summary": {
                "total_return_pct":       run_info.get("total_return_pct"),
                "annualized_return_pct":  run_info.get("annualized_return_pct"),
                "sharpe_ratio":           run_info.get("sharpe_ratio"),
                "max_drawdown_pct":       run_info.get("max_drawdown_pct"),
            },
            "cumulative":            cumulative,
            "waterfall":             waterfall,
            "monthly":               monthly,
            "quarterly":             quarterly,
            "regime_breakdown":      regime_breakdown,
            "strategy_contribution": strategy_contribution,
        }
        if include_daily:
            result["daily_attribution"] = self._daily_attribution(daily_df)

        return _sanitize_for_json(result)

    def _load_run_data(self, run_id) -> tuple[dict | None, pd.DataFrame, pd.DataFrame]:
        try:
            with self.engine.connect() as conn:
                run_row = conn.execute(text(
                    "SELECT * FROM multibacktest_runs WHERE id = :rid"
                ), {"rid": run_id}).fetchone()
                run_info = dict(run_row._mapping) if run_row else None

                daily_df = pd.read_sql(text(
                    "SELECT * FROM multibacktest_daily WHERE run_id = :rid ORDER BY trade_date"
                ), conn, params={"rid": run_id})
                strategy_daily_df = pd.read_sql(text(
                    "SELECT * FROM multibacktest_strategy_daily WHERE run_id = :rid ORDER BY trade_date, strategy_id"
                ), conn, params={"rid": run_id})

            if not daily_df.empty:
                daily_df["trade_date"] = pd.to_datetime(daily_df["trade_date"])
            if not strategy_daily_df.empty:
                strategy_daily_df["trade_date"] = pd.to_datetime(strategy_daily_df["trade_date"])
            return run_info, daily_df, strategy_daily_df
        except Exception as e:
            logger.error(f"Load failed: {e}")
            return None, pd.DataFrame(), pd.DataFrame()

    def _load_strategy_names(self, strategy_ids) -> dict:
        if not strategy_ids:
            return {}
        try:
            with self.engine.connect() as conn:
                placeholders = ",".join(f":s{i}" for i in range(len(strategy_ids)))
                params = {f"s{i}": int(sid) for i, sid in enumerate(strategy_ids)}
                rows = conn.execute(text(
                    f"SELECT id, name FROM strategies WHERE id IN ({placeholders})"
                ), params).fetchall()
            return {int(r._mapping["id"]): r._mapping["name"] for r in rows}
        except Exception:
            return {int(sid): f"Strategy #{sid}" for sid in strategy_ids}

    @staticmethod
    def _cumulative_attribution(daily_df) -> dict:
        if daily_df.empty:
            return {}
        cum_alloc = float(daily_df["allocation_effect"].fillna(0).sum() * 100)
        cum_select = float(daily_df["selection_effect"].fillna(0).sum() * 100)
        cum_macro = float(daily_df["macro_effect"].fillna(0).sum() * 100)
        cum_netting = float(daily_df["netting_effect"].fillna(0).sum() * 100)
        cum_cost = float(daily_df["cost_effect"].fillna(0).sum() * 100)

        actual_cum = (
            float(daily_df["cumulative_return"].iloc[-1])
            if "cumulative_return" in daily_df.columns and not pd.isna(daily_df["cumulative_return"].iloc[-1])
            else float((1 + daily_df["portfolio_return"]).prod() - 1) * 100
        )

        sum_factors = cum_alloc + cum_select + cum_macro + cum_netting + cum_cost
        interaction = actual_cum - sum_factors

        return {
            "allocation_effect_pct":   round(cum_alloc, 3),
            "selection_effect_pct":    round(cum_select, 3),
            "macro_effect_pct":        round(cum_macro, 3),
            "netting_effect_pct":      round(cum_netting, 3),
            "cost_effect_pct":         round(cum_cost, 3),
            "interaction_pct":         round(interaction, 3),
            "total_decomposed_pct":    round(sum_factors, 3),
            "actual_return_pct":       round(actual_cum, 3),
            "netting_savings_value":   float(round(daily_df["netting_savings"].fillna(0).sum(), 2)),
        }

    @staticmethod
    def _build_waterfall(cum) -> list[dict]:
        if not cum:
            return []
        baseline = cum["actual_return_pct"] - (
            cum["allocation_effect_pct"] + cum["macro_effect_pct"]
            + cum["netting_effect_pct"] + cum["cost_effect_pct"]
            + cum["selection_effect_pct"]
        )
        running = baseline
        waterfall = [{
            "step": "Baseline", "label": "베이스라인",
            "value": round(baseline, 3),
            "running_total": round(running, 3), "kind": "baseline",
        }]
        steps = [
            ("Allocation Effect", "배분 효과", cum["allocation_effect_pct"]),
            ("Selection Effect",  "전략 선택", cum["selection_effect_pct"]),
            ("Macro Overlay",     "매크로 오버레이", cum["macro_effect_pct"]),
            ("Netting Effect",    "청산 효과", cum["netting_effect_pct"]),
            ("Transaction Cost",  "거래 비용", cum["cost_effect_pct"]),
        ]
        for en, ko, val in steps:
            running += val
            waterfall.append({
                "step": en, "label": ko,
                "value": round(val, 3),
                "running_total": round(running, 3),
                "kind": "positive" if val >= 0 else "negative",
            })
        if abs(cum.get("interaction_pct", 0)) > 0.01:
            running += cum["interaction_pct"]
            waterfall.append({
                "step": "Interaction", "label": "복리 효과",
                "value": round(cum["interaction_pct"], 3),
                "running_total": round(running, 3), "kind": "interaction",
            })
        waterfall.append({
            "step": "Actual Total", "label": "실제 수익률",
            "value": cum["actual_return_pct"],
            "running_total": cum["actual_return_pct"], "kind": "total",
        })
        return waterfall

    @staticmethod
    def _aggregate_period(daily_df, freq) -> list[dict]:
        if daily_df.empty:
            return []
        df = daily_df.copy().set_index("trade_date")
        agg = df.groupby(pd.Grouper(freq=freq)).agg({
            "portfolio_return": "sum", "allocation_effect": "sum",
            "selection_effect": "sum", "macro_effect": "sum",
            "netting_effect": "sum", "cost_effect": "sum",
            "netting_savings": "sum", "turnover_pct": "sum",
            "num_trades": "sum", "rebalanced": "sum",
        }).fillna(0)

        for col in ["portfolio_return", "allocation_effect", "selection_effect",
                    "macro_effect", "netting_effect", "cost_effect"]:
            agg[col] = agg[col] * 100

        compound = (
            (1 + df["portfolio_return"]).groupby(pd.Grouper(freq=freq))
            .apply(lambda x: x.prod() - 1 if len(x) > 0 else 0) * 100
        )
        agg["portfolio_return_compound"] = compound.reindex(agg.index).fillna(0)

        result = []
        for period_end, row in agg.iterrows():
            if row["num_trades"] == 0 and abs(row["portfolio_return"]) < 0.0001:
                continue

            def _safe(v, d=3):
                try:
                    v = float(v)
                    if math.isnan(v) or math.isinf(v):
                        return 0.0
                    return round(v, d)
                except (TypeError, ValueError):
                    return 0.0

            result.append({
                "period":                str(period_end.date()),
                "portfolio_return_pct":  _safe(row.get("portfolio_return_compound", row["portfolio_return"])),
                "allocation_effect_pct": _safe(row["allocation_effect"]),
                "selection_effect_pct":  _safe(row["selection_effect"]),
                "macro_effect_pct":      _safe(row["macro_effect"]),
                "netting_effect_pct":    _safe(row["netting_effect"]),
                "cost_effect_pct":       _safe(row["cost_effect"]),
                "netting_savings_value": _safe(row["netting_savings"], 2),
                "turnover_pct":          _safe(row["turnover_pct"], 2),
                "num_trades":            int(row["num_trades"] or 0),
                "rebalances":            int(row["rebalanced"] or 0),
            })
        return result

    @staticmethod
    def _regime_breakdown(daily_df) -> list[dict]:
        if daily_df.empty or "regime" not in daily_df.columns:
            return []
        result = []
        for regime in ["GOLDILOCKS", "REFLATION", "STAGFLATION", "DEFLATION"]:
            subset = daily_df[daily_df["regime"] == regime]
            if subset.empty:
                continue
            n = len(subset)
            avg_ret = subset["portfolio_return"].mean()
            vol = subset["portfolio_return"].std()
            sharpe = (avg_ret/vol * np.sqrt(252)) if vol > 0 else 0
            sys_risk_mean = subset["systemic_risk"].mean()

            result.append({
                "regime": regime, "n_days": n,
                "n_days_pct": round(n/len(daily_df) * 100, 1),
                "annualized_return_pct": round(float(avg_ret * 252 * 100), 2),
                "volatility_pct": round(float(vol * np.sqrt(252) * 100), 2),
                "sharpe": round(float(sharpe), 3),
                "allocation_effect_pct": round(float(subset["allocation_effect"].fillna(0).sum() * 100), 3),
                "macro_effect_pct": round(float(subset["macro_effect"].fillna(0).sum() * 100), 3),
                "netting_effect_pct": round(float(subset["netting_effect"].fillna(0).sum() * 100), 3),
                "cost_effect_pct": round(float(subset["cost_effect"].fillna(0).sum() * 100), 3),
                "avg_systemic_risk": (round(float(sys_risk_mean), 1)
                                       if not pd.isna(sys_risk_mean) else None),
            })
        return result

    def _strategy_contribution(self, strategy_daily_df, strategy_names) -> list[dict]:
        if strategy_daily_df.empty:
            return []
        result = []
        for sid, group in strategy_daily_df.groupby("strategy_id"):
            sid_int = int(sid)
            avg_weight = float(group["weight"].fillna(0).mean())
            ma = group["macro_adjustment"].fillna(0)
            avg_macro_adj = float(ma.mean()) if len(ma) > 0 else 0.0
            cum_contribution = float(group["contribution"].fillna(0).sum() * 100)
            if cum_contribution == 0 and "strategy_return" in group.columns:
                cum_contribution = float((group["weight"].fillna(0) * group["strategy_return"].fillna(0)).sum() * 100)

            result.append({
                "strategy_id": sid_int,
                "strategy_name": strategy_names.get(sid_int, f"#{sid_int}"),
                "avg_weight": round(avg_weight, 4),
                "avg_macro_adjustment": round(avg_macro_adj, 4),
                "cumulative_contribution_pct": round(cum_contribution, 3),
                "n_days_active": int((group["weight"].fillna(0) > 0.001).sum()),
            })
        result.sort(key=lambda x: x["avg_weight"], reverse=True)
        return result

    @staticmethod
    def _daily_attribution(daily_df) -> list[dict]:
        if daily_df.empty:
            return []
        return [{
            "date": str(r["trade_date"].date()),
            "portfolio_return": round(float(r["portfolio_return"] or 0) * 100, 4),
            "allocation_effect": round(float(r["allocation_effect"] or 0) * 100, 4),
            "selection_effect": round(float(r["selection_effect"] or 0) * 100, 4),
            "macro_effect": round(float(r["macro_effect"] or 0) * 100, 4),
            "netting_effect": round(float(r["netting_effect"] or 0) * 100, 4),
            "cost_effect": round(float(r["cost_effect"] or 0) * 100, 4),
            "regime": r["regime"],
        } for _, r in daily_df.iterrows()]
