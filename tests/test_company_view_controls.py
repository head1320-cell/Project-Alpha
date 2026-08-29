"""기업 뷰 ★음성 통제★ 변환 — 파이프라인이 도는 것과 신호가 있는 것은 다르다 (S6)
==============================================================================
설계: `docs/superpowers/specs/2026-08-28-investment-decision-layer-design.md` §2.3
선행: S4 `company_views()`(`8fb867c`) · S5 배선(`bdd5bca`)

S1~S5 의 증거는 전부 **파이프라인이 돈다**는 것이었다. 이 팔들이 그 다음 질문을
연다 — ★뷰의 내용을 지우거나 뒤섞어도 같은 일이 일어나는가?★

## ★셔플 함수는 프로덕션 옆에 두지 않는다★

`company_views.py` 는 배분 경로에 있다. 셔플러가 그 옆에 있으면 언젠가 한 줄
차이로 새어 들어간다. 그래서 별도 모듈에 두고, ★`src/api/` 가 이 모듈을 import
하지 않는다는 것을 정적으로 강제★한다 — `OrderExecutor` 우회 방지 가드와 같은
장치이고, 그 파일의 관례대로 **가드가 실제 위반을 잡는지 확인하는 짝**도 둔다.
"""

from __future__ import annotations

import ast
import copy
import math
import os
from pathlib import Path

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

import src.engine.company_view_controls as cvc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE = "company_view_controls"


def _v(code: str, direction: int, mag: float, conf: float) -> dict:
    return {"assets": [code], "direction": direction, "magnitude_pct": mag,
            "confidence": conf, "source": "company_valuation",
            "label": f"{code} 밸류에이션 갭", "z": mag * direction / 10.0}


VIEWS = [_v("a", +1, 10.0, 20.0), _v("b", -1, 4.0, 45.0), _v("c", +1, 7.0, 50.0)]


def _triples(views: list[dict]) -> list[tuple]:
    return sorted((v["direction"], v["magnitude_pct"], v["confidence"]) for v in views)


# ══════════════════════════════════════════════════════════════════════════
# Z1·Z2 neutral — ★내용을 지우되 구조는 남긴다★
# ══════════════════════════════════════════════════════════════════════════
def test_neutralize_keeps_the_assets_and_removes_the_cross_section(_=None):
    out = cvc.neutralize(VIEWS)
    assert [v["assets"] for v in out] == [v["assets"] for v in VIEWS]
    assert len({v["magnitude_pct"] for v in out}) == 1
    assert {v["direction"] for v in out} == {cvc.NEUTRAL_DIRECTION}
    assert all(v["arm"] == cvc.ARM_NEUTRAL for v in out)


def test_neutralize_is_not_the_identity():
    """★짝★ 원래 크기를 그대로 두면 통제가 아니라 복사다."""
    out = cvc.neutralize(VIEWS)
    assert [v["magnitude_pct"] for v in out] != [v["magnitude_pct"] for v in VIEWS]
    assert [v["direction"] for v in out] != [v["direction"] for v in VIEWS]


# ══════════════════════════════════════════════════════════════════════════
# Z3·Z4 shuffle — ★치환이지 재생성이 아니다★
# ══════════════════════════════════════════════════════════════════════════
def test_shuffle_is_a_permutation_of_the_same_content():
    """다중집합이 보존되어야 널이 '같은 내용, 다른 배치' 를 뜻한다."""
    out = cvc.shuffle_views(VIEWS, (2, 0, 1))
    assert [v["assets"] for v in out] == [v["assets"] for v in VIEWS]
    assert _triples(out) == _triples(VIEWS)


def test_a_non_identity_permutation_actually_changes_the_pairing():
    """★짝★ 입력을 그대로 돌려주는 셔플러는 통제가 아니다."""
    out = cvc.shuffle_views(VIEWS, (2, 0, 1))
    assert [v["magnitude_pct"] for v in out] != [v["magnitude_pct"] for v in VIEWS]
    assert all(v["arm"] == cvc.ARM_SHUFFLED for v in out)


def test_the_identity_permutation_is_refused():
    """★항등을 널 표본으로 세면 널이 진짜 팔로 오염된다★"""
    with pytest.raises(ValueError):
        cvc.shuffle_views(VIEWS, (0, 1, 2))


# ══════════════════════════════════════════════════════════════════════════
# Z5 evidence-stripped — ★신뢰도만★
# ══════════════════════════════════════════════════════════════════════════
def test_stripping_evidence_touches_only_the_confidence():
    out = cvc.strip_confidence(VIEWS)
    assert {v["confidence"] for v in out} == {cvc.DEFAULT_CONFIDENCE}
    assert [v["magnitude_pct"] for v in out] == [v["magnitude_pct"] for v in VIEWS]
    assert [v["direction"] for v in out] == [v["direction"] for v in VIEWS]


def test_stripping_is_a_no_op_when_the_confidences_are_already_uniform():
    """★S4 가 예고한 상태★ mock 에서는 신뢰도가 전부 포화해 같다 — 그때 이 팔은
    `company-on` 과 **동일하다**. 하네스가 그 사실을 신고해야 한다(보고서 테스트)."""
    uniform = [_v("a", +1, 10.0, cvc.DEFAULT_CONFIDENCE),
               _v("b", -1, 4.0, cvc.DEFAULT_CONFIDENCE)]
    assert cvc.is_inert(uniform, cvc.strip_confidence(uniform)) is True
    assert cvc.is_inert(VIEWS, cvc.strip_confidence(VIEWS)) is False


# ══════════════════════════════════════════════════════════════════════════
# Z6 ★순수하다★
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("fn", ["neutralize", "strip_confidence"])
def test_the_transforms_do_not_mutate_their_input(fn):
    """제자리에서 고치면 `company-on` 팔이 통제 팔로 오염된다 — 조용히."""
    before = copy.deepcopy(VIEWS)
    getattr(cvc, fn)(VIEWS)
    assert VIEWS == before


def test_shuffle_does_not_mutate_its_input():
    before = copy.deepcopy(VIEWS)
    cvc.shuffle_views(VIEWS, (1, 2, 0))
    assert VIEWS == before


# ══════════════════════════════════════════════════════════════════════════
# Z7·Z8 널 표본 — ★작은 유니버스에서 가짜 해상도를 만들지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_small_universe_is_enumerated_exhaustively():
    """뷰가 3개면 비항등 치환은 **5개뿐**이다. 200번 뽑아 '분포' 라 부르면 안 된다."""
    perms, enumerated = cvc.permutations_for(3, limit=200,
                                             rng=np.random.default_rng(0))
    assert enumerated is True
    assert len(perms) == math.factorial(3) - 1
    assert len(set(perms)) == len(perms)
    assert (0, 1, 2) not in perms


def test_a_large_universe_is_sampled_and_says_so():
    perms, enumerated = cvc.permutations_for(8, limit=50,
                                             rng=np.random.default_rng(0))
    assert enumerated is False
    assert len(perms) == 50
    assert (tuple(range(8))) not in perms


def test_one_view_cannot_be_shuffled_at_all():
    """★셔플할 수 없다는 것은 널이 없다는 뜻이다★ 빈 목록으로 정직하게 말한다."""
    for k in (0, 1):
        perms, enumerated = cvc.permutations_for(k, limit=10,
                                                 rng=np.random.default_rng(0))
        assert perms == [] and enumerated is True


def test_the_same_seed_gives_the_same_null():
    a, _ = cvc.permutations_for(8, limit=20, rng=np.random.default_rng(5))
    b, _ = cvc.permutations_for(8, limit=20, rng=np.random.default_rng(5))
    c, _ = cvc.permutations_for(8, limit=20, rng=np.random.default_rng(6))
    assert a == b and a != c


# ══════════════════════════════════════════════════════════════════════════
# arm_views 디스패치
# ══════════════════════════════════════════════════════════════════════════
def test_the_off_arm_is_no_views_at_all():
    assert cvc.arm_views(VIEWS, cvc.ARM_OFF) is None


def test_the_on_arm_is_the_views_themselves():
    out = cvc.arm_views(VIEWS, cvc.ARM_ON)
    assert _triples(out) == _triples(VIEWS)
    assert out is not VIEWS                       # 복사본이어야 오염되지 않는다


def test_the_shuffled_arm_demands_a_permutation():
    """치환 없이 셔플 팔을 요구하면 조용히 `on` 을 돌려주면 안 된다."""
    with pytest.raises(ValueError):
        cvc.arm_views(VIEWS, cvc.ARM_SHUFFLED)


def test_an_unknown_arm_is_refused():
    with pytest.raises(ValueError):
        cvc.arm_views(VIEWS, "company-magic")


# ══════════════════════════════════════════════════════════════════════════
# Z9·Z10 ★라우트 차단을 정적으로 강제★
# ══════════════════════════════════════════════════════════════════════════
def _imports_controls(source: str) -> bool:
    """이 소스가 통제 모듈을 끌어오는가 — AST + 문자열 두 겹."""
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
    # `importlib.import_module("...company_view_controls")` 같은 동적 경로도 잡는다.
    return MODULE in source


def test_the_api_layer_never_imports_the_controls():
    """★셔플된 뷰가 거래 판단 경로에 닿는 길을 구조로 없앤다★

    `OrderExecutor` 를 `trading_engine.py` 밖에서 못 만들게 하는 가드와 같은 장치다.
    """
    offenders = [str(p.relative_to(REPO_ROOT))
                 for p in (REPO_ROOT / "src" / "api").rglob("*.py")
                 if _imports_controls(p.read_text(encoding="utf-8"))]
    assert offenders == [], f"라우트가 통제 모듈을 끌어온다: {offenders}"


def test_the_guard_actually_catches_a_violation():
    """★짝★ 항상 통과하는 가드는 가드가 아니다."""
    assert _imports_controls(
        "from src.engine.company_view_controls import shuffle_views\n")
    assert _imports_controls("import src.engine.company_view_controls as c\n")
    assert _imports_controls(
        'importlib.import_module("src.engine.company_view_controls")\n')
    assert not _imports_controls("from src.engine.company_views import company_views\n")


def test_the_guard_actually_scans_files():
    """★짝의 짝★ 대상이 비어 있으면 위 테스트는 아무것도 검사하지 않는다."""
    files = list((REPO_ROOT / "src" / "api").rglob("*.py"))
    assert len(files) > 5, files
    assert any("allocation_routes.py" == p.name for p in files)
