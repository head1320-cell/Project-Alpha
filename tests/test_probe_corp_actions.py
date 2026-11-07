"""기업행위 엔드포인트 프로브 — ★여기서 못 재는 것을 한 명령으로 재게 만든다★

## 왜 이 파일이 있나

로드맵 2단계의 첫 작업은 *"어느 제공자의 어느 엔드포인트가 분할·증자를 주는가"*
에 **실호출 응답 한 건**을 증거로 남기는 것이다. ★이 컨테이너에서는 불가능하다★ —
`opendart.fss.or.kr` 과 `data.krx.co.kr` 이 **둘 다** 이그레스 프록시에 403 으로
막히고(키 유무와 무관), `DART_API_KEY` 도 없다.

★그것은 "그 데이터를 못 받는다" 가 아니라 "여기서는 확인할 수 없다" 다.★
둘을 섞으면 1단계의 A/B 설계를 근거 없이 고르게 된다. 그래서 판정하는 대신
`scripts/explain_hot_queries.py` 와 **같은 선례**로 하네스를 남긴다.

## ★추측을 지식처럼 저장하지 않는다★

가이드 페이지를 열 수 없었으므로 후보 엔드포인트 이름을 적으면 그것은 추측이
저장소에 사실처럼 남는 것이다. 그래서 엔드포인트는 **인자로 받는다** — ⑰ 이
그것을 강제한다.
"""
import json
import os
import pathlib

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
import scripts.probe_corp_actions as P  # noqa: E402


class _FakeClient:
    """`DartClient` 대역 — 네트워크 없이 성공/실패 경로를 둘 다 만든다."""

    def __init__(self, *, configured=True, payload=None):
        self.is_configured = configured
        self._payload = payload
        self.calls: list[tuple] = []

    def _get(self, endpoint, params):
        self.calls.append((endpoint, dict(params)))
        return self._payload


# ═══════════════════════════════════════════════════════════════════════════
# ⑬ 스크립트 자체가 돈다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_selftest_passes():
    """★안 돌아가는 스크립트를 남기지 않는다★ — 네트워크·키 불필요."""
    assert P._selftest() == 0


# ═══════════════════════════════════════════════════════════════════════════
# ⑭ 성공하면 ★증거 파일★ 이 남는다
# ═══════════════════════════════════════════════════════════════════════════

def test_a_successful_call_is_saved_as_evidence(tmp_path, capsys):
    payload = {"status": "000", "message": "정상",
               "list": [{"rcept_no": "20240101000001", "corp_code": "00126380",
                         "stock_knd": "보통주", "nstk_ostk_cnt": "1000"}]}
    client = _FakeClient(payload=payload)
    code = P.probe(client, "someEndpoint", {"corp_code": "00126380"},
                   out_dir=str(tmp_path))
    assert code == 0
    saved = list(pathlib.Path(tmp_path).glob("someEndpoint-*.json"))
    assert saved, f"증거가 저장되지 않았다: {list(pathlib.Path(tmp_path).iterdir())}"
    assert json.loads(saved[0].read_text(encoding="utf-8")) == payload


def test_the_summary_names_the_response_fields(tmp_path, capsys):
    """★필드 이름이 곧 스키마 증거다★ — 저장만 하고 안 보여주면 다시 열어야 한다."""
    client = _FakeClient(payload={"status": "000",
                                  "list": [{"rcept_no": "1", "nstk_ostk_cnt": "1000"}]})
    P.probe(client, "someEndpoint", {}, out_dir=str(tmp_path))
    out = capsys.readouterr().out
    assert "rcept_no" in out and "nstk_ostk_cnt" in out, out


def test_the_evidence_path_is_reported(tmp_path, capsys):
    client = _FakeClient(payload={"status": "000", "list": [{"a": 1}]})
    P.probe(client, "someEndpoint", {}, out_dir=str(tmp_path))
    assert str(tmp_path) in capsys.readouterr().out


# ═══════════════════════════════════════════════════════════════════════════
# ⑮ 실패도 결론이다 — ★다만 어느 실패인지 말해야 결론이 된다★
# ═══════════════════════════════════════════════════════════════════════════

def test_a_failure_prints_the_dart_status_and_message(tmp_path, capsys, monkeypatch):
    """`_get` 은 실패를 `None` 으로 삼킨다 — 사유는 `dart_usage()` 에 남는다."""
    import src.data.dart_client as DC
    monkeypatch.setattr(DC, "dart_usage", lambda: {
        "requests": 1, "errors": {"013": 1}, "quota_exhausted": False,
        "last_error": {"endpoint": "someEndpoint", "status": "013",
                       "message": "조회된 데이터가 없습니다."}})
    code = P.probe(_FakeClient(payload=None), "someEndpoint", {},
                   out_dir=str(tmp_path))
    out = capsys.readouterr().out
    assert code == 1
    assert "013" in out, out
    assert "조회된 데이터가 없습니다" in out, out
    assert not list(pathlib.Path(tmp_path).iterdir()), "실패인데 증거를 저장했다"


def test_a_failure_without_a_recorded_reason_says_so(tmp_path, capsys, monkeypatch):
    """★사유를 지어내지 않는다★ — 기록이 없으면 없다고 적는다."""
    import src.data.dart_client as DC
    monkeypatch.setattr(DC, "dart_usage", lambda: {
        "requests": 0, "errors": {}, "quota_exhausted": False, "last_error": None})
    P.probe(_FakeClient(payload=None), "someEndpoint", {}, out_dir=str(tmp_path))
    assert "기록되지 않" in capsys.readouterr().out


# ═══════════════════════════════════════════════════════════════════════════
# ⑯ 키가 없으면 ★그 사실을 말한다★ (조용히 0 을 내지 않는다)
# ═══════════════════════════════════════════════════════════════════════════

def test_an_unconfigured_key_is_reported(tmp_path, capsys):
    client = _FakeClient(configured=False)
    code = P.probe(client, "someEndpoint", {}, out_dir=str(tmp_path))
    assert code == 1
    assert "DART_API_KEY" in capsys.readouterr().out
    assert client.calls == [], "키가 없는데 호출을 시도했다"


# ═══════════════════════════════════════════════════════════════════════════
# ⑰ ★추측 목록을 싣지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

_SRC = pathlib.Path("scripts/probe_corp_actions.py")


def test_no_endpoint_name_is_hardcoded():
    """가이드 페이지를 못 읽었으므로 이름을 적으면 **추측이 저장소에 사실로 남는다**.

    DART 엔드포인트는 `piicDecsn`·`fricDecsn` 처럼 `Decsn` 으로 끝나거나
    `xxx.json` 형태다. 소스에 그런 리터럴이 있으면 안 된다.
    """
    src = _SRC.read_text(encoding="utf-8")
    import re
    guessed = re.findall(r"[\"'][A-Za-z]{3,}(?:Decsn|Rs|Dsclsr)[\"']", src)
    assert not guessed, f"추측한 엔드포인트 이름이 하드코딩됐다: {guessed}"
    # `.json` 엔드포인트 리터럴도 마찬가지 (증거 파일 확장자는 예외)
    jsons = [m for m in re.findall(r"[\"'](\w+)\.json[\"']", src)]
    assert not jsons, f"엔드포인트 `.json` 리터럴이 있다: {jsons}"


def test_the_tripwire_would_notice_a_guessed_name():
    """★테스트의 테스트★ — 항상 통과하는 검사를 배제한다."""
    import re
    fake = 'ENDPOINT = "piicDecsn"\n'
    assert re.findall(r"[\"'][A-Za-z]{3,}(?:Decsn|Rs|Dsclsr)[\"']", fake)


def test_the_source_points_at_the_official_guide():
    """★어디서 이름을 확인하는지 적는다★ 하네스만 있고 길이 없으면 못 쓴다."""
    src = _SRC.read_text(encoding="utf-8")
    assert "opendart.fss.or.kr/guide" in src, "가이드 URL 이 없다"
    assert "403" in src or "막" in src, "이 컨테이너에서 막혔다는 사실이 없다"


def test_it_reuses_the_existing_client_not_a_new_request_path():
    """★새로 만들지 않는다★ — 스로틀·캐시·쿼터 집계가 이미 `DartClient` 에 있다."""
    src = _SRC.read_text(encoding="utf-8")
    assert "DartClient" in src
    assert "requests.get" not in src, "요청 경로를 새로 만들었다"


@pytest.mark.parametrize("argv", [["--selftest"]])
def test_main_runs_the_selftest(argv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["probe_corp_actions", *argv])
    assert P.main() == 0
