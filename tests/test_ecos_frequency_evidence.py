"""ECOS 주기 **증거 인프라** — ★검증할 수 없다는 것을 정직하게 담는다★
==============================================================================
감사: `docs/specs/2026-08-27-ecos-data-contract-audit.md` · 선행: `432f554`

## 이 파일이 지키는 것

`432f554` 가 주기 축을 세우고 37계열 전부 `None` 으로 커밋했다. 다음 질문은
"미검증에서 검증됨으로 갈 수 있는가" 였고, 실측이 답을 강제했다 — ★갈 수 없다★.
`BOK_API_KEY` 가 없고 `ecos.bok.or.kr` 이 프록시 CONNECT 403 이다.

그래서 검증하지 않고 **검증 가능한 날을 준비**한다. 이 파일은 그 준비물이
★거짓을 담을 수 없게★ 만든다.

## 왜 `verified_live` 처럼 만들지 않았나

`verified_live=True` 인 ECOS 8계열의 근거를 추적하면 **커밋 메시지 주장 하나**가
전부다. 검증 경로인 `verify_connection.py::check_ecos` 는 값의 범위만 볼 뿐 주기도
TIME 문자열도 기록하지 않는다. ★플래그는 코드에 있는데 관측은 어디에도 없는 상태★
이고, 그것이 정확히 이번에 피하려는 것이다.

그래서 주기는 **파일에 관측을 남기고 레지스트리가 읽는다**. 사실과 출처가 붙어
다니고, diff 가 증거의 변화를 보여 준다.

## 짝 검증

G1/G2 · G9/G10 — 한쪽만 있으면 "로더를 안 만들었다" · "키가 있어도 안 부른다"
구현으로도 통과한다. ★G7 은 `432f554` 에서 실제로 변이가 살아남았던 자리다.★
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import dataclasses  # noqa: E402
import importlib  # noqa: E402
import json  # noqa: E402

import pytest  # noqa: E402
import scripts.verify_ecos_meta as v  # noqa: E402

import src.services.macro_collector as mc  # noqa: E402
from src.data import source_registry as reg  # noqa: E402

AUDIT_DOC = (reg.FREQ_EVIDENCE_PATH.parent / "2026-08-27-ecos-data-contract-audit.md")


def _ecos_series_specs():
    return [s for s in reg.specs_by_provider(reg.ECOS) if not s.derived_from]


def _reload(monkeypatch, evidence: dict | None, floor: str = "E2"):
    """증거를 갈아 끼우고 레지스트리를 다시 구성한다(임포트 부작용 없이)."""
    monkeypatch.setattr(reg, "_FREQ_EVIDENCE", evidence or {})
    monkeypatch.setattr(reg, "_FREQ_EVIDENCE_FLOOR", floor)
    return {s.key: reg._apply_frequency_evidence(s).frequency for s in reg._RAW_SPECS}


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p


# ══════════════════════════════════════════════════════════════════════════
# 1) ★증거 파일은 비어서 커밋된다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_evidence_file_ships_empty():
    """G1 — ★이 단언이 이 커밋의 정직성 그 자체다★

    비어 있는 것이 결함이 아니라 **현재 사실**이다. 채워진 척하면 추측이 검증된
    사실과 구분되지 않는다.
    """
    doc = json.loads(reg.FREQ_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert doc["series"] == {}, f"증거 없이 주기가 채워졌다: {sorted(doc['series'])}"
    assert doc["min_grade_to_apply"] in reg.EVIDENCE_GRADES
    assert "why_empty" in doc, "왜 비었는지 파일 스스로 말해야 한다"


def test_every_ecos_series_is_still_unverified():
    """G1 짝 — 레지스트리 쪽에서도 37/37 이 `None` 이다."""
    specs = _ecos_series_specs()
    assert len(specs) == 37
    assert [s.key for s in specs if s.frequency is not None] == []


def test_evidence_actually_reaches_the_registry(monkeypatch):
    """G2 ★짝★ — "로더를 안 만들었다" 를 배제한다.

    G1 만 있으면 `_apply_frequency_evidence` 가 아무것도 안 해도 통과한다.
    """
    got = _reload(monkeypatch, {"KR_GDP": {"frequency": "Q", "grade": "E3"}})
    assert got["KR_GDP"] == "Q", "증거가 레지스트리에 닿지 않는다"
    assert got["KR_CPI"] is None, "증거 없는 계열까지 채워졌다"


def test_frequency_evidence_for_returns_the_provenance(monkeypatch):
    """G2 보강 — ★사실만이 아니라 출처도 조회할 수 있어야 한다★"""
    ev = {"frequency": "Q", "grade": "E3", "evidence_source": "StatisticItemList"}
    monkeypatch.setattr(reg, "_FREQ_EVIDENCE", {"KR_GDP": ev})
    assert reg.frequency_evidence_for("KR_GDP")["evidence_source"] == "StatisticItemList"
    assert reg.frequency_evidence_for("KR_CPI") is None


# ══════════════════════════════════════════════════════════════════════════
# 2) 로더는 ★없거나 깨져도 죽지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_missing_evidence_file_is_not_an_error(monkeypatch, tmp_path):
    """G3 — 증거가 없는 것은 오류가 아니라 정상 상태다(지금이 그렇다).

    여기서 터지면 레지스트리를 임포트하는 **모든 경로**가 함께 죽는다 —
    "주기를 모른다" 보다 훨씬 나쁜 결과다.
    """
    monkeypatch.setattr(reg, "FREQ_EVIDENCE_PATH", tmp_path / "없는파일.json")
    series, floor = reg._load_frequency_evidence()
    assert series == {} and floor in reg.EVIDENCE_GRADES


@pytest.mark.parametrize("body", ["{{{ 깨진 json", '{"series": "딕트가 아님"}', "null"])
def test_a_corrupt_evidence_file_is_not_an_error(monkeypatch, tmp_path, body):
    """G4 — 깨진 파일도 조용히 `None` 으로 떨어진다."""
    p = tmp_path / "e.json"
    p.write_text(body, encoding="utf-8")
    monkeypatch.setattr(reg, "FREQ_EVIDENCE_PATH", p)
    series, floor = reg._load_frequency_evidence()
    assert series == {} and floor in reg.EVIDENCE_GRADES


# ══════════════════════════════════════════════════════════════════════════
# 3) ★확신이 모자라면 사실이 되지 않는다★
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("grade,applied", [("E0", False), ("E1", False),
                                           ("E2", True), ("E3", True)])
def test_low_confidence_evidence_is_not_applied(monkeypatch, grade, applied):
    """G5 — `min_grade_to_apply` 미만은 적용하지 않는다.

    E1 은 "값이 오는 것은 봤으나 주기를 확정 못 함" 이다. 그것을 사실로 올리면
    `verified_live` 가 빠진 함정에 그대로 빠진다.
    """
    got = _reload(monkeypatch, {"KR_GDP": {"frequency": "Q", "grade": grade}}, floor="E2")
    assert (got["KR_GDP"] == "Q") is applied


@pytest.mark.parametrize("bad", ["W", "monthly", "", None, "MM", 3])
def test_a_value_outside_the_vocabulary_is_ignored(monkeypatch, bad):
    """G6 — `ECOS_CYCLES` 밖의 값은 사실이 아니다."""
    got = _reload(monkeypatch, {"KR_GDP": {"frequency": bad, "grade": "E3"}})
    assert got["KR_GDP"] is None


def test_a_missing_grade_is_ignored(monkeypatch):
    """G5 짝 — 등급이 아예 없으면 적용하지 않는다(등급 검사를 우회할 수 없다)."""
    got = _reload(monkeypatch, {"KR_GDP": {"frequency": "Q"}})
    assert got["KR_GDP"] is None


# ══════════════════════════════════════════════════════════════════════════
# 4) ★두 읽기 경로가 갈라지지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_two_registry_read_paths_agree_when_evidence_exists(tmp_path, monkeypatch):
    """G7 — ★증거가 **있을 때** 두 경로가 같은 사실을 말한다★

    이 테스트를 처음엔 지금 상태(증거 파일이 빔)에서만 확인했고, 그래서
    **공허했다** — 증거가 없으면 `_apply_frequency_evidence` 가 같은 객체를 그대로
    돌려주므로 `_SPECS` 와 `_RAW_SPECS` 의 원소가 **동일 객체**다. `_BY_KEY` 를
    어느 쪽에서 만들든 통과한다(변이 W8 이 그렇게 살아남았다).

    갈라짐은 **증거가 붙는 순간에만** 드러난다. 그 상태를 만들어서 본다.
    ★`432f554` 에 이어 이 가드가 공허했던 것이 두 번째다.★
    """
    ev = tmp_path / "e.json"
    ev.write_text(json.dumps({
        "schema": 1, "min_grade_to_apply": "E2",
        "series": {"KR_GDP": {"frequency": "Q", "grade": "E3"},
                   "KOSPI": {"frequency": "D", "grade": "E3"}},
    }), encoding="utf-8")
    monkeypatch.setenv("ECOS_FREQ_EVIDENCE_PATH", str(ev))

    mod = importlib.reload(reg)
    try:
        assert mod.get_spec("KR_GDP").frequency == "Q", "증거가 반영되지 않았다"
        by_specs = {s.key: s.frequency for s in mod._SPECS}
        by_key = {k: s.frequency for k, s in mod._BY_KEY.items()}
        assert by_specs == by_key, "두 읽기 경로가 어긋난다 — _BY_KEY 를 따로 만들었는가?"
        for s in mod._SPECS:
            assert mod.get_spec(s.key) is s, f"{s.key} 가 두 경로에서 다른 객체다"
    finally:
        monkeypatch.delenv("ECOS_FREQ_EVIDENCE_PATH", raising=False)
        importlib.reload(reg)


def test_specs_are_built_from_raw_specs():
    """G7 짝 — `_SPECS` 가 `_RAW_SPECS` 에서 나온다(개수·키·순서가 보존된다)."""
    assert len(reg._SPECS) == len(reg._RAW_SPECS)
    assert [s.key for s in reg._SPECS] == [s.key for s in reg._RAW_SPECS]
    for s in reg._SPECS:
        assert reg.get_spec(s.key) is s


# ══════════════════════════════════════════════════════════════════════════
# 5) ★트립와이어 — 증거가 생겨도 수집 주기는 그대로다★
# ══════════════════════════════════════════════════════════════════════════
def test_evidence_does_not_change_what_the_collector_queries(monkeypatch):
    """G8 — ★증거가 있어도 수집기는 여전히 전부 M 으로 조회한다★

    `collect_all()` 은 regime 과 allocation 경로까지 닿는다(감사 §1 의존 지도).
    주기를 알게 됐다고 조회가 달라지면, 키가 들어오는 순간 사람 확인 없이 그
    경로들의 입력이 바뀐다. 배선은 **별도 승인**이다.
    """
    monkeypatch.setattr(reg, "_FREQ_EVIDENCE",
                        {s.key: {"frequency": "D", "grade": "E3"} for s in reg._RAW_SPECS})
    calls: list[str] = []

    def spy(self, stat_code, item_code="0", start=None, end=None,
            period="M", limit=1000):
        calls.append(period)
        return [], []

    monkeypatch.setattr(mc.BokClient, "fetch_series", spy)
    monkeypatch.setattr(mc.BokClient, "is_configured", property(lambda self: True))
    mc.MacroCollector().collect_all(use_cache=False)

    assert len(calls) == 37, f"ECOS 조회 수가 바뀌었다: {len(calls)}"
    assert set(calls) == {"M"}, f"월별이 아닌 조회가 생겼다: {sorted(set(calls) - {'M'})}"


# ══════════════════════════════════════════════════════════════════════════
# 6) 프로브 — ★같은 규율을 쓰고, 키가 없으면 걸지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_probe_shares_the_throttle_and_returns_raw_time(monkeypatch):
    """G9 — 분당 한도는 서비스별이 아니라 **키별**이다.

    그리고 ★`TIME` 을 해석하지 않고 그대로 남긴다★ — 포맷이 무엇인지가 질문인데
    파싱해 정규화하면 답을 지워 버린다.
    """
    hits: list[int] = []
    monkeypatch.setenv("BOK_API_KEY", "k" * 20)
    monkeypatch.setattr(mc.BokClient, "_throttle", lambda self: hits.append(1))
    monkeypatch.setattr(mc.requests, "get", lambda url, timeout=None, **kw: _Resp(
        {"StatisticSearch": {"row": [{"TIME": "2024Q1", "DATA_VALUE": "1"}]}}))

    r = mc.BokClient().probe_series("200Y002", "1400", "Q", "2020Q1", "2024Q4")
    assert hits == [1], "프로브가 스로틀을 건너뛴다"
    assert r["status"] == "ok" and r["time_sample"] == ["2024Q1"]
    assert r["http_status"] == 200 and "DATA_VALUE" in r["row_keys"]


def test_probe_does_not_call_without_a_key(monkeypatch):
    """G10 ★짝★ — "키가 있어도 안 부른다" 와 "키가 없어도 부른다" 를 둘 다 배제."""
    called: list[int] = []
    monkeypatch.delenv("BOK_API_KEY", raising=False)
    monkeypatch.setattr(mc.BokClient, "_throttle", lambda self: called.append(1))
    monkeypatch.setattr(mc.requests, "get",
                        lambda *a, **k: called.append(1) or _Resp({}))

    r = mc.BokClient().probe_series("200Y002", "1400", "M", "202401", "202403")
    assert r["status"] == "no_key" and r["reason"] == reg.REASON_NO_KEY
    assert called == [], "키 없이 호출까지 갔다"


def test_probe_relays_the_servers_own_error(monkeypatch):
    """G9 보강 — ECOS 오류 문구를 지어내지 않고 있으면 그대로 전달한다."""
    monkeypatch.setenv("BOK_API_KEY", "k" * 20)
    monkeypatch.setattr(mc.BokClient, "_throttle", lambda self: None)
    monkeypatch.setattr(mc.requests, "get", lambda url, timeout=None, **kw: _Resp(
        {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}))
    r = mc.BokClient().probe_series("999Y999", "0", "M", "202401", "202403")
    assert r["status"] == "empty" and r["ecos_code"] == "INFO-200"
    assert "해당하는" in r["ecos_message"]


def test_the_production_fetch_path_is_untouched(monkeypatch):
    """G11 — ★`period="M"` URL 이 여전히 문자 단위로 동일하다★

    프로브를 더하면서 운영 경로를 건드리지 않았다는 실제 근거다. 골든 스냅샷은
    `MacroSeries` 를 직렬화하지 않으므로 그것만으로는 증명이 못 된다.
    """
    seen: dict = {}
    monkeypatch.setenv("BOK_API_KEY", "k" * 20)
    monkeypatch.setattr(mc.BokClient, "_throttle", lambda self: None)
    monkeypatch.setattr(mc, "_history_years", lambda: 20)
    monkeypatch.setattr(mc, "datetime", _FixedClock)
    monkeypatch.setattr(mc.requests, "get",
                        lambda url, timeout=None, **kw: (seen.setdefault("url", url),
                                                         _Resp({}))[1])
    mc.BokClient().fetch_series("722Y001", "0101000")
    assert seen["url"].endswith("/722Y001/M/200608/202608/0101000"), seen["url"]


class _FixedClock:
    @staticmethod
    def now():
        import datetime as _d
        return _d.datetime(2026, 8, 27)


# ══════════════════════════════════════════════════════════════════════════
# 7) 스크립트 — ★관측 없이는 쓰지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_probe_records_representative_time_values(monkeypatch):
    """G12 — 아티팩트에 대표 `TIME` 이 남는다. Q2 의 답이 거기서 나온다."""
    monkeypatch.setenv("BOK_API_KEY", "k" * 20)
    monkeypatch.setattr(mc.BokClient, "_throttle", lambda self: None)
    monkeypatch.setattr(mc.BokClient, "fetch_item_list",
                        lambda self, stat: ([{"ITEM_CODE": "0101000", "CYCLE": "D"}], None))
    monkeypatch.setattr(mc.BokClient, "probe_series",
                        lambda self, *a, **k: {"period": a[2], "status": "ok",
                                               "row_count": 3,
                                               "time_sample": ["20240102"],
                                               "row_keys": ["DATA_VALUE", "TIME"]})
    out = v.collect()
    row = next(r for r in out["rows"] if r["key"] == "KR_BASE_RATE")
    assert row["time_sample"] == ["20240102"]
    assert row["observed_frequency"] == "D" and row["grade"] == "E3"
    assert row["collector_mismatch"], "D 인데 M 으로 조회하는 것을 불일치로 세지 않았다"


def test_the_script_does_not_write_without_the_flag(monkeypatch, capsys):
    """G13 — ★`--write` 없이는 증거 파일을 쓰지 않는다★ 기본은 읽기 전용이다."""
    before = reg.FREQ_EVIDENCE_PATH.read_text(encoding="utf-8")
    monkeypatch.setattr(v, "collect", lambda **kw: {
        "rows": [{"key": "KR_GDP", "observed_frequency": "Q", "grade": "E3"}],
        "checked": 1})
    assert v.main([]) == 0
    assert reg.FREQ_EVIDENCE_PATH.read_text(encoding="utf-8") == before
    assert "evidence" not in json.loads(capsys.readouterr().out)


def test_a_skipped_run_writes_nothing(monkeypatch, capsys):
    """G14 — 키가 없으면 `{"skipped": 사유}`. ★"0건 성공" 이라고 말하지 않는다★

    0건 성공은 "확인했더니 문제가 없었다" 로 읽히고, 실제로는 아무것도 확인하지
    않았다. `--write` 를 줘도 관측이 없으므로 쓰지 않는다.
    """
    before = reg.FREQ_EVIDENCE_PATH.read_text(encoding="utf-8")
    monkeypatch.delenv("BOK_API_KEY", raising=False)
    assert v.collect() == {"skipped": reg.REASON_NO_KEY}
    assert v.main(["--write"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["skipped"] == reg.REASON_NO_KEY and out["evidence"]["written"] == []
    assert reg.FREQ_EVIDENCE_PATH.read_text(encoding="utf-8") == before
    assert "checked" not in out


def test_writing_only_records_sufficient_evidence(monkeypatch, tmp_path):
    """G13 짝 — `--write` 가 **실제로는 쓴다**(항상-안-씀 구현 배제). 단 E2 이상만."""
    p = tmp_path / "e.json"
    p.write_text(json.dumps({"schema": 1, "min_grade_to_apply": "E2", "series": {}}),
                 encoding="utf-8")
    monkeypatch.setattr(v, "FREQ_EVIDENCE_PATH", p)
    monkeypatch.setattr(reg, "FREQ_EVIDENCE_PATH", p)
    res = v.write_evidence({"rows": [
        {"key": "KR_GDP", "observed_frequency": "Q", "grade": "E3",
         "time_sample": ["2024Q1"], "evidence_source": "StatisticItemList"},
        {"key": "KR_CPI", "observed_frequency": None, "grade": "E1"},
    ]})
    assert res["written"] == ["KR_GDP"], "확신이 모자란 관측까지 기록했다"
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["series"]["KR_GDP"]["frequency"] == "Q"
    assert doc["series"]["KR_GDP"]["probed_at"], "언제 봤는지가 없다"


def test_the_quarterly_request_notation_is_still_not_invented():
    """G12 보강 — ★프로브 창에 `Q` 가 **없다**★

    분기 요청 표기가 바로 알아내려는 것이므로, 여기 적으면 순환이 된다.
    (부록 9 — `1fa4fbd` 에서 추측한 항목코드로 회사채를 국고채라고 부른 전례)
    """
    assert "Q" not in v._PROBE_WINDOWS
    assert set(v._PROBE_WINDOWS) == {"D", "M", "A"}


# ══════════════════════════════════════════════════════════════════════════
# 8) 문서와 코드가 어긋나지 않는다
# ══════════════════════════════════════════════════════════════════════════
def test_the_audit_document_lists_every_series_as_unverified():
    """G15 — ★감사문이 37계열 전부를 E0 으로 적는다★

    문서가 코드보다 낙관적이 되는 것이 이 저장소가 반복해 겪은 실패다(감사 #2·#4·#5
    가 전부 그랬다). 표의 행 수와 등급을 기계로 못 박는다.
    """
    doc = AUDIT_DOC.read_text(encoding="utf-8")
    for spec in _ecos_series_specs():
        assert f"`{spec.key}`" in doc, f"감사문에 {spec.key} 가 없다"
    rows = [ln for ln in doc.splitlines()
            if ln.startswith("| `") and ln.rstrip().endswith("**E0** |")]
    assert len(rows) == 37, f"E0 으로 적힌 행이 37 이 아니다: {len(rows)}"


def test_the_audit_document_does_not_claim_verified_live_proves_frequency():
    """G15 짝 — ★이번 감사의 핵심 발견이 문서에 남아 있다★"""
    doc = AUDIT_DOC.read_text(encoding="utf-8")
    assert "verified_live" in doc and "주기 검증됨" in doc
    assert "순환논증" in doc, "손으로 쓴 픽스처가 증거가 아니라는 근거가 빠졌다"


def test_the_spec_dataclass_still_holds_what_it_is_given():
    """G2 보강 — 필드 자체는 그대로다(로더가 필드를 대체하지 않았다)."""
    assert "frequency" in {f.name for f in dataclasses.fields(reg.SourceSpec)}
    s = reg.SourceSpec(key="X", label="x", provider=reg.ECOS, endpoint="1/2",
                       frequency="Q")
    assert s.frequency == "Q" and dataclasses.replace(s, frequency="D").frequency == "D"
