"""
KIS Open API Client
=====================
Wrapper around Korea Investment & Securities OpenAPI.

Reads credentials and mode from environment. Never hardcodes keys.

Required environment variables:
  KIS_MODE                = "MOCK" or "REAL"
  KIS_MOCK_APP_KEY        = ...
  KIS_MOCK_APP_SECRET     = ...
  KIS_REAL_APP_KEY        = ...
  KIS_REAL_APP_SECRET     = ...

Optional:
  KIS_MOCK_BASE_URL       (default: https://openapivts.koreainvestment.com:29443)
  KIS_REAL_BASE_URL       (default: https://openapi.koreainvestment.com:9443)
  KIS_ACCOUNT_NO          (if placing orders)
  KIS_ACCOUNT_PROD_CD     (usually "01")
"""

import logging
import os
import time
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)


DEFAULT_MOCK_URL = "https://openapivts.koreainvestment.com:29443"
DEFAULT_REAL_URL = "https://openapi.koreainvestment.com:9443"


class KISClient:
    """
    Synchronous KIS API client.

    Use a single instance per worker process. The token is cached
    in memory for 23.5 hours (KIS issues 24hr tokens).
    """

    def __init__(self, mode: str | None = None):
        self.mode = (mode or os.getenv("KIS_MODE", "MOCK")).upper()
        self._load_config()
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    def _load_config(self):
        """Dynamically resolve credentials based on mode."""
        if self.mode == "MOCK":
            self.base_url = os.getenv("KIS_MOCK_BASE_URL", DEFAULT_MOCK_URL)
            self.app_key = os.getenv("KIS_MOCK_APP_KEY", "")
            self.app_secret = os.getenv("KIS_MOCK_APP_SECRET", "")
            self.is_paper = True
        elif self.mode == "REAL":
            self.base_url = os.getenv("KIS_REAL_BASE_URL", DEFAULT_REAL_URL)
            self.app_key = os.getenv("KIS_REAL_APP_KEY", "")
            self.app_secret = os.getenv("KIS_REAL_APP_SECRET", "")
            self.is_paper = False
        else:
            raise ValueError(f"KIS_MODE must be 'MOCK' or 'REAL', got '{self.mode}'")

        self.account_no = os.getenv("KIS_ACCOUNT_NO", "")
        self.account_prod_cd = os.getenv("KIS_ACCOUNT_PROD_CD", "01")

        if not self.app_key or not self.app_secret:
            logger.warning(
                f"KIS credentials for mode={self.mode} are missing. "
                f"Set KIS_{self.mode}_APP_KEY and KIS_{self.mode}_APP_SECRET."
            )

    # ─── Token Management ────────────────────────────────────────────────

    def issue_token(self) -> str:
        """
        Issue a new OAuth token. KIS tokens are valid for 24 hours.
        We cache with a 30-min safety margin.
        """
        if not self.app_key or not self.app_secret:
            raise RuntimeError("KIS credentials not configured")

        url = f"{self.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        headers = {"content-type": "application/json"}

        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        self._token = data["access_token"]
        # KIS returns expires_in in seconds; default 86400
        expires_in = int(data.get("expires_in", 86400))
        self._token_expires_at = datetime.utcnow() + timedelta(
            seconds=expires_in - 1800,  # 30-min safety margin
        )
        logger.info(f"KIS token issued ({self.mode}), expires at {self._token_expires_at}")
        return self._token

    def get_token(self) -> str:
        """Return cached token, re-issuing if expired or missing."""
        if self._token is None or datetime.utcnow() >= (
            self._token_expires_at or datetime.utcnow()
        ):
            return self.issue_token()
        return self._token

    def _build_headers(self, tr_id: str, custtype: str = "P") -> dict:
        """Build request headers for a TR call."""
        return {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": custtype,  # P=personal, B=business
        }

    # ─── Market Data Endpoints ───────────────────────────────────────────

    def get_current_price(self, ticker: str, market: str = "J") -> dict:
        """
        Current price query.

        TR ID: FHKST01010100
        market: J=KRX, NX=NXT, UN=Unified

        Returns dict with price, volume, open, high, low, etc.
        """
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self._build_headers("FHKST01010100")
        params = {
            "FID_COND_MRKT_DIV_CODE": market,
            "FID_INPUT_ISCD": ticker,
        }

        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        body = resp.json()

        if body.get("rt_cd") != "0":
            raise RuntimeError(
                f"KIS error for {ticker}: "
                f"{body.get('msg_cd')} - {body.get('msg1')}"
            )

        output = body.get("output", {})
        return {
            "ticker": ticker,
            "price": float(output.get("stck_prpr", 0)),
            "open": float(output.get("stck_oprc", 0)),
            "high": float(output.get("stck_hgpr", 0)),
            "low": float(output.get("stck_lwpr", 0)),
            "volume": int(output.get("acml_vol", 0)),
            "trading_value": int(output.get("acml_tr_pbmn", 0)),
            "change_pct": float(output.get("prdy_ctrt", 0)),
            "per": float(output.get("per", 0)) if output.get("per") else None,
            "pbr": float(output.get("pbr", 0)) if output.get("pbr") else None,
            "market_cap_oku": output.get("hts_avls"),  # 억원
        }

    def get_daily_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        period: str = "D",
        market: str = "J",
        adjust: str = "1",
    ) -> list[dict]:
        """
        Daily OHLCV history.

        TR ID: FHKST03010100
        period: D=daily, W=weekly, M=monthly, Y=yearly
        adjust: 0=adjusted, 1=raw
        Dates in YYYYMMDD format.

        KIS returns up to 100 rows per call.
        """
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        headers = self._build_headers("FHKST03010100")
        params = {
            "FID_COND_MRKT_DIV_CODE": market,
            "FID_INPUT_ISCD": ticker,
            "FID_INPUT_DATE_1": start_date,
            "FID_INPUT_DATE_2": end_date,
            "FID_PERIOD_DIV_CODE": period,
            "FID_ORG_ADJ_PRC": adjust,
        }

        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        body = resp.json()

        if body.get("rt_cd") != "0":
            raise RuntimeError(
                f"KIS error for {ticker}: "
                f"{body.get('msg_cd')} - {body.get('msg1')}"
            )

        # output2 contains the time series
        rows = body.get("output2", []) or []
        result = []
        for r in rows:
            if not r.get("stck_bsop_date"):
                continue
            result.append({
                "ticker": ticker,
                "trade_date": r["stck_bsop_date"],  # YYYYMMDD
                "open": float(r.get("stck_oprc", 0)),
                "high": float(r.get("stck_hgpr", 0)),
                "low": float(r.get("stck_lwpr", 0)),
                "close": float(r.get("stck_clpr", 0)),
                "volume": int(r.get("acml_vol", 0)),
                "trading_value": int(r.get("acml_tr_pbmn", 0)),
            })
        return result

    # ─── Throttling Helper ───────────────────────────────────────────────

    def throttle(self, calls_per_second: float = 15):
        """
        Sleep to respect KIS rate limits.
        Real: 20 TPS. Mock: 10 TPS. Default to 15 TPS safe zone.
        """
        time.sleep(1.0 / calls_per_second)

    def get_holdings(self) -> list[dict]:
        """
        보유 종목 조회.
        TR ID: TTTC8434R (실전) / VTTC8434R (모의)
        """
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        tr_id = "VTTC8434R" if self.is_paper else "TTTC8434R"
        headers = self._build_headers(tr_id)
        params = {
            "CANO": self.account_no[:8] if len(self.account_no) >= 8 else self.account_no,
            "ACNT_PRDT_CD": self.account_prod_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            body = resp.json()
            if body.get("rt_cd") == "0":
                return body.get("output1", []) or []
            return []
        except Exception as e:
            logger.error(f"get_holdings error: {e}")
            return []

    def get_account_balance(self) -> dict:
        """
        예수금 및 평가금액 조회.
        TR ID: TTTC8434R 의 output2 사용
        """
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        tr_id = "VTTC8434R" if self.is_paper else "TTTC8434R"
        headers = self._build_headers(tr_id)
        params = {
            "CANO": self.account_no[:8] if len(self.account_no) >= 8 else self.account_no,
            "ACNT_PRDT_CD": self.account_prod_cd,
            "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
            "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            body = resp.json()
            if body.get("rt_cd") == "0":
                output2 = body.get("output2", [{}])
                if output2:
                    o = output2[0]
                    return {
                        "deposit":        float(o.get("dnca_tot_amt", 0)),
                        "eval_amount":    float(o.get("tot_evlu_amt", 0)),
                        "profit_loss":    float(o.get("evlu_pfls_smtl_amt", 0)),
                        "profit_rate":    float(o.get("asst_icdc_erng_rt", 0)),
                    }
            return {}
        except Exception as e:
            logger.error(f"get_account_balance error: {e}")
            return {}
