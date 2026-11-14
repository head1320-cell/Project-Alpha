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

from src.data.mock_gate import mock_allowed

logger = logging.getLogger(__name__)

#: 화면·응답에 그대로 실리는 문장 — 개발자 낱말·환경변수 이름·제공자 이름을 싣지 않는다(용어집 §6).
MARKET_DOWNLOAD_BLOCKED = "합성 데이터 모드에서는 해외 시세를 내려받지 않습니다 — 이 분석은 실데이터 모드에서 사용할 수 있습니다."


class MarketDataBlockedInMock(ValueError):
    """mock 게이트가 켜져 있어 야후 시세를 ★시도하지 않았다★(2026-11-13) — 내려받다 실패한 것과 다른 사유다.

    `ValueError` 하위라 '시세 없음'을 `ValueError` 로 받던 호출자(`fetch_vix` — 빈 계열로 열화)는 그대로 돈다.
    """

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
        # ★mock 게이트(`mock_allowed()` — 유일한 판정 기준)★ — mock 은 외부로 나가지 않는다. 재시도·대기 없이 바로 사유를 올린다.
        # 합성 시세를 지어내지 않는다(이 로더를 쓰는 분석은 mock 에서 '사용 불가 + 사유'가 된다).
        if mock_allowed():
            raise MarketDataBlockedInMock(MARKET_DOWNLOAD_BLOCKED)
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
