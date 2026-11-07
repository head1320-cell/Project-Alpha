"""ALFRED 빈티지 백필 — ★찾으려는 개정을 숨기지 않는다★
==============================================================================
설계: `docs/specs/2026-08-27-capability-lineage-audit.md` §C1 · 선행: `0ffe083`

## 이 파일이 막는 것

1. ★열린 빈티지 구간을 건너뛰는 것★ — 이 파일에서 **가장 위험한 결함**이다.
   `realtime_end == 9999-12-31` 은 "아직 대체되지 않았다" 는 뜻이라, 그 안의
   `as_of` 를 다시 받아야 **개정으로 닫혔는지** 알 수 있다. 건너뛰면 개정이
   일어난 순간을 영영 관측하지 못한다 — **찾으려는 바로 그것이 사라진다.**
   조용히 통과하므로 변이 테스트가 아니면 못 잡는다.
2. ★대상 계열 하드코딩★ — `"FRED"` 를 적으면 ECOS 가 빈티지를 갖게 돼도 모른다.
   `PROVIDER_HAS_VINTAGE` 가 단일 권위다.
3. ★키 없는 실행을 "0행 성공" 으로 보고하는 것★ — `fetch_observations` 는 키가
   없으면 빈 리스트를 준다. 그것을 성공으로 적으면 거짓이다.
4. ★빈티지 1개를 "개정 없음" 으로 세는 것★ — "개정 **관측** 안 됨" 이다.
   접으면 표본 부족이 "안정적인 계열" 로 둔갑한다.

## 실키 없이 전부 검증한다

`fetch_observations` 를 몽키패치한다 — 이 환경에는 `FRED_API_KEY` 가 없고,
기계 검증에는 실데이터가 필요하지 않다(감사 §H).
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.macro_observation_store as store  # noqa: E402
import src.data.macro_vintage_backfill as bf  # noqa: E402
from src.data.pit_macro import _FAR_FUTURE, DataStatus, MacroObservation  # noqa: E402

_KEY = "x" * 32          # 길이만 만족하면 된다 — fetch 는 몽키패치한다


@pytest.fixture
def eng():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    yield e
    e.dispose()


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", _KEY)


def _obs(series, period, value, rs, re_=_FAR_FUTURE):
    return MacroObservation(
        series_id=series, observation_period=period, release_timestamp=rs,
        vintage_id=f"{rs}..{re_}", retrieved_at="2026-01-01T00:00:00Z",
        value=value, data_status=DataStatus.REAL)


# ══════════════════════════════════════════════════════════════════════════
# 1) ★대상은 레지스트리에서 파생된다★
# ══════════════════════════════════════════════════════════════════════════
def test_targets_come_from_the_provider_vintage_flag():
    """B1 — `PROVIDER_HAS_VINTAGE` 가 단일 권위다."""
    from src.data.source_registry import FRED, specs_by_provider

    targets = set(bf.vintage_targets())
    fred_keys = {s.key for s in specs_by_provider(FRED) if not s.derived_from}
    assert targets == fred_keys, "대상이 레지스트리와 갈라졌다"
    assert targets, "전제: FRED 계열이 등록돼 있다"


def test_providers_without_vintages_are_not_targets():
    """B2 ★짝★ — 없으면 "전부 대상" 구현으로도 B1 이 통과한다."""
    from src.data.source_registry import ECOS, specs_by_provider

    targets = set(bf.vintage_targets())
    ecos_keys = {s.key for s in specs_by_provider(ECOS)}
    assert ecos_keys, "전제: ECOS 계열이 등록돼 있다"
    assert not (targets & ecos_keys), "빈티지 없는 제공자가 대상에 들어갔다"


def test_targets_follow_the_flag_not_a_hardcoded_provider(monkeypatch):
    """B1 심화 — ★플래그를 뒤집으면 대상이 따라 바뀐다★

    `"FRED"` 를 코드에 적어 넣었다면 이 테스트가 죽는다.
    """
    import src.data.source_registry as reg

    monkeypatch.setitem(reg.PROVIDER_HAS_VINTAGE, reg.ECOS, True)
    targets = set(bf.vintage_targets())
    ecos_keys = {s.key for s in reg.specs_by_provider(reg.ECOS) if not s.derived_from}
    assert ecos_keys & targets, "플래그가 참인데 대상에 들어오지 않았다"


# ══════════════════════════════════════════════════════════════════════════
# 2) `as_of` 스케줄
# ══════════════════════════════════════════════════════════════════════════
def test_schedule_is_month_ends_within_the_window():
    """B3"""
    got = bf.as_of_schedule("2026-01-01", "2026-04-30")
    assert got == ("2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30")


def test_schedule_respects_the_step():
    got = bf.as_of_schedule("2026-01-01", "2026-06-30", step_months=2)
    assert got == ("2026-01-31", "2026-03-31", "2026-05-31")


def test_schedule_rejects_a_zero_step():
    with pytest.raises(ValueError):
        bf.as_of_schedule("2026-01-01", "2026-06-30", step_months=0)


# ══════════════════════════════════════════════════════════════════════════
# 3) ★건너뛰기 — 이 파일의 핵심★
# ══════════════════════════════════════════════════════════════════════════
def test_a_closed_vintage_range_is_skipped(eng, with_key, monkeypatch):
    """B4 — 닫힌 구간은 다시 받아도 같은 빈티지가 온다."""
    store.save([_obs("GDPC1", "2026-01", 1.0, "2026-01-15", "2026-03-15")],
               source=store.SOURCE_ALFRED, engine=eng)
    calls: list[str] = []
    monkeypatch.setattr(bf, "fetch_observations",
                        lambda sid, as_of, **kw: calls.append(as_of) or [])

    bf.backfill(["GDPC1"], start="2026-01-01", end="2026-03-31",
                throttle=0, engine=eng)
    assert "2026-01-31" not in calls and "2026-02-28" not in calls, \
        f"닫힌 구간을 다시 받았다: {calls}"


def test_an_open_vintage_range_is_never_skipped(eng, with_key, monkeypatch):
    """B5 ★가장 중요한 짝★ — 열린 구간을 건너뛰면 개정을 영영 못 본다.

    `..9999-12-31` 은 "아직 대체되지 않았다" 는 뜻이다. 개정이 일어나야 그 구간이
    닫히는데, 재수집하지 않으면 **닫히는 순간을 관측할 수 없다.**
    ★찾으려는 바로 그것이 조용히 사라진다.★
    """
    store.save([_obs("GDPC1", "2026-01", 1.0, "2026-01-15")],   # 열림
               source=store.SOURCE_ALFRED, engine=eng)
    calls: list[str] = []
    monkeypatch.setattr(bf, "fetch_observations",
                        lambda sid, as_of, **kw: calls.append(as_of) or [])

    bf.backfill(["GDPC1"], start="2026-01-01", end="2026-03-31",
                throttle=0, engine=eng)
    assert "2026-01-31" in calls and "2026-02-28" in calls, \
        f"열린 구간을 건너뛰었다 — 개정이 사라진다: {calls}"


def test_closed_vintage_ranges_excludes_open_ones(eng):
    """B4/B5 의 원시함수 — 열린 구간이 목록에 들어가면 안 된다."""
    store.save([_obs("GDPC1", "2026-01", 1.0, "2026-01-15", "2026-03-15"),
                _obs("GDPC1", "2026-02", 2.0, "2026-03-15")], engine=eng)
    got = bf.closed_vintage_ranges("GDPC1", engine=eng)
    assert got == (("2026-01-15", "2026-03-15"),)


def test_force_disables_skipping(eng, with_key, monkeypatch):
    """B4 짝 — `--force` 가 닫힌 구간도 다시 받는다."""
    store.save([_obs("GDPC1", "2026-01", 1.0, "2026-01-15", "2026-03-15")],
               source=store.SOURCE_ALFRED, engine=eng)
    calls: list[str] = []
    monkeypatch.setattr(bf, "fetch_observations",
                        lambda sid, as_of, **kw: calls.append(as_of) or [])

    bf.backfill(["GDPC1"], start="2026-01-01", end="2026-02-28",
                skip_covered=False, throttle=0, engine=eng)
    assert len(calls) == 2


# ══════════════════════════════════════════════════════════════════════════
# 4) 쿼터 · 정직한 실패
# ══════════════════════════════════════════════════════════════════════════
def test_max_calls_actually_limits_the_run(eng, with_key, monkeypatch):
    """B6 — 쿼터 분할(`krx_ingest --max-days` 와 같은 역할)."""
    calls: list[str] = []
    monkeypatch.setattr(bf, "fetch_observations",
                        lambda sid, as_of, **kw: calls.append(as_of) or [])

    stats = bf.backfill(["GDPC1"], start="2026-01-01", end="2026-12-31",
                        max_calls=3, throttle=0, engine=eng)
    assert len(calls) == 3 and stats["calls"] == 3
    assert "stopped_at" in stats, "어디서 멈췄는지 알려주지 않는다"


def test_no_key_is_skipped_not_a_zero_row_success(eng, monkeypatch):
    """B7 — ★0행 성공으로 위장하지 않는다★"""
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    got = bf.backfill(["GDPC1"], start="2026-01-01", end="2026-02-28",
                      throttle=0, engine=eng)
    assert "skipped" in got and got["skipped"]
    assert "rows" not in got, "실행한 것처럼 보인다"


def test_a_short_key_counts_as_missing(eng, monkeypatch):
    """`pit_macro` 와 같은 판정 — 짧은 키는 키가 아니다."""
    monkeypatch.setenv("FRED_API_KEY", "abc")
    assert "skipped" in bf.backfill(["GDPC1"], throttle=0, engine=eng)


def test_one_series_failing_does_not_kill_the_run(eng, with_key, monkeypatch):
    """B13 — 한 계열의 실패가 전체를 죽이지 않는다."""
    def flaky(sid, as_of, **kw):
        if as_of == "2026-01-31":
            raise RuntimeError("네트워크 실패")
        return [_obs(sid, "2026-01", 1.0, "2026-02-10")]

    monkeypatch.setattr(bf, "fetch_observations", flaky)
    stats = bf.backfill(["GDPC1"], start="2026-01-01", end="2026-02-28",
                        throttle=0, engine=eng)
    assert stats["errors"] and "GDPC1@2026-01-31" in stats["errors"][0]
    assert stats["rows"] >= 1, "나머지 시점까지 포기했다"


# ══════════════════════════════════════════════════════════════════════════
# 5) ★죽어 있던 상수를 살린다★
# ══════════════════════════════════════════════════════════════════════════
def test_backfilled_rows_are_recorded_as_alfred(eng, with_key, monkeypatch):
    """B8 — `SOURCE_ALFRED` 가 실제로 쓰인다(스토어 도입 시엔 죽은 상수였다)."""
    from sqlalchemy import text

    monkeypatch.setattr(bf, "fetch_observations",
                        lambda sid, as_of, **kw: [_obs(sid, "2026-01", 1.0, "2026-02-10")])
    bf.backfill(["GDPC1"], start="2026-01-01", end="2026-01-31",
                throttle=0, engine=eng)
    with eng.connect() as c:
        got = {r[0] for r in c.execute(text(
            f"SELECT DISTINCT source FROM {store.TABLE}"))}
    assert got == {store.SOURCE_ALFRED}


def test_multiple_as_of_points_produce_multiple_vintages(eng, with_key, monkeypatch):
    """B10 ★사슬의 목적★ — 이것이 되어야 개정 편향을 잴 수 있다."""
    def by_as_of(sid, as_of, **kw):
        if as_of == "2026-01-31":
            return [_obs(sid, "2026-01", 1.0, "2026-01-20", "2026-02-20")]
        return [_obs(sid, "2026-01", 1.4, "2026-02-20")]

    monkeypatch.setattr(bf, "fetch_observations", by_as_of)
    bf.backfill(["GDPC1"], start="2026-01-01", end="2026-02-28",
                throttle=0, engine=eng)
    vs = store.vintages_of("GDPC1", "2026-01", engine=eng)
    assert len(vs) == 2, f"빈티지가 쌓이지 않았다: {vs}"


def test_backfill_is_idempotent(eng, with_key, monkeypatch):
    """B9 — 같은 빈티지 재수집이 행을 늘리지 않는다."""
    monkeypatch.setattr(bf, "fetch_observations",
                        lambda sid, as_of, **kw: [_obs(sid, "2026-01", 1.0, "2026-02-10")])
    for _ in range(2):
        bf.backfill(["GDPC1"], start="2026-01-01", end="2026-02-28",
                    skip_covered=False, throttle=0, engine=eng)
    assert len(store.load("GDPC1", engine=eng)) == 1


# ══════════════════════════════════════════════════════════════════════════
# 6) 개정 리포트
# ══════════════════════════════════════════════════════════════════════════
def test_revision_report_measures_first_versus_latest(eng):
    """B11 — 최초 빈티지 값과 최신 빈티지 값의 차이가 편향의 크기다."""
    store.save([_obs("GDPC1", "2026-01", 1.0, "2026-01-20", "2026-02-20"),
                _obs("GDPC1", "2026-01", 1.4, "2026-02-20")], engine=eng)
    rep = bf.revision_report("GDPC1", engine=eng)
    assert rep["available"] is True
    row = rep["rows"][0]
    assert row["status"] == bf.REVISION_OBSERVED
    assert row["first"] == pytest.approx(1.0) and row["latest"] == pytest.approx(1.4)
    assert row["delta"] == pytest.approx(0.4)
    assert rep["periods_with_observed_revision"] == 1


def test_a_single_vintage_is_unobserved_not_no_revision(eng):
    """B12 ★짝★ — ★표본 부족을 "안정적인 계열" 로 둔갑시키지 않는다★"""
    store.save([_obs("GDPC1", "2026-01", 1.0, "2026-02-10")], engine=eng)
    rep = bf.revision_report("GDPC1", engine=eng)
    row = rep["rows"][0]
    assert row["status"] == bf.REVISION_UNOBSERVED
    assert row["delta"] is None, "관측 못 한 것을 0 으로 적었다"
    assert rep["periods_revision_unobserved"] == 1
    assert rep["periods_with_observed_revision"] == 0
    assert rep["note"]


def test_revision_report_without_data_is_unavailable(eng):
    got = bf.revision_report("NOPE", engine=eng)
    assert got["available"] is False and got["reason"]


# ══════════════════════════════════════════════════════════════════════════
# 7) 라우트
# ══════════════════════════════════════════════════════════════════════════
def test_route_includes_the_revision_block(monkeypatch, eng):
    from fastapi.testclient import TestClient

    from src.app_factory import create_app

    monkeypatch.setattr("src.database.get_engine", lambda: eng)
    store.save([_obs("GDPC1", "2026-01", 1.0, "2026-01-20", "2026-02-20"),
                _obs("GDPC1", "2026-01", 1.4, "2026-02-20")], engine=eng)

    r = TestClient(create_app()).get("/api/v1/data/macro-vintages?series=GDPC1")
    assert r.status_code == 200
    rev = r.json()["revision"]
    assert rev["periods_with_observed_revision"] == 1


# ══════════════════════════════════════════════════════════════════════════
# 8) ★분리를 코드가 강제한다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_engine_layer_does_not_read_the_backfill():
    """B14 — 백필도 스토어와 같은 경계에 있다.

    빈티지를 **저장**하는 것과 국면 축이 그것을 **읽는** 것은 다른 일이고,
    후자는 배분 정책이라 별도 승인 사항이다.
    """
    import io as _io
    import pathlib
    import tokenize

    hits = []
    for path in sorted(pathlib.Path("src/engine").rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        if "macro_vintage_backfill" not in src:
            continue
        for tok in tokenize.generate_tokens(_io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            if "macro_vintage_backfill" in tok.string:
                hits.append(f"{path.as_posix()}:{tok.start[0]}")
    assert hits == [], (
        "`src/engine/` 이 빈티지 백필을 읽는다 — 배분 정책 배선은 별도 승인 "
        "사항이다:\n" + "\n".join(hits))
