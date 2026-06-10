"""
Korea Investment Securities (KIS) Open API Connector
Supports both mock (paper trading) and real account modes.
"""
import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()


class KoreaInvestmentAPI:
    REAL_URL = "https://openapi.koreainvestment.com:9443"
    MOCK_URL = "https://openapivts.koreainvestment.com:29443"

    def __init__(self):
        self.app_key    = os.getenv("KIS_APP_KEY", "")
        self.app_secret = os.getenv("KIS_APP_SECRET", "")
        self.account_no = os.getenv("KIS_ACCOUNT_NO", "00000000-01")
        self.mode       = os.getenv("KIS_MODE", "mock").lower()
        self.base_url   = self.MOCK_URL if self.mode == "mock" else self.REAL_URL
        self._token     = None

    @property
    def access_token(self) -> str:
        if not self._token:
            self._token = self._get_token()
        return self._token

    def _get_token(self) -> str:
        if not self.app_key or not self.app_secret:
            return "DEMO_TOKEN"
        res = requests.post(
            f"{self.base_url}/oauth2/tokenP",
            headers={"content-type": "application/json"},
            data=json.dumps({
                "grant_type": "client_credentials",
                "appkey":     self.app_key,
                "appsecret":  self.app_secret,
            }),
            timeout=10,
        )
        return res.json().get("access_token", "")

    def _headers(self, tr_id: str) -> dict:
        return {
            "content-type":  "application/json",
            "authorization": f"Bearer {self.access_token}",
            "appkey":        self.app_key,
            "appsecret":     self.app_secret,
            "tr_id":         tr_id,
        }

    def fetch_portfolio(self) -> list:
        """Fetch current account holdings."""
        if not self.app_key:
            # Return demo data when no API key is configured
            return [
                {"ticker": "005930.KS", "name": "삼성전자", "quantity": 100,
                 "current_price": 75000, "total_value": 7_500_000},
                {"ticker": "000660.KS", "name": "SK하이닉스", "quantity": 50,
                 "current_price": 190000, "total_value": 9_500_000},
            ]

        acc, prod = self.account_no.split("-")
        tr_id = "VTTC8434R" if self.mode == "mock" else "TTTC8434R"
        res = requests.get(
            f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
            headers=self._headers(tr_id),
            params={
                "CANO": acc, "ACNT_PRDT_CD": prod,
                "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
                "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
                "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
            },
            timeout=10,
        ).json()

        portfolio = []
        for item in res.get("output1", []):
            qty = int(item.get("hldg_qty", 0))
            if qty > 0:
                portfolio.append({
                    "ticker":        item["pdno"] + ".KS",
                    "name":          item["prdt_name"],
                    "quantity":      qty,
                    "current_price": float(item.get("prpr", 0)),
                    "total_value":   float(item.get("evlu_amt", 0)),
                })
        return portfolio

    def place_order(self, ticker: str, qty: int, side: str = "sell") -> dict:
        """Place a market order. side: 'buy' | 'sell'."""
        if not self.app_key:
            return {"status": "DEMO", "message": f"[DEMO] {side.upper()} {qty} shares of {ticker}"}

        acc, prod = self.account_no.split("-")
        if self.mode == "mock":
            tr_id = "VTTC0802U" if side == "sell" else "VTTC0801U"
        else:
            tr_id = "TTTC0802U" if side == "sell" else "TTTC0801U"

        body = {
            "CANO": acc, "ACNT_PRDT_CD": prod,
            "PDNO":    ticker.replace(".KS", ""),
            "ORD_DVSN":  "01",  # market order
            "ORD_QTY":   str(qty),
            "ORD_UNPR":  "0",
        }
        res = requests.post(
            f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash",
            headers=self._headers(tr_id),
            data=json.dumps(body),
            timeout=10,
        )
        return res.json()
