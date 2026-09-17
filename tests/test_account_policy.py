"""AD1 — 계좌 제약 어휘와 판정의 계약 (순수 계층).

★이 파일이 지키는 단 하나★ — **한도를 모르면 통과가 아니다**. `run_evidence` 의
`AXIS_UNKNOWN` 이 통과가 아닌 것과 같은 규율이고, 계좌 제약에서는 그것이 곧
"법규를 검증했다" 는 거짓 주장을 막는 장치다.
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from src.domain.account_policy import (
    ACCOUNT_GENERAL,
    ACCOUNT_IRP,
    ACCOUNT_ISA,
    ACCOUNT_LIMIT_SLOTS,
    ACCOUNT_PENSION_SAVINGS,
    ACCOUNT_TYPES,
    DIRECTION_MAX,
    DIRECTION_MIN,
    LIMIT_DIRECTION,
    LIMIT_KINDS,
    LIMIT_MIN_HOLDING_DAYS,
    LIMIT_RISKY_ASSET_MAX_PCT,
    UNDECLARED_REASON,
    VERDICT_BREACH,
    VERDICT_PASS,
    VERDICT_UNDETERMINED,
    AccountLimit,
    judge_account,
    judge_limit,
    undeclared_limits,
)

_MODULE = pathlib.Path(__file__).resolve().parents[1] / "src" / "domain" / "account_policy.py"


def _declared(kind: str, value: float, as_of: str = "2026-01-01") -> AccountLimit:
    return AccountLimit(kind=kind, value=value, source="운영자 선언(테스트)", as_of=as_of)


# ── 어휘 ────────────────────────────────────────────────────────────────────

def test_the_four_account_types_are_the_vocabulary():
    """RA5 도메인 문서의 어휘 그대로 — 새로 만들지 않는다."""
    assert ACCOUNT_TYPES == (ACCOUNT_GENERAL, ACCOUNT_PENSION_SAVINGS,
                             ACCOUNT_IRP, ACCOUNT_ISA)


def test_each_account_type_has_its_own_slot_set():
    """★계좌마다 제약이 다르다★ — 넷이 전부 같으면 계좌 구분이 장식이다."""
    slot_sets = {a: frozenset(ACCOUNT_LIMIT_SLOTS[a]) for a in ACCOUNT_TYPES}
    assert len(set(slot_sets.values())) > 1, "계좌 유형별 슬롯이 전부 같다"
    # 일반 위탁계좌에는 세제 한도가 없다.
    assert slot_sets[ACCOUNT_GENERAL] == frozenset()
    # IRP 는 위험자산 한도를 갖는 것으로 알려져 있다.
    assert LIMIT_RISKY_ASSET_MAX_PCT in slot_sets[ACCOUNT_IRP]


def test_every_slot_is_a_known_kind():
    for account, kinds in ACCOUNT_LIMIT_SLOTS.items():
        assert account in ACCOUNT_TYPES
        for kind in kinds:
            assert kind in LIMIT_KINDS


def test_every_kind_declares_its_direction():
    """★상한과 하한을 섞지 않는다★ — 의무보유기간은 최소값이고 납입한도는 최대값이다."""
    for kind in LIMIT_KINDS:
        assert LIMIT_DIRECTION[kind] in (DIRECTION_MAX, DIRECTION_MIN)
    assert LIMIT_DIRECTION[LIMIT_MIN_HOLDING_DAYS] == DIRECTION_MIN
    assert LIMIT_DIRECTION[LIMIT_RISKY_ASSET_MAX_PCT] == DIRECTION_MAX


# ── ★값이 없으면 반드시 사유★ ─────────────────────────────────────────────

def test_an_unknown_limit_cannot_exist_without_a_reason():
    """★구조적으로 불가능하게 만든다★ — 사유 없는 미상은 생성 자체가 실패한다."""
    with pytest.raises(ValueError):
        AccountLimit(kind=LIMIT_RISKY_ASSET_MAX_PCT, value=None, reason=None)


def test_the_default_limits_are_all_undeclared_with_the_same_reason():
    """★법규 수치를 이 저장소가 들고 있지 않다★ — 기본은 전부 미선언이다."""
    for account in ACCOUNT_TYPES:
        for limit in undeclared_limits(account):
            assert limit.value is None
            assert limit.reason == UNDECLARED_REASON
            assert limit.source is None and limit.as_of is None


def test_the_undeclared_reason_names_who_must_declare():
    assert "운영자" in UNDECLARED_REASON
    assert "검증" in UNDECLARED_REASON


# ── ★핵심★ 미선언은 통과가 아니다 ─────────────────────────────────────────

def test_an_undeclared_limit_is_undetermined_not_pass():
    """★이 작업에서 가장 중요한 불변식★."""
    limit = AccountLimit(kind=LIMIT_RISKY_ASSET_MAX_PCT, value=None,
                         reason=UNDECLARED_REASON)
    out = judge_limit(limit, 42.0)
    assert out["verdict"] == VERDICT_UNDETERMINED
    assert out["verdict"] != VERDICT_PASS
    assert out["reason"] == UNDECLARED_REASON


def test_a_declared_limit_with_room_passes():
    """★짝★ — 항상-UNDETERMINED 구현을 배제한다."""
    out = judge_limit(_declared(LIMIT_RISKY_ASSET_MAX_PCT, 70.0), 42.0)
    assert out["verdict"] == VERDICT_PASS


def test_a_declared_limit_that_is_exceeded_breaches():
    """★짝★ — 항상-PASS 구현을 배제한다."""
    out = judge_limit(_declared(LIMIT_RISKY_ASSET_MAX_PCT, 70.0), 81.0)
    assert out["verdict"] == VERDICT_BREACH


def test_an_absent_observation_is_undetermined_too():
    """한도는 있는데 **재지 못했으면** 그것도 통과가 아니다."""
    out = judge_limit(_declared(LIMIT_RISKY_ASSET_MAX_PCT, 70.0), None)
    assert out["verdict"] == VERDICT_UNDETERMINED
    assert out["reason"]


# ── ★어느 한도로 쟀는지★ ─────────────────────────────────────────────────

def test_the_verdict_records_which_limit_it_measured_against():
    limit = _declared(LIMIT_RISKY_ASSET_MAX_PCT, 70.0, as_of="2026-01-01")
    out = judge_limit(limit, 42.0)
    assert out["limit"]["value"] == 70.0
    assert out["limit"]["as_of"] == "2026-01-01"
    assert out["limit"]["source"] == "운영자 선언(테스트)"


def test_a_revised_limit_changes_the_verdict_and_keeps_its_own_as_of():
    """★개정 대비★ — 같은 보유라도 한도가 바뀌면 판정이 바뀌고, 각 판정은
    **자기가 쓴 한도의 기준일**을 들고 있다. 옛 판정이 무엇을 기준으로 한 것인지
    나중에도 읽을 수 있어야 한다."""
    old = judge_limit(_declared(LIMIT_RISKY_ASSET_MAX_PCT, 70.0, "2026-01-01"), 75.0)
    new = judge_limit(_declared(LIMIT_RISKY_ASSET_MAX_PCT, 80.0, "2027-01-01"), 75.0)
    assert old["verdict"] == VERDICT_BREACH
    assert new["verdict"] == VERDICT_PASS
    assert old["limit"]["as_of"] == "2026-01-01"
    assert new["limit"]["as_of"] == "2027-01-01"


# ── 구간 관측 (AD3 이 쓰는 계약) ──────────────────────────────────────────

def test_an_interval_fully_below_the_cap_passes():
    out = judge_limit(_declared(LIMIT_RISKY_ASSET_MAX_PCT, 70.0), (40.0, 55.0))
    assert out["verdict"] == VERDICT_PASS


def test_an_interval_fully_above_the_cap_breaches():
    out = judge_limit(_declared(LIMIT_RISKY_ASSET_MAX_PCT, 70.0), (75.0, 90.0))
    assert out["verdict"] == VERDICT_BREACH


def test_an_interval_straddling_the_cap_is_undetermined():
    """★미배정분을 0 으로 접어 '통과' 라고 말하지 않는다★."""
    out = judge_limit(_declared(LIMIT_RISKY_ASSET_MAX_PCT, 70.0), (55.0, 83.0))
    assert out["verdict"] == VERDICT_UNDETERMINED
    assert "구간" in out["reason"]


def test_a_scalar_observation_is_a_degenerate_interval():
    """★짝★ — 스칼라를 언제나 구간으로 벌리는 구현을 배제한다."""
    out = judge_limit(_declared(LIMIT_RISKY_ASSET_MAX_PCT, 70.0), 42.0)
    assert out["observed"]["lo"] == out["observed"]["hi"] == 42.0


# ── 방향이 실제로 반대로 동작한다 ────────────────────────────────────────

def test_a_minimum_limit_judges_the_other_way():
    """의무보유기간은 **넘겨야** 통과다 — 상한 로직을 그대로 쓰면 뒤집힌다."""
    limit = _declared(LIMIT_MIN_HOLDING_DAYS, 1095.0)
    assert judge_limit(limit, 1200.0)["verdict"] == VERDICT_PASS
    assert judge_limit(limit, 300.0)["verdict"] == VERDICT_BREACH


# ── 계좌 단위 판정 ────────────────────────────────────────────────────────

def test_judging_an_account_covers_every_slot_it_declares():
    out = judge_account(ACCOUNT_IRP, undeclared_limits(ACCOUNT_IRP), {})
    kinds = {v["kind"] for v in out["verdicts"]}
    assert kinds == set(ACCOUNT_LIMIT_SLOTS[ACCOUNT_IRP])


def test_an_account_with_no_declared_limits_is_undetermined_everywhere():
    out = judge_account(ACCOUNT_IRP, undeclared_limits(ACCOUNT_IRP), {})
    assert out["summary"][VERDICT_PASS] == 0
    assert out["summary"][VERDICT_UNDETERMINED] == len(ACCOUNT_LIMIT_SLOTS[ACCOUNT_IRP])


def test_a_general_account_has_nothing_to_judge_and_says_so():
    out = judge_account(ACCOUNT_GENERAL, undeclared_limits(ACCOUNT_GENERAL), {})
    assert out["verdicts"] == []
    assert out["note"], "판정할 것이 없다는 사실도 말해야 한다"


def test_an_unknown_account_type_is_refused_with_a_reason():
    with pytest.raises(ValueError) as e:
        judge_account("crypto_wallet", (), {})
    assert "crypto_wallet" in str(e.value)


def test_the_account_summary_counts_every_verdict_kind():
    limits = (_declared(LIMIT_RISKY_ASSET_MAX_PCT, 70.0),)
    out = judge_account(ACCOUNT_IRP, limits, {LIMIT_RISKY_ASSET_MAX_PCT: 90.0})
    assert out["summary"][VERDICT_BREACH] == 1
    assert set(out["summary"]) == {VERDICT_PASS, VERDICT_BREACH, VERDICT_UNDETERMINED}


# ── ★법규 수치가 소스에 없다★ ────────────────────────────────────────────

_FORBIDDEN_NUMBERS = {70.0, 70, 0.7, 900, 600, 1095,
                      20_000_000, 100_000_000, 6_000_000, 9_000_000}


def test_no_regulatory_number_is_baked_into_the_module():
    """★이 저장소는 법규 수치를 검증할 수 없다★ — 그래서 적지 않는다.

    IRP 70% · ISA 2천만/1억 · 연금저축 600만/900만 · 의무보유 1095일 어느 것도
    상수로 나타나면 안 된다. 나타나는 순간 그것은 **미검증 주장**이다.
    """
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    found = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
        and node.value in _FORBIDDEN_NUMBERS
    ]
    assert not found, f"법규 수치가 소스에 박혀 있다: {found}"


def test_the_number_detector_actually_detects():
    """★테스트의 테스트★ — 검출기를 빈 집합으로 바꾸면 위 검사가 무력해진다."""
    tree = ast.parse("RISKY_CAP = 70.0\n")
    found = [n.value for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and n.value in _FORBIDDEN_NUMBERS]
    assert found == [70.0]
    assert _FORBIDDEN_NUMBERS, "금지 목록이 비면 검사가 언제나 통과한다"


# ── 순수성 ────────────────────────────────────────────────────────────────

def test_the_domain_module_stays_pure():
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for name in imported:
        for bad in ("sqlalchemy", "fastapi", "requests", "src.database", "src.data"):
            assert not name.startswith(bad), f"순수 계층이 {name} 을 import 한다"


def test_an_account_limit_is_immutable():
    limit = _declared(LIMIT_RISKY_ASSET_MAX_PCT, 70.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        limit.value = 99.0  # type: ignore[misc]
