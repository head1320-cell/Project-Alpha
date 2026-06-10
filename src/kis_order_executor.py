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
        """한국 주식시장 호가단위 (2023년 기준) — 원본 그대로."""
        if price < 2_000:    return 1
        if price < 5_000:    return 5
        if price < 20_000:   return 10
        if price < 50_000:   return 50
        if price < 200_000:  return 100
        if price < 500_000:  return 500
        return 1_000

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

        # 주문 구분 결정
        ord_dvsn, ord_unpr = self._determine_order_type(stock_code, strength, target_price)

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
        """시그널 강도 기반 주문 구분 — 원본 그대로."""
        if strength >= 0.8:   # is_strong() 기준
            return ("01", "0")  # 시장가

        if target_price:
            adjusted = self._round_to_tick(int(target_price))
            return ("00", str(adjusted))

        if self._client:
            try:
                info = self._client.get_current_price(stock_code)
                price = info.get("price", 0)
                if price > 0:
                    return ("00", str(self._round_to_tick(int(price))))
            except Exception:
                pass

        return ("01", "0")  # 조회 실패 시 시장가

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
