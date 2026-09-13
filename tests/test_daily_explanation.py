"""하루를 ★설명하되 설명하지 못한 몫을 숨기지 않는다★ (AB1)

설계: `docs/plans` AB · 로드맵 P3 · 도메인 아키텍처 §5

## 완료 판정(로드맵)

> *"하루치 설명이 한국어 한 문단으로 나오고, 같은 입력에 **항상 같은 문장**이며,
>   설명하지 못한 몫이 `residual` 과 `missing_drivers` 로 **보인다**."*

## ★결정론이 무엇을 뜻하나★

같은 함수에 같은 객체를 넣으면 같은 값이 나오는 것은 당연하다 — 그것을 100번 재는
테스트는 아무것도 막지 못한다. 진짜 위험은 **상류의 딕트 삽입 순서**가 문장 순서로
새어 나오는 것이다. 그래서 이 파일은 **같은 사실을 다른 순서로 넣어** 같은 문장이
나오는지 본다.

## ★드라이버 집합이 둘인 이유★

전략 수준 5효과 분해와 보유 수준 분해는 **다른 질문에 답한다**. 하나로 뭉개면
"배분 효과" 와 "가격" 이 같은 목록에 놓여 합이 의미를 잃는다 — Z 에서 `kind` 와
`data_real` 을 가른 것과 같은 규율이다.
"""
from __future__ import annotations

import pytest

from src.domain.daily_explanation import (
    DRIVER_DIVIDEND,
    DRIVER_FEE,
    DRIVER_FX,
    DRIVER_LABELS,
    DRIVER_PRICE,
    DRIVER_REBALANCE,
    DRIVER_SET_HOLDING,
    DRIVER_SET_STRATEGY,
    DRIVER_SETS,
    HOLDING_DRIVERS,
    RESIDUAL_INTERACTION,
    RESIDUAL_UNEXPLAINED,
    STRATEGY_DRIVERS,
    UNMEASURABLE_DRIVERS,
    DailyExplanation,
    summarize_ko,
)


def _exp(**kw) -> DailyExplanation:
    base = dict(
        as_of="2026-09-11", scope="run", scope_id="7",
        driver_set=DRIVER_SET_STRATEGY,
        total_change_pct=0.41,
        drivers={"allocation_effect": 0.31, "cost_effect": -0.08,
                 "selection_effect": 0.16, "macro_effect": None,
                 "netting_effect": 0.0},
        missing_drivers={"macro_effect": "이 실행에서 관측되지 않았습니다"},
        residual_pct=0.02, residual_kind=RESIDUAL_UNEXPLAINED,
        residual_reason="macro_effect 의 커버리지가 불완전합니다",
        price_basis=None,
    )
    base.update(kw)
    return DailyExplanation(**base)


# ═══════════════════════════════════════════════════════════════════════════
# ⑭ 두 드라이버 집합은 겹치지 않는다
# ═══════════════════════════════════════════════════════════════════════════
def test_the_two_driver_sets_share_no_name():
    """★겹치면 합이 의미를 잃는다★ — 전략 분해와 보유 분해는 다른 질문이다."""
    overlap = set(STRATEGY_DRIVERS) & set(HOLDING_DRIVERS)
    assert not overlap, f"두 집합이 같은 이름을 씁니다: {sorted(overlap)}"
    assert set(DRIVER_SETS) == {DRIVER_SET_STRATEGY, DRIVER_SET_HOLDING}


def test_strategy_drivers_match_the_producer_verbatim():
    """★`attribution_decomposer` 가 단일 출처다★ — 손으로 옮겨 적으면 낡는다."""
    from src.engine.attribution_decomposer import EFFECT_COLUMNS
    assert tuple(STRATEGY_DRIVERS) == tuple(EFFECT_COLUMNS)


def test_every_driver_has_a_korean_label():
    """★이름 없는 드라이버는 문장에서 KeyError 가 된다★"""
    for name in (*STRATEGY_DRIVERS, *HOLDING_DRIVERS):
        assert DRIVER_LABELS.get(name), name


# ═══════════════════════════════════════════════════════════════════════════
# ①② 결정론 — ★삽입 순서가 문장으로 새지 않는다★
# ═══════════════════════════════════════════════════════════════════════════
def test_insertion_order_does_not_leak_into_the_sentence():
    """같은 사실을 다른 순서로 넣으면 **같은 문장**이 나와야 한다.

    ★100번 부르는 테스트는 이것을 못 잡는다★ — 같은 객체를 다시 넣을 뿐이다.
    """
    facts = [("allocation_effect", 0.31), ("cost_effect", -0.08),
             ("selection_effect", 0.16), ("netting_effect", 0.0)]
    a = summarize_ko(_exp(drivers={**dict(facts), "macro_effect": None}))
    b = summarize_ko(_exp(drivers={**dict(reversed(facts)), "macro_effect": None}))
    assert a == b, f"삽입 순서가 문장을 바꿨습니다\nA: {a}\nB: {b}"


def test_equal_magnitudes_break_ties_by_name():
    """② ★동률이면 이름 사전순★ — 불안정하면 같은 입력에 다른 문장이 나온다."""
    one = summarize_ko(_exp(drivers={"allocation_effect": 0.20,
                                     "cost_effect": -0.20,
                                     "selection_effect": None,
                                     "macro_effect": None,
                                     "netting_effect": None},
                            missing_drivers={"selection_effect": "미관측",
                                             "macro_effect": "미관측",
                                             "netting_effect": "미관측"}))
    two = summarize_ko(_exp(drivers={"cost_effect": -0.20,
                                     "allocation_effect": 0.20,
                                     "macro_effect": None,
                                     "netting_effect": None,
                                     "selection_effect": None},
                            missing_drivers={"macro_effect": "미관측",
                                             "netting_effect": "미관측",
                                             "selection_effect": "미관측"}))
    assert one == two
    # 동률이면 `allocation_effect` 가 `cost_effect` 보다 먼저다(사전순).
    assert one.index("배분 효과") < one.index("거래 비용")


def test_the_same_input_gives_the_same_bytes():
    """①  같은 입력 → **바이트 단위로** 같은 문자열."""
    outs = {summarize_ko(_exp()) for _ in range(50)}
    assert len(outs) == 1


# ═══════════════════════════════════════════════════════════════════════════
# ③④⑤ 잔차 — ★문장에서 빼지 않는다★
# ═══════════════════════════════════════════════════════════════════════════
def test_the_residual_is_always_in_the_sentence():
    """③ 0 이어도 생략하지 않는다 — 빠지면 "설명이 완전하다" 로 읽힌다."""
    for kw in ({}, {"residual_pct": 0.0, "residual_kind": RESIDUAL_INTERACTION,
                    "residual_reason": None},
               {"residual_pct": None, "residual_kind": None,
                "residual_reason": "전체 변동을 알 수 없습니다"}):
        text = summarize_ko(_exp(**kw))
        assert ("잔차" in text or "설명하지 못한" in text or "상호작용" in text), text


def test_interaction_and_unexplained_read_differently():
    """④ ★커버리지가 완전할 때만 "복리 상호작용" 이라 부른다★"""
    inter = summarize_ko(_exp(residual_kind=RESIDUAL_INTERACTION,
                              residual_reason=None, missing_drivers={},
                              drivers={k: 0.1 for k in STRATEGY_DRIVERS}))
    unexp = summarize_ko(_exp())
    assert "상호작용" in inter
    assert "상호작용" not in unexp, (
        "커버리지가 불완전한데 잔차를 복리 상호작용이라 불렀습니다")
    assert "설명하지 못한" in unexp


def test_a_complete_coverage_is_never_called_unexplained():
    """⑤ ★짝★ 항상-unexplained 구현을 배제한다."""
    text = summarize_ko(_exp(residual_kind=RESIDUAL_INTERACTION,
                             residual_reason=None, missing_drivers={},
                             drivers={k: 0.1 for k in STRATEGY_DRIVERS}))
    assert "설명하지 못한" not in text


# ═══════════════════════════════════════════════════════════════════════════
# ⑥⑦ 미측정 드라이버 — ★이름과 사유로 부른다★
# ═══════════════════════════════════════════════════════════════════════════
def test_missing_drivers_are_named_in_the_sentence():
    """⑥ 이름을 안 부르면 "그 축이 없다" 는 사실이 사라진다."""
    text = summarize_ko(_exp())
    assert DRIVER_LABELS["macro_effect"] in text


def test_missing_drivers_is_a_dict_of_reasons_not_a_list():
    """★이름만 나열하면 **왜** 없는지가 사라진다★"""
    exp = _exp()
    assert isinstance(exp.missing_drivers, dict)
    for name, why in exp.missing_drivers.items():
        assert name in DRIVER_LABELS and isinstance(why, str) and why.strip()


def test_dividend_and_fx_are_permanently_unmeasurable_with_reasons():
    """⑦ ★데이터가 없다는 사실을 상수가 들고 있다★

    일별 배당락·지급일 데이터가 없고(연간 DPS 공시뿐), 해외 직접보유도 없다.
    누가 이 둘에 값을 넣으려 하면 **그 데이터부터** 필요하다.
    """
    assert set(UNMEASURABLE_DRIVERS) == {DRIVER_DIVIDEND, DRIVER_FX}
    for name, why in UNMEASURABLE_DRIVERS.items():
        assert len(why) >= 30, f"{name}: 사유가 너무 얇습니다"
        assert "없습니다" in why


def test_a_holding_explanation_names_both_unmeasurable_drivers():
    text = summarize_ko(_exp(
        driver_set=DRIVER_SET_HOLDING, scope="portfolio", scope_id="요청 보유",
        drivers={DRIVER_PRICE: 0.44, DRIVER_REBALANCE: None,
                 DRIVER_FEE: None, DRIVER_DIVIDEND: None, DRIVER_FX: None},
        missing_drivers={DRIVER_REBALANCE: "그날의 매매를 받지 못했습니다",
                         DRIVER_FEE: "매매를 몰라 비용을 잴 수 없습니다",
                         **UNMEASURABLE_DRIVERS},
        price_basis={"basis": "uniform_raw", "reason": None}))
    assert DRIVER_LABELS[DRIVER_DIVIDEND] in text
    assert DRIVER_LABELS[DRIVER_FX] in text


# ═══════════════════════════════════════════════════════════════════════════
# ⑪ 가격 기준을 문장이 말한다
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("basis,needle", [
    ("uniform_raw", "원주가"),
    ("uniform_adjusted", "수정주가"),
    ("mixed", "섞여"),
    ("unknown", "알 수 없"),
])
def test_the_price_basis_is_stated(basis, needle):
    """★배당락이 손실로 보일 수 있다는 사실을 문장이 말한다★"""
    text = summarize_ko(_exp(
        driver_set=DRIVER_SET_HOLDING, scope="portfolio", scope_id="요청 보유",
        drivers={DRIVER_PRICE: 0.44, DRIVER_REBALANCE: None, DRIVER_FEE: None,
                 DRIVER_DIVIDEND: None, DRIVER_FX: None},
        missing_drivers=dict(UNMEASURABLE_DRIVERS),
        price_basis={"basis": basis, "reason": None}))
    assert needle in text, text


def test_a_strategy_explanation_has_no_price_basis_clause():
    """★전략 분해에는 가격 기준 절이 없다★ — 그 축을 다루지 않는다."""
    assert "주가" not in summarize_ko(_exp())


# ═══════════════════════════════════════════════════════════════════════════
# 문장 규율
# ═══════════════════════════════════════════════════════════════════════════
def test_the_sentence_makes_no_judgement():
    """★판정 부사를 쓰지 않는다★ (CLAUDE.md §2) — 템플릿은 값을 옮길 뿐이다."""
    text = summarize_ko(_exp())
    for banned in ("견고", "우수", "훌륭", "안정적으로", "성공적",
                   "검증됨", "입증"):
        assert banned not in text, f"판정 어휘가 들어갔습니다: {banned}"


def test_the_sentence_is_one_paragraph():
    """로드맵의 완료 판정 — "한국어 한 문단"."""
    text = summarize_ko(_exp())
    assert "\n" not in text and 40 < len(text) < 900


def test_an_unknown_total_says_so():
    """★미상을 0 으로 적지 않는다★"""
    text = summarize_ko(_exp(total_change_pct=None))
    assert "알 수 없" in text or "미상" in text


def test_to_dict_keeps_every_field():
    d = _exp().to_dict()
    for k in ("as_of", "scope", "scope_id", "driver_set", "total_change_pct",
              "drivers", "missing_drivers", "residual_pct", "residual_kind",
              "residual_reason", "price_basis", "summary_ko"):
        assert k in d, k
    assert d["summary_ko"] == summarize_ko(_exp())


# ═══════════════════════════════════════════════════════════════════════════
# 문장 품질 — ★눈으로 보고 찾은 결함 넷★
# ─────────────────────────────────────────────────────────────────────────────
# 위 22개가 전부 초록인 채로 다음 넷이 살아 있었다: 조사 앞 공백("실행 #7 의"),
# 받침 무시("매크로 오버레이 는"), 구분자 충돌(라벨의 `·` 가 목록 구분자 `·` 와
# 섞임), 평문 응답에 마크다운 `**`. ★테스트가 문장을 **읽지** 않고 조각만 찾고
# 있었다★ — 아래는 문장을 읽는다.
# ═══════════════════════════════════════════════════════════════════════════
def test_no_space_before_a_josa():
    """★"실행 #7 의" 는 한국어가 아니다★"""
    text = summarize_ko(_exp(scope_id="멀티백테스트 실행 #7"))
    assert "멀티백테스트 실행 #7의" in text
    assert " 의 하루" not in text


@pytest.mark.parametrize("label,expected", [
    ("매크로 오버레이", "매크로 오버레이는"),   # 받침 없음
    ("배당", "배당은"),                         # 받침 있음
])
def test_the_topic_particle_follows_the_final_consonant(label, expected):
    """★받침에 따라 은/는이 달라진다★ — 목록의 **마지막** 낱말이 정한다."""
    from src.domain.daily_explanation import _josa
    assert f"{label}{_josa(label, '은', '는')}" == expected


def test_the_missing_clause_uses_the_last_label_for_its_particle():
    text = summarize_ko(_exp(
        drivers={k: None for k in STRATEGY_DRIVERS},
        missing_drivers={"macro_effect": "미관측"}))
    assert "매크로 오버레이는 재지 못했습니다" in text, text


def test_no_markdown_leaks_into_the_plain_sentence():
    """★이 문자열은 API 응답이다★ — 렌더러를 가정할 수 없다."""
    for kw in ({}, {"driver_set": DRIVER_SET_HOLDING,
                    "price_basis": {"basis": "uniform_raw", "reason": None},
                    "drivers": {DRIVER_PRICE: 0.1}, "missing_drivers": {}}):
        text = summarize_ko(_exp(**kw))
        for mark in ("**", "__", "`"):
            assert mark not in text, f"마크다운이 새어 나왔습니다: {mark!r} in {text}"


def test_the_list_separator_never_collides_with_a_label():
    """★라벨이 구분자를 품으면 어디까지가 한 항목인지 읽을 수 없다★

    `수수료·세금` 을 `·` 로 이으면 항목이 넷인지 다섯인지 가를 수 없었다.
    구분자는 `, ` 이고, **어떤 라벨도 그것을 품지 않아야** 한다.
    """
    for label in DRIVER_LABELS.values():
        assert ", " not in label, f"라벨이 구분자를 품고 있습니다: {label!r}"


def test_the_ranked_clause_is_readable_as_a_list():
    """기여 절이 항목 수만큼의 구분자를 갖는다."""
    text = summarize_ko(_exp(
        drivers={"allocation_effect": 0.31, "cost_effect": -0.08,
                 "selection_effect": 0.16},
        missing_drivers={}, residual_kind=RESIDUAL_INTERACTION,
        residual_reason=None))
    clause = text.split("기여가 큰 순서로 ")[1].split(" 입니다.")[0]
    assert len(clause.split(", ")) == 3, clause


# ═══════════════════════════════════════════════════════════════════════════
# ★전수★ — 사유 문자열도 문장과 같은 규율을 지킨다
# ─────────────────────────────────────────────────────────────────────────────
# `summarize_ko` 만 검사했더니 **사유 문자열**에 마크다운(`**없었다**`)과 이중
# 대시가 남아 있었다. 사유도 API 응답으로 나가고, 템플릿이 그것을 문장에 꿴다.
# 그래서 검사 대상은 "문장" 이 아니라 ★사용자에게 도달하는 모든 문자열★ 이다.
# ═══════════════════════════════════════════════════════════════════════════
def _user_facing_strings() -> dict[str, str]:
    """설명 계층이 사용자에게 내보내는 고정 문자열 전부."""
    import src.domain.daily_explanation as dom
    import src.engine.daily_explain_backtest as bt
    import src.engine.daily_explain_holdings as hd

    out: dict[str, str] = {}
    for mod in (dom, bt, hd):
        for name in dir(mod):
            if name.startswith("__"):
                continue
            val = getattr(mod, name)
            if isinstance(val, str) and len(val) > 20:
                out[f"{mod.__name__}.{name}"] = val
            elif isinstance(val, dict):
                for k, v in val.items():
                    if isinstance(v, str) and len(v) > 20:
                        out[f"{mod.__name__}.{name}[{k}]"] = v
    return out


def test_the_scan_finds_the_strings():
    """★공허 배제★ 0개면 아래 두 검사가 아무 말도 하지 않는다."""
    found = _user_facing_strings()
    assert len(found) >= 8, f"고정 문자열을 {len(found)}개만 찾았습니다"


def test_no_user_facing_string_contains_markdown():
    """★렌더러를 가정할 수 없다★ — `**` 가 그대로 보이면 그것이 결함이다."""
    bad = {k: v for k, v in _user_facing_strings().items()
           if "**" in v or "__" in v or "`" in v}
    assert not bad, f"마크다운이 든 문자열: {sorted(bad)}"


def test_no_reason_string_carries_its_own_dash():
    """★템플릿이 대시를 하나 붙인다★ — 사유가 또 품으면 "… — … — …" 가 된다."""
    bad = {k: v for k, v in _user_facing_strings().items()
           if k.endswith("]") is False and " — " in v
           and not k.startswith("src.domain.daily_explanation._BASIS")}
    assert not bad, f"사유가 대시를 품고 있습니다: {sorted(bad)}"


def test_the_residual_clause_has_exactly_one_dash():
    """문장 수준에서도 확인한다 — 사유가 바뀌어도 여기가 잡는다."""
    text = summarize_ko(_exp(residual_reason="어떤 사유"))
    clause = text.split("설명하지 못한 몫 ")[1]
    assert clause.count(" — ") == 1, clause
