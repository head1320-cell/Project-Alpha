"""구조화된 논지 + kill 조건 → 백테스트 다리 (P2-5 커밋 ①)

★자유 텍스트로 두면 검증할 수 없다★ 그래서 이 파일이 거는 것은 세 가지다:
kill 조건이 **레지스트리로** 검증되는가 · 다리의 **폭**을 정직하게 말하는가 ·
올리지 못한 조건의 **사유**가 남는가.

★새 DSL 이 없다는 것이 요점★ 조건 dict 는 `filter_ast.parse_condition` 을 그대로
통과한다. 두 번째 검증기를 만들면 두 검증기가 서로 어긋나기 시작한다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402

from src.engine.company_thesis import (  # noqa: E402
    BRIDGEABLE_TIERS,
    OPT_IN_FLAG,
    TIER_BACKTESTABLE,
    TIER_LOOKAHEAD,
    TIER_SCREEN_ONLY,
    kill_condition_bridge,
    known_sections,
    thesis_to_sell_conditions,
    token_maps,
    validate_thesis,
)
from src.engine.filter_ast import FIELD_BY_ID, parse_condition  # noqa: E402

CODE = "005930"
TODAY = date(2026, 8, 23)

# 실측으로 고른 대표들 — PIT 다리를 건너는 것 / 스냅샷 상수인 것 / 도달 불가한 것.
PIT_FIELD = "roe"
REACHABLE_ONLY_FIELD = "accruals"
UNREACHABLE_FIELD = "momentum_12_1"


def _kill(field: str, op: str = "lt", value=8.0, **kw) -> dict:
    return {"kind": "field", "field": field, "op": op, "value": value, **kw}


def _thesis(**kw) -> dict:
    base = dict(
        claim="반도체 사이클 저점에서 ROE 가 정상화된다",
        evidence=[{"section": "quality", "path": "roe", "note": "8.8%"}],
        catalysts=[{"what": "4분기 실적", "by": "2026-12-31"}],
        kill_conditions=[_kill(PIT_FIELD)],
    )
    base.update(kw)
    return base


def _rows(out) -> dict:
    return {r["field"]: r for r in out["kill_conditions"]["rows"]}


# ── 1. ★kill 조건이 레지스트리로 검증된다★ ─────────────────────────────────
def test_an_unknown_field_is_refused_with_the_registrys_own_reason():
    """★두 번째 검증기를 만들지 않는다★ 문구까지 레지스트리 것을 그대로 쓴다."""
    out = kill_condition_bridge([_kill("존재하지않는필드")], code=CODE)
    row = out["rows"][0]
    assert row["valid"] is False
    assert row["reason"] == parse_condition(_kill("존재하지않는필드")).validate()
    assert "Unknown field" in row["reason"]
    # 검증에 실패한 조건에는 tier 를 붙이지 않는다 — 모르는 것을 분류할 수 없다.
    assert row["tier"] is None
    assert out["available"] is False


def test_a_valid_field_passes_and_gets_a_tier():
    """★짝★ 거부만 확인하면 전부 거부해도 green 이다."""
    out = kill_condition_bridge([_kill(PIT_FIELD)], code=CODE)
    row = out["rows"][0]
    assert row["valid"] is True and row["reason"] is None or row["tier"]
    assert row["tier"] in (TIER_BACKTESTABLE, TIER_LOOKAHEAD, TIER_SCREEN_ONLY)
    assert row["valid"] is True


def test_no_new_dsl_the_condition_dict_passes_through_parse_condition():
    """★새 DSL 0★ 논지가 쓰는 조건은 스크리너·백테스트가 쓰는 그 조건이다."""
    cond = _kill(PIT_FIELD, op="lt", value=8.0)
    parsed = parse_condition(cond)
    assert parsed.field == PIT_FIELD and parsed.op == "lt" and parsed.value == 8.0
    # 다리는 원본 dict 를 변형하지 않고 그대로 들고 있는다.
    assert kill_condition_bridge([cond], code=CODE)["rows"][0]["condition"] is cond


# ── 2. ★다리의 폭을 정직하게 말한다★ ───────────────────────────────────────
def test_the_bridge_width_matches_the_measurement():
    """★실측 검산★ 숫자가 달라지면 상류 레지스트리가 바뀐 것이다 — 먼저 그것을 본다."""
    pit, reach = token_maps()
    assert len(FIELD_BY_ID) == 157
    assert len(reach) == 92, f"도달 가능 필드가 92 에서 바뀌었다: {len(reach)}"
    assert set(pit) == {"per", "pbr", "psr", "pcr", "roe"}, pit


def test_a_pit_field_without_history_is_labelled_lookahead(monkeypatch):
    """★적재되지 않으면 PIT 토큰조차 스냅샷 상수로 떨어진다★"""
    monkeypatch.setattr("src.engine.company_thesis.history_loaded", lambda code: False)
    row = kill_condition_bridge([_kill(PIT_FIELD)], code=CODE)["rows"][0]
    assert row["tier"] == TIER_LOOKAHEAD
    assert row["pit_supported"] is True
    assert row["lookahead"] is True
    assert row["requires_opt_in"] == OPT_IN_FLAG
    assert "look-ahead" in row["reason"]


def test_a_pit_field_with_history_crosses_the_bridge(monkeypatch):
    """★짝★ 재무 시계열이 적재되면 같은 조건이 tier 1 이 된다."""
    monkeypatch.setattr("src.engine.company_thesis.history_loaded", lambda code: True)
    row = kill_condition_bridge([_kill(PIT_FIELD)], code=CODE)["rows"][0]
    assert row["tier"] == TIER_BACKTESTABLE
    assert row["lookahead"] is False
    assert row["reason"] is None


def test_history_is_checked_for_real_not_assumed():
    """★가정하지 않는다★ 이 컨테이너에는 financials_history 가 비어 있다."""
    from src.data.dart_history import load_history
    assert load_history(CODE) == [], "적재 상태가 바뀌었다 — 분류 기대치를 다시 잰다"
    assert kill_condition_bridge([_kill(PIT_FIELD)], code=CODE)["history_loaded"] is False
    # 종목을 모르면 적재를 주장할 수 없다.
    assert kill_condition_bridge([_kill(PIT_FIELD)])["history_loaded"] is False


def test_a_non_pit_but_reachable_field_is_lookahead_even_with_history(monkeypatch):
    """★재무 시계열이 있어도 PIT 토큰이 아니면 룩어헤드다★ 둘은 다른 조건이다."""
    monkeypatch.setattr("src.engine.company_thesis.history_loaded", lambda code: True)
    row = kill_condition_bridge([_kill(REACHABLE_ONLY_FIELD, op="gt", value=0.1)],
                                code=CODE)["rows"][0]
    assert row["tier"] == TIER_LOOKAHEAD
    assert row["pit_supported"] is False
    assert "PIT 지원 토큰이 아닙니다" in row["reason"]


def test_an_unreachable_field_is_screen_only():
    """★65개는 조건식 토큰이 아예 없다★ 빈칸이 아니라 사유로 답한다."""
    row = kill_condition_bridge([_kill(UNREACHABLE_FIELD, value=0.0)],
                                code=CODE)["rows"][0]
    assert row["valid"] is True, "레지스트리에는 있는 필드다"
    assert row["tier"] == TIER_SCREEN_ONLY
    assert row["token"] is None
    assert "조건식 토큰이 없습니다" in row["reason"]


def test_a_cross_sectional_rank_cannot_be_a_single_stock_condition():
    row = kill_condition_bridge([{"kind": "field", "field": PIT_FIELD,
                                  "rank_mode": "bottom_pct", "rank_value": 20}],
                                code=CODE)["rows"][0]
    assert row["tier"] == TIER_SCREEN_ONLY
    assert "횡단면 순위" in row["reason"]


def test_a_non_field_kind_says_which_kind_it_was():
    row = kill_condition_bridge([{"kind": "peer", "field": PIT_FIELD,
                                  "peer_scope": "sector", "peer_stat": "median",
                                  "op": "lt", "value": 1.0}], code=CODE)["rows"][0]
    assert row["tier"] == TIER_SCREEN_ONLY
    assert "kind=peer" in row["reason"]


def test_an_empty_kill_list_is_a_reason_not_an_empty_success():
    out = kill_condition_bridge([], code=CODE)
    assert out["available"] is False and out["reason"]
    assert out["rows"] == []


# ── 3. ★논지 자체의 검증★ ──────────────────────────────────────────────────
def test_an_empty_claim_is_refused():
    """★빈 논지는 논지가 아니다★"""
    out = validate_thesis(_thesis(claim="   "), code=CODE, today=TODAY)
    assert out["available"] is False
    assert any("주장" in e for e in out["errors"])


def test_a_complete_thesis_validates():
    """★짝★ 전부 거부하면 위 테스트도 green 이다."""
    out = validate_thesis(_thesis(), code=CODE, today=TODAY)
    assert out["available"] is True, out["reason"]
    assert out["claim"] and out["reason"] is None and out["errors"] == []


def test_evidence_must_point_at_a_real_snapshot_section():
    out = validate_thesis(_thesis(evidence=[{"section": "없는섹션", "path": "x"}]),
                          code=CODE, today=TODAY)
    assert out["available"] is False
    ev = out["evidence"][0]
    assert ev["valid"] is False and "스냅샷 섹션이 아닙니다" in ev["reason"]


def test_every_real_section_is_accepted_as_evidence():
    """★짝★ 섹션 목록을 코드에서 읽는 것이 요점 — 하드코딩하면 곧 어긋난다."""
    sections = known_sections()
    assert {"quality", "valuation", "risk", "peers"} <= sections
    assert "thesis" not in sections, "논지가 자기를 근거로 드는 것은 순환이다"
    for s in sections:
        out = validate_thesis(_thesis(evidence=[{"section": s}]),
                              code=CODE, today=TODAY)
        assert out["evidence"][0]["valid"] is True, s


def test_a_catalyst_without_a_deadline_is_refused():
    """★기한 없는 촉매는 반증되지 않는다★ 영원히 유예된다."""
    out = validate_thesis(_thesis(catalysts=[{"what": "언젠가 실적 개선"}]),
                          code=CODE, today=TODAY)
    assert out["available"] is False
    assert "기한(by)이 없습니다" in out["catalysts"][0]["reason"]


def test_a_past_deadline_is_judged_overdue_rather_than_left_quiet():
    """★기한 지난 촉매를 조용히 두는 것이 논지가 썩는 방식이다★"""
    past = (TODAY - timedelta(days=30)).isoformat()
    fut = (TODAY + timedelta(days=30)).isoformat()
    out = validate_thesis(
        _thesis(catalysts=[{"what": "지난 촉매", "by": past},
                           {"what": "남은 촉매", "by": fut}]),
        code=CODE, today=TODAY)
    a, b = out["catalysts"]
    assert a["overdue"] is True and a["days_left"] == -30
    assert b["overdue"] is False and b["days_left"] == 30
    assert out["overdue_catalysts"] == ["지난 촉매"]
    # 기한이 지났다고 논지가 무효가 되지는 않는다 — 판정해서 보여줄 뿐이다.
    assert out["available"] is True, out["reason"]


def test_an_unreadable_deadline_says_so():
    out = validate_thesis(_thesis(catalysts=[{"what": "실적", "by": "4분기쯤"}]),
                          code=CODE, today=TODAY)
    assert out["available"] is False
    assert "YYYY-MM-DD" in out["catalysts"][0]["reason"]


def test_a_thesis_with_no_kill_condition_is_refused():
    """★반증할 수 없는 논지는 검증할 수 없다★ 이 슬라이스가 존재하는 이유다."""
    out = validate_thesis(_thesis(kill_conditions=[]), code=CODE, today=TODAY)
    assert out["available"] is False
    assert any("kill 조건이 없습니다" in e for e in out["errors"])


def test_an_invalid_kill_condition_fails_the_thesis_without_raising():
    out = validate_thesis(_thesis(kill_conditions=[_kill("없는필드")]),
                          code=CODE, today=TODAY)
    assert out["available"] is False
    assert any("kill 조건[0]" in e for e in out["errors"])


def test_a_non_dict_thesis_is_a_reason_not_a_crash():
    out = validate_thesis("반도체가 좋아진다", code=CODE, today=TODAY)
    assert out["available"] is False and out["reason"]


# ── 4. ★백테스트 다리★ ─────────────────────────────────────────────────────
def test_only_bridgeable_tiers_are_lifted_and_the_rest_carry_a_reason():
    """★조용히 빠진 kill 조건은 없는 kill 조건보다 나쁘다★"""
    out = thesis_to_sell_conditions(_thesis(kill_conditions=[
        _kill(PIT_FIELD), _kill(UNREACHABLE_FIELD, value=0.0),
    ]), code=CODE)
    assert len(out["conditions"]) == 1
    assert out["conditions"][0]["factor_token"]

    assert len(out["excluded"]) == 1
    ex = out["excluded"][0]
    assert ex["field"] == UNREACHABLE_FIELD
    assert ex["tier"] == TIER_SCREEN_ONLY
    assert ex["reason"], "제외에는 반드시 사유가 붙는다"


def test_the_lifted_condition_is_shaped_for_the_backtest_engine():
    """★이미 있는 다리에 올린다★ condition_strategy 가 읽는 그 dict 다."""
    out = thesis_to_sell_conditions(_thesis(kill_conditions=[
        _kill(PIT_FIELD, op="lt", value=8.0)]), code=CODE)
    c = out["conditions"][0]
    assert set(c) >= {"factor_token", "function_id", "op", "rhs"}
    assert c["op"] in ("gte", "lte", "eq", "between")
    assert c["rhs"] == 8.0


def test_a_strict_op_is_relabelled_not_silently_changed():
    """★경계 의미가 달라진 것을 숨기지 않는다★ lt 와 lte 는 임계값에서 갈린다."""
    c = thesis_to_sell_conditions(_thesis(kill_conditions=[
        _kill(PIT_FIELD, op="lt", value=8.0)]), code=CODE)["conditions"][0]
    assert c["op"] == "lte" and "boundary_note" in c

    c2 = thesis_to_sell_conditions(_thesis(kill_conditions=[
        _kill(PIT_FIELD, op="lte", value=8.0)]), code=CODE)["conditions"][0]
    assert c2["op"] == "lte" and "boundary_note" not in c2


def test_a_between_kill_carries_both_bounds():
    c = thesis_to_sell_conditions(_thesis(kill_conditions=[
        {"kind": "field", "field": PIT_FIELD, "op": "between",
         "value": 0.0, "value2": 8.0}]), code=CODE)["conditions"][0]
    assert c["op"] == "between" and c["rhs"] == 0.0 and c["rhs2"] == 8.0


def test_a_lookahead_lift_labels_itself_and_names_the_opt_in():
    """★룩어헤드를 숨기지 않는다★ 켜야 도는 것이면 무엇을 켜야 하는지 말한다."""
    out = thesis_to_sell_conditions(_thesis(kill_conditions=[_kill(PIT_FIELD)]),
                                    code=CODE)
    assert out["lookahead"] is True
    assert out["requires_opt_in"] == OPT_IN_FLAG
    assert out["conditions"][0]["lookahead"] is True
    assert OPT_IN_FLAG in out["note"]


def test_a_clean_lift_makes_no_lookahead_claim(monkeypatch):
    """★짝★ tier 1 만 올라가면 룩어헤드 라벨이 붙지 않는다."""
    monkeypatch.setattr("src.engine.company_thesis.history_loaded", lambda code: True)
    out = thesis_to_sell_conditions(_thesis(kill_conditions=[_kill(PIT_FIELD)]),
                                    code=CODE)
    assert out["lookahead"] is False
    assert out["requires_opt_in"] is None and out["note"] is None
    assert "lookahead" not in out["conditions"][0]


def test_nothing_liftable_is_a_reason_not_an_empty_list():
    out = thesis_to_sell_conditions(_thesis(kill_conditions=[
        _kill(UNREACHABLE_FIELD, value=0.0)]), code=CODE)
    assert out["available"] is False and out["reason"]
    assert out["conditions"] == [] and out["excluded"]


def test_the_bridgeable_tiers_are_exactly_one_and_two():
    assert BRIDGEABLE_TIERS == (TIER_BACKTESTABLE, TIER_LOOKAHEAD)
    assert TIER_SCREEN_ONLY not in BRIDGEABLE_TIERS


@pytest.mark.parametrize("field,expected_pit", [
    ("roe", True), ("per", True), ("pbr", True), ("psr", True), ("pcr", True),
    ("accruals", False), ("altman_z", False),
])
def test_pit_support_is_read_from_the_upstream_registry(field, expected_pit):
    row = kill_condition_bridge([_kill(field, value=1.0)], code=CODE)["rows"][0]
    assert row["pit_supported"] is expected_pit
