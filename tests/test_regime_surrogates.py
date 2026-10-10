"""국면 경로 ★서로게이트★ — 잘못 만들면 거짓 양성이 난다 (M1)
==============================================================================
설계·사전등록: `docs/superpowers/specs/2026-08-29-macro-regime-negative-control-design.md`

## ★실측이 이 모듈의 설계를 정했다★

실제 국면 경로는 82개월에 런 26개(평균 3.15개월)로 **지속성**이 있다. 단순 셔플은
런을 61~71개로 쪼개 평균 회전율을 8.5% → 11.5~13.1% 로 올린다. 그러면 널 팔이
**비용 때문에** 불리해지고, 그 상태로 "진짜가 낫다" 고 결론내면 ★정보가 아니라
지속성 파괴를 잰 것★이다 — 거짓 양성.

순환이동은 **주변분포를 정확히** 보존하고 런 구조를 거의 그대로 둔 채(감싸는 지점
하나만 갈라져 런 수가 최대 1 달라진다) 오직 **수익과의 정렬**만 깬다.

## ★보존 성질은 선언하지 않고 잰다★

"이 방법은 주변분포를 보존합니다" 를 상수표에 적으면 구현이 바뀌어도 표는 그대로다.
`preserved_properties(before, after)` 가 **비교해서** 답한다.
"""

from __future__ import annotations

import ast
import copy
import itertools
import os
from pathlib import Path

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

import src.engine.regime_surrogates as rs  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE = "regime_surrogates"

#: 실제 경로를 닮은 픽스처 — 런이 있고 라벨이 넷이다.
LABELS = (["G"] * 4 + ["R"] * 3 + ["S"] * 2 + ["D"] * 5 + ["G"] * 2
          + ["R"] * 4 + ["S"] * 3 + ["G"] * 1 + ["D"] * 2)
POINTS = [{"t": f"20{18 + i // 12:02d}-{i % 12 + 1:02d}", "growth": 0.1,
           "inflation": -0.2, "regime": g} for i, g in enumerate(LABELS)]


def _labels(pts):
    return [p["regime"] for p in pts]


def _n_runs(seq):
    return len([1 for _, _ in itertools.groupby(seq)])


# ══════════════════════════════════════════════════════════════════════════
# G1·G2 ★순환이동이 지속성을 지킨다 — 단순 셔플은 부순다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_circular_shift_preserves_the_marginal_exactly():
    """주변분포가 정확히 같아야 널이 '같은 국면 구성, 다른 시점' 을 뜻한다."""
    for k in (1, 5, 13, len(POINTS) - 1):
        out = rs.circular_shift(POINTS, k)
        assert rs.marginal(out) == rs.marginal(POINTS), k


def test_a_circular_shift_changes_the_run_count_by_at_most_one():
    """★감싸는 지점 하나만 갈라진다★ — 실측에서 26 → 26~27 이었다.

    "런 길이 다중집합을 정확히 보존" 은 **틀린 진술**이다(선형 수열에서는 감싸인
    런이 양끝으로 쪼개진다). 참인 것은 런 **수**가 최대 1 달라진다는 것이고,
    회전율을 지키는 데는 그것으로 충분하다.
    """
    base = _n_runs(_labels(POINTS))
    for k in range(1, len(POINTS)):
        got = _n_runs(_labels(rs.circular_shift(POINTS, k)))
        assert abs(got - base) <= 1, (k, base, got)


def test_a_naive_shuffle_destroys_the_persistence_that_the_shift_keeps():
    """★짝 — 이 테스트가 설계의 이유다★

    단순 셔플을 널로 쓰면 런이 쪼개져 회전율이 오르고, 널 팔이 비용 때문에
    불리해진다. 그 상태의 "진짜가 낫다" 는 정보가 아니라 지속성 파괴다.
    """
    rng = np.random.default_rng(0)
    base = _n_runs(_labels(POINTS))
    naive = [_n_runs(list(rng.permutation(_labels(POINTS)))) for _ in range(20)]
    shifted = [_n_runs(_labels(rs.circular_shift(POINTS, k)))
               for k in range(1, len(POINTS))]
    assert min(naive) > max(shifted), (base, min(naive), max(shifted))


def test_the_preservation_is_measured_not_declared():
    """상수표에 적으면 구현이 바뀌어도 표는 그대로다 — 비교해서 답한다."""
    p = rs.preserved_properties(POINTS, rs.circular_shift(POINTS, 7))
    assert p["marginal_preserved"] is True
    assert abs(p["run_count_delta"]) <= 1
    assert p["n_runs_before"] == _n_runs(_labels(POINTS))

    rng = np.random.default_rng(1)
    naive = [{**q, "regime": r} for q, r in
             zip(POINTS, rng.permutation(_labels(POINTS)), strict=True)]
    q = rs.preserved_properties(POINTS, naive)
    assert q["marginal_preserved"] is True          # 셔플도 주변분포는 지킨다
    assert q["run_count_delta"] > 1                 # ★지속성은 부순다★


# ══════════════════════════════════════════════════════════════════════════
# G3·G4 시간 격자와 거부
# ══════════════════════════════════════════════════════════════════════════
def test_the_month_grid_is_never_moved():
    """★`t` 를 옮기면 `_truncated_points` 가 다른 방식으로 자른다★ — 라벨만 옮긴다."""
    for fn in (lambda: rs.circular_shift(POINTS, 3),
               lambda: rs.constant_path(POINTS),
               lambda: rs.markov_surrogate(POINTS, np.random.default_rng(0))):
        out = fn()
        assert [p["t"] for p in out] == [p["t"] for p in POINTS]
        assert len(out) == len(POINTS)


def test_the_identity_shift_is_refused():
    """★항등을 널 표본으로 세면 널이 진짜 팔로 오염된다★"""
    with pytest.raises(ValueError):
        rs.circular_shift(POINTS, 0)
    with pytest.raises(ValueError):
        rs.circular_shift(POINTS, len(POINTS))


def test_an_unknown_null_or_arm_is_refused():
    with pytest.raises(ValueError):
        rs.surrogate_path(POINTS, "regime-magic", np.random.default_rng(0))


# ══════════════════════════════════════════════════════════════════════════
# G5·G6·G7 보조 널과 상수 경로
# ══════════════════════════════════════════════════════════════════════════
def test_the_markov_surrogate_keeps_persistence_in_distribution():
    """전이행렬에서 뽑으므로 런이 **분포적으로** 보존된다 — 셔플보다 훨씬 길다."""
    rng = np.random.default_rng(3)
    runs = [_n_runs(_labels(rs.markov_surrogate(POINTS, rng))) for _ in range(30)]
    naive = [_n_runs(list(rng.permutation(_labels(POINTS)))) for _ in range(30)]
    assert float(np.mean(runs)) < float(np.mean(naive))


def test_the_transition_matrix_rows_are_probabilities():
    tm = rs.transition_matrix(POINTS)
    assert set(tm) == set(rs.marginal(POINTS))
    for row in tm.values():
        assert abs(sum(row.values()) - 1.0) < 1e-9


def test_the_block_surrogate_reports_the_block_length_it_used():
    """블록 길이는 **관측된 평균 런 길이**에서 나온다 — 지어내지 않는다."""
    rng = np.random.default_rng(5)
    out = rs.block_surrogate(POINTS, rng)
    assert len(out) == len(POINTS)
    assert out[0]["surrogate_block"] == rs.default_block(POINTS)
    assert rs.default_block(POINTS) >= 1


def test_a_constant_path_has_no_timing_left():
    """★타이밍을 전부 없애고 수준만 남긴다★ — `-const` 대조군과 같은 이유."""
    out = rs.constant_path(POINTS)
    assert _n_runs(_labels(out)) == 1
    assert len(set(_labels(out))) == 1
    # ★최빈 라벨 · 동률이면 사전순 첫 번째★ — 이 픽스처는 G/R/D 가 7개월씩 3중
    # 동률이라 규칙이 없으면 dict 삽입 순서에 결과가 달린다(실제로 겪었다).
    marg = rs.marginal(POINTS)
    assert sorted(marg.values(), reverse=True)[:3] == [7, 7, 7], marg
    assert _labels(out)[0] == "D"


def test_the_modal_tie_break_is_declared_not_accidental():
    """★짝★ 동률에서 삽입 순서에 기대는 구현을 배제한다."""
    pts = [{"t": f"2020-{i+1:02d}", "regime": g}
           for i, g in enumerate(["Z", "Z", "A", "A"])]
    assert rs.constant_path(pts)[0]["regime"] == "A"
    rev = [{"t": f"2020-{i+1:02d}", "regime": g}
           for i, g in enumerate(["A", "A", "Z", "Z"])]
    assert rs.constant_path(rev)[0]["regime"] == "A"


# ══════════════════════════════════════════════════════════════════════════
# G8 ★순수하다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_transforms_do_not_mutate_their_input():
    """제자리에서 고치면 진짜 팔이 널 팔로 **조용히** 오염된다."""
    before = copy.deepcopy(POINTS)
    rng = np.random.default_rng(0)
    rs.circular_shift(POINTS, 4)
    rs.constant_path(POINTS)
    rs.markov_surrogate(POINTS, rng)
    rs.block_surrogate(POINTS, rng)
    assert POINTS == before


# ══════════════════════════════════════════════════════════════════════════
# G9·G10 널 표본
# ══════════════════════════════════════════════════════════════════════════
def test_all_shifts_are_enumerated_when_they_fit():
    ks, enumerated = rs.shifts_for(len(POINTS), limit=500,
                                   rng=np.random.default_rng(0))
    assert enumerated is True
    assert ks == list(range(1, len(POINTS)))
    assert 0 not in ks


def test_a_tight_limit_samples_and_says_so():
    ks, enumerated = rs.shifts_for(len(POINTS), limit=7,
                                   rng=np.random.default_rng(0))
    assert enumerated is False and len(ks) == 7 and 0 not in ks


def test_a_path_too_short_to_shift_yields_an_empty_null():
    """★널이 없다는 것을 빈 목록으로 말한다★ — 없는 널을 지어내지 않는다."""
    for n in (0, 1):
        ks, enumerated = rs.shifts_for(n, limit=10, rng=np.random.default_rng(0))
        assert ks == [] and enumerated is True


def test_the_same_seed_reproduces_the_surrogate():
    a = rs.markov_surrogate(POINTS, np.random.default_rng(9))
    b = rs.markov_surrogate(POINTS, np.random.default_rng(9))
    c = rs.markov_surrogate(POINTS, np.random.default_rng(10))
    assert _labels(a) == _labels(b)
    assert _labels(a) != _labels(c)


# ══════════════════════════════════════════════════════════════════════════
# G11·G12 ★라우트 차단을 정적으로 강제★
# ══════════════════════════════════════════════════════════════════════════
def _imports_surrogates(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return MODULE in source
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(MODULE in a.name for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and MODULE in node.module:
                return True
            if any(a.name == MODULE for a in node.names):
                return True
    return MODULE in source


def test_the_api_layer_never_imports_the_surrogates():
    """★서로게이트 경로가 프로덕션 결정에 닿는 길을 구조로 없앤다★"""
    bad = [str(p.relative_to(REPO_ROOT))
           for p in (REPO_ROOT / "src" / "api").rglob("*.py")
           if _imports_surrogates(p.read_text(encoding="utf-8"))]
    assert bad == [], f"라우트가 서로게이트를 끌어온다: {bad}"


def test_the_guard_actually_catches_a_violation():
    """★짝★ 항상 통과하는 가드는 가드가 아니다."""
    assert _imports_surrogates(
        "from src.engine.regime_surrogates import circular_shift\n")
    assert _imports_surrogates("import src.engine.regime_surrogates as r\n")
    # ★동적 경로도 잡아야 한다★ AST 만으로는 이것이 빠진다 — 변이 배터리가 정확히
    # 그 구멍을 찾아냈다(문자열 대비를 지워도 위 두 줄은 통과했다).
    assert _imports_surrogates(
        'importlib.import_module("src.engine.regime_surrogates")\n')
    assert not _imports_surrogates("from src.engine.regime_axes import axes\n")


def test_the_guard_actually_scans_files():
    files = list((REPO_ROOT / "src" / "api").rglob("*.py"))
    assert len(files) > 5 and any(p.name == "allocation_routes.py" for p in files)
