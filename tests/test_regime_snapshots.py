"""RegimeSnapshot — 버전·ID 로 참조하는 불변 매크로 스냅샷 (AAS Phase 2).

이 객체가 메우는 구멍: 지금까지 매크로 → AAS 전달은 AllocationProvider.loadedStrategy,
즉 **ID·버전·시각이 없는 휘발성 브라우저 메모리 객체**였다. 새로고침하면 사라지고,
과거 리서치를 오늘의 국면 분류로 채점하는 것을 막을 방법이 없었다.

관례: in-memory SQLite + monkeypatch (실DB·실네트워크 0) — test_research_runs.py 와 동일.

핵심 주장:
  create/get   — snapshot_id 발급, 관측치 신원·축·확률·재현 메타 왕복 보존
  불변성        — 갱신 경로가 없다(같은 as_of 도 새 스냅샷이 된다)
  PIT          — as_of 이후 공표 관측치는 스냅샷에 들어가지 못한다
  정직성        — DB 미가용 시 None (가짜 스냅샷 반환 금지)
  usage        — 빈티지 없는 시리즈가 섞이면 스냅샷 전체가 backtest 부적격
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.regime_snapshots as rs  # noqa: E402
from src.data.pit_macro import DataStatus, MacroObservation, ResearchUsage  # noqa: E402


def _obs(series_id: str, period: str, release: str, value: float) -> MacroObservation:
    return MacroObservation(
        series_id=series_id, observation_period=period, release_timestamp=release,
        vintage_id=f"{release}..9999-12-31", retrieved_at="2026-07-27T00:00:00Z",
        value=value, data_status=DataStatus.REAL,
    )


AS_OF = "2020-05-01"
OBS_OK = [
    _obs("DGS10", "2020-04-30", "2020-04-30", 0.64),
    _obs("T10Y2Y", "2020-04-30", "2020-04-30", 0.42),
]


@pytest.fixture
def mem_rs(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(rs, "_engine", lambda: eng)
    monkeypatch.setattr(rs, "_inited", False)
    yield eng
    eng.dispose()


# ─── 1. 왕복 보존 ─────────────────────────────────────────────────────────────
def test_create_and_get_roundtrip(mem_rs):
    sid = rs.create_snapshot(
        as_of=AS_OF, observations=OBS_OK,
        growth_axis=-1.2, inflation_axis=-0.4,
        phase_probabilities={"Goldilocks": 0.1, "Deflation": 0.7, "Reflation": 0.2},
        stress_score=78.5, confidence=0.55,
        explanation="성장·물가 동반 둔화 — 디플레 국면 우위",
    )
    assert sid and sid.startswith("rgs_")

    snap = rs.get_snapshot(sid)
    assert snap is not None
    assert snap["as_of"] == AS_OF
    assert snap["growth_axis"] == pytest.approx(-1.2)
    assert snap["phase_probabilities"]["Deflation"] == pytest.approx(0.7)
    assert snap["stress_score"] == pytest.approx(78.5)
    assert snap["explanation"].startswith("성장")


def test_observations_keep_full_identity(mem_rs):
    """관측치를 맨 숫자로 눌러 담지 않는다 — 공표시각·빈티지가 살아 있어야 재현이 된다."""
    sid = rs.create_snapshot(as_of=AS_OF, observations=OBS_OK, growth_axis=0.0,
                             inflation_axis=0.0, phase_probabilities={}, stress_score=0.0,
                             confidence=0.0)
    got = rs.get_snapshot(sid)["observations"]
    assert len(got) == 2
    o = next(x for x in got if x["series_id"] == "DGS10")
    for field in ("observation_period", "release_timestamp", "vintage_id", "retrieved_at"):
        assert o.get(field), f"{field} 가 유실됐다"
    assert o["value"] == pytest.approx(0.64)


def test_reproducibility_metadata_is_stamped(mem_rs):
    sid = rs.create_snapshot(as_of=AS_OF, observations=OBS_OK, growth_axis=0.0,
                             inflation_axis=0.0, phase_probabilities={}, stress_score=0.0,
                             confidence=0.0)
    snap = rs.get_snapshot(sid)
    for field in ("model_version", "engine_version", "code_version", "created_at", "data_status"):
        assert snap.get(field) is not None, f"{field} 가 비어 있다"


# ─── 2. PIT — as_of 이후 공표분은 못 들어간다 ─────────────────────────────────
def test_observation_released_after_as_of_is_rejected(mem_rs):
    late = _obs("GDPC1", "2020-01-01", "2020-06-25", -5.1)   # as_of 이후 공표
    with pytest.raises(rs.LookAheadError) as ei:
        rs.create_snapshot(as_of=AS_OF, observations=[*OBS_OK, late],
                           growth_axis=0.0, inflation_axis=0.0, phase_probabilities={},
                           stress_score=0.0, confidence=0.0)
    msg = str(ei.value)
    assert "GDPC1" in msg, "어떤 시리즈가 문제인지 이름이 나와야 한다"
    assert "2020-06-25" in msg, "문제의 공표시각이 나와야 한다"


def test_rejection_happens_before_persistence(mem_rs):
    late = _obs("GDPC1", "2020-01-01", "2020-06-25", -5.1)
    with pytest.raises(rs.LookAheadError):
        rs.create_snapshot(as_of=AS_OF, observations=[late], growth_axis=0.0,
                           inflation_axis=0.0, phase_probabilities={}, stress_score=0.0,
                           confidence=0.0)
    assert rs.list_snapshots() == [], "거부된 스냅샷이 저장돼 있으면 안 된다"


# ─── 3. 불변성 ────────────────────────────────────────────────────────────────
def test_no_update_path_exists():
    """스냅샷은 불변이다. update/patch 류 공개 함수가 있으면 설계가 깨진 것."""
    forbidden = [n for n in dir(rs)
                 if not n.startswith("_") and any(k in n.lower() for k in ("update", "patch", "edit", "modify"))]
    assert forbidden == [], f"불변이어야 하는데 변경 경로가 있다: {forbidden}"


def test_same_as_of_creates_a_distinct_snapshot(mem_rs):
    a = rs.create_snapshot(as_of=AS_OF, observations=OBS_OK, growth_axis=0.0,
                           inflation_axis=0.0, phase_probabilities={}, stress_score=1.0,
                           confidence=0.0)
    b = rs.create_snapshot(as_of=AS_OF, observations=OBS_OK, growth_axis=0.0,
                           inflation_axis=0.0, phase_probabilities={}, stress_score=2.0,
                           confidence=0.0)
    assert a != b, "같은 as_of 라도 덮어쓰지 않고 새 스냅샷이어야 한다"
    assert rs.get_snapshot(a)["stress_score"] == pytest.approx(1.0), "앞 스냅샷이 변조됐다"


# ─── 4. ResearchUsage 전파 — 하나라도 forward_only 면 스냅샷 전체가 부적격 ─────
def test_snapshot_usage_degrades_to_forward_only(mem_rs):
    ecos = MacroObservation(
        series_id="ECOS_722Y001", observation_period="2020-04-30",
        release_timestamp="2020-04-30", vintage_id="", retrieved_at="2026-07-27T00:00:00Z",
        value=0.75, data_status=DataStatus.PARTIAL,
    )
    sid = rs.create_snapshot(as_of=AS_OF, observations=[*OBS_OK, ecos], growth_axis=0.0,
                             inflation_axis=0.0, phase_probabilities={}, stress_score=0.0,
                             confidence=0.0)
    snap = rs.get_snapshot(sid)
    assert snap["research_usage"] == ResearchUsage.FORWARD_ONLY.value, (
        "빈티지 없는 시리즈(vintage_id 공백)가 섞이면 스냅샷 전체가 과거 시뮬레이션 부적격이어야 한다"
    )


def test_all_vintaged_snapshot_is_backtest_eligible(mem_rs):
    sid = rs.create_snapshot(as_of=AS_OF, observations=OBS_OK, growth_axis=0.0,
                             inflation_axis=0.0, phase_probabilities={}, stress_score=0.0,
                             confidence=0.0)
    assert rs.get_snapshot(sid)["research_usage"] == ResearchUsage.BACKTEST_ELIGIBLE.value


# ─── 5. 목록·삭제·정직 실패 ───────────────────────────────────────────────────
def test_list_is_newest_first(mem_rs):
    ids = [rs.create_snapshot(as_of=AS_OF, observations=OBS_OK, growth_axis=float(i),
                              inflation_axis=0.0, phase_probabilities={}, stress_score=0.0,
                              confidence=0.0) for i in range(3)]
    listed = [s["snapshot_id"] for s in rs.list_snapshots()]
    assert listed == list(reversed(ids))


def test_get_missing_returns_none(mem_rs):
    assert rs.get_snapshot("rgs_nope") is None


def test_db_unavailable_returns_none_not_fake(monkeypatch):
    def boom():
        raise RuntimeError("no db")
    monkeypatch.setattr(rs, "_engine", boom)
    monkeypatch.setattr(rs, "_inited", False)
    assert rs.create_snapshot(as_of=AS_OF, observations=OBS_OK, growth_axis=0.0,
                              inflation_axis=0.0, phase_probabilities={}, stress_score=0.0,
                              confidence=0.0) is None
    assert rs.get_snapshot("rgs_x") is None
    assert rs.list_snapshots() == []


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4a — regime 라벨 / recommended_mode 를 **필드로** 보관.
#
# Phase 2/3a 에서는 이 둘이 explanation 문자열("[Goldilocks · 권고 NORMAL] …") 안에만
# 있었다. 리서치 컨텍스트 스트립이 국면 배지를 그리려면 표시 문자열을 파싱해야 했는데,
# 그러면 문구를 한 번 다듬는 순간 배지가 조용히 깨진다. 열로 승격해 근원을 고친다.
# ═══════════════════════════════════════════════════════════════════════════════
def test_regime_and_mode_roundtrip_as_fields(mem_rs):
    sid = rs.create_snapshot(
        as_of=AS_OF, observations=OBS_OK, growth_axis=0.8, inflation_axis=-0.3,
        phase_probabilities={"Goldilocks": 0.6}, stress_score=41.0, confidence=0.64,
        explanation="성장 우위", regime="Goldilocks", recommended_mode="NORMAL",
    )
    snap = rs.get_snapshot(sid)
    assert snap["regime"] == "Goldilocks"
    assert snap["recommended_mode"] == "NORMAL"


def test_regime_fields_are_optional(mem_rs):
    """호출자가 안 넘기면 None — 없는 값을 빈 문자열로 위장하지 않는다."""
    sid = rs.create_snapshot(as_of=AS_OF, observations=OBS_OK, growth_axis=0.0,
                             inflation_axis=0.0, phase_probabilities={}, stress_score=0.0,
                             confidence=0.0)
    snap = rs.get_snapshot(sid)
    assert snap["regime"] is None
    assert snap["recommended_mode"] is None


def test_regime_fields_appear_in_list_summary(mem_rs):
    """스트립·목록이 관측치 배열 없이도 국면을 보여줄 수 있어야 한다."""
    rs.create_snapshot(as_of=AS_OF, observations=OBS_OK, growth_axis=0.0, inflation_axis=0.0,
                       phase_probabilities={}, stress_score=0.0, confidence=0.0,
                       regime="Stagflation", recommended_mode="DEFENSIVE")
    row = rs.list_snapshots()[0]
    assert row["regime"] == "Stagflation"
    assert row["recommended_mode"] == "DEFENSIVE"
    assert "observations" not in row


def test_pre_migration_rows_still_read(mem_rs):
    """★기존 운영 DB 시나리오★ — 두 열이 없는 테이블에 든 행도 그대로 읽혀야 한다.

    열을 추가하고 무조건 SELECT 하면, ALTER 가 권한 등으로 실패했을 때 스냅샷 조회가
    통째로 깨진다(수정 전보다 나쁨). backtest_runs.py:115~122 가 같은 이유로 ALTER 적용
    여부를 확인하고 기능만 끄는 패턴을 쓴다 — 여기서도 그것을 따른다.
    """
    from sqlalchemy import text

    # 구 스키마(두 열 없음)를 직접 만들고 행을 하나 넣는다
    with mem_rs.begin() as c:
        c.execute(text(f"DROP TABLE IF EXISTS {rs._TABLE}"))
        c.execute(text(
            f"CREATE TABLE {rs._TABLE} ("
            "snapshot_id VARCHAR(40) PRIMARY KEY, created_at DOUBLE PRECISION, "
            "as_of VARCHAR(32), growth_axis DOUBLE PRECISION, inflation_axis DOUBLE PRECISION, "
            "phase_probabilities TEXT, stress_score DOUBLE PRECISION, confidence DOUBLE PRECISION, "
            "observations TEXT, data_status VARCHAR(20), research_usage VARCHAR(24), "
            "model_version VARCHAR(40), engine_version VARCHAR(40), code_version VARCHAR(60), "
            "explanation TEXT)"
        ))
        c.execute(text(
            f"INSERT INTO {rs._TABLE} (snapshot_id, created_at, as_of, growth_axis, "
            "inflation_axis, phase_probabilities, stress_score, confidence, observations, "
            "data_status, research_usage, model_version, engine_version, code_version, explanation) "
            "VALUES ('rgs_old_1', 1.0, '2020-01-01', 0.1, 0.2, '{}', 5.0, 0.5, '[]', "
            "'real', 'forward_only', 'v1', 'v1', 'dev', '구버전 행')"
        ))
    rs._inited = False   # 다음 호출에서 마이그레이션이 돌게

    snap = rs.get_snapshot("rgs_old_1")
    assert snap is not None, "구 스키마 행을 못 읽으면 마이그레이션이 파괴적이다"
    assert snap["as_of"] == "2020-01-01"
    assert snap["explanation"] == "구버전 행"
    # 마이그레이션이 성공했다면 새 열은 None, 실패했다면 키가 없거나 None — 둘 다 허용
    assert snap.get("regime") is None
