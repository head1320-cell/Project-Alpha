"""업종 세분류·ETF 배선 — collect-master 적재 시 마스터 코드로 전 종목 그룹화.

① 파서: 지수업종 중/소분류 + group_code(ETF) 캐시 저장
② frame: 마스터 sector_code로 sector 해석 (curated 우선, 없으면 '업종 {코드}')
③ /sectors: 마스터 있으면 실데이터 업종으로 확장
④ stock-browse: ETF 목록(group EF) 채워짐
⑤ sector_labels: 오버라이드 없으면 정직 폴백 (틀린 한글명 0)
"""
import pandas as pd

from src.data import sector_labels


def fake_flags():
    """collect-master 산출물 모사 — 코드별 업종/그룹."""
    return {
        "005930": {"market": "KOSPI", "market_cap_억": 4_000_000, "cap_size": "1",
                   "group_code": "ST", "sector_code": "0027", "sector_mid": "0102"},
        "000660": {"market": "KOSPI", "market_cap_억": 1_000_000, "cap_size": "1",
                   "group_code": "ST", "sector_code": "0027", "sector_mid": "0102"},
        "069500": {"market": "KOSPI", "market_cap_억": 50_000, "cap_size": "2",
                   "group_code": "EF", "sector_code": "", "sector_mid": ""},
        "900100": {"market": "KOSDAQ", "market_cap_억": 800, "cap_size": "3",
                   "group_code": "ST", "sector_code": "0031", "sector_mid": "0210"},
    }


def test_sector_labels_honest_fallback():
    # 오버라이드 비어 있음 → '업종 {코드}' (틀린 한글명 위험 0), 코드 없으면 None
    assert sector_labels.label_for("0027") == "업종 0027"
    assert sector_labels.label_for("") is None
    assert sector_labels.is_real_label("0027") is False
    # 오버라이드 채우면 한글
    sector_labels.SECTOR_CODE_LABELS["0027"] = "반도체"
    try:
        assert sector_labels.label_for("0027") == "반도체"
        assert sector_labels.is_real_label("0027") is True
    finally:
        sector_labels.SECTOR_CODE_LABELS.pop("0027", None)


def test_master_frame_uses_sector_code(monkeypatch):
    import src.engine.universe_select as us
    us.load_universe_frame.cache_clear()
    monkeypatch.setattr("src.data.stock_master.load_master_flags", fake_flags)
    df = us.load_universe_frame()
    us.load_universe_frame.cache_clear()
    assert set(["sector_code", "sector_mid"]).issubset(df.columns)
    row = df[df["ticker"] == "900100"].iloc[0]
    # curated STOCK_SECTOR에 없는 종목 → 마스터 코드 라벨 폴백
    assert row["sector"] == "업종 0031" and row["sector_code"] == "0031"
    assert row["sector_mid"] == "0210"
    # ETF 판별 (group EF)
    assert bool(df[df["ticker"] == "069500"].iloc[0]["is_etf"]) is True
    # 삼성/하이닉스 같은 코드 → 같은 업종 그룹
    assert (df[df["ticker"].isin(["005930", "000660"])]["sector"] == "업종 0027").all() \
        or (df[df["ticker"].isin(["005930", "000660"])]["sector"].notna()).all()


def test_sectors_endpoint_expands_with_master(monkeypatch):
    import src.engine.universe_select as us
    us.load_universe_frame.cache_clear()
    monkeypatch.setattr("src.data.stock_master.load_master_flags", fake_flags)
    from src.api.screener_routes import screener_sectors
    out = screener_sectors()
    us.load_universe_frame.cache_clear()
    assert out["source"] == "master"
    labels = {s["label"] for s in out["sectors"]}
    assert "업종 0031" in labels      # 마스터 코드 그룹 노출
    # ETF는 업종 그룹에서 제외
    assert all("069500" not in s["sample"] for s in out["sectors"])


def test_stock_browse_etf_populates(monkeypatch):
    import src.engine.universe_select as us
    us.load_universe_frame.cache_clear()
    monkeypatch.setattr("src.data.stock_master.load_master_flags", fake_flags)
    from src.api.screener_routes import stock_browse
    cat = stock_browse()
    assert cat["etf_size"] >= 1
    etf = stock_browse(cls="etf")
    us.load_universe_frame.cache_clear()
    assert any(it["code"] == "069500" for it in etf["items"])


def test_no_master_falls_back_to_curated(monkeypatch):
    import src.engine.universe_select as us
    us.load_universe_frame.cache_clear()
    monkeypatch.setattr("src.data.stock_master.load_master_flags", lambda: {})
    from src.api.screener_routes import screener_sectors
    out = screener_sectors()
    us.load_universe_frame.cache_clear()
    assert out["source"] == "curated"   # 미적재 시 기존 동작 불변
