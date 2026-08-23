"""
AI Model Monitoring & Drift Detection
=====================================
Tracks production AI model health over time.

Capabilities:
  1. Walk-forward backtest — predictions vs realized volatility
  2. Rolling error decay — is the model getting worse?
  3. Feature drift — input distribution shift (PSI, KS test)
  4. Prediction drift — output distribution shift
  5. Concept drift — target relationship change (error autocorrelation)
  6. Alert generation — RETRAIN / MONITOR / HEALTHY

Reference:
  - Population Stability Index (PSI) — standard MLOps drift metric
  - Kolmogorov-Smirnov test — distribution shift
  - FRM Part II: model validation, performance decay
"""


import numpy as np
import pandas as pd
from scipy.stats import ks_2samp
from sklearn.metrics import mean_absolute_error, mean_squared_error

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Drift Detection Metrics
# ═══════════════════════════════════════════════════════════════════════════════

def population_stability_index(
    expected: np.ndarray,
    actual: np.ndarray,
    n_bins: int = 10,
) -> float:
    """
    Population Stability Index — standard drift metric.

    PSI = Σ (A% − E%) × ln(A% / E%)

    Thresholds:
      PSI < 0.10 → no significant shift
      0.10 ≤ PSI < 0.25 → moderate shift, monitor
      PSI ≥ 0.25 → significant shift, retrain
    """
    expected = expected[np.isfinite(expected)]
    actual = actual[np.isfinite(actual)]
    if len(expected) < 10 or len(actual) < 10:
        return 0.0

    # Use expected distribution to define bin edges (quantile-based)
    quantiles = np.linspace(0, 1, n_bins + 1)
    edges = np.quantile(expected, quantiles)
    edges[0] = -np.inf
    edges[-1] = np.inf
    edges = np.unique(edges)
    if len(edges) < 3:
        return 0.0

    e_counts, _ = np.histogram(expected, bins=edges)
    a_counts, _ = np.histogram(actual, bins=edges)

    e_pct = e_counts / e_counts.sum()
    a_pct = a_counts / a_counts.sum()

    # Smooth zeros to avoid log(0)
    eps = 1e-4
    e_pct = np.maximum(e_pct, eps)
    a_pct = np.maximum(a_pct, eps)

    psi = np.sum((a_pct - e_pct) * np.log(a_pct / e_pct))
    return float(psi)


def psi_classification(psi: float) -> tuple[str, str]:
    """Classify PSI level into (severity, color)."""
    if psi < 0.10:
        return "NO_SHIFT", "green"
    elif psi < 0.25:
        return "MODERATE_SHIFT", "amber"
    else:
        return "SIGNIFICANT_SHIFT", "red"


def ks_drift_test(
    reference: np.ndarray,
    current: np.ndarray,
) -> dict:
    """
    Kolmogorov-Smirnov test for distribution shift.

    H0: reference and current come from the same distribution.
    Low p-value → reject H0 → distributions differ (drift).
    """
    ref = reference[np.isfinite(reference)]
    cur = current[np.isfinite(current)]
    if len(ref) < 10 or len(cur) < 10:
        return {"ks_stat": 0.0, "p_value": 1.0, "drift_detected": False}

    stat, p_val = ks_2samp(ref, cur)
    return {
        "ks_stat": round(float(stat), 6),
        "p_value": round(float(p_val), 6),
        "drift_detected": bool(p_val < 0.05),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Model Monitor
# ═══════════════════════════════════════════════════════════════════════════════

class ModelMonitor:
    """
    Walk-forward model monitoring for volatility forecasters.

    Workflow:
      1. Initial training on first N points
      2. For each step t in the hold-out: predict t+1, move window forward
      3. Refit every `refit_every` steps (expanding or rolling window)
      4. Compare predictions to actual realized vols
      5. Compute drift metrics on features and predictions

    Two engines supported:
      - AIVolatilityEngine (RF, sequence-based) — default
      - MultiFeatureVolatilityEngine (technical indicator features)
    """

    def __init__(
        self,
        ohlcv: pd.DataFrame,
        returns: pd.Series,
        vix: pd.Series | None = None,
        vol_window: int = 20,
        initial_train_ratio: float = 0.6,
        refit_every: int = 20,
        engine_type: str = "multi_feature",   # "rf_seq" or "multi_feature"
    ):
        self.ohlcv = ohlcv
        self.returns = returns.dropna()
        self.vix = vix
        self.vol_window = vol_window
        self.initial_train_ratio = initial_train_ratio
        self.refit_every = refit_every
        self.engine_type = engine_type

        # Compute realized vol series (the target) once
        self.realized_vol = self.returns.rolling(vol_window).std().dropna()

    # ─── Walk-Forward Backtest ───────────────────────────────────────────────

    def walk_forward_backtest(self) -> dict:
        """
        Walk-forward predictions vs realized volatility.

        Refit every `refit_every` days to simulate production retraining.
        """
        from src.models.ai_engine import AIVolatilityEngine
        from src.models.feature_engine import MultiFeatureVolatilityEngine

        vol = self.realized_vol
        n = len(vol)
        if n < 120:
            return {"error": "Not enough data for walk-forward (need 120+ rows)"}

        split_idx = int(n * self.initial_train_ratio)
        predictions = []
        actuals = []
        dates = []

        current_idx = split_idx
        while current_idx < n - 1:
            # Train up to current_idx
            if self.engine_type == "multi_feature":
                # Use ohlcv up to date of current_idx
                end_date = vol.index[current_idx]
                ohlcv_train = self.ohlcv.loc[:end_date]
                vix_train = self.vix.loc[:end_date] if self.vix is not None else None
                try:
                    eng = MultiFeatureVolatilityEngine(
                        ohlcv_train, vix=vix_train, vol_window=self.vol_window,
                    )
                    eng.train()
                except Exception:
                    break
            else:
                returns_train = self.returns.loc[:vol.index[current_idx]]
                try:
                    eng = AIVolatilityEngine(returns_train, window=self.vol_window)
                    eng.train()
                except Exception:
                    break

            # Predict next `refit_every` days (or until end)
            batch_end = min(current_idx + self.refit_every, n - 1)
            for t in range(current_idx, batch_end):
                try:
                    pred = eng.predict_next()
                except Exception:
                    pred = np.nan
                actual = vol.iloc[t + 1]
                predictions.append(pred)
                actuals.append(float(actual))
                dates.append(
                    vol.index[t + 1].strftime("%Y-%m-%d")
                    if hasattr(vol.index, "strftime")
                    else t + 1
                )

            current_idx = batch_end

        if len(predictions) == 0:
            return {"error": "Backtest produced no predictions"}

        preds_arr = np.array(predictions)
        actuals_arr = np.array(actuals)

        # Drop any NaN predictions
        mask = np.isfinite(preds_arr) & np.isfinite(actuals_arr)
        preds_arr = preds_arr[mask]
        actuals_arr = actuals_arr[mask]
        clean_dates = [d for i, d in enumerate(dates) if mask[i]]

        errors = preds_arr - actuals_arr

        # Overall metrics
        rmse = float(np.sqrt(mean_squared_error(actuals_arr, preds_arr)))
        mae = float(mean_absolute_error(actuals_arr, preds_arr))
        bias = float(np.mean(errors))
        corr = float(np.corrcoef(preds_arr, actuals_arr)[0, 1]) \
            if len(preds_arr) > 1 else 0.0

        # Directional accuracy
        actual_changes = np.diff(actuals_arr)
        pred_changes = np.diff(preds_arr)
        dir_acc = float(np.mean(np.sign(actual_changes) == np.sign(pred_changes))) \
            if len(actual_changes) > 0 else 0.0

        # Rolling RMSE to detect performance decay
        rolling_window = max(10, len(errors) // 10)
        rolling_rmse = []
        for i in range(rolling_window, len(errors)):
            w_errors = errors[i - rolling_window:i]
            rolling_rmse.append(float(np.sqrt(np.mean(w_errors**2))))

        # Early vs late comparison for decay detection
        n_half = len(errors) // 2
        if n_half > 10:
            early_rmse = float(np.sqrt(np.mean(errors[:n_half]**2)))
            late_rmse = float(np.sqrt(np.mean(errors[n_half:]**2)))
            rmse_decay_pct = (late_rmse - early_rmse) / early_rmse * 100 \
                if early_rmse > 0 else 0
        else:
            early_rmse = rmse
            late_rmse = rmse
            rmse_decay_pct = 0.0

        return {
            "n_predictions": int(len(preds_arr)),
            "rmse": round(rmse, 8),
            "mae": round(mae, 8),
            "bias": round(bias, 8),
            "correlation": round(corr, 4),
            "directional_accuracy": round(dir_acc, 4),
            "early_half_rmse": round(early_rmse, 8),
            "late_half_rmse": round(late_rmse, 8),
            "rmse_decay_pct": round(rmse_decay_pct, 2),
            "predictions": [round(float(p), 8) for p in preds_arr],
            "actuals": [round(float(a), 8) for a in actuals_arr],
            "errors": [round(float(e), 8) for e in errors],
            "dates": clean_dates,
            "rolling_rmse": [round(r, 8) for r in rolling_rmse],
            "rolling_window": rolling_window,
        }

    # ─── Drift Detection ─────────────────────────────────────────────────────

    def feature_drift(self) -> dict:
        """
        Compute PSI and KS-test for each feature between reference period
        (first half) and current period (second half).
        """
        from src.models.feature_engine import FeatureEngineer

        fe = FeatureEngineer(self.ohlcv, vix=self.vix, vol_window=self.vol_window)
        features = fe.build_feature_matrix()

        n = len(features)
        if n < 100:
            return {"error": "Not enough data for drift detection"}

        split = n // 2
        reference = features.iloc[:split]
        current = features.iloc[split:]

        results = []
        any_significant = False
        max_psi = 0.0

        for col in features.columns:
            psi = population_stability_index(
                reference[col].values, current[col].values
            )
            ks = ks_drift_test(reference[col].values, current[col].values)
            severity, _ = psi_classification(psi)

            if psi > max_psi:
                max_psi = psi
            if severity == "SIGNIFICANT_SHIFT":
                any_significant = True

            results.append({
                "feature": col,
                "psi": round(psi, 6),
                "severity": severity,
                "ks_stat": ks["ks_stat"],
                "ks_p_value": ks["p_value"],
                "ks_drift": ks["drift_detected"],
            })

        # Sort by PSI descending
        results.sort(key=lambda r: r["psi"], reverse=True)

        return {
            "max_psi": round(max_psi, 6),
            "max_psi_severity": psi_classification(max_psi)[0],
            "any_significant_drift": bool(any_significant),
            "reference_period_size": int(len(reference)),
            "current_period_size": int(len(current)),
            "n_features": len(results),
            "feature_drifts": results,
        }

    def prediction_drift(self, backtest_result: dict) -> dict:
        """
        Compare prediction distributions between first and second halves.

        If predictions drift but actuals don't → model is unstable.
        If both drift similarly → the underlying is regime-changing.
        """
        preds = np.array(backtest_result.get("predictions", []))
        actuals = np.array(backtest_result.get("actuals", []))

        if len(preds) < 40:
            return {"error": "Not enough predictions for drift test"}

        n_half = len(preds) // 2
        pred_psi = population_stability_index(preds[:n_half], preds[n_half:])
        actual_psi = population_stability_index(actuals[:n_half], actuals[n_half:])
        pred_ks = ks_drift_test(preds[:n_half], preds[n_half:])
        actual_ks = ks_drift_test(actuals[:n_half], actuals[n_half:])

        # Interpretation
        if pred_psi > 0.25 and actual_psi < 0.10:
            interp = "모델 예측은 흐르지만 실현 변동성은 안정 → 모델 불안정, 재학습 필요"
        elif pred_psi > 0.25 and actual_psi > 0.25:
            interp = "예측/실현 모두 드리프트 → 시장 레짐 변화, 모델 재학습 + 피처 재검토 필요"
        elif pred_psi < 0.10 and actual_psi < 0.10:
            interp = "양쪽 모두 안정 → 모델 건강"
        else:
            interp = "부분 드리프트 → 계속 모니터링"

        return {
            "prediction_psi": round(pred_psi, 6),
            "actual_psi": round(actual_psi, 6),
            "prediction_ks": pred_ks,
            "actual_ks": actual_ks,
            "interpretation": interp,
        }

    def error_autocorrelation(self, backtest_result: dict, lag: int = 5) -> dict:
        """
        High error autocorrelation → systematic bias (concept drift).
        Healthy models have near-zero error autocorrelation.
        """
        errors = np.array(backtest_result.get("errors", []))
        if len(errors) < lag + 10:
            return {"error": "Not enough errors for autocorrelation"}

        err_series = pd.Series(errors)
        autocorrs = [
            float(err_series.autocorr(lag=k))
            for k in range(1, lag + 1)
        ]

        # Mean absolute autocorrelation: < 0.1 good, > 0.3 concerning
        mean_abs_ac = float(np.mean(np.abs(autocorrs)))

        if mean_abs_ac < 0.10:
            severity = "LOW"
            interp = "에러 자기상관 낮음 → 모델 건강"
        elif mean_abs_ac < 0.30:
            severity = "MODERATE"
            interp = "에러에 약한 패턴 존재 → 피처 누락 가능성"
        else:
            severity = "HIGH"
            interp = "에러 자기상관 큼 → 컨셉 드리프트, 재학습 권장"

        return {
            "autocorrelations": [round(a, 4) for a in autocorrs],
            "mean_abs_autocorr": round(mean_abs_ac, 4),
            "severity": severity,
            "interpretation": interp,
        }

    # ─── Overall Health Status ──────────────────────────────────────────────

    @staticmethod
    def overall_health_status(
        backtest: dict,
        feature_drift: dict,
        prediction_drift: dict,
        error_autocorr: dict,
    ) -> dict:
        """
        Aggregate signals into a single health status:
          HEALTHY / MONITOR / RETRAIN / CRITICAL
        """
        flags = []

        # RMSE decay check
        decay = backtest.get("rmse_decay_pct", 0)
        if decay > 50:
            flags.append(("CRITICAL", f"RMSE {decay:.0f}% 증가"))
        elif decay > 20:
            flags.append(("MONITOR", f"RMSE {decay:.0f}% 증가"))

        # Feature drift
        if feature_drift.get("any_significant_drift"):
            flags.append(("RETRAIN", "피처 분포 유의 변화 (PSI > 0.25)"))
        elif feature_drift.get("max_psi", 0) > 0.10:
            flags.append(("MONITOR", f"최대 PSI {feature_drift['max_psi']:.2f}"))

        # Prediction drift
        pred_psi = prediction_drift.get("prediction_psi", 0)
        if pred_psi > 0.25:
            flags.append(("RETRAIN", f"예측 분포 이동 (PSI {pred_psi:.2f})"))

        # Error autocorrelation
        if error_autocorr.get("severity") == "HIGH":
            flags.append(("RETRAIN", "에러 자기상관 큼"))
        elif error_autocorr.get("severity") == "MODERATE":
            flags.append(("MONITOR", "에러에 약한 패턴"))

        # Directional accuracy
        dir_acc = backtest.get("directional_accuracy", 0)
        if dir_acc < 0.40:
            flags.append(("CRITICAL", f"방향 정확도 {dir_acc:.1%} 매우 낮음"))
        elif dir_acc < 0.50:
            flags.append(("MONITOR", f"방향 정확도 {dir_acc:.1%}"))

        # Correlation with actual
        corr = backtest.get("correlation", 0)
        if corr < 0.20:
            flags.append(("CRITICAL", f"예측-실현 상관 {corr:.2f} 낮음"))
        elif corr < 0.40:
            flags.append(("MONITOR", f"예측-실현 상관 {corr:.2f}"))

        # Aggregate
        severities = [f[0] for f in flags]
        if "CRITICAL" in severities:
            status = "CRITICAL"
        elif "RETRAIN" in severities:
            status = "RETRAIN"
        elif "MONITOR" in severities:
            status = "MONITOR"
        else:
            status = "HEALTHY"

        return {
            "status": status,
            "n_flags": len(flags),
            "flags": [{"severity": f[0], "message": f[1]} for f in flags],
        }

    # ─── Full Report ────────────────────────────────────────────────────────

    def full_report(self) -> dict:
        """Run all monitoring checks and return a consolidated report."""
        backtest = self.walk_forward_backtest()
        if "error" in backtest:
            return {"error": backtest["error"]}

        feature_drift = self.feature_drift()
        prediction_drift = self.prediction_drift(backtest)
        error_autocorr = self.error_autocorrelation(backtest)
        health = self.overall_health_status(
            backtest, feature_drift, prediction_drift, error_autocorr,
        )

        return {
            "health_status": health,
            "backtest": backtest,
            "feature_drift": feature_drift,
            "prediction_drift": prediction_drift,
            "error_autocorrelation": error_autocorr,
            "config": {
                "engine_type": self.engine_type,
                "vol_window": self.vol_window,
                "initial_train_ratio": self.initial_train_ratio,
                "refit_every": self.refit_every,
            },
        }
