"""성과에 ★"이 수치가 무엇인가"★ 를 붙인다 (Z1)

## 왜 필요한가 (실측)

배지 관용구가 넷인데 **어느 것도 성과의 종류를 말하지 않는다**:

    brun-badge     시점 정합(PIT)
    tbt-prov       데이터 실/합성
    as-bt-badge    데이터 + OOS
    인라인 스타일   실행 모드(주문 행 단위)

★셋 다 다른 축이다.★ *"이 수익률이 백테스트인가 실계좌인가"* 를 그리는 컴포넌트는
하나도 없었고, 수익률·Sharpe·MDD 를 라벨 없이 숫자로만 그리는 화면이 여럿이었다.

## ★프런트가 지어내면 장식이다★

"백테스트 페이지니까 BACKTEST" 는 사실이 아니라 **배치**다. 같은 컴포넌트를 다른
데이터로 재사용하는 순간 거짓말이 된다. 그래서 **백엔드가 선언**하고, 이 모듈이
그 선언의 어휘다.

## ★두 축을 섞지 않는다★

`kind`(무슨 **성과**인가)와 `data_real`(무슨 **데이터**인가)은 독립이다 —
실데이터 백테스트도, mock 데이터 페이퍼도 있다. Y2 에서 `evidence_level` 과
`confidence` 를 가른 것과 같은 규율.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.domain.perf_kind import (  # noqa: E402
    KIND_BACKTEST,
    KIND_LIVE,
    KIND_PAPER,
    KIND_RA_TESTBED,
    KIND_SHADOW,
    KIND_UNKNOWN,
    PERF_KINDS,
    PerfLabel,
    backtest_label,
    execution_label,
)

# ═══════════════════════════════════════════════════════════════════════════
# ①②③ 백테스트 — 데이터 축은 ★모르면 `None`★
# ═══════════════════════════════════════════════════════════════════════════

def test_a_mock_backtest_is_backtest_and_not_real_data():
    lb = backtest_label(is_mock_data=True)
    assert lb.kind == KIND_BACKTEST
    assert lb.data_real is False
    assert lb.kind_reason is None


def test_a_real_backtest_is_still_a_backtest():
    """★짝★ 실데이터라고 종류가 바뀌지 않는다(두 축이 독립이라는 뜻)."""
    lb = backtest_label(is_mock_data=False)
    assert lb.kind == KIND_BACKTEST
    assert lb.data_real is True


def test_an_unknown_data_source_is_none_not_false():
    """★미상을 `False` 로 접지 않는다★ — '합성이다' 와 '모른다' 는 다른 사실이다."""
    lb = backtest_label(is_mock_data=None)
    assert lb.kind == KIND_BACKTEST
    assert lb.data_real is None
    assert lb.data_reason and len(lb.data_reason) > 5


def test_a_known_data_source_carries_no_reason():
    """★짝★ 아는 것에는 사유를 달지 않는다(항상-사유 구현 배제)."""
    assert backtest_label(is_mock_data=True).data_reason is None
    assert backtest_label(is_mock_data=False).data_reason is None


# ═══════════════════════════════════════════════════════════════════════════
# ④⑤ 실행 모드 — ★알아보지 못한 값은 `unknown` + 그 값★
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("mode,expected", [
    ("SHADOW", KIND_SHADOW), ("PAPER", KIND_PAPER), ("LIVE", KIND_LIVE),
])
def test_execution_modes_map_to_kinds(mode, expected):
    lb = execution_label(execution_mode=mode)
    assert lb.kind == expected
    assert lb.kind_reason is None


def test_a_missing_execution_mode_is_unknown():
    lb = execution_label(execution_mode=None)
    assert lb.kind == KIND_UNKNOWN
    assert lb.kind_reason and len(lb.kind_reason) > 5


def test_an_unrecognized_mode_says_what_it_saw():
    """★무엇을 못 알아봤는지 말한다★ — 어휘가 여섯이라 새 값이 들어올 수 있다."""
    lb = execution_label(execution_mode="SANDBOX")
    assert lb.kind == KIND_UNKNOWN
    assert "SANDBOX" in (lb.kind_reason or ""), lb.kind_reason


def test_an_unrecognized_mode_is_not_leaned_toward_paper():
    """★안전한 쪽으로도 기울지 않는다★ — 미상은 미상이다."""
    for bad in ("sandbox", "live_restricted", "", "  ", "REAL"):
        assert execution_label(execution_mode=bad).kind == KIND_UNKNOWN, bad


def test_execution_label_does_not_claim_a_data_axis():
    """실행 모드는 데이터 실/합성을 말하지 않는다 — ★다른 축★."""
    lb = execution_label(execution_mode="PAPER")
    assert lb.data_real is None
    assert lb.data_reason


# ═══════════════════════════════════════════════════════════════════════════
# ⑥ 두 축은 ★독립★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_two_axes_are_independent():
    """같은 종류 안에서 데이터 축이 갈리고, 데이터 축이 종류를 바꾸지 않는다."""
    kinds = {backtest_label(is_mock_data=m).kind for m in (True, False, None)}
    assert kinds == {KIND_BACKTEST}, kinds
    reals = {backtest_label(is_mock_data=m).data_real for m in (True, False, None)}
    assert reals == {True, False, None}, reals


def test_data_real_is_not_derivable_from_kind():
    """★kind 로 data_real 을 유추하지 않는다★ — 유추하면 두 축이 하나가 된다."""
    assert execution_label(execution_mode="LIVE").data_real is None


# ═══════════════════════════════════════════════════════════════════════════
# ⑦ 어휘 — ★없는 것을 만들지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_every_produced_kind_is_declared():
    produced = {backtest_label(is_mock_data=None).kind}
    produced |= {execution_label(execution_mode=m).kind
                 for m in ("SHADOW", "PAPER", "LIVE", None, "X")}
    assert produced <= set(PERF_KINDS), produced - set(PERF_KINDS)


def test_ra_testbed_is_vocabulary_only():
    """★이 저장소는 테스트베드에 제출한 적이 없다★ — 상수는 두되 아무도 만들지 않는다."""
    assert KIND_RA_TESTBED in PERF_KINDS
    produced = {backtest_label(is_mock_data=m).kind for m in (True, False, None)}
    produced |= {execution_label(execution_mode=m).kind
                 for m in ("SHADOW", "PAPER", "LIVE", None, "RA_TESTBED", "testbed")}
    assert KIND_RA_TESTBED not in produced, "생산자가 없어야 한다"


def test_the_label_is_immutable_and_serializable():
    import dataclasses
    lb = backtest_label(is_mock_data=True)
    assert isinstance(lb, PerfLabel)
    with pytest.raises(dataclasses.FrozenInstanceError):
        lb.kind = KIND_LIVE                      # type: ignore[misc]
    d = lb.to_dict()
    assert set(d) == {"kind", "kind_reason", "data_real", "data_reason"}
    assert d["kind"] == KIND_BACKTEST
