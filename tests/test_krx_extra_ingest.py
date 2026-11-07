"""KRX 확장 4종 수집 — ★배선하되, 모르는 집계는 거부한다★
==============================================================================
감사: `docs/specs/2026-08-26-data-extraction-audit.md` §1.1
재사용: `krx_client.get_extra`/`parse_extra_rows` · `source_registry` 사유 어휘 ·
        `macro_observation_store.record_series`

## 이 파일이 막는 것

`get_extra()` 는 구현돼 있는데 **운영 호출부가 0** 이었다. 그 사실을
`source_registry.NOT_INGESTED_KEYS` 가 **손으로 적은 frozenset** 으로 선언했다 —
직전 커밋의 Z2 변이가 죽인 바로 그 모양이다(목록을 비우기만 하면 가드가 해제된다).
그래서 이제 그 집합은 **수집 경로에서 유도**되고, 경로를 지우면 선언이 자동으로
되돌아온다.

## ★두 번째 함정 — 접기 규칙★

`get_extra` 는 `basDd` **하루치** 조회이고 `parse_extra_rows` 의 결과에는 **종목
식별자가 없다**. VKOSPI 는 이름으로 한 행을 고르므로 정의가 알려져 있다. 그러나
`/sto/*_bydd_trd` 셋은 **전종목 일별** 명명 규약이라 하루에 여러 행이 온다.
그것을 시장 한 숫자로 접으려면 집계 정의가 필요한데 ★엔드포인트 자체가 미검증★
이라 그 정의를 우리가 지어내는 것이 된다. 그래서:

    COLLAPSE_SINGLE   이름으로 고른 한 행 — 의미가 알려져 있다 → 값을 낸다
    COLLAPSE_UNKNOWN  한 날짜에 여러 행   — 정의 미확정        → ★값을 내지 않는다★

## 증거등급

★E1(픽스처)★ 이다. `KRX_API_KEY` 가 없고 호스트가 프록시 403 이라 실호출로 확인한
것이 하나도 없다. 그리고 KRX 는 빈티지가 없어(`PROVIDER_HAS_VINTAGE[KRX]=False`)
이 배선은 **백테스트 적격 데이터를 한 줄도 늘리지 않는다** — 바뀌는 것은 "아니오"
의 정확도다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

import src.data.krx_client as kc  # noqa: E402
import src.data.krx_extras as kx  # noqa: E402
import src.data.macro_observation_store as mos  # noqa: E402
import src.data.source_registry as sr  # noqa: E402

_FOUR = ("VKOSPI", "KR_MARGIN_BALANCE", "KR_SHORT_VOLUME", "KR_LENDING_BALANCE")


class FakeKRX:
    """`KRXClient` 대역 — 하루치 조회에 **몇 행이 오는가**를 통제한다."""

    def __init__(self, rows_per_day: int = 1, *, configured: bool = True):
        self.is_configured = configured
        self.rows_per_day = rows_per_day
        self.calls: list[tuple[str, str]] = []

    def get_extra(self, kind, date, *, name_field=None, name_match=None):
        self.calls.append((kind, date))
        return [{"date": date, "value": 10.0 + i} for i in range(self.rows_per_day)]


@pytest.fixture
def eng():
    return create_engine("sqlite://", connect_args={"check_same_thread": False})


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, eng):
    """★프로세스 공용 DB 를 건드리지 않는다★"""
    monkeypatch.setattr(mos, "_engine", lambda engine=None: eng)
    yield


# ══════════════════════════════════════════════════════════════════════════
# B1 ★키가 없으면 값이 아니라 사유다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_missing_key_yields_a_reason_not_a_zero():
    s = kx.collect_extra("VKOSPI", "2024-01-02", "2024-01-05",
                         client=FakeKRX(configured=False))
    assert s.values == [] and s.latest is None
    assert s.source == "unavailable"
    assert s.reason == sr.REASON_NO_KEY


def test_a_missing_key_does_not_call_the_endpoint():
    cli = FakeKRX(configured=False)
    kx.collect_extra("VKOSPI", "2024-01-02", "2024-01-05", client=cli)
    assert cli.calls == [], "키도 없이 호출했다 — 쿼터를 태운다"


# ══════════════════════════════════════════════════════════════════════════
# B2·B4 ★한 날짜에 한 행이면 값을 낸다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_single_named_row_produces_a_series():
    s = kx.collect_extra("VKOSPI", "2024-01-02", "2024-01-04",
                         client=FakeKRX(rows_per_day=1))
    assert s.source == "KRX" and s.reason is None
    assert s.values == [10.0, 10.0, 10.0]
    assert s.timestamps == ["2024-01-02", "2024-01-03", "2024-01-04"]


def test_an_unambiguous_day_is_accepted_even_for_the_unknown_rule():
    """★짝★ 없으면 B3 가 '항상 거부' 구현으로도 통과한다."""
    s = kx.collect_extra("KR_MARGIN_BALANCE", "2024-01-02", "2024-01-03",
                         client=FakeKRX(rows_per_day=1))
    assert s.source == "KRX" and s.reason is None
    assert s.values == [10.0, 10.0]


# ══════════════════════════════════════════════════════════════════════════
# B3 ★핵심 — 모르는 집계를 조용히 제조하지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_multiple_rows_on_one_day_refuse_instead_of_aggregating():
    s = kx.collect_extra("KR_MARGIN_BALANCE", "2024-01-02", "2024-01-05",
                         client=FakeKRX(rows_per_day=3))
    assert s.values == [], "여러 행을 조용히 하나로 접었다"
    assert s.source == "unavailable"
    assert s.reason and "집계" in s.reason
    assert "3" in s.reason and "2024-01-02" in s.reason, (
        "몇 행이 어느 날 왔는지 말하지 않으면 고칠 수 없다")


def test_the_refusal_stops_calling_instead_of_burning_quota():
    cli = FakeKRX(rows_per_day=3)
    kx.collect_extra("KR_MARGIN_BALANCE", "2024-01-02", "2024-01-31", client=cli)
    assert len(cli.calls) == 1, "모호함을 알고도 계속 호출했다"


def test_a_named_rule_also_refuses_an_ambiguous_day():
    """이름으로 골랐는데도 여러 행이면 그 이름이 유일하지 않다는 뜻이다."""
    s = kx.collect_extra("VKOSPI", "2024-01-02", "2024-01-05",
                         client=FakeKRX(rows_per_day=2))
    assert s.values == [] and s.source == "unavailable"


def test_the_two_refusals_are_told_apart():
    """★사유를 뭉개지 않는다★ 고치는 사람이 다르다.

    이름 필터가 유일하지 않은 것은 **우리 필터**를 고쳐야 하고, 집계 정의가 없는
    것은 **실응답 1건**이면 확정된다. 한 문자열로 합치면 둘 다 잃는다.
    """
    named = kx.collect_extra("VKOSPI", "2024-01-02", "2024-01-05",
                             client=FakeKRX(rows_per_day=2))
    unknown = kx.collect_extra("KR_MARGIN_BALANCE", "2024-01-02", "2024-01-05",
                               client=FakeKRX(rows_per_day=2))
    assert named.reason != unknown.reason
    assert "집계" in unknown.reason and "집계" not in named.reason
    assert "이름" in named.reason


def test_an_empty_day_is_skipped_not_zero_filled():
    """휴장·미공표는 **0 이 아니다** — 건너뛴다."""
    cli = FakeKRX(rows_per_day=0)
    s = kx.collect_extra("VKOSPI", "2024-01-02", "2024-01-04", client=cli)
    assert s.values == [] and s.source == "unavailable"
    assert s.reason and "집계" not in s.reason, (
        "빈 응답을 모호함으로 잘못 분류했다 — 원인이 다르다")
    assert len(cli.calls) == 3, "빈 날짜에서 멈추면 안 된다(휴장일 수 있다)"


# ══════════════════════════════════════════════════════════════════════════
# B5·B6 ★선언이 수집 경로에서 유도된다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_four_series_are_no_longer_declared_uningested():
    for key in _FOUR:
        st = sr.status(key)
        assert st["not_ingested"] is False, key
        assert "수집 코드가 없습니다" not in (st["reason"] or ""), key
    assert sr.not_ingested_keys() == frozenset()


def test_deleting_the_pipeline_restores_the_honest_declaration(monkeypatch):
    """★유도 검증★ 손으로 적은 목록이었다면 비우기만 해도 가드가 풀렸다.

    이제는 **수집 경로가 진실**이라, 경로를 지우면 선언이 스스로 되돌아온다.
    """
    monkeypatch.setattr(kc, "EXTRA_SERIES", {})
    assert sr.not_ingested_keys() == frozenset(_FOUR)
    for key in _FOUR:
        st = sr.status(key)
        assert st["not_ingested"] is True, key
        assert "수집 코드가 없습니다" in st["reason"], key


def test_every_declared_endpoint_has_a_collapse_rule():
    """`EXTRA_ENDPOINTS` 와 `EXTRA_SERIES` 가 갈라지면 키만 있고 값이 안 오는
    조합이 생기고, 그것은 조용하다."""
    kinds = {kind for kind, _rule, _name in kc.EXTRA_SERIES.values()}
    assert kinds == set(kc.EXTRA_ENDPOINTS)
    for _kind, rule, _name in kc.EXTRA_SERIES.values():
        assert rule in (kc.COLLAPSE_SINGLE, kc.COLLAPSE_UNKNOWN)


def test_an_unregistered_key_says_so_rather_than_pretending():
    s = kx.collect_extra("NOT_A_KEY", "2024-01-02", "2024-01-03",
                         client=FakeKRX())
    assert s.values == [] and s.source == "unavailable"
    assert s.reason and "수집 경로" in s.reason


# ══════════════════════════════════════════════════════════════════════════
# B7 ★mock 이 미검증 소스를 채우지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_mock_mode_does_not_synthesize_these_series(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    for key in _FOUR:
        assert sr.new_source_mock_allowed(key) is False, key
        s = kx.collect_extra(key, "2024-01-02", "2024-01-03",
                             client=FakeKRX(configured=False))
        assert s.values == [], f"{key}: mock 이 미검증 계열을 채웠다"


# ══════════════════════════════════════════════════════════════════════════
# B9 ★기록 — REAL 만, 빈티지는 지어내지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_real_krx_series_is_recorded(eng):
    s = kx.collect_extra("VKOSPI", "2024-01-02", "2024-01-04",
                         client=FakeKRX(rows_per_day=1))
    assert mos.record_series(s, engine=eng) == 3
    rows = mos.load("VKOSPI", engine=eng)
    assert len(rows) == 3
    assert all(r.vintage_id == "" for r in rows), "빈티지를 지어냈다"


def test_an_unavailable_krx_series_is_not_recorded(eng):
    """★짝★ 사유만 있는 계열이 저장되면 나중에 실제 역사로 읽힌다."""
    s = kx.collect_extra("VKOSPI", "2024-01-02", "2024-01-04",
                         client=FakeKRX(configured=False))
    assert mos.record_series(s, engine=eng) == 0
    assert mos.load("VKOSPI", engine=eng) == []


# ══════════════════════════════════════════════════════════════════════════
# B8 ★불변 — KRX 관측이 국면 축을 움직이지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_krx_series_are_structurally_outside_the_regime_axes():
    """★불변의 **이유**를 못 박는다★

    아래 불변 테스트만으로는 공허하다 — KRX 계열이 애초에 축 계열이 아니면
    무엇을 해도 축은 안 움직인다. 그 **구조적 사실 자체**를 고정해서, 누군가
    KRX 계열을 축에 넣으면(=Macro → Allocation 배선, 별도 승인 사항) 여기가
    빨개지게 한다.
    """
    from src.engine.regime_axes import AXES

    axis_keys = {key for group in AXES.values() for part in group
                 for key, _t, _s, _w in part}
    assert axis_keys and not (axis_keys & set(kc.EXTRA_SERIES)), (
        "KRX 확장 계열이 국면 축에 들어왔다 — 별도 승인 사항이다")


def test_recording_krx_does_not_manufacture_a_vintage(eng):
    """★불변의 **기제**★ 축을 `managed` 로 올리는 유일한 통로는 빈티지 행이다.

    KRX 는 제공자 차원에서 빈티지가 없다(`PROVIDER_HAS_VINTAGE[KRX]=False`).
    기록 경로가 `retrieved_at` 같은 것을 빈티지로 채우면 **빈티지 정보가 전혀
    없는 응답이 backtest_eligible 로 인증된다**(Phase 8b 의 교훈).
    """
    s = kx.collect_extra("VKOSPI", "2024-01-02", "2024-01-10",
                         client=FakeKRX(rows_per_day=1))
    assert mos.record_series(s, engine=eng) > 0
    cov = mos.coverage(["VKOSPI"], engine=eng)
    assert cov["rows"] > 0, "행이 저장되지 않아 검사가 공허해졌다"
    assert cov["by_series"]["VKOSPI"]["with_vintage"] == 0, "빈티지를 지어냈다"
    assert cov["research_usage"] != "backtest_eligible"


def test_krx_observations_do_not_change_the_regime_axis_verdict(eng):
    """위 두 사실의 결론 — 행이 쌓여도 축 출력은 **바이트 동일**하다."""
    from src.engine.regime_axes import axis_revision_status

    before = {m: axis_revision_status(m) for m in ("kr", "us")}
    s = kx.collect_extra("VKOSPI", "2024-01-02", "2024-01-10",
                         client=FakeKRX(rows_per_day=1))
    assert mos.record_series(s, engine=eng) > 0
    after = {m: axis_revision_status(m) for m in ("kr", "us")}
    assert after == before, "KRX 적재가 국면 축 판정을 움직였다"
