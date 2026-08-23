"""매크로(BOK/FRED) 실연결 — 운영서 합성 MOCK 폴백 금지(정직 unavailable), 연결 점검."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.services.macro_collector import MacroCollector  # noqa: E402


def test_macro_real_mode_no_synthetic(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    c = MacroCollector()
    c.cache_clear()
    # 외부 fetch 빈 결과(키 없음/실패) → 운영선 합성 금지
    s = c._collect_one(key="KR_10Y", name="국고채10년", unit="%",
                       fetcher=lambda: ([], []), use_cache=False, source="BOK")
    assert s.source == "unavailable"
    assert s.values == []
    assert s.latest is None


def test_macro_mock_mode_synthetic(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    c = MacroCollector()
    c.cache_clear()
    s = c._collect_one(key="KR_10Y", name="국고채10년", unit="%",
                       fetcher=lambda: ([], []), use_cache=False, source="BOK")
    assert s.source == "MOCK"            # mock 모드 — 합성(회귀)
    assert len(s.values) > 0
    assert s.latest is not None


def test_macro_connection_status(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    c = MacroCollector()
    st = c.connection_status()
    assert st["real_mode"] is True
    assert "bok_configured" in st
    assert "fred_configured" in st
    assert st["mock_allowed"] is False


# ── regime 분석기 하드닝: 실데이터 부족 시 허위 국면 금지 ──
def test_regime_insufficient_data(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    from src.engine.regime_analyzer import RegimeAnalyzer
    c = MacroCollector()
    c.cache_clear()
    state = RegimeAnalyzer(collector=c).analyze()
    assert state.regime == "데이터 부족"     # 운영 무데이터 → 허위 국면(Reflation 등) 금지
    assert state.confidence == 0.0
    assert state.asset_tilts == {}


def test_regime_with_data_classifies(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")   # mock 데이터 → 정상 분류(회귀)
    from src.engine.regime_analyzer import RegimeAnalyzer
    c = MacroCollector()
    c.cache_clear()
    state = RegimeAnalyzer(collector=c).analyze()
    assert state.regime in ("Goldilocks", "Reflation", "Stagflation", "Disinflation")
    assert state.confidence > 0
