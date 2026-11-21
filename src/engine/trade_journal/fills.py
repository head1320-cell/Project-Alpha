"""매매일지 — 받은 줄을 체결로 옮긴다(줄 검사 · 정규화). 순수 함수.

통과 못 한 줄은 ★사유와 줄 번호와 함께★ 돌려준다 — 조용히 버리지 않는다.
쉼표·원 기호를 걷는 일은 파일을 읽는 쪽(브라우저)이 한다. 여기서는 어림해 읽지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

#: 버린 줄의 사유 → 화면 문장.
REJECT_REASONS: dict[str, str] = {
    "bad_datetime": "체결 일시를 읽지 못했습니다.",
    "no_symbol": "종목이 비어 있습니다.",
    "bad_side": "매수·매도를 알 수 없습니다.",
    "bad_quantity": "수량이 양수가 아닙니다.",
    "bad_price": "단가가 양수가 아닙니다.",
    "bad_fee": "수수료가 0 이상의 수가 아닙니다.",
    "bad_tax": "세금이 0 이상의 수가 아닙니다.",
}

_WITH_TIME = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y/%m/%d %H:%M:%S",
              "%Y/%m/%d %H:%M", "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y%m%d %H%M%S", "%Y%m%d%H%M%S", "%Y%m%d %H:%M:%S")
_DATE_ONLY = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d")
_MARKETS = ("KOSPI", "KOSDAQ", "KONEX")
_INSTRUMENTS = ("stock", "etf")


@dataclass(frozen=True)
class Fill:
    row: int                    # 받은 순서(0부터) — 버린 줄도 번호를 차지한다
    at: datetime
    has_time: bool              # 시각까지 있는가(날짜만이면 False)
    symbol: str
    side: str                   # "buy" | "sell"
    quantity: float
    price: float
    fee: float | None           # 파일에 있던 수수료(원). 없으면 None
    tax: float | None           # 파일에 있던 세금(원). 없으면 None
    market: str | None
    instrument: str | None
    name: str | None

    @property
    def notional(self) -> float:
        return self.quantity * self.price


def _when(value: Any) -> tuple[datetime, bool] | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in _WITH_TIME:
        try:
            return datetime.strptime(text, fmt), True
        except ValueError:
            continue
    for fmt in _DATE_ONLY:
        try:
            return datetime.strptime(text, fmt), False
        except ValueError:
            continue
    return None


def _number(value: Any) -> float | None:
    """수 또는 수로만 된 글자 → float. 불리언·쉼표 섞인 글자·NaN 은 None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        out = float(value)
    elif isinstance(value, str):
        try:
            out = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


def _optional_amount(value: Any) -> tuple[float | None, bool]:
    """없으면 `(None, True)` · 0 이상의 수면 `(값, True)` · 그 밖은 `(None, False)`."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, True
    n = _number(value)
    return (n, True) if n is not None and n >= 0 else (None, False)


def _choice(value: Any, allowed: tuple[str, ...], upper: bool) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().upper() if upper else value.strip().lower()
    return text if text in allowed else None


def normalize(rows: list[dict]) -> tuple[list[Fill], list[dict]]:
    """받은 줄 → `(체결 목록, 버린 줄 목록)`. 체결은 시각 순이고 같은 시각은 받은 순서다."""
    fills: list[Fill] = []
    rejects: list[dict] = []

    def reject(i: int, reason: str) -> None:
        rejects.append({"row": i, "reason": reason, "message": REJECT_REASONS[reason]})

    for i, r in enumerate(rows):
        r = r if isinstance(r, dict) else {}
        when = _when(r.get("executed_at"))
        if when is None:
            reject(i, "bad_datetime")
            continue
        symbol = str(r.get("symbol") or "").strip()
        if not symbol:
            reject(i, "no_symbol")
            continue
        side = _choice(r.get("side"), ("buy", "sell"), upper=False)
        if side is None:
            reject(i, "bad_side")
            continue
        qty = _number(r.get("quantity"))
        if qty is None or qty <= 0:
            reject(i, "bad_quantity")
            continue
        price = _number(r.get("price"))
        if price is None or price <= 0:
            reject(i, "bad_price")
            continue
        fee, ok = _optional_amount(r.get("fee"))
        if not ok:
            reject(i, "bad_fee")
            continue
        tax, ok = _optional_amount(r.get("tax"))
        if not ok:
            reject(i, "bad_tax")
            continue
        name = str(r.get("name")).strip() if isinstance(r.get("name"), str) and r.get("name").strip() else None
        fills.append(Fill(row=i, at=when[0], has_time=when[1], symbol=symbol, side=side, quantity=qty, price=price,
                          fee=fee, tax=tax, market=_choice(r.get("market"), _MARKETS, upper=True),
                          instrument=_choice(r.get("instrument"), _INSTRUMENTS, upper=False), name=name))
    fills.sort(key=lambda f: (f.at, f.row))
    return fills, rejects
