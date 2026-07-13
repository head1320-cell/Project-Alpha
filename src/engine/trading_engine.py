"""
Trading Engine — Screener V3 실거래 자동매매 오케스트레이터
==========================================================================
시그널 → 안전장치 검증 → KIS 주문 → 체결 추적의 전 과정 조율.

★ 안전 최우선 설계 ★
  실제 자금이 움직이므로 다층 안전장치:
    1. Kill Switch     — 전역 중단 (모든 주문 차단)
    2. 일일 손실 한도   — 손실 X% 초과 시 신규 매수 중단
    3. 주문 금액 상한   — 종목당/일일 최대 투자금
    4. 포지션 수 제한   — 동시 보유 종목 수
    5. 중복 매수 방지   — 이미 보유 종목
    6. 모드 명시        — paper(모의)/real(실계좌) 명확 구분
    7. Dry-run         — 실주문 없이 시뮬만

★ 자금 관리 ★
  포지션 사이징: 자본 대비 비중 또는 고정 금액.
  현재가 조회하여 매수 가능 수량 계산.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 안전장치 설정
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SafetyConfig:
    """자동매매 안전장치 — 보수적 기본값."""
    kill_switch: bool = False              # True면 모든 주문 차단
    dry_run: bool = True                   # True면 실주문 없이 시뮬 (기본 안전)
    max_position_pct: float = 0.20         # 종목당 최대 자본 비중 (20%)
    max_order_amount_krw: float = 10_000_000  # 종목당 최대 주문액 (1천만원)
    max_daily_invest_krw: float = 50_000_000  # 일일 최대 신규 투자액
    max_positions: int = 10                # 동시 최대 보유 종목
    daily_loss_limit_pct: float = -5.0     # 일일 손실 한도 (-5% 도달 시 매수 중단)
    min_order_amount_krw: float = 100_000  # 최소 주문액 (10만원)
    allow_duplicate_buy: bool = False      # 중복 매수 허용 여부

    def validate(self) -> list[str]:
        warns = []
        if not self.dry_run:
            warns.append("⚠ dry_run=False — 실제 주문이 발주됩니다")
        if self.kill_switch:
            warns.append("⛔ kill_switch=True — 모든 주문이 차단됩니다")
        return warns


@dataclass
class TradeSignal:
    """매매 시그널."""
    stock_code: str
    stock_name: str
    action: str               # "buy" | "sell" | "hold"
    strength: float = 1.0     # 0~1 (신호 강도)
    target_weight: float | None = None  # 목표 비중 (리밸런싱용)
    reason: str = ""


@dataclass
class TradeRecord:
    """실행 기록."""
    timestamp: str
    stock_code: str
    stock_name: str
    action: str
    quantity: int
    price: float
    amount_krw: float
    success: bool
    order_no: str
    message: str
    blocked_by: str | None = None  # 안전장치 차단 사유

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════════════════
# Trading Engine
# ═══════════════════════════════════════════════════════════════════════════════

class TradingEngine:
    """
    자동매매 오케스트레이터.

    사용:
        engine = TradingEngine(safety=SafetyConfig(dry_run=True))
        result = engine.execute_signals([
            TradeSignal("005930", "삼성전자", "buy", strength=1.0),
        ])
    """

    def __init__(self, safety: SafetyConfig | None = None, client=None):
        self.safety = safety or SafetyConfig()
        # 클라이언트: 주입 또는 팩토리
        if client is None:
            from src.execution.kis_client import get_kis_client
            client = get_kis_client()
        self.client = client
        self.is_mock = type(client).__name__ == "MockKISClient"

        from src.kis_order_executor import OrderExecutor, PositionManager
        self.executor = OrderExecutor(
            client=client, allow_duplicate_buy=self.safety.allow_duplicate_buy)
        self.position_manager = PositionManager(client)

        # 일일 추적 (날짜 바뀌면 리셋)
        self._today = date.today()
        self._daily_invested = 0.0
        self._records: list[TradeRecord] = []

    # ── 안전장치 ────────────────────────────────────────────────────────────

    def _reset_daily_if_needed(self):
        if date.today() != self._today:
            self._today = date.today()
            self._daily_invested = 0.0
            logger.info("일일 추적 리셋")

    def _check_safety(self, signal: TradeSignal, amount_krw: float,
                      balance: dict) -> str | None:
        """주문 전 안전장치 검사. 차단 사유 반환 (통과 시 None)."""
        self._reset_daily_if_needed()

        # 1. Kill switch
        if self.safety.kill_switch:
            return "kill_switch 활성 — 모든 주문 차단"

        # 매수에만 적용되는 한도
        if signal.action == "buy":
            # 2. 일일 손실 한도
            total = balance.get("evaluated_total", 0)
            deposit = balance.get("deposit", 0) or balance.get("cash_krw", 0)
            if deposit > 0:
                daily_pnl_pct = (total - deposit) / deposit * 100
                if daily_pnl_pct <= self.safety.daily_loss_limit_pct:
                    return f"일일 손실 한도 도달 ({daily_pnl_pct:.1f}% ≤ {self.safety.daily_loss_limit_pct}%)"

            # 3. 주문 금액 상한
            if amount_krw > self.safety.max_order_amount_krw:
                return f"주문액 초과 ({amount_krw:,.0f} > {self.safety.max_order_amount_krw:,.0f})"
            if amount_krw < self.safety.min_order_amount_krw:
                return f"주문액 미달 ({amount_krw:,.0f} < {self.safety.min_order_amount_krw:,.0f})"

            # 4. 일일 투자 한도
            if self._daily_invested + amount_krw > self.safety.max_daily_invest_krw:
                return f"일일 투자 한도 초과 (누적 {self._daily_invested:,.0f} + {amount_krw:,.0f})"

            # 5. 포지션 수 제한
            n_pos = balance.get("n_positions", len(balance.get("positions", [])))
            if n_pos >= self.safety.max_positions:
                return f"최대 보유 종목 수 도달 ({n_pos} ≥ {self.safety.max_positions})"

            # 6. 현금 부족
            cash = balance.get("cash_krw", 0)
            if amount_krw > cash:
                return f"현금 부족 (필요 {amount_krw:,.0f} > 보유 {cash:,.0f})"

        return None

    # ── 포지션 사이징 ────────────────────────────────────────────────────────

    def _calc_quantity(self, stock_code: str, signal: TradeSignal,
                       balance: dict) -> tuple[int, float, float]:
        """
        매수 수량 계산. Returns (수량, 단가, 주문액).
        목표비중 있으면 비중 기반, 없으면 max_position_pct 사용.
        """
        try:
            quote = self.client.get_price(stock_code)
            price = quote.get("current_price", 0)
        except Exception:
            price = 0
        if price <= 0:
            return 0, 0, 0

        total_capital = balance.get("evaluated_total", 0) or balance.get("cash_krw", 0)
        weight = signal.target_weight if signal.target_weight else self.safety.max_position_pct
        target_amount = min(
            total_capital * weight,
            self.safety.max_order_amount_krw,
        )
        qty = int(target_amount // price)
        return qty, price, qty * price

    # ── 메인 실행 ────────────────────────────────────────────────────────────

    def execute_signals(self, signals: list[TradeSignal]) -> dict:
        """
        시그널 리스트를 순차 실행 (안전장치 적용).

        Returns:
            {
              "mode": "dry_run"|"paper"|"real",
              "executed": [...], "blocked": [...],
              "summary": {...}
            }
        """
        balance = self._safe_balance()
        executed, blocked = [], []

        # 매도 먼저 (현금 확보), 매수 나중, 그 외(hold 등)는 순서 무관 — sells+buys만 돌면
        # hold 시그널이 통째로 누락돼 executed/blocked 어디에도 안 잡히는 버그였음
        sells = [s for s in signals if s.action == "sell"]
        buys = [s for s in signals if s.action == "buy"]
        others = [s for s in signals if s.action not in ("sell", "buy")]

        for signal in sells + buys + others:
            rec = self._execute_one(signal, balance)
            if rec.blocked_by:
                blocked.append(rec.to_dict())
            else:
                executed.append(rec.to_dict())
                if rec.success and signal.action == "buy":
                    self._daily_invested += rec.amount_krw
                    # 잔고 갱신 (다음 안전장치 검사 정확도)
                    balance = self._safe_balance(refresh=True)

        mode = "dry_run" if self.safety.dry_run else ("paper" if self.is_mock or getattr(self.client.creds, "is_paper", True) else "real")
        return {
            "mode": mode,
            "executed": executed,
            "blocked": blocked,
            "summary": {
                "n_signals": len(signals),
                "n_executed": len(executed),
                "n_blocked": len(blocked),
                "daily_invested_krw": self._daily_invested,
                "warnings": self.safety.validate(),
            },
            "timestamp": datetime.now().isoformat(),
        }

    def _execute_one(self, signal: TradeSignal, balance: dict) -> TradeRecord:
        """단일 시그널 실행."""
        now = datetime.now().isoformat()

        if signal.action == "hold":
            return TradeRecord(now, signal.stock_code, signal.stock_name, "hold",
                               0, 0, 0, False, "", "HOLD", blocked_by="hold")

        # 수량/금액 산정
        if signal.action == "buy":
            qty, price, amount = self._calc_quantity(signal.stock_code, signal, balance)
        else:  # sell — 보유 전량
            held = self.position_manager.get_holding_quantity(signal.stock_code)
            try:
                price = self.client.get_price(signal.stock_code).get("current_price", 0)
            except Exception:
                price = 0
            qty, amount = held, held * price

        if qty <= 0:
            return TradeRecord(now, signal.stock_code, signal.stock_name, signal.action,
                               0, price, 0, False, "",
                               "수량 0 (현금부족/미보유)", blocked_by="zero_qty")

        # 안전장치
        blocked = self._check_safety(signal, amount, balance)
        if blocked:
            logger.warning(f"주문 차단 [{signal.stock_code}]: {blocked}")
            return TradeRecord(now, signal.stock_code, signal.stock_name, signal.action,
                               qty, price, amount, False, "", blocked, blocked_by=blocked)

        # Dry-run: 실주문 없이 시뮬
        if self.safety.dry_run:
            return TradeRecord(now, signal.stock_code, signal.stock_name, signal.action,
                               qty, price, amount, True, "DRY-RUN",
                               f"[모의계산] {signal.action} {qty}주 @ {price:,.0f} = {amount:,.0f}원")

        # 실제 주문
        result = self.executor.execute(
            stock_code=signal.stock_code, stock_name=signal.stock_name,
            action=signal.action, strength=signal.strength, quantity=qty,
        )
        return TradeRecord(now, signal.stock_code, signal.stock_name, signal.action,
                           qty, result.price or price, amount,
                           result.success, result.order_no or "", result.message)

    # ── 헬퍼 ────────────────────────────────────────────────────────────────

    def _safe_balance(self, refresh: bool = False) -> dict:
        """잔고 조회 (실패 시 빈 구조)."""
        try:
            return self.client.get_balance()
        except Exception as e:
            logger.error(f"잔고 조회 실패: {e}")
            return {"cash_krw": 0, "evaluated_total": 0, "positions": [], "n_positions": 0}

    def get_account_status(self) -> dict:
        """현재 계좌 상태 (UI용)."""
        bal = self._safe_balance()
        return {
            "mode": "mock" if self.is_mock else ("paper" if getattr(getattr(self.client, "creds", None), "is_paper", True) else "real"),
            "cash_krw": bal.get("cash_krw", 0),
            "evaluated_total": bal.get("evaluated_total", 0),
            "stock_value": bal.get("stock_value", 0),
            "n_positions": bal.get("n_positions", 0),
            "positions": bal.get("positions", []),
            "safety": asdict(self.safety),
        }
