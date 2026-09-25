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

from src.engine.attribution_evidence import attribution_evidence

logger = logging.getLogger(__name__)


#: 분해의 효과 컬럼. 커버리지는 이 **여섯**을 기준으로 잰다.
#: ★`cash_effect` 는 AL3 에서 갈라져 나왔다★ — 예전에는 현금이자가
#: `cost_effect` 에 더해져 "거래 비용" 으로 렌더됐다(부호도 성격도 반대인 둘).
#: ★`src/domain/daily_explanation.STRATEGY_DRIVERS` 와 **같아야 한다**★ —
#: `tests/test_daily_explanation.py:77` 이 대조한다.
EFFECT_COLUMNS = ("allocation_effect", "selection_effect", "macro_effect",
                  "netting_effect", "cost_effect", "cash_effect")

#: ★수익률 항등식의 드라이버★ (BH2) — 엔진의 실제 식이다:
#:     net_t = EW_t + alloc_t + cost_t (+ cash_t, realism)
#: `EW_t` 는 그날 전략 수익률의 단순평균(동일가중 기준), `alloc_t = Σ(w−1/n)·r`.
#: 워터폴·잔차는 **이것만** 더한다. ★`STRATEGY_DRIVERS` 와 같아야 한다★.
IDENTITY_DRIVERS = ("baseline_effect", "allocation_effect", "cost_effect",
                    "cash_effect")

#: ★보고 전용 — 수익률에 없는 것은 스텝이 아니다★ (BH2)
#: 예전 워터폴은 네팅을 '청산 효과' 스텝으로 더했고, 잔차가 정확히 그만큼 줄어
#: 차트는 닫혔다 — 틀렸을 때 오히려 자기일관적이었다.
REPORT_ONLY_EFFECTS = {
    "netting_effect": ("네팅은 보고 전용입니다 — 전략 보유로 잰 상쇄 절감이지만 수익률에 "
                       "더해지지 않습니다(엔진 계약). 워터폴의 스텝이 아닙니다."),
    "macro_effect": ("매크로 조정은 이미 최종 가중 안에 있어 배분 효과에 들어 있습니다 — "
                     "따로 더하면 이중 계산입니다. 배분 효과의 내역으로만 봅니다."),
    "selection_effect": ("멀티전략에서 전략 선택 효과는 정의되지 않습니다 — 각 전략 내부의 "
                         "선택은 동일가중 기준(전략 수익) 안에 들어 있고, Brinson 선택항에 "
                         "필요한 전략별 벤치마크가 저장소에 없습니다."),
}

#: 항등식 검사 허용오차(일별 수익률 단위). 저장이 float64 여야 의미가 있다 —
#: PostgreSQL 의 `REAL` 은 4바이트라 `schema_ddls` 가 `DOUBLE PRECISION` 으로 만든다.
IDENTITY_TOL = 1e-9

_CASH_NOT_MODELED = ("이 엔진에는 현금 이자 모델이 없습니다 — 수익률에도 들어 있지 않아 "
                     "항등식이 현금 없이 닫힙니다(미상이 아니라 없는 축입니다).")


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
            # ★어느 효과를 쟀고 어느 효과를 안 쟀나★ (AL4) — 커버리지는 *몇 행을
            # 봤나* 이고 이것은 *왜 값이 없나* 다. FX·국가는 결함이 아니라
            # 정의되지 않는 축이라 따로 실린다.
            "attribution_evidence":  attribution_evidence(cumulative),
            "waterfall":             waterfall,
            "monthly":               monthly,
            "quarterly":             quarterly,
            "regime_breakdown":      regime_breakdown,
            "strategy_contribution": strategy_contribution,
        }
        if include_daily:
            rows = self._daily_attribution(daily_df)
            # ★각 행이 스스로를 설명한다★ (AB4) — 기존 키는 하나도 바뀌지 않고
            # `explanation` 이 덧붙는다. 문장은 결정론적 템플릿이 만든다(LLM 아님).
            from src.engine.daily_explain_backtest import explain_backtest_day
            for row in rows:
                row["explanation"] = explain_backtest_day(
                    row, run_id=run_id).to_dict()
            result["daily_attribution"] = rows

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
        # ★이름은 전략 레지스트리에서 온다★ (BG5) — 예전에는 이 저장소에 없는
        # `strategies` 표를 읽어 조회가 늘 실패했고, 모든 전략의 이름이 사유와 함께
        # 비어 있었다(정직했지만 레지스트리가 복원된 지금은 사실이 옆에 있다).
        try:
            from src.engine.strategy_registry import StrategyRegistry
            reg = StrategyRegistry(self.engine)
            names = {}
            for sid in strategy_ids:
                s = reg.get(sid)
                if s is not None:
                    names[int(s["id"])] = s["name"]
            return names, None
        except Exception as e:
            return {}, f"전략명 조회에 실패했습니다 — {type(e).__name__}: {e}"

    @staticmethod
    def _identity_check(daily_df) -> dict:
        """★수익률 항등식을 데이터로 검증한다★ (BH2)

        일별 `gap = net − (EW + alloc + cost + cash_or_0)`. 세 필수 드라이버를 전부 아는
        행만 검사하고, 모든 행이 검사되고 최대 |gap| 이 허용오차 안일 때만 성립이다.
        현금이 한 행도 관측되지 않았는데 성립하면 현금은 **이 엔진에 없는 축**이다.
        """
        n = int(len(daily_df))
        if "baseline_effect" not in daily_df.columns or daily_df["baseline_effect"].isna().all():
            return {"holds": False, "max_abs_gap": None, "n_rows": n, "n_rows_checked": 0,
                    "not_modeled": [], "tolerance": IDENTITY_TOL,
                    "reason": ("동일가중 기준(EW) 이 저장되지 않은 실행입니다(BH2 이전) — "
                               "항등식을 검사할 수 없어 잔차를 설명하지 못합니다.")}
        need = ["baseline_effect", "allocation_effect", "cost_effect", "portfolio_return"]
        num = daily_df[need].apply(pd.to_numeric, errors="coerce")
        known = num.notna().all(axis=1)
        cash = (pd.to_numeric(daily_df["cash_effect"], errors="coerce")
                if "cash_effect" in daily_df.columns
                else pd.Series([np.nan] * n, index=daily_df.index, dtype=float))
        cash_known = cash.notna()
        sub = num[known]
        gap = (sub["portfolio_return"] - sub["baseline_effect"] - sub["allocation_effect"]
               - sub["cost_effect"] - cash[known].fillna(0.0))
        max_gap = float(gap.abs().max()) if len(gap) else None
        n_checked = int(known.sum())
        holds = (n_checked == n and n > 0 and max_gap is not None
                 and max_gap <= IDENTITY_TOL)
        # 현금이 전부 None 인데 닫히면 "없는 축", 일부만 있으면 미상이 섞인 것이다.
        not_modeled = ["cash_effect"] if (holds and not cash_known.any()) else []
        if holds:
            reason = None
        elif n_checked < n:
            reason = (f"{n - n_checked}/{n} 일에서 기준·배분·비용 중 하나가 미상이라 "
                      "항등식을 검사하지 못했습니다.")
        else:
            reason = (f"항등식이 닫히지 않습니다 — 최대 일별 차이 {max_gap:.3g}"
                      f"(허용 {IDENTITY_TOL:g}). 수익률에 드라이버 밖의 무엇이 들어 있습니다.")
        return {"holds": bool(holds), "max_abs_gap": max_gap, "n_rows": n,
                "n_rows_checked": n_checked, "not_modeled": not_modeled,
                "tolerance": IDENTITY_TOL, "reason": reason}

    @staticmethod
    def _cumulative_attribution(daily_df) -> dict:
        """누적 분해 — ★항등식을 검증하고, 수익률에 없는 것은 더하지 않는다★ (BH2)

        P4-a 에서 커버리지·잔차 명명을 세웠고(미상 ≠ 0), BH2 에서 **무엇을 더하는가**를
        고쳤다: 기준(EW) 을 0 으로 두고 수익률에 없는 네팅을 더하던 것을 버리고, 엔진의
        실제 식 `net = EW + alloc + cost (+ cash)` 만 더한다. 복리는 `∏(1+r)−1−Σr` 로
        **계산**한다 — 항등식이 성립하면 잔차는 그 복리 하나뿐이다.
        """
        if daily_df.empty:
            return {}

        cols = [*EFFECT_COLUMNS, "baseline_effect"]
        vals: dict[str, float | None] = {}
        coverage: dict[str, dict] = {}
        for col in cols:
            v, cov = sum_known(daily_df, col, scale=100.0)
            vals[col] = None if v is None else round(v, 6)
            coverage[col] = cov

        savings, savings_cov = sum_known(daily_df, "netting_savings")
        coverage["netting_savings"] = savings_cov

        actual_cum = (
            float(daily_df["cumulative_return"].iloc[-1])
            if "cumulative_return" in daily_df.columns
            and not pd.isna(daily_df["cumulative_return"].iloc[-1])
            else float((1 + daily_df["portfolio_return"]).prod() - 1) * 100
        )
        r = daily_df["portfolio_return"].astype(float)
        compounding = (float((1 + r).prod() - 1) - float(r.sum())) * 100

        identity = AttributionDecomposer._identity_check(daily_df)
        if identity["holds"]:
            # ★같은 재료로 잰다★ — 항등식이 닫히는 실행이면 실제 수익률도 일별 수익의
            # 곱으로 잰다(엔진의 `cumulative_return` 칸은 소수 4자리로 반올림돼 있다).
            actual_cum = float((1 + r).prod() - 1) * 100
        drivers = [c for c in IDENTITY_DRIVERS if c not in identity["not_modeled"]]
        known = [vals[c] for c in drivers if vals[c] is not None]
        sum_factors = float(sum(known))
        residual = actual_cum - sum_factors
        complete = identity["holds"]

        unexplained_reason = None if complete else identity["reason"]

        report_only = {c: {"value_pct": vals[c], "reason": why}
                       for c, why in REPORT_ONLY_EFFECTS.items()}

        return {
            "baseline_effect_pct":     vals["baseline_effect"],
            "allocation_effect_pct":   vals["allocation_effect"],
            "selection_effect_pct":    vals["selection_effect"],
            "macro_effect_pct":        vals["macro_effect"],
            "netting_effect_pct":      vals["netting_effect"],
            "cost_effect_pct":         vals["cost_effect"],
            # ★현금이자는 비용이 아니다★ (AL3) — 제 칸을 갖는다.
            "cash_effect_pct":         vals["cash_effect"],
            "cash_not_modeled_reason": (_CASH_NOT_MODELED
                                        if "cash_effect" in identity["not_modeled"] else None),
            # ★복리는 계산값이다★ — 항등식이 성립하면 잔차 = 이것(허용오차 안).
            "compounding_pct":         round(compounding, 9),
            # ★잔차는 항등식 성립 여부에 따라 이름이 다르다★ 둘 중 하나만 값을 갖는다.
            "interaction_pct":         (round(residual, 9) if complete else None),
            "unexplained_pct":         (None if complete else round(residual, 6)),
            "unexplained_reason":      unexplained_reason,
            "identity":                identity,
            "report_only":             report_only,
            "coverage":                coverage,
            "coverage_complete":       complete,
            # 값이 미상인 항등식 드라이버는 스텝을 만들 수 없다.
            "waterfall_omitted":       [c for c in drivers if vals[c] is None],
            "total_decomposed_pct":    round(sum_factors, 6),
            "actual_return_pct":       round(actual_cum, 6),
            "netting_savings_value":   (None if savings is None
                                        else float(round(savings, 2))),
        }

    @staticmethod
    def _build_waterfall(cum) -> list[dict]:
        """워터폴 — ★동일가중 기준에서 시작해 실제에서 닫힌다★ (BH2)

        `동일가중 기준 → 배분 → 비용 → (현금) → 복리 → 실제`. 항등식이 성립하면 복리는
        **계산된** 스텝이고 잔차는 허용오차 안이다. 성립하지 않으면 마지막 몫은
        "미설명 잔차" 이고 사유가 붙는다. ★수익률에 없는 네팅·매크로는 스텝이 아니다★.

        ★불변식★ 스텝 값은 `None` 이 아니다(프론트가 `toFixed` 를 부른다) · 잔차를 두 번
        세지 않는다(P4-a) · `kind` 는 프론트의 닫힌 유니온 안에서만.
        """
        if not cum:
            return []
        base = cum.get("baseline_effect_pct")
        # ★반올림은 표시에서만★ — 누적을 반올림한 값으로 이어 가면 스텝마다 오차가
        # 쌓여 마지막 스텝이 실제와 어긋난다(실측 1e-3).
        running = 0.0 if base is None else float(base)
        waterfall = [{
            "step": "Baseline",
            "label": "동일가중 기준" if base is not None else "기준 미상 — 0 에서 시작",
            "value": round(running, 3), "running_total": round(running, 3),
            "kind": "baseline",
        }]
        steps = [
            ("Allocation Effect", "배분 효과", cum.get("allocation_effect_pct")),
            ("Transaction Cost",  "거래 비용", cum.get("cost_effect_pct")),
        ]
        if not cum.get("cash_not_modeled_reason"):
            steps.append(("Cash Yield", "현금 이자", cum.get("cash_effect_pct")))
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

        complete = cum.get("coverage_complete", False)
        resid = (cum.get("interaction_pct") if complete
                 else cum.get("unexplained_pct"))
        if resid is not None and (abs(resid) > 1e-6 or not complete):
            running += resid
            waterfall.append({
                "step": "Compounding" if complete else "Unexplained",
                "label": "복리 효과" if complete else "미설명 잔차",
                "value": round(resid, 3),
                "running_total": round(running, 3),
                "kind": "interaction",
            })
        waterfall.append({
            "step": "Actual Total", "label": "실제 수익률",
            "value": round(cum["actual_return_pct"], 3),
            "running_total": round(cum["actual_return_pct"], 3), "kind": "total",
        })
        return waterfall

    @staticmethod
    def _aggregate_period(daily_df, freq) -> list[dict]:
        if daily_df.empty:
            return []
        df = daily_df.copy().set_index("trade_date")
        # ★동일가중 기준 칸★ (BH2) — 옛 실행엔 칸이 없다 → NaN(= 미상)으로 둔다.
        if "baseline_effect" not in df.columns:
            df["baseline_effect"] = np.nan
        # ★효과 칸에 `fillna(0)` 을 걸지 않는다★ (AL) — 걸면 "재지 않았다" 가
        # 월간 표에서 `0.0` 이 되어, 같은 실행을 누적 표와 월간 표가 **다르게**
        # 말한다. `sum(min_count=1)` 은 한 행도 못 보면 `NaN` 을 남긴다.
        _effects = [*EFFECT_COLUMNS, "baseline_effect"]
        for c in _effects:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        agg = df.groupby(pd.Grouper(freq=freq)).agg({
            "portfolio_return": "sum",
            **{c: (lambda x: x.sum(min_count=1)) for c in _effects},
            "netting_savings": "sum", "turnover_pct": "sum",
            "num_trades": "sum", "rebalanced": "sum",
        })
        for col in ("portfolio_return", "netting_savings", "turnover_pct",
                    "num_trades", "rebalanced"):
            agg[col] = agg[col].fillna(0)

        for col in ["portfolio_return", *_effects]:
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

            def _effect(v, d=3):
                """효과 칸 전용. ★미상은 `None` 으로 남는다★ (AL)

                `_safe` 는 `0.0` 을 낸다 — 거래량·회전율처럼 "없으면 0" 이 맞는
                칸에는 옳지만, 효과 칸에서는 **안 잰 것을 잰 0 으로** 만든다.
                프런트는 이 표를 아직 안 읽으므로 계약이 깨질 소비자는 없다.
                """
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    return None
                return None if (math.isnan(v) or math.isinf(v)) else round(v, d)

            result.append({
                "period":                str(period_end.date()),
                "portfolio_return_pct":  _safe(row.get("portfolio_return_compound", row["portfolio_return"])),
                "baseline_effect_pct":   _effect(row["baseline_effect"]),
                "allocation_effect_pct": _effect(row["allocation_effect"]),
                "selection_effect_pct":  _effect(row["selection_effect"]),
                "macro_effect_pct":      _effect(row["macro_effect"]),
                "netting_effect_pct":    _effect(row["netting_effect"]),
                "cost_effect_pct":       _effect(row["cost_effect"]),
                "cash_effect_pct":       _effect(row["cash_effect"]),
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
            sys_risk_mean = pd.to_numeric(subset["systemic_risk"], errors="coerce").mean()

            def _sum_pct(col):
                """★미상은 `None`★ (BH2) — 예전 `fillna(0).sum()` 은 안 잰 것을 0 으로 뒀다."""
                if col not in subset.columns:
                    return None
                v = pd.to_numeric(subset[col], errors="coerce").sum(min_count=1)
                return None if pd.isna(v) else round(float(v) * 100, 3)

            result.append({
                "regime": regime, "n_days": n,
                "n_days_pct": round(n/len(daily_df) * 100, 1),
                "annualized_return_pct": round(float(avg_ret * 252 * 100), 2),
                "volatility_pct": round(float(vol * np.sqrt(252) * 100), 2),
                "sharpe": sharpe,
                "sharpe_reason": sharpe_reason,
                "baseline_effect_pct": _sum_pct("baseline_effect"),
                "allocation_effect_pct": _sum_pct("allocation_effect"),
                "macro_effect_pct": _sum_pct("macro_effect"),
                "netting_effect_pct": _sum_pct("netting_effect"),
                "cost_effect_pct": _sum_pct("cost_effect"),
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
                    else (names_error or f"id {sid_int} 이 전략 레지스트리에 없습니다")),
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
        """일별 5효과. ★미상을 0 으로 접지 않는다★ (AB2)

        예전에는 `float(r[col] or 0)` 이었다 — 같은 파일의 누적 경로가
        `column_coverage`/`sum_known` 으로 정확히 피하고 있는 그 함정이다
        (*"`fillna(0)` 은 '안 본 행' 과 '0 인 행' 을 같은 자리에 쓴다"*).
        한 파일 안에서 한쪽만 규율 밖이었고, 소비자가 0 건이라 아무도 못 봤다.

        일일 설명 엔진(AB)이 **첫 소비자**다. 0 으로 접힌 값을 문장으로 만들면
        "배분 효과가 0 이었습니다" 라는 **없는 사실**을 말하게 되므로 여기서 막는다.

        각 행에 `coverage` 를 함께 낸다 — 설명이 잔차를 `interaction`(복리)과
        `unexplained`(복리+미관측 혼합) 중 무엇으로 부를지 가르는 근거다.
        """
        if daily_df.empty:
            return []

        def _num(v):
            """관측값이면 퍼센트로, 아니면 ★`None` 그대로★."""
            try:
                return None if v is None or pd.isna(v) else round(float(v) * 100, 9)
            except (TypeError, ValueError):
                return None

        # ★실행 단위로 현금 모델이 있는지 먼저 본다★ (BH2) — 항등식이 현금 없이
        # 닫히는 실행이면 현금은 그 날의 "미상" 이 아니라 **없는 축**이다.
        run_identity = AttributionDecomposer._identity_check(daily_df)
        not_modeled = list(run_identity["not_modeled"])
        drivers = [c for c in IDENTITY_DRIVERS if c not in not_modeled]

        out: list[dict] = []
        for _, r in daily_df.iterrows():
            effects = {c: _num(r[c] if c in r else None)
                       for c in (*EFFECT_COLUMNS, "baseline_effect")}
            missing = sorted(c for c in EFFECT_COLUMNS if effects[c] is None)
            total = _num(r["portfolio_return"])
            known_drivers = [effects[c] for c in drivers if effects[c] is not None]
            all_known = len(known_drivers) == len(drivers) and total is not None
            gap = (None if not all_known else round(total - sum(known_drivers), 9))
            out.append({
                "date": str(r["trade_date"].date()),
                "portfolio_return": total,
                **effects,
                "regime": r["regime"],
                # ★그 행에서 몇 축을 봤는가★ — 누적 경로의 `column_coverage` 와
                # 같은 것을 행 단위로 말한다(저장된 여섯 칸 기준).
                "coverage": {
                    "n_total": len(EFFECT_COLUMNS),
                    "n_known": len(EFFECT_COLUMNS) - len(missing),
                    "complete": not missing,
                    "missing": missing,
                },
                # ★그 날 항등식이 닫히는가★ (BH2) — 하루에는 복리가 없으므로 닫히면
                # 잔차는 부동소수 오차뿐이다(%p 단위, 허용 IDENTITY_TOL×100).
                "identity": {
                    "drivers": drivers,
                    "not_modeled": not_modeled,
                    "gap_pct": gap,
                    "closes": (gap is not None and abs(gap) <= IDENTITY_TOL * 100),
                },
            })
        return out
