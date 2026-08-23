"""매수 우선순위 정렬(sort_screener_items) 단위 테스트 — 1차/2차 키 + 방향.

ScreenerItem을 직접 구성해 정렬 로직만 검증. DB·평가 파이프라인 불필요.
"""
from src.engine.screener import ScreenerItem, sort_screener_items


def mk_item(code: str, per: float | None = None, pbr: float | None = None,
            score: float = 50.0, mcap: float | None = None) -> ScreenerItem:
    return ScreenerItem(
        stock_code=code, corp_name=f"기업{code}", sector=None,
        current_price=10_000, intrinsic_value=12_000, gap_pct=-16.7, verdict="저평가",
        composite_score=score, gap_score=50, roe_score=50, stability_score=50,
        roe_pct=10.0, roa_pct=5.0, per=per, pbr=pbr, debt_ratio_pct=80.0,
        dividend_yield_pct=2.0, market_cap_억=mcap, fcf_억=100.0,
    )


def codes(items) -> list[str]:
    return [it.stock_code for it in items]


def test_primary_desc_default():
    items = [mk_item("000001", score=10), mk_item("000002", score=30), mk_item("000003", score=20)]
    sort_screener_items(items, "composite_score")
    assert codes(items) == ["000002", "000003", "000001"]


def test_primary_ascending():
    """PER 낮은순 (저PER 우선) — ascending=True."""
    items = [mk_item("000001", per=15), mk_item("000002", per=5), mk_item("000003", per=10)]
    sort_screener_items(items, "per", ascending=True)
    assert codes(items) == ["000002", "000003", "000001"]


def test_secondary_tiebreak():
    """1차 동점(PER 동일) → 2차 키(PBR 낮은순)로 타이브레이크."""
    items = [
        mk_item("000001", per=10, pbr=3.0),
        mk_item("000002", per=10, pbr=1.0),
        mk_item("000003", per=5, pbr=9.0),
    ]
    sort_screener_items(items, "per", ascending=True,
                        sort_by_secondary="pbr", sort_secondary_ascending=True)
    # 1차: PER 5 < 10. 동점 그룹(10) 내 2차: PBR 1.0 < 3.0
    assert codes(items) == ["000003", "000002", "000001"]


def test_mixed_directions():
    """1차 내림차순 + 2차 오름차순 — 키별 독립 방향."""
    items = [
        mk_item("000001", score=90, per=20),
        mk_item("000002", score=90, per=10),
        mk_item("000003", score=95, per=30),
    ]
    sort_screener_items(items, "composite_score", ascending=False,
                        sort_by_secondary="per", sort_secondary_ascending=True)
    assert codes(items) == ["000003", "000002", "000001"]


def test_full_tie_is_deterministic_by_code():
    """전부 동점 → stock_code 순 (PIT 재현성)."""
    items = [mk_item("000300"), mk_item("000100"), mk_item("000200")]
    sort_screener_items(items, "composite_score")
    assert codes(items) == ["000100", "000200", "000300"]


def test_none_values_treated_as_zero():
    """결측(None) 키는 0으로 취급 — 내림차순 시 맨 뒤."""
    items = [mk_item("000001", per=None), mk_item("000002", per=8.0)]
    sort_screener_items(items, "per")  # desc
    assert codes(items) == ["000002", "000001"]


def test_unknown_secondary_is_noop():
    """알 수 없는 2차 키 → getattr 폴백 0 (전원 동점) → 1차 순서 유지."""
    items = [mk_item("000001", score=10), mk_item("000002", score=20)]
    sort_screener_items(items, "composite_score", sort_by_secondary="없는필드")
    assert codes(items) == ["000002", "000001"]
