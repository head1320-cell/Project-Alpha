"""
KIS Order Executor & Position Manager
=======================================
KIS strategy_builder/core/order_executor.py +
           strategy_builder/core/position_manager.py 이식.

원본의 `ka._url_fetch()` → 우리 KISClient 사용.
원본의 `data_fetcher.get_holdings()` → KIS API 직접 호출.

설계 원칙:
  - MOCK 모드: 실제 주문 없음, 로그만 기록
  - REAL 모드: KIS TR 호출 (TTTC0802U 매수 / TTTC0801U 매도)
  - 주문 전 검증 유지 (강도 체크, 중복 체크, 보유 체크)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Data models
# ═══════════════════════════════════════════════════════════════════════════════

class OrderPriceUnavailable(Exception):
    """지정가를 정할 현재가가 없다 — 주문을 시장가로 바꾸지 않고 멈춘다(BV0b)."""


@dataclass
class OrderResult:
    success: bool
    stock_code: str
    stock_name: str
    action: str         # "buy" | "sell"
    quantity: int
    price: float
    order_no: str = ""
    message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "success":    self.success,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "action":     self.action,
            "quantity":   self.quantity,
            "price":      self.price,
            "order_no":   self.order_no,
            "message":    self.message,
            "timestamp":  self.timestamp,
        }


@dataclass
class Position:
    stock_code: str
    stock_name: str
    quantity: int
    avg_price: float
    current_price: float
    eval_amount: float
    profit_loss: float
    profit_rate: float

    def to_dict(self) -> dict:
        return {
            "stock_code":   self.stock_code,
            "stock_name":   self.stock_name,
            "quantity":     self.quantity,
            "avg_price":    self.avg_price,
            "current_price": self.current_price,
            "eval_amount":  self.eval_amount,
            "profit_loss":  self.profit_loss,
            "profit_rate":  self.profit_rate,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Position Manager — 원본 그대로
# ═══════════════════════════════════════════════════════════════════════════════

class PositionManager:
    """보유 포지션 관리. 원본 core/position_manager.py 이식."""

    def __init__(self, client):
        self._client = client
        self._cache: list[Position] | None = None

    def get_positions(self, refresh: bool = False) -> list[Position]:
        if self._cache is None or refresh:
            self._cache = self._fetch_positions()
        return self._cache

    def _fetch_positions(self) -> list[Position]:
        """KIS get_balance()로 보유 종목 조회."""
        try:
            bal = self._client.get_balance()
            positions = []
            for item in bal.get("positions", []):
                positions.append(Position(
                    stock_code=item.get("ticker", ""),
                    stock_name=item.get("name", ""),
                    quantity=int(item.get("quantity", 0)),
                    avg_price=float(item.get("avg_price", 0)),
                    current_price=float(item.get("current_price", 0)),
                    eval_amount=float(item.get("eval_amount", 0)),
                    profit_loss=float(item.get("pnl_krw", 0)),
                    profit_rate=float(item.get("pnl_pct", 0)),
                ))
            return positions
        except Exception as e:
            logger.error(f"get_positions error: {e}")
            return []

    def check_duplicate(self, stock_code: str) -> bool:
        return any(p.stock_code == stock_code for p in self.get_positions())

    def get_holding_quantity(self, stock_code: str) -> int:
        for p in self.get_positions():
            if p.stock_code == stock_code:
                return p.quantity
        return 0

    def refresh(self) -> None:
        self._cache = None


# ═══════════════════════════════════════════════════════════════════════════════
# Order Executor — 원본 그대로
# ═══════════════════════════════════════════════════════════════════════════════

class OrderExecutor:
    """
    주문 실행 — 원본 core/order_executor.py 이식.

    변경사항:
      ka._url_fetch() → self._client.order_cash()
    """

    def __init__(self, client=None, allow_duplicate_buy: bool = True):
        self._client = client
        self.allow_duplicate_buy = allow_duplicate_buy
        self.position_manager = PositionManager(client) if client else None

    # ── 원본 static methods 그대로 ──────────────────────────────────────────

    @staticmethod
    def _get_tick_size(price: int) -> int:
        """한국 주식시장 호가단위 — ★`market_rules` 의 표를 읽는다★ (BD)

        예전에는 이 자리에 표가 따로 있었고(`<`) `market_rules`(`<=`)와 여섯
        경계에서 갈렸다. 표를 하나로 합쳤다 — KRX 원문대로 **미만**. 내림
        가격(`_round_to_tick`)은 1..1,000,000 전수로 이전과 같다(경계가 공배수).
        """
        from src.data.market_rules import tick_size
        return int(tick_size(price))

    @staticmethod
    def _round_to_tick(price: int) -> int:
        """가격을 호가단위로 내림 — 원본 그대로."""
        tick = OrderExecutor._get_tick_size(price)
        return int(math.floor(price / tick) * tick)

    # ── 주문 실행 흐름 (원본 execute_signal 과 동일) ────────────────────────

    def execute(
        self,
        stock_code: str,
        stock_name: str,
        action: str,          # "buy" | "sell"
        strength: float = 1.0,
        quantity: int | None = None,
        target_price: float | None = None,
    ) -> OrderResult:
        """
        시그널을 실제 주문으로 실행.

        1. strength 체크 (< 0.5 → 생략)
        2. 매수: 중복 체크 (allow_duplicate_buy=False 시)
        3. 매도: 보유 여부 체크
        4. 주문 구분 결정 (시장가 / 지정가)
        5. 수량 결정
        6. order_cash() 호출
        """
        if action == "hold":
            return OrderResult(False, stock_code, stock_name, action, 0, 0, message="HOLD 시그널 생략")

        if strength < 0.5:
            return OrderResult(False, stock_code, stock_name, action, 0, 0, message=f"약한 시그널 (strength={strength:.2f})")

        if self.position_manager:
            if action == "buy" and not self.allow_duplicate_buy:
                if self.position_manager.check_duplicate(stock_code):
                    return OrderResult(False, stock_code, stock_name, action, 0, 0, message="이미 보유 중 — 매수 생략")

            if action == "sell":
                qty_held = self.position_manager.get_holding_quantity(stock_code)
                if qty_held <= 0:
                    return OrderResult(False, stock_code, stock_name, action, 0, 0, message="미보유 종목 — 매도 생략")
                if quantity is None:
                    quantity = qty_held

        # 주문 구분 결정 — 지정가를 정할 현재가가 없으면 시장가로 바꾸지 않고 주문하지 않는다(BV0b)
        try:
            ord_dvsn, ord_unpr = self._determine_order_type(stock_code, strength, target_price)
        except OrderPriceUnavailable as e:
            logger.warning(f"주문 생략 [{stock_code}]: {e}")
            return OrderResult(False, stock_code, stock_name, action, 0, 0, message=str(e))

        # 수량 결정
        if quantity is None:
            quantity = 1  # 기본 1주 (실제는 투자금액 기반 계산 필요)

        if quantity <= 0:
            return OrderResult(False, stock_code, stock_name, action, 0, 0, message="주문 수량 0")

        return self._send_order(stock_code, stock_name, action, ord_dvsn, ord_unpr, quantity)

    def _determine_order_type(
        self,
        stock_code: str,
        strength: float,
        target_price: float | None,
    ) -> tuple[str, str]:
        """시그널 강도 기반 주문 구분.

        강한 신호(≥0.8)는 시장가, 목표가가 있으면 그 지정가, 그 밖에는 현재가를 호가단위로 내린 지정가.

        ★BV0b — 조용한 시장가 대체를 없앴다★ 예전에는 현재가를 `get_current_price`(두 클라이언트 어디에도 없는
        메서드)로 묻고 `"price"`(응답에 없는 키)를 읽은 뒤 예외를 삼켜, 이 구간 주문이 ★늘 시장가★로 나갔다.
        이제 현재가는 `get_price()["current_price"]` 로 읽고, 받지 못하면(예외·0·없음) `OrderPriceUnavailable`
        로 주문을 멈춘다 — 지정가를 원한 주문을 시장가로 바꾸지 않는다(CLAUDE.md §4·§6).
        클라이언트가 없으면(`_send_order` 가 MOCK 으로 끝나는 경로) 예전처럼 시장가 표기다 — 실주문이 나가지 않는다.
        """
        if strength >= 0.8:   # is_strong() 기준
            return ("01", "0")  # 시장가

        if target_price:
            adjusted = self._round_to_tick(int(target_price))
            return ("00", str(adjusted))

        if self._client is None:
            return ("01", "0")  # 클라이언트 없음 → `_send_order` 의 MOCK 경로(실주문 없음)

        try:
            info = self._client.get_price(stock_code)
        except Exception as e:
            raise OrderPriceUnavailable(
                f"현재가 조회 실패로 지정가를 정하지 못해 주문하지 않음 ({type(e).__name__}: {e})") from e
        raw = (info or {}).get("current_price")
        try:
            price = float(raw)
        except (TypeError, ValueError):
            price = 0.0
        if not math.isfinite(price) or price <= 0:
            raise OrderPriceUnavailable(
                f"현재가를 받지 못해 지정가를 정하지 못해 주문하지 않음 (current_price={raw!r})")
        return ("00", str(self._round_to_tick(int(price))))

    def _send_order(
        self,
        stock_code: str, stock_name: str, action: str,
        ord_dvsn: str, ord_unpr: str, quantity: int,
    ) -> OrderResult:
        """KIS API 주문 전송 — get_kis_client() 기반 place_order 사용."""

        # 클라이언트 미주입 → MOCK
        if self._client is None:
            logger.info(f"[MOCK 주문] {stock_name}({stock_code}) "
                        f"{'매수' if action=='buy' else '매도'} {quantity}주")
            return OrderResult(
                success=True, stock_code=stock_code, stock_name=stock_name,
                action=action, quantity=quantity,
                price=float(ord_unpr) if ord_unpr != "0" else 0,
                order_no="MOCK-" + datetime.now().strftime("%H%M%S"),
                message="모의 주문 완료 (client 없음)",
            )

        # place_order 파라미터 변환
        side = "BUY" if action == "buy" else "SELL"
        order_type = "MARKET" if ord_dvsn == "01" else "LIMIT"
        price = None if ord_dvsn == "01" else float(ord_unpr)

        try:
            result = self._client.place_order(
                ticker=stock_code, side=side, quantity=int(quantity),
                order_type=order_type, price=price,
            )
            order_no = result.get("kis_order_no") or result.get("order_no") or ""
            # MockKISClient는 항상 성공 반환
            is_mock = type(self._client).__name__ == "MockKISClient"
            if self.position_manager:
                try:
                    self.position_manager.refresh()
                except Exception:
                    pass
            return OrderResult(
                success=True, stock_code=stock_code, stock_name=stock_name,
                action=action, quantity=quantity,
                price=price or 0,
                order_no=str(order_no),
                message=("모의 주문 완료" if is_mock else "실주문 접수") + f" ({result.get('msg','')})",
            )
        except Exception as e:
            return OrderResult(
                False, stock_code, stock_name, action, quantity, 0,
                message=f"주문 실행 오류: {e}",
            )
