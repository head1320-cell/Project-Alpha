"""체결가 규칙 — 설계 §6.3 의 표를 줄마다 손으로 계산해 건다 (분봉 백테스트 W4b b3).

호가 단위(2023-01-25 표): 2,000원 미만 1 · 5,000원 미만 5 · 20,000원 미만 10 · 50,000원 미만 50 · 200,000원 미만 100 …
모든 맞춤은 ★불리한 쪽★이다 — 사는 값은 올리고 파는 값은 내린다. 닿기만 한 지정가는 체결로 치지 않는다.
"""
from __future__ import annotations

import pytest

from src.engine.intraday import fills


# ── 시장가(다음 봉 시가 ± 슬리피지) ─────────────────────────────────────────────────────
def test_a_market_buy_pays_the_open_plus_slippage_ticks():
    assert fills.buy_market(10_000, 1) == 10_010          # 10,000원대의 호가 단위는 10원
    assert fills.buy_market(10_000, 2) == 10_020
    assert fills.buy_market(10_000, 0) == 10_000          # 슬리피지 0 은 0 이라는 가정이다


def test_a_market_sell_receives_the_open_minus_slippage_ticks():
    assert fills.sell_market(10_000, 1) == 9_990
    assert fills.sell_market(60_000, 1) == 59_900         # 50,000원 이상 200,000원 미만은 100원 단위
    assert fills.sell_market(10_000, 0) == 10_000


def test_an_off_tick_price_is_rounded_against_the_trader():
    assert fills.buy_market(10_003, 0) == 10_010          # 사는 값은 올림
    assert fills.sell_market(10_007, 0) == 10_000         # 파는 값은 내림
    assert fills.buy_market(10_003, 1) == 10_020 and fills.sell_market(10_007, 1) == 9_990


def test_slippage_uses_the_tick_of_the_price_band_it_starts_in():
    assert fills.buy_market(1_999, 1) == 2_000            # 1,999원의 호가 단위는 1원
    assert fills.sell_market(2_000, 1) == 1_995           # 2,000원의 호가 단위는 5원


# ── 손절(역지정가 매도) ────────────────────────────────────────────────────────────────
def test_a_stop_fills_at_the_stop_less_slippage_when_the_bar_trades_down_to_it():
    assert fills.stop_sell(9_800, bar_open=9_900, bar_low=9_790, ticks=1) == 9_790
    assert fills.stop_sell(9_800, bar_open=9_900, bar_low=9_800, ticks=1) == 9_790     # 닿으면 걸린다
    assert fills.stop_sell(9_800, bar_open=9_900, bar_low=9_790, ticks=0) == 9_800


def test_a_stop_that_is_not_reached_does_not_fill():
    assert fills.stop_sell(9_800, bar_open=9_900, bar_low=9_810, ticks=1) is None


def test_a_gap_through_the_stop_fills_at_the_open_not_at_the_stop():
    """★갭으로 열리면 손절가가 아니라 시가에 맞는다★ — 손절가에 팔았다고 치면 손실이 줄어 보인다."""
    assert fills.stop_sell(9_800, bar_open=9_700, bar_low=9_650, ticks=1) == 9_690
    assert fills.stop_sell(9_800, bar_open=9_700, bar_low=9_650, ticks=0) == 9_700


# ── 익절(지정가 매도) ──────────────────────────────────────────────────────────────────
def test_a_target_fills_only_when_the_bar_trades_through_it_by_a_tick():
    assert fills.limit_sell(10_300, bar_open=10_100, bar_high=10_300) is None          # 닿기만 했다
    assert fills.limit_sell(10_300, bar_open=10_100, bar_high=10_310) == 10_300        # 한 틱 넘었다 — 슬리피지 없음
    assert fills.limit_sell(10_300, bar_open=10_100, bar_high=10_290) is None


def test_a_gap_above_the_target_fills_at_the_open():
    assert fills.limit_sell(10_300, bar_open=10_350, bar_high=10_400) == 10_350
    assert fills.limit_sell(10_300, bar_open=10_300, bar_high=10_300) is None          # 시가가 꼭 그 값이면 닿은 것뿐이다


# ── 미리 건 매수(역지정가 매수) ────────────────────────────────────────────────────────
def test_a_resting_buy_fills_at_the_level_plus_slippage_when_reached():
    assert fills.stop_buy(10_200, bar_open=10_100, bar_high=10_200, ticks=1) == 10_210
    assert fills.stop_buy(10_200, bar_open=10_100, bar_high=10_190, ticks=1) is None


def test_a_resting_buy_gapped_over_fills_at_the_open():
    assert fills.stop_buy(10_200, bar_open=10_250, bar_high=10_300, ticks=1) == 10_260


def test_an_off_tick_level_is_raised_to_the_next_tick_before_it_can_trigger():
    assert fills.stop_buy(10_204.5, bar_open=10_100, bar_high=10_205, ticks=0) is None   # 10,210 이 돼야 걸린다
    assert fills.stop_buy(10_204.5, bar_open=10_100, bar_high=10_210, ticks=0) == 10_210


# ── 손절가·익절가 ──────────────────────────────────────────────────────────────────────
def test_stop_and_target_levels_are_set_from_the_entry_price_on_tick():
    assert fills.stop_level(10_010, 2.0) == 9_800          # 10,010 × 0.98 = 9,809.8 → 내림 9,800
    assert fills.target_level(10_010, 3.0) == 10_320       # 10,010 × 1.03 = 10,310.3 → 올림 10,320
    assert fills.stop_level(10_000, 2.0) == 9_800 and fills.target_level(10_000, 3.0) == 10_300


# ── 수량 ─────────────────────────────────────────────────────────────────────────────
def test_quantity_is_the_whole_shares_the_amount_buys():
    assert fills.quantity(1_000_000, 10_010) == 99          # 99.9 주 → 99주
    assert fills.quantity(10_010, 10_010) == 1
    assert fills.quantity(5_000, 10_010) == 0               # 한 주도 못 산다


def test_the_participation_cap_limits_the_fill_to_a_share_of_the_bar_volume():
    assert fills.capped(99, bar_volume=500, cap=0.1) == 50
    assert fills.capped(40, bar_volume=500, cap=0.1) == 40
    assert fills.capped(99, bar_volume=500, cap=None) == 99     # 상한 없음 — 그것도 가정이다
    assert fills.capped(99, bar_volume=0, cap=0.1) == 0
    assert fills.capped(99, bar_volume=9, cap=0.1) == 0         # 0.9 주 → 0


@pytest.mark.parametrize("call", [
    lambda: fills.buy_market(0, 1), lambda: fills.sell_market(-5, 1), lambda: fills.buy_market(10_000, -1),
    lambda: fills.quantity(1_000, 0), lambda: fills.stop_level(10_000, 0), lambda: fills.target_level(10_000, -1),
    lambda: fills.stop_level(10_000, 100),
])
def test_nonsense_inputs_raise_rather_than_return_a_price(call):
    with pytest.raises(ValueError):
        call()


def test_a_sell_never_goes_to_zero_or_below():
    assert fills.sell_market(2, 5) == 1                     # 1원 아래로는 내려가지 않는다
