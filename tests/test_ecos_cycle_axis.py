"""ECOS 공표 주기 축 — ★전부 월별로 조회하고 있었다★
==============================================================================
감사: `docs/specs/2026-08-27-capability-lineage-audit.md` 부록 3 #5 · 선행: `1fa4fbd`

## 감사의 전제가 틀렸다 — 먼저 그것부터 적는다

감사는 #5 의 근거를 *"계열의 단위·주기·공표지연이 `timing_factor_meta` 에 손으로
적혀 있다"* 고 적었다. ★실측하니 아니었다★ — `timing_factor_meta._SOURCE_TIMING`
은 **타이밍 팩터** 5개(NFCI·curve_slope·VIX 2종·범용 indicator)의 공표지연이고
전부 FRED 계열이다. ECOS 는 한 줄도 없다. 감사 #2·#4 에 이은 세 번째 정정이다.

## 실제 결함 셋

1. ★주기를 담을 자리가 없다★ — `SourceSpec` 에 `frequency` 가 없었고,
   `macro_collector` 는 `fetch_series(stat, item)` 로 **period 를 넘기지 않는다**.
   즉 비파생 37계열이 **전부 월별**로 조회된다. 그 안에 일별(기준금리·국고채·
   환율·KOSPI)과 분기로 보이는 것(GDP·경상수지)이 섞여 있다.
2. ★세 원인이 한 문자열로 뭉개진다★ — 빈 응답이면 `source="unavailable"` 이
   전부였다. **키 없음**·**좌표 틀림**·**주기 불일치** 는 처방이 전부 다르다.
3. ★날짜 포맷이 M·A 만 만든다★(잠재) — `period="D"` 로 start/end 를 생략하면
   일별로는 무효한 `2006`~`2026` 이 만들어졌다.

## 이 파일이 가장 강하게 막는 것

★모르는 것을 지어내는 것★ 이다. 주기는 37계열 전부 `None`(미검증)으로 커밋했고,
분기 TIME 표기는 확인할 수 없어 **거절**한다. `1fa4fbd` 에서 고친 결함이 바로
추측한 좌표로 회사채를 국고채라고 부른 것이다 — 같은 사고를 반복하지 않는다.

## 짝 검증

C1/C2 · C8/C9 · C13/C14 — 한쪽만 있으면 "전부 None" · "전부 사유" · "항상 성공"
구현으로도 통과한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import dataclasses  # noqa: E402

import pytest  # noqa: E402

import src.services.macro_collector as mc  # noqa: E402
from src.data import source_registry as reg  # noqa: E402

#: 리팩터링 직전 실측한 월별 URL — C10 이 문자 단위로 대조한다.
BASELINE_M_URL_TAIL = "/722Y001/M/200608/202608/0101000"


def _ecos_series_specs():
    return [s for s in reg.specs_by_provider(reg.ECOS) if not s.derived_from]


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


@pytest.fixture
def captured(monkeypatch):
    """`requests.get` 을 가로채 URL 을 본다."""
    seen: dict = {}

    def fake_get(url, timeout=None, **kw):
        seen["url"] = url
        return _Resp(seen.get("payload", {}))

    monkeypatch.setattr(mc.requests, "get", fake_get)
    monkeypatch.setattr(mc.BokClient, "_throttle", lambda self: None)
    return seen


def _client(monkeypatch):
    monkeypatch.setenv("BOK_API_KEY", "k" * 20)
    return mc.BokClient()


# ══════════════════════════════════════════════════════════════════════════
# 1) 주기 축 — ★아무것도 지어내지 않았다★
# ══════════════════════════════════════════════════════════════════════════
def test_no_series_declares_a_guessed_frequency():
    """C1 — 37계열 전부 `frequency is None`.

    ★이것이 이 변경의 핵심 주장이다★ 주기를 담을 자리를 만들되, 메타 API 가
    말해 주기 전까지는 **모른다고 적는다**. 하나라도 채우면 그 값은 검증된 사실과
    구분되지 않는다.
    """
    specs = _ecos_series_specs()
    assert len(specs) == 37, f"ECOS 비파생 계열 수가 바뀌었다: {len(specs)}"
    guessed = [s.key for s in specs if s.frequency is not None]
    assert guessed == [], f"주기를 추측해 채운 계열이 있다: {guessed}"


def test_the_frequency_field_exists_and_holds_what_it_is_given():
    """C2 ★짝★ — "필드를 안 만들었다" 나 "항상 None 을 돌려준다" 를 배제한다.

    C1 만 있으면 필드를 아예 없애 버려도 통과한다(`getattr` 이 없으니 실패하겠지만,
    `frequency = None` 이라는 클래스 상수로도 통과한다). 값을 넣으면 보존되는지
    확인해야 축이 **실제로 존재**한다고 말할 수 있다.
    """
    assert "frequency" in {f.name for f in dataclasses.fields(reg.SourceSpec)}
    for cyc in reg.ECOS_CYCLES:
        spec = reg.SourceSpec(key="X", label="x", provider=reg.ECOS,
                              endpoint="1/2", frequency=cyc)
        assert spec.frequency == cyc


def test_the_cycle_vocabulary_is_fixed():
    """C2 보강 — 어휘가 `D·M·Q·A` 다. 자유 문자열이면 대조가 불가능해진다."""
    assert reg.ECOS_CYCLES == ("D", "M", "Q", "A")


# ══════════════════════════════════════════════════════════════════════════
# 2) ★트립와이어★ — 수집 주기는 바뀌지 않았다
# ══════════════════════════════════════════════════════════════════════════
def test_the_collector_still_does_not_pass_a_period(monkeypatch):
    """C3 — ★승인된 선택: 기록·대조만, 조회는 M 유지★

    주기를 알게 됐다고 수집기가 그것으로 조회하기 시작하면, 키가 들어오는 순간
    사람 확인 없이 `collect_all()` 출력이 달라진다. `verified_live` 와 같은
    규율로 사람이 올린다.

    ★배선하려면 이 테스트를 의식적으로 고쳐야 한다.★ 그것이 목적이다.

    ★소스를 읽지 않고 **호출을 본다**★
    ─────────────────────────────────────────────────────────────────────────
    첫 판은 `inspect.getsource` + `tokenize` 로 소스 토큰을 검사했다. 전체
    스위트에서 **실패했다** — `getsource` 는 로드된 코드객체의 줄번호로 **디스크의
    현재 파일**을 읽으므로, 실행 중에 그 파일이 편집되면 엉뚱한 구간을 집는다.
    (실제로 그렇게 됐다. 스위트가 도는 동안 `macro_collector.py` 의 주석을 고쳤다.)

    호출을 직접 보면 그 취약성이 사라지고, 무엇보다 **실제로 중요한 것**을 본다 —
    소스에 `period` 라는 글자가 있느냐가 아니라 조회가 월별로 나가느냐다.
    """
    calls: list[tuple] = []

    def spy(self, stat_code, item_code="0", start=None, end=None,
            period="M", limit=1000):
        calls.append((stat_code, item_code, period))
        return [], []

    monkeypatch.setattr(mc.BokClient, "fetch_series", spy)
    monkeypatch.setattr(mc.BokClient, "is_configured", property(lambda self: True))
    mc.MacroCollector().collect_all(use_cache=False)

    assert calls, "수집기가 BokClient.fetch_series 를 부르지 않았다 — 가드가 무의미하다"
    assert len(calls) == 37, f"ECOS 조회 수가 바뀌었다: {len(calls)}"
    offenders = sorted({p for _, _, p in calls} - {"M"})
    assert offenders == [], \
        f"수집기가 월별이 아닌 주기로 조회한다: {offenders} — 주기 배선은 별도 승인 사항이다"


def test_the_collection_coordinate_contract_is_unchanged():
    """C4 — `ecos_collection_targets()` 는 여전히 37행 · 5-튜플.

    ★frequency 를 여기 넣지 않았다★ — 넣으면 다음 사람이 그대로 배선한다.
    주기는 `get_spec(key).frequency` 로 읽는다.
    """
    t = reg.ecos_collection_targets()
    assert len(t) == 37, f"수집 좌표 수가 바뀌었다: {len(t)}"
    assert all(len(row) == 5 for row in t), "좌표 튜플 폭이 바뀌었다"


def test_the_series_count_is_unchanged():
    """C4 짝 — 수집 범위 자체가 안 바뀌었다(ECOS 40 + FRED 21)."""
    assert len(mc.MacroCollector().collect_all().series) == 61


# ══════════════════════════════════════════════════════════════════════════
# 3) 사유 — ★네 원인을 가른다★
# ══════════════════════════════════════════════════════════════════════════
def test_no_key_says_so_and_does_not_blame_the_coordinates():
    """C5 — 키가 없으면 조회를 시도조차 안 했다. 좌표 이야기를 하면 거짓이다."""
    r = reg.unavailable_reason_for("KR_CALL_RATE", configured=False)
    assert r == reg.REASON_NO_KEY
    assert "키" in r


def test_an_unverified_coordinate_says_it_is_unverified():
    """C6 — `verified_live=False` → 기존 `_UNVERIFIED_NOTE` 를 **재사용**한다."""
    assert reg.get_spec("KR_CALL_RATE").verified_live is False
    r = reg.unavailable_reason_for("KR_CALL_RATE", configured=True)
    assert r == reg._UNVERIFIED_NOTE


def test_a_verified_coordinate_that_comes_back_empty_says_something_else():
    """C7 — 검증된 좌표가 비면 원인이 다르다(쿼터·장애·미공표)."""
    assert reg.get_spec("KR_BASE_RATE").verified_live is True
    r = reg.unavailable_reason_for("KR_BASE_RATE", configured=True)
    assert r == reg.REASON_EMPTY_RESPONSE


def test_a_known_non_monthly_cycle_is_appended_not_substituted(monkeypatch):
    """C8 — ★사유를 덧붙이지 덮어쓰지 않는다★

    Phase 1 에서 `not_ingested` 가 "미검증" 을 지워 원인을 잃었다. 원인은 둘 다일
    수 있다 — 좌표가 미검증이면서 주기도 안 맞을 수 있고, 하나를 지우면 그 정보가
    사라진다.
    """
    spec = reg.get_spec("KR_CALL_RATE")
    monkeypatch.setitem(reg._BY_KEY, "KR_CALL_RATE",
                        dataclasses.replace(spec, frequency="D"))
    r = reg.unavailable_reason_for("KR_CALL_RATE", configured=True)
    assert reg._UNVERIFIED_NOTE in r, "기존 사유가 지워졌다"
    assert "주기 불일치" in r and "D" in r, "주기 의심이 붙지 않았다"


def test_a_monthly_cycle_adds_no_suspicion(monkeypatch):
    """C8 짝 — "주기가 알려지면 무조건 의심" 을 배제한다. M 은 수집기와 맞다."""
    spec = reg.get_spec("KR_CALL_RATE")
    monkeypatch.setitem(reg._BY_KEY, "KR_CALL_RATE",
                        dataclasses.replace(spec, frequency="M"))
    r = reg.unavailable_reason_for("KR_CALL_RATE", configured=True)
    assert "주기 불일치" not in r


def test_every_unavailable_series_has_a_reason_and_no_other_does():
    """C9 ★짝★ — 값이 온 계열은 `reason is None` 이다.

    "항상 사유를 채운다" 는 구현이면 이 필드는 "왜 비었나" 에 답하는 것이 아니라
    그냥 또 하나의 설명문이 된다. ★파생 스프레드도 포함★ — 그것의 실패 원인은
    넷째다(원계열 부재).
    """
    series = mc.MacroCollector().collect_all().series
    missing = [k for k, v in series.items() if v.source == "unavailable" and not v.reason]
    spurious = [k for k, v in series.items() if v.source != "unavailable" and v.reason]
    assert missing == [], f"사유 없는 unavailable: {missing}"
    assert spurious == [], f"값이 있는데 사유가 붙었다: {spurious}"


def test_a_derived_spread_names_the_missing_leg():
    """C9 보강 — 넷째 원인. 어느 다리가 빠졌는지 말하지 않으면 사용자는
    스프레드가 고장난 줄 안다 — 고쳐야 할 곳은 원계열 쪽이다."""
    s = mc.MacroCollector()._derive_spread(
        None, None, key="X", name="x", unit="%p")
    assert s.source == "unavailable"
    assert "원계열" in s.reason and "스프레드" in s.reason


# ══════════════════════════════════════════════════════════════════════════
# 4) 날짜 포맷 — ★아는 것만 만들고 모르는 것은 거절한다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_monthly_url_is_byte_identical_to_the_baseline(captured, monkeypatch):
    """C10 — ★기존 호출이 한 글자도 안 바뀌었다★

    이것이 이 변경의 무해함에 대한 실제 근거다. 골든 스냅샷은 `MacroSeries` 를
    직렬화하지 않으므로 바이트 동일성만으로는 증명이 못 된다.
    """
    monkeypatch.setattr(mc, "_history_years", lambda: 20)
    monkeypatch.setattr(mc, "datetime", _FixedClock)
    _client(monkeypatch).fetch_series("722Y001", "0101000")
    assert captured["url"].endswith(BASELINE_M_URL_TAIL), captured["url"]


class _FixedClock:
    @staticmethod
    def now():
        import datetime as _d
        return _d.datetime(2026, 8, 27)


def test_daily_builds_an_eight_digit_range(captured, monkeypatch):
    """C11 — `period="D"` 가 `YYYYMMDD` 를 만든다. 예전엔 `2006`~`2026` 이었다."""
    monkeypatch.setattr(mc, "_history_years", lambda: 20)
    monkeypatch.setattr(mc, "datetime", _FixedClock)
    _client(monkeypatch).fetch_series("722Y001", "0101000", period="D")
    assert "/D/20060827/20260827/" in captured["url"], captured["url"]


def test_annual_still_builds_a_four_digit_range(captured, monkeypatch):
    """C11 짝 — 기존 A 경로가 안 깨졌다."""
    monkeypatch.setattr(mc, "_history_years", lambda: 20)
    monkeypatch.setattr(mc, "datetime", _FixedClock)
    _client(monkeypatch).fetch_series("200Y002", "1400", period="A")
    assert "/A/2006/2026/" in captured["url"], captured["url"]


def test_quarterly_is_refused_rather_than_invented(captured, monkeypatch):
    """C12 — ★이 계획의 핵심 변이가 여기서 죽는다★

    ECOS 분기 TIME 표기(`2024Q1`? `20241`?)를 오프라인에서 확인할 수 없다.
    추측한 좌표로 회사채를 국고채라고 불렀던 것과 정확히 같은 종류의 오류이므로,
    포맷을 지어내는 대신 **호출하지 않는다**.
    """
    ts, vals = _client(monkeypatch).fetch_series("200Y002", "1400", period="Q")
    assert (ts, vals) == ([], [])
    assert "url" not in captured, "지어낸 분기 포맷으로 실제 호출했다"


def test_explicit_quarterly_bounds_are_honoured(captured, monkeypatch):
    """C12 짝 — "Q 는 무조건 막는다" 가 아니다. 사람이 표기를 알면 쓸 수 있다."""
    _client(monkeypatch).fetch_series("200Y002", "1400", period="Q",
                                      start="2020Q1", end="2026Q2")
    assert "/Q/2020Q1/2026Q2/" in captured["url"], captured["url"]


# ══════════════════════════════════════════════════════════════════════════
# 5) 메타 클라이언트 — ★모른다는 것을 설계에 반영했다★
# ══════════════════════════════════════════════════════════════════════════
def test_cycle_is_extracted_when_a_candidate_key_is_present():
    """C13 — 후보 키 중 하나가 있으면 주기를 낸다."""
    for k in mc.META_CYCLE_KEYS:
        cyc, why = mc.cycle_from_meta_row({k: "D", "ITEM_CODE": "x"})
        assert cyc == "D" and why is None, f"{k} 에서 못 뽑았다"


def test_an_unrecognised_row_returns_none_and_says_why():
    """C14 ★짝★ — ★기본값 `"M"` 을 돌려주지 않는다★

    돌려주면 그 값은 "확인된 월별" 과 구분되지 않는다 — 이 축을 만든 이유가
    정확히 그것이다.
    """
    cyc, why = mc.cycle_from_meta_row({"ITEM_CODE": "x", "ITEM_NAME": "y"})
    assert cyc is None and why and "주기 필드가 없습니다" in why
    cyc2, why2 = mc.cycle_from_meta_row({"CYCLE": "격주"})
    assert cyc2 is None and why2 and "해석할 수 없습니다" in why2


def test_meta_calls_share_the_throttle_and_key_check(monkeypatch):
    """C15 — 분당 한도는 서비스별이 아니라 **키별**이다. 경로가 둘이면 한도를
    넘긴 쪽이 조용히 실패한다."""
    hits: list[int] = []
    monkeypatch.setattr(mc.BokClient, "_throttle", lambda self: hits.append(1))
    monkeypatch.setattr(mc.requests, "get",
                        lambda url, timeout=None, **kw: _Resp(
                            {"StatisticItemList": {"row": [{"CYCLE": "M"}]}}))
    rows, err = _client(monkeypatch).fetch_item_list("722Y001")
    assert err is None and rows and hits == [1]

    monkeypatch.delenv("BOK_API_KEY", raising=False)
    rows2, err2 = mc.BokClient().fetch_item_list("722Y001")
    assert rows2 == [] and err2 == reg.REASON_NO_KEY
    assert hits == [1], "키 없이 스로틀·호출까지 갔다"


def test_an_empty_meta_response_relays_the_servers_own_message(monkeypatch):
    """C14 보강 — ECOS 오류 문구를 지어내지 않고 **있으면 그대로** 전달한다."""
    monkeypatch.setattr(mc.BokClient, "_throttle", lambda self: None)
    monkeypatch.setattr(mc.requests, "get",
                        lambda url, timeout=None, **kw: _Resp(
                            {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}))
    rows, err = _client(monkeypatch).fetch_item_list("999Y999")
    assert rows == [] and "해당하는 데이터가 없습니다." in err


# ══════════════════════════════════════════════════════════════════════════
# 6) 검증 스크립트 — ★건너뛴 것을 성공이라 하지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_verify_script_skips_loudly_without_a_key(monkeypatch):
    """C16 — `{"skipped": 사유}`. "0건 성공" 은 "확인했더니 문제없었다" 로 읽힌다."""
    import scripts.verify_ecos_meta as v

    monkeypatch.delenv("BOK_API_KEY", raising=False)
    out = v.collect()
    assert out == {"skipped": reg.REASON_NO_KEY}
    assert "checked" not in out


def _registry_frequencies() -> dict[str, dict[str, str | None]]:
    """★두 읽기 경로를 **둘 다** 본다★

    `specs_by_provider()` 는 `_SPECS`(튜플)를 읽고 `get_spec()` 은 `_BY_KEY`(딕트)를
    읽는다. 한쪽만 검사하면 다른 쪽에 쓴 변경을 놓친다 — 실제로 첫 판의 C17 이
    `_SPECS` 만 봤고, `_BY_KEY` 에 쓰는 변이(V10)가 살아남았다.
    """
    return {
        "specs": {s.key: s.frequency for s in _ecos_series_specs()},
        "by_key": {s.key: reg.get_spec(s.key).frequency for s in _ecos_series_specs()},
    }


def test_the_two_registry_read_paths_agree():
    """C17 짝 — ★`_SPECS` 와 `_BY_KEY` 가 갈라질 수 있다★

    같은 사실에 두 읽기 경로가 있으면 언젠가 갈라지고, 갈라진 레지스트리는
    "단일 출처" 라는 이 모듈의 존재 이유를 무효로 만든다.
    """
    views = _registry_frequencies()
    assert views["specs"] == views["by_key"], "두 읽기 경로가 어긋난다"


def test_the_verify_script_never_writes_the_registry(monkeypatch):
    """C17 — ★발견한 주기를 자동으로 올리지 않는다★

    `verified_live` 와 같은 규율이다. 한 번 응답이 왔다고 코드가 사실을 올리면
    그 필드는 "확인됨" 이 아니라 "언젠가 한 번 그렇게 보였음" 이 된다.

    ★두 읽기 경로를 모두 본다★ — 첫 판은 `_SPECS` 만 봐서 `_BY_KEY` 에 쓰는
    변이를 놓쳤다.
    """
    import scripts.verify_ecos_meta as v

    monkeypatch.setenv("BOK_API_KEY", "k" * 20)
    monkeypatch.setattr(mc.BokClient, "_throttle", lambda self: None)
    monkeypatch.setattr(
        mc.BokClient, "fetch_item_list",
        lambda self, stat: ([{"ITEM_CODE": c, "CYCLE": "D"}
                             for c in ("0101000", "010195000", "010210000")], None))

    before = _registry_frequencies()
    out = v.collect()
    after = _registry_frequencies()

    assert before == after, "스크립트가 레지스트리를 고쳤다"
    for view, freqs in after.items():
        assert all(f is None for f in freqs.values()), f"{view} 에 주기가 올라갔다"
    assert out["checked"] == 37
    assert out["mismatched"] >= 1, "M 이 아닌 주기를 찾고도 불일치로 세지 않았다"
    # ★산문을 단언하지 않는다★ 원래 여기서 `note` 의 정확한 문구를 확인했는데,
    # 스크립트를 확장하며 문구를 다듬자 **동작은 그대로인데 테스트가 빨개졌다**.
    # 진짜 가드는 위의 `before == after`(두 읽기 경로) 다 — 문구가 아니라 그것이
    # "레지스트리를 고치지 않았다" 를 말한다.
    assert "note" in out, "무엇을 했고 안 했는지 리포트가 말하지 않는다"
