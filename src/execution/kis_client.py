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
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src.data.mock_gate import mock_allowed

try:
    import requests
except ImportError:
    requests = None

from src.domain.kis_failure import (
    FAILURE_KINDS,
    KIND_BLOCKED,
    KIND_BUSINESS,
    KIND_MALFORMED,
    KIND_TOKEN,
    KIND_TRANSPORT,
    KIND_UNKNOWN,
    failure_label,
)

logger = logging.getLogger(__name__)


class KISCallError(RuntimeError):
    """KIS 호출 실패 하나 — ★종류를 들고 다닌다★ (AR2)

    ★메시지 문구는 예전 그대로다★ — `tests/test_ingest_doctor.py` 가
    `"토큰 발급 실패"` **부분문자열**을 단언한다. 문구를 바꾸면 그 계약이 깨지므로
    **타입과 속성만** 더한다.

    ★`RuntimeError` 하위형인 이유★ — `src/` 의 모든 소비자가 `except Exception`
    이라 하위형은 안전하고, `KISCredentialsMissing(RuntimeError)` 라는 선례가
    이미 있다(`try_kis_client` 가 **타입으로** 잡는다).
    """

    def __init__(self, message: str, *, kind: str, rt_cd=None, status=None,
                 kis_msg=None, msg_cd=None):
        super().__init__(message)
        self.kind = kind
        self.rt_cd = rt_cd
        self.status = status
        self.kis_msg = kis_msg
        #: ★표의 열쇠★(AS1) — `rt_cd` 는 `!= "0"` 이분법으로 쓰이는 거친 값이라
        #: 혼자서는 뜻을 가리지 못한다. 없으면 `None` 이고 그것은 미상이다.
        self.msg_cd = msg_cd

    def label(self) -> dict:
        """기록·응답에 싣는 블록. ★책임 소재를 단정하지 않는다★"""
        return failure_label(self.kind, rt_cd=self.rt_cd, status=self.status,
                             msg=self.kis_msg, msg_cd=self.msg_cd)


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
    "MINUTE_TODAY":       "FHKST03010200",   # 주식당일분봉조회 (당일 1분봉, 30건/콜)
    "MINUTE_DAILY":       "FHKST03010230",   # 주식일별분봉조회 (과거 일자 — 소급 한도는 실측)
    "INVESTOR":           "FHKST01010900",   # 주식현재가 투자자 (개인/외국인/기관 일별, 최근 ~30일)
}

# ── 일봉 가격 정의(basis) ────────────────────────────────────────────────────
#: `get_daily_ohlcv` 가 KIS 에 **요청하는** 수정주가 플래그.
#: KIS 기간별시세의 `FID_ORG_ADJ_PRC` — 0=수정주가, 1=원주가.
DAILY_ADJ_PRC_FLAG = "0"

#: 위 플래그가 뜻하는 가격 정의. ★적재 경로가 이 상수를 읽어 행에 기록한다★
#: (`ohlcv_loader.ingest_df_to_db` → `daily_prices.price_basis`).
#:
#: ★이 상수가 주장하는 것은 좁다★ — "우리가 무엇을 **요청했는가**" 이지
#: "KIS 가 준 값이 실제로 수정주가다" 가 아니다. 후자는 실데이터에서
#: `price_quality.basis_overlap_check()` 가 연속 종가의 수익률과 KRX 등락률
#: (`return_1d`)이 맞는지 보고 나서야 말할 수 있다.
#:
#: ★플래그와 같은 자리에 둔 이유★ 누가 `DAILY_ADJ_PRC_FLAG` 를 뒤집으면
#: 기록되는 basis 도 **함께** 바뀌어야 한다. 적재 경로가 문자열을 따로
#: 들고 있으면 언젠가 둘이 갈라지고, 그때 DB 는 조용히 거짓을 적는다.
DAILY_PRICE_BASIS = "adjusted" if DAILY_ADJ_PRC_FLAG == "0" else "raw"


def normalize_investor_rows(rows: list) -> list[dict]:
    """KIS 투자자별 응답(output) → 정규화 행.

    반환: [{date "YYYY-MM-DD", prsn_qty, frgn_qty, orgn_qty,
            prsn_amt, frgn_amt, orgn_amt}] — 량=주, 금액=★억원 단위로 정규화★.
    KIS pbmn 필드는 백만원 단위 → /100. (원본을 단위 그대로 저장하던 시절 표시가
    '외국인 20일 순매수 -1519조'로 100배 뻥튀기 — CIO 실사. 적재 시 억 단일화)"""
    def _f(v):
        try:
            return float(str(v).replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    def _억(v):  # pbmn(백만원) → 억원
        x = _f(v)
        return (x / 100.0) if x is not None else None

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
            "prsn_amt": _억(r.get("prsn_ntby_tr_pbmn")),
            "frgn_amt": _억(r.get("frgn_ntby_tr_pbmn")),
            "orgn_amt": _억(r.get("orgn_ntby_tr_pbmn")),
        })
    out.reverse()  # KIS 최신→과거 → 과거→현재
    return out


@dataclass
class KISCredentials:
    """KIS API 인증 정보.

    ★비밀은 repr 에 나오지 않는다(BV2)★ — 앱 키·시크릿·계좌번호가 예외 메시지·로그·디버거 출력에
    `KISCredentials(app_key='…')` 로 새지 않게 `repr=False`. 값과 동작은 그대로다.
    """
    app_key:        str = field(repr=False)
    app_secret:     str = field(repr=False)
    account_no:     str = field(repr=False)   # CANO (계좌번호 앞 8자리)
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
    """초당 N회 API 호출 제한 (스레드 안전 — 병렬 OHLCV 로딩 등 동시 호출 대응).

    여러 워커 스레드가 동시에 acquire()를 불러도 _last_calls 경쟁 없이 합산 ≤ N/s 유지.
    페이싱(sleep)은 락 안에서 하지만, 실제 HTTP 요청은 acquire() 반환 후(락 밖)라 동시 실행됨.
    """
    calls_per_second: float = 18.0   # 한도 20, 안전 마진 2
    _last_calls: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def acquire(self):
        # ★락을 쥔 채 자지 않는다★ 예전에는 `time.sleep()` 이 `with self._lock:`
        # 안에 있어, 스로틀된 스레드 하나가 자는 동안 다른 로더 스레드 10개의
        # `acquire()` 가 전부 막혔다 — 페이싱이 아니라 직렬화였다.
        # 슬롯 **예약**은 락 안에서(합산 한도 유지), **대기**는 락 밖에서 한다.
        sleep_for = 0.0
        with self._lock:
            now = time.time()
            # 1초 이전 호출 제거
            self._last_calls = [t for t in self._last_calls if now - t < 1.0]
            if len(self._last_calls) >= self.calls_per_second:
                sleep_for = max(0.0, 1.0 - (now - self._last_calls[0]) + 0.01)
            # 예약 시각을 미리 기록 — 대기 중에 다른 스레드가 이 슬롯을 겹쳐 쓰지 못한다.
            self._last_calls.append(now + sleep_for)
        if sleep_for > 0:
            time.sleep(sleep_for)


#: 연속 실패 링의 최대 길이. ★임계(5)보다 넉넉하게★ — 임계만큼만 담으면
#: 넘치는 순간 구성이 사실상 언제나 카운트와 어긋난다.
STREAK_RING = 20


@dataclass
class CircuitBreaker:
    """N회 연속 실패 시 차단 (스레드 안전).

    ★AT2 — 세는 것 옆에 **무엇을 셌는지**를 남긴다★

    `auto_api` 는 이 카운트로 킬스위치를 겨냥하는데, AR 이 드러낸 대로 그 안에는
    장 종료 같은 정상 업무 응답이 섞여 들어간다(`_request` 가 `rt_cd != "0"`
    에서도 `record_failure()` 를 부른다). 예전에는 이 메서드가 **인자를 받지
    않아** breaker 가 눈먼 채로 셌고, 종류는 `last_failure_kind` 한 칸뿐이라
    *"5회 중 몇 회가 업무 응답이었나"* 를 판정 자리에서 알 수 없었다.

    감사 로그로는 답할 수 없다 — `_request` 의 7개 호출부 중 감사 행이 남는
    것은 주문·취소 둘뿐이라, `get_balance` 실패 5회는 어디에도 남지 않는다.
    그래서 ★숫자와 같은 객체에 같은 수명으로★ 기록한다.

    ★링은 카운터와 함께 비워진다★ — `failure_count` 가 0 이 되는 자리는 둘이고
    (`record_success` · `call_allowed` 의 HALF_OPEN 전환) 하나만 비우면 구성이
    **다른 집합**을 설명하게 된다. 넘치면 그 사실이 개수 불일치로 드러난다
    (`failure_streak.streak_composition` 의 `describes_count`).

    ★세는 것은 0줄 바뀌지 않았다★ — 임계값도, 어떤 종류가 카운트되는지도
    그대로다. 그것을 바꾸는 것은 실거래 호출 경로 동작 변경이다(CLAUDE.md §6).
    """
    failure_threshold: int = 5
    reset_timeout_seconds: float = 30.0
    failure_count: int = 0
    last_failure_time: datetime | None = None
    state: str = "CLOSED"
    _lock: threading.Lock = field(default_factory=threading.Lock)
    #: ★경계 있는 링★ — 무제한이면 메모리가 새고 넘침을 감지할 수도 없다.
    _recent_kinds: deque = field(
        default_factory=lambda: deque(maxlen=STREAK_RING))

    def call_allowed(self) -> bool:
        with self._lock:
            if self.state == "OPEN" and self.last_failure_time:
                if (datetime.now() - self.last_failure_time).total_seconds() > self.reset_timeout_seconds:
                    self.state = "HALF_OPEN"
                    self.failure_count = 0
                    # ★카운터와 함께★ — 여기만 빠지면 0회를 5개가 설명한다.
                    self._recent_kinds.clear()
                    return True
                return False
            return True

    def record_success(self):
        with self._lock:
            self.failure_count = 0
            self.state = "CLOSED"
            self._recent_kinds.clear()

    def record_failure(self, kind: str | None = None):
        """연속 실패 하나. `kind` 는 `kis_failure.FAILURE_KINDS` 의 값.

        ★기본값이 관측 행세를 하지 않게★ 모르면 `unknown` 이다 — 어휘 밖의
        값도 마찬가지다(버리지도 믿지도 않는다).
        """
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = datetime.now()
            self._recent_kinds.append(
                kind if kind in FAILURE_KINDS else KIND_UNKNOWN)
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                logger.error(f"Circuit breaker OPEN after {self.failure_count} failures")

    def streak_kinds(self) -> tuple[str, ...]:
        """지금 연속에 기록된 종류들(오래된 것부터). ★스냅샷이다★"""
        with self._lock:
            return tuple(self._recent_kinds)


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
        #: ★마지막 실패의 종류★ — 새 카운터가 아니라 한 칸짜리 기록이다(AR4).
        #: 구성(무엇이 몇 번)의 증거는 `live_orders.reason_code` 와 감사 로그에
        #: 이력으로 쌓인다.
        self.last_failure_kind: str | None = None
        self.last_failure_rt_cd: str | None = None
        self.last_failure_msg_cd: str | None = None
        self.last_failure_status: int | None = None
        self._token_lock = threading.Lock()  # 동시 첫 호출 시 토큰 1회만 발급

    # ─────────────────────────────────────────────────────────────────────
    # OAuth Token
    # ─────────────────────────────────────────────────────────────────────

    def _ensure_token(self):
        """토큰 유효성 확인 + 만료 시 재발급 (스레드 안전: double-checked locking)."""
        if self.token and self.token.is_valid:
            return
        with self._token_lock:
            # 락 안에서 재확인 — 다른 스레드가 이미 발급했으면 재사용(중복 발급 방지)
            if self.token and self.token.is_valid:
                return
            self._fetch_token()

    def prewarm_token(self):
        """병렬 호출 전에 토큰을 1회 미리 확보 (토큰 발급 경쟁 회피). 실패해도 무시."""
        try:
            self._ensure_token()
        except Exception as e:
            logger.debug(f"KIS 토큰 프리워밍 실패(무시): {e}")

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
            # ★`_request` 를 타지 않으므로 breaker 에 기록되지 않는다★(실측 그대로).
            raise KISCallError(f"토큰 발급 실패: {resp.status_code} {resp.text}",
                               kind=KIND_TOKEN, status=resp.status_code)
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

    def _note_failure(self, kind: str, rt_cd=None, status=None,
                      msg_cd=None) -> None:
        """마지막 실패의 종류를 남긴다. ★기록이지 카운팅이 아니다★"""
        self.last_failure_kind = kind
        self.last_failure_rt_cd = rt_cd
        self.last_failure_msg_cd = msg_cd
        self.last_failure_status = status

    def _request(self, method: str, path: str, headers: dict,
                  params: dict | None = None, json_body: dict | None = None) -> dict:
        if not self.circuit_breaker.call_allowed():
            # ★차단은 실패가 아니다★ — 호출 자체를 하지 않았으므로 카운트도 없다.
            raise KISCallError("Circuit breaker OPEN — KIS API 호출 차단됨",
                               kind=KIND_BLOCKED)

        self.rate_limiter.acquire()
        url = f"{self.base_url}{path}"

        try:
            resp = requests.request(
                method=method, url=url, headers=headers,
                params=params, json=json_body, timeout=self.timeout,
            )
            status = getattr(resp, "status_code", None)
            try:
                data = resp.json()
            except Exception as e:                       # noqa: BLE001
                # ★이름만 준다 — 세지는 않는다★(AR2). 예전에는 이 실패가 분류도
                # 기록도 없이 그대로 샜다. `record_failure()` 는 **부르지 않는다**.
                raise KISCallError(f"KIS 응답 본문을 읽을 수 없습니다: {e}",
                                   kind=KIND_MALFORMED, status=status) from e

            # KIS는 HTTP 200 + rt_cd로 성공/실패 구분
            rt_cd = str(data.get("rt_cd", ""))
            if rt_cd != "0":
                # ★열쇠를 잡는다★(AS1) — 예전에는 이 칸을 읽지도 않고 버렸다.
                # 있다고 가정하지 않는다: 없으면 `None` 이고 그것은 미상이다.
                msg_cd = data.get("msg_cd")
                self.circuit_breaker.record_failure(KIND_BUSINESS)
                self._note_failure(KIND_BUSINESS, rt_cd=rt_cd, status=status,
                                   msg_cd=msg_cd)
                raise KISCallError(
                    f"KIS API 실패: rt_cd={rt_cd}, msg={data.get('msg1', 'unknown')}",
                    kind=KIND_BUSINESS, rt_cd=rt_cd, status=status,
                    kis_msg=data.get("msg1"), msg_cd=msg_cd,
                )

            self.circuit_breaker.record_success()
            return data
        except requests.RequestException as e:
            self.circuit_breaker.record_failure(KIND_TRANSPORT)
            self._note_failure(KIND_TRANSPORT)
            raise KISCallError(f"네트워크 오류: {e}", kind=KIND_TRANSPORT) from e

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
            "profit_loss":     float(output2.get("evlu_pfls_smtl_amt") or 0),
            "profit_rate":     float(output2.get("asst_icdc_erng_rt") or 0),
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
                         period: str = "D", start_date: str | None = None,
                         end_date: str | None = None) -> list:
        """
        국내주식 기간별 OHLCV (백테스트·기술지표용).

        Args:
            ticker: 6자리 종목코드
            days:   조회 일수 (KIS는 1회 최대 100건 → 자동 페이지네이션)
            period: D(일)|W(주)|M(월)|Y(년)
            start_date: "YYYY-MM-DD" — 주면 **여기 도달 시 중단**(과다 페치 방지)
            end_date:   "YYYY-MM-DD" — 주면 여기서부터 거슬러 수집(기본 오늘)
        Returns:
            [{date, open, high, low, close, volume}, ...] 과거→현재 순

        ★왜 `start_date` 가 생겼나 — 단위가 어긋나 있었다★
        종료조건은 `len(collected) >= days` 였는데 `collected` 는 **영업일 행**이고
        호출자(`ohlcv_loader`)가 넘기는 `days` 는 **달력일**이다(≈1.45배 크다).
        목표에 도달하지 못해 `max_pages` 까지 돌았고, 3년 요청에 필요한 756봉 대신
        ~1,148봉(**1.52배**)을 받았다.

        환산 계수를 정교하게 맞추는 것은 답이 아니다 — 우리는 요청 구간을 알고
        있으므로 **"가장 오래된 수집 봉이 start_date 이하"** 를 조건으로 쓰면
        추정이 아예 필요 없다. `days` 는 인자를 안 준 호출부를 위한 **폴백**으로만 남는다.
        """
        from datetime import datetime, timedelta

        def _parse(v):
            try:
                return datetime.strptime(v, "%Y-%m-%d") if v else None
            except (TypeError, ValueError):
                return None    # ★지어내지 않는다★ — 못 읽으면 예전 동작으로

        want_from = _parse(start_date)
        stop_at = want_from.strftime("%Y%m%d") if want_from else None

        # KIS inquire-daily-itemchartprice 는 1콜 최대 ~100봉만 반환한다. 장기 역사를 얻으려면
        # 날짜 윈도를 과거로 옮기며 페이지네이션해야 한다. 윈도는 ~120일(영업일 ~80<100)로 잡아
        # 잘림 없이 수집하고, 요청 시작일에 닿거나(또는 days 만큼 모이거나) 더 과거
        # 데이터가 없을 때(상장 시작 도달)까지 반복.
        collected: dict[str, dict] = {}
        end_cursor = _parse(end_date) or datetime.now()
        if want_from:
            # 필요한 달력일 + 여유 1페이지. 영업일/달력일 환산을 추정하지 않는다.
            span = max(1, (end_cursor - want_from).days)
            max_pages = max(1, min(int(span / 110) + 2, 500))
        else:
            max_pages = max(1, min(int(days / 70) + 3, 500))   # 무한루프 방지 상한
        for _ in range(max_pages):
            start_cursor = end_cursor - timedelta(days=120)
            params = {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD":          ticker,
                "FID_INPUT_DATE_1":        start_cursor.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2":        end_cursor.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE":     period,
                # ★`DAILY_PRICE_BASIS` 와 한 몸이다★ 여기를 바꾸면 적재되는
                # `daily_prices.price_basis` 도 따라 바뀐다.
                "FID_ORG_ADJ_PRC":         DAILY_ADJ_PRC_FLAG,
            }
            headers = self._headers(TR_ID["DAILY_CHART"])
            try:
                data = self._request(
                    "GET", "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                    headers, params=params,
                )
            except Exception:
                break  # 윈도 조회 실패 → 지금까지 수집분 반환
            rows = data.get("output2", []) or []
            oldest = None
            new = 0
            for r in rows:
                d = r.get("stck_bsop_date")
                if not d:
                    continue
                if d not in collected:
                    collected[d] = {
                        "date":   d,
                        "open":   float(r.get("stck_oprc") or 0),
                        "high":   float(r.get("stck_hgpr") or 0),
                        "low":    float(r.get("stck_lwpr") or 0),
                        "close":  float(r.get("stck_clpr") or 0),
                        "volume": float(r.get("acml_vol") or 0),
                        "trading_value": float(r.get("acml_tr_pbmn") or 0),
                    }
                    new += 1
                if oldest is None or d < oldest:
                    oldest = d
            if not rows or new == 0 or oldest is None:
                break  # 더 이상 과거 데이터 없음(상장 시작 도달)
            if stop_at is not None:
                if oldest <= stop_at:
                    break          # ★요청 시작일에 닿았다 — 더 받을 이유가 없다★
            elif len(collected) >= days:
                break              # 예전 동작(인자 미지정 호출부)
            end_cursor = datetime.strptime(oldest, "%Y%m%d") - timedelta(days=1)
        result = [collected[d] for d in sorted(collected)]  # 과거→현재
        if stop_at is not None:
            # 구간이 명시됐으면 그 구간이 진실이다 — 달력일 `days` 로 자르면
            # 영업일 행이 그보다 적어 **요청 구간을 다시 잘라먹는다**.
            return [r for r in result if r["date"] >= stop_at]
        return result[-days:] if len(result) > days else result

    def _parse_minute_rows(self, rows: list) -> list[dict]:
        out = []
        for r in rows or []:
            t = r.get("stck_cntg_hour")
            if not t:
                continue
            out.append({
                "time":   str(t),                                   # HHMMSS
                "open":   float(r.get("stck_oprc") or 0),
                "high":   float(r.get("stck_hgpr") or 0),
                "low":    float(r.get("stck_lwpr") or 0),
                "close":  float(r.get("stck_prpr") or 0),           # 분봉 체결가=종가
                "volume": float(r.get("cntg_vol") or 0),
            })
        return out

    def _page_minute_bars(self, path: str, tr_key: str, ticker: str,
                          date: str | None = None, max_calls: int = 16) -> list[dict]:
        """분봉 페이지네이션 — 15:30부터 30건씩 09:00까지 역방향 커서."""
        bars: dict[str, dict] = {}
        cursor = "153000"
        for _ in range(max_calls):
            params = {
                "FID_ETC_CLS_CODE": "",
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": ticker,
                "FID_INPUT_HOUR_1": cursor,
                "FID_PW_DATA_INCU_YN": "Y",
            }
            if date is not None:
                params["FID_INPUT_DATE_1"] = date
                params["FID_FAKE_TICK_INCU_YN"] = ""
            headers = self._headers(TR_ID[tr_key])
            data = self._request("GET", path, headers, params=params)
            page = self._parse_minute_rows(data.get("output2") or [])
            if not page:
                break
            for b in page:
                bars.setdefault(b["time"], b)
            earliest = min(b["time"] for b in page)
            if earliest <= "090100":
                break
            # 다음 커서 = 가장 이른 봉 - 1분
            hh, mm = int(earliest[:2]), int(earliest[2:4])
            total = hh * 60 + mm - 1
            cursor = f"{total // 60:02d}{total % 60:02d}00"
            if cursor < "090000":
                break
        return [bars[t] for t in sorted(bars)]

    def get_minute_bars_today(self, ticker: str) -> list[dict]:
        """당일 1분봉 전체 (FHKST03010200, 30건/콜 자동 페이지네이션 → ~13콜)."""
        return self._page_minute_bars(
            "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            "MINUTE_TODAY", ticker)

    def get_minute_bars_dated(self, ticker: str, date: str) -> list[dict]:
        """과거 특정 일자 1분봉 (FHKST03010230 일별분봉조회).

        소급 한도는 KIS가 문서에 명시하지 않음 — verify_connection 【9】로 실측."""
        return self._page_minute_bars(
            "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice",
            "MINUTE_DAILY", ticker, date=date)

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
        total_pnl = 0.0
        cost_basis = 0.0
        for ticker, pos in self.positions.items():
            cp = self.prices.get(ticker, pos["avg_price"])
            eval_amount = pos["quantity"] * cp
            pnl_pct = (cp / pos["avg_price"] - 1) * 100 if pos["avg_price"] > 0 else 0
            pnl_krw = (cp - pos["avg_price"]) * pos["quantity"]
            evaluated += eval_amount
            total_pnl += pnl_krw
            cost_basis += pos["avg_price"] * pos["quantity"]
            positions.append({
                "ticker": ticker, "quantity": pos["quantity"],
                "avg_price": pos["avg_price"], "current_price": cp,
                "eval_amount": eval_amount,
                "pnl_pct": pnl_pct,
                "pnl_krw": pnl_krw,
            })
        return {
            "cash_krw":        self.cash,
            "evaluated_total": evaluated,
            "stock_value":     evaluated - self.cash,
            "deposit":         self.cash,
            "positions":       positions,
            "n_positions":     len(positions),
            "profit_loss":     total_pnl,
            "profit_rate":     (total_pnl / cost_basis * 100) if cost_basis > 0 else 0.0,
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
            volume = rng.uniform(5e5, 5e6)
            rows.append({
                "date": "MOCK", "open": px - spread*0.3, "high": px + spread,
                "low": px - spread, "close": px, "volume": volume,
                "trading_value": px * volume,
            })
        return rows

    def cancel_order(self, *args, **kwargs):
        return {"msg": "Mock 취소 완료"}


# ═══════════════════════════════════════════════════════════════════════════════
# 통합 팩토리 — .env 기반 자동 분기 (실데이터 연동 진입점)
# ═══════════════════════════════════════════════════════════════════════════════

class KISCredentialsMissing(RuntimeError):
    """운영 모드인데 KIS 자격증명이 없다 — ★합성으로 대체하지 않는다★.

    `mock_allowed()` 는 `KIS_USE_MOCK == "1"` 일 때만 참이다. 그것이 아닌데 키도
    없으면 이 시스템은 **실데이터를 낼 수 없다**. 예전에는 그 상황에서 조용히
    `MockKISClient` 를 돌려줬고, 그래서 난수가 운영 경로로 흘렀다.
    """


_kis_singleton = None
#: ★첫 생성은 한 번만★(BV2) — 동시 첫 호출이 클라이언트를 둘 만들면 같은 앱 키로 토큰을 두 번 받는다
#: (KIS 토큰 발급은 분당 1회). 이미 있으면 잠금 없이 돌려준다(이중 확인).
_kis_singleton_lock = threading.Lock()

#: 사용자 증권 계좌별 클라이언트(BV3) — `account_id` → 클라이언트. 서버 싱글턴과 따로 둔다.
#: 계좌마다 토큰·속도 제한·회로 차단기가 하나씩이다(같은 계좌로 둘을 만들지 않는다).
_account_clients: dict[str, object] = {}
_account_clients_lock = threading.Lock()


def try_kis_client(force_reload: bool = False):
    """`(client, reason)` — 열화가 **맞는** 호출부를 위한 통로.

    적재 보강 훅처럼 "KIS 가 없으면 그냥 그 부분을 건너뛴다" 가 옳은 자리가 있다.
    그런 곳이 `get_kis_client()` 의 예외를 잡느라 `except Exception` 을 넓게 두면
    진짜 오류까지 삼키게 되므로, 의도를 이름으로 드러낸 통로를 따로 준다.

    ★사유 없는 None 은 금지★ — 실패하면 왜인지 함께 돌려준다.
    """
    try:
        return get_kis_client(force_reload=force_reload), None
    except KISCredentialsMissing as e:
        return None, str(e)


def get_kis_client(force_reload: bool = False, *, account_id: str | None = None):
    """
    .env 설정에 따라 KISClient(실) 또는 MockKISClient(가짜)를 반환.

    `account_id` 를 주면 그 사용자 증권 계좌의 클라이언트(BV3 — `broker_accounts` 금고의 자격 ·
    계좌마다 모의/실계좌). ★소유자는 여기서 보지 않는다★ — 경로가 본다. 계좌 클라이언트를 비우는 길은
    `evict_account_client` 이고, `force_reload` 와 함께 주면 거절한다(조용히 무시하지 않는다).

    환경변수:
      KIS_USE_MOCK=1            → MockKISClient (외부 호출 없음)
      KIS_USE_MOCK=0, IS_PAPER=1 → KIS 모의투자
      KIS_USE_MOCK=0, IS_PAPER=0 → KIS 실계좌

    데이터 조회(get_price/get_daily_ohlcv)는 모의·실계좌 모두 가능.
    싱글톤으로 토큰 재사용 (1분당 1회 발급 제한 대응).
    """
    if account_id is not None:
        if force_reload:
            raise ValueError("force_reload 는 서버 클라이언트에만 씁니다 — 계좌 클라이언트는 "
                             "evict_account_client 로 비웁니다.")
        return _account_client(account_id)
    global _kis_singleton
    if _kis_singleton is not None and not force_reload:
        return _kis_singleton
    with _kis_singleton_lock:
        if _kis_singleton is not None and not force_reload:
            return _kis_singleton
        _kis_singleton = _build_kis_client()
        return _kis_singleton


def _account_client(account_id: str):
    client = _account_clients.get(account_id)
    if client is not None:
        return client
    with _account_clients_lock:
        client = _account_clients.get(account_id)
        if client is None:
            client = _build_account_client(account_id)
            _account_clients[account_id] = client
        return client


def evict_account_client(account_id: str) -> None:
    """계좌 클라이언트를 내린다(계좌를 지웠을 때). 없으면 아무 일도 없다."""
    with _account_clients_lock:
        _account_clients.pop(account_id, None)


def _build_account_client(account_id: str):
    """금고의 자격으로 계좌 클라이언트 하나를 만든다. 없거나 풀 수 없으면 예외가 그대로 올라간다
    (`BrokerAccountNotFound` · `CredentialVaultUnavailable`) — ★서버 `.env` 계좌로 대신하지 않는다★."""
    from src.execution.broker_accounts import open_account

    acct = open_account(account_id)
    if mock_allowed():
        # 계좌마다 따로 — mock 잔고·주문이 계좌끼리 섞이지 않게.
        return MockKISClient()
    return KISClient(KISCredentials(
        app_key=acct.app_key,
        app_secret=acct.app_secret,
        account_no=acct.account_no,
        account_prdt=acct.account_prdt,
        is_paper=acct.is_paper,
    ))


def get_order_client():
    """주문 실행기가 쓰는 클라이언트 — ★`get_kis_client()` 와 같은 인스턴스★(BV2).

    예전에는 실거래 실행기(`stage13_routes.get_executor`)가 `.env` 를 직접 읽어 `KISClient` 를 하나 더 만들었다.
    그러면 같은 앱 키로 토큰·속도 제한·회로 차단기가 둘이 되고, 실패 관측(`api_failure_probe`)은 실행기 쪽 차단기를
    보지 못한다. 이제 하나를 같이 쓴다.

    ★주문에는 계좌번호가 필요하다★ — 시세만 쓰는 곳은 계좌번호 없이도 되므로 `get_kis_client()` 는 비어 있어도
    만든다. 주문 실행기는 운영에서 계좌번호가 비면 만들지 않고 사유를 낸다(빈 계좌로 주문을 보내지 않는다).
    """
    client = get_kis_client()
    if mock_allowed():
        return client
    account_no = getattr(getattr(client, "creds", None), "account_no", "")
    if not (account_no or "").strip():
        raise KISCredentialsMissing(
            "KIS_ACCOUNT_NO 미설정 — 주문 실행기를 만들 수 없습니다. 운영 모드에서는 빈 계좌번호로 "
            "주문하지 않습니다. 계좌번호를 설정하거나 개발용으로 KIS_USE_MOCK=1 을 쓰세요.")
    return client


def _build_kis_client():
    """`.env` 로 클라이언트 하나를 만든다 — ★이 파일 밖에서 `KISClient(`·`MockKISClient(` 를 부르지 않는다★
    (`tests/test_single_kis_construction_path.py`)."""
    use_mock = mock_allowed()
    if use_mock:
        logger.info("KIS: MockKISClient (KIS_USE_MOCK=1)")
        return MockKISClient()

    app_key = os.getenv("KIS_APP_KEY", "")
    app_secret = os.getenv("KIS_APP_SECRET", "")
    if not app_key or not app_secret:
        # ★운영에서는 mock 을 돌려주지 않는다★
        # 예전에는 여기서 경고 한 줄을 남기고 `MockKISClient` 를 반환했다. 그것이
        # **mock 게이트 우회로**였다 — 호출부가 `if mock_allowed(): return` 으로
        # 성실히 막아도, 그 직후 이 함수를 부르면 mock 을 받았다(호출부 17곳 중
        # 6곳만 `MockKISClient` 를 직접 확인했다).
        #
        # 실제 사고: `data/market_data.py` 가 그렇게 받은 client 로
        # `get_daily_ohlcv()` 를 불러 `rng.gauss` 난수 일봉을 **운영에서** 받았다.
        #
        # CLAUDE.md §6 — mock 은 `KIS_USE_MOCK` 이 정확히 "1" 일 때만이고,
        # 운영에서 실패하면 합성이 아니라 **사유**를 낸다.
        raise KISCredentialsMissing(
            "KIS_APP_KEY/KIS_APP_SECRET 미설정 — 운영 모드에서는 합성 데이터로 "
            "대체하지 않습니다. 키를 설정하거나 개발용으로 KIS_USE_MOCK=1 을 쓰세요.")

    is_paper = os.getenv("KIS_IS_PAPER", "1") == "1"
    creds = KISCredentials(
        app_key=app_key,
        app_secret=app_secret,
        account_no=os.getenv("KIS_ACCOUNT_NO", ""),
        account_prdt=os.getenv("KIS_ACCOUNT_PRDT", "01"),
        is_paper=is_paper,
    )
    logger.info(f"KIS: 실연동 ({'모의투자' if is_paper else '실계좌'})")
    return KISClient(creds)
