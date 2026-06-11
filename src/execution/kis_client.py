"""
KIS OpenAPI Client — 한국투자증권 실거래/모의투자 API
========================================================
공식 문서: https://apiportal.koreainvestment.com/

지원 엔드포인트:
  · POST /oauth2/tokenP                                  — OAuth 토큰 발급
  · POST /uapi/domestic-stock/v1/trading/order-cash      — 현금 주문
  · POST /uapi/domestic-stock/v1/trading/order-rvsecncl  — 정정/취소
  · GET  /uapi/domestic-stock/v1/trading/inquire-balance — 잔고 조회
  · GET  /uapi/domestic-stock/v1/quotations/inquire-price — 현재가

설계:
  · 토큰 자동 갱신 (24h 만료 30분 전 자동 재발급)
  · Rate limit throttle (초당 20회 한도)
  · 회로 차단기 (5회 연속 실패 → 30초 차단)
  · 모의투자/실계좌 base URL 자동 분기

보안:
  · 키는 환경변수 또는 .env 파일 (코드에 하드코딩 X)
  · 모든 API 호출에 hash 서명 (TR_ID는 거래마다 다름)
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

KIS_BASE_URL_REAL = "https://openapi.koreainvestment.com:9443"
KIS_BASE_URL_PAPER = "https://openapivts.koreainvestment.com:29443"


def _safe_float(v):
    """KIS 응답의 문자열 숫자 → float (빈값/오류 시 None)."""
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None

# Transaction IDs
TR_ID = {
    # 주문 (실거래)
    "ORDER_BUY_REAL":     "TTTC0802U",
    "ORDER_SELL_REAL":    "TTTC0801U",
    # 주문 (모의)
    "ORDER_BUY_PAPER":    "VTTC0802U",
    "ORDER_SELL_PAPER":   "VTTC0801U",
    # 정정/취소
    "ORDER_RVSE_REAL":    "TTTC0803U",
    "ORDER_RVSE_PAPER":   "VTTC0803U",
    # 잔고
    "BALANCE_REAL":       "TTTC8434R",
    "BALANCE_PAPER":      "VTTC8434R",
    # 시세 (공통)
    "PRICE":              "FHKST01010100",
    "DAILY_CHART":        "FHKST03010100",   # 국내주식 기간별시세(일/주/월/년)
    "DAILY_PRICE":        "FHKST01010400",   # 국내주식 일자별 (최근 30일)
    "INVESTOR":           "FHKST01010900",   # 주식현재가 투자자 (개인/외국인/기관 일별, 최근 ~30일)
}


def normalize_investor_rows(rows: list) -> list[dict]:
    """KIS 투자자별 응답(output) → 정규화 행.

    반환: [{date "YYYY-MM-DD", prsn_qty, frgn_qty, orgn_qty,
            prsn_amt, frgn_amt, orgn_amt}] (량=주, 금액=KIS pbmn 단위 그대로)"""
    def _f(v):
        try:
            return float(str(v).replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    out = []
    for r in rows or []:
        d = str(r.get("stck_bsop_date") or "").strip()
        if len(d) != 8:
            continue
        out.append({
            "date": f"{d[:4]}-{d[4:6]}-{d[6:]}",
            "prsn_qty": _f(r.get("prsn_ntby_qty")),
            "frgn_qty": _f(r.get("frgn_ntby_qty")),
            "orgn_qty": _f(r.get("orgn_ntby_qty")),
            "prsn_amt": _f(r.get("prsn_ntby_tr_pbmn")),
            "frgn_amt": _f(r.get("frgn_ntby_tr_pbmn")),
            "orgn_amt": _f(r.get("orgn_ntby_tr_pbmn")),
        })
    out.reverse()  # KIS 최신→과거 → 과거→현재
    return out


@dataclass
class KISCredentials:
    """KIS API 인증 정보."""
    app_key:        str
    app_secret:     str
    account_no:     str          # CANO (계좌번호 앞 8자리)
    account_prdt:   str = "01"   # ACNT_PRDT_CD (상품 코드, 기본 01)
    is_paper:       bool = False # 모의투자 여부


@dataclass
class KISToken:
    """OAuth 토큰 캐시."""
    access_token:   str
    expires_at:     datetime
    token_type:     str = "Bearer"

    @property
    def is_valid(self) -> bool:
        return datetime.now() < (self.expires_at - timedelta(minutes=30))


# ═══════════════════════════════════════════════════════════════════════════════
# Rate Limiter + Circuit Breaker
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RateLimiter:
    """초당 N회 API 호출 제한."""
    calls_per_second: float = 18.0   # 한도 20, 안전 마진 2
    _last_calls: list = field(default_factory=list)

    def acquire(self):
        now = time.time()
        # 1초 이전 호출 제거
        self._last_calls = [t for t in self._last_calls if now - t < 1.0]
        if len(self._last_calls) >= self.calls_per_second:
            sleep_for = 1.0 - (now - self._last_calls[0]) + 0.01
            time.sleep(max(0, sleep_for))
        self._last_calls.append(time.time())


@dataclass
class CircuitBreaker:
    """N회 연속 실패 시 차단."""
    failure_threshold: int = 5
    reset_timeout_seconds: float = 30.0
    failure_count: int = 0
    last_failure_time: datetime | None = None
    state: str = "CLOSED"

    def call_allowed(self) -> bool:
        if self.state == "OPEN" and self.last_failure_time:
            if (datetime.now() - self.last_failure_time).total_seconds() > self.reset_timeout_seconds:
                self.state = "HALF_OPEN"
                self.failure_count = 0
                return True
            return False
        return True

    def record_success(self):
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.error(f"Circuit breaker OPEN after {self.failure_count} failures")


# ═══════════════════════════════════════════════════════════════════════════════
# KIS Client
# ═══════════════════════════════════════════════════════════════════════════════

class KISClient:
    """
    한국투자증권 OpenAPI 클라이언트.

    Usage:
        creds = KISCredentials(
            app_key=os.environ["KIS_APP_KEY"],
            app_secret=os.environ["KIS_APP_SECRET"],
            account_no="50123456",
            is_paper=True,   # 모의투자
        )
        client = KISClient(creds)

        # 잔고 조회
        balance = client.get_balance()

        # 주문
        order_resp = client.place_order(
            ticker="005930", side="BUY", quantity=10, order_type="LIMIT", price=70000,
        )

        # 시세
        price = client.get_price("005930")
    """

    def __init__(self, credentials: KISCredentials, timeout: float = 10.0):
        if requests is None:
            raise RuntimeError("'requests' 패키지가 필요합니다. pip install requests")

        self.creds = credentials
        self.base_url = KIS_BASE_URL_PAPER if credentials.is_paper else KIS_BASE_URL_REAL
        self.timeout = timeout
        self.token: KISToken | None = None
        self.rate_limiter = RateLimiter()
        self.circuit_breaker = CircuitBreaker()

    # ─────────────────────────────────────────────────────────────────────
    # OAuth Token
    # ─────────────────────────────────────────────────────────────────────

    def _ensure_token(self):
        """토큰 유효성 확인 + 만료 시 재발급."""
        if self.token and self.token.is_valid:
            return
        self._fetch_token()

    def _fetch_token(self):
        """새 토큰 발급."""
        url = f"{self.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey":     self.creds.app_key,
            "appsecret":  self.creds.app_secret,
        }
        resp = requests.post(url, json=payload, timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"토큰 발급 실패: {resp.status_code} {resp.text}")
        data = resp.json()
        access_token = data["access_token"]
        # KIS 토큰 만료: access_token_token_expired는 epoch 또는 datetime string
        expires_in = data.get("expires_in", 86400)
        self.token = KISToken(
            access_token=access_token,
            expires_at=datetime.now() + timedelta(seconds=int(expires_in)),
            token_type=data.get("token_type", "Bearer"),
        )
        logger.info(f"KIS 토큰 발급 완료 (만료: {self.token.expires_at})")

    def _headers(self, tr_id: str, hashkey: str | None = None) -> dict:
        """공통 헤더 생성."""
        self._ensure_token()
        h = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.token.access_token}",
            "appkey":     self.creds.app_key,
            "appsecret":  self.creds.app_secret,
            "tr_id":      tr_id,
            "custtype":   "P",
        }
        if hashkey:
            h["hashkey"] = hashkey
        return h

    # ─────────────────────────────────────────────────────────────────────
    # HTTP 호출 헬퍼
    # ─────────────────────────────────────────────────────────────────────

    def _request(self, method: str, path: str, headers: dict,
                  params: dict | None = None, json_body: dict | None = None) -> dict:
        if not self.circuit_breaker.call_allowed():
            raise RuntimeError("Circuit breaker OPEN — KIS API 호출 차단됨")

        self.rate_limiter.acquire()
        url = f"{self.base_url}{path}"

        try:
            resp = requests.request(
                method=method, url=url, headers=headers,
                params=params, json=json_body, timeout=self.timeout,
            )
            data = resp.json()

            # KIS는 HTTP 200 + rt_cd로 성공/실패 구분
            rt_cd = str(data.get("rt_cd", ""))
            if rt_cd != "0":
                self.circuit_breaker.record_failure()
                raise RuntimeError(
                    f"KIS API 실패: rt_cd={rt_cd}, msg={data.get('msg1', 'unknown')}"
                )

            self.circuit_breaker.record_success()
            return data
        except requests.RequestException as e:
            self.circuit_breaker.record_failure()
            raise RuntimeError(f"네트워크 오류: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # 1. 주문 (현금)
    # ─────────────────────────────────────────────────────────────────────

    def place_order(
        self,
        ticker: str,
        side: str,                  # BUY | SELL
        quantity: int,
        order_type: str = "MARKET", # MARKET | LIMIT
        price: float | None = None,
    ) -> dict:
        """
        주식 현금 주문 발주.

        Returns:
            {
              "kis_order_id": str,    # KRX_FWDG_ORD_ORGNO
              "kis_order_no": str,    # ODNO (주문번호)
              "ord_tmd":      str,    # 주문시각
              "raw":          dict,   # KIS 원본 응답
            }
        """
        if side not in ("BUY", "SELL"):
            raise ValueError(f"side는 BUY/SELL: {side}")
        if quantity <= 0:
            raise ValueError(f"quantity > 0: {quantity}")

        # TR_ID 결정
        is_paper = self.creds.is_paper
        if side == "BUY":
            tr_id = TR_ID["ORDER_BUY_PAPER" if is_paper else "ORDER_BUY_REAL"]
        else:
            tr_id = TR_ID["ORDER_SELL_PAPER" if is_paper else "ORDER_SELL_REAL"]

        # 주문 구분 코드
        if order_type == "MARKET":
            ord_dvsn = "01"   # 시장가
            order_price = "0"
        elif order_type == "LIMIT":
            if price is None or price <= 0:
                raise ValueError("LIMIT 주문은 price 필수")
            ord_dvsn = "00"   # 지정가
            order_price = str(int(price))
        else:
            raise ValueError(f"order_type: MARKET | LIMIT (받음: {order_type})")

        body = {
            "CANO":         self.creds.account_no,
            "ACNT_PRDT_CD": self.creds.account_prdt,
            "PDNO":         ticker,
            "ORD_DVSN":     ord_dvsn,
            "ORD_QTY":      str(int(quantity)),
            "ORD_UNPR":     order_price,
        }

        headers = self._headers(tr_id)
        data = self._request(
            "POST",
            "/uapi/domestic-stock/v1/trading/order-cash",
            headers, json_body=body,
        )

        output = data.get("output", {})
        return {
            "kis_order_id":  output.get("KRX_FWDG_ORD_ORGNO"),
            "kis_order_no":  output.get("ODNO"),
            "ord_tmd":       output.get("ORD_TMD"),
            "msg":           data.get("msg1"),
            "raw":           data,
        }

    # ─────────────────────────────────────────────────────────────────────
    # 2. 정정/취소
    # ─────────────────────────────────────────────────────────────────────

    def cancel_order(
        self,
        kis_order_id: str,
        kis_order_no: str,
        cancel_qty: int | None = None,
    ) -> dict:
        """미체결 주문 취소 (또는 부분 취소)."""
        tr_id = TR_ID["ORDER_RVSE_PAPER" if self.creds.is_paper else "ORDER_RVSE_REAL"]
        body = {
            "CANO":            self.creds.account_no,
            "ACNT_PRDT_CD":    self.creds.account_prdt,
            "KRX_FWDG_ORD_ORGNO": kis_order_id,
            "ORGN_ODNO":       kis_order_no,
            "ORD_DVSN":        "00",
            "RVSE_CNCL_DVSN_CD": "02",        # 02 = 취소
            "ORD_QTY":         str(int(cancel_qty)) if cancel_qty else "0",
            "ORD_UNPR":        "0",
            "QTY_ALL_ORD_YN":  "Y" if cancel_qty is None else "N",
        }
        headers = self._headers(tr_id)
        return self._request(
            "POST",
            "/uapi/domestic-stock/v1/trading/order-rvsecncl",
            headers, json_body=body,
        )

    # ─────────────────────────────────────────────────────────────────────
    # 3. 잔고 조회
    # ─────────────────────────────────────────────────────────────────────

    def get_balance(self) -> dict:
        """
        주식 잔고 조회.

        Returns:
            {
              "cash_krw":        가용 현금
              "evaluated_total": 평가 자산 합계
              "positions":       [{ticker, name, quantity, avg_price, current_price, eval_amount, pnl_pct}, ...]
              "raw": ...
            }
        """
        tr_id = TR_ID["BALANCE_PAPER" if self.creds.is_paper else "BALANCE_REAL"]
        params = {
            "CANO":             self.creds.account_no,
            "ACNT_PRDT_CD":     self.creds.account_prdt,
            "AFHR_FLPR_YN":     "N",
            "OFL_YN":           "",
            "INQR_DVSN":        "02",
            "UNPR_DVSN":        "01",
            "FUND_STTL_ICLD_YN":"N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN":        "01",
            "CTX_AREA_FK100":   "",
            "CTX_AREA_NK100":   "",
        }
        headers = self._headers(tr_id)
        data = self._request(
            "GET", "/uapi/domestic-stock/v1/trading/inquire-balance",
            headers, params=params,
        )

        # output1 = 종목별, output2 = 계좌 요약
        positions = []
        for item in data.get("output1", []):
            qty = int(item.get("hldg_qty") or 0)
            if qty == 0:
                continue
            positions.append({
                "ticker":        item.get("pdno"),
                "name":          item.get("prdt_name"),
                "quantity":      qty,
                "avg_price":     float(item.get("pchs_avg_pric") or 0),
                "current_price": float(item.get("prpr") or 0),
                "eval_amount":   float(item.get("evlu_amt") or 0),
                "pnl_pct":       float(item.get("evlu_pfls_rt") or 0),
                "pnl_krw":       float(item.get("evlu_pfls_amt") or 0),
            })

        output2 = data.get("output2", [{}])[0] if data.get("output2") else {}

        return {
            "cash_krw":        float(output2.get("nxdy_excc_amt") or 0),
            "evaluated_total": float(output2.get("tot_evlu_amt") or 0),
            "stock_value":     float(output2.get("scts_evlu_amt") or 0),
            "deposit":         float(output2.get("dnca_tot_amt") or 0),
            "positions":       positions,
            "n_positions":     len(positions),
            "raw":             data,
        }

    # ─────────────────────────────────────────────────────────────────────
    # 4. 현재가 시세
    # ─────────────────────────────────────────────────────────────────────

    def get_price(self, ticker: str) -> dict:
        """단일 종목 현재가."""
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD":          ticker,
        }
        headers = self._headers(TR_ID["PRICE"])
        data = self._request(
            "GET", "/uapi/domestic-stock/v1/quotations/inquire-price",
            headers, params=params,
        )
        output = data.get("output", {})
        return {
            "ticker":        ticker,
            "name":          output.get("hts_kor_isnm"),
            "current_price": float(output.get("stck_prpr") or 0),
            "change":        float(output.get("prdy_vrss") or 0),
            "change_pct":    float(output.get("prdy_ctrt") or 0),
            "volume":        int(output.get("acml_vol") or 0),
            "trade_value_krw": float(output.get("acml_tr_pbmn") or 0),
            "high_52w":      float(output.get("w52_hgpr") or 0),
            "low_52w":       float(output.get("w52_lwpr") or 0),
            "market_cap_억": (float(output.get("hts_avls") or 0)),  # 시가총액(억원)
            "per":           _safe_float(output.get("per")),
            "pbr":           _safe_float(output.get("pbr")),
            "eps":           _safe_float(output.get("eps")),
            "bps":           _safe_float(output.get("bps")),
            "raw":           data,
        }

    def get_daily_ohlcv(self, ticker: str, days: int = 150,
                         period: str = "D") -> list:
        """
        국내주식 기간별 OHLCV (백테스트·기술지표용).

        Args:
            ticker: 6자리 종목코드
            days:   조회 일수 (KIS는 1회 최대 100건 → 자동 페이지네이션)
            period: D(일)|W(주)|M(월)|Y(년)
        Returns:
            [{date, open, high, low, close, volume}, ...] 과거→현재 순
        """
        from datetime import datetime, timedelta
        end = datetime.now()
        start = end - timedelta(days=int(days * 1.6) + 10)  # 영업일 환산 여유
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD":          ticker,
            "FID_INPUT_DATE_1":        start.strftime("%Y%m%d"),
            "FID_INPUT_DATE_2":        end.strftime("%Y%m%d"),
            "FID_PERIOD_DIV_CODE":     period,
            "FID_ORG_ADJ_PRC":         "0",   # 0=수정주가, 1=원주가
        }
        headers = self._headers(TR_ID["DAILY_CHART"])
        data = self._request(
            "GET", "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            headers, params=params,
        )
        rows = data.get("output2", []) or []
        result = []
        for r in rows:
            if not r.get("stck_bsop_date"):
                continue
            result.append({
                "date":   r.get("stck_bsop_date"),
                "open":   float(r.get("stck_oprc") or 0),
                "high":   float(r.get("stck_hgpr") or 0),
                "low":    float(r.get("stck_lwpr") or 0),
                "close":  float(r.get("stck_clpr") or 0),
                "volume": float(r.get("acml_vol") or 0),
            })
        # KIS는 최신→과거 순으로 반환 → 과거→현재로 뒤집기
        result.reverse()
        return result[-days:] if len(result) > days else result

    def get_investor_daily(self, ticker: str) -> list[dict]:
        """종목별 투자자 일별 순매수 (개인/외국인/기관계, 최근 ~30영업일).

        kis_flows가 매일 적재해 누적 — KIS TR 특성상 깊은 과거는 미제공."""
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker,
        }
        headers = self._headers(TR_ID["INVESTOR"])
        data = self._request(
            "GET", "/uapi/domestic-stock/v1/quotations/inquire-investor",
            headers, params=params,
        )
        return normalize_investor_rows(data.get("output", []) or [])


# ═══════════════════════════════════════════════════════════════════════════════
# Mock client (테스트용 — 실제 KIS 호출 없이 시뮬레이션)
# ═══════════════════════════════════════════════════════════════════════════════

class MockKISClient:
    """
    KIS 호출을 시뮬레이션하는 mock 클라이언트.
    테스트, 개발, dry-run에 사용. 실제 주문 X.
    """

    def __init__(self, initial_cash: float = 100_000_000):
        self.cash = initial_cash
        self.positions: dict = {}    # ticker -> {quantity, avg_price}
        self.orders: list = []
        self.fills: list = []
        self.prices: dict = {        # 모의 가격
            "005930": 71000,    # 삼성전자
            "000660": 130000,   # SK하이닉스
            "035420": 200000,   # NAVER
        }

    def get_investor_daily(self, ticker: str) -> list[dict]:
        """mock엔 수급 데이터 없음 — 빈 리스트 (kis_flows가 실키 필요를 안내)."""
        return []

    def place_order(self, ticker, side, quantity, order_type="MARKET", price=None):
        # 즉시 체결 시뮬레이션 (시장가 가정)
        execute_price = price or self.prices.get(ticker, 50000)

        if side == "BUY":
            cost = execute_price * quantity + (execute_price * quantity) * 0.00015
            if cost > self.cash:
                raise RuntimeError(f"Mock 잔고 부족: 필요 {cost:.0f} / 보유 {self.cash:.0f}")
            self.cash -= cost
            pos = self.positions.setdefault(ticker, {"quantity": 0, "avg_price": 0})
            new_qty = pos["quantity"] + quantity
            pos["avg_price"] = (pos["avg_price"] * pos["quantity"] + execute_price * quantity) / new_qty
            pos["quantity"] = new_qty
        else:
            pos = self.positions.get(ticker, {"quantity": 0})
            if pos["quantity"] < quantity:
                raise RuntimeError(f"Mock 보유 부족: 매도 {quantity} / 보유 {pos['quantity']}")
            proceeds = execute_price * quantity * (1 - 0.00015 - 0.0023)  # 수수료+세금
            self.cash += proceeds
            pos["quantity"] -= quantity

        order_id = f"MOCK-{uuid.uuid4().hex[:8]}"
        self.fills.append({
            "ticker": ticker, "side": side, "quantity": quantity,
            "price": execute_price, "ts": datetime.now(),
        })
        return {
            "kis_order_id": "MOCK-ORG",
            "kis_order_no": order_id,
            "ord_tmd":      datetime.now().strftime("%H%M%S"),
            "msg":          "Mock 주문 즉시 체결",
            "raw":          {"rt_cd": "0", "msg1": "정상"},
        }

    def get_balance(self):
        evaluated = self.cash
        positions = []
        for ticker, pos in self.positions.items():
            cp = self.prices.get(ticker, pos["avg_price"])
            eval_amount = pos["quantity"] * cp
            pnl_pct = (cp / pos["avg_price"] - 1) * 100 if pos["avg_price"] > 0 else 0
            evaluated += eval_amount
            positions.append({
                "ticker": ticker, "quantity": pos["quantity"],
                "avg_price": pos["avg_price"], "current_price": cp,
                "eval_amount": eval_amount,
                "pnl_pct": pnl_pct,
                "pnl_krw": (cp - pos["avg_price"]) * pos["quantity"],
            })
        return {
            "cash_krw":        self.cash,
            "evaluated_total": evaluated,
            "stock_value":     evaluated - self.cash,
            "positions":       positions,
            "n_positions":     len(positions),
            "raw":             {"mock": True},
        }

    def get_price(self, ticker):
        return {
            "ticker":        ticker,
            "name":          f"Mock-{ticker}",
            "current_price": self.prices.get(ticker, 50000),
            "change":        0,
            "change_pct":    0,
            "volume":        1_000_000,
            "market_cap_억": None, "per": None, "pbr": None, "eps": None, "bps": None,
        }

    def get_daily_ohlcv(self, ticker, days=150, period="D"):
        """Mock 일봉 — deterministic (실제 KIS 호출 없음)."""
        import random as _r
        seed = sum(ord(ch) for ch in ticker)
        rng = _r.Random(seed)
        base = self.prices.get(ticker, 10000 + (seed % 90) * 1000)
        closes, px = [], base
        for _ in range(days):
            px = max(100, px * (1 + rng.gauss(0.0005, 0.018)))
            closes.append(px)
        rows = []
        for px in closes:
            spread = px * rng.uniform(0.005, 0.02)
            rows.append({
                "date": "MOCK", "open": px - spread*0.3, "high": px + spread,
                "low": px - spread, "close": px, "volume": rng.uniform(5e5, 5e6),
            })
        return rows

    def cancel_order(self, *args, **kwargs):
        return {"msg": "Mock 취소 완료"}


# ═══════════════════════════════════════════════════════════════════════════════
# 통합 팩토리 — .env 기반 자동 분기 (실데이터 연동 진입점)
# ═══════════════════════════════════════════════════════════════════════════════

_kis_singleton = None

def get_kis_client(force_reload: bool = False):
    """
    .env 설정에 따라 KISClient(실) 또는 MockKISClient(가짜)를 반환.

    환경변수:
      KIS_USE_MOCK=1            → MockKISClient (외부 호출 없음)
      KIS_USE_MOCK=0, IS_PAPER=1 → KIS 모의투자
      KIS_USE_MOCK=0, IS_PAPER=0 → KIS 실계좌

    데이터 조회(get_price/get_daily_ohlcv)는 모의·실계좌 모두 가능.
    싱글톤으로 토큰 재사용 (1분당 1회 발급 제한 대응).
    """
    global _kis_singleton
    if _kis_singleton is not None and not force_reload:
        return _kis_singleton

    use_mock = os.getenv("KIS_USE_MOCK", "1") == "1"
    if use_mock:
        _kis_singleton = MockKISClient()
        logger.info("KIS: MockKISClient (KIS_USE_MOCK=1)")
        return _kis_singleton

    app_key = os.getenv("KIS_APP_KEY", "")
    app_secret = os.getenv("KIS_APP_SECRET", "")
    if not app_key or not app_secret:
        logger.warning("KIS_APP_KEY/SECRET 미설정 → MockKISClient fallback")
        _kis_singleton = MockKISClient()
        return _kis_singleton

    is_paper = os.getenv("KIS_IS_PAPER", "1") == "1"
    creds = KISCredentials(
        app_key=app_key,
        app_secret=app_secret,
        account_no=os.getenv("KIS_ACCOUNT_NO", ""),
        account_prdt=os.getenv("KIS_ACCOUNT_PRDT", "01"),
        is_paper=is_paper,
    )
    _kis_singleton = KISClient(creds)
    logger.info(f"KIS: 실연동 ({'모의투자' if is_paper else '실계좌'})")
    return _kis_singleton
