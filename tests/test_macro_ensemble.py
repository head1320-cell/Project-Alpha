"""스튜디오 앙상블 — **불일치를 일급으로** (P4-M3).

왜 이 파일이 있는가
------------------------------------------------------------------------------
다섯 스튜디오는 각자 답하고 끝난다. 이들을 하나의 매크로 상태로 묶되, ★합의도가
아니라 불일치를 일급으로★ 낸다 — 모델이 서로 다르게 말할 때가 가장 정보가 많은
순간이고, 평균으로 뭉개면 그 정보가 사라진다.

A8 이 세 국면 도구(축·Markov·GMM)를 **하나로 평균 내지 않은** 것과 같은 원칙이다.
그때 적은 이유가 그대로 적용된다: "하나로 평균 내면 어느 모형이 무슨 말을 했는지
사라진다."

★미가용 도구는 합의에 세지 않는다★ 5개 중 4개가 미가용이고 1개만 답했을 때
"만장일치" 라고 말하면 그건 거짓이다. 답한 개수를 함께 내고, 1개면 합의가 아니라고
적는다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.macro_models.ensemble import (  # noqa: E402
    combine_studio_views,
    disagreement,
)


def _views(**kw: str) -> dict[str, dict]:
    """도구 이름 → 결과. 값이 `None` 이면 미가용으로 만든다."""
    out = {}
    for name, verdict in kw.items():
        if verdict == "NA":
            out[name] = {"available": False, "reason": f"{name}: 표본 부족"}
        else:
            out[name] = {"available": True, "verdict": verdict}
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 1. ★불일치가 숫자로 나온다 — 평균으로 지워지지 않는다★
# ─────────────────────────────────────────────────────────────────────────────
def test_full_agreement_scores_zero_disagreement():
    d = disagreement(["Goldilocks"] * 4)
    assert d["score"] == 0.0
    assert d["unique"] == 1


def test_a_split_verdict_scores_clearly_above_zero_and_names_both_sides():
    """★짝★ 없으면 항상 0 을 돌려줘도 위 테스트가 통과한다.

    그리고 점수만 내면 "무엇과 무엇이 갈렸는지" 를 화면이 말할 수 없다.

    ★임계값을 처음엔 0.9 로 적었는데 그건 근거 없는 숫자였다★
    척도는 관측 가능한 최대(log n)로 정규화한 엔트로피다. 도구 4개가 2:2 로 갈리면
    log2/log4 = 0.5 이고, 4갈래로 흩어져야 1.0 이다. 2:2 를 "최대 불일치" 로 보는
    것이 오히려 틀렸다 — 1:1:1:1 이 더 흩어진 상태이고, 그 순서는 아래 단조성
    테스트가 붙들고 있다. 여기서는 **0 이 아니라는 것**만 재는 것이 맞다.
    """
    d = disagreement(["Goldilocks", "Goldilocks", "Stagflation", "Stagflation"])
    assert d["score"] > 0.4, d
    assert set(d["counts"]) == {"Goldilocks", "Stagflation"}
    assert d["unique"] == 2


def test_two_tools_splitting_evenly_is_maximal_for_that_sample():
    """짝 — 표본이 2개면 1:1 이 그 표본에서 가능한 최대 불일치다.

    정규화가 "얼마나 흩어질 수 있었는가" 대비로 읽힌다는 것을 고정한다.
    """
    assert disagreement(["A", "B"])["score"] == 1.0


def test_disagreement_rises_monotonically_as_views_scatter():
    """2갈래보다 4갈래가 더 불일치다 — 순서가 뒤집히면 지표가 뜻을 잃는다."""
    two = disagreement(["A", "A", "B", "B"])["score"]
    four = disagreement(["A", "B", "C", "D"])["score"]
    assert four > two > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. ★미가용 도구를 합의로 세지 않는다★
# ─────────────────────────────────────────────────────────────────────────────
def test_unavailable_tools_are_excluded_but_named_with_their_reasons():
    out = combine_studio_views(_views(
        axis="Goldilocks", markov="Goldilocks", cluster="NA", tail="NA"))
    assert out["n_available"] == 2
    assert set(out["unavailable"]) == {"cluster", "tail"}
    for name in ("cluster", "tail"):
        assert out["reasons"][name], f"{name}: 미가용 사유가 없다"


def test_a_single_available_tool_is_not_called_a_consensus():
    """★5개 중 1개만 답했는데 "만장일치" 라고 하면 거짓이다★"""
    out = combine_studio_views(_views(
        axis="Goldilocks", markov="NA", cluster="NA", tail="NA"))
    assert out["n_available"] == 1
    assert out["consensus"] is False
    assert out["note"], "왜 합의가 아닌지 안 적혀 있다"


def test_agreement_among_several_tools_is_a_consensus():
    """짝 — 합의가 아예 성립하지 않으면 지표가 무의미하다."""
    out = combine_studio_views(_views(
        axis="Goldilocks", markov="Goldilocks", cluster="Goldilocks"))
    assert out["n_available"] == 3
    assert out["consensus"] is True
    assert out["disagreement"]["score"] == 0.0


def test_nothing_available_yields_no_verdict_and_a_reason():
    """★전부 미가용이면 결론을 지어내지 않는다★"""
    out = combine_studio_views(_views(axis="NA", markov="NA"))
    assert out["n_available"] == 0
    assert out["verdict"] is None
    assert out["consensus"] is False
    assert out["note"]


# ─────────────────────────────────────────────────────────────────────────────
# 3. 결합해도 개별 판정을 숨기지 않는다
# ─────────────────────────────────────────────────────────────────────────────
def test_the_combined_result_still_carries_every_individual_verdict():
    """★평균 옆에 원본이 남아야 한다★ 남지 않으면 되짚을 수 없다."""
    out = combine_studio_views(_views(
        axis="Goldilocks", markov="Stagflation", cluster="Goldilocks"))
    assert out["per_tool"] == {"axis": "Goldilocks", "markov": "Stagflation",
                               "cluster": "Goldilocks"}


def test_the_majority_verdict_is_reported_but_flagged_when_contested():
    """다수결을 내되 **갈렸다는 사실을 함께** 낸다 — 다수결만 보면 2:1 이 만장일치처럼 읽힌다."""
    out = combine_studio_views(_views(
        axis="Goldilocks", markov="Stagflation", cluster="Goldilocks"))
    assert out["verdict"] == "Goldilocks"
    assert out["consensus"] is False
    assert out["disagreement"]["score"] > 0.0


def test_a_tie_does_not_silently_pick_one_side():
    """★동수는 결론이 아니다★ 임의로 하나를 고르면 그건 지어낸 결론이다.

    ★변이 프로브가 이 테스트의 구멍을 잡았다★
    처음엔 `tie`·`consensus`·`note` 만 단언했는데, `verdict = top[0][0]` 로 되돌려도
    **초록으로 남았다** — 정작 "고르지 않는다" 의 대상인 판정 자체를 안 봤기 때문이다.
    지키려던 것과 재던 것이 달랐던, 이 저장소가 반복해 값을 치른 형태다.
    """
    out = combine_studio_views(_views(axis="Goldilocks", markov="Stagflation"))
    assert out["verdict"] is None, "동수인데 한쪽을 골랐다"
    assert out["consensus"] is False
    assert out["tie"] is True
    assert out["note"]
