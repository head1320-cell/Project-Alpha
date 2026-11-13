"""mock 모드(`KIS_USE_MOCK` 이 정확히 `"1"`)는 ★외부로 나가지 않는다★ — 기동 · 화면 조회(인자 없는 GET).

CLAUDE.md: *"개발 기본값 `KIS_USE_MOCK=1` — 외부 호출 0"*. 2026-11-13 에 재 보니 그렇지 않았다: 기동 때 KIS 종목 마스터를
내려받고(`new.real.download.dws.co.kr`), 매크로 지표 탭이 연준·한국은행 정책문을 긁었다(`www.federalreserve.gov` · `www.bok.or.kr`).
둘 다 키가 필요 없어 mock 게이트를 지나지 않았고, 네트워크가 열린 곳과 막힌 곳에서 서버가 다른 상태가 됐다(2026-11-12 CI 전용 실패).

판정은 `src/data/mock_gate.py::mock_allowed()` 하나다. 마스터 쪽 단위 시험은 `tests/test_lifecycle_daemons.py` 에 있다.

★이 파일이 말하지 않는 것★ — 인자가 있는 경로 · POST 등 사용자가 실행하는 분석(야후 시세를 읽는 `MarketDataLoader` 등은 게이트가 없다) ·
키가 있어야 도는 데몬. 아래 훑기의 "0건" 은 그 범위의 관측이다.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "probe_external_calls.py"
_LONG = "The Committee decided to raise rates. " * 40


def _probe_module():
    spec = importlib.util.spec_from_file_location("probe_external_calls", PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 1. 정책문 수집 ───────────────────────────────────────────────────────────

def _cb(monkeypatch, mock: str | None, text: str | None = None, use_cache: bool = False):
    import src.engine.cb_sentiment as cbs
    calls: list[str] = []

    def fake(url, timeout=8.0):
        calls.append(url)
        return text

    monkeypatch.setattr(cbs, "_fetch", fake)
    if mock is None:
        monkeypatch.delenv("KIS_USE_MOCK", raising=False)
    else:
        monkeypatch.setenv("KIS_USE_MOCK", mock)
    return cbs.cb_sentiment(use_cache=use_cache), calls


@pytest.fixture(autouse=True)
def _clean_cb_cache():
    import src.engine.cb_sentiment as cbs
    cbs._CACHE.clear()
    yield
    cbs._CACHE.clear()


def test_mock_mode_does_not_fetch_policy_statements(monkeypatch):
    out, calls = _cb(monkeypatch, "1", text=_LONG)
    assert calls == []
    for bank in ("fed", "bok"):
        b = out["banks"][bank]
        assert b["available"] is False and b["reason"] == "mock_mode" and b["note"]
        assert "score" not in b                      # 점수를 지어내지 않는다
    assert out["method"]


def test_an_unset_gate_is_mock_and_does_not_fetch(monkeypatch):
    out, calls = _cb(monkeypatch, None, text=_LONG)
    assert calls == [] and out["banks"]["fed"]["reason"] == "mock_mode"


def test_real_mode_fetches_both_banks(monkeypatch):
    """★짝★ — 운영에서는 두 은행 모두 수집하고 점수를 낸다(게이트가 늘 막는 구현이 아니다)."""
    out, calls = _cb(monkeypatch, "0", text=_LONG)
    assert len(calls) == 2 and any("federalreserve.gov" in u for u in calls) and any("bok.or.kr" in u for u in calls)
    assert out["banks"]["fed"]["available"] is True and "score" in out["banks"]["fed"]


def test_the_gate_is_exactly_one(monkeypatch):
    for v in ("0", "true", "", "01", " 1"):
        _, calls = _cb(monkeypatch, v, text=_LONG)
        assert len(calls) == 2, repr(v)


def test_not_trying_and_failing_are_different_reasons(monkeypatch):
    """시도하지 않은 것(mock)과 시도했다가 실패한 것은 다른 사유·다른 문장이다 — 뭉개면 화면이 '수집 실패'라고 거짓말한다."""
    mock_out, _ = _cb(monkeypatch, "1")
    fail_out, calls = _cb(monkeypatch, "0", text=None)
    assert len(calls) == 2
    m, f = mock_out["banks"]["fed"], fail_out["banks"]["fed"]
    assert f["available"] is False and f["reason"] == "fetch_failed"
    assert m["reason"] != f["reason"] and m["note"] != f["note"]


def test_the_mock_note_is_screen_text(monkeypatch):
    """이 문장은 화면에 그대로 실린다(`data-server`) — 개발자 낱말·환경변수 이름을 싣지 않는다(용어집 §4)."""
    out, _ = _cb(monkeypatch, "1")
    note = out["banks"]["bok"]["note"]
    assert "합성 데이터" in note
    assert not any(w in note for w in ("mock", "Mock", "MOCK", "KIS_", "모의"))


def test_the_mock_answer_is_not_cached_and_the_gate_is_read_before_the_cache(monkeypatch):
    """게이트가 바뀌면 답도 바로 바뀐다 — mock 의 '미산출'이 6시간 캐시에 남아 운영 응답이 되거나, 그 반대가 되지 않는다."""
    _cb(monkeypatch, "1", use_cache=True)
    real, calls = _cb(monkeypatch, "0", text=_LONG, use_cache=True)
    assert len(calls) == 2 and real["banks"]["fed"]["available"] is True     # mock 답이 캐시에서 나오지 않았다
    again, calls2 = _cb(monkeypatch, "1", text=_LONG, use_cache=True)
    assert calls2 == [] and again["banks"]["fed"]["reason"] == "mock_mode"    # 운영 캐시가 mock 에서 나오지 않았다


# ── 2. 소켓 가드 — 기동 + 인자 없는 GET 전부 ─────────────────────────────────

def test_the_guard_catches_a_planted_external_call(monkeypatch):
    """★짝★ — 가드가 실제로 잡는다. 아무것도 못 보는 가드라면 아래 '0건' 은 공허하다."""
    probe = _probe_module()
    for k in list(os.environ):
        if k.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
            monkeypatch.delenv(k)
    seen: list[str] = []
    probe.install(lambda host, where: seen.append(host), monkeypatch.setattr)
    import requests
    with pytest.raises(requests.exceptions.RequestException):
        requests.get("https://example.invalid/x", timeout=2)
    assert seen and all(h == "example.invalid" for h in seen)
    assert probe.is_local("127.0.0.1") and probe.is_local("localhost") and not probe.is_local("10.0.0.5")


def _sweep(tmp_path, mock: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.upper().endswith("_API_KEY") and k != "KIS_APP_KEY"}
    env.update({"KIS_USE_MOCK": mock, "LIFECYCLE_DAEMONS": "1", "DATABASE_URL": f"sqlite:///{tmp_path}/probe.db",
                "PYTHONPATH": str(ROOT)})
    env.pop("LIFECYCLE_MASTER_COLLECT", None)        # 명시 스위치 없이 — 제품 기본 동작을 본다
    r = subprocess.run([sys.executable, str(PROBE), "--json", "--idle", "2"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("PROBE_JSON ")), None)
    assert r.returncode == 0 and line, (r.stdout[-800:], r.stderr[-1500:])
    return json.loads(line[len("PROBE_JSON "):])


def test_mock_mode_startup_and_get_routes_make_no_external_call(tmp_path):
    """데몬을 켠 채(마스터 수집 분기에 닿게) 기동하고 인자 없는 GET 을 모두 부른다 — 비로컬 대상 0.

    DB 호스트는 뺀다: `database_async` 의 기본 주소(`postgres` — 도커 서비스 이름)는 인프라 연결이지 외부 서비스 호출이 아니다.
    """
    from urllib.parse import urlparse

    import src.database_async as dba
    db_host = urlparse(dba.DEFAULT_DB_URL.replace("+asyncpg", "")).hostname
    out = _sweep(tmp_path, "1")
    assert out["mock"] == "1" and out["daemons"] == "1"
    assert out["routes_called"] > 100, "경로를 거의 못 불렀다 — 훑기가 공허하다"
    external = [a for a in out["attempts"] if a["host"] != db_host]
    assert external == []
