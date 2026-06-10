"""
Counterfactual Analyzer — What-If 의사결정 가치 정량화
=========================================================
"매크로 끄면?" "netting 없으면?" "다른 알고리즘이면?" — N개 시나리오 병렬 실행.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _sanitize_cf(obj):
    """재귀적 NaN/Inf → 0."""
    if isinstance(obj, dict):
        return {k: _sanitize_cf(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_cf(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
    return obj


# ═══════════════════════════════════════════════════════════════════════════════
# 사전 정의 시나리오
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ScenarioOverride:
    name:                   str
    label:                  str
    description:            str
    allocation_method:      str | None = None
    macro_overlay_enabled:  bool | None = None
    netting_enabled:        bool | None = None
    rebalance_policy:       str | None = None
    equal_weight_override:  bool = False


PRESET_SCENARIOS = {
    "baseline": ScenarioOverride(
        name="baseline", label="원본 (Baseline)",
        description="사용자가 설정한 원본 구성",
    ),
    "no_macro_overlay": ScenarioOverride(
        name="no_macro_overlay", label="매크로 오버레이 끄기",
        description="HRP만 (Stage 9 매크로 영향 제거)",
        allocation_method="hrp", macro_overlay_enabled=False,
    ),
    "no_netting": ScenarioOverride(
        name="no_netting", label="중앙 청산 끄기",
        description="각 전략 독립 거래 (비용 증가)",
        netting_enabled=False,
    ),
    "equal_weight": ScenarioOverride(
        name="equal_weight", label="동일 가중 (1/N)",
        description="모든 전략 균등 배분 (벤치마크)",
        allocation_method="inverse_vol",
        equal_weight_override=True,
    ),
    "inverse_vol": ScenarioOverride(
        name="inverse_vol", label="역변동성 가중",
        description="단순 변동성 역수 (HRP 클러스터링 없이)",
        allocation_method="inverse_vol",
    ),
    "hrp_only": ScenarioOverride(
        name="hrp_only", label="HRP만 (매크로 X)",
        description="HRP 클러스터링 + 매크로 오버레이 끄기",
        allocation_method="hrp", macro_overlay_enabled=False,
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
# CounterfactualAnalyzer
# ═══════════════════════════════════════════════════════════════════════════════

class CounterfactualAnalyzer:
    """N개 시나리오 병렬 실행 + 의사결정 가치 정량화."""

    def __init__(self, engine):
        self.engine = engine

    def compare(
        self, base_config, scenario_names: list[str],
        custom_scenarios: list[dict] | None = None,
    ) -> dict:
        from src.engine.multi_strategy_backtest import MultiStrategyBacktester

        bt = MultiStrategyBacktester(self.engine)

        scenarios = []
        for name in scenario_names:
            if name in PRESET_SCENARIOS:
                scenarios.append(PRESET_SCENARIOS[name])
        if custom_scenarios:
            for cs in custom_scenarios:
                scenarios.append(ScenarioOverride(**cs))

        if not scenarios:
            return {"available": False, "message": "시나리오 없음"}

        scenario_results = []
        t_start = time.perf_counter()

        for sc in scenarios:
            t_sc = time.perf_counter()
            try:
                sc_config = self._apply_override(base_config, sc)
                sc_result = bt.run(sc_config)

                if sc_result["success"]:
                    summary = sc_result["summary"]
                    daily = sc_result["daily_records"]
                    eq_curve = self._compress_equity_curve(daily, max_points=200)

                    scenario_results.append({
                        "name":           sc.name,
                        "label":          sc.label,
                        "description":    sc.description,
                        "summary":        summary,
                        "equity_curve":   eq_curve,
                        "n_trading_days": sc_result["n_trading_days"],
                        "duration_seconds": round(time.perf_counter() - t_sc, 2),
                        "config_used":    sc_config.__dict__,
                    })
                else:
                    scenario_results.append({
                        "name": sc.name, "label": sc.label,
                        "success": False, "error": sc_result.get("message"),
                    })
            except Exception as e:
                logger.error(f"Scenario {sc.name} failed: {e}", exc_info=True)
                scenario_results.append({
                    "name": sc.name, "label": sc.label,
                    "success": False, "error": str(e),
                })

        if not scenario_results:
            return {"available": False, "message": "모든 시나리오 실패"}

        comparison = self._build_comparison_table(scenario_results)
        decision_values = self._compute_decision_values(scenario_results)

        return _sanitize_cf({
            "available":              True,
            "n_scenarios":            len(scenario_results),
            "scenarios":              scenario_results,
            "comparison_table":       comparison,
            "decision_values":        decision_values,
            "total_duration_seconds": round(time.perf_counter() - t_start, 2),
        })

    @staticmethod
    def _apply_override(base_config, override: ScenarioOverride):
        from src.engine.multi_strategy_backtest import BacktestConfig
        return BacktestConfig(
            strategy_ids=list(base_config.strategy_ids),
            start_date=base_config.start_date,
            end_date=base_config.end_date,
            initial_capital=base_config.initial_capital,
            allocation_method=override.allocation_method or base_config.allocation_method,
            rebalance_policy=override.rebalance_policy or base_config.rebalance_policy,
            netting_enabled=(override.netting_enabled if override.netting_enabled is not None
                              else base_config.netting_enabled),
            macro_overlay_enabled=(override.macro_overlay_enabled
                                    if override.macro_overlay_enabled is not None
                                    else base_config.macro_overlay_enabled),
            commission_rate=base_config.commission_rate,
            slippage_rate=base_config.slippage_rate,
            lookback_days=base_config.lookback_days,
            max_weight=base_config.max_weight,
            min_weight=base_config.min_weight,
            run_name=f"{base_config.run_name or 'CF'}_{override.name}",
        )

    @staticmethod
    def _compress_equity_curve(daily_records, max_points=200) -> list[dict]:
        if not daily_records:
            return []
        n = len(daily_records)
        step = max(1, n // max_points)
        compressed = []
        for i in range(0, n, step):
            r = daily_records[i]
            compressed.append({
                "date": r["date"],
                "equity": r["portfolio_equity"],
                "cumulative_return_pct": r["cumulative_return"],
                "drawdown_pct": r["drawdown_pct"],
                "regime": r.get("regime"),
            })
        if compressed[-1]["date"] != daily_records[-1]["date"]:
            r = daily_records[-1]
            compressed.append({
                "date": r["date"],
                "equity": r["portfolio_equity"],
                "cumulative_return_pct": r["cumulative_return"],
                "drawdown_pct": r["drawdown_pct"],
                "regime": r.get("regime"),
            })
        return compressed

    @staticmethod
    def _build_comparison_table(scenario_results) -> list[dict]:
        table = []
        baseline = None
        for sc in scenario_results:
            if sc.get("name") == "baseline" and sc.get("summary"):
                baseline = sc["summary"]
                break

        for sc in scenario_results:
            if "summary" not in sc:
                continue
            s = sc["summary"]
            row = {
                "scenario": sc["name"], "label": sc["label"],
                "total_return_pct": s["total_return_pct"],
                "annualized_return_pct": s["annualized_return_pct"],
                "sharpe_ratio": s["sharpe_ratio"],
                "max_drawdown_pct": s["max_drawdown_pct"],
                "calmar_ratio": s["calmar_ratio"],
                "n_rebalances": s["n_rebalances"],
                "total_turnover_pct": s["total_turnover_pct"],
                "netting_savings": s["netting_total_savings"],
            }
            if baseline and sc["name"] != "baseline":
                row["alpha_vs_baseline_pct"] = round(s["total_return_pct"] - baseline["total_return_pct"], 3)
                row["sharpe_diff_vs_baseline"] = round(s["sharpe_ratio"] - baseline["sharpe_ratio"], 3)
                row["mdd_diff_vs_baseline"] = round(s["max_drawdown_pct"] - baseline["max_drawdown_pct"], 3)
            else:
                row["alpha_vs_baseline_pct"] = 0
                row["sharpe_diff_vs_baseline"] = 0
                row["mdd_diff_vs_baseline"] = 0
            table.append(row)

        table.sort(key=lambda x: x["total_return_pct"], reverse=True)
        return table

    @staticmethod
    def _compute_decision_values(scenario_results) -> dict:
        by_name = {sc["name"]: sc for sc in scenario_results if sc.get("summary")}
        baseline = by_name.get("baseline")
        if not baseline:
            return {}
        b = baseline["summary"]
        result = {
            "baseline_return_pct": b["total_return_pct"],
            "baseline_sharpe":     b["sharpe_ratio"],
        }
        comparisons = [
            ("macro_overlay",       "no_macro_overlay", "매크로 오버레이의 가치"),
            ("netting",             "no_netting",       "중앙 청산의 가치"),
            ("hrp_vs_inverse_vol",  "inverse_vol",      "HRP 클러스터링의 가치"),
            ("vs_equal_weight",     "equal_weight",     "전체 시스템의 가치"),
        ]
        n_days = baseline.get("n_trading_days", 252)
        n_years = max(n_days / 252, 0.1)

        for key, scenario_key, description in comparisons:
            sc = by_name.get(scenario_key)
            if not sc:
                continue
            s = sc["summary"]
            alpha_pct = b["total_return_pct"] - s["total_return_pct"]
            sharpe_diff = b["sharpe_ratio"] - s["sharpe_ratio"]
            annualized_alpha = alpha_pct / n_years
            result[f"{key}_value_pct"] = round(alpha_pct, 3)
            result[f"{key}_value_bp_per_year"] = round(annualized_alpha * 100, 1)
            result[f"{key}_sharpe_diff"] = round(sharpe_diff, 3)
            result[f"{key}_description"] = description
        return result
