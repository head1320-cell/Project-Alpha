"""AI/ML — LSTM 변동성 예측·멀티피처·모니터 — main_api.py에서 분리(경로·동작 불변).
"""

import logging

import numpy as np
from fastapi import APIRouter, HTTPException

from src.api.legacy_schemas import (
    AICompareRequest,
    LSTMForecastRequest,
    MonitorRequest,
    MultiFeatureRequest,
)
from src.data_loader import MarketDataLoader
from src.models.feature_engine import MultiFeatureVolatilityEngine
from src.models.model_monitor import ModelMonitor

logger = logging.getLogger("api.ai")
router = APIRouter(tags=["ai"])


@router.post("/ai-vol-compare")
def ai_vol_compare(req: AICompareRequest):
    """
    Head-to-head comparison: Random Forest vs LSTM volatility forecast.
    Returns both models' metrics, predictions, and ensemble.
    """
    try:
        from src.models.lstm_engine import TORCH_AVAILABLE, AIModelComparison
        if not TORCH_AVAILABLE:
            raise HTTPException(503, "LSTM 기능은 torch 설치가 필요합니다. `pip install torch` 후 사용하세요.")
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        returns = loader.fetch_returns()

        if len(returns) < 120:
            raise HTTPException(400, "최소 120일치 데이터 필요 (LSTM 훈련용)")

        cmp = AIModelComparison(returns, window=req.window)
        result = cmp.compare(lstm_epochs=req.lstm_epochs)
        result["ticker"] = req.ticker
        result["n_observations"] = len(returns)
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/lstm-forecast")
def lstm_forecast(req: LSTMForecastRequest):
    """Multi-step-ahead LSTM volatility forecast."""
    try:
        from src.models.lstm_engine import TORCH_AVAILABLE, LSTMVolatilityEngine
        if not TORCH_AVAILABLE:
            raise HTTPException(503, "LSTM 기능은 torch 설치가 필요합니다. `pip install torch` 후 사용하세요.")
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        returns = loader.fetch_returns()

        if len(returns) < 120:
            raise HTTPException(400, "최소 120일치 데이터 필요")

        engine = LSTMVolatilityEngine(returns, window=req.window, epochs=req.epochs)
        train_result = engine.train()
        forecasts = engine.predict_n_step(req.n_steps)

        return {
            "ticker": req.ticker,
            "training": train_result,
            "forecasts_daily": [round(f, 8) for f in forecasts],
            "forecasts_annual": [round(f * (252 ** 0.5), 6) for f in forecasts],
            "n_steps": req.n_steps,
            "regime": engine.volatility_regime(),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/ai-multi-feature")
def ai_multi_feature(req: MultiFeatureRequest):
    """
    Train a multi-feature AI volatility model (19 features from OHLCV + VIX).

    Features: RSI, MACD, Bollinger position, Stochastic, ATR, realized vol
    (5/20/60d), skewness, kurtosis, return autocorr, volume change/ratio,
    OBV change, VIX level/change/MA-ratio.
    """
    try:
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        ohlcv = loader.fetch_ohlcv()

        vix = None
        if req.use_vix:
            try:
                vix = loader.fetch_vix()
            except Exception:
                vix = None

        if len(ohlcv) < 120:
            raise HTTPException(400, "최소 120일 데이터 필요")

        engine = MultiFeatureVolatilityEngine(
            ohlcv, vix=vix, vol_window=req.vol_window,
            model_type=req.model_type,
        )
        train_result = engine.train()
        if "error" in train_result:
            raise HTTPException(400, train_result["error"])

        next_vol = engine.predict_next()

        return {
            "ticker": req.ticker,
            "model_type": train_result["model_type"],
            "training": train_result,
            "prediction_next_daily": round(next_vol, 8),
            "prediction_next_annual": round(next_vol * (252 ** 0.5), 6),
            "vix_used": vix is not None and not vix.empty,
            "n_observations": len(ohlcv),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/ai-monitor")
def ai_monitor(req: MonitorRequest):
    """
    Full AI model monitoring report.

    Walk-forward backtest, feature drift (PSI + KS), prediction drift,
    concept drift (error autocorrelation), overall health status.
    """
    try:
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        ohlcv = loader.fetch_ohlcv()
        returns = np.log(ohlcv["Close"] / ohlcv["Close"].shift(1)).dropna()
        returns.name = req.ticker

        vix = None
        if req.use_vix:
            try:
                vix = loader.fetch_vix()
            except Exception:
                vix = None

        if len(ohlcv) < 200:
            raise HTTPException(400, "모니터링에는 최소 200일 데이터 필요")

        monitor = ModelMonitor(
            ohlcv, returns, vix=vix,
            vol_window=req.vol_window,
            initial_train_ratio=req.initial_train_ratio,
            refit_every=req.refit_every,
        )
        report = monitor.full_report()
        if "error" in report:
            raise HTTPException(400, report["error"])

        report["ticker"] = req.ticker
        return report
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
