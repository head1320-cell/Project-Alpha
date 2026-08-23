"""
Market Data Loader
Fetches historical price data from Yahoo Finance API.
Includes retry logic and fallback for robustness in Docker environments.
"""
import logging
import time

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Maximum retries for yfinance downloads
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


class MarketDataLoader:
    def __init__(self, ticker: str, start_date: str, end_date: str):
        self.ticker = ticker
        self.start_date = start_date
        self.end_date = end_date

    def _download_with_retry(self, ticker: str, **kwargs) -> pd.DataFrame:
        """Download data with automatic retry on failure."""
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                data = yf.download(
                    ticker,
                    start=self.start_date,
                    end=self.end_date,
                    progress=False,
                    **kwargs,
                )
                if not data.empty:
                    return data
                logger.warning(
                    f"Empty data for {ticker} (attempt {attempt}/{MAX_RETRIES})"
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Download failed for {ticker} (attempt {attempt}/{MAX_RETRIES}): {e}"
                )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)

        raise ValueError(
            f"No data found for ticker '{ticker}' after {MAX_RETRIES} attempts. "
            f"Last error: {last_error}"
        )

    def fetch_prices(self) -> pd.Series:
        """Fetch adjusted closing prices."""
        data = self._download_with_retry(self.ticker)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        return data["Close"].squeeze()

    def fetch_returns(self) -> pd.Series:
        """Compute daily log returns."""
        prices = self.fetch_prices()
        returns = np.log(prices / prices.shift(1)).dropna()
        returns.name = self.ticker
        return returns

    def fetch_multi_returns(self, tickers: list) -> pd.DataFrame:
        """Fetch returns for multiple tickers."""
        frames = {}
        for t in tickers:
            loader = MarketDataLoader(t, self.start_date, self.end_date)
            frames[t] = loader.fetch_returns()
        return pd.DataFrame(frames).dropna()

    def fetch_ohlcv(self) -> pd.DataFrame:
        """Fetch full OHLCV data (Open, High, Low, Close, Volume)."""
        data = self._download_with_retry(self.ticker, auto_adjust=False)
        # Handle multi-level columns from yfinance
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        # Standardize column names
        result = pd.DataFrame(index=data.index)
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in data.columns:
                result[col] = data[col]
        if "Adj Close" in data.columns:
            result["AdjClose"] = data["Adj Close"]
        return result.dropna()

    def fetch_vix(self) -> pd.Series:
        """Fetch VIX index as a secondary feature."""
        try:
            vix = self._download_with_retry("^VIX", auto_adjust=False)
        except ValueError:
            logger.warning("VIX data unavailable, returning empty series")
            return pd.Series(dtype=float)
        if isinstance(vix.columns, pd.MultiIndex):
            vix.columns = vix.columns.get_level_values(0)
        return vix["Close"].dropna().rename("VIX")
