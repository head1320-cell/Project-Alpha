"""현재 국면 → RegimeSnapshot 빌더 (AAS Phase 3a).

라이브 매크로 엔진(get_regime_state)의 판정을 불변 스냅샷으로 굳힌다.

★정직성이 이 테스트의 주제다★
대시보드 수집기(MacroCollector)는 아직 빈티지를 모른다(그건 Phase 7b). 따라서 여기서 만든
관측치는 vintage_id 가 비어 있고, 공표시각을 알 수 없으므로 data_status=partial 이다.
그 결과 스냅샷 전체가 **forward_only** 로 떨어져 과거 시뮬레이션에서 구조적으로 차단된다.

관측일을 공표시각인 척 채워 넣으면 스냅샷이 backtest_eligible 로 보이게 되는데,
그것이 바로 이 프로젝트가 막으려는 조용한 날조다. 아래 테스트가 그것을 고정한다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.regime_snapshots as rs  # noqa: E402
from src.engine import regime_snapshot_builder as bld  # noqa: E402


class _Series:
    """MacroSeries 의 최소 스텁 (빌더가 읽는 필드만)."""
    def __init__(self, indicator, source, timestamps, values, last_update=None):
        self.indicator = indicator
        self.source = source
        self.timestamps = timestamps
        self.values = values
        self.last_update = last_update
        self.name = indicator
        self.unit = "%"


class _MacroSnap:
    def __init__(self, series):
        self.timestamp = "2026-07-27T00:00:00"
        self.series = series


class _State:
    regime = "Goldilocks"
    growth_axis = 0.82
    inflation_axis = -0.31
    confidence = 0.64
    stress_score = 41.5
    regime_probs = {"Goldilocks": 0.55, "Reflation": 0.25, "Disinflation": 0.20}
    description = "성장 우위 · 물가 둔화"
    recommended_mode = "NORMAL"
    timestamp = "2026-07-27T00:00:00"
    market = "kr"


FRED_SERIES = {
    "FRED_T10Y": _Series("FRED_T10Y", "FRED", ["2026-06-30", "2026-07-25"], [4.1, 4.25], "2026-07-26"),
    "KR_BASE_RATE": _Series("KR_BASE_RATE", "BOK", ["2026-07-01"], [2.75], "2026-07-20"),
}


@pytest.fixture
def mem(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(rs, "_engine", lambda: eng)
    monkeypatch.setattr(rs, "_inited", False)
    yield eng
    eng.dispose()


@pytest.fixture
def stub_engine(monkeypatch):
    """국면 엔진 + 수집기를 스텁 (네트워크 0)."""
    monkeypatch.setattr(bld, "_collect", lambda market: (_State(), _MacroSnap(dict(FRED_SERIES))))


# ─── 1. 관측치 인코딩 — 여기서 정직성이 결정된다 ───────────────────────────────
def test_observations_have_no_vintage_and_are_partial():
    obs = bld.observations_from_series(_MacroSnap(dict(FRED_SERIES)))
    assert obs, "관측치가 비면 뒤 단언이 공허하다"
    for o in obs:
        assert o.vintage_id == "", "수집기는 빈티지를 모른다 — 있는 척하면 안 된다"
        assert o.data_status.value == "partial", (
            "공표시각을 모르므로 real 이 아니라 partial 이다"
        )


def test_mock_source_is_labelled_mock():
    snap = _MacroSnap({"X": _Series("X", "MOCK", ["2026-07-01"], [1.0])})
    o = bld.observations_from_series(snap)[0]
    assert o.data_status.value == "mock"


def test_release_timestamp_is_not_faked_from_observation_date():
    """관측일을 공표시각으로 베끼면 안 된다 — 실제 공표는 그 이후다."""
    o = next(x for x in bld.observations_from_series(_MacroSnap(dict(FRED_SERIES)))
             if x.series_id == "FRED_T10Y")
    assert o.observation_period == "2026-07-25"
    assert o.release_timestamp == "2026-07-26", "수집기의 last_update 를 써야 한다"
    assert o.release_timestamp != o.observation_period


def test_series_without_values_is_skipped():
    snap = _MacroSnap({"EMPTY": _Series("EMPTY", "FRED", [], [])})
    assert bld.observations_from_series(snap) == [], "빈 시리즈를 0 으로 채우면 안 된다"


# ─── 2. 스냅샷 전체가 forward_only 로 떨어지는가 ──────────────────────────────
def test_snapshot_is_forward_only_and_partial(mem, stub_engine):
    sid = bld.build_and_store(market="kr")
    snap = rs.get_snapshot(sid)
    assert snap["research_usage"] == "forward_only", (
        "빈티지 없는 관측치로 만든 스냅샷이 backtest_eligible 로 보이면 안 된다"
    )
    assert snap["data_status"] == "partial"


# ─── 3. RegimeState 필드가 그대로 옮겨지는가 ──────────────────────────────────
def test_state_fields_are_mapped(mem, stub_engine):
    snap = rs.get_snapshot(bld.build_and_store(market="kr"))
    assert snap["growth_axis"] == pytest.approx(0.82)
    assert snap["inflation_axis"] == pytest.approx(-0.31)
    assert snap["stress_score"] == pytest.approx(41.5)
    assert snap["confidence"] == pytest.approx(0.64)
    assert snap["phase_probabilities"]["Goldilocks"] == pytest.approx(0.55)
    assert "Goldilocks" in snap["explanation"]
    assert "NORMAL" in snap["explanation"], "권고 모드가 설명에 남아야 매핑 미리보기가 가능하다"


def test_as_of_comes_from_the_state_not_wall_clock(mem, stub_engine):
    snap = rs.get_snapshot(bld.build_and_store(market="kr"))
    assert snap["as_of"].startswith("2026-07-27"), "판정 시각을 as_of 로 써야 한다"


# ─── 4. market 파라미터가 전달되는가 ──────────────────────────────────────────
def test_market_is_passed_through(monkeypatch, mem):
    seen = {}

    def spy(market):
        seen["market"] = market
        return _State(), _MacroSnap(dict(FRED_SERIES))

    monkeypatch.setattr(bld, "_collect", spy)
    bld.build_and_store(market="us")
    assert seen["market"] == "us"


# ─── 5. 정직한 실패 ───────────────────────────────────────────────────────────
def test_db_unavailable_returns_none(monkeypatch, stub_engine):
    def boom():
        raise RuntimeError("no db")
    monkeypatch.setattr(rs, "_engine", boom)
    monkeypatch.setattr(rs, "_inited", False)
    assert bld.build_and_store(market="kr") is None


def test_engine_failure_propagates_not_silently_zero(monkeypatch, mem):
    def boom(market):
        raise RuntimeError("collector down")
    monkeypatch.setattr(bld, "_collect", boom)
    with pytest.raises(RuntimeError):
        bld.build_and_store(market="kr")
