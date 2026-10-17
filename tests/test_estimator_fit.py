"""AH1 — 추정이 **어느 창·어느 빈티지** 위에 섰나 (순수 계층).

★두 축을 섞지 않는다★ — 실측이 그것을 요구했다:

  · `regime_axes.zscore_at` 은 **창은 후행(깨끗)인데 값이 현재 빈티지**다.
  · `reverse_stress.factor_covariance:74` 는 **창은 as-of 인데 표준화가 전체표본**이다.

하나로 뭉치면 그 구분이 사라진다. Z(`kind ⟂ data_real`)·AA(`trigger ⟂ reason`)·
AG(`signal_lag ⟂ fill_type`)와 같은 규율이다.

★`trailing` 을 `bounded` 와 가르는 이유★ — 라이브 배분에서 "최근 252일" 은 **옳다**.
같은 코드가 과거 시점 재현에 쓰이면 **틀린다**. 하나로 뭉치면 둘 중 어느 쪽인지
영원히 못 가른다.
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from src.domain.estimator_fit import (
    VINTAGE_AS_OF,
    VINTAGE_CURRENT,
    VINTAGE_UNMEASURED,
    WINDOW_BOUNDED,
    WINDOW_FULL_SAMPLE,
    WINDOW_TRAILING,
    WINDOW_UNMEASURED,
    EstimatorFit,
    fit_label,
    fit_state,
)
from src.engine.run_evidence import AXIS_DEGRADED, AXIS_OK, AXIS_UNKNOWN

_MODULE = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "domain" / "estimator_fit.py")


def _f(window, vintage, **kw) -> EstimatorFit:
    return EstimatorFit(site=kw.pop("site", "t"), window=window, vintage=vintage, **kw)


# ── ★핵심★ 잘린 창 + 그때 값 = 통과 ───────────────────────────────────────

def test_a_bounded_window_on_as_of_values_is_ok():
    assert fit_state(WINDOW_BOUNDED, VINTAGE_AS_OF) == AXIS_OK


def test_a_full_sample_window_is_degraded():
    assert fit_state(WINDOW_FULL_SAMPLE, VINTAGE_AS_OF) == AXIS_DEGRADED


# ── ★두 축★ 창이 깨끗해도 빈티지가 현재면 통과가 아니다 ──────────────────

def test_a_clean_window_on_current_vintage_is_not_ok():
    """L2 — `regime_axes.zscore_at` 이 정확히 이 모양이다."""
    assert fit_state(WINDOW_BOUNDED, VINTAGE_CURRENT) == AXIS_DEGRADED


def test_the_vintage_actually_changes_the_verdict():
    """★짝★ 같은 창에서 빈티지만 바꾸면 판정이 **달라진다**(창만 보는 구현 배제)."""
    assert (fit_state(WINDOW_BOUNDED, VINTAGE_AS_OF)
            != fit_state(WINDOW_BOUNDED, VINTAGE_CURRENT))


def test_the_window_actually_changes_the_verdict():
    """★짝★ 같은 빈티지에서 창만 바꿔도 판정이 달라진다(빈티지만 보는 구현 배제)."""
    assert (fit_state(WINDOW_BOUNDED, VINTAGE_AS_OF)
            != fit_state(WINDOW_FULL_SAMPLE, VINTAGE_AS_OF))


# ── ★미상★ 하나라도 못 쟀으면 None ────────────────────────────────────────

@pytest.mark.parametrize("window,vintage", [
    (WINDOW_UNMEASURED, VINTAGE_AS_OF),
    (WINDOW_BOUNDED, VINTAGE_UNMEASURED),
    (WINDOW_UNMEASURED, VINTAGE_UNMEASURED),
    (None, VINTAGE_AS_OF),
    (WINDOW_BOUNDED, None),
])
def test_an_unmeasured_side_makes_the_state_unknown(window, vintage):
    """★미상을 ok 로도 degraded 로도 접지 않는다★"""
    assert fit_state(window, vintage) == AXIS_UNKNOWN


def test_unknown_is_not_the_only_answer():
    """★짝★ 언제나 `unknown` 을 내는 구현을 배제한다."""
    seen = {fit_state(w, v) for w, v in (
        (WINDOW_BOUNDED, VINTAGE_AS_OF),
        (WINDOW_FULL_SAMPLE, VINTAGE_AS_OF),
        (WINDOW_UNMEASURED, VINTAGE_AS_OF))}
    assert seen == {AXIS_OK, AXIS_DEGRADED, AXIS_UNKNOWN}


# ── ★trailing 은 bounded 가 아니다★ ──────────────────────────────────────

def test_trailing_is_a_state_of_its_own():
    """라이브에선 옳고 과거 재현엔 틀린 창 — 둘을 같은 칸에 넣으면 못 가른다."""
    assert WINDOW_TRAILING not in (WINDOW_BOUNDED, WINDOW_FULL_SAMPLE, WINDOW_UNMEASURED)
    assert fit_state(WINDOW_TRAILING, VINTAGE_AS_OF) != fit_state(WINDOW_BOUNDED, VINTAGE_AS_OF)


def test_trailing_is_not_silently_a_pass():
    assert fit_state(WINDOW_TRAILING, VINTAGE_AS_OF) != AXIS_OK


# ── 라벨 ──────────────────────────────────────────────────────────────────

def test_the_label_carries_both_axes_and_a_state():
    got = fit_label(_f(WINDOW_BOUNDED, VINTAGE_AS_OF, consumer="allocation"))
    assert got["state"] == AXIS_OK
    assert got["window"] == WINDOW_BOUNDED
    assert got["vintage"] == VINTAGE_AS_OF
    assert got["consumer"] == "allocation"
    assert got["reason"] is None


def test_a_non_ok_label_always_carries_a_reason():
    """★사유 없는 열화는 금지★ (CLAUDE.md §4)"""
    for window, vintage in ((WINDOW_FULL_SAMPLE, VINTAGE_AS_OF),
                            (WINDOW_BOUNDED, VINTAGE_CURRENT),
                            (WINDOW_TRAILING, VINTAGE_AS_OF),
                            (WINDOW_UNMEASURED, VINTAGE_UNMEASURED)):
        got = fit_label(_f(window, vintage))
        assert got["state"] != AXIS_OK
        assert got["reason"], f"{window}/{vintage} 에 사유가 없다"


def test_the_reason_names_which_axis_is_at_fault():
    """창이 문제인지 빈티지가 문제인지 사유가 말한다 — 안 그러면 고칠 곳을 모른다."""
    assert "빈티지" in fit_label(_f(WINDOW_BOUNDED, VINTAGE_CURRENT))["reason"]
    assert "전체표본" in fit_label(_f(WINDOW_FULL_SAMPLE, VINTAGE_AS_OF))["reason"]


def test_an_empty_fit_is_unmeasured_not_ok():
    got = fit_label(EstimatorFit())
    assert got["state"] == AXIS_UNKNOWN
    assert got["window"] is None and got["vintage"] is None
    assert got["reason"]


# ── 타입·순수성 ───────────────────────────────────────────────────────────

def test_the_fit_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _f(WINDOW_BOUNDED, VINTAGE_AS_OF).window = WINDOW_FULL_SAMPLE  # type: ignore[misc]


def test_the_domain_module_stays_pure():
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for name in imported:
        for bad in ("sqlalchemy", "fastapi", "requests", "pandas", "numpy",
                    "sklearn", "statsmodels", "src.database", "src.data", "src.api"):
            assert not name.startswith(bad), f"순수 계층이 {name} 을 import 한다"


# ── ★어휘를 두 벌 만들지 않는다★ ─────────────────────────────────────────

def test_the_state_vocabulary_is_the_same_as_run_evidence():
    """순수 계층이라 `src.engine` 을 import 하지 않는다 — 대신 **값이 같음을 못 박는다**.

    ★두 벌이 되면 한쪽만 고쳐도 타입 에러가 안 나고, 화면에 따라 다른 판정이 나온다★
    — `run_evidence.rollup` 의 독스트링이 적어 둔 바로 그 사건이다.
    """
    from src.domain import estimator_fit as ef
    assert (ef.STATE_OK, ef.STATE_DEGRADED, ef.STATE_UNKNOWN) == (
        AXIS_OK, AXIS_DEGRADED, AXIS_UNKNOWN)


def test_the_state_tuples_match_the_constants():
    """★목록이 상수와 어긋나면 전수 검사가 엉뚱한 것을 훑는다★"""
    from src.domain.estimator_fit import VINTAGE_STATES, WINDOW_STATES
    assert set(WINDOW_STATES) == {WINDOW_BOUNDED, WINDOW_TRAILING,
                                  WINDOW_FULL_SAMPLE, WINDOW_UNMEASURED}
    assert set(VINTAGE_STATES) == {VINTAGE_AS_OF, VINTAGE_CURRENT, VINTAGE_UNMEASURED}
    assert len(set(WINDOW_STATES)) == len(WINDOW_STATES), "중복된 창 상태"


@pytest.mark.parametrize("window", [WINDOW_BOUNDED, WINDOW_TRAILING,
                                    WINDOW_FULL_SAMPLE, WINDOW_UNMEASURED])
@pytest.mark.parametrize("vintage", [VINTAGE_AS_OF, VINTAGE_CURRENT, VINTAGE_UNMEASURED])
def test_every_combination_yields_a_known_state(window, vintage):
    """★전수★ 12조합 중 어느 것도 판정 밖으로 떨어지지 않는다."""
    got = fit_label(_f(window, vintage))
    assert got["state"] in (AXIS_OK, AXIS_DEGRADED, AXIS_UNKNOWN)
    if got["state"] != AXIS_OK:
        assert got["reason"], f"{window}/{vintage} 에 사유가 없다"
    else:
        assert got["reason"] is None
