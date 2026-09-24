"""BC5 · ★호가 표가 두 벌이고 경계 여섯 곳에서 갈린다★ — 이름 붙이고 고치지 않는다
==============================================================================
대상(읽기만): `src/data/market_rules.py::tick_size` ·
`src/kis_order_executor.py::OrderExecutor._get_tick_size`

## 실측 (2026-09-24)

`market_rules` 는 `price <= 2000 → 1원`, 실주문 경로 `OrderExecutor` 는
`price < 2000 → 1원`(즉 2,000원은 5원). **여섯 경계 전부**에서 다른 틱을 낸다.
기존 `test_tick_size_table` 은 내부값만(1500·3000·12000…) 재고 경계는 한 번도
안 쟀다 — ★그래서 살아남았다★.

## ★영향 범위는 좁다 — 그것도 잰다★

여섯 경계가 **전부 두 틱의 공배수**라 `is_on_tick`·반올림은 같은 답을 낸다.
갈리는 것은 *"다음 호가"*(`price + tick`) — 2,000 → 2,001(주문 불가) vs 2,005.
BC 의 반올림이 이 불일치의 영향을 **안 받는** 근거가 이 파일이다.

## ★고치지 않는다★

`OrderExecutor` 는 실주문 경로(CLAUDE.md §6 최우선)이고, `market_rules` 를 고치면
`execution_plan` 보고값이 바뀐다. 1차 출처(KRX)는 이 환경에서 CONNECT 403 이다.
★어느 쪽이 맞는지는 사용자가 답할 미상★ 으로 로드맵에 등록했다.
"""
from __future__ import annotations

import pytest

from src.data import market_rules as mr
from src.kis_order_executor import OrderExecutor

#: ★관측으로 고정한 경계★ — 이 목록이 red 가 되면 누가 한쪽 표를 고친 것이다.
BOUNDARIES = (2_000, 5_000, 20_000, 50_000, 200_000, 500_000)

#: 경계에서 두 표가 내는 틱(관측). (market_rules, OrderExecutor)
OBSERVED_AT_BOUNDARY = {
    2_000: (1, 5), 5_000: (5, 10), 20_000: (10, 50),
    50_000: (50, 100), 200_000: (100, 500), 500_000: (500, 1_000),
}

INTERIOR = (1, 1_500, 1_999, 2_001, 3_000, 4_999, 5_001, 12_000, 19_999,
            20_001, 35_000, 49_999, 50_001, 120_000, 199_999, 200_001,
            350_000, 499_999, 500_001, 1_000_000)


@pytest.mark.parametrize("price", INTERIOR)
def test_the_two_tables_agree_away_from_the_boundaries(price):
    """★짝★ — 불일치가 경계에만 있다는 진술의 반쪽."""
    assert mr.tick_size(price) == OrderExecutor._get_tick_size(price)


@pytest.mark.parametrize("price", BOUNDARIES)
def test_the_two_tables_disagree_at_every_boundary_as_observed(price):
    """변이 n — ★관측으로 고정★ red 가 되면 *"누가 맞췄다 — 기록을 갱신하라"*.

    두 표 중 하나를 몰래 고치면 여기서 죽는다. 고친 것이 옳을 수도 있다 —
    그때는 이 관측과 로드맵의 미상을 **함께** 갱신한다.
    """
    got = (mr.tick_size(price), OrderExecutor._get_tick_size(price))
    assert got == OBSERVED_AT_BOUNDARY[price], got
    assert got[0] != got[1]


def test_the_boundary_list_is_the_whole_disagreement():
    """★경계를 손으로 고르지 않았다★ — 1원 단위로 훑어 갈리는 가격을 전부 찾는다."""
    found = [p for p in range(1, 600_001)
             if mr.tick_size(p) != OrderExecutor._get_tick_size(p)]
    assert tuple(found) == BOUNDARIES, found[:20]


@pytest.mark.parametrize("price", BOUNDARIES)
def test_on_tick_and_rounding_agree_at_the_boundaries(price):
    """★BC 가 이 불일치의 영향을 안 받는 근거★ — 경계가 두 틱의 공배수다."""
    a, b = OBSERVED_AT_BOUNDARY[price]
    assert price % a == 0 and price % b == 0
    assert mr.is_on_tick(price)
    assert OrderExecutor._round_to_tick(price) == price
    for d in ("up", "down", "nearest"):
        assert mr.round_to_tick(price, d) == price


@pytest.mark.parametrize("price", BOUNDARIES)
def test_the_next_tick_is_where_they_really_split(price):
    """★갈리는 곳은 "다음 호가" 다★ — 2,000 의 다음이 2,001 인가 2,005 인가."""
    nxt_rules = price + mr.tick_size(price)
    nxt_exec = price + OrderExecutor._get_tick_size(price)
    assert nxt_rules != nxt_exec
    # market_rules 의 "다음 호가" 는 그 가격대의 실주문 경로에서 호가가 아니다.
    assert OrderExecutor._round_to_tick(nxt_rules) != nxt_rules
