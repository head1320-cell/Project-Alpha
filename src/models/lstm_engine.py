"""
LSTM Volatility Forecasting Engine
===================================
Sequential neural network for next-period volatility prediction.

Runs in parallel with the existing Random Forest engine for head-to-head
comparison. LSTM captures long-range temporal dependencies that RF misses.

Architecture:
  - 2-layer LSTM (hidden=32)
  - Dropout 0.2
  - Linear output layer
  - MSE loss, Adam optimiser, early stopping

Reference: FRM Part II — AI/ML applications in risk management

Comparison framework:
  - RMSE, MAE on hold-out set
  - Directional accuracy (vol regime prediction)
  - Prediction variance (stability)
  - Training time trade-off
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.preprocessing import StandardScaler

# torch는 선택적 의존성 — 없으면 LSTM 기능만 비활성, 나머지 플랫폼은 정상 작동
try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
    TORCH_AVAILABLE = True
    _TorchModuleBase = nn.Module
except ImportError:
    TORCH_AVAILABLE = False
    torch = None  # type: ignore
    nn = None  # type: ignore
    DataLoader = TensorDataset = None  # type: ignore
    _TorchModuleBase = object  # nn.Module 대체 (클래스 정의가 깨지지 않도록)


def _require_torch():
    """LSTM 기능 호출 시 torch 설치 여부 확인."""
    if not TORCH_AVAILABLE:
        raise RuntimeError(
            "LSTM 기능을 사용하려면 torch가 필요합니다. "
            "`pip install torch`로 설치하세요. (나머지 플랫폼 기능은 torch 없이 작동합니다)"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. LSTM Model Architecture
# ═══════════════════════════════════════════════════════════════════════════════

class LSTMVolNet(_TorchModuleBase):
    """
    LSTM → Dropout → Dense
    Input: (batch, seq_len, n_features)
    Output: next-period volatility prediction
    """
    def __init__(
        self,
        input_size: int = 1,
        hidden_size: int = 32,
        num_layers: int = 2,
        dropout: float = 0.2,
    ):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0.0,
            batch_first=True,
        )
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        last = out[:, -1, :]        # final time-step
        last = self.dropout(last)
        return self.fc(last).squeeze(-1)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. LSTM Volatility Engine
# ═══════════════════════════════════════════════════════════════════════════════

class LSTMVolatilityEngine:
    """
    LSTM-based volatility forecasting engine.

    Mirrors the Random Forest engine API for easy head-to-head comparison.
    """

    def __init__(
        self,
        returns: pd.Series,
        window: int = 20,
        hidden_size: int = 32,
        num_layers: int = 2,
        dropout: float = 0.2,
        epochs: int = 50,
        batch_size: int = 32,
        learning_rate: float = 1e-3,
        patience: int = 8,
        seed: int = 42,
    ):
        _require_torch()
        self.returns = returns.dropna()
        self.window = window
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.epochs = epochs
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.patience = patience
        self.seed = seed

        torch.manual_seed(seed)
        np.random.seed(seed)

        self.device = torch.device("cpu")
        self.scaler = StandardScaler()
        self.model: LSTMVolNet | None = None
        self._trained = False
        self._training_history: list[dict] = []

    # ─── Feature Engineering ─────────────────────────────────────────────────

    def _build_sequences(self) -> tuple[np.ndarray, np.ndarray]:
        """
        Build rolling-window sequences from realized volatility.

        X: (n_samples, window, 1) — sequence of past vol values
        y: (n_samples,) — next-period vol target
        """
        vol = self.returns.rolling(self.window).std().dropna()
        X, y = [], []
        for i in range(len(vol) - self.window):
            X.append(vol.iloc[i: i + self.window].values)
            y.append(vol.iloc[i + self.window])
        X = np.array(X, dtype=np.float32)
        y = np.array(y, dtype=np.float32)
        return X.reshape(X.shape[0], X.shape[1], 1), y

    # ─── Training ────────────────────────────────────────────────────────────

    def train(self) -> dict:
        """
        Train the LSTM with early stopping on a validation split.
        """
        X, y = self._build_sequences()
        if len(X) < 50:
            return {"error": "Not enough data to train (need 50+ periods)"}

        # Chronological split (80/20, no shuffle)
        split = int(len(X) * 0.8)
        X_tr, X_te = X[:split], X[split:]
        y_tr, y_te = y[:split], y[split:]

        # Scale (fit on train only)
        orig_shape = X_tr.shape
        X_tr_flat = X_tr.reshape(-1, 1)
        X_te_flat = X_te.reshape(-1, 1)
        X_tr_s = self.scaler.fit_transform(X_tr_flat).reshape(orig_shape)
        X_te_s = self.scaler.transform(X_te_flat).reshape(X_te.shape)

        # Further split train into train/val for early stopping
        val_split = int(len(X_tr_s) * 0.85)
        X_tr_train = torch.tensor(X_tr_s[:val_split], dtype=torch.float32)
        y_tr_train = torch.tensor(y_tr[:val_split], dtype=torch.float32)
        X_tr_val = torch.tensor(X_tr_s[val_split:], dtype=torch.float32)
        y_tr_val = torch.tensor(y_tr[val_split:], dtype=torch.float32)
        X_te_t = torch.tensor(X_te_s, dtype=torch.float32)
        torch.tensor(y_te, dtype=torch.float32)

        train_ds = TensorDataset(X_tr_train, y_tr_train)
        train_loader = DataLoader(train_ds, batch_size=self.batch_size, shuffle=True)

        # Init model
        self.model = LSTMVolNet(
            input_size=1,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            dropout=self.dropout,
        ).to(self.device)

        optimiser = torch.optim.Adam(self.model.parameters(), lr=self.learning_rate)
        criterion = nn.MSELoss()

        best_val_loss = float("inf")
        best_state = None
        patience_counter = 0
        history = []

        for epoch in range(self.epochs):
            self.model.train()
            train_losses = []
            for xb, yb in train_loader:
                xb = xb.to(self.device)
                yb = yb.to(self.device)
                optimiser.zero_grad()
                pred = self.model(xb)
                loss = criterion(pred, yb)
                loss.backward()
                optimiser.step()
                train_losses.append(loss.item())

            # Validation
            self.model.eval()
            with torch.no_grad():
                val_pred = self.model(X_tr_val.to(self.device))
                val_loss = criterion(val_pred, y_tr_val.to(self.device)).item()

            train_loss_mean = float(np.mean(train_losses))
            history.append({
                "epoch": epoch + 1,
                "train_loss": round(train_loss_mean, 8),
                "val_loss": round(val_loss, 8),
            })

            # Early stopping
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_state = {k: v.clone() for k, v in self.model.state_dict().items()}
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= self.patience:
                    break

        # Restore best weights
        if best_state is not None:
            self.model.load_state_dict(best_state)

        self._trained = True
        self._training_history = history

        # Test-set evaluation
        self.model.eval()
        with torch.no_grad():
            test_pred = self.model(X_te_t.to(self.device)).cpu().numpy()

        rmse = float(np.sqrt(mean_squared_error(y_te, test_pred)))
        mae = float(mean_absolute_error(y_te, test_pred))
        # Directional accuracy: predicted vs actual direction of change
        y_te_change = np.diff(y_te)
        pred_change = np.diff(test_pred)
        if len(y_te_change) > 0:
            dir_acc = float(np.mean(np.sign(y_te_change) == np.sign(pred_change)))
        else:
            dir_acc = 0.0

        return {
            "rmse": round(rmse, 8),
            "mae": round(mae, 8),
            "directional_accuracy": round(dir_acc, 4),
            "train_samples": int(len(X_tr_train)),
            "val_samples": int(len(X_tr_val)),
            "test_samples": int(len(X_te_t)),
            "epochs_trained": len(history),
            "best_val_loss": round(best_val_loss, 8),
            "final_train_loss": history[-1]["train_loss"] if history else 0,
        }

    # ─── Prediction ──────────────────────────────────────────────────────────

    def predict_next(self) -> float:
        """Predict next-period volatility using the most recent window."""
        if not self._trained:
            self.train()

        vol = self.returns.rolling(self.window).std().dropna()
        last_window = vol.iloc[-self.window:].values.astype(np.float32)
        last_scaled = self.scaler.transform(last_window.reshape(-1, 1)).reshape(1, self.window, 1)

        self.model.eval()
        with torch.no_grad():
            x = torch.tensor(last_scaled, dtype=torch.float32).to(self.device)
            pred = self.model(x).cpu().item()

        return float(pred)

    def predict_n_step(self, n_steps: int = 5) -> list[float]:
        """
        Multi-step-ahead recursive forecast.

        Each predicted vol becomes the last element of the window for the next step.
        """
        if not self._trained:
            self.train()

        vol = self.returns.rolling(self.window).std().dropna()
        window = vol.iloc[-self.window:].values.astype(np.float32).copy()

        self.model.eval()
        forecasts = []
        with torch.no_grad():
            for _ in range(n_steps):
                w_scaled = self.scaler.transform(window.reshape(-1, 1)).reshape(1, self.window, 1)
                x = torch.tensor(w_scaled, dtype=torch.float32).to(self.device)
                pred = self.model(x).cpu().item()
                forecasts.append(float(pred))
                # Update window: drop oldest, append predicted
                window = np.roll(window, -1)
                window[-1] = pred

        return forecasts

    def predict_var(self, portfolio_value: float, confidence_level: float = 0.99) -> float:
        """LSTM-predicted volatility → VaR dollar amount."""
        vol = self.predict_next()
        z = norm.ppf(confidence_level)
        return float(portfolio_value * vol * z)

    # ─── Volatility Regime ───────────────────────────────────────────────────

    def volatility_regime(self, lookback: int = 60) -> str:
        """Classify current volatility regime (same interface as RF engine)."""
        recent = self.returns.rolling(20).std().dropna()
        hist = self.returns.rolling(lookback).std().dropna()
        if len(recent) == 0 or len(hist) == 0:
            return "unknown"
        ratio = recent.iloc[-1] / hist.mean()
        if ratio > 1.5:
            return "HIGH"
        elif ratio < 0.7:
            return "LOW"
        return "NORMAL"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. RF vs LSTM Comparison
# ═══════════════════════════════════════════════════════════════════════════════

class AIModelComparison:
    """
    Head-to-head comparison of RF and LSTM volatility forecasters.

    Runs both models on the same series and reports:
      - RMSE, MAE per model
      - Directional accuracy
      - Prediction convergence / divergence
      - Recommended model based on metrics
    """

    def __init__(self, returns: pd.Series, window: int = 20):
        _require_torch()
        self.returns = returns.dropna()
        self.window = window

    def compare(self, lstm_epochs: int = 30) -> dict:
        """
        Train both models, evaluate on the same hold-out,
        produce side-by-side metrics.
        """
        from src.models.ai_engine import AIVolatilityEngine

        # ─── Random Forest ────────────────────────────────────────────────
        rf = AIVolatilityEngine(self.returns, window=self.window)
        rf_train = rf.train()
        if "error" in rf_train:
            return {"error": rf_train["error"]}

        rf_pred = rf.predict_next()
        # Capture RF test-set performance via re-split
        X_rf, y_rf = rf._build_features()
        split = int(len(X_rf) * 0.8)
        X_te = X_rf[split:]
        y_te = y_rf[split:]
        X_te_s = rf.scaler.transform(X_te)
        rf_test_pred = rf.model.predict(X_te_s)
        rf_mae = float(mean_absolute_error(y_te, rf_test_pred))

        y_te_change = np.diff(y_te)
        pred_change_rf = np.diff(rf_test_pred)
        rf_dir_acc = float(np.mean(np.sign(y_te_change) == np.sign(pred_change_rf))) \
            if len(y_te_change) > 0 else 0.0

        # ─── LSTM ─────────────────────────────────────────────────────────
        lstm = LSTMVolatilityEngine(
            self.returns, window=self.window, epochs=lstm_epochs,
        )
        lstm_train = lstm.train()
        if "error" in lstm_train:
            return {"error": lstm_train["error"]}
        lstm_pred = lstm.predict_next()

        # ─── Comparison ──────────────────────────────────────────────────
        rf_metrics = {
            "model": "Random Forest",
            "rmse": rf_train["rmse"],
            "mae": round(rf_mae, 8),
            "directional_accuracy": round(rf_dir_acc, 4),
            "prediction_next": round(rf_pred, 8),
            "prediction_annual": round(rf_pred * np.sqrt(252), 6),
        }

        lstm_metrics = {
            "model": "LSTM",
            "rmse": lstm_train["rmse"],
            "mae": lstm_train["mae"],
            "directional_accuracy": lstm_train["directional_accuracy"],
            "prediction_next": round(lstm_pred, 8),
            "prediction_annual": round(lstm_pred * np.sqrt(252), 6),
            "epochs_trained": lstm_train["epochs_trained"],
        }

        # Winner
        if lstm_metrics["rmse"] < rf_metrics["rmse"]:
            winner_rmse = "LSTM"
            rmse_improvement = (rf_metrics["rmse"] - lstm_metrics["rmse"]) / rf_metrics["rmse"] * 100
        else:
            winner_rmse = "Random Forest"
            rmse_improvement = (lstm_metrics["rmse"] - rf_metrics["rmse"]) / lstm_metrics["rmse"] * 100

        # Prediction gap
        pred_gap = abs(rf_pred - lstm_pred) / max(rf_pred, lstm_pred)

        return {
            "random_forest": rf_metrics,
            "lstm": lstm_metrics,
            "winner_by_rmse": winner_rmse,
            "rmse_improvement_pct": round(rmse_improvement, 2),
            "prediction_gap_pct": round(pred_gap * 100, 2),
            "ensemble_prediction": round((rf_pred + lstm_pred) / 2, 8),
            "ensemble_annual": round((rf_pred + lstm_pred) / 2 * np.sqrt(252), 6),
            "recommendation": (
                f"{winner_rmse}이(가) 더 낮은 RMSE. "
                f"예측 차이 {pred_gap*100:.1f}% — "
                f"{'앙상블 추천' if pred_gap < 0.15 else '모델간 의견 차이 큼, 추가 피처 고려'}"
            ),
            "training_history": lstm._training_history[-10:],  # last 10 epochs
        }
