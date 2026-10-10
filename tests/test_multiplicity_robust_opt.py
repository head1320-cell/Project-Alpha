"""AJ4 — ★결정에 닿는 유일한 다중검정 자리 — 관측·라벨만, 수치 불변★

`robust_opt.mu_standard_errors` 는 자산마다 `|μ|/SE ≥ 2` 를 **동시에** 판정하고,
그 결과가 `uncertainty_scalar` 를 거쳐 **리밸런싱 밴드**(`1+u` 배)로 간다.
즉 ★보정 없는 단일검정 임계가 실제로 비중을 움직인다.★

## ★이 파일의 요점은 "안 바뀌었음" 이다★

임계를 고치는 것은 **배분 동작 변경**이라 별도 승인 사항이다(CLAUDE.md §3).
그래서 이 작업은 *"보정하면 임계가 얼마이고 몇 개가 살아남는가"* 를 **보고만**
한다. `_RESOLVABLE_T`·`resolvable`·`n_resolvable`·`uncertainty_scalar` 는
한 글자도 바뀌지 않는다 — AH 가 누출을 관측만 한 것과 같은 경계다.
"""
from __future__ import annotations

import ast
import os
import pathlib

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.robust_opt import (  # noqa: E402
    _RESOLVABLE_T,
    mu_standard_errors,
    uncertainty_scalar,
)

_MODULE = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "engine" / "robust_opt.py")


def _returns(n_assets: int = 10, days: int = 504, seed: int = 20260915):
    """자산마다 드리프트가 다른 합성 수익률 — 일부는 해소되고 일부는 안 된다."""
    rng = np.random.default_rng(seed)
    drift = np.linspace(0.0, 0.0012, n_assets)
    return rng.normal(0.0, 0.01, size=(days, n_assets)) + drift


@pytest.fixture(scope="module")
def est():
    return mu_standard_errors(_returns())


# ═══════════════════════════════════════════════════════════════════════════
# ⑩ ★수치 불변★ — 이것이 이 작업의 경계 판정이다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_single_test_threshold_is_untouched():
    """★배분 동작 변경은 별도 승인★ (CLAUDE.md §3)"""
    assert _RESOLVABLE_T == 2.0


def test_resolvable_still_uses_the_raw_threshold(est):
    for x, flag in zip(est["t"], est["resolvable"]):
        assert flag is bool(x >= 2.0)
    assert est["n_resolvable"] == sum(est["resolvable"])


def test_the_uncertainty_scalar_did_not_move(est):
    """★밴드를 먹이는 값이 그대로여야 한다★"""
    t = np.asarray(est["t"], dtype=float)
    expected = float(np.clip(1.0 - (np.clip(t, 0.0, 2.0) / 2.0).mean(), 0.0, 1.0))
    assert uncertainty_scalar(t) == pytest.approx(expected)


def test_the_original_keys_are_all_still_there(est):
    for key in ("available", "reason", "mu", "se", "t", "n_obs", "years",
                "resolvable", "n_resolvable", "note"):
        assert key in est, key


# ═══════════════════════════════════════════════════════════════════════════
# ⑪ ★보정이 없다는 사실과 그 크기를 보고한다★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_family_is_declared_at_last(est):
    """★지금까지 몇 개를 동시에 보는지 선언조차 없었다★"""
    m = est["multiplicity"]
    assert m["family_size"] == 10
    assert m["family_source"] == "declared"


def test_the_block_admits_no_correction_is_applied(est):
    m = est["multiplicity"]
    assert m["correction"] == "none"
    assert m["applied"] is False
    assert m["reason"]


def test_the_corrected_threshold_is_stricter_than_the_live_one(est):
    """★보정하면 문턱이 **올라간다**★ — 내려가면 그것은 보정이 아니다."""
    m = est["multiplicity"]
    assert m["bonferroni_t"] > _RESOLVABLE_T


def test_fewer_survive_under_the_corrected_threshold(est):
    m = est["multiplicity"]
    assert m["n_resolvable_if_corrected"] <= est["n_resolvable"]
    assert m["n_resolvable_if_corrected"] == sum(
        1 for x in est["t"] if x >= m["bonferroni_t"])


def test_the_threshold_tightens_as_the_family_grows():
    """★상수 구현을 배제한다★ — 자산이 많을수록 임계가 높아져야 한다."""
    small = mu_standard_errors(_returns(n_assets=3))["multiplicity"]["bonferroni_t"]
    big = mu_standard_errors(_returns(n_assets=40))["multiplicity"]["bonferroni_t"]
    assert big > small


def test_the_note_says_the_threshold_was_not_changed(est):
    note = est["multiplicity"]["note"]
    assert "바꾸지 않" in note or "바뀌지 않" in note


def test_an_unusable_sample_has_no_multiplicity_block():
    """★계산을 못 했으면 블록을 지어내지 않는다★"""
    out = mu_standard_errors(np.zeros((1, 3)))
    assert out["available"] is False and out["reason"]
    assert "multiplicity" not in out


# ═══════════════════════════════════════════════════════════════════════════
# ★범위 위반 트립와이어★ — 변이 i·j 를 잡는다
# ═══════════════════════════════════════════════════════════════════════════

def _module_tree() -> ast.Module:
    return ast.parse(_MODULE.read_text(encoding="utf-8"))


def test_the_resolvable_threshold_constant_is_assigned_exactly_once():
    """★보정값으로 덮어쓰는 변이를 잡는다★"""
    assigns = [n for n in ast.walk(_module_tree())
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "_RESOLVABLE_T"
                       for t in n.targets)]
    assert len(assigns) == 1, "임계 상수가 두 번 대입된다 — 어디선가 덮고 있다"
    assert isinstance(assigns[0].value, ast.Constant)
    assert assigns[0].value.value == 2.0


def test_the_uncertainty_scalar_never_reads_the_corrected_threshold():
    """★보정 t 가 밴드로 새어 들어가면 그것은 배분 동작 변경이다★"""
    fn = next(n for n in ast.walk(_module_tree())
              if isinstance(n, ast.FunctionDef) and n.name == "uncertainty_scalar")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    for banned in ("corrected_t_threshold", "bonferroni_t", "bonferroni_alpha",
                   "multiplicity"):
        assert banned not in names, f"`uncertainty_scalar` 가 {banned} 를 읽는다"


def test_the_solver_never_reads_the_corrected_threshold():
    """`_solve_robust` 도 마찬가지다 — 최적화 의미 변경은 별도 승인이다."""
    fn = next(n for n in ast.walk(_module_tree())
              if isinstance(n, ast.FunctionDef) and n.name == "_solve_robust")
    src = ast.unparse(fn)
    for banned in ("corrected_t_threshold", "bonferroni"):
        assert banned not in src, f"`_solve_robust` 가 {banned} 를 읽는다"


def test_this_guard_is_not_vacuous():
    """★검사의 검사★ — 위 두 함수가 실제로 존재해야 검사가 뜻을 가진다."""
    names = {n.name for n in ast.walk(_module_tree())
             if isinstance(n, ast.FunctionDef)}
    assert {"uncertainty_scalar", "_solve_robust", "mu_standard_errors"} <= names
