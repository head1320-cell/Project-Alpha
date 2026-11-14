"""체결가 규칙 — 설계 §6.3 (분봉 백테스트). 순수 함수.

모든 맞춤은 ★불리한 쪽★이다: 사는 값은 호가 단위로 올리고 파는 값은 내린다. 슬리피지는 틱 수로 받는다(가정 — 0 도 가정이다).
호가 단위는 `market_rules.tick_size` 하나에서 온다(주식 표 — ETF 의 호가 단위는 다르고, 그 차이는 시뮬레이터가 가정으로 센다).

- 시장가: 그 봉의 시가 ± 슬리피지.
- 손절(역지정가 매도): 봉 저가가 손절가에 닿으면 걸린다. ★갭으로 열리면 손절가가 아니라 시가에 맞는다.★
- 익절(지정가 매도): 봉 고가가 익절가를 ★한 틱 이상 넘었을 때만★ 체결로 친다 — 닿기만 한 지정가는 체결을 장담할 수 없다.
- 미리 건 매수(역지정가 매수): 봉 고가가 그 값에 닿으면 걸리고, 갭으로 넘어 열리면 시가에 맞는다.
"""
from __future__ import annotations

import math

from src.data.market_rules import round_to_tick, tick_size


def _positive(price: float) -> float:
    if not (isinstance(price, (int, float)) and math.isfinite(price) and price > 0):
        raise ValueError(f"가격이 양수가 아니다: {price!r}")
    return float(price)


def _ticks(ticks: int) -> int:
    if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 0:
        raise ValueError(f"슬리피지 틱은 0 이상의 정수여야 한다: {ticks!r}")
    return ticks


def buy_market(raw: float, ticks: int) -> float:
    """사는 값 — 호가 단위로 올린 뒤 슬리피지 틱을 더한다."""
    price = round_to_tick(_positive(raw), "up")
    return round_to_tick(price + _ticks(ticks) * tick_size(price), "up")


def sell_market(raw: float, ticks: int) -> float:
    """파는 값 — 호가 단위로 내린 뒤 슬리피지 틱을 뺀다. 1원 아래로는 내려가지 않는다."""
    price = max(1.0, round_to_tick(_positive(raw), "down"))
    return max(1.0, round_to_tick(max(1.0, price - _ticks(ticks) * tick_size(price)), "down"))


def stop_sell(stop: float, *, bar_open: float, bar_low: float, ticks: int) -> float | None:
    """손절 — 걸리지 않으면 `None`."""
    if bar_low > stop:
        return None
    return sell_market(min(stop, bar_open), ticks)


def limit_sell(target: float, *, bar_open: float, bar_high: float) -> float | None:
    """익절 — 한 틱 이상 넘어 거래됐을 때만. 갭으로 넘어 열리면 시가에 맞는다. 슬리피지는 없다(지정가)."""
    target = round_to_tick(_positive(target), "up")
    if bar_high < target + tick_size(target):
        return None
    return max(target, round_to_tick(bar_open, "down"))


def stop_buy(level: float, *, bar_open: float, bar_high: float, ticks: int) -> float | None:
    """미리 건 매수 — 걸리지 않으면 `None`."""
    level = round_to_tick(_positive(level), "up")
    if bar_high < level:
        return None
    return buy_market(max(level, bar_open), ticks)


def _pct(pct: float) -> float:
    if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not 0 < pct < 100:
        raise ValueError(f"비율(%)은 0 과 100 사이여야 한다: {pct!r}")
    return float(pct)


def stop_level(entry: float, pct: float) -> float:
    """진입가에서 `pct`% 아래의 손절가 — 호가 단위로 내린다(더 늦게 걸리는 쪽)."""
    return max(1.0, round_to_tick(_positive(entry) * (1 - _pct(pct) / 100.0), "down"))


def target_level(entry: float, pct: float) -> float:
    """진입가에서 `pct`% 위의 익절가 — 호가 단위로 올린다(더 닿기 어려운 쪽)."""
    return round_to_tick(_positive(entry) * (1 + _pct(pct) / 100.0), "up")


def quantity(amount: float, price: float) -> int:
    """그 금액으로 살 수 있는 온 주식 수."""
    return int(_positive(amount) // _positive(price))


def capped(qty: int, *, bar_volume: float, cap: float | None) -> int:
    """참여율 상한 — 그 봉 거래량의 `cap` 배까지만. `cap` 이 없으면 그대로(상한 없음도 가정이다)."""
    if cap is None:
        return int(qty)
    return int(min(qty, math.floor(max(0.0, bar_volume) * cap + 1e-9)))
