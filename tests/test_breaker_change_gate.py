"""AU · ★결정을 산문이 아니라 문으로★ — 업무 응답을 breaker 에서 뺄 수 있는가
==============================================================================
대상: `src/domain/breaker_change_gate.py` · 선례
`src/domain/distribution_gate.py` + `tests/test_distribution_blocked.py`

## 왜 이 파일이 생겼나

AR 이 드러낸 안전 역전이 네 프로그램째 살아 있다 — 정상 업무 응답이 KIS
장애와 같은 breaker 카운터에 들어간다. HISTORY 에 *"바꾸지 않았다"* 고 적은
것이 벌써 **네 번**이고, ★산문은 내일 누군가 그냥 바꿔도 아무것도 깨지지
않는다★. 그래서 이번에는 **통과해야 하는 문**을 남긴다.

## ★질문이 잘못 놓여 있었다★

"업무 응답을 빼자" 는 **종류 단위** 질문인데, `business` 는 의미가 아니라
**모양**(HTTP 200 + `rt_cd != "0"`)이다. 그 안에 '장 종료'(안전 문제 아님)와
'KIS 내부 오류'(진짜 장애)가 섞여 있을 수 있으므로, ★종류 통째로 빼면 그 안의
진짜 장애까지 같이 빠진다★. 판정 단위는 `(rt_cd, msg_cd)` 하나하나다.

## ★어휘가 모자란다는 것도 실측이다★

AR 의 책임 소재 축은 `provider`·`self`·`unknown` 셋인데 '장 종료' 의 정직한
답은 **아무의 문제도 아니다** 이고 그런 값이 없다. `self` 로 우겨 넣는 것은
어휘를 비트는 일이라, 게이트는 목적 전용 칸 `outage` 를 쓴다.

## ★여기서 재는 것★

- 기본이 **언제나 막힘**인가(빈 표에서 어느 코드도 통과 못 한다).
- ★그런데 항상-거부가 아닌가★ — 조건을 채우면 실제로 열린다(짝).
- 조건 하나하나가 **각각** 문다(넷을 한 덩어리로 검사하면 셋이 죽어도 통과).
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from src.domain.breaker_change_gate import (
    CHANGE_ALLOWED,
    CHANGE_BLOCKED,
    COND_MEANING,
    COND_NOT_OUTAGE,
    COND_OBSERVED,
    COND_REAL_SOURCE,
    CONDITIONS,
    MIN_OBSERVATIONS,
    gate_summary,
    may_stop_counting,
)

_MODULE = pathlib.Path("src/domain/breaker_change_gate.py")


def _evidence(tmp_path, monkeypatch, entry=None, *, key="1/A"):
    codes = {key: entry} if entry is not None else {}
    p = tmp_path / "ev.json"
    p.write_text(json.dumps({"schema": 1, "min_grade_to_apply": "K2",
                             "why_empty": "테스트", "codes": codes},
                            ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("KIS_RT_CD_EVIDENCE_PATH", str(p))
    return p


def _good_entry(**over):
    """★모든 조건을 충족하는 항목★ — 짝 테스트의 기준선."""
    entry = {"rt_cd": "1", "msg_cd": "A", "meaning": "장 종료",
             "fault": "unknown", "outage": False, "grade": "K2",
             "evidence_source": "KIS 문서"}
    entry.update(over)
    return entry


def _good_obs(**over):
    obs = {"rt_cd": "1", "msg_cd": "A", "count": MIN_OBSERVATIONS,
           "execution_mode": "live"}
    obs.update(over)
    return obs


# ── ★기본은 언제나 막힘★ ───────────────────────────────────────────────

def test_an_empty_table_blocks_every_code(tmp_path, monkeypatch):
    _evidence(tmp_path, monkeypatch)
    out = may_stop_counting("1", "A", observation=_good_obs())
    assert out["state"] == CHANGE_BLOCKED
    assert out["reason"]


def test_no_observation_at_all_blocks(tmp_path, monkeypatch):
    _evidence(tmp_path, monkeypatch, _good_entry())
    out = may_stop_counting("1", "A", observation=None)
    assert out["state"] == CHANGE_BLOCKED
    assert COND_OBSERVED in out["unmet"]


def test_the_gate_names_every_unmet_condition(tmp_path, monkeypatch):
    """★막힌 사람이 무엇을 해야 하는지 모르면 그 거부는 절반만 정직하다★"""
    _evidence(tmp_path, monkeypatch)
    out = may_stop_counting("1", "A", observation=None)
    assert set(out["unmet"]) >= {COND_MEANING, COND_NOT_OUTAGE, COND_OBSERVED}
    for name in out["unmet"]:
        assert out["conditions"][name]["reason"], name


def test_every_condition_is_reported_whether_met_or_not(tmp_path, monkeypatch):
    """★키가 사라지지 않는다★ — 빠진 조건은 소비자가 못 보고 지나간다."""
    _evidence(tmp_path, monkeypatch, _good_entry())
    out = may_stop_counting("1", "A", observation=_good_obs())
    assert set(out["conditions"]) == set(CONDITIONS)


# ── ★그런데 항상-거부가 아니다★ (CLAUDE.md §5 의 짝) ──────────────────

def test_a_fully_satisfied_code_is_allowed(tmp_path, monkeypatch):
    """변이 b — ★게이트가 언제나 막으면 죽는다★

    이것이 없으면 `return blocked` 한 줄짜리 구현이 모든 테스트를 통과한다.
    """
    _evidence(tmp_path, monkeypatch, _good_entry())
    out = may_stop_counting("1", "A", observation=_good_obs())
    assert out["state"] == CHANGE_ALLOWED, out
    assert out["unmet"] == []
    assert out["reason"] is None


# ── ★조건 하나하나가 각각 문다★ ───────────────────────────────────────

def test_an_unknown_outage_blocks(tmp_path, monkeypatch):
    """변이 c — ★미상은 통과가 아니다★ (`null` 은 모른다는 뜻)."""
    _evidence(tmp_path, monkeypatch, _good_entry(outage=None))
    out = may_stop_counting("1", "A", observation=_good_obs())
    assert out["state"] == CHANGE_BLOCKED
    assert COND_NOT_OUTAGE in out["unmet"]


def test_a_real_outage_blocks(tmp_path, monkeypatch):
    """변이 d — ★가장 위험한 변이★

    `outage: true` 는 이 코드가 **진짜 KIS 장애**를 뜻한다는 것이다. 그것을
    안 세면 안전장치를 끄는 것이다.
    """
    _evidence(tmp_path, monkeypatch, _good_entry(outage=True))
    out = may_stop_counting("1", "A", observation=_good_obs())
    assert out["state"] == CHANGE_BLOCKED
    assert COND_NOT_OUTAGE in out["unmet"]


@pytest.mark.parametrize("bad", ["K0", "K1", "K9", "", None])
def test_a_grade_below_the_floor_blocks(tmp_path, monkeypatch, bad):
    """변이 e — AS 의 적용선을 우회하면 죽는다."""
    _evidence(tmp_path, monkeypatch, _good_entry(grade=bad))
    out = may_stop_counting("1", "A", observation=_good_obs())
    assert out["state"] == CHANGE_BLOCKED
    assert COND_MEANING in out["unmet"]


def test_a_mock_observation_blocks(tmp_path, monkeypatch):
    """변이 f — ★합성이 증거 행세를 하면 죽는다★"""
    _evidence(tmp_path, monkeypatch, _good_entry())
    out = may_stop_counting("1", "A",
                            observation=_good_obs(execution_mode="mock"))
    assert out["state"] == CHANGE_BLOCKED
    assert COND_REAL_SOURCE in out["unmet"]


@pytest.mark.parametrize("mode", [None, "", "미상", "unknown"])
def test_an_unknown_execution_mode_blocks(tmp_path, monkeypatch, mode):
    """★모드를 모르면 그 관측이 실제인지도 모른다★"""
    _evidence(tmp_path, monkeypatch, _good_entry())
    out = may_stop_counting("1", "A",
                            observation=_good_obs(execution_mode=mode))
    assert out["state"] == CHANGE_BLOCKED
    assert COND_REAL_SOURCE in out["unmet"]


def test_too_few_observations_block(tmp_path, monkeypatch):
    """변이 g — 본 적 거의 없는 코드를 면제하면 죽는다."""
    _evidence(tmp_path, monkeypatch, _good_entry())
    out = may_stop_counting("1", "A",
                            observation=_good_obs(count=MIN_OBSERVATIONS - 1))
    assert out["state"] == CHANGE_BLOCKED
    assert COND_OBSERVED in out["unmet"]


def test_exactly_the_minimum_is_enough(tmp_path, monkeypatch):
    """★경계를 어느 쪽으로 여는지 못 박는다★ — 이상(>=)이다."""
    _evidence(tmp_path, monkeypatch, _good_entry())
    out = may_stop_counting("1", "A",
                            observation=_good_obs(count=MIN_OBSERVATIONS))
    assert out["state"] == CHANGE_ALLOWED


def test_the_key_is_both_codes(tmp_path, monkeypatch):
    """변이 j — 종류 단위로 판정하면 죽는다. `rt_cd` 만 같아도 다른 코드다."""
    _evidence(tmp_path, monkeypatch, _good_entry())
    out = may_stop_counting("1", "B", observation=_good_obs(msg_cd="B"))
    assert out["state"] == CHANGE_BLOCKED
    assert COND_MEANING in out["unmet"]


def test_a_missing_msg_cd_blocks(tmp_path, monkeypatch):
    """★열쇠가 반쪽이면 어느 코드인지 모른다★"""
    _evidence(tmp_path, monkeypatch, _good_entry())
    out = may_stop_counting("1", None, observation=_good_obs(msg_cd=None))
    assert out["state"] == CHANGE_BLOCKED


# ── ★어휘를 비틀어 쓰지 않는다★ ───────────────────────────────────────

def test_the_fault_axis_does_not_open_the_gate(tmp_path, monkeypatch):
    """변이 k — `fault` 를 `outage` 대신 쓰면 죽는다.

    AR 의 축은 ★누구의 문제인가★(provider·self·unknown)이고 '장 종료' 에
    맞는 값이 없다. 게이트는 목적 전용 칸을 쓴다 — `fault` 가 무엇이든
    `outage` 가 `false` 가 아니면 막힌다.
    """
    for fault in ("provider", "self", "unknown"):
        _evidence(tmp_path, monkeypatch,
                  _good_entry(fault=fault, outage=None))
        out = may_stop_counting("1", "A", observation=_good_obs())
        assert out["state"] == CHANGE_BLOCKED, fault


def test_the_fault_axis_does_not_close_an_otherwise_open_gate(tmp_path, monkeypatch):
    """★짝★ — `fault` 는 이 판정과 무관하다(어느 값이어도 열린다)."""
    for fault in ("provider", "self", "unknown", None):
        _evidence(tmp_path, monkeypatch, _good_entry(fault=fault))
        out = may_stop_counting("1", "A", observation=_good_obs())
        assert out["state"] == CHANGE_ALLOWED, fault


# ── ★전체 판정★ ───────────────────────────────────────────────────────

def test_the_summary_of_an_empty_table_is_blocked(tmp_path, monkeypatch):
    _evidence(tmp_path, monkeypatch)
    s = gate_summary([])
    assert s["state"] == CHANGE_BLOCKED
    assert s["allowed_codes"] == []
    assert s["reason"]


def test_an_empty_table_does_not_claim_every_code_passes(tmp_path, monkeypatch):
    """변이 l — ★공허한 전칭★ 금지. `all([])` 은 `True` 다."""
    _evidence(tmp_path, monkeypatch)
    s = gate_summary([])
    assert s["state"] != CHANGE_ALLOWED
    assert s["n_allowed"] == 0


def test_the_summary_lists_which_codes_would_be_exempt(tmp_path, monkeypatch):
    """★짝★ — 조건을 채운 코드는 실제로 목록에 오른다."""
    _evidence(tmp_path, monkeypatch, _good_entry())
    s = gate_summary([_good_obs()])
    assert [c["key"] for c in s["allowed_codes"]] == ["1/A"]
    assert s["n_allowed"] == 1


def test_the_summary_separates_blocked_codes_with_reasons(tmp_path, monkeypatch):
    _evidence(tmp_path, monkeypatch, _good_entry(outage=True))
    s = gate_summary([_good_obs()])
    assert s["allowed_codes"] == []
    assert s["blocked_codes"][0]["unmet"]


def test_the_summary_is_blocked_while_any_code_is_blocked(tmp_path, monkeypatch):
    """★일부만 통과한 것은 통과가 아니다★ — 전체 상태는 보수적으로 잡는다."""
    _evidence(tmp_path, monkeypatch, _good_entry())
    s = gate_summary([_good_obs(), _good_obs(msg_cd="B")])
    assert s["n_allowed"] == 1
    assert s["state"] == CHANGE_BLOCKED


# ── ★순수★ ────────────────────────────────────────────────────────────

def test_the_module_imports_no_database_or_network():
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for banned in ("requests", "sqlalchemy", "httpx", "urllib"):
        assert banned not in imported, banned


def test_the_module_reuses_the_table_rather_than_reimplementing_it():
    """★적용선 판정은 AS 에 있다★ — 두 벌이면 한쪽만 고쳐도 안 깨진다."""
    src = _MODULE.read_text(encoding="utf-8")
    assert "kis_rt_cd" in src
    assert "min_grade_to_apply" not in src, "적용선을 여기서 다시 구현하고 있다"
