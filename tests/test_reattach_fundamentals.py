"""ingest 재적재 시 복원(item:) 종목에도 펀더멘털 재주입 —
과거 item:만 저장되고 ffl:은 없던 종목이 재실행 때 to_eval에서 빠져(복원)
펀더멘털 주입이 통째로 스킵되던(=유니버스 884 정체) 근본 원인의 회귀 방지."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.engine.screener as scr  # noqa: E402
from src.engine.screener import ScreenerItem, ValuationScreener  # noqa: E402


def _item(code: str) -> ScreenerItem:
    return ScreenerItem(
        stock_code=code, corp_name=f"C{code}", sector="반도체",
        current_price=1000.0, intrinsic_value=1200.0, gap_pct=-16.7, verdict="매수",
        composite_score=80.0, gap_score=80.0, roe_score=70.0, stability_score=60.0,
        roe_pct=10.0, roa_pct=6.0, per=9.0, pbr=1.1, debt_ratio_pct=40.0,
        dividend_yield_pct=2.0, market_cap_억=5000.0, fcf_억=300.0,
    )


def _spy(monkeypatch):
    """복원 경로 강제(to_eval 비움) + attach 스파이 + KIS/DB 부작용 차단."""
    seen: dict = {"attach": None, "store": None}
    codes = ["100001", "100002", "100003"]
    monkeypatch.setattr(ValuationScreener, "_load_cached_items",
                        lambda self, tks: {c: _item(c) for c in tks})   # 전부 복원(신규 0)
    import src.data.extended_factors_store as ef
    import src.data.fundamentals_store as fs
    import src.data.price_factors_store as pf
    monkeypatch.setattr(fs, "attach_fundamentals", lambda items: seen.__setitem__("attach", [i.stock_code for i in items]))
    monkeypatch.setattr(pf, "attach_price_factors", lambda items: None)
    monkeypatch.setattr(ef, "attach_extended_factors", lambda items: None)
    monkeypatch.setattr(ValuationScreener, "_store_items",
                        lambda self, items: seen.__setitem__("store", [i.stock_code for i in items]))
    monkeypatch.setattr(ValuationScreener, "_enrich_kis_quotes", lambda self, items: None)
    return seen, codes


def test_reattach_true_attaches_restored_items(monkeypatch):
    seen, codes = _spy(monkeypatch)
    sc = ValuationScreener()
    sc.run(universe=codes, filter_ast=None, liquidity_floor="off",
           limit=len(codes), no_cap=True, reattach_fundamentals=True)
    assert seen["attach"] == codes    # ★ 복원(신규 0)이어도 펀더멘털 재주입됨 → ffl: 생성
    assert seen["store"] == codes


def test_reattach_false_skips_restored_items(monkeypatch):
    seen, codes = _spy(monkeypatch)
    sc = ValuationScreener()
    sc.run(universe=codes, filter_ast=None, liquidity_floor="off",
           limit=len(codes), no_cap=True, reattach_fundamentals=False)
    assert seen["attach"] is None     # 기존 동작: 복원분엔 주입 스킵(불변)
    assert seen["store"] is None
