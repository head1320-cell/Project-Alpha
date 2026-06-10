"""
AI Volatility Prediction Engine
- Random Forest regression for next-day volatility forecasting
- Feature engineering from realized volatility history
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


class AIVolatilityEngine:
    def __init__(self, returns: pd.Series, window: int = 20):
        self.returns = returns.dropna()
        self.window  = window
        self.model   = RandomForestRegressor(n_estimators=150, random_state=42, n_jobs=-1)
        self.scaler  = StandardScaler()
        self._trained = False

    def _build_features(self) -> tuple:
        """Construct feature matrix from rolling volatility windows."""
        vol = self.returns.rolling(self.window).std().dropna()
        X, y = [], []
        for i in range(len(vol) - self.window):
            X.append(vol.iloc[i: i + self.window].values)
            y.append(vol.iloc[i + self.window])
        return np.array(X), np.array(y)

    def train(self) -> dict:
        X, y = self._build_features()
        if len(X) < 30:
            return {"error": "Not enough data to train (need 30+ periods)"}

        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, shuffle=False)
        X_tr_s = self.scaler.fit_transform(X_tr)
        X_te_s = self.scaler.transform(X_te)

        self.model.fit(X_tr_s, y_tr)
        self._trained = True

        preds = self.model.predict(X_te_s)
        rmse  = float(np.sqrt(mean_squared_error(y_te, preds)))
        return {"rmse": round(rmse, 6), "train_samples": len(X_tr)}

    def predict_next(self) -> float:
        """Predict next-period volatility. Auto-trains if needed."""
        if not self._trained:
            self.train()
        vol = self.returns.rolling(self.window).std().dropna()
        last = vol.iloc[-self.window:].values.reshape(1, -1)
        last_s = self.scaler.transform(last)
        return float(self.model.predict(last_s)[0])

    def predict_var(self, portfolio_value: float,
                    confidence_level: float = 0.99) -> float:
        """Convert predicted volatility to a VaR dollar amount."""
        from scipy.stats import norm
        vol = self.predict_next()
        z   = norm.ppf(confidence_level)
        return portfolio_value * vol * z

    def volatility_regime(self, lookback: int = 60) -> str:
        """Classify current volatility regime."""
        recent = self.returns.rolling(20).std().dropna()
        hist   = self.returns.rolling(lookback).std().dropna()
        if len(recent) == 0 or len(hist) == 0:
            return "unknown"
        ratio = recent.iloc[-1] / hist.mean()
        if ratio > 1.5:
            return "HIGH"
        elif ratio < 0.7:
            return "LOW"
        return "NORMAL"
