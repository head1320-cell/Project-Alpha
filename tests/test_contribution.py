"""AO2 — 적립: ★대상을 모르면 방향을 모른다★ (순수 계층).

## 이 모듈이 존재하는 이유는 **두 함정**이다

### 함정 ① 적립 대상을 모르면 방향을 모른다

목표가 현재보다 위험자산을 **줄이는** 방향인데 위험자산에 납입하면 격차는
★벌어진다★. "적립하면 목표에 가까워진다" 는 **틀린 일반화**다. 그래서
`target_bucket` 이 선언되지 않으면 도달 개월 수를 내지 않는다.

### 함정 ② 실적과 계획은 다른 축이다

한도 판정(`account_policy.LIMIT_ANNUAL_CONTRIB_KRW`)에 들어갈 것은 **실적**이고,
도달 계산에 들어갈 것은 **계획**이다. 계획을 한도 관측으로 넘기면 *"아직 내지
않은 돈"* 으로 한도를 판정하게 된다 — 그 판정은 거짓이다. 이 모듈은 **계획만**
다루고, 실적은 라우트가 따로 받아 `judge_account` 로 보낸다.

## ★매도 없이★ 라는 전제

이 계산은 **기존 보유를 팔지 않는다**고 가정한다. 연금 계좌에서 비중을 맞추는
표준적인 방법이고, 매도에는 세제·수수료가 따로 붙기 때문이다. 그 전제를 note 가
적는다 — 적지 않으면 "리밸런싱하면 되는데 40개월?" 이라고 읽힌다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from src.domain.contribution import (
    BUCKET_RISKY,
    BUCKET_SAFE,
    BUCKETS,
    DIRECTION_CLOSES,
    DIRECTION_UNKNOWN,
    DIRECTION_WIDENS,
    contribution_direction,
    months_to_close,
)
from src.domain.glide_path import GAP_ABOVE, GAP_BELOW, GAP_UNKNOWN

_MODULE = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "domain" / "contribution.py")

V = 100_000_000.0      # 포트폴리오 평가액
C = 1_000_000.0        # 월 적립액


# ═══════════════════════════════════════════════════════════════════════════
# 어휘
# ═══════════════════════════════════════════════════════════════════════════

def test_the_buckets_are_registered():
    assert set(BUCKETS) == {BUCKET_RISKY, BUCKET_SAFE}


def test_the_module_is_pure():
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    # `src.domain.glide_path` 의 격차 어휘는 재사용한다 — 어휘를 두 벌 만들지 않는다.
    assert not (imported & {"os", "requests", "sqlalchemy"}), imported


def test_the_module_does_not_touch_contribution_limits():
    """★실적 ⟂ 계획★ — 이 모듈은 한도를 **코드로** 건드리지 않는다.

    ★이 테스트를 처음엔 틀리게 썼다★ — 소스에서 `judge_account` 문자열을 금지했더니
    *"실적은 라우트가 따로 받아 `judge_account` 로 보낸다"* 라고 **경계를 설명하는
    독스트링**이 걸렸다. 이 세션에서만 네 번째 같은 실수다(E 의 검출기 · `note`
    테스트 · 라우트 docstring 테스트). ★산문은 코드가 아니다★ — AST 로 **import 와
    호출**만 본다.
    """
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                called.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                called.add(fn.attr)
    banned = {"judge_account", "judge_limit", "LIMIT_ANNUAL_CONTRIB_KRW",
              "LIMIT_TOTAL_CONTRIB_KRW"}
    assert not (imported & banned), imported & banned
    assert not (called & banned), called & banned


# ═══════════════════════════════════════════════════════════════════════════
# 방향 — ★함정 ①★
# ═══════════════════════════════════════════════════════════════════════════

def test_over_target_closes_by_contributing_to_safe():
    """위험자산이 목표보다 많다 → **안전자산**에 넣어야 비중이 내려온다."""
    assert contribution_direction(GAP_ABOVE, BUCKET_SAFE) == DIRECTION_CLOSES


def test_over_target_widens_by_contributing_to_risky():
    """★이것이 함정이다★ — 적립이 늘 도움이 되는 것은 아니다."""
    assert contribution_direction(GAP_ABOVE, BUCKET_RISKY) == DIRECTION_WIDENS


def test_under_target_closes_by_contributing_to_risky():
    assert contribution_direction(GAP_BELOW, BUCKET_RISKY) == DIRECTION_CLOSES


def test_under_target_widens_by_contributing_to_safe():
    assert contribution_direction(GAP_BELOW, BUCKET_SAFE) == DIRECTION_WIDENS


def test_an_unknown_gap_gives_an_unknown_direction():
    for b in BUCKETS:
        assert contribution_direction(GAP_UNKNOWN, b) == DIRECTION_UNKNOWN


@pytest.mark.parametrize("bucket", [None, "", "cash", "RISKY ", 3])
def test_an_undeclared_bucket_gives_an_unknown_direction(bucket):
    """★선언이 없으면 방향이 없다★"""
    assert contribution_direction(GAP_ABOVE, bucket) == DIRECTION_UNKNOWN


def test_all_three_directions_are_reachable():
    """★공허한 분기는 증거가 아니다★"""
    got = {contribution_direction(GAP_ABOVE, BUCKET_SAFE),
           contribution_direction(GAP_ABOVE, BUCKET_RISKY),
           contribution_direction(GAP_UNKNOWN, BUCKET_SAFE)}
    assert got == {DIRECTION_CLOSES, DIRECTION_WIDENS, DIRECTION_UNKNOWN}


# ═══════════════════════════════════════════════════════════════════════════
# 도달 개월 — 산수와 ★구간 전파★
# ═══════════════════════════════════════════════════════════════════════════

def _close(**kw):
    base = dict(target_pct=50.0, observed_lo=70.0, observed_hi=70.0,
                monthly_krw=C, portfolio_value_krw=V, bucket=BUCKET_SAFE)
    base.update(kw)
    return months_to_close(**base)


def test_contributing_to_safe_reaches_the_target():
    """★손으로 검산한다★ 70%→50%, 평가액 1억, 월 100만 → 40개월.

    매도 없이 위험자산 7천만은 그대로 두고 총액만 늘린다:
    40개월 뒤 총액 1.4억 · 위험자산 7천만 → 정확히 50%.
    """
    out = _close()
    assert out["available"] is True
    assert out["months"]["lo"] == pytest.approx(40.0, abs=0.01)
    assert out["months"]["hi"] == pytest.approx(40.0, abs=0.01)


def test_contributing_to_risky_reaches_the_target():
    """30%→50%, 같은 조건 → 40개월(검산: 위험 7천만 / 총 1.4억)."""
    out = _close(observed_lo=30.0, observed_hi=30.0, bucket=BUCKET_RISKY)
    assert out["available"] is True
    assert out["months"]["lo"] == pytest.approx(40.0, abs=0.01)


def test_an_interval_observation_gives_an_interval_of_months():
    """★구간을 점으로 접지 않는다★ (AD3 이 막은 바로 그 접기)"""
    out = _close(observed_lo=65.0, observed_hi=75.0)
    assert out["available"] is True
    assert out["months"]["lo"] < out["months"]["hi"]
    assert out["months"]["lo"] == pytest.approx(30.0, abs=0.01)
    assert out["months"]["hi"] == pytest.approx(50.0, abs=0.01)


def test_a_widening_direction_gives_a_reason_not_a_number():
    """★방향이 반대면 숫자를 내지 않는다★"""
    out = _close(bucket=BUCKET_RISKY)
    assert out["available"] is False
    assert out["direction"] == DIRECTION_WIDENS
    assert out["months"] is None
    assert out["reason"]


def test_an_undeclared_bucket_gives_a_reason_not_a_number():
    out = _close(bucket=None)
    assert out["available"] is False
    assert out["months"] is None
    assert out["reason"]


def test_a_straddling_target_gives_a_reason_not_a_number():
    """목표가 관측 구간 안 — 부호를 모르므로 개월 수도 모른다."""
    out = _close(observed_lo=40.0, observed_hi=60.0)
    assert out["available"] is False
    assert out["direction"] == DIRECTION_UNKNOWN
    assert out["reason"]


@pytest.mark.parametrize("kw", [
    {"monthly_krw": 0.0}, {"monthly_krw": -1.0}, {"monthly_krw": None},
    {"portfolio_value_krw": 0.0}, {"portfolio_value_krw": None},
    {"target_pct": None}, {"target_pct": 0.0}, {"target_pct": 100.0},
])
def test_every_degenerate_input_gives_a_reason_not_a_number(kw):
    """★수치 안전★ (CLAUDE.md §6) — 분모 0·음수·미상에 숫자를 내지 않는다."""
    out = _close(**kw)
    assert out["available"] is False, kw
    assert out["months"] is None
    assert out["reason"]


def test_a_target_of_one_hundred_is_unreachable_by_contributing_to_risky():
    """★분모가 0 이 되는 자리★ — 위험자산 100% 는 적립만으로 도달하지 않는다."""
    out = _close(target_pct=100.0, observed_lo=30.0, observed_hi=30.0,
                 bucket=BUCKET_RISKY)
    assert out["available"] is False
    assert out["reason"]


def test_already_at_the_target_is_zero_months_not_unavailable():
    """★짝★ — 도달해 있는 것과 못 재는 것은 다르다."""
    out = _close(observed_lo=50.0, observed_hi=50.0)
    assert out["direction"] == DIRECTION_UNKNOWN, "격차 0 은 구간이 목표에 걸친 것"
    assert out["reason"]


def test_the_note_declares_the_no_selling_assumption():
    """★전제를 적지 않으면 숫자가 거짓말을 한다★"""
    out = _close()
    assert out["note"]
    assert "매도" in out["note"]


def test_the_result_never_claims_the_plan_was_executed():
    """★계획이지 실적이 아니다★ — 한도 판정과 섞이면 안 된다."""
    out = _close()
    assert "contributed" not in str(out).lower()
    assert "계획" in out["note"]
