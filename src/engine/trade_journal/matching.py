"""매매일지 — 왕복 매칭. 순수 함수.

단위는 둘이다.
- **묶음 맞추기**(`Match`) — 매도 수량을 그 종목의 가장 오래된 매수 수량부터 맞춘다(선입선출). 손익은 여기서 나온다.
- **거래(왕복)**(`Trade`) — 보유 수량이 0 에서 시작해 다시 0 이 될 때까지. 나눠 사고 나눠 팔아도 한 번이다.

파일이 끝났는데 0 으로 돌아오지 않은 거래는 미청산이다 — 남은 수량을 평가하지 않는다(시세가 없다).
매수 기록 없는 매도는 손익을 계산하지 않고 따로 센다(파일 시작 전에 산 것일 수 있다 · 공매도는 다루지 않는다).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.engine.trade_journal.fills import Fill

#: 수량이 이보다 작으면 0 으로 본다(소수 수량의 뺄셈 오차).
_EPS = 1e-9


@dataclass(frozen=True)
class Match:
    """매수 체결 한 건의 일부와 매도 체결 한 건의 일부를 맞춘 것."""
    quantity: float
    buy: Fill
    sell: Fill

    @property
    def gross(self) -> float:
        return (self.sell.price - self.buy.price) * self.quantity


@dataclass
class Trade:
    symbol: str
    name: str | None
    fills: list[Fill] = field(default_factory=list)
    matches: list[Match] = field(default_factory=list)
    open_quantity: float = 0.0
    closed_at: datetime | None = None

    @property
    def closed(self) -> bool:
        return self.closed_at is not None

    @property
    def opened_at(self) -> datetime:
        return self.fills[0].at

    @property
    def has_time(self) -> bool:
        """이 거래의 체결이 전부 시각까지 갖고 있는가 — 아니면 보유 시간·시간대를 말하지 않는다."""
        return all(f.has_time for f in self.fills)

    @property
    def realized_gross(self) -> float:
        """이미 맞춘 묶음의 손익(비용 앞) — 미청산 거래에도 있다."""
        return sum(m.gross for m in self.matches)

    @property
    def gross(self) -> float | None:
        """거래의 손익(비용 앞). ★미청산이면 `None`★ — 끝나지 않은 거래의 손익은 정해지지 않았다."""
        return self.realized_gross if self.closed else None

    @property
    def holding_seconds(self) -> int | None:
        if not self.closed or not self.has_time:
            return None
        return int((self.closed_at - self.opened_at).total_seconds())

    @property
    def same_day(self) -> bool | None:
        return None if not self.closed else self.opened_at.date() == self.closed_at.date()

    @property
    def buy_quantity(self) -> float:
        return sum(f.quantity for f in self.fills if f.side == "buy")

    @property
    def sell_quantity(self) -> float:
        return sum(m.quantity for m in self.matches)

    @property
    def buy_amount(self) -> float:
        return sum(f.notional for f in self.fills if f.side == "buy")

    @property
    def sell_amount(self) -> float:
        return sum(m.quantity * m.sell.price for m in self.matches)


@dataclass
class MatchResult:
    trades: list[Trade]                 # 청산된 것(청산 순) 다음에 미청산(시작 순)
    unmatched_sells: list[dict]         # 맞출 매수가 없던 매도 — {row, symbol, quantity, reason}


def match(fills: list[Fill]) -> MatchResult:
    """시각 순 체결 → 거래(왕복)와 매수 없는 매도."""
    lots: dict[str, list[list]] = {}        # 종목 → [[매수 체결, 남은 수량], …] (오래된 것부터)
    current: dict[str, Trade] = {}
    done: list[Trade] = []
    unmatched: list[dict] = []

    for f in fills:
        if f.side == "buy":
            trade = current.get(f.symbol)
            if trade is None:
                trade = current[f.symbol] = Trade(symbol=f.symbol, name=f.name)
            trade.fills.append(f)
            trade.open_quantity += f.quantity
            lots.setdefault(f.symbol, []).append([f, f.quantity])
            continue

        trade = current.get(f.symbol)
        left = f.quantity
        if trade is not None:
            trade.fills.append(f)
            queue = lots[f.symbol]
            while left > _EPS and queue:
                buy, remaining = queue[0]
                take = min(left, remaining)
                trade.matches.append(Match(quantity=take, buy=buy, sell=f))
                left -= take
                queue[0][1] = remaining - take
                trade.open_quantity -= take
                if queue[0][1] <= _EPS:
                    queue.pop(0)
            if trade.open_quantity <= _EPS:
                trade.open_quantity = 0.0
                trade.closed_at = f.at
                done.append(trade)
                del current[f.symbol]
        if left > _EPS:
            unmatched.append({"row": f.row, "symbol": f.symbol, "quantity": left, "reason": "no_position"})

    still_open = sorted(current.values(), key=lambda t: (t.opened_at, t.fills[0].row))
    return MatchResult(trades=done + still_open, unmatched_sells=unmatched)
