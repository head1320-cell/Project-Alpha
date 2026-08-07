"""regime_ensemble — 세 도구를 나란히 돌리고, 못 하는 것은 못 한다고 말하는가 (A7).

★이 테스트가 지키는 것★
1. 세 방법을 **합치지 않는다** — 각각의 확률이 따로 나오고 argmax 도 따로다.
2. 표본 부족·미수렴·라이브러리 부재는 `available: False` + **사유** 다.
   0 이나 균등분포로 채우면 "국면을 모르겠다" 가 "네 국면이 똑같이 가능하다" 로
   둔갑한다 — 이 저장소가 반복해서 고쳐 온 결함 유형이다.
3. 전이행렬은 확률행렬이다(행 합 = 1).
"""

from __future__ import annotations

import math
import random

import pytest

from src.engine.regime_ensemble import MIN_OBS, REGIMES, regime_ensemble


class _S:
    """regime_axes 가 기대하는 최소 인터페이스 — `.values` 만 본다."""

    def __init__(self, values):
        self.values = values


def _series(n: int, seed: int = 7) -> dict:
    """뚜렷한 순환이 있는 합성 매크로 계열 (확장/수축이 번갈아 온다)."""
    random.seed(seed)
    g, c = [], []
    for i in range(n):
        cyc = 3.0 * math.sin(i / 16.0)
        g.append(100 * (1 + (0.02 * i + cyc) / 100))
        c.append(100 * (1 + (0.015 * i - cyc * 0.6) / 100))
    return {
        "KR_LEADING_CYCLE": _S([x / 100 for x in g]),
        "KR_IP": _S(g),
        "KOSPI": _S(g),
        "KR_CPI": _S(c),
        "T10YIE": _S([2 + 0.4 * math.sin(i / 11.0) for i in range(n)]),
    }


def test_three_tools_run_side_by_side():
    r = regime_ensemble(_series(140), "kr", months=90)
    assert set(r["tools"]) == {"axis", "markov", "cluster"}
    for name, tool in r["tools"].items():
        assert tool["available"] is True, f"{name}: {tool.get('reason')}"
        # 확률은 4국면 전부에 대해 나오고 합이 1이다.
        assert set(tool["probs"]) == set(REGIMES), name
        assert abs(sum(tool["probs"].values()) - 1.0) < 1e-3, name
        assert tool["argmax"] in REGIMES


def test_results_are_not_merged_into_one_number():
    """★평균내지 않는다★ — 각 도구의 확률이 개별로 남아 있어야 한다.

    합의된 단일 확률 필드가 생기면 어느 모형이 무엇을 말했는지 사라진다.
    """
    r = regime_ensemble(_series(140), "kr", months=90)
    assert "probs" not in r, "앙상블 최상위에 합쳐진 확률이 있으면 안 된다"
    assert "consensus" not in r
    # agreement 는 '같은가' 만 말하고 값을 만들지 않는다.
    assert set(r["agreement"]) == {"unanimous", "picks", "note"}


def test_transition_matrix_is_a_probability_matrix():
    r = regime_ensemble(_series(140), "kr", months=90)
    mk = r["tools"]["markov"]
    assert mk["available"] is True, mk.get("reason")
    tm = mk["detail"]["transition"]
    assert len(tm) == 2 and all(len(row) == 2 for row in tm)
    for col in range(2):
        # statsmodels 의 regime_transition 은 P[j][i] = i→j 라 **열** 합이 1이다.
        assert abs(sum(tm[row][col] for row in range(2)) - 1.0) < 1e-3, tm
    assert 0.0 <= mk["detail"]["persistence"] <= 1.0


def test_named_transitions_match_the_matrix_and_do_not_flip_direction():
    """★방향이 헷갈릴 수 없는 이름이 실제로 그 방향인가★

    `regime_transition` 은 **열이 출발**(P[j][i] = i→j)인데, 엔진 주석이 한때 반대로
    적혀 있었고 그걸 읽은 프론트가 전이 그래프의 화살표를 뒤집어 그렸다. 대각(지속성)은
    어느 규약에서든 같은 값이라 **화면으로는 티가 나지 않는다** — 그래서 테스트가
    필요하다. 여기서 잡지 못하면 "확장에서 수축으로 갈 확률" 자리에 그 반대가 찍힌다.
    """
    d = regime_ensemble(_series(140), "kr", months=90)["tools"]["markov"]
    assert d["available"] is True, d.get("reason")
    det = d["detail"]
    tm, e = det["transition"], det["expansion_state"]
    c = 1 - e

    # 이름 있는 값이 행렬의 **올바른 칸**에서 왔는가 (뒤집으면 여기서 깨진다).
    assert det["p_exp_to_con"] == pytest.approx(tm[c][e], abs=1e-3)
    assert det["p_con_to_exp"] == pytest.approx(tm[e][c], abs=1e-3)

    # 2상태에서 출발 확률의 합은 1 — 지속성과 이탈확률은 서로의 여집합이다.
    assert det["persistence"] + det["p_exp_to_con"] == pytest.approx(1.0, abs=1e-3)


@pytest.mark.parametrize("months", [6, MIN_OBS - 1])
def test_short_sample_is_unavailable_with_a_reason_not_a_uniform_prior(months):
    """★표본이 모자라면 균등분포를 지어내지 않는다★

    0.25씩 넷으로 채우면 화면에는 "네 국면이 똑같이 가능" 으로 읽힌다 —
    실제로는 아무것도 추정하지 못한 것이다.
    """
    r = regime_ensemble(_series(months + 4), "kr", months=months)
    for name in ("markov", "cluster"):
        tool = r["tools"][name]
        assert tool["available"] is False, name
        assert "probs" not in tool, f"{name}: 미가용인데 확률을 만들었다"
        assert str(months) in tool["reason"] or "표본" in tool["reason"], tool["reason"]


def test_no_axis_indicators_is_unavailable_not_zero():
    """축을 만들 지표가 없으면 축-확률도 미가용이다 (0,0 → Goldilocks 로 찍지 않는다)."""
    r = regime_ensemble({}, "kr", months=60)
    assert r["tools"]["axis"]["available"] is False
    assert "지표" in r["tools"]["axis"]["reason"]


def test_agreement_reports_disagreement_when_tools_differ():
    """세 도구가 갈리면 `unanimous` 가 False 여야 한다 — 갈린 사실이 정보다."""
    r = regime_ensemble(_series(140), "kr", months=90)
    picks = r["agreement"]["picks"]
    assert r["agreement"]["unanimous"] == (len(set(picks.values())) == 1)
