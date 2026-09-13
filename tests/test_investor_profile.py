"""AD2 — 투자자 프로파일의 계약 (순수 계층).

RA5 도메인 문서 §1 의 설계를 코드로 옮긴 것이다. ★그 문서가 스스로 적은 경계도
지킨다★ — `decide()` 시그니처는 건드리지 않고, `horizon_days=None` 을 63 으로
지어내지 않는다.
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from src.domain.account_policy import ACCOUNT_IRP, ACCOUNT_TYPES
from src.domain.investor_profile import (
    PROFILE_SOURCES,
    RISK_TOLERANCE_LEVELS,
    SOURCE_DEFAULT,
    SOURCE_SURVEY,
    SOURCE_UNKNOWN,
    SOURCE_USER_DECLARED,
    InvestorProfile,
)

_MODULE = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "domain" / "investor_profile.py")


def _p(**kw) -> InvestorProfile:
    base = dict(profile_id="p1", owner_id="alice", account_type=ACCOUNT_IRP,
                risk_tolerance="moderate")
    return InvestorProfile(**{**base, **kw})


# ── 어휘 ────────────────────────────────────────────────────────────────────

def test_the_five_risk_levels_are_ordered_from_conservative():
    assert RISK_TOLERANCE_LEVELS[0] == "conservative"
    assert RISK_TOLERANCE_LEVELS[-1] == "aggressive"
    assert len(RISK_TOLERANCE_LEVELS) == 5


def test_how_the_profile_was_obtained_is_part_of_the_vocabulary():
    """★"어떻게 정해졌나" 를 값에 남긴다★ — 설문과 기본값은 같은 신뢰도가 아니다."""
    assert PROFILE_SOURCES == (SOURCE_SURVEY, SOURCE_USER_DECLARED,
                               SOURCE_DEFAULT, SOURCE_UNKNOWN)


def test_the_account_type_vocabulary_is_shared_not_duplicated():
    """★어휘를 두 벌 만들지 않는다★ — account_policy 의 것을 그대로 쓴다."""
    src = _MODULE.read_text(encoding="utf-8")
    assert "account_policy" in src
    assert 'ACCOUNT_IRP = "irp"' not in src, "계좌 어휘를 복제했다"


# ── ★미상을 지어내지 않는다★ ─────────────────────────────────────────────

def test_an_unknown_horizon_stays_none():
    """★63 으로 채우지 않는다★ — RA5 가 명시한 규율(CLAUDE.md §4 미상 ≠ 0)."""
    assert _p().horizon_days is None


def test_an_unknown_risk_aversion_stays_none():
    assert _p().risk_aversion is None


def test_the_default_source_is_unknown_not_survey():
    """모르면 '모른다' 다 — 가장 신뢰도 높은 값으로 기본값을 두지 않는다."""
    assert _p().source == SOURCE_UNKNOWN


def test_an_unassessed_profile_has_no_assessment_date():
    assert _p().assessed_at is None


def test_the_module_does_not_contain_the_default_horizon():
    """★전수★ — `DEFAULT_HORIZON_DAYS = 63` 을 나중에 슬쩍 되살리는 것을 막는다."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    baked = [n.value for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and n.value == 63]
    assert not baked, "기본 투자기간 63 이 박혀 있다"


# ── 검증 ────────────────────────────────────────────────────────────────────

def test_an_unknown_account_type_is_refused():
    with pytest.raises(ValueError) as e:
        _p(account_type="crypto_wallet")
    assert "crypto_wallet" in str(e.value)


def test_an_unknown_risk_level_is_refused():
    with pytest.raises(ValueError) as e:
        _p(risk_tolerance="yolo")
    assert "yolo" in str(e.value)


def test_an_unknown_source_is_refused():
    with pytest.raises(ValueError):
        _p(source="telepathy")


def test_every_account_type_is_accepted():
    """★짝★ — 전부 거부하는 구현을 배제한다."""
    for account in ACCOUNT_TYPES:
        assert _p(account_type=account).account_type == account


# ── 라벨 ────────────────────────────────────────────────────────────────────

def test_a_profile_declares_whether_its_horizon_was_measured_or_defaulted():
    """★호출부가 기본값을 쓰기로 정하면 그 사실이 결과에 라벨로 남는다★(RA5)."""
    known = _p(horizon_days=252, source="user_declared")
    assert known.horizon_label()["state"] == "declared"
    assert _p().horizon_label()["state"] == "unknown"
    assert _p().horizon_label()["reason"]


def test_the_profile_round_trips_to_a_dict():
    d = _p(horizon_days=252).to_dict()
    assert d["accountType"] == ACCOUNT_IRP
    assert d["horizonDays"] == 252
    assert d["riskAversion"] is None


def test_a_profile_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _p().risk_tolerance = "aggressive"  # type: ignore[misc]


# ── ★결정 경로를 건드리지 않았다★ ───────────────────────────────────────

def test_the_decision_path_signature_is_untouched():
    """RA5 가 ★승인 필요★ 라 적은 경계 — `decide()` 가 프로파일을 받지 않는다."""
    import inspect

    from src.engine.investment_decision import decide
    params = set(inspect.signature(decide).parameters)
    assert "profile" not in params and "investor_profile" not in params


def test_the_domain_module_stays_pure():
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for name in imported:
        for bad in ("sqlalchemy", "fastapi", "requests", "src.database", "src.engine"):
            assert not name.startswith(bad), f"순수 계층이 {name} 을 import 한다"
