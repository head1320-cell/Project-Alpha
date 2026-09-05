"""매크로 토큰 목록의 ★단일 출처★ — 백엔드가 표시 그룹까지 서빙한다

## 무엇이 문제였나 — 목록이 두 벌이었다

`FRED_INDICATOR_TOKENS` 8종을 열면서 프런트 픽커(`butlerFactors.ts`)에도 손으로
8줄을 더했다. 그 순간 목록이 갈라졌고, **아무 테스트도 그것을 잡지 못했다.**

실측한 괴리:

    백엔드 macro 토큰 20개 · 픽커에 13개
    ★8개는 사용자가 닿을 수 없다★ — US국채(1·2·3·5·7·20·30년) · 국고채(1년)

저장소는 같은 병을 이미 앓았다 — `ingest_registry` 이전의 `DbStatusPanel` 에서
`macro` 적재 대상이 **화면에서만** 빠져 있었다. 처방도 같다: 백엔드가 목록을 갖고,
UI 는 그것을 그린다.

## 이 파일이 거는 계약

① ★어휘를 다시 나열하지 않는다★ — 그룹은 기존 딕셔너리에서 **파생**한다.
   다시 적으면 두 벌이 갈라지고, 그게 지금 고치려는 병이다.
② **매크로 토큰은 전부 정확히 한 그룹에 있다** — 그룹에 안 넣고 딕셔너리에만
   추가하면 여기서 죽는다. 지금은 아무것도 실패하지 않고 화면에서만 사라진다.
③ **미검증 토큰도 어휘에 남는다** — `ECOS_UNVERIFIED_TOKENS` 는 `supported` 가
   아니지만 저장된 전략이 쓰고 있다. 목록에서 지우면 "그런 토큰은 없다" 로 읽힌다.
   픽커는 그것들을 **사유와 함께 회색**으로 그린다.
④ **추가만 한다** — `token_support()` 의 기존 키는 그대로다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.kis_strategies.factor_tokens as ft  # noqa: E402


def _grouped_tokens() -> list[str]:
    return [t for g in ft.macro_token_groups() for t in g.tokens]


# ═══════════════════════════════════════════════════════════════════════════════
# ② ★B 의 알맹이★ — 그룹에 안 들어간 매크로 토큰은 없다
# ═══════════════════════════════════════════════════════════════════════════════

def test_every_supported_macro_token_is_in_exactly_one_group():
    """★이 테스트가 이 작업의 이유다★

    지금까지는 백엔드에 매크로 토큰을 더해도 **아무것도 실패하지 않고** 화면에만
    안 나왔다. 그 침묵을 없앤다.
    """
    macro = {k for k, v in ft.token_support()["supported"].items() if v == "macro"}
    grouped = _grouped_tokens()
    missing = sorted(macro - set(grouped))
    assert missing == [], (
        f"그룹에 없는 매크로 토큰: {missing} — 픽커에서 사용자가 닿을 수 없다. "
        "`macro_token_groups()` 의 출처 딕셔너리를 확인할 것.")


def test_the_deliberately_unverified_tokens_stay_in_the_vocabulary():
    """★어휘를 지우지 않는다★ 저장된 전략이 그 토큰을 쓰고 있다.

    좌표가 미확인이라 `supported` 는 아니지만, 목록에서 빼면 "그런 토큰은 없다" 로
    읽힌다. 사유와 함께 보이는 것이 맞다.
    """
    grouped = set(_grouped_tokens())
    missing = sorted(set(ft.ECOS_UNVERIFIED_TOKENS) - grouped)
    assert missing == [], f"미검증 토큰이 어휘에서 사라졌다: {missing}"


def test_no_token_appears_in_two_groups():
    """중복 노출은 픽커의 항목 id(`카테고리/그룹/이름`)도 흔든다."""
    grouped = _grouped_tokens()
    dupes = sorted({t for t in grouped if grouped.count(t) > 1})
    assert dupes == [], f"두 그룹에 같은 토큰이 있다: {dupes}"


def test_no_group_is_empty():
    """★빈 그룹은 '팩터가 없다' 로 읽힌다★ 출처 딕셔너리가 비면 여기서 잡는다."""
    empty = [g.label for g in ft.macro_token_groups() if not g.tokens]
    assert empty == [], f"빈 그룹: {empty}"


# ═══════════════════════════════════════════════════════════════════════════════
# ① 어휘는 파생이다 — 다시 나열하지 않았다
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_groups_are_derived_from_the_existing_dicts_not_relisted():
    """★손으로 다시 적으면 두 벌이 갈라진다★

    그룹마다 출처 딕셔너리가 정확히 하나다. 그래서 딕셔너리를 고치면 그룹이 따라온다.
    """
    by_label = {g.label: set(g.tokens) for g in ft.macro_token_groups()}
    assert by_label["국내 금리·환율"] == set(ft.ECOS_TOKENS) | set(ft.ECOS_UNVERIFIED_TOKENS)
    assert by_label["미국 국채"] == set(ft.FRED_TOKENS)
    assert by_label["미국 지표"] == set(ft.FRED_INDICATOR_TOKENS)


def test_a_token_added_to_a_source_dict_shows_up_in_a_group(monkeypatch):
    """★파생이 진짜인지 확인한다★ 딕셔너리에 넣으면 그룹에 나타나야 한다.

    이 테스트가 없으면 "우연히 지금 일치하는" 하드코딩도 위 테스트를 통과한다.
    """
    monkeypatch.setitem(ft.FRED_INDICATOR_TOKENS, "US신규주택착공(전년비)",
                        ("HOUST", "yoy"))
    assert "US신규주택착공(전년비)" in _grouped_tokens(), (
        "출처 딕셔너리에 넣었는데 그룹에 안 나타난다 — 파생이 아니라 하드코딩이다")


# ═══════════════════════════════════════════════════════════════════════════════
# ④ 엔드포인트 — 추가만 한다
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_support_map_carries_the_groups():
    ts = ft.token_support()
    groups = ts.get("macro_groups")
    assert groups, "지원 맵에 macro_groups 가 없다"
    assert all(isinstance(g.get("label"), str) and g.get("tokens") for g in groups), groups


def test_the_existing_support_map_keys_are_untouched():
    """★추가만★ 기존 소비자(`TokenSupportMap`)를 깨뜨리지 않는다."""
    ts = ft.token_support()
    for k in ("supported", "unsupported", "default_reason", "fundamental_note",
              "market_note", "macro_note", "flow_note", "score_note", "substitutes"):
        assert k in ts, f"기존 키 {k} 가 사라졌다"


def test_the_group_order_is_stable():
    """픽커가 이 순서로 그린다 — 순서가 흔들리면 화면이 실행마다 달라진다."""
    assert [g.label for g in ft.macro_token_groups()] == [
        "국내 금리·환율", "미국 국채", "미국 지표"]
