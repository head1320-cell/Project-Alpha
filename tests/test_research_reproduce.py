"""런을 다시 돌려 대조한다 — Research Case (P1-C)
==============================================================================
지금까지 ResearchRun 은 **영수증**이었다. 무엇을 넣었고 무엇이 나왔는지는 적혀
있지만, 다시 돌려 같은 답이 나오는지 확인할 방법이 없었다. 재현성이 이 플랫폼의
1번 원칙(랜딩 밴드 `01 재현`)인데 그 원칙을 검증하는 경로가 코드에 없었다.

★이 파일이 지키는 정직성 셋★
  1. 재현 좌표가 없으면 오늘로 돌려 놓고 "재현했다" 고 적지 않는다.
  2. 기록된 비중이 없으면 `incomparable` 이다 — 비교 대상이 없는 것은 일치가 아니다.
  3. 자산이 유니버스에서 빠진 것은 "비중이 0 이 됐다" 가 아니다 — 다른 사실이므로
     `universe_changed` 로 따로 보고하고 `deltas` 에 넣지 않는다.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

TICKERS = ["005930", "000660", "035420"]
PIN = (date.today() - timedelta(days=10)).isoformat()


@pytest.fixture(scope="module")
def client():
    from src.app_factory import create_app
    return TestClient(create_app())


def _fake_run(**over) -> dict:
    """`get_run` 이 돌려주는 모양. 저장소 상태에 의존하지 않게 직접 만든다."""
    run = {
        "run_id": "rr_fixture", "created_at": 0.0, "kind": "allocation_analyze",
        "name": "fixture", "code_version": "dev", "parent_run_id": None, "note": None,
        "inputs": {"tickers": TICKERS, "model": "mvo", "lookback_days": 250,
                   "mc_paths": 100, "as_of": PIN},
        "outputs": {"weights": {"optimized": {}}},
        "snapshot": {"coverage": {"start": None, "end": PIN,
                                  "as_of_requested": PIN, "as_of_effective": PIN}},
    }
    run.update(over)
    return run


def _patch_get_run(monkeypatch, run: dict | None):
    import src.data.research_runs as rr
    monkeypatch.setattr(rr, "get_run", lambda rid: (dict(run) if run else None))


def _repro(client, run: dict | None, monkeypatch, **body) -> dict:
    _patch_get_run(monkeypatch, run)
    r = client.post("/api/v1/research-runs/rr_fixture/reproduce", json=body or {})
    assert r.status_code == 200, r.text
    return r.json()


# ── 0. 실제로 한 번 돌려 기준 비중을 얻는다 ─────────────────────────────────
@pytest.fixture(scope="module")
def recorded_weights(client) -> dict:
    r = client.post("/api/v1/allocation/analyze", json={
        "tickers": TICKERS, "model": "mvo", "lookback_days": 250,
        "mc_paths": 100, "as_of": PIN})
    assert r.status_code == 200, r.text
    body = r.json()
    if body.get("error"):
        pytest.skip(f"이 환경에는 시세가 없다: {body.get('message')}")
    return body["weights"]["optimized"]


# ── 1. ★기록된 대로 다시 돌리면 같은 답이 나온다★ ──────────────────────────
def test_a_recorded_run_reproduces_identically(client, monkeypatch, recorded_weights):
    out = _repro(client, _fake_run(outputs={"weights": {"optimized": recorded_weights}}),
                 monkeypatch)
    assert out["reproducible"] is True, out
    assert out["basis"] == "recorded_as_of"
    assert out["estimated"] is False
    assert out["verdict"] == "identical", out.get("deltas")
    assert out["max_delta_pp"] == 0.0
    assert out["universe_changed"] == {"dropped": [], "added": []}


# ── 2. ★비중이 다르면 일치라고 하지 않는다★ (1번의 짝) ─────────────────────
def test_changed_weights_are_reported_as_drift_not_swallowed(client, monkeypatch,
                                                             recorded_weights):
    """1번만 있으면 **항상 identical 을 답하는** 구현도 통과한다 — 여기서 잠근다."""
    bent = {c: round(v + 5.0, 2) for c, v in recorded_weights.items()}
    out = _repro(client, _fake_run(outputs={"weights": {"optimized": bent}}), monkeypatch)
    assert out["verdict"] == "drifted"
    assert out["max_delta_pp"] >= 4.0
    assert out["deltas"] and abs(out["deltas"][0]["delta_pp"]) == out["max_delta_pp"]


# ── 3. 기준일 3단계 ─────────────────────────────────────────────────────────
def test_server_stamped_cutoff_is_used_when_the_request_did_not_pin(client, monkeypatch,
                                                                    recorded_weights):
    run = _fake_run(outputs={"weights": {"optimized": recorded_weights}})
    run["inputs"].pop("as_of")
    out = _repro(client, run, monkeypatch)
    assert out["basis"] == "server_stamped"
    assert out["as_of"] == PIN
    assert out["estimated"] is False


def test_coverage_end_is_an_estimated_reproduction_and_says_so(client, monkeypatch,
                                                               recorded_weights):
    """★P1 이전 런은 여기로 온다★ 재현하되 무엇이 추정인지 숨기지 않는다."""
    run = _fake_run(outputs={"weights": {"optimized": recorded_weights}})
    run["inputs"].pop("as_of")
    run["snapshot"]["coverage"] = {"end": PIN}      # 옛 런의 모양
    out = _repro(client, run, monkeypatch)
    assert out["basis"] == "coverage_end"
    assert out["estimated"] is True, "추정인데 확정 재현인 척했다"
    assert out["as_of"] == PIN


def test_a_run_with_no_coordinates_is_refused_not_run_at_today(client, monkeypatch):
    """오늘로 돌려 놓고 '재현했다' 고 적는 것이 가장 나쁘다."""
    run = _fake_run()
    run["inputs"].pop("as_of")
    run["snapshot"] = {}
    out = _repro(client, run, monkeypatch)
    assert out["reproducible"] is False
    assert out["basis"] == "none"
    assert out["reason"]
    assert "verdict" not in out, "재현하지 못했는데 판정을 내렸다"


# ── 4. 비교 대상이 없는 것은 일치가 아니다 ──────────────────────────────────
def test_a_run_without_recorded_weights_is_incomparable_not_identical(client, monkeypatch):
    out = _repro(client, _fake_run(outputs={}), monkeypatch)
    assert out["reproducible"] is True          # 다시 돌리기는 했다
    assert out["verdict"] == "incomparable", "대조할 것이 없는데 일치라고 답했다"
    assert out["reason"]
    assert "max_delta_pp" not in out


# ── 5. 유니버스 변화는 비중 차이와 다른 사실이다 ────────────────────────────
def test_a_dropped_asset_is_not_reported_as_a_weight_moving_to_zero(client, monkeypatch,
                                                                    recorded_weights):
    ghost = dict(recorded_weights)
    ghost["999999"] = 12.5                      # 지금은 유니버스에 없는 자산
    out = _repro(client, _fake_run(outputs={"weights": {"optimized": ghost}}), monkeypatch)
    assert "999999" in out["universe_changed"]["dropped"]
    assert all(d["code"] != "999999" for d in out["deltas"]), \
        "빠진 자산을 '비중이 0 이 됐다' 로 그렸다 — 다른 사실이다"
    assert out["verdict"] == "drifted", "유니버스가 바뀌었는데 일치라고 답했다"


# ── 6. 못 하는 것을 못 한다고 적는다 ────────────────────────────────────────
def test_an_unsupported_kind_says_which_kind_it_cannot_do(client, monkeypatch):
    out = _repro(client, _fake_run(kind="alpha_validate"), monkeypatch)
    assert out["reproducible"] is False
    assert "alpha_validate" in out["reason"]


def test_a_missing_run_is_404_and_a_storage_failure_is_503(client, monkeypatch):
    """R0-S 가 세운 분기를 재현 경로도 지킨다 — 404 와 503 은 다른 사실이다."""
    _patch_get_run(monkeypatch, None)
    assert client.post("/api/v1/research-runs/nope/reproduce", json={}).status_code == 404

    import src.data.research_runs as rr

    def boom(_rid):
        raise RuntimeError("storage down (test)")

    monkeypatch.setattr(rr, "get_run", boom)
    assert client.post("/api/v1/research-runs/nope/reproduce", json={}).status_code == 503


# ── 7. 재현은 그 자체로 하나의 런이고, 부모는 원본이다 ──────────────────────
def test_recording_a_reproduction_links_it_to_its_parent(client, monkeypatch,
                                                         recorded_weights):
    captured: dict = {}

    def fake_record(kind, inputs, outputs, **kw):
        captured.update({"kind": kind, "inputs": inputs, "kw": kw})
        return "rr_child"

    monkeypatch.setattr("src.data.research_runs.record_run", fake_record)
    out = _repro(client, _fake_run(outputs={"weights": {"optimized": recorded_weights}}),
                 monkeypatch, record=True)
    assert out["child_recorded"] is True
    assert captured["kind"] == "allocation_reproduce"
    assert captured["kw"]["parent_run_id"] == "rr_fixture"
    assert captured["inputs"]["source_run_id"] == "rr_fixture"
