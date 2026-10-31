"""AD3 — 위험자산 비중은 ★관측★, 위험/안전 분류는 ★선언★.

"IRP 위험자산 70%" 를 재려면 무엇이 위험자산인지 알아야 하는데 ★그것 자체가 규제
판단★이다. 그래서 가른다: 자산군 **구성**은 데이터에서 관측하고, 어느 자산군이
위험자산인지는 **요청이 선언**한다. 선언이 없으면 비중을 계산하지 않는다.

그리고 ★미배정 자산군이 있으면 비중은 점이 아니라 구간★이다 — 미배정분을 0 으로
접어 "한도 이하입니다" 라고 말하면 없는 사실을 만든다.
"""
from __future__ import annotations

import ast
import pathlib

from src.engine.risky_share import (
    RISKY_UNDECLARED_REASON,
    asset_class_mix,
    risky_share_interval,
)

_MODULE = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "engine" / "risky_share.py")

# ★픽스처를 실측이 고쳤다★ — `005930`(삼성전자) 같은 **개별주는 이 환경에서
# 미배정**이다(`no_master_flags` — 규칙 배정이 `instrument_master` 를 요구하는데
# 개발 환경에는 그 표가 없다). 체크인된 ETF 55종만 결정론적으로 배정되므로
# 그것을 쓴다. 덕분에 미배정 경로도 진짜로 밟힌다.
_EQUITY = "069500"      # KODEX 200 → EQUITY
_RATES = "153130"       # 단기채 ETF → RATES
_COMMODITY = "132030"   # KODEX 골드선물 → COMMODITY
#: 배정되지 않는 티커 — 개별주는 개발 환경에서 `no_master_flags` 로 미배정이다.
_UNKNOWN = "005930"


# ── 관측: 자산군 구성 ──────────────────────────────────────────────────────

def test_the_mix_reports_assigned_and_unassigned_separately():
    """★미배정을 조용히 빠뜨리지 않는다★ — `asset_class_of` 의 계약 그대로."""
    mix = asset_class_mix({_EQUITY: 60.0, _UNKNOWN: 40.0})
    assert mix["assigned_pct"] > 0
    assert mix["unassigned_pct"] > 0
    assert mix["unassigned"], "미배정 목록이 비었다"
    assert mix["unassigned"][0]["reason"], "미배정에 사유가 없다"


def test_the_mix_sums_to_one_hundred():
    mix = asset_class_mix({_EQUITY: 60.0, _RATES: 40.0})
    total = sum(mix["by_class"].values()) + mix["unassigned_pct"]
    assert abs(total - 100.0) < 1e-6


def test_an_empty_holding_is_not_a_zero_mix():
    """★빈 보유와 '위험자산 0%' 는 다른 사실이다★."""
    mix = asset_class_mix({})
    assert mix["available"] is False
    assert mix["reason"]


def test_negative_and_zero_weights_are_refused_with_a_reason():
    mix = asset_class_mix({_EQUITY: 0.0, _RATES: 0.0})
    assert mix["available"] is False
    assert mix["reason"]


# ── ★선언이 없으면 재지 않는다★ ─────────────────────────────────────────

def test_without_a_declared_classification_the_share_is_not_computed():
    out = risky_share_interval({_EQUITY: 100.0}, risky_classes=None)
    assert out["available"] is False
    assert out["interval"] is None
    assert out["reason"] == RISKY_UNDECLARED_REASON


def test_the_undeclared_reason_says_it_is_a_regulatory_judgement():
    assert "규제" in RISKY_UNDECLARED_REASON or "선언" in RISKY_UNDECLARED_REASON


def test_an_empty_declaration_is_still_a_declaration():
    """★짝★ — "위험자산이 하나도 없다" 는 선언은 미선언과 다르다."""
    out = risky_share_interval({_EQUITY: 100.0}, risky_classes=[])
    assert out["available"] is True
    assert out["interval"]["lo"] == 0.0


# ── ★구간★ — 미배정분이 폭을 만든다 ────────────────────────────────────

def test_a_fully_classified_holding_yields_a_point():
    """★짝★ — 언제나 구간을 벌리는 구현을 배제한다."""
    out = risky_share_interval({_EQUITY: 60.0, _RATES: 40.0},
                               risky_classes=["EQUITY"])
    assert out["available"] is True
    # 폭이 0 인 것이 계약이다 — 값(60%)이 아니라 **점이라는 사실**을 못 박는다.
    assert out["interval"]["lo"] == out["interval"]["hi"]
    assert abs(out["interval"]["lo"] - 60.0) < 1e-6
    assert out["unassigned_pct"] == 0.0


def test_an_unassigned_slice_widens_the_interval_by_exactly_its_weight():
    """미배정 40% 면 구간 폭이 정확히 40 이다 — 모르는 몫만큼만 벌어진다."""
    out = risky_share_interval({_EQUITY: 60.0, _UNKNOWN: 40.0},
                               risky_classes=["EQUITY"])
    lo, hi = out["interval"]["lo"], out["interval"]["hi"]
    assert abs(lo - 60.0) < 1e-6
    assert abs(hi - 100.0) < 1e-6
    assert abs((hi - lo) - out["unassigned_pct"]) < 1e-6


def test_the_lower_bound_treats_unassigned_as_safe_and_the_upper_as_risky():
    """★경계의 의미를 말한다★ — 두 극단이 무엇을 가정한 것인지 응답이 적는다."""
    out = risky_share_interval({_EQUITY: 60.0, _UNKNOWN: 40.0},
                               risky_classes=["EQUITY"])
    assert out["interval"]["lo_assumes"]
    assert out["interval"]["hi_assumes"]
    assert out["interval"]["lo_assumes"] != out["interval"]["hi_assumes"]


def test_a_non_risky_class_does_not_enter_the_lower_bound():
    """채권만 들고 있고 주식을 위험자산으로 선언하면 위험 비중은 0 이다."""
    out = risky_share_interval({_RATES: 100.0}, risky_classes=["EQUITY"])
    assert out["interval"]["lo"] == 0.0
    assert out["interval"]["hi"] == 0.0


def test_an_unknown_class_name_in_the_declaration_is_reported():
    """★어휘 밖 자산군을 조용히 무시하지 않는다★ — 오타가 곧 잘못된 판정이다."""
    out = risky_share_interval({_EQUITY: 100.0},
                               risky_classes=["EQUITY", "CRYPTO"])
    assert "CRYPTO" in out["unknown_classes"]
    assert out["reason"], "어휘 밖 이름이 있는데 사유가 없다"


def test_a_valid_declaration_reports_no_unknown_classes():
    """★짝★ — 언제나 unknown 을 채우는 구현을 배제한다."""
    out = risky_share_interval({_EQUITY: 100.0}, risky_classes=["EQUITY"])
    assert out["unknown_classes"] == []


# ── ★분류를 코드에 박지 않았다★ ────────────────────────────────────────

def test_no_default_risky_classification_is_baked_in():
    """어느 자산군이 위험자산인지는 ★규제 판단★ 이라 소스가 정해 두지 않는다.

    `EQUITY` 같은 자산군 이름이 '위험' 쪽 기본값으로 묶여 있으면 안 된다.
    """
    src = _MODULE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            name = getattr(target, "id", "")
            if "RISKY" in name.upper() and "REASON" not in name.upper():
                dumped = ast.unparse(node.value)
                assert "EQUITY" not in dumped, f"{name} 에 기본 위험자산 분류가 박혀 있다"
