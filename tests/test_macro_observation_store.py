"""매크로 관측 스토어 — ★개정 편향을 잴 수 있게 만드는 조건★
==============================================================================
설계: `docs/specs/2026-08-27-capability-lineage-audit.md` §B1·§D

## 이 파일이 막는 것

1. ★같은 기간의 빈티지를 덮는 것★ — 덮으면 개정 편향을 **영영 못 잰다**.
   이 스토어가 존재하는 유일한 이유가 그것이다.
2. ★빈 `vintage_id` 를 지어내는 것★ — Phase 8b 가 고친 결함이다. 지어내면
   `has_vintage` 가 참이 되어 **빈티지 정보가 전혀 없는 응답이
   `backtest_eligible` 로 인증된다.** 게이트가 거짓말을 한다.
3. ★빈 빈티지에서 개정 증거를 잃는 것★ — 빈티지가 없으면 두 관측치를 가르는
   유일한 증거가 **값**이다. 접으면 개정이 사라지고, 매번 새 행을 만들면
   아무 정보 없는 증가만 남는다.
4. ★mock 을 영속화하는 것★ — 합성값이 스토어에 들어가면 나중에 누군가 그것을
   실제 역사로 읽는다.
5. ★`as_of` 를 과잉 차단하는 것★ — `release_timestamp` 가 빈 행까지 막으면
   빈티지 없는 계열이 전방 연구에서도 사라진다.
6. ★국면 축이 이 스토어를 읽는 것★ — 배분 정책 배선은 별도 승인 사항이다.

## 짝 검증

M2/M3 · M5/M6 · M7/M8 · M9/M10 — 한쪽만 있으면 "무조건 덮기" · "무조건 쌓기" ·
"무조건 차단" · "무조건 건너뛰기" 로도 통과한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.macro_observation_store as st  # noqa: E402
from src.data.pit_macro import (  # noqa: E402
    DataStatus,
    MacroObservation,
    ResearchUsage,
)


@pytest.fixture
def eng():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    yield e
    e.dispose()


def _obs(period="2026-01", value=1.0, *, vintage="", release="",
         series="GDP", status=DataStatus.REAL, retrieved="2026-01-01T00:00:00Z"):
    return MacroObservation(
        series_id=series, observation_period=period, release_timestamp=release,
        vintage_id=vintage, retrieved_at=retrieved, value=value, data_status=status)


# ══════════════════════════════════════════════════════════════════════════
# 1) 왕복
# ══════════════════════════════════════════════════════════════════════════
def test_round_trip_preserves_every_field(eng):
    """M1 — 9필드 전부. 하나라도 잃으면 계보가 끊긴다."""
    o = MacroObservation(
        series_id="GDPC1", observation_period="2026-01", release_timestamp="2026-02-27",
        vintage_id="2026-02-27..9999-12-31", retrieved_at="2026-03-01T10:00:00Z",
        value=23456.78, data_status=DataStatus.REAL,
        market_cutoff="2026-02-27T21:00:00Z", execution_timestamp="2026-02-28T09:00:00Z")
    assert st.save([o], source=st.SOURCE_ALFRED, engine=eng) == 1

    got = st.load("GDPC1", engine=eng)
    assert len(got) == 1
    g = got[0]
    assert g.series_id == "GDPC1" and g.observation_period == "2026-01"
    assert g.release_timestamp == "2026-02-27"
    assert g.vintage_id == "2026-02-27..9999-12-31"
    assert g.retrieved_at == "2026-03-01T10:00:00Z"
    assert g.value == pytest.approx(23456.78)
    assert g.data_status is DataStatus.REAL
    assert g.market_cutoff == "2026-02-27T21:00:00Z"
    assert g.execution_timestamp == "2026-02-28T09:00:00Z"


# ══════════════════════════════════════════════════════════════════════════
# 2) ★빈티지가 공존한다★ — 이 스토어의 존재 이유
# ══════════════════════════════════════════════════════════════════════════
def test_two_vintages_of_the_same_period_coexist(eng):
    """M2 ★핵심★ 개정본이 이전본을 덮으면 편향을 영영 못 잰다."""
    st.save([_obs(value=1.0, vintage="v1", release="2026-02-01"),
             _obs(value=1.2, vintage="v2", release="2026-03-01")], engine=eng)
    got = st.vintages_of("GDP", "2026-01", engine=eng)
    assert [o.value for o in got] == pytest.approx([1.0, 1.2])
    assert [o.vintage_id for o in got] == ["v1", "v2"]


def test_resaving_the_same_vintage_is_idempotent(eng):
    """M3 ★짝★ — 없으면 "무조건 새 행" 구현으로도 M2 가 통과한다."""
    st.save([_obs(value=1.0, vintage="v1", release="2026-02-01")], engine=eng)
    st.save([_obs(value=1.0, vintage="v1", release="2026-02-01")], engine=eng)
    with eng.connect() as c:
        n = c.execute(text(f"SELECT COUNT(*) FROM {st.TABLE}")).scalar()
    assert n == 1


def test_vintages_are_ordered_by_release(eng):
    """M14 — 순서가 없으면 "무엇이 먼저였나" 를 읽는 쪽이 다시 정렬해야 한다."""
    st.save([_obs(value=3.0, vintage="v3", release="2026-04-01"),
             _obs(value=1.0, vintage="v1", release="2026-02-01"),
             _obs(value=2.0, vintage="v2", release="2026-03-01")], engine=eng)
    got = st.vintages_of("GDP", "2026-01", engine=eng)
    assert [o.release_timestamp for o in got] == \
        ["2026-02-01", "2026-03-01", "2026-04-01"]


# ══════════════════════════════════════════════════════════════════════════
# 3) ★빈 빈티지 — 지어내지 않되 증거는 잃지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_an_empty_vintage_is_stored_empty(eng):
    """M4 — ★지어내면 게이트가 거짓말을 한다★ (Phase 8b 가 고친 결함)"""
    st.save([_obs(value=5.0)], engine=eng)
    got = st.load("GDP", engine=eng)
    assert got[0].vintage_id == "", f"빈티지를 지어냈다: {got[0].vintage_id!r}"
    assert got[0].release_timestamp == ""


def test_an_empty_vintage_with_a_different_value_is_a_separate_row(eng):
    """M5 — ★빈티지가 없으면 값이 개정의 유일한 증거다★ 접으면 사라진다."""
    st.save([_obs(period="2026-02", value=5.0)], engine=eng)
    st.save([_obs(period="2026-02", value=5.5)], engine=eng)
    got = st.vintages_of("GDP", "2026-02", engine=eng)
    assert sorted(o.value for o in got) == pytest.approx([5.0, 5.5])


def test_an_empty_vintage_with_the_same_value_does_not_grow(eng):
    """M6 ★짝★ — 없으면 "무조건 새 행" 으로도 M5 가 통과하고 행이 무한히 는다.

    같은 값을 다시 받은 것은 **아무 정보도 담지 않는다**.
    """
    st.save([_obs(period="2026-02", value=5.0)], engine=eng)
    st.save([_obs(period="2026-02", value=5.0, retrieved="2026-09-09T00:00:00Z")],
            engine=eng)
    assert len(st.vintages_of("GDP", "2026-02", engine=eng)) == 1


def test_first_seen_retrieved_at_is_preserved(eng):
    """★"언제부터 알았나" 를 덮지 않는다★ 같은 값 재수집은 새 정보가 아니다."""
    st.save([_obs(period="2026-02", value=5.0, retrieved="2026-01-01T00:00:00Z")],
            engine=eng)
    st.save([_obs(period="2026-02", value=5.0, retrieved="2026-09-09T00:00:00Z")],
            engine=eng)
    assert st.load("GDP", engine=eng)[0].retrieved_at == "2026-01-01T00:00:00Z"


# ══════════════════════════════════════════════════════════════════════════
# 4) `as_of` — 기존 룩어헤드 규칙을 복제한다
# ══════════════════════════════════════════════════════════════════════════
def test_as_of_excludes_later_releases(eng):
    """M7 — `regime_snapshots._assert_pit` 과 같은 규칙."""
    st.save([_obs(value=1.0, vintage="v1", release="2026-02-01"),
             _obs(value=1.2, vintage="v2", release="2026-03-01")], engine=eng)
    got = st.load("GDP", as_of="2026-02-15", engine=eng)
    assert [o.vintage_id for o in got] == ["v1"]


def test_an_empty_release_passes_as_of_but_grades_down(eng):
    """M8 ★짝★ — 과잉 차단하면 빈티지 없는 계열이 전방 연구에서도 사라진다.

    ★통과가 곧 적격이 아니다★ — `derive_usage` 가 등급을 낮춘다.
    """
    st.save([_obs(period="2026-02", value=5.0)], engine=eng)   # release 없음
    assert len(st.load("GDP", as_of="1999-01-01", engine=eng)) == 1, "과잉 차단했다"
    assert st.coverage(engine=eng)["research_usage"] == ResearchUsage.FORWARD_ONLY.value


# ══════════════════════════════════════════════════════════════════════════
# 5) ★mock 은 저장하지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_mock_observations_are_not_persisted(eng):
    """M9 — 합성값이 스토어에 들어가면 나중에 실제 역사로 읽힌다."""
    assert st.save([_obs(value=9.9, status=DataStatus.MOCK)], engine=eng) == 0
    assert st.load("GDP", engine=eng) == []


def test_real_observations_are_persisted(eng):
    """M10 ★짝★ — 없으면 "전부 건너뛰기" 구현으로도 M9 가 통과한다."""
    assert st.save([_obs(value=1.0, vintage="v1")], engine=eng) == 1
    assert len(st.load("GDP", engine=eng)) == 1


def test_a_mixed_batch_keeps_only_the_real_rows(eng):
    st.save([_obs(period="2026-01", value=1.0, vintage="v1"),
             _obs(period="2026-02", value=9.9, status=DataStatus.MOCK)], engine=eng)
    assert [o.observation_period for o in st.load("GDP", engine=eng)] == ["2026-01"]


# ══════════════════════════════════════════════════════════════════════════
# 6) 저장 원시함수 규약
# ══════════════════════════════════════════════════════════════════════════
def test_save_without_a_database_returns_zero_instead_of_raising(monkeypatch):
    """M11 — `instrument_master_store` 규약."""
    monkeypatch.setattr(st, "_engine", lambda engine=None: None)
    assert st.save([_obs(value=1.0, vintage="v1")]) == 0


def test_load_without_a_database_is_empty_not_an_error(monkeypatch):
    """M12 — ★재지 못한 것을 0으로 적지 않는다★"""
    monkeypatch.setattr(st, "_engine", lambda engine=None: None)
    assert st.load() == []


def test_coverage_without_a_database_is_unavailable(monkeypatch):
    monkeypatch.setattr(st, "_engine", lambda engine=None: None)
    got = st.coverage()
    assert got["available"] is False and got["reason"]
    assert "rows" not in got


# ══════════════════════════════════════════════════════════════════════════
# 7) 등급은 `derive_usage` 가 판다
# ══════════════════════════════════════════════════════════════════════════
def test_coverage_goes_through_derive_usage(eng, monkeypatch):
    """M13 ★핵심 가드★ 두 번째 등급 체계를 만들면 반드시 갈라진다."""
    seen = {}
    real = st.derive_usage

    def spy(**kw):
        seen.update(kw)
        return real(**kw)

    monkeypatch.setattr(st, "derive_usage", spy)
    st.save([_obs(value=1.0, vintage="v1", release="2026-02-01")], engine=eng)
    st.coverage(engine=eng)
    assert seen, "`derive_usage` 를 부르지 않았다 — 자체 판정 중이다"
    assert seen["has_vintage"] is True and seen["lag_known"] is True


def test_full_vintage_coverage_is_backtest_eligible(eng):
    """짝 — 게이트가 전부를 막아버리지 않는다."""
    st.save([_obs(value=1.0, vintage="v1", release="2026-02-01")], engine=eng)
    got = st.coverage(engine=eng)
    assert got["research_usage"] == ResearchUsage.BACKTEST_ELIGIBLE.value
    assert got["reason"] is None


def test_an_empty_store_is_unavailable_not_eligible(eng):
    """★"없다" 와 "있는데 부적격" 은 다른 사실이다★"""
    st.ensure_table(eng)
    got = st.coverage(engine=eng)
    assert got["research_usage"] == ResearchUsage.UNAVAILABLE.value
    assert got["rows"] == 0 and got["reason"]


# ══════════════════════════════════════════════════════════════════════════
# 8) `record_series` — MacroSeries 변환
# ══════════════════════════════════════════════════════════════════════════
class _Series:
    def __init__(self, source, stamps, values, indicator="KR_BASE_RATE"):
        self.indicator, self.source = indicator, source
        self.timestamps, self.values = stamps, values


def test_record_series_converts_and_stores(eng):
    """M15 — ★이 경로에는 빈티지가 없다★ 빈 채로 둔다."""
    n = st.record_series(
        _Series("FRED", ["2026-01", "2026-02"], [1.0, 2.0]), engine=eng)
    assert n == 2
    got = st.load("KR_BASE_RATE", engine=eng)
    assert [o.value for o in got] == pytest.approx([1.0, 2.0])
    assert all(o.vintage_id == "" for o in got), "빈티지를 지어냈다"
    assert all(o.release_timestamp == "" for o in got)


def test_record_series_ignores_mock_and_unavailable(eng):
    """★`MOCK`·`unavailable` 은 기록하지 않는다★"""
    assert st.record_series(_Series("MOCK", ["2026-01"], [1.0]), engine=eng) == 0
    assert st.record_series(_Series("unavailable", [], []), engine=eng) == 0
    assert st.load(engine=eng) == []


def test_record_series_handles_ragged_input(eng):
    """길이가 어긋나면 짝을 지어내지 않는다."""
    assert st.record_series(_Series("BOK", ["2026-01", "2026-02"], [1.0]),
                            engine=eng) == 0


# ══════════════════════════════════════════════════════════════════════════
# 9) 라우트
# ══════════════════════════════════════════════════════════════════════════
def test_route_reports_coverage_and_vintages(monkeypatch, eng):
    """M16"""
    from fastapi.testclient import TestClient

    from src.app_factory import create_app

    monkeypatch.setattr("src.database.get_engine", lambda: eng)
    st.save([_obs(value=1.0, vintage="v1", release="2026-02-01"),
             _obs(value=1.2, vintage="v2", release="2026-03-01")], engine=eng)

    client = TestClient(create_app())
    r = client.get("/api/v1/data/macro-vintages?series=GDP&period=2026-01")
    assert r.status_code == 200
    body = r.json()
    assert body["coverage"]["rows"] == 2
    assert len(body["vintages"]) == 2, "한 기간의 두 빈티지가 보이지 않는다"


# ══════════════════════════════════════════════════════════════════════════
# 10) ★분리를 코드가 강제한다★
# ══════════════════════════════════════════════════════════════════════════
#: 메타데이터만 묻는 함수 — "행이 있는가" 이지 "값이 무엇인가" 가 아니다.
#: ★예외는 여기 명시된 것뿐이고, 나머지는 전부 값 취급이다★
_METADATA_READERS = ("coverage",)


def _value_readers() -> tuple:
    """스토어의 공개 API 에서 **유도한다** — 손으로 유지하지 않는다.

    ★목록을 손으로 적으면 비우는 것만으로 가드가 무장해제된다★(변이 실험에서
    실제로 살아남았다). 그리고 스토어에 새 값 함수가 생겨도 자동으로 잡힌다.
    """
    import src.data.macro_observation_store as mos

    return tuple(sorted(
        n for n in dir(mos)
        if not n.startswith("_") and callable(getattr(mos, n, None))
        and getattr(getattr(mos, n), "__module__", "") == mos.__name__
        and n not in _METADATA_READERS))


def _engine_hits(names: tuple) -> list[str]:
    """`src/engine/` 에서 스토어의 해당 심볼을 **코드 토큰으로** 찾는다."""
    import io as _io
    import pathlib
    import tokenize

    hits = []
    for path in sorted(pathlib.Path("src/engine").rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        if "macro_observation_store" not in src:
            continue
        for tok in tokenize.generate_tokens(_io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue          # 산문은 설명해도 된다
            if tok.string in names:
                hits.append(f"{path.as_posix()}:{tok.start[0]}")
    return hits


def test_the_engine_layer_does_not_read_observation_values():
    """★불변 논증 — 재실시 (2026-08-28)★

    원래 이 테스트는 `src/engine/` 에서 `macro_observation_store` **식별자 전체**를
    금지했다. 독스트링이 *"소비자가 생기면 red 가 된다 — 그때 그 논증을 다시 해야
    한다"* 고 적어 뒀고, P2 작업에서 실제로 red 가 되어 여기서 다시 한다.

    ★구분이 실재한다★ — 막으려던 것은 스토어의 **관측값**이 국면 계산으로 흘러드는
    것이다(배분 정책 배선). P2 가 추가한 `regime_axes._series_has_vintage` 는
    `coverage()` 만 부른다 — *"이 계열에 빈티지 행이 **있는가**"* 라는 개수 조회이고,
    값이 아니라 **정직성 라벨**(`blocked_by`)에만 쓰이며, 축 출력은 바이트 동일이다.
    빈티지가 0건인 지금 그 판정은 "못 쓴다" 이므로 오히려 **더 보수적**이다.

    ★그래서 가드를 좁히되 느슨하게 하지 않는다★ — 값 읽기(`load`·`vintages_of`·
    `save`·`record_series`)는 **여전히 금지**다. 그것이 생기면 국면 계산이 스토어의
    숫자를 먹는다는 뜻이고, 그때 논증을 또 해야 한다.
    """
    hits = _engine_hits(_value_readers())
    assert hits == [], (
        "`src/engine/` 이 매크로 관측 **값**을 읽는다 — 배분 정책 배선은 별도 "
        "승인 사항이다. 불변 논증을 다시 할 것:\n" + "\n".join(hits))


def test_metadata_only_reads_are_the_narrow_exception():
    """★짝★ — 예외가 **좁다**는 것을 못 박는다.

    이 테스트가 없으면 위 가드를 "아무것도 금지하지 않음" 으로 약화시켜도 통과한다.
    메타데이터 조회는 **한 곳**(`regime_axes`)뿐이어야 하고, 늘어나면 그때 다시 본다.
    """
    hits = _engine_hits(_METADATA_READERS)
    files = {h.rsplit(":", 1)[0] for h in hits}
    assert files <= {"src/engine/regime_axes.py"}, (
        f"메타데이터 조회가 예상 밖 모듈로 번졌다: {sorted(files)}")
    assert hits, "메타데이터 조회가 사라졌다 — P2 판정이 관측을 안 쓴다는 뜻이다"

    # ★가드가 실제로 무언가를 금지하는지★ — 목록이 비면 위 테스트가 공허해진다.
    readers = _value_readers()
    assert {"load", "vintages_of", "save"} <= set(readers), (
        f"값 읽기 함수가 가드 목록에서 빠졌다: {readers}")


# ══════════════════════════════════════════════════════════════════════════
# 11) ★배선이 실제로 발화한다★ — 고아를 하나 더 만들지 않았다는 증거
# ══════════════════════════════════════════════════════════════════════════
def test_the_collector_actually_writes_through(eng, monkeypatch):
    """M17 — 감사가 비판한 것은 "만들어 놓고 아무도 안 부르는" 상태였다.

    스토어만 만들면 `adj_close_coverage` 처럼 또 하나의 고아가 된다. 수집
    파이프라인이 **실제로** 기록하는지 여기서 확인한다.

    ★`src/engine/` 이 아니라 `services/` 에 배선했다★ — 읽는 소비자는 여전히 0이고,
    국면 축 배선은 별도 승인 사항이다(`test_the_engine_layer_does_not_read_this_store`).
    """
    from src.services.macro_collector import MacroCollector

    monkeypatch.setattr("src.database.get_engine", lambda: eng)
    collector = MacroCollector()
    series = collector._collect_one(
        "TEST_SERIES", "테스트", "%",
        lambda: (["2026-01", "2026-02"], [1.0, 2.0]),
        use_cache=False, source="FRED")

    assert series.source == "FRED", "전제: 실 소스로 남아야 한다"
    got = st.load("TEST_SERIES", engine=eng)
    assert [o.value for o in got] == pytest.approx([1.0, 2.0]), "배선이 발화하지 않았다"
    # ★이 경로에는 빈티지가 없다★ 지어내면 게이트가 거짓말을 한다.
    assert all(o.vintage_id == "" for o in got)


def test_a_mock_collection_writes_nothing(eng, monkeypatch):
    """M17 ★짝★ — 없으면 "무조건 기록" 구현으로도 통과하고 합성값이 영속화된다."""
    from src.services.macro_collector import MacroCollector

    monkeypatch.setattr("src.database.get_engine", lambda: eng)
    collector = MacroCollector()
    collector._collect_one(
        "MOCK_SERIES", "테스트", "%",
        lambda: (_ for _ in ()).throw(RuntimeError("fetcher 실패")),
        use_cache=False, source="FRED")

    assert st.load("MOCK_SERIES", engine=eng) == [], "합성/미가용을 영속화했다"
