"""스크리너 PIT 스냅샷도 ★실측 접수일★ 을 쓴다 (V4 ④)

## 무엇이 문제인가

`PITStore._dart_snapshot` 은 **두 축이 함께 틀려** 있었다:

  ① 날짜 축 — `_period_asof` 가 정적 시차(연간 90일 · 분기 45일)로 "as_of 에
     쓸 수 있는 보고서" 를 골랐다. 늦게 공시된 보고서면 **아직 공표되지 않은
     재무**를 본다.
  ② 값 축 — 고른 보고서를 `history_snapshot` 으로 읽는데, 그 표
     (`financials_history`)는 **정정이 원본을 덮은 뒤**의 값이다. 2020년 시점
     스크리닝에 2025년에 정정된 수치가 들어간다.

V3 의 `history_as_of` 는 두 축을 한 번에 답한다 — 그 시점에 접수된 것 중
기간별 최신 빈티지.

## ★전환이 아니다★

빈티지가 없으면(지금 사용자 DB 가 그렇다) 지금 경로 그대로 내려간다. 라벨은
`_source` 가 든다 — 저장소가 이미 쓰는 어휘(`pit_db` · `pit_dart`)에
`pit_vintage` 를 더할 뿐 새 어휘를 만들지 않는다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

import src.data.dart_history as DH  # noqa: E402
from src.engine.pit_store import PITStore  # noqa: E402

#: `get_financials_asof` 의 셋째 인자는 **현재 재무 dict** 다(가격이 아니다) —
#: mock 폴백이 이걸 시점 변형해 쓴다. `test_pit_dart.py:11` 과 같은 모양.
CUR = {"roe_pct": 12.0, "roa_pct": 6.0, "per": 10.0, "pbr": 1.2,
       "debt_ratio_pct": 80.0, "dividend_yield_pct": 2.0,
       "fcf_억": 100.0, "market_cap_억": 1000.0}


def _row(**kw) -> dict:
    """`history_as_of` 가 돌려주는 행 (원 단위 + 축 + 출처)."""
    base = {"net_income": 1e10, "total_equity": 5e10, "total_assets": 2e11,
            "total_liabilities": 1.5e11, "revenue": 3e11, "operating_profit": 2e10,
            "operating_cf": 1.5e10, "shares_outstanding": 1e8,
            "year": 2024, "reprt": "11011", "month": 12, "seq": 2024 * 12 + 12,
            "rcept_no": "20250314000777", "rcept_dt": "2025-03-14"}
    base.update(kw)
    return base


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr("src.engine.universe_select.mktcap_asof",
                        lambda t, d, engine=None: None)   # 시총 미적재 — 비율만 본다
    return PITStore()


def _no_vintages(monkeypatch):
    monkeypatch.setattr(DH, "history_as_of", lambda t, a, engine=None: ([], None))


# ═══════════════════════════════════════════════════════════════════════════════
# ① 실측 빈티지를 쓴다
# ═══════════════════════════════════════════════════════════════════════════════

def test_a_vintage_snapshot_is_used_when_available(store, monkeypatch):
    """★알맹이★ 실측 접수일 기준 행이 있으면 그것을 쓰고 출처를 밝힌다."""
    monkeypatch.setattr(DH, "history_as_of", lambda t, a, engine=None: ([_row()], None))
    snap = store.get_financials_asof("005930", "2025-04-01", CUR)
    assert snap["_source"] == "pit_vintage", snap
    assert snap["_report"] == "2024/11011", snap
    assert snap["roe_pct"] == pytest.approx(20.0), snap    # 1e10 / 5e10
    assert snap["_annualized"] is False, snap


def test_without_vintages_the_existing_path_is_unchanged(store, monkeypatch):
    """★짝 — 지금 사용자 DB 가 이 상태다★ 빈티지가 없으면 동작이 그대로여야 한다."""
    _no_vintages(monkeypatch)
    monkeypatch.setattr(DH, "history_snapshot",
                        lambda t, y, r, engine=None: {"net_income": 2e10, "total_equity": 5e10,
                                                      "total_assets": 2e11,
                                                      "total_liabilities": 1.5e11})
    snap = store.get_financials_asof("005930", "2025-04-01", CUR)
    assert snap["_source"] == "pit_db", snap
    assert snap["roe_pct"] == pytest.approx(40.0), snap


def test_the_value_axis_is_fixed_too_not_just_the_date(store, monkeypatch):
    """★값 축★ 정정 **전** 시점에는 원본 수치로 비율이 나온다.

    지금까지는 `financials_history` 를 읽어 **정정 후 수치**가 과거 스크리닝에
    들어갔다. 날짜만 고치고 값을 거기서 가져오면 그 룩어헤드가 그대로 남는다.
    """
    ORIGINAL, RESTATED = _row(net_income=1e10), _row(
        net_income=5e9, rcept_no="20250620000999", rcept_dt="2025-06-20")

    def _as_of(t, a, engine=None):
        return ([RESTATED] if a >= "2025-06-20" else [ORIGINAL]), None

    monkeypatch.setattr(DH, "history_as_of", _as_of)
    monkeypatch.setattr(DH, "history_snapshot",
                        lambda t, y, r, engine=None: {"net_income": 5e9, "total_equity": 5e10,
                                                      "total_assets": 2e11,
                                                      "total_liabilities": 1.5e11})
    before = PITStore().get_financials_asof("005930", "2025-05-01", CUR)
    after = PITStore().get_financials_asof("005930", "2025-08-01", CUR)
    assert before["roe_pct"] == pytest.approx(20.0), f"정정 전인데 정정값이 보인다: {before}"
    assert after["roe_pct"] == pytest.approx(10.0), f"정정 후인데 원본이 보인다: {after}"


def test_the_most_recent_knowable_period_wins(store, monkeypatch):
    """여러 기간이 알려져 있으면 **가장 최근 기간**을 쓴다."""
    monkeypatch.setattr(DH, "history_as_of", lambda t, a, engine=None: ([
        _row(year=2023, seq=2023 * 12 + 12, net_income=1e9),
        _row(year=2024, seq=2024 * 12 + 12, net_income=1e10),
    ], None))
    snap = store.get_financials_asof("005930", "2025-04-01", CUR)
    assert snap["_report"] == "2024/11011", snap
    assert snap["roe_pct"] == pytest.approx(20.0), snap


def test_a_quarterly_vintage_is_annualized(store, monkeypatch):
    """분기 누적 손익은 연환산 — 기존 규칙 그대로다(빈티지라고 달라지지 않는다)."""
    monkeypatch.setattr(DH, "history_as_of", lambda t, a, engine=None: ([
        _row(year=2024, reprt="11013", month=3, seq=2024 * 12 + 3, net_income=5e9),
    ], None))
    snap = store.get_financials_asof("005930", "2024-06-01", CUR)
    assert snap["_report"] == "2024/11013", snap
    assert snap["_annualized"] is True, snap
    assert snap["roe_pct"] == pytest.approx(40.0), snap    # 5e9 × 4 / 5e10


# ═══════════════════════════════════════════════════════════════════════════════
# ② ★미상 ≠ 없음★ · 당일 가드
# ═══════════════════════════════════════════════════════════════════════════════

def test_an_unreadable_vintage_table_falls_back_instead_of_failing(store, monkeypatch):
    """못 읽으면 추정 경로로 **내려간다** — 스크리너가 통째로 죽으면 안 된다."""
    monkeypatch.setattr(DH, "history_as_of",
                        lambda t, a, engine=None: (None, "빈티지를 읽지 못했습니다: X"))
    monkeypatch.setattr(DH, "history_snapshot",
                        lambda t, y, r, engine=None: {"net_income": 2e10, "total_equity": 5e10,
                                                      "total_assets": 2e11,
                                                      "total_liabilities": 1.5e11})
    snap = store.get_financials_asof("005930", "2025-04-01", CUR)
    assert snap["_source"] == "pit_db", snap


def test_a_filing_is_not_used_on_the_day_it_was_filed(store, monkeypatch):
    """★당일 가드★ 백테스트 경로와 **같은 상수**를 쓴다 — 두 경로가 갈리면 안 된다."""
    from src.engine.pit_store import FILING_SAME_DAY_GUARD_DAYS
    seen = {}

    def _as_of(t, a, engine=None):
        seen["cutoff"] = a
        return [], None

    monkeypatch.setattr(DH, "history_as_of", _as_of)
    monkeypatch.setattr(DH, "history_snapshot", lambda t, y, r, engine=None: None)
    monkeypatch.setattr("src.data.dart_client.get_corp_code", lambda c: None)
    store.get_financials_asof("005930", "2025-03-14", CUR)
    assert FILING_SAME_DAY_GUARD_DAYS == 1
    assert seen["cutoff"] == "2025-03-13", (
        f"접수 당일까지 조회했다 — 장마감 후 접수분이면 룩어헤드다: {seen}")


def test_a_malformed_as_of_does_not_reach_the_vintage_reader(store, monkeypatch):
    """형식이 틀린 as_of 로 조회하면 문자열 비교가 조용히 전부/전무가 된다."""
    called = {"n": 0}

    def _as_of(t, a, engine=None):
        called["n"] += 1
        return [], None

    monkeypatch.setattr(DH, "history_as_of", _as_of)
    assert store.get_financials_asof("005930", "2025-13-99", CUR) is not None  # mock 폴백
    assert called["n"] == 0, "잘못된 as_of 를 빈티지 리더에 넘겼다"
