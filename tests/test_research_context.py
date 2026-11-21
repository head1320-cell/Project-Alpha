"""ResearchContext — 연구 계산의 정보집합 (벤치마크 §4, Priority S)

★이 파일이 거는 것★
  1. ★동결★ 컨텍스트가 도중에 바뀌면 재현성이 무의미하다.
  2. ★지문이 **필드마다** 반응한다★ "같은 입력 → 같은 출력" 만 재면 동어반복이다
     (직전 슬라이스에서 PD 플래그가 equivalent mutant 로 드러났다).
  3. ★선언하지 않은 절단일을 지어내지 않는다★ 비어 있음은 '그 날짜로 잘랐다' 가
     아니라 '자른 적이 없다' 이다 — §4 의 hidden date.
"""
import dataclasses
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402

from src.engine.research_context import (  # noqa: E402
    CUTOFF_FIELDS,
    FINGERPRINT_LEN,
    ResearchContext,
    code_version,
    data_source,
    describe,
    fingerprint,
    now,
    validate_as_of,
)

ALL_FIELDS = tuple(f.name for f in dataclasses.fields(ResearchContext))


def _ctx(**kw) -> ResearchContext:
    base = {"as_of": "2026-06-30", "information_cutoff": "2026-06-30",
            "universe_id": "kospi200", "data_snapshot_id": "snap_1",
            "engine_version": "e1", "risk_model_version": "r1"}
    base.update(kw)
    return ResearchContext(**base)


# ── 1. ★동결★ ─────────────────────────────────────────────────────────────
def test_the_context_cannot_be_mutated():
    """도중에 바뀌는 컨텍스트로는 '같은 컨텍스트 → 같은 결과' 를 말할 수 없다."""
    c = _ctx()
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.as_of = "2020-01-01"


def test_a_derived_context_leaves_the_original_alone():
    c = _ctx()
    d = c.with_(universe_id="kosdaq150")
    assert c.universe_id == "kospi200" and d.universe_id == "kosdaq150"
    assert fingerprint(c) != fingerprint(d)


def test_the_declared_fields_match_the_specification():
    """벤치마크 §4 가 지정한 필드가 전부 있다."""
    for f in ("as_of", "information_cutoff", "universe_id", "market_data_as_of",
              "fundamental_data_as_of", "macro_data_as_of", "data_snapshot_id",
              "engine_version", "risk_model_version"):
        assert f in ALL_FIELDS, f


# ── 2. ★지문이 필드마다 반응한다★ ────────────────────────────────────────
def test_the_same_context_gives_the_same_fingerprint():
    assert fingerprint(_ctx()) == fingerprint(_ctx())
    assert len(fingerprint(_ctx())) == FINGERPRINT_LEN


@pytest.mark.parametrize("field", ALL_FIELDS)
def test_changing_any_single_field_changes_the_fingerprint(field):
    """★동어반복 가드를 쓰지 않는다★ 필드 하나하나가 실제로 지문에 들어가는지.

    일부 필드만으로 지문을 계산하는 변이는 여기서 잡힌다.
    """
    base = _ctx(**{f: "x" for f in CUTOFF_FIELDS})
    changed = base.with_(**{field: "다른값"})
    assert fingerprint(base) != fingerprint(changed), field


def test_the_data_source_is_part_of_the_fingerprint(monkeypatch):
    """★mock 과 실데이터가 같은 지문을 갖는 것이 가장 위험한 재현성 거짓말이다★"""
    c = _ctx()
    mock_fp = fingerprint(c)
    monkeypatch.setattr("src.engine.research_context.data_source", lambda: "db")
    assert fingerprint(c) != mock_fp


def test_the_code_version_is_part_of_the_fingerprint(monkeypatch):
    c = _ctx()
    before = fingerprint(c)
    monkeypatch.setattr("src.engine.research_context.code_version", lambda: "sha-zzz")
    assert fingerprint(c) != before


def test_the_fingerprint_is_stable_under_field_order():
    """정규화 확인 — dict 순서가 지문을 바꾸면 재현성이 깨진다."""
    a = ResearchContext(as_of="2026-01-01", universe_id="u", engine_version="e")
    b = ResearchContext(engine_version="e", universe_id="u", as_of="2026-01-01")
    assert fingerprint(a) == fingerprint(b)


# ── 3. ★선언하지 않은 절단일을 지어내지 않는다★ ─────────────────────────
def test_unspecified_cutoffs_are_reported_as_unspecified():
    """★§4 의 hidden date★ 비어 있음은 '자른 적이 없다' 는 뜻이다."""
    d = describe(_ctx())
    assert set(d["cutoffs_unspecified"]) == set(CUTOFF_FIELDS)
    assert d["cutoffs_declared"] == {}
    assert "자른 적이 없다" in d["note"]


def test_a_declared_cutoff_is_reported_as_declared():
    """★짝★ 전부 unspecified 라고 하면 위 테스트도 green 이다."""
    d = describe(_ctx(macro_data_as_of="2026-05-31"))
    assert d["cutoffs_declared"] == {"macro_data_as_of": "2026-05-31"}
    assert "macro_data_as_of" not in d["cutoffs_unspecified"]
    assert set(d["cutoffs_unspecified"]) == set(CUTOFF_FIELDS) - {"macro_data_as_of"}


def test_now_does_not_invent_cutoffs():
    """`now()` 가 편의를 위해 절단일을 채우면 그것이 바로 hidden date 다."""
    c = now()
    for f in CUTOFF_FIELDS:
        assert getattr(c, f) is None, f
    assert c.as_of == date.today().isoformat()
    # information_cutoff 는 as_of 와 같게 두되 그것은 **명시적 기본값**이다.
    assert c.information_cutoff == c.as_of


def test_now_accepts_explicit_overrides():
    c = now(universe_id="kospi200", macro_data_as_of="2026-01-31")
    assert c.universe_id == "kospi200"
    assert c.macro_data_as_of == "2026-01-31"


def test_describe_carries_the_source_and_version():
    d = describe(_ctx())
    assert d["data_source"] in ("mock", "db", "unknown")
    assert d["code_version"] == code_version()
    assert d["fingerprint"] == fingerprint(_ctx())


# ── 4. ★as_of 정책★ ──────────────────────────────────────────────────────
def test_a_future_as_of_is_refused_with_the_reason():
    """★고정이 아니라 고정한 척★"""
    future = (date.today() + timedelta(days=1)).isoformat()
    reason = validate_as_of(future)
    assert reason and "고정한 척" in reason


def test_today_is_allowed():
    assert validate_as_of(date.today().isoformat()) is None


def test_a_past_as_of_is_allowed():
    assert validate_as_of("2020-01-01") is None


def test_none_is_allowed():
    assert validate_as_of(None) is None


@pytest.mark.parametrize("bad", ["2026-13-01", "26-01-01", "2026/01/01",
                                 "not-a-date", "", "2026-01-01T00:00:00"])
def test_a_malformed_as_of_is_refused(bad):
    reason = validate_as_of(bad)
    assert reason and "형식" in reason


def test_the_engine_never_raises_http():
    """★엔진은 HTTP 를 모른다★ 사유를 돌려줄 뿐 예외를 던지지 않는다."""
    assert isinstance(validate_as_of("2099-01-01"), str)
    assert isinstance(validate_as_of("쓰레기"), str)


# ── 5. ★단일 출처★ ───────────────────────────────────────────────────────
def test_the_code_version_fallback_order(monkeypatch):
    """★AM2 에서 마지막 칸이 바뀌었다★ `"dev"` → 측정, 못 재면 `None` + 사유.

    주입 우선순위(`GIT_SHA` → `APP_VERSION`)는 그대로다 — 컨테이너에는 `.git` 이
    없어(`.dockerignore`) 주입이 유일한 진실이기 때문이다. 바뀐 것은 **주입이
    없을 때** 이며, 옛 코드는 여기서 `"dev"` 를 지어냈다. 그 상수 때문에 실측
    701행이 전부 같은 값이 됐고 `research_manifest` 의 노후화 검사가 항상 참이
    됐다 — ★가드는 있는데 도달할 수 없었다★.
    """
    from src.domain.build_identity import is_version
    from src.engine.build_probe import current_identity

    monkeypatch.setenv("GIT_SHA", "sha-1")
    monkeypatch.setenv("APP_VERSION", "app-1")
    assert code_version() == "sha-1"
    monkeypatch.delenv("GIT_SHA")
    assert code_version() == "app-1", "APP_VERSION 이 두 번째 폴백이다"

    monkeypatch.delenv("APP_VERSION")
    got = code_version()
    assert got != "dev", "★`\"dev\"` 를 지어내지 않는다★"
    if got is None:
        assert current_identity().reason, "사유 없는 미상은 금지다"
    else:
        assert is_version(got), "측정된 커밋이어야 한다"


def test_the_data_source_follows_the_mock_gate(monkeypatch):
    """★`mock_gate` 가 유일한 판정 기준이다★ (CLAUDE.md)"""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    assert data_source() == "mock"
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    assert data_source() == "db"
