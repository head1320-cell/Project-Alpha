"""매크로 민감도 배선 — 통계 채널 · 스냅샷 컬럼 · 라이브 엔드포인트 (P2-4 커밋 ③)

★이 파일이 새로 거는 것★
  1. 통계 채널은 **유의한 것만 고르지 않는다** — 코어 5계열을 전부 보고한다.
  2. 구조적 블록과 통계 블록이 **섞이지 않는다** — 인식론이 다른 두 물건이다.
  3. 얇은 표본은 숫자가 아니라 사유다.

그리고 이 세션에서 결함 둘을 놓친 교훈대로, 통계 채널은 **실제 수집기와 실제
로더**를 태워 확인한다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.company_snapshots as cs  # noqa: E402
import src.engine.company_snapshot_builder as bld  # noqa: E402
from src.engine.valuation.macro_sensitivity import (  # noqa: E402
    CORE_SERIES,
    MIN_MONTHS,
    statistical_sensitivity,
)

CODE = "005930"
PRICE = 71000.0
MS = f"/api/v1/company/{CODE}/macro-sensitivity"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


@pytest.fixture
def mem_cs(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(cs, "_engine", lambda: eng)
    monkeypatch.setattr(cs, "_inited", False)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def live_stat():
    """★실제 수집기 + 실제 로더★ 합성 입력으로 결함 둘을 놓친 뒤의 규칙이다."""
    out = statistical_sensitivity(CODE)
    if not out.get("available"):
        pytest.skip(f"이 환경에서 통계 채널을 낼 수 없다: {out.get('reason')}")
    return out


# ── 1. ★유의한 것만 고르지 않는다★ ─────────────────────────────────────────
def test_every_core_series_is_reported_not_just_the_significant_ones(live_stat):
    """61계열을 훑어 t값 큰 것만 내면 다중검정 보정 없는 데이터 마이닝이다."""
    reported = [r["series"] for r in live_stat["rows"]]
    assert reported == list(CORE_SERIES), reported
    assert live_stat["multiple_testing"]["n_tested"] == len(CORE_SERIES)
    assert "데이터 마이닝" in live_stat["multiple_testing"]["note"]


def test_the_core_series_are_fixed_in_code_not_discovered():
    """코어를 코드에 못박는 것이 요점 — 데이터에서 고르면 그것이 마이닝이다."""
    assert isinstance(CORE_SERIES, tuple)
    assert 3 <= len(CORE_SERIES) <= 7, "차원의 저주 — 코어는 소수여야 한다"


def test_each_beta_carries_its_uncertainty(live_stat):
    """★베타만 내면 '얼마나 모르는지' 가 사라진다★"""
    for r in live_stat["rows"]:
        if not r.get("available"):
            continue
        assert r["n_obs"] >= MIN_MONTHS
        assert r["std_error"] is not None
        assert r["t_stat"] is not None
        assert r["span"][0] < r["span"][1]


def test_correlation_is_labelled_as_not_causation(live_stat):
    assert "인과가 아닙니다" in live_stat["causality"]


def test_a_thin_overlap_is_a_reason_not_a_beta():
    """★얇은 표본의 베타는 부호조차 믿을 수 없다★ 하한을 올려 그 경로를 연다."""
    out = statistical_sensitivity(CODE, min_months=10_000)
    assert out["available"] is False
    assert out["reason"]
    for r in out["rows"]:
        assert r["available"] is False
        assert "beta" not in r
        assert r["reason"]


def test_a_missing_series_says_so_rather_than_skipping(monkeypatch):
    out = statistical_sensitivity(CODE, core=("KR_10Y", "존재하지않는계열"))
    rows = {r["series"]: r for r in out["rows"]}
    assert rows["존재하지않는계열"]["available"] is False
    assert "수집기에 없습니다" in rows["존재하지않는계열"]["reason"]


def test_a_dead_collector_answers_with_a_reason(monkeypatch):
    class _Boom:
        def __init__(self): raise RuntimeError("수집 불가")
    monkeypatch.setattr("src.engine.regime_analyzer.RegimeAnalyzer", _Boom)
    out = statistical_sensitivity(CODE)
    assert out["available"] is False and out["reason"]


# ── 2. ★두 블록이 섞이지 않는다★ ───────────────────────────────────────────
def test_the_route_keeps_structural_and_statistical_apart(client):
    """인식론이 다르다 — 항등식과 표본 추정을 한 표에 놓으면 같게 읽힌다."""
    r = client.get(MS, params={"price": PRICE})
    assert r.status_code == 200, r.text
    b = r.json()

    assert b["method"] == "structural_exact"
    assert b["available"] is True, b["reason"]
    # 구조적 행에는 통계 필드가 없다.
    for row in b["rows"]:
        assert row["method"] == "structural_exact"
        assert "std_error" not in row and "t_stat" not in row
    # 통계 블록은 따로 있고 자기 method 를 단다.
    assert b["statistical"]["method"] == "ols_contemporaneous_monthly"
    assert "causality" in b["statistical"]


def test_the_statistical_block_can_be_turned_off(client):
    b = client.get(MS, params={"price": PRICE, "statistical": False}).json()
    assert "statistical" not in b
    assert b["rows"], "구조적 블록은 그대로 나온다"


def test_the_route_reports_the_impossible_channels(client):
    """★빈칸이 아니라 사유★ GDP→EPS · USD→EPS · Oil→EBIT."""
    b = client.get(MS, params={"price": PRICE, "statistical": False}).json()
    un = {u["shock"] for u in b["unavailable"]}
    assert un == {"GDP −2σ", "USD +10%", "Oil +30%"}
    for u in b["unavailable"]:
        assert u["available"] is False and u["reason"]


def test_the_route_is_registered_alongside_the_existing_five(client):
    paths = {r.path for r in client.app.routes}
    assert "/api/v1/company/{code}/macro-sensitivity" in paths
    for p in ("/api/v1/company/{code}/valuation-sandbox",
              "/api/v1/company/{code}/financial-deep",
              "/api/v1/company/{code}/risk-deep",
              "/api/v1/company/{code}/reverse-dcf",
              "/api/v1/company/{code}/valuation-distribution"):
        assert p in paths


def test_a_bad_price_is_rejected_before_any_work(client):
    assert client.get(MS, params={"price": -1}).status_code == 422


# ── 3. 스냅샷 컬럼 ─────────────────────────────────────────────────────────
def _snap(**kw) -> dict:
    sid = bld.build_and_store(CODE, price=PRICE, **kw)
    assert sid
    out = cs.get_snapshot(sid)
    assert out is not None
    return out


def test_the_snapshot_carries_both_blocks(mem_cs):
    m = _snap()["macro_sensitivity"]
    assert m is not None and m["available"] is True, m.get("reason")
    assert m["structural"]["method"] == "structural_exact"
    assert "statistical" in m
    # 스냅샷 안에서도 둘이 섞이지 않는다.
    assert "rows" in m["structural"] and "rows" in m["statistical"]
    assert "다른 종류의 숫자" in m["note"]


def test_the_builder_calls_the_engine_rather_than_copying_it(mem_cs, monkeypatch):
    monkeypatch.setattr(
        "src.engine.valuation.macro_sensitivity.macro_sensitivity",
        lambda fs, params, **kw: {"available": True, "marker": "재정의됨"})
    assert _snap()["macro_sensitivity"]["structural"] == {
        "available": True, "marker": "재정의됨"}


def test_a_dead_engine_does_not_kill_the_snapshot(mem_cs, monkeypatch):
    def _boom(fs, params, **kw):
        raise RuntimeError("민감도 실패")
    monkeypatch.setattr(
        "src.engine.valuation.macro_sensitivity.macro_sensitivity", _boom)

    snap = _snap()
    assert snap["macro_sensitivity"]["available"] is False
    assert "RuntimeError" in snap["macro_sensitivity"]["reason"]
    # 나머지는 굳는다.
    assert snap["valuation"]["available"] is True
    assert snap["valuation_dist"]["available"] is True


def test_no_price_means_no_section_rather_than_a_fake_one(mem_cs, monkeypatch):
    monkeypatch.setattr(bld, "_resolve_price", lambda code, price: (None, "unavailable"))
    sid = bld.build_and_store(CODE)
    m = cs.get_snapshot(sid)["macro_sensitivity"]
    assert m["available"] is False
    assert "현재가" in m["reason"]


def test_the_late_column_registry_carries_all_three(mem_cs):
    """★P2-3 이 일반화해 둔 자리에 한 줄만 더한다★"""
    assert {"implied", "valuation_dist", "macro_sensitivity"} <= set(cs._LATE_COLUMNS)
    assert set(cs._late_ok) == set(cs._LATE_COLUMNS)


def test_a_missing_column_hides_only_its_own_section(mem_cs, monkeypatch):
    sid = bld.build_and_store(CODE, price=PRICE)
    assert sid
    monkeypatch.setattr(cs, "_late_ok",
                        {**cs._late_ok, "macro_sensitivity": False})
    got = cs.get_snapshot(sid)
    assert got is not None
    assert "macro_sensitivity" not in got
    # 이웃 후행 컬럼은 남는다 — 플래그가 독립이라는 증거.
    assert "implied" in got and "valuation_dist" in got
