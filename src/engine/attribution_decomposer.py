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


#: 5-Factor 분해의 효과 컬럼. 커버리지는 이 다섯을 기준으로 잰다.
EFFECT_COLUMNS = ("allocation_effect", "selection_effect", "macro_effect",
                  "netting_effect", "cost_effect")


def _sanitize_for_json(obj):
    """재귀적 NaN/Inf → ★`None`★ (JSON 안전).

    ★예전에는 `0.0` 이었다 (P4-a).★ 엄격 JSON 이 NaN/Inf 를 못 싣는 것은 맞지만
    그 해법이 **0** 일 이유는 없다 — 0 은 측정된 값이고 NaN 은 미상이다. 둘을
    같은 자리에 쓰면 소비자가 구분할 방법이 사라진다. `null` 도 똑같이 유효한
    JSON 이고, 이쪽은 아무것도 제조하지 않는다.
    """
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
    return obj


def column_coverage(df, col: str) -> dict:
    """★몇 행을 실제로 봤는가★ — 순수 함수 (P4-a).

    `fillna(0)` 은 "안 본 행" 과 "0 인 행" 을 같은 자리에 쓴다. 합을 쓰려면 그 합이
    **무엇으로 만들어졌는지** 함께 말해야 한다.
    """
    n_total = int(len(df))
    if col not in getattr(df, "columns", []):
        return {"n_total": n_total, "n_known": 0, "coverage": 0.0,
                "reason": f"'{col}' 컬럼이 없습니다"}
    n_known = int(pd.notna(df[col]).sum())
    cov = (n_known / n_total) if n_total else 0.0
    reason = None
    if n_known == 0:
        reason = (f"'{col}' 이 {n_total}행 전부에서 관측되지 않았습니다 — "
                  "미상이지 0 이 아닙니다")
    return {"n_total": n_total, "n_known": n_known,
            "coverage": round(cov, 6), "reason": reason}


def sum_known(df, col: str, *, scale: float = 1.0):
    """알려진 행만의 합 + 커버리지. 한 행도 못 봤으면 ★`None`★ 이다."""
    cov = column_coverage(df, col)
    if cov["n_known"] == 0:
        return None, cov
    return float(df[col].sum(skipna=True)) * scale, cov


class AttributionDecomposer:
    """멀티 전략 백테스트 결과의 5-Factor 정밀 분해."""

    def __init__(self, engine):
        self.engine = engine

    def decompose(self, run_id: int, include_daily: bool = False) -> dict:
        run_info, daily_df, strategy_daily_df, load_error = self._load_run_data(run_id)
        if load_error is not None:
            return {"available": False, "failure": "load_failed",
                    "message": (f"Run {run_id} 적재에 실패했습니다 — {load_error}. "
                                "데이터가 없다는 뜻이 아닙니다.")}
        if run_info is None or daily_df.empty:
            return {"available": False, "failure": "no_rows",
                    "message": f"Run {run_id} 에 해당하는 행이 없습니다"}

        strategy_ids = list(strategy_daily_df["strategy_id"].unique()) if not strategy_daily_df.empty else []
        strategy_names, names_error = self._load_strategy_names(strategy_ids)

        cumulative = self._cumulative_attribution(daily_df)
        waterfall = self._build_waterfall(cumulative)
        monthly = self._aggregate_period(daily_df, "ME")
        quarterly = self._aggregate_period(daily_df, "QE")
        regime_breakdown = self._regime_breakdown(daily_df)
        strategy_contribution = self._strategy_contribution(
            strategy_daily_df, strategy_names, names_error)

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

    def _load_run_data(self, run_id) -> tuple[dict | None, pd.DataFrame,
                                              pd.DataFrame, str | None]:
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
            return run_info, daily_df, strategy_daily_df, None
        except Exception as e:
            # ★적재 실패를 "데이터 없음" 으로 말하지 않는다 (P4-a)★ 없는 것과
            # 못 읽은 것은 다른 사실이고, 원인이 다르면 대응도 다르다.
            logger.error(f"Load failed: {e}")
            return None, pd.DataFrame(), pd.DataFrame(), f"{type(e).__name__}: {e}"

    def _load_strategy_names(self, strategy_ids) -> tuple[dict, str | None]:
        """전략 id → 이름. ★조회에 실패하면 이름을 지어내지 않는다 (P4-a)★

        예전에는 `f"Strategy #{sid}"` 를 만들어 돌려줬다 — 조회가 성공한 것처럼
        보이는 문자열이다. `stock_master` 에서 `"Unknown Corp"` 를 금지한 것과
        같은 형태다: 미상인 이름은 이름이 아니다.
        """
        if not strategy_ids:
            return {}, None
        try:
            with self.engine.connect() as conn:
                placeholders = ",".join(f":s{i}" for i in range(len(strategy_ids)))
                params = {f"s{i}": int(sid) for i, sid in enumerate(strategy_ids)}
                rows = conn.execute(text(
                    f"SELECT id, name FROM strategies WHERE id IN ({placeholders})"
                ), params).fetchall()
            return {int(r._mapping["id"]): r._mapping["name"] for r in rows}, None
        except Exception as e:
            return {}, f"전략명 조회에 실패했습니다 — {type(e).__name__}: {e}"

    @staticmethod
    def _cumulative_attribution(daily_df) -> dict:
        """누적 분해 — ★합은 쓰되 무엇으로 만든 합인지 말한다★ (P4-a).

        예전에는 다섯 효과를 전부 `fillna(0)` 으로 더했다. 그러면 `sum_factors`
        가 미상만큼 줄고 `interaction = actual − sum_factors` 가 **정확히 그만큼을
        흡수한다** — 구멍이 있는 패널과 없는 패널이 완전히 같은 리포트를 냈다.
        ★리포트는 틀렸을 때 오히려 자기일관적이었다.★ 그래서 값을 `None` 으로
        바꾸는 것만으로는 부족하고, **잔차의 이름**을 바꿔야 한다.
        """
        if daily_df.empty:
            return {}

        vals: dict[str, float | None] = {}
        coverage: dict[str, dict] = {}
        for col in EFFECT_COLUMNS:
            v, cov = sum_known(daily_df, col, scale=100.0)
            vals[col] = None if v is None else round(v, 3)
            coverage[col] = cov

        savings, savings_cov = sum_known(daily_df, "netting_savings")
        coverage["netting_savings"] = savings_cov

        actual_cum = (
            float(daily_df["cumulative_return"].iloc[-1])
            if "cumulative_return" in daily_df.columns
            and not pd.isna(daily_df["cumulative_return"].iloc[-1])
            else float((1 + daily_df["portfolio_return"]).prod() - 1) * 100
        )

        known = [v for v in vals.values() if v is not None]
        sum_factors = float(sum(known))
        residual = actual_cum - sum_factors
        complete = all(coverage[c]["coverage"] == 1.0 for c in EFFECT_COLUMNS)

        # ★커버리지가 불완전하면 잔차를 "복리 효과" 라고 부르기를 거부한다★
        # 그때 잔차는 복리와 **흡수된 미상**의 혼합이라, 복리라고 이름 붙이는
        # 순간 하지 않은 분해를 주장하게 된다.
        unexplained_reason = None
        if not complete:
            missing = [c for c in EFFECT_COLUMNS if coverage[c]["coverage"] < 1.0]
            unexplained_reason = (
                f"{', '.join(missing)} 의 커버리지가 불완전해 잔차가 복리 효과와 "
                "미관측분의 혼합입니다 — 복리 효과로 읽을 수 없습니다")

        return {
            "allocation_effect_pct":   vals["allocation_effect"],
            "selection_effect_pct":    vals["selection_effect"],
            "macro_effect_pct":        vals["macro_effect"],
            "netting_effect_pct":      vals["netting_effect"],
            "cost_effect_pct":         vals["cost_effect"],
            # ★잔차는 커버리지에 따라 이름이 다르다★ 둘 중 하나만 값을 갖는다.
            "interaction_pct":         (round(residual, 3) if complete else None),
            "unexplained_pct":         (None if complete else round(residual, 3)),
            "unexplained_reason":      unexplained_reason,
            "coverage":                coverage,
            "coverage_complete":       complete,
            # 커버리지 0 인 효과는 워터폴 스텝을 만들 수 없다(값이 미상이다).
            "waterfall_omitted":       [c for c in EFFECT_COLUMNS
                                        if vals[c] is None],
            "total_decomposed_pct":    round(sum_factors, 3),
            "actual_return_pct":       round(actual_cum, 3),
            "netting_savings_value":   (None if savings is None
                                        else float(round(savings, 2))),
        }

    @staticmethod
    def _build_waterfall(cum) -> list[dict]:
        """워터폴 — ★잔차를 두 번 세지 않는다★ (P4-a).

        예전에는 `baseline = actual − Σ효과` 였는데 `interaction` 이 **같은 식**
        이었다. 그래서 같은 미설명분이 두 번 더해져 running_total 이 실제값을
        넘어섰다가(실측 5.0 → 8.0) 마지막 "Actual Total" 스텝이 조용히 되돌려
        놓았다. 이제 베이스라인은 0 에서 시작하고 잔차는 **한 번만** 센다 —
        이 모듈에는 베이스라인을 0 이 아닌 값으로 앵커할 벤치마크가 없다.

        ★불변식: 스텝 값은 절대 `None` 이 아니다★ 프론트가
        `step.value.toFixed(2)` 를 부른다. 커버리지 0 인 효과는 스텝을 만들지
        않고 `cum["waterfall_omitted"]` 가 그 사실을 남긴다.

        ★`kind` 는 프론트의 닫힌 유니온 안에서만 쓴다★ `COLORS[step.kind]` 라
        새 값을 넣으면 `undefined` 가 된다. 잔차는 `interaction` 을 유지하고
        **라벨만** 바꾼다.
        """
        if not cum:
            return []
        running = 0.0
        waterfall = [{
            "step": "Baseline", "label": "베이스라인",
            "value": 0.0, "running_total": 0.0, "kind": "baseline",
        }]
        steps = [
            ("Allocation Effect", "배분 효과", cum["allocation_effect_pct"]),
            ("Selection Effect",  "전략 선택", cum["selection_effect_pct"]),
            ("Macro Overlay",     "매크로 오버레이", cum["macro_effect_pct"]),
            ("Netting Effect",    "청산 효과", cum["netting_effect_pct"]),
            ("Transaction Cost",  "거래 비용", cum["cost_effect_pct"]),
        ]
        for en, ko, val in steps:
            if val is None:                  # ★미상은 스텝이 될 수 없다★
                continue
            running += val
            waterfall.append({
                "step": en, "label": ko,
                "value": round(val, 3),
                "running_total": round(running, 3),
                "kind": "positive" if val >= 0 else "negative",
            })

        complete = cum.get("coverage_complete", True)
        resid = (cum.get("interaction_pct") if complete
                 else cum.get("unexplained_pct"))
        if resid is not None and abs(resid) > 0.01:
            running += resid
            waterfall.append({
                "step": "Interaction" if complete else "Unexplained",
                "label": "복리 효과" if complete else "미설명 잔차(커버리지 불완전)",
                "value": round(resid, 3),
                "running_total": round(running, 3),
                "kind": "interaction",
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
            # ★변동성 0 이면 샤프는 0 이 아니라 미상이다 (P4-a)★ 바로 아래
            # `avg_systemic_risk` 가 이미 쓰던 관례를 같은 함수 안에서 맞춘다.
            sharpe = None
            sharpe_reason = None
            if pd.isna(vol):
                sharpe_reason = "표본이 1일이라 변동성을 잴 수 없습니다"
            elif vol > 0:
                sharpe = round(float(avg_ret / vol * np.sqrt(252)), 3)
            else:
                sharpe_reason = ("이 국면의 일수익 변동성이 0 이라 샤프가 "
                                 "정의되지 않습니다 — 0 이 아니라 미상입니다")
            sys_risk_mean = subset["systemic_risk"].mean()

            result.append({
                "regime": regime, "n_days": n,
                "n_days_pct": round(n/len(daily_df) * 100, 1),
                "annualized_return_pct": round(float(avg_ret * 252 * 100), 2),
                "volatility_pct": round(float(vol * np.sqrt(252) * 100), 2),
                "sharpe": sharpe,
                "sharpe_reason": sharpe_reason,
                "allocation_effect_pct": round(float(subset["allocation_effect"].fillna(0).sum() * 100), 3),
                "macro_effect_pct": round(float(subset["macro_effect"].fillna(0).sum() * 100), 3),
                "netting_effect_pct": round(float(subset["netting_effect"].fillna(0).sum() * 100), 3),
                "cost_effect_pct": round(float(subset["cost_effect"].fillna(0).sum() * 100), 3),
                "avg_systemic_risk": (round(float(sys_risk_mean), 1)
                                       if not pd.isna(sys_risk_mean) else None),
            })
        return result

    def _strategy_contribution(self, strategy_daily_df, strategy_names,
                               names_error: str | None = None) -> list[dict]:
        if strategy_daily_df.empty:
            return []
        result = []
        for sid, group in strategy_daily_df.groupby("strategy_id"):
            sid_int = int(sid)
            avg_weight = float(group["weight"].fillna(0).mean())
            ma = group["macro_adjustment"].fillna(0)
            avg_macro_adj = float(ma.mean()) if len(ma) > 0 else 0.0
            # ★"기여가 0" 과 "기여가 미상" 을 **값으로** 구분하지 않는다 (P4-a)★
            # 예전에는 합이 0 이면 대체 계산으로 넘어갔다 — 진짜 0 인 전략이
            # 조용히 재계산돼 없던 기여가 생겼다. 커버리지로 가른다.
            contrib_cov = column_coverage(group, "contribution")
            if contrib_cov["n_known"] > 0:
                cum_contribution = float(
                    group["contribution"].sum(skipna=True) * 100)
                source = "contribution"
            elif "strategy_return" in group.columns:
                cum_contribution = float(
                    (group["weight"] * group["strategy_return"]).sum(skipna=True) * 100)
                source = "weight_times_return"
            else:
                cum_contribution = None
                source = None

            result.append({
                "strategy_id": sid_int,
                "strategy_name": strategy_names.get(sid_int),
                "strategy_name_reason": (
                    None if sid_int in strategy_names
                    else (names_error or f"id {sid_int} 이 strategies 에 없습니다")),
                "avg_weight": round(avg_weight, 4),
                "avg_macro_adjustment": round(avg_macro_adj, 4),
                "cumulative_contribution_pct": (None if cum_contribution is None
                                                else round(cum_contribution, 3)),
                # ★대체 계산을 썼으면 그 사실을 적는다★ 같은 칸에 다른 출처의
                # 수를 넣고 말하지 않으면 소비자가 구분할 수 없다.
                "contribution_source": source,
                "contribution_coverage": contrib_cov["coverage"],
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
