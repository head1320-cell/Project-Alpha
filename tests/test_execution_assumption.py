"""AG1 — 실행 가정의 계약 (순수 계층).

★저장소가 자기 기준을 어기고 있었다★ — `fill_price.py:166` 이 이동평균 체결가에서
당일을 빼며 *"주문가는 장 시작 전 계산 가능해야"* 라고 적어 뒀는데, 엔진 기본값
`signal_lag=0` 은 **신호를 당일 종가에서 뽑고 그 종가에 체결**했다. 종가가 확정되기
전에는 그 신호를 계산할 수 없으므로 그 주문은 낼 수 없다.

불변식은 간단하다: ★`signal_lag >= 1` ⟺ 결정이 장 시작 전 계산 가능★.
체결가 유형은 **별개 축**이라 판정에 넣지 않는다.
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from src.domain.execution_assumption import (
    SIGNAL_LAG_DEFAULT,
    STATE_PRECOMPUTABLE,
    STATE_SAME_BAR,
    STATE_UNRECORDED,
    UNRECORDED_REASON,
    ExecutionAssumption,
    assumption_from_result,
    assumption_label,
    decision_precomputable,
)

_MODULE = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "domain" / "execution_assumption.py")


def _a(lag, buy="close", sell="close") -> ExecutionAssumption:
    return ExecutionAssumption(signal_lag=lag, buy_fill_type=buy, sell_fill_type=sell)


# ── ★핵심★ 기본값이 1 이다 ────────────────────────────────────────────────

def test_the_default_lag_makes_the_decision_precomputable():
    """★이 파일의 핵심★ — 기본값으로 돌린 백테스트는 장 시작 전 계산 가능하다."""
    assert SIGNAL_LAG_DEFAULT == 1
    assert decision_precomputable(SIGNAL_LAG_DEFAULT) is True


def test_the_default_is_not_zero():
    """직전까지 `0` 이었다 — 당일 봉 신호·당일 체결."""
    assert SIGNAL_LAG_DEFAULT != 0


# ── 판정과 짝 ───────────────────────────────────────────────────────────────

def test_a_lag_of_one_is_precomputable():
    assert decision_precomputable(1) is True


def test_a_lag_of_zero_is_not():
    """★짝★ — 항상-True 구현을 배제한다."""
    assert decision_precomputable(0) is False


def test_a_larger_lag_is_also_precomputable():
    assert decision_precomputable(5) is True


def test_an_unrecorded_lag_is_neither_true_nor_false():
    """★미상 ≠ 0★ — `None` 을 `False` 로도 `True` 로도 접지 않는다."""
    assert decision_precomputable(None) is None


# ── 라벨 ────────────────────────────────────────────────────────────────────

def test_the_default_assumption_is_labelled_precomputable():
    out = assumption_label(_a(SIGNAL_LAG_DEFAULT))
    assert out["state"] == STATE_PRECOMPUTABLE
    assert out["reason"] is None


def test_a_same_bar_assumption_is_labelled_and_explained():
    """`lag=0` 은 **막히지 않는다** — 판정되고 사유가 붙을 뿐이다."""
    out = assumption_label(_a(0))
    assert out["state"] == STATE_SAME_BAR
    assert out["reason"], "same_bar 인데 사유가 없다"
    assert "종가" in out["reason"]


def test_an_unrecorded_assumption_says_it_cannot_tell():
    out = assumption_label(_a(None))
    assert out["state"] == STATE_UNRECORDED
    assert out["reason"] == UNRECORDED_REASON


def test_the_unrecorded_reason_says_zero_cannot_be_assumed():
    """★기록이 없는 것을 0 으로 적으면 그것이 지어낸 사실이다★."""
    assert "알 수 없" in UNRECORDED_REASON
    assert "0" in UNRECORDED_REASON


def test_the_label_carries_the_lag_and_both_fill_types():
    out = assumption_label(_a(1, buy="open", sell="prev_close"))
    assert out["signal_lag"] == 1
    assert out["buy_fill_type"] == "open"
    assert out["sell_fill_type"] == "prev_close"


# ── ★체결가 유형은 판정을 바꾸지 않는다★ (축 섞기 배제) ─────────────────

@pytest.mark.parametrize("fill", ["close", "open", "prev_close", "ma20", "pivot"])
def test_the_fill_type_never_changes_the_verdict(fill):
    """★별개 축★ — `lag=0` 이면 체결가가 무엇이든 **결정 자체**가 계산 불가다."""
    assert assumption_label(_a(0, buy=fill, sell=fill))["state"] == STATE_SAME_BAR
    assert assumption_label(_a(1, buy=fill, sell=fill))["state"] == STATE_PRECOMPUTABLE


def test_missing_fill_types_do_not_break_the_label():
    out = assumption_label(_a(1, buy=None, sell=None))
    assert out["state"] == STATE_PRECOMPUTABLE
    assert out["buy_fill_type"] is None


# ── ★단일 출처★ — 기본값이 한 곳에만 있다 ──────────────────────────────

_DECLARATION_SITES = (
    "src/kis_backtest_engine.py",
    "src/api/screener_routes.py",
)


def test_no_declaration_site_hardcodes_a_zero_default():
    """★전수★ — `signal_lag` 기본값이 `0` 으로 다시 박히면 실패한다.

    기본값이 세 곳에 흩어져 있었던 것이 애초에 서로 갈릴 수 있었던 이유다.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for rel in _DECLARATION_SITES:
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # `signal_lag: int = 0` (AnnAssign) 와 `signal_lag=0`(keyword 기본값)
            if isinstance(node, ast.AnnAssign):
                if getattr(node.target, "id", None) == "signal_lag":
                    if isinstance(node.value, ast.Constant) and node.value.value == 0:
                        offenders.append(f"{rel}: signal_lag: int = 0")
            elif isinstance(node, ast.arg) and node.arg == "signal_lag":
                pass  # 기본값은 args.defaults 에 있다 — 아래에서 본다
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = node.args.args + node.args.kwonlyargs
            defaults = list(node.args.defaults) + list(node.args.kw_defaults)
            for a, d in zip(args[-len(defaults):] if defaults else [], defaults):
                if (a.arg == "signal_lag" and isinstance(d, ast.Constant)
                        and d.value == 0):
                    offenders.append(f"{rel}: def {node.name}(signal_lag=0)")
        # ★pydantic `Field(default=0)` 도 잡는다★ — Constant 가 아니라 Call 이라
        #   위 두 갈래로는 걸리지 않는다. 실제로 세 번째 선언 지점이 이 모양이었다.
        for node in ast.walk(tree):
            if not (isinstance(node, ast.AnnAssign)
                    and getattr(node.target, "id", None) == "signal_lag"
                    and isinstance(node.value, ast.Call)):
                continue
            for kw in node.value.keywords:
                if (kw.arg == "default" and isinstance(kw.value, ast.Constant)
                        and kw.value.value == 0):
                    offenders.append(f"{rel}: signal_lag = Field(default=0)")
    assert not offenders, f"기본값 0 이 다시 박혔다: {offenders}"


#: ★골든 스냅샷★ — 검사 대상 목록 자체를 못 박는다.
#:
#: 위 전수 검사만으로는 **목록을 비우는** 변이가 살아남는다(검사할 파일이 줄 뿐
#: 이라 언제나 초록이다 — 변이 배터리의 `i` 가 실제로 그렇게 살아남았다).
#: 그런데 목록이 비는 것이 곧 이 파일이 막으려는 결함이다: 기본값이 다시 갈리는데
#: 아무도 모르는 상태. 그래서 목록을 여기 **글자로** 적는다.
#:
#: 선언 지점이 실제로 늘거나 옮겨졌다면 이 스냅샷을 고치는 것이 정상이다.
_EXPECTED_DECLARATION_SITES = (
    "src/kis_backtest_engine.py",
    "src/api/screener_routes.py",
)


def test_the_declaration_site_list_is_pinned():
    """★공허한 하네스는 증거가 아니다★ 목록이 비거나 줄면 전수 검사는 언제나 통과한다."""
    assert _DECLARATION_SITES == _EXPECTED_DECLARATION_SITES, (
        "선언 지점 목록이 바뀌었다 — 새 지점이 `SIGNAL_LAG_DEFAULT` 를 읽는지 "
        "확인하고 이 스냅샷을 갱신하세요.")
    assert _DECLARATION_SITES, "검사 대상이 없다 — 전수 검사가 공허하다"


def test_every_declared_site_really_declares_the_default():
    """★목록에 적힌 파일이 실제로 그 기본값을 읽는가★

    목록이 낡아 엉뚱한 파일을 가리키면 전수 검사는 통과하지만 아무것도 안 지킨다.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    for rel in _DECLARATION_SITES:
        text = (root / rel).read_text(encoding="utf-8")
        assert "signal_lag" in text, f"{rel} 에 signal_lag 선언이 없다 — 목록이 낡았다"
        assert "SIGNAL_LAG_DEFAULT" in text, (
            f"{rel} 이 단일 출처 상수를 읽지 않는다")


def test_the_detector_actually_detects():
    """★테스트의 테스트★ — 검출기가 명백한 위반을 잡는지."""
    tree = ast.parse("signal_lag: int = 0\n")
    found = [n for n in ast.walk(tree)
             if isinstance(n, ast.AnnAssign)
             and getattr(n.target, "id", None) == "signal_lag"
             and isinstance(n.value, ast.Constant) and n.value.value == 0]
    assert found, "검출기가 명백한 위반을 놓친다"


# ── 타입·순수성 ────────────────────────────────────────────────────────────

def test_the_assumption_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _a(1).signal_lag = 0  # type: ignore[misc]


def test_the_domain_module_stays_pure():
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for name in imported:
        for bad in ("sqlalchemy", "fastapi", "requests", "pandas",
                    "src.database", "src.data", "src.engine"):
            assert not name.startswith(bad), f"순수 계층이 {name} 을 import 한다"


# ═══════════════════════════════════════════════════════════════════════════
# ★저장된 실행을 되읽는다★ — AG2 를 컬럼이 아니라 `result` JSON 으로 한 이유
#
# 계획은 `backtest_runs` 에 세 컬럼을 붙이는 것이었다. ★실측이 계획을 뒤집었다★:
#   · `set_result()` 가 엔진 결과 dict 를 통째로 `result` TEXT 에 JSON 으로 넣고
#     `_row()` 가 그대로 되읽는다 — 컬럼이 없어도 값은 이미 영속된다.
#   · 그리고 더 중요한 것: 요청 설정(`input_snapshot`)에는 `signal_lag` 이 **없을
#     수 있다**(클라이언트가 안 보내면 기본값이 엔진에서 정해진다). 컬럼에 요청값을
#     적었다면 ★기본값으로 실행된 런이 미상으로 기록★되었을 것이다.
# 그래서 기록하는 것은 **엔진이 실제로 쓴 값**이고, 그것이 결과 블록이다.
# ═══════════════════════════════════════════════════════════════════════════

def test_a_recorded_run_reads_back_its_assumption():
    got = assumption_from_result({"execution_assumption": {
        "signal_lag": 1, "buy_fill_type": "close", "sell_fill_type": "close"}})
    assert got["state"] == STATE_PRECOMPUTABLE
    assert got["signal_lag"] == 1
    assert got["reason"] is None


def test_a_run_recorded_as_same_bar_reads_back_as_same_bar():
    """★짝★ 리더가 무엇을 읽든 `precomputable` 을 내지는 않는다."""
    got = assumption_from_result({"execution_assumption": {"signal_lag": 0}})
    assert got["state"] == STATE_SAME_BAR
    assert got["precomputable_before_open"] is False


def test_a_run_from_before_the_recording_is_unrecorded_not_zero():
    """★미상 ≠ 0★ 기록 이전 런은 `same_bar` 가 아니라 `unrecorded` 다."""
    got = assumption_from_result({"currency": "KRW", "result": {}})
    assert got["state"] == STATE_UNRECORDED
    assert got["signal_lag"] is None, "없는 기록을 0 으로 읽었다"
    assert got["precomputable_before_open"] is None


def test_a_missing_record_is_unrecorded():
    for empty in (None, {}):
        assert assumption_from_result(empty)["state"] == STATE_UNRECORDED


def test_a_malformed_block_is_unrecorded_not_a_crash():
    """블록이 dict 가 아니면 **미상**이다 — 지어내지도, 터지지도 않는다."""
    for junk in ("precomputable", 1, [], {"signal_lag": None}):
        got = assumption_from_result({"execution_assumption": junk})
        assert got["state"] == STATE_UNRECORDED, junk


def test_the_reader_does_not_label_everything_unrecorded():
    """★짝★ 언제나 `unrecorded` 를 내는 리더를 배제한다."""
    states = {assumption_from_result({"execution_assumption": {"signal_lag": lag}})["state"]
              for lag in (0, 1, 2)}
    assert states == {STATE_SAME_BAR, STATE_PRECOMPUTABLE}
