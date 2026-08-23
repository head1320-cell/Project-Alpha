"""스크리너 펀더멘털이 financials_history DB를 우선 사용하는지 —
백필된 재무시계열(2,562종목)이 DART 쿼터 무소모로 ffl: 팩터가 되어 유니버스가 확장된다."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.data.fundamentals_store as fsmod  # noqa: E402

# financials_history 스냅샷(원 단위 원천) — history_snapshot 반환 형식
_SNAP = {
    "revenue": 1_000_000_000_000.0, "operating_profit": 100_000_000_000.0,
    "net_income": 80_000_000_000.0, "gross_profit": 300_000_000_000.0,
    "total_assets": 2_000_000_000_000.0, "total_liabilities": 800_000_000_000.0,
    "total_equity": 1_200_000_000_000.0, "current_assets": 800_000_000_000.0,
    "current_liabilities": 400_000_000_000.0, "operating_cf": 110_000_000_000.0,
    "capex": None, "shares_outstanding": 100000, "dps": None,
}


class _NoDart:
    is_configured = False


def _db_only(monkeypatch, snap):
    """DART 미설정 + history_snapshot 스텁 → 순수 DB 경로 강제."""
    monkeypatch.setattr("src.data.dart_history.history_snapshot",
                        lambda t, y, r, engine=None: snap)
    monkeypatch.setattr("src.data.dart_client.get_dart_client", lambda: _NoDart())
    monkeypatch.setattr("src.data.dart_client.get_corp_code", lambda c: None)


def test_fs_from_history_maps_fields():
    fs = fsmod.FundamentalsStore._fs_from_history("005930", 2024)
    # (patch 없이) history_snapshot 실제 호출 — DB 없으면 None (환경 안전)
    assert fs is None or fs.revenue is not None


def test_real_raw_uses_db_when_dart_unconfigured(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")   # 운영: mock 금지
    _db_only(monkeypatch, _SNAP)
    store = fsmod.FundamentalsStore()
    raw = store._real_raw_financials("005930")
    assert raw is not None                       # DB에서 원천 확보(DART 없이)
    assert raw["revenue"] == 10000.0             # 1e12원 → 억(/1e8)
    assert raw["net_income"] == 800.0


def test_build_factors_nonempty_from_db(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    _db_only(monkeypatch, _SNAP)
    store = fsmod.FundamentalsStore()
    factors = store._build_factors("005930")
    assert factors                               # 빈 dict 아님 → cached가 영속 → ffl: 증가
    assert factors.get("roe") is not None        # 실 재무에서 도출(80/1200×100 ≈ 6.67)
    assert abs(factors["net_margin"] - 8.0) < 0.1  # DB 원천값 반영(net 80억/매출 1000억)


def test_no_db_no_dart_returns_none(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    _db_only(monkeypatch, None)                  # history_snapshot None(백필 없음)
    store = fsmod.FundamentalsStore()
    assert store._real_raw_financials("005930") is None   # 폴백 없음 — 기존 정직 동작
    assert store._build_factors("005930") == {}           # 운영 빈 팩터(합성 금지)
