"""`portfolio_weights` — 부호 보존 정규화의 단일 출처.

★이 파일이 거는 것★
  1. ★롱온리 비트 동일★ 이 성질이 깨지면 하류 7곳의 리팩터가 전부 회귀 위험이 된다.
  2. ★달러중립이 폭발하지 않는다★ net 으로 나누던 방식이 죽는 지점.
  3. ★부호가 살아 있다★ 숏이 출력에 음수로 남는다.

★합만 재는 가드를 쓰지 않는다★ `Σ|out| == 1` 은 틀린 답 다수가 만족한다 —
값마다 따로 핀한다.
"""
from __future__ import annotations

import math

import pytest

from src.engine.portfolio_weights import (
    GROSS_EPS,
    exposure_basis,
    gross,
    has_short,
    net,
    signed_fractions,
)


def _legacy(weights: dict) -> dict:
    """★교체 전 구현★ 하류 7곳에 복사돼 있던 바로 그 두 줄."""
    total = sum(max(float(v), 0.0) for v in weights.values())
    if total <= 0:
        return {}
    return {k: max(float(v), 0.0) / total for k, v in weights.items()
            if max(float(v), 0.0) > 0}


# ── 1. ★롱온리 비트 동일★ ────────────────────────────────────────────────
@pytest.mark.parametrize("w", [
    {"A": 100.0},
    {"A": 40.0, "B": 25.0, "C": 20.0, "D": 15.0},
    {"A": 60.0, "B": 40.0},
    {"A": 33.3, "B": 33.3, "C": 33.4},
    {"A": 60.0, "B": 0.0, "C": 40.0},          # 0 은 예전에도 버렸다
    {"A": 0.5, "B": 0.5},                       # 분수 입력
    {"A": 12.0, "B": 8.0},                      # 합이 100 이 아니어도
])
def test_long_only_is_bit_identical_to_the_old_clamp(w):
    """★이 슬라이스의 안전 근거★ 값까지 같아야 한다 — approx 가 아니라 정확히."""
    assert signed_fractions(w) == _legacy(w), w


def test_the_baseline_helper_is_not_vacuous():
    """★짝★ `_legacy` 가 실제로 숏을 버리는 구현이어야 위 비교가 뜻이 있다."""
    assert _legacy({"A": 130.0, "B": -30.0}) == {"A": 1.0}


# ── 2. ★달러중립이 폭발하지 않는다★ ──────────────────────────────────────
def test_a_dollar_neutral_book_does_not_explode():
    """net 으로 나누면 여기서 ZeroDivision 이거나 무한대가 된다."""
    w = {"A": 100.0, "B": -100.0}
    assert net(w) == pytest.approx(0.0)
    f = signed_fractions(w)
    assert all(math.isfinite(v) for v in f.values())
    assert f["A"] == pytest.approx(0.5)
    assert f["B"] == pytest.approx(-0.5)


def test_a_near_neutral_book_is_stable_too():
    """정확히 0 이 아니라 **거의** 0 일 때가 실전이다 — net 정규화는 여기서 폭발한다."""
    w = {"A": 100.0, "B": -99.999}
    f = signed_fractions(w)
    assert abs(f["A"]) < 1.0 and abs(f["B"]) < 1.0
    # net 으로 나눴다면 |값| 이 5만 배쯤 됐을 것이다.
    assert max(abs(v) for v in f.values()) < 2.0


# ── 3. ★부호가 살아 있다★ ────────────────────────────────────────────────
def test_shorts_survive_with_their_sign_and_size():
    """130/30 — ★항마다 핀한다★ 합만 재면 틀린 답이 통과한다."""
    f = signed_fractions({"A": 130.0, "B": -30.0})
    assert set(f) == {"A", "B"}, "숏이 사라졌다"
    assert f["A"] == pytest.approx(130.0 / 160.0)
    assert f["B"] == pytest.approx(-30.0 / 160.0)
    assert sum(abs(v) for v in f.values()) == pytest.approx(1.0)


def test_has_short_separates_the_two_worlds():
    assert has_short({"A": 130.0, "B": -30.0}) is True
    assert has_short({"A": 60.0, "B": 40.0}) is False
    assert has_short({"A": 60.0, "B": 0.0}) is False


# ── 4. ★전액 숏 북 — 오늘은 거짓 사유가 나간다★ ─────────────────────────
def test_an_all_short_book_has_size_even_though_its_net_is_negative():
    """예전 `tot = sum(max(w,0))` 은 0 이라 "보유 비중 합이 0입니다" 를 냈다 —
    포지션을 **갖고 있는데** 없다고 말하는 거짓 사유였다."""
    w = {"A": -60.0, "B": -40.0}
    assert _legacy(w) == {}, "예전 구현은 여기서 아무것도 남기지 않았다"
    assert gross(w) == pytest.approx(100.0)
    assert net(w) == pytest.approx(-100.0)
    f = signed_fractions(w)
    assert f["A"] == pytest.approx(-0.6)
    assert f["B"] == pytest.approx(-0.4)


def test_a_genuinely_empty_book_is_still_empty():
    """★짝★ 위가 "무엇이든 통과" 가 되지 않게 한다."""
    assert signed_fractions({}) == {}
    assert signed_fractions({"A": 0.0, "B": 0.0}) == {}
    assert gross({"A": 0.0}) <= GROSS_EPS


# ── 5. ★기준을 말한다★ ──────────────────────────────────────────────────
def test_the_basis_block_describes_a_130_30():
    b = exposure_basis({"A": 130.0, "B": -30.0})
    assert b["gross_pct"] == pytest.approx(160.0)
    assert b["net_pct"] == pytest.approx(100.0)
    assert b["long_pct"] == pytest.approx(130.0)
    assert b["short_pct"] == pytest.approx(30.0)
    assert b["long_short"] is True
    assert b["normalized_by"] == "gross"


def test_the_basis_block_separates_two_books_with_the_same_net():
    """★넷이 같아도 다른 포트폴리오다★ P3 가 gross 를 도입한 이유 그 자체."""
    a = exposure_basis({"A": 100.0})
    b = exposure_basis({"A": 150.0, "B": -50.0})
    assert a["net_pct"] == b["net_pct"] == pytest.approx(100.0)
    assert a["gross_pct"] == pytest.approx(100.0)
    assert b["gross_pct"] == pytest.approx(200.0)
    assert a["long_short"] is False and b["long_short"] is True


def test_non_numeric_values_are_ignored_rather_than_raising():
    w = {"A": 100.0, "B": None, "C": "x", "D": -50.0}
    assert gross(w) == pytest.approx(150.0)
    f = signed_fractions(w)
    assert set(f) == {"A", "D"}
