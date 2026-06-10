"""
Multi-Source Feature Engineering for AI Volatility Prediction
==============================================================
Expands beyond simple rolling-vol sequences to include:

Technical Indicators:
  - RSI (Relative Strength Index) — momentum / overbought-oversold
  - MACD (Moving Average Convergence Divergence) — trend/momentum
  - Bollinger Band position — mean-reversion signal
  - ATR (Average True Range) — volatility proxy
  - Stochastic Oscillator — momentum

Volume & Market Context:
  - Volume change & volume-price ratio
  - On-Balance Volume (OBV)
  - VIX level & change — market-wide fear index

Returns statistics:
  - Multi-window realized vol (5/20/60 day)
  - Rolling skewness & kurtosis — tail risk features
  - Return autocorrelation lag-1

Reference: FRM Part II — ML for risk management; Lopez de Prado
"""


import numpy as np
import pandas as pd


class FeatureEngineer:
    """
    Compute a comprehensive feature matrix from OHLCV + VIX data.

    Input: DataFrame with columns [Open, High, Low, Close, Volume]
           (AdjClose optional; VIX series optional)
    Output: Feature matrix + target (next-period realized volatility)
    """

    def __init__(
        self,
        ohlcv: pd.DataFrame,
        vix: pd.Series | None = None,
        vol_window: int = 20,
    ):
        self.ohlcv = ohlcv.copy()
        self.vix = vix
        self.vol_window = vol_window
        # Compute log returns once
        self.returns = np.log(self.ohlcv["Close"] / self.ohlcv["Close"].shift(1))

    # ─── Technical Indicators ────────────────────────────────────────────────

    def rsi(self, period: int = 14) -> pd.Series:
        """
        Relative Strength Index.
        RSI = 100 − 100 / (1 + RS),  RS = avg_gain / avg_loss
        """
        delta = self.ohlcv["Close"].diff()
        gains = delta.where(delta > 0, 0.0)
        losses = -delta.where(delta < 0, 0.0)
        avg_gain = gains.rolling(period).mean()
        avg_loss = losses.rolling(period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return (100 - 100 / (1 + rs)).fillna(50)

    def macd(
        self, fast: int = 12, slow: int = 26, signal: int = 9,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """
        MACD = EMA_fast − EMA_slow
        Signal = EMA_signal(MACD)
        Histogram = MACD − Signal
        """
        close = self.ohlcv["Close"]
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        hist = macd_line - signal_line
        return macd_line, signal_line, hist

    def bollinger_position(self, period: int = 20, n_std: float = 2.0) -> pd.Series:
        """
        Position within Bollinger Bands, normalised to [-1, 1].
        0 = at MA, +1 = at upper band, -1 = at lower band.
        """
        close = self.ohlcv["Close"]
        ma = close.rolling(period).mean()
        sd = close.rolling(period).std()
        upper = ma + n_std * sd
        lower = ma - n_std * sd
        width = upper - lower
        position = (close - ma) / (width / 2).replace(0, np.nan)
        return position.clip(-2, 2).fillna(0)

    def atr(self, period: int = 14) -> pd.Series:
        """
        Average True Range — volatility measure based on price ranges.
        TR = max(H−L, |H−C_prev|, |L−C_prev|)
        """
        high = self.ohlcv["High"]
        low = self.ohlcv["Low"]
        close_prev = self.ohlcv["Close"].shift(1)
        tr = pd.concat([
            high - low,
            (high - close_prev).abs(),
            (low - close_prev).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def stochastic_oscillator(self, period: int = 14) -> pd.Series:
        """Stochastic %K = 100 × (C − L_n) / (H_n − L_n)"""
        high_n = self.ohlcv["High"].rolling(period).max()
        low_n = self.ohlcv["Low"].rolling(period).min()
        k = 100 * (self.ohlcv["Close"] - low_n) / (high_n - low_n).replace(0, np.nan)
        return k.fillna(50)

    # ─── Volume Features ─────────────────────────────────────────────────────

    def volume_change(self) -> pd.Series:
        """Log change in volume."""
        return np.log(self.ohlcv["Volume"] / self.ohlcv["Volume"].shift(1)).fillna(0)

    def volume_ratio(self, period: int = 20) -> pd.Series:
        """Current volume relative to its rolling average."""
        avg_vol = self.ohlcv["Volume"].rolling(period).mean()
        return (self.ohlcv["Volume"] / avg_vol).fillna(1)

    def obv(self) -> pd.Series:
        """On-Balance Volume: cumulative signed volume."""
        direction = np.sign(self.ohlcv["Close"].diff().fillna(0))
        signed_vol = direction * self.ohlcv["Volume"]
        return signed_vol.cumsum()

    def obv_change(self, period: int = 10) -> pd.Series:
        """OBV rate of change — normalised momentum."""
        obv = self.obv()
        return (obv - obv.shift(period)) / obv.shift(period).abs().replace(0, np.nan)

    # ─── Return Statistics ───────────────────────────────────────────────────

    def realized_vol(self, window: int) -> pd.Series:
        """Rolling realized volatility."""
        return self.returns.rolling(window).std()

    def rolling_skewness(self, window: int = 20) -> pd.Series:
        """Rolling return skewness — asymmetric tail indicator."""
        return self.returns.rolling(window).skew().fillna(0)

    def rolling_kurtosis(self, window: int = 20) -> pd.Series:
        """Rolling return excess kurtosis — fat tail indicator."""
        return self.returns.rolling(window).kurt().fillna(0)

    def return_autocorrelation(self, lag: int = 1, window: int = 20) -> pd.Series:
        """Rolling lag-1 autocorrelation of returns — momentum / mean reversion signal."""
        return self.returns.rolling(window).apply(
            lambda x: x.autocorr(lag=lag) if len(x) > lag else 0,
            raw=False,
        ).fillna(0)

    # ─── VIX Features ────────────────────────────────────────────────────────

    def vix_features(self) -> pd.DataFrame:
        """VIX level and change features, aligned to ohlcv index."""
        if self.vix is None or self.vix.empty:
            empty = pd.DataFrame(index=self.ohlcv.index)
            empty["vix_level"] = 20.0  # neutral default
            empty["vix_change"] = 0.0
            empty["vix_ma_ratio"] = 1.0
            return empty

        vix_aligned = self.vix.reindex(self.ohlcv.index).ffill()
        vix_change = vix_aligned.pct_change().fillna(0)
        vix_ma = vix_aligned.rolling(20).mean()
        vix_ma_ratio = (vix_aligned / vix_ma).fillna(1)

        return pd.DataFrame({
            "vix_level": vix_aligned,
            "vix_change": vix_change,
            "vix_ma_ratio": vix_ma_ratio,
        })

    # ─── Master Feature Matrix ───────────────────────────────────────────────

    def build_feature_matrix(self) -> pd.DataFrame:
        """
        Assemble all features into a single aligned DataFrame.

        Feature categories (14 total):
          Price momentum:  rsi, macd, macd_signal, macd_hist, boll_position, stoch
          Volatility:      vol_5d, vol_20d, vol_60d, atr_norm
          Higher moments:  skew, kurt
          Return autocorr: ret_autocorr
          Volume:          vol_change, vol_ratio, obv_change
          Market context:  vix_level, vix_change, vix_ma_ratio
        """
        close = self.ohlcv["Close"]
        macd_line, macd_sig, macd_hist = self.macd()

        features = pd.DataFrame(index=self.ohlcv.index)
        # Price momentum
        features["rsi"] = self.rsi() / 100.0
        features["macd"] = macd_line / close
        features["macd_signal"] = macd_sig / close
        features["macd_hist"] = macd_hist / close
        features["boll_position"] = self.bollinger_position()
        features["stoch"] = self.stochastic_oscillator() / 100.0
        # Volatility measures
        features["vol_5d"] = self.realized_vol(5)
        features["vol_20d"] = self.realized_vol(20)
        features["vol_60d"] = self.realized_vol(60)
        features["atr_norm"] = self.atr() / close
        # Higher moments
        features["skew"] = self.rolling_skewness()
        features["kurt"] = self.rolling_kurtosis()
        features["ret_autocorr"] = self.return_autocorrelation()
        # Volume
        features["vol_change"] = self.volume_change()
        features["vol_ratio"] = self.volume_ratio()
        features["obv_change"] = self.obv_change().fillna(0)
        # VIX context
        vix_df = self.vix_features()
        features["vix_level"] = vix_df["vix_level"] / 100.0  # scale
        features["vix_change"] = vix_df["vix_change"]
        features["vix_ma_ratio"] = vix_df["vix_ma_ratio"]

        return features.replace([np.inf, -np.inf], np.nan).fillna(0)

    def build_training_set(
        self, forecast_horizon: int = 1,
    ) -> tuple[pd.DataFrame, pd.Series]:
        """
        Build X, y for supervised learning.

        X: feature matrix (one row per day)
        y: next-period realized volatility (target)
        """
        features = self.build_feature_matrix()
        target = self.realized_vol(self.vol_window).shift(-forecast_horizon)

        # Drop rows where target is NaN (end of series) or features all zero (start)
        aligned = pd.concat([features, target.rename("target")], axis=1).dropna()
        return aligned[features.columns], aligned["target"]

    def feature_names(self) -> list[str]:
        """Return the list of feature column names."""
        return list(self.build_feature_matrix().columns)


# ═══════════════════════════════════════════════════════════════════════════════
# Multi-Feature AI Engine (Random Forest + Feature Importance)
# ═══════════════════════════════════════════════════════════════════════════════

from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.preprocessing import StandardScaler


class MultiFeatureVolatilityEngine:
    """
    Expanded AI engine that uses the full FeatureEngineer output.

    Supports Random Forest or Gradient Boosting, with feature importance.
    """

    def __init__(
        self,
        ohlcv: pd.DataFrame,
        vix: pd.Series | None = None,
        vol_window: int = 20,
        model_type: str = "random_forest",  # or "gradient_boosting"
        n_estimators: int = 200,
        seed: int = 42,
    ):
        self.fe = FeatureEngineer(ohlcv, vix=vix, vol_window=vol_window)
        self.vol_window = vol_window
        self.scaler = StandardScaler()
        self.model_type = model_type

        if model_type == "gradient_boosting":
            self.model = GradientBoostingRegressor(
                n_estimators=n_estimators, random_state=seed,
                max_depth=4, learning_rate=0.05,
            )
        else:
            self.model = RandomForestRegressor(
                n_estimators=n_estimators, random_state=seed,
                n_jobs=-1, max_depth=8,
            )

        self._trained = False
        self._feature_names: list[str] = []
        self._last_features: pd.DataFrame | None = None

    def train(self, test_ratio: float = 0.2) -> dict:
        """Train model and return performance metrics."""
        X, y = self.fe.build_training_set()
        if len(X) < 60:
            return {"error": "Not enough data to train (need 60+ rows)"}

        self._feature_names = list(X.columns)
        self._last_features = X

        # Chronological split
        split = int(len(X) * (1 - test_ratio))
        X_tr, X_te = X.iloc[:split], X.iloc[split:]
        y_tr, y_te = y.iloc[:split], y.iloc[split:]

        X_tr_s = self.scaler.fit_transform(X_tr.values)
        X_te_s = self.scaler.transform(X_te.values)

        self.model.fit(X_tr_s, y_tr)
        self._trained = True

        preds = self.model.predict(X_te_s)
        rmse = float(np.sqrt(mean_squared_error(y_te, preds)))
        mae = float(mean_absolute_error(y_te, preds))

        # Directional accuracy
        y_te_change = np.diff(y_te.values)
        pred_change = np.diff(preds)
        dir_acc = float(np.mean(np.sign(y_te_change) == np.sign(pred_change))) \
            if len(y_te_change) > 0 else 0.0

        # Feature importance
        importances = self.feature_importance()

        return {
            "model_type": self.model_type,
            "n_features": len(self._feature_names),
            "feature_names": self._feature_names,
            "rmse": round(rmse, 8),
            "mae": round(mae, 8),
            "directional_accuracy": round(dir_acc, 4),
            "train_samples": int(len(X_tr)),
            "test_samples": int(len(X_te)),
            "top_features": importances[:5],
            "all_importances": importances,
        }

    def feature_importance(self) -> list[dict]:
        """Rank features by importance, descending."""
        if not self._trained:
            return []
        importances = self.model.feature_importances_
        ranking = sorted(
            zip(self._feature_names, importances),
            key=lambda x: x[1], reverse=True,
        )
        return [
            {"feature": name, "importance": round(float(imp), 6)}
            for name, imp in ranking
        ]

    def predict_next(self) -> float:
        """Predict next-period volatility using the last feature row."""
        if not self._trained:
            self.train()
        features = self.fe.build_feature_matrix()
        last_row = features.iloc[-1:]
        last_s = self.scaler.transform(last_row.values)
        return float(self.model.predict(last_s)[0])

    def predict_var(self, portfolio_value: float, confidence_level: float = 0.99) -> float:
        from scipy.stats import norm
        vol = self.predict_next()
        z = norm.ppf(confidence_level)
        return float(portfolio_value * vol * z)
