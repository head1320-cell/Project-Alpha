"""젠포트 17그룹 → 88 세부업종 taxonomy + 선택 해석.

① 구조: 정확히 88 세부 / 17 그룹 (캡처 전사 — 합계 검증)
② 시드 무결성: 모든 시드 키가 트리에 존재, 코드 6자리
③ 선택 해석: theme:세부 / themegroup:그룹 → 시드 종목, 미시드=0, 가짜 id=no-op
④ /theme-tree 엔드포인트
"""
import re

from src.data.genport_themes import (
    SUBSECTOR_GROUP,
    THEME_SEED,
    THEME_TREE,
    get_theme_tree,
    group_members,
    theme_members,
)


def test_structure_is_88():
    total = sum(len(v) for v in THEME_TREE.values())
    assert total == 88 and len(THEME_TREE) == 17
    # 역인덱스 일관성
    assert len(SUBSECTOR_GROUP) == 88


def test_seed_integrity():
    # 시드 키는 전부 트리에 존재 (오타 방어)
    assert all(k in SUBSECTOR_GROUP for k in THEME_SEED)
    # 코드는 6자리 숫자
    for codes in THEME_SEED.values():
        for c in codes:
            assert re.fullmatch(r"\d{6}", c), c
    # 의미 있는 커버리지 (대표주 시드)
    seeded = {c for v in THEME_SEED.values() for c in v}
    assert len(seeded) >= 100


def test_member_resolution():
    assert "005930" in theme_members("반도체")           # 삼성전자
    assert "036570" in theme_members("게임")             # 엔씨
    assert theme_members("블랙박스") == []               # 미시드 → 빈
    # 그룹 = 하위 세부 합집합
    g = group_members("반도체")
    assert "005930" in g and "042700" in g               # 반도체 + 반도체 장비
    assert set(g) >= set(theme_members("반도체 장비"))


def test_theme_tree_endpoint():
    t = get_theme_tree()
    assert t["group_count"] == 17 and t["subsector_count"] == 88
    # 각 그룹이 세부업종 보유
    반도체 = next(g for g in t["groups"] if g["label"] == "반도체")
    assert len(반도체["subsectors"]) == 3
    assert 반도체["subsectors"][0]["id"].startswith("theme:")


def test_stock_browse_cascade():
    # 관심종목 모달 4단 카스케이드 — 주식 업종(17)/주식 테마(88)
    from src.api.screener_routes import stock_browse
    cat = stock_browse()
    assert len(cat["groups"]) == 17 and len(cat["themes"]) == 88
    # 주식 업종 → 그룹 멤버
    g = stock_browse(cls="group", id="반도체")["items"]
    assert any(it["code"] == "005930" for it in g)        # 삼성전자
    # 주식 테마 → 세부 멤버
    t = stock_browse(cls="theme", id="반도체 장비")["items"]
    assert any(it["code"] == "042700" for it in t)        # 한미반도체
    # 미시드 테마 → 빈
    assert stock_browse(cls="theme", id="블랙박스")["items"] == []


def test_select_universe_theme(monkeypatch):
    from src.engine.universe_select import select_universe
    # 게임 세부 → 시드 종목만
    tk, total = select_universe(sectors=["theme:게임"])
    assert "036570" in tk and len(tk) < total
    # 미시드 세부 → 0 (유효 id지만 멤버 없음)
    assert select_universe(sectors=["theme:블랙박스"])[0] == []
    # 가짜 id → no-op (전체 통과)
    assert len(select_universe(sectors=["theme:없는세부"])[0]) == total
    # 그룹 선택
    tkg, _ = select_universe(sectors=["themegroup:반도체"])
    assert "005930" in tkg and "042700" in tkg
