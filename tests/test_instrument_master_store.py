"""마스터 DB 사본 — ★파일이 진실이고 DB 는 사본이다★
==============================================================================
감사: `docs/specs/2026-08-26-data-extraction-audit.md` §3.3

## 이 파일이 막는 것

`kis_master_parser` 의 산출물이 `master_flags_cache.json` **파일 하나**뿐이라,
그 파일이 없으면 셋이 **함께** 멈췄다:

    krx_mdc 투자자 플로우 백필         ← ISIN 이 조회 키
    constrained_opt.sector_groups_for  ← {} 를 돌려준다
    exposure_taxonomy 규칙 배정        ← no_master_flags

DB 사본이 그 단일 장애점을 없앤다. ★그러나 순서를 뒤집으면 새 결함이 생긴다★ —
DB 를 먼저 읽으면 스테일 DB 가 방금 받은 새 파일을 덮는다. 그래서 **파일 → DB**
순이고, 파일이 있으면 동작이 이전과 **완전히 같아야** 한다.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

import src.data.instrument_master_store as ims  # noqa: E402
import src.data.stock_master as sm  # noqa: E402

_FLAGS = {
    "005930": {"name": "삼성전자", "market": "KOSPI", "isin": "KR7005930003",
               "group_code": "ST", "is_etf": False, "is_kospi200": True,
               "is_kosdaq150": False, "cap_size": "1", "sector_code": "13",
               "sector_mid": "1301", "sector_sub": "130101", "is_managed": False,
               "alert_code": "00", "is_halted": False, "is_clearing": False,
               "is_caution": False, "market_cap_억": 4_500_000},
    "069500": {"name": "KODEX 200", "market": "KOSPI", "isin": "KR7069500007",
               "group_code": "EF", "is_etf": True, "is_kospi200": False,
               "is_kosdaq150": False, "cap_size": "", "sector_code": "",
               "sector_mid": "", "sector_sub": "", "is_managed": False,
               "alert_code": "00", "is_halted": False, "is_clearing": False,
               "is_caution": False, "market_cap_억": 60_000},
}


@pytest.fixture
def eng():
    return create_engine("sqlite://", connect_args={"check_same_thread": False})


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, eng):
    """★프로세스 공용 DB 를 절대 건드리지 않는다★

    `src.database.get_engine()` 는 `sqlite:///risk_system.db` 라는 **작업 디렉터리
    파일**이다. 여기에 행을 남기면 다른 테스트 파일이 "마스터가 없으면 비어 있다" 를
    검사할 때 그 행을 보게 된다 — 실제로 3개가 그렇게 깨졌다.

    모듈 전역 캐시도 비운다 — 안 하면 실행 순서에 따라 결과가 달라진다.
    """
    monkeypatch.setattr(ims, "_engine", lambda engine=None: eng)
    sm._MASTER_FLAGS = None
    yield
    sm._MASTER_FLAGS = None


# ══════════════════════════════════════════════════════════════════════════
# 1) DB 왕복 — 파일 없이도 살아난다
# ══════════════════════════════════════════════════════════════════════════
def test_round_trip_preserves_every_field(eng):
    assert ims.save(_FLAGS, engine=eng) == 2
    got = ims.load(engine=eng)
    assert set(got) == set(_FLAGS)
    a = got["005930"]
    assert a["isin"] == "KR7005930003" and a["name"] == "삼성전자"
    assert a["is_kospi200"] is True and a["is_etf"] is False
    assert a["sector_sub"] == "130101" and a["market_cap_억"] == 4_500_000


def test_booleans_survive_sqlite_round_trip(eng):
    """sqlite 는 0/1 로 돌려준다 — 소비자가 `is True` 로 보면 깨진다."""
    ims.save(_FLAGS, engine=eng)
    got = ims.load(engine=eng)
    assert got["069500"]["is_etf"] is True
    assert got["005930"]["is_etf"] is False


def test_load_returns_the_same_shape_as_the_file_cache(eng):
    """★모양이 다르면 소비자가 두 갈래 코드를 갖는다★ — 그중 하나만 고쳐지는 날이 온다."""
    ims.save(_FLAGS, engine=eng)
    got = ims.load(engine=eng)
    assert set(got["005930"]) >= set(_FLAGS["005930"]) - {"is_clearing", "is_caution"}


def test_upsert_is_idempotent(eng):
    ims.save(_FLAGS, engine=eng)
    ims.save(_FLAGS, engine=eng)
    with eng.connect() as c:
        n = c.execute(text(f"SELECT COUNT(*) FROM {ims.TABLE}")).scalar()
    assert n == 2


def test_save_records_provenance_and_as_of(eng):
    ims.save(_FLAGS, engine=eng, as_of="2026-08-26")
    with eng.connect() as c:
        row = c.execute(text(
            f"SELECT as_of, source FROM {ims.TABLE} WHERE ticker='005930'")).one()
    assert row[0] == "2026-08-26" and row[1] == ims.SOURCE_KIS_MASTER


# ══════════════════════════════════════════════════════════════════════════
# 2) ★파일이 이긴다★
# ══════════════════════════════════════════════════════════════════════════
def test_file_wins_over_db(tmp_path, eng, monkeypatch):
    """★기존 동작 불변★ 파일이 있으면 DB 는 쳐다보지도 않는다.

    반대로 하면 스테일 DB 가 방금 받은 새 파일을 덮는다.
    """
    path = tmp_path / "master_flags_cache.json"
    path.write_text(json.dumps(
        {"stocks": {"111111": {"name": "파일에서", "isin": "KRFILE0000001"}}}),
        encoding="utf-8")
    monkeypatch.setattr(sm, "_master_flags_path", lambda: str(path))
    monkeypatch.setattr(ims, "_engine", lambda engine=None: eng)
    ims.save(_FLAGS, engine=eng)          # DB 에는 전혀 다른 내용

    got = sm.load_master_flags()
    assert set(got) == {"111111"}, "DB 가 파일을 덮었다"


def test_db_is_used_only_when_the_file_is_absent(tmp_path, eng, monkeypatch):
    """★짝★ 파일이 없으면 DB 가 살려낸다 — 아니면 위 테스트가 'DB 무시' 로도 통과한다."""
    monkeypatch.setattr(sm, "_master_flags_path",
                        lambda: str(tmp_path / "does_not_exist.json"))
    monkeypatch.setattr(ims, "_engine", lambda engine=None: eng)
    ims.save(_FLAGS, engine=eng)

    got = sm.load_master_flags()
    assert set(got) == set(_FLAGS)
    assert got["005930"]["isin"] == "KR7005930003"


def test_an_empty_file_falls_through_to_the_db(tmp_path, eng, monkeypatch):
    """빈 파일은 '파일이 있다' 가 아니다 — 내용이 없으면 DB 를 본다."""
    path = tmp_path / "master_flags_cache.json"
    path.write_text(json.dumps({"stocks": {}}), encoding="utf-8")
    monkeypatch.setattr(sm, "_master_flags_path", lambda: str(path))
    monkeypatch.setattr(ims, "_engine", lambda engine=None: eng)
    ims.save(_FLAGS, engine=eng)
    assert set(sm.load_master_flags()) == set(_FLAGS)


# ══════════════════════════════════════════════════════════════════════════
# 3) ★DB 실패가 마스터 갱신을 실패로 만들지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_save_without_a_database_returns_zero_instead_of_raising(monkeypatch):
    monkeypatch.setattr(ims, "_engine", lambda engine=None: None)
    assert ims.save(_FLAGS) == 0


def test_save_master_flags_has_no_database_side_effect(tmp_path, monkeypatch):
    """★저장 원시함수는 DB 를 건드리지 않는다★

    처음에는 `save_master_flags` 안에서 DB 미러링을 했다. 그러면 픽스처를 깔려고
    이 함수를 부르는 **다른 테스트 파일**이 프로세스 공용 DB 에 행을 남기고,
    "마스터가 없으면 비어 있다" 를 검사하는 기존 테스트 3개가 깨진다(실측).
    미러링은 `kis_master_parser` 의 적재 파이프라인이 한다.
    """
    path = tmp_path / "master_flags_cache.json"
    monkeypatch.setattr(sm, "_master_flags_path", lambda: str(path))
    called = []
    monkeypatch.setattr(ims, "save", lambda *a, **k: called.append(1))

    n = sm.save_master_flags([
        {"ticker": "005930", "name": "삼성전자", "market": "KOSPI",
         "isin": "KR7005930003"}])
    assert n == 1 and path.exists()
    assert called == [], "저장 원시함수가 DB 를 건드렸다"


def test_load_without_a_database_is_empty_not_an_error(monkeypatch):
    monkeypatch.setattr(ims, "_engine", lambda engine=None: None)
    assert ims.load() == {}


# ══════════════════════════════════════════════════════════════════════════
# 4) ★ISIN 을 합성하지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_isin_of_returns_the_real_value(tmp_path, eng, monkeypatch):
    monkeypatch.setattr(sm, "_master_flags_path",
                        lambda: str(tmp_path / "absent.json"))
    monkeypatch.setattr(ims, "_engine", lambda engine=None: eng)
    ims.save(_FLAGS, engine=eng)
    assert ims.isin_of("005930") == "KR7005930003"


def test_isin_of_returns_none_rather_than_a_synthetic_key(tmp_path, eng, monkeypatch):
    """★가짜 ISIN 을 만들면 krx_mdc 조회가 조용히 빈 결과를 낸다★"""
    monkeypatch.setattr(sm, "_master_flags_path",
                        lambda: str(tmp_path / "absent.json"))
    monkeypatch.setattr(ims, "_engine", lambda engine=None: eng)
    ims.save({"999999": {"name": "ISIN 없음", "isin": ""}}, engine=eng)
    assert ims.isin_of("999999") is None
    assert ims.isin_of("NOT_A_TICKER") is None
