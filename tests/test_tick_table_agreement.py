"""BD · ★호가 표는 하나다 — KRX 원문대로 "미만"★
==============================================================================
대상: `src/data/market_rules.py::tick_size`(단일 출처) ·
`src/kis_order_executor.py::OrderExecutor._get_tick_size`(그것을 읽는다)

## 무엇이 있었나 (BC 실측 2026-09-24)

표가 두 벌이었다. `market_rules` 는 `price <= 2000 → 1원`, 실주문 경로
`OrderExecutor` 는 `price < 2000 → 1원`. 여섯 경계 전부에서 다른 틱을 냈다.
BC 는 그 불일치를 **관측으로 고정**하고 어느 쪽이 맞는지를 미상으로 남겼다.

## 누가 답했나 — ★등급을 적는다★

증권사 안내(대신·한화·유진증권)와 2023-01-25 개편 보도가 전부 *"2,000원 미만
1원 · 2,000원 이상 5,000원 미만 5원 · … · 50만원 이상 1,000원"* 이었고, 사용자가
**"KRX 원문대로 `<`"** 로 확정했다. ★KRX 1차 문서는 이 환경에서 CONNECT 403 이라
직접 확인하지 못했다★ — 이 표의 근거는 *"2차 출처 일치 + 사용자 확정"* 이다.

## ★실주문 가격은 1원도 안 바뀐다 — 전수로 증명한다★

`_round_to_tick` 은 내림이다. 여섯 경계가 두 틱의 **공배수**라 경계에서 어느 틱을
써도 내림 결과가 같다. 그 추론을 믿지 않고 1..1,000,000 **전수**로 옛 함수와
대조한다. 바뀌는 것은 `market_rules` 쪽 — `execution_plan` 이 경계 여섯 가격에서
**보고하는** 틱과 *"다음 호가"* 뿐이다.
"""
from __future__ import annotations

import ast
import math
import pathlib

import pytest

from src.data import market_rules as mr
from src.kis_order_executor import OrderExecutor

#: KRX 경계 → 그 가격(경계 **이상**)에서의 호가 단위.
KRX_AT_BOUNDARY = {
    2_000: 5, 5_000: 10, 20_000: 50,
    50_000: 100, 200_000: 500, 500_000: 1_000,
}


def _frozen_order_tick(price: int) -> int:
    """★BD 이전 `OrderExecutor._get_tick_size` 의 동결 사본★ — 골든의 기준."""
    if price < 2_000:
        return 1
    if price < 5_000:
        return 5
    if price < 20_000:
        return 10
    if price < 50_000:
        return 50
    if price < 200_000:
        return 100
    if price < 500_000:
        return 500
    return 1_000


def _frozen_order_round(price: int) -> int:
    t = _frozen_order_tick(price)
    return int(math.floor(price / t) * t)


# ── ★실주문 가격 골든 — 전수★ ─────────────────────────────────────────

def test_live_order_rounding_is_unchanged_for_every_price():
    """★실주문 경로의 내림 가격이 1원도 안 바뀐다★ (1..1,000,000 전수)."""
    bad = [p for p in range(1, 1_000_001)
           if OrderExecutor._round_to_tick(p) != _frozen_order_round(p)]
    assert bad == [], bad[:20]


# ── ★하나의 표★ ────────────────────────────────────────────────────

def test_the_two_paths_agree_everywhere():
    """★갈리는 가격이 하나도 없다★ — 1원 단위로 60만 원까지 훑는다."""
    found = [p for p in range(1, 600_001)
             if mr.tick_size(p) != OrderExecutor._get_tick_size(p)]
    assert found == [], found[:20]


@pytest.mark.parametrize("price,tick", sorted(KRX_AT_BOUNDARY.items()))
def test_each_boundary_price_takes_the_upper_band(price, tick):
    """★경계는 "미만"★ — 정확히 2,000원은 5원 단위다."""
    assert mr.tick_size(price) == tick
    assert OrderExecutor._get_tick_size(price) == tick


@pytest.mark.parametrize("price", sorted(KRX_AT_BOUNDARY))
def test_just_below_each_boundary_is_the_lower_band(price):
    """★짝★ — 경계 1원 아래는 아래 구간이다(항상-위 구현 배제)."""
    lower = {2_000: 1, 5_000: 5, 20_000: 10, 50_000: 50,
             200_000: 100, 500_000: 500}[price]
    assert mr.tick_size(price - 1) == lower


def test_the_order_path_reads_market_rules():
    """★단일 출처★ — `_get_tick_size` 가 자기 표를 다시 갖지 않고 `market_rules` 를 읽는다.

    AST 로 본다: 함수 본문에 비교 연산이 없고 `tick_size` 호출이 있다.
    """
    tree = ast.parse(pathlib.Path("src/kis_order_executor.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_get_tick_size")
    assert not any(isinstance(n, ast.Compare) for n in ast.walk(fn)), "표가 복제돼 있다"
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", getattr(n.func, "id", None)) == "tick_size"]
    assert calls, "market_rules.tick_size 를 부르지 않는다"


def test_the_snapshot_says_below_not_up_to():
    """★`up_to` 는 "이하" 로 읽힌다★ — 경계가 미만이면 키 이름도 미만이어야 한다."""
    rows = mr.rules_snapshot()["tick_table"]
    assert all("below" in r and "up_to" not in r for r in rows)
    assert rows[0] == {"below": 2000, "tick": 1}
    assert rows[-1]["below"] is None


# ── BC 의 반올림은 영향이 없다 ──────────────────────────────────────

@pytest.mark.parametrize("price", sorted(KRX_AT_BOUNDARY))
def test_boundary_prices_are_on_tick_and_round_to_themselves(price):
    assert mr.is_on_tick(price)
    for d in ("up", "down", "nearest"):
        assert mr.round_to_tick(price, d) == price


def test_buy_rounding_just_above_a_boundary_uses_the_upper_tick():
    """2,001원 매수(올림)는 2,005원이다 — 2,002원(1원 단위)이 아니다."""
    assert mr.round_to_tick(2001, "up") == 2005
    assert mr.round_to_tick(2001, "down") == 2000
