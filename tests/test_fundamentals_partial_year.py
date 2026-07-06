"""펀더멘털 적재 정체(유니버스 ~40% 고착)의 근본 원인 회귀 방지.

증상: financials_history에 재무가 있는데도 ffl:(팩터)이 안 생겨 스크리너 유니버스가
안 늘어남. item:(2805) > ffl:(1996) 비대칭 + 정직 카운터 "저장 1"이 증거 —
_build_factors가 {} 반환 → cached()가 truthy만 영속하므로 ffl: 미기록(item:은 기록됨).

두 근본 원인(둘 다 '날조 없이' 복구 가능):
  1) 최신 연도(예 2025)가 조기 공시로 순이익 결측 → _real_raw_financials가 그 해를
     선택하고 엄격 5필드 게이트에서 탈락. 실제론 직전 완전연도(2024)를 쓰면 됨.
  2) 자본총계(total_equity) 결측(자산·부채는 있음) → 회계 항등식(자본=자산-부채)으로
     정확 복구 가능한데 안 함.
"""
import os
from datetime import datetime

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.data.fundamentals_store import FundamentalsStore  # noqa: E402

_FH_FIELDS = ("revenue", "operating_profit", "net_income", "gross_profit",
              "total_assets", "total_liabilities", "total_equity",
              "current_assets", "current_liabilities", "operating_cf", "capex",
              "shares_outstanding", "dps")


def _snap(**kw) -> dict:
    base = dict.fromkeys(_FH_FIELDS)
    base.update(kw)
    return base


def _install(monkeypatch, by_year: dict):
    """financials_history(history_snapshot)를 by_year로 대체 + 라이브 DART 폴백 차단(DB만)."""
    import src.data.dart_client as dc
    import src.data.dart_history as dh
    monkeypatch.setattr(dh, "history_snapshot",
                        lambda t, y, r, engine=None: by_year.get(str(y)))

    class _Dart:            # 미설정 — 라이브 DART 폴백 없음(DB 경로만 검증)
        is_configured = False

        def get_dividend_info(self, *a, **k):
            return {}
    monkeypatch.setattr(dc, "get_dart_client", lambda: _Dart())
    monkeypatch.setattr(dc, "get_corp_code", lambda t: None)


def test_picks_complete_earlier_year_when_latest_incomplete(monkeypatch):
    """최신 연도가 순이익 결측(조기공시)이면 직전 완전연도를 선택해 팩터를 만든다."""
    cy = datetime.now().year - 1
    by_year = {
        # 최신 연도: 매출·자산만(순이익/영업이익 결측) — 조기·부분 공시
        str(cy): _snap(revenue=1000e8, total_assets=2000e8),
        # 직전 연도: 완전
        str(cy - 1): _snap(revenue=900e8, operating_profit=120e8, net_income=90e8,
                           total_assets=1900e8, total_liabilities=800e8, total_equity=1100e8,
                           current_assets=700e8, current_liabilities=400e8, operating_cf=100e8),
    }
    _install(monkeypatch, by_year)
    st = FundamentalsStore()
    raw = st._real_raw_financials("900001")
    assert raw is not None, "직전 완전연도를 못 찾고 최신 부분연도에서 탈락(=유니버스 정체 버그)"
    fac = st._build_factors("900001")
    assert fac, "팩터가 비어있음 → ffl: 미영속 → 유니버스 안 늘어남"
    assert fac.get("roe") is not None and fac.get("_source") == "dart_real"


def test_equity_derived_from_accounting_identity(monkeypatch):
    """자본총계 결측이어도 자산-부채로 정확 복구 → 팩터 생성(날조 아님)."""
    cy = datetime.now().year - 1
    by_year = {
        str(cy): _snap(revenue=900e8, operating_profit=120e8, net_income=90e8,
                       total_assets=1900e8, total_liabilities=800e8,  # total_equity 결측
                       current_assets=700e8, current_liabilities=400e8, operating_cf=100e8),
    }
    _install(monkeypatch, by_year)
    st = FundamentalsStore()
    fs = st._fs_from_history("900002", cy)
    assert fs is not None and fs.total_equity == 1900e8 - 800e8, "회계 항등식 자본 복구 실패"
    raw = st._real_raw_financials("900002")
    assert raw is not None
    fac = st._build_factors("900002")
    assert fac and fac.get("pbr") is not None


def test_db_served_path_makes_no_network_call(monkeypatch):
    """DB가 서빙하면 corp_code 다운로드·라이브 배당 호출 0 — 재배포 직후 적재 정체 방지.

    배당은 DB 적재 dps로 산출(라이브 get_dividend_info 미호출)."""
    cy = datetime.now().year - 1
    by_year = {
        str(cy): _snap(revenue=900e8, operating_profit=120e8, net_income=90e8,
                       total_assets=1900e8, total_liabilities=800e8, total_equity=1100e8,
                       current_assets=700e8, current_liabilities=400e8, operating_cf=100e8,
                       shares_outstanding=5000, dps=300.0),  # dps=원/주, shares=만주
        str(cy - 1): _snap(revenue=850e8, operating_profit=110e8, net_income=85e8,
                           total_assets=1850e8, total_liabilities=780e8, total_equity=1070e8),
    }
    import src.data.dart_client as dc
    import src.data.dart_history as dh
    monkeypatch.setattr(dh, "history_snapshot",
                        lambda t, y, r, engine=None: by_year.get(str(y)))

    def _boom_corp(*a, **k):
        raise AssertionError("corp_code 다운로드 호출됨 — DB 서빙 경로에서 네트워크 발생")

    class _Dart:
        is_configured = True        # 설정돼 있어도 DB가 서빙하면 corp_code 불필요

        def get_dividend_info(self, *a, **k):
            raise AssertionError("라이브 배당 호출됨 — DB dps로 대체됐어야 함")
    monkeypatch.setattr(dc, "get_corp_code", _boom_corp)
    monkeypatch.setattr(dc, "get_dart_client", lambda: _Dart())

    st = FundamentalsStore()
    raw = st._real_raw_financials("900004")     # BOOM 없이 통과해야 함
    assert raw is not None
    # 배당(억) = dps 300 × shares 5000(만주) / 1e4 = 150억
    assert abs(raw["dividend"] - 300.0 * 5000 / 1e4) < 1e-6
    fac = st._build_factors("900004")
    assert fac and fac.get("dividend_yield") is not None


def test_no_usable_year_returns_none_honest(monkeypatch):
    """모든 연도가 이익·자본 결측이면 정직하게 None(합성 금지) — 경계 고정."""
    cy = datetime.now().year - 1
    by_year = {str(cy - i): _snap(revenue=900e8, total_assets=1900e8) for i in range(8)}
    _install(monkeypatch, by_year)
    st = FundamentalsStore()
    assert st._real_raw_financials("900003") is None
