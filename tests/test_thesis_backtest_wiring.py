"""논지 백테스트 라우트 + `rr_*` 사슬 (P3-1 커밋 ②)

★이 파일이 거는 것★
  1. 논지가 **실제로** 백테스트를 돌린다 — 있는 다리를 통과한다.
  2. ★퇴화를 성공으로 보고하지 않는다★ 거래 0건은 "손실 없음" 이 아니다.
  3. 사슬에 남되 **돌리지 않은 것은 남기지 않는다** — 없는 것을 가리키는 기록은
     사슬이 아니라 거짓 사슬이다.
  4. 재현 경로는 아직 없고, 그 사실을 **정직하게 거절**한다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.research_runs as rr  # noqa: E402

CODE = "005930"
TB = f"/api/v1/company/{CODE}/thesis-backtest"
START, END = "2024-01-01", "2024-06-30"
BARS = 130

# 실제 ROE 19.27 — 임계값이 항상 참 / 항상 거짓을 가른다.
KILL_ALWAYS_FALSE = {"kind": "field", "field": "roe", "op": "lt", "value": 8.0}
KILL_ALWAYS_TRUE = {"kind": "field", "field": "roe", "op": "lt", "value": 25.0}
KILL_SCREEN_ONLY = {"kind": "field", "field": "momentum_12_1", "op": "lt", "value": 0.0}


def _body(**kw) -> dict:
    base = {"claim": "반도체 사이클 저점에서 ROE 가 정상화된다",
            "evidence": [{"section": "quality", "path": "roe"}],
            "catalysts": [{"what": "4분기 실적", "by": "2026-12-31"}],
            "kill_conditions": [dict(KILL_ALWAYS_FALSE)],
            "start_date": START, "end_date": END}
    base.update(kw)
    return base


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


@pytest.fixture
def mem_rr(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(rr, "_engine", lambda: eng)
    monkeypatch.setattr(rr, "_inited", False)
    yield eng
    eng.dispose()


# ── 1. 라우트 ───────────────────────────────────────────────────────────────
def test_the_route_is_registered_alongside_the_existing_seven(client):
    paths = {r.path for r in client.app.routes}
    assert "/api/v1/company/{code}/thesis-backtest" in paths
    for p in ("/api/v1/company/{code}/valuation-sandbox",
              "/api/v1/company/{code}/financial-deep",
              "/api/v1/company/{code}/risk-deep",
              "/api/v1/company/{code}/reverse-dcf",
              "/api/v1/company/{code}/valuation-distribution",
              "/api/v1/company/{code}/macro-sensitivity",
              "/api/v1/company/{code}/thesis-check"):
        assert p in paths, p


def test_a_thesis_actually_runs_a_backtest(client, mem_rr):
    """★논지가 그대로 백테스트가 된다★"""
    b = client.post(TB, json=_body()).json()
    assert b["available"] is True, b["reason"]
    assert b["screened_count"] == 1, "논지는 그 기업 한 종목에 대한 것이다"
    stats = b["backtest"]["statistics"]
    assert stats["num_trades"] >= 1, "실제로 거래가 일어났다"
    assert b["backtest"]["id"]


def test_the_run_goes_through_the_existing_bridge(client, mem_rr, monkeypatch):
    """★있는 다리에 올린다★ 실행 경로를 새로 짓지 않았다는 증거."""
    seen = {}

    import src.api.screener_routes as sr
    real = sr._screen_to_backtest_core

    def _spy(req, progress_cb=None):
        seen["req"] = req
        return real(req, progress_cb)
    monkeypatch.setattr(sr, "_screen_to_backtest_core", _spy)

    client.post(TB, json=_body())
    req = seen["req"]
    assert req.custom_tickers == [CODE]
    assert req.strategy_name == "Condition"
    assert req.sell_conditions and req.buy_conditions
    assert req.allow_snapshot_fundamentals is True


def test_the_lookahead_label_reaches_the_response(client, mem_rr):
    """★룩어헤드를 숨기지 않는다★ 자동으로 켠 사실이 응답에 있다."""
    b = client.post(TB, json=_body()).json()
    assert b["lookahead"] is True
    assert b["auto_enabled_opt_in"] is True
    assert "조용히 무시" in b["lookahead_reason"]


def test_the_entry_rule_is_disclosed(client, mem_rr):
    """진입 규칙은 논지가 준 것이 아니라 우리가 붙인 것이다 — 그것을 말한다."""
    b = client.post(TB, json=_body()).json()
    assert b["entry"]["condition"]["factor_token"] == "종가"
    assert "진입 규칙" in b["entry"]["note"]


# ── 2. ★퇴화를 성공으로 보고하지 않는다★ ──────────────────────────────────
def test_an_always_true_kill_reports_zero_trades_as_not_verified(client, mem_rr):
    """★거래 0건은 '손실 없음' 이 아니다★"""
    b = client.post(TB, json=_body(kill_conditions=[dict(KILL_ALWAYS_TRUE)])).json()
    assert b["available"] is True
    d = b["diagnostics"]
    assert d["degenerate"] == "no_entry"
    assert d["buy_bars"] == 0 and d["sell_bars"] == d["total_bars"] == BARS
    assert "검증되지 않음" in d["reason"]


def test_an_always_false_kill_reports_buy_and_hold(client, mem_rr):
    """★짝★ 반대쪽 퇴화도 응답에 나온다."""
    d = client.post(TB, json=_body()).json()["diagnostics"]
    assert d["degenerate"] == "never_exits"
    assert d["sell_bars"] == 0
    assert "바이앤홀드" in d["reason"]


def test_the_constant_condition_is_shown_per_condition(client, mem_rr):
    row = client.post(TB, json=_body()).json()["diagnostics"]["rows"][0]
    assert row["constant_over_window"] is True
    assert row["lookahead"] is True and row["reason"]


# ── 3. ★사슬 — 돌린 것만 남긴다★ ──────────────────────────────────────────
def test_the_run_is_recorded_with_inputs_that_can_revive_it(client, mem_rr):
    """★입력을 되살릴 수 있게 적는다★ (alpha_routes 관례)"""
    b = client.post(TB, json=_body()).json()
    assert b["recorded"] is True and b["run_id"]

    run = rr.get_run(b["run_id"])
    assert run is not None and run["kind"] == "thesis_backtest"
    inp = run["inputs"]
    assert inp["code"] == CODE
    assert inp["thesis"]["claim"]
    assert inp["lifted_conditions"], "무엇을 올렸는지 남는다"
    assert inp["entry_condition"]["factor_token"] == "종가"
    assert inp["start_date"] == START and inp["end_date"] == END
    # ★자동으로 켰다는 사실 자체가 입력의 일부다★
    assert inp["allow_snapshot_fundamentals"] is True
    assert inp["auto_enabled_opt_in"] is True
    # 퇴화 판정이 결과에 함께 남는다 — 나중에 이 런을 믿을지 정하는 근거다.
    assert run["outputs"]["diagnostics"]["degenerate"] == "never_exits"
    assert run["outputs"]["lookahead"] is True


def test_a_thesis_with_nothing_liftable_is_not_run_and_not_recorded(client, mem_rr):
    """★없는 것을 가리키는 기록은 사슬이 아니라 거짓 사슬이다★"""
    before = len(rr.list_runs(kind="thesis_backtest", limit=200))
    b = client.post(TB, json=_body(kill_conditions=[dict(KILL_SCREEN_ONLY)])).json()
    assert b["available"] is False and b["reason"]
    assert b["run_id"] is None
    assert b["backtest"] is None if "backtest" in b else True
    assert len(rr.list_runs(kind="thesis_backtest", limit=200)) == before


def test_an_empty_kill_list_is_refused_before_any_work(client, mem_rr):
    b = client.post(TB, json=_body(kill_conditions=[])).json()
    assert b["available"] is False and b["run_id"] is None
    assert b["thesis"]["available"] is False, "논지 검증 결과도 함께 돌려준다"


def test_record_run_false_runs_without_recording(client, mem_rr):
    before = len(rr.list_runs(kind="thesis_backtest", limit=200))
    b = client.post(TB, json=_body(record_run=False)).json()
    assert b["available"] is True and b["backtest"]
    assert b["run_id"] is None and b["recorded"] is False
    assert len(rr.list_runs(kind="thesis_backtest", limit=200)) == before


def test_a_failed_validation_is_a_reason_not_a_500(client, mem_rr):
    r = client.post(TB, json=_body(claim=""))
    assert r.status_code == 200, r.text
    assert r.json()["thesis"]["available"] is False


def test_a_dead_recorder_does_not_invalidate_the_run(client, mem_rr, monkeypatch):
    """기록 실패가 실행을 무효로 만들지 않는다 — 다만 남지 않았다고 말한다."""
    def _boom(*a, **kw):
        raise RuntimeError("기록 불가")
    monkeypatch.setattr("src.data.research_runs.record_run", _boom)
    b = client.post(TB, json=_body()).json()
    assert b["available"] is True and b["backtest"]
    assert b["run_id"] is None and b["recorded"] is False


# ── 4. 케이스 포인터 · 재현 ────────────────────────────────────────────────
def test_the_case_pointer_only_advances_to_a_stored_run(client, mem_rr, monkeypatch):
    """★저장 성공한 아티팩트만 가리킨다★"""
    monkeypatch.setattr("src.data.research_runs.record_run", lambda *a, **kw: None)
    b = client.post(TB, json=_body(case_id="rc_없는케이스")).json()
    assert b["run_id"] is None
    assert b["case_bound"]["ok"] is False and b["case_bound"]["reason"]


def test_no_case_id_makes_no_pointer_claim(client, mem_rr):
    assert "case_bound" not in client.post(TB, json=_body()).json()


def test_the_reproduce_endpoint_refuses_this_kind_honestly(client, mem_rr):
    """★거짓 사슬을 만들지 않는다★ 재현 경로는 이 슬라이스에서 열지 않았다."""
    rid = client.post(TB, json=_body()).json()["run_id"]
    assert rid
    r = client.post(f"/api/v1/research-runs/{rid}/reproduce", json={})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["reproducible"] is False
    assert b["kind"] == "thesis_backtest"
    assert "아직 재현 경로가 없습니다" in b["reason"]


# ── 5. 비유한 값 ───────────────────────────────────────────────────────────
def test_an_infinite_statistic_is_named_rather_than_silently_dropped(client, mem_rr):
    """손실 거래가 0이면 `profit_factor` 는 정당하게 무한하다. JSON 이 그것을
    실을 수 없으므로 None 으로 바꾸되 ★어느 키가 그랬는지 남긴다★ — 조용히 지우면
    "값이 없다" 와 "무한이다" 가 같아 보인다.

    ★조건부로 단언하지 않는다★ 이 테스트의 앞 판본은
    `if b.get("non_finite"):` 로 감싸여 있었는데, 변이가 지우는 것이 바로 그
    `non_finite` 라 변이를 걸면 단언이 **실행되지 않고** green 이 됐다.
    이 논지(항상 거짓 kill → 바이앤홀드 1거래, 손실 0)는 결정적이므로
    실측 3회 모두 동일했다 — 그래서 무조건 단언한다.
    """
    b = client.post(TB, json=_body()).json()
    stats = b["backtest"]["statistics"]

    assert b.get("non_finite"), "무한 통계가 있었는데 이름이 남지 않았다"
    assert any("profit_factor" in n for n in b["non_finite"]), b["non_finite"]
    assert stats.get("profit_factor") is None, "JSON 이 실을 수 없는 값은 None 이 된다"

    for k, v in stats.items():                      # NaN 이 남지 않았다
        if isinstance(v, float):
            assert v == v, k
