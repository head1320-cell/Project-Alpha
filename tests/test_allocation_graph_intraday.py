"""캔버스의 분봉 백테스트 노드 둘 — 설정(`intraday_setup`) → 결과 조회(`intraday_load`)
==============================================================================
설계 `docs/superpowers/specs/2026-11-14-canvas-intraday-nodes-design.md`

계산은 분봉 백테스트의 시험들이 건다. 여기서는 ★캔버스에 놓였을 때의 약속★만 본다:

- **기록되는 길 하나.** 계산(`/graph/run`)은 아무것도 쓰지 않고 봉도 읽지 않는다. 실행은 단추(`/graph/save`)만 하고,
  그 한 번이 시행 한 줄과 결과 요약을 남긴다. ★시행을 기록하지 못하면 결과도 남기지 않는다.★
- **신원.** 문은 열려 있고, 분봉 노드만 로그인을 요구한다(사유는 까닭별로 다르다). 분봉 노드가 없는 그래프는 신원을 묻지 않는다.
- **본인만.** 남의 결과와 없는 결과는 같은 문장이다. 못 읽음은 없음과 다른 문장이다.
- **운영 게이트.** 합성 분봉 위의 결과는 운영에서 내주지 않는다 — 모의 모드에서는 연습용 표식을 달고 보인다.
- **같은 검사 · 같은 판정.** 설정 노드의 거절 사유는 판정 문의 사유이고, 결과 노드의 관문 표는 판정 문의 응답이다.

손 계산의 하루(`WIN`)와 준비 도우미는 `test_intraday_validate_route.py` 의 것이다.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

import src.data.backtest_runs as br
import src.data.minute_bars as mb
import src.database as dbmod
from src.api.allocation_graph_nodes import REGISTRY
from src.api.allocation_graph_roles import HISTORY
from src.data import intraday_trials as trials
from src.domain.auth_identity import ROLE_ANALYST
from src.engine import portfolio_graph as pg
from tests.graph_write_guard import graph_write_guard  # noqa: F401
from tests.route_walk import flat_routes
from tests.test_intraday_validate_route import BODY, login, made_days, stored_rows, with_days

#: ★계산 중 DB 쓰기 0★ (BL0) — 시행 기록의 쓰기 함수 셋도 감시 목록에 있다. 단추(저장 문)의 쓰기는 계산이 끝난 뒤라 허용된다.
pytestmark = pytest.mark.usefixtures("graph_write_guard")

RUN = "/api/v1/allocation/graph/run"
SAVE = "/api/v1/allocation/graph/save"
VAL = "/api/v1/intraday/validate"
RESULTS = "/api/v1/intraday/results"
_SECRET = "canvas-intraday-nodes-test-secret-0123456789"
NO_LOGIN = "로그인하지 않았습니다"


@pytest.fixture(scope="module", autouse=True)
def _the_run_stores_table_flag_is_left_as_found():
    """이 파일의 임시 DB 가 뒤에 도는 시험을 망가뜨리지 않는다 — 전체 실행(새 기본 DB)에서만 보이던 결함의 가드."""
    before = br._inited
    yield
    assert br._inited == before, "실행 저장소의 표 표시를 임시 DB 에서 만든 값으로 남겼다 — 뒤의 시험이 기본 DB 에서 실패한다"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("MINUTE_BARS_DIR", str(tmp_path / "bars"))
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    # 실행 저장소의 "표를 만들었다" 표시는 프로세스 전역이다(DB 주소를 보지 않는다). 기동이 임시 DB 에 표를 만들고
    # 그 표시를 남기면, 뒤에 도는 시험이 기본 DB 에서 "표 없음"으로 실패한다 — 시험이 끝나면 앞의 값으로 되돌린다.
    monkeypatch.setattr(br, "_inited", False)
    dbmod.reset_session()
    dbmod.init_db()
    dbmod.create_user("alice", "alice-pw", role=ROLE_ANALYST)
    dbmod.create_user("bob", "bob-pw", role=ROLE_ANALYST)
    mb.clear_cache()

    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        yield c

    mb.clear_cache()
    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


@pytest.fixture()
def auth(client) -> dict[str, str]:
    return login(client)


# ── 그래프 문서 ────────────────────────────────────────────────────────────────────────
SETUP = {"tickers": ["005930"], "start_date": "2026-03-02", "end_date": "2026-03-13",
         "rule": "opening_range_breakout", "opening_range_breakout__minutes": 5,
         "amount": 1_000_000, "commission_bp": 1.5, "slippage_ticks": 1}


def setup_node(**over) -> dict:
    params = {k: v for k, v in {**SETUP, **over}.items() if v is not ...}
    return {"id": "s", "type": "intraday_setup", "params": params}


def load_node(key: str | None) -> dict:
    return {"id": "l", "type": "intraday_load", "params": {} if key is None else {"trial_key": key}}


def universe_node(*tickers: str) -> dict:
    return {"id": "u", "type": "universe", "params": {"tickers": list(tickers)}}


def graph(*nodes: dict, edges: list | None = None) -> dict:
    return {"format": pg.FORMAT, "version": pg.VERSION, "nodes": list(nodes), "edges": edges or []}


def run(client, g: dict, headers: dict | None = None) -> dict:
    r = client.post(RUN, json=g, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()["nodes"]


def press(client, g: dict, node_id: str, headers: dict | None = None) -> dict:
    """미리보기를 본 뒤(계산) 단추를 누른다 → 저장 문의 답."""
    seen = run(client, g, headers)[node_id]
    r = client.post(SAVE, json={"graph": g, "node_id": node_id, "preview_hash": seen["view_hash"] or "none"},
                    headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def table_rows() -> dict[str, int]:
    """DB 의 모든 표의 행 수 — '쓰기 0'을 동작으로 건다."""
    engine = dbmod.get_engine()
    with engine.connect() as c:
        return {t: int(c.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()) for t in inspect(engine).get_table_names()}


def no_bars_may_be_read(monkeypatch) -> None:
    import src.api.intraday_routes as mod

    def boom(*a, **k):
        raise AssertionError("봉을 읽었다")

    monkeypatch.setattr(mod.minute_feed, "build_days", boom)
    monkeypatch.setattr(mod.intraday, "run", boom)


# ── 신원 — 문은 열려 있고, 분봉 노드만 요구한다 ───────────────────────────────────────────────
def test_without_login_the_setup_node_fails_with_the_reason_and_other_nodes_still_run(client, monkeypatch):
    with_days(monkeypatch, made_days())
    out = run(client, graph(universe_node("005930"), setup_node()))
    assert out["u"]["status"] == "ok"
    assert out["s"]["status"] == "failed" and NO_LOGIN in out["s"]["reason"]
    assert out["s"]["view"] is None


def test_with_login_the_setup_node_passes(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    out = run(client, graph(setup_node()), auth)
    assert out["s"]["status"] == "ok", out["s"]["reason"]


def test_a_token_that_does_not_verify_gives_its_own_reason(client, monkeypatch):
    with_days(monkeypatch, made_days())
    out = run(client, graph(setup_node()), {"Authorization": "Bearer not-a-real-token"})
    assert out["s"]["status"] == "failed"
    assert NO_LOGIN not in out["s"]["reason"] and "토큰" in out["s"]["reason"]


def test_a_token_from_before_a_password_change_gives_its_own_reason(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    assert dbmod.set_password("alice", "new-alice-pw", must_change=False) is not None
    out = run(client, graph(setup_node()), auth)
    assert out["s"]["status"] == "failed" and "다시 로그인" in out["s"]["reason"] and NO_LOGIN not in out["s"]["reason"]


def test_a_temporary_password_does_not_count_as_logged_in(client, monkeypatch):
    with_days(monkeypatch, made_days())
    assert dbmod.set_password("alice", "temp-pw-1", must_change=True) is not None
    tok = client.post("/api/v1/auth/login", json={"username": "alice", "password": "temp-pw-1"}).json()["access_token"]
    out = run(client, graph(setup_node()), {"Authorization": f"Bearer {tok}"})
    assert out["s"]["status"] == "failed" and "비밀번호를 먼저 변경" in out["s"]["reason"]


def test_when_the_account_store_cannot_be_read_it_is_not_called_not_logged_in(client, auth, monkeypatch):
    """확인하지 못함 ≠ 로그인 안 함."""
    with_days(monkeypatch, made_days())

    def down(_name):
        raise RuntimeError("identity db down")

    monkeypatch.setattr(dbmod, "account_state", down)
    out = run(client, graph(setup_node()), auth)
    assert out["s"]["status"] == "failed"
    assert "확인 실패" in out["s"]["reason"] and NO_LOGIN not in out["s"]["reason"]


def test_a_graph_without_intraday_nodes_never_asks_who_you_are(client, auth, monkeypatch):
    """지금의 캔버스 계산에 계정 조회가 늘지 않는다 — 분봉 노드가 있을 때만 신원을 읽는다."""
    asked = []
    real = dbmod.account_state
    monkeypatch.setattr(dbmod, "account_state", lambda name: asked.append(name) or real(name))
    out = run(client, graph(universe_node("005930")), auth)
    assert out["u"]["status"] == "ok" and asked == []
    with_days(monkeypatch, made_days())
    run(client, graph(universe_node("005930"), setup_node()), auth)
    assert asked == ["alice"]                                                   # 짝 — 있으면 한 번 읽는다


def test_the_graph_routes_stay_open(client):
    """문에 잠금을 붙이지 않았다 — 보호 라우트 분류(열린 연구 문)는 그대로다."""
    from src.api.protected_routes import PROTECTED, auth_requirement_of_route
    real = {(m, r.path): r for r in flat_routes(client.app) for m in (getattr(r, "methods", None) or ())}
    for key in (("POST", RUN), ("POST", SAVE)):
        assert auth_requirement_of_route(real[key]) is None and key not in PROTECTED


# ── 설정 노드의 계산 — 쓰기 0 · 봉을 읽지 않는다 ─────────────────────────────────────────────
def test_computing_the_setup_node_writes_nothing_and_reads_no_bars(client, auth, monkeypatch, tmp_path):
    with_days(monkeypatch, made_days())
    no_bars_may_be_read(monkeypatch)
    run(client, graph(setup_node()), auth)                                      # 표를 만드는 첫 호출을 기준선 앞에 둔다
    before, files = table_rows(), sorted(p.name for p in tmp_path.rglob("*"))
    for _ in range(3):
        out = run(client, graph(setup_node()), auth)
        assert out["s"]["status"] == "ok", out["s"]["reason"]
    assert table_rows() == before and stored_rows() == 0
    assert sorted(p.name for p in tmp_path.rglob("*")) == files


def test_the_setup_view_says_what_will_be_run(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    v = run(client, graph(setup_node()), auth)["s"]["view"]
    assert v["request"]["tickers"] == ["005930"] and (v["request"]["from"], v["request"]["to"]) == ("2026-03-02", "2026-03-13")
    assert v["request"]["rule"] == {"kind": "opening_range_breakout", "params": {"minutes": 5}}
    assert v["request"]["position"]["amount"] == 1_000_000 and v["request"]["costs"]["commission_bp"] == 1.5
    assert v["rule_label"] == "시가 범위 돌파" and v["tickers_from"] == "typed"
    assert v["days"] == {"calendar": 12, "loaded": 10}
    assert v["work"] == {"ticker_days": 10, "simulations": 3, "total": 30, "limit": 6_000}       # 슬리피지 0·1·2틱(두 배 = 2틱)


def test_only_the_chosen_templates_parameters_reach_the_request(client, auth, monkeypatch):
    """다른 틀의 칸에 값이 남아 있어도(틀을 바꾼 흔적) 고른 틀의 것만 간다 — 그리고 비운 칸은 틀의 기본값이다."""
    with_days(monkeypatch, made_days())
    g = graph(setup_node(rule="rsi_reversal", rsi_reversal__n=10, opening_range_breakout__minutes=7))
    v = run(client, g, auth)["s"]["view"]
    assert v["request"]["rule"] == {"kind": "rsi_reversal", "params": {"n": 10, "oversold": 30, "overbought": 70}}


def test_an_unset_commission_stays_unknown_not_zero(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    v = run(client, graph(setup_node(commission_bp=...)), auth)["s"]["view"]
    assert v["request"]["costs"]["commission_bp"] is None


@pytest.mark.parametrize(("over", "body_over"), [
    ({"tickers": [f"{i:06d}" for i in range(31)]}, {"tickers": [f"{i:06d}" for i in range(31)]}),
    ({"start_date": "2026-03-13", "end_date": "2026-03-02"}, {"from": "2026-03-13", "to": "2026-03-02"}),
    ({"start_date": "2025-01-01", "end_date": "2026-03-13"}, {"from": "2025-01-01", "to": "2026-03-13"}),
    ({"tickers": []}, {"tickers": []}),
    ({"time_exit": "25:99"}, {"position": {"amount": 1_000_000, "time_exit": "25:99"}}),
])
def test_the_setup_node_refuses_with_the_reason_of_the_validate_route(client, auth, monkeypatch, over, body_over):
    with_days(monkeypatch, made_days())
    said = client.post(VAL, json={**BODY, **body_over}, headers=auth)
    assert said.status_code == 400
    out = run(client, graph(setup_node(**over)), auth)["s"]
    assert out["status"] == "failed" and said.json()["detail"]["reason"] in out["reason"]


def test_too_much_work_is_refused_before_anything_runs(client, auth, monkeypatch):
    import src.api.intraday_routes as mod
    with_days(monkeypatch, made_days())
    no_bars_may_be_read(monkeypatch)
    monkeypatch.setattr(mod, "MAX_VALIDATE_WORK", 29)                           # 10 종목·일 × 3번 = 30
    out = run(client, graph(setup_node()), auth)["s"]
    assert out["status"] == "failed" and mod.REASONS["too_much_work"] in out["reason"]


def test_the_setup_node_needs_a_period(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    out = run(client, graph(setup_node(start_date=..., end_date=...)), auth)["s"]
    assert out["status"] == "failed" and "기간" in out["reason"]


def test_a_connected_universe_supplies_the_tickers_and_says_the_typed_ones_were_not_used(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    edge = {"source": "u", "source_port": "universe", "target": "s", "target_port": "universe"}
    out = run(client, graph(universe_node("000660", "005930"), setup_node(tickers=["035720"]), edges=[edge]), auth)["s"]
    assert out["status"] == "ok", out["reason"]
    assert out["view"]["request"]["tickers"] == ["000660", "005930"] and out["view"]["tickers_from"] == "universe"
    assert out["view"]["typed_ignored"] == 1
    assert any("직접 넣은 종목" in f for f in out["explain"]["facts"])
    alone = run(client, graph(setup_node(tickers=["035720"])), auth)["s"]         # 짝 — 잇지 않으면 직접 넣은 종목
    assert alone["view"]["request"]["tickers"] == ["035720"] and alone["view"]["typed_ignored"] == 0
    assert not any("직접 넣은 종목" in f for f in alone["explain"]["facts"])


def test_the_setup_node_admits_the_tickers_are_chosen_after_the_fact(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    ex = run(client, graph(setup_node()), auth)["s"]["explain"]
    assert any("사후 선택" in t["text"] for t in ex["trust"])
    assert any("실행하지 않았습니다" in u for u in ex["unmeasured"])


# ── 단추 — 계산 · 판정 · 시행 기록을 한 번에 ────────────────────────────────────────────────
def test_the_button_records_one_trial_and_keeps_the_verdict_of_the_route(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    out = press(client, graph(setup_node()), "s", auth)
    assert out["ok"] is True, out
    key = out["saved_id"]
    assert len(key) == 64 and "분봉 결과 조회" in out["text"]
    assert stored_rows() == 1
    kept = trials.result_of("alice", key)["result"]
    said = client.post(VAL, json=BODY, headers=login(client, "bob")).json()     # 같은 요청을 다른 사람이 문으로 — 그의 첫 시행
    for part in ("request", "origin", "summary", "out_of_sample", "slippage", "stress", "multiplicity", "trial", "gates",
                 "breakeven", "assumptions"):
        assert kept[part] == said[part], part
    assert kept["data"]["skipped_total"] == said["data"]["skipped_total"] and "skipped" not in kept["data"]
    assert kept["summary"]["gross_total"] == pytest.approx(19_800.0)             # 열흘 × 1,980원 — 손 계산


def test_pressing_again_with_the_same_setting_is_not_a_new_trial(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    first = press(client, graph(setup_node()), "s", auth)
    again = press(client, graph(setup_node()), "s", auth)
    assert again["ok"] is True and again["saved_id"] == first["saved_id"]
    assert stored_rows() == 1 and trials.result_of("alice", first["saved_id"])["runs"] == 2
    other = press(client, graph(setup_node(opening_range_breakout__minutes=6)), "s", auth)
    assert other["saved_id"] != first["saved_id"] and stored_rows() == 2         # 짝 — 설정이 다르면 새 시행


def test_the_button_without_login_does_nothing(client, monkeypatch):
    with_days(monkeypatch, made_days())
    no_bars_may_be_read(monkeypatch)
    out = press(client, graph(setup_node()), "s")
    assert out["ok"] is False and out["code"] == "not_ok" and NO_LOGIN in out["message"]
    assert stored_rows() == 0


def test_when_the_trial_cannot_be_recorded_the_button_fails_and_keeps_nothing(client, auth, monkeypatch):
    """★N 을 1 로 꾸미지 않는다★ — 세지 못한 실행의 결과를 캔버스에 남기지 않는다."""
    with_days(monkeypatch, made_days())
    monkeypatch.setattr(trials, "record", lambda *a, **k: None)
    out = press(client, graph(setup_node()), "s", auth)
    assert out["ok"] is False and out["code"] == "save_failed" and "시행을 기록하지 못" in out["message"]
    assert trials.results_of("alice") == [] and stored_rows() == 0


def test_when_the_result_cannot_be_kept_the_button_says_the_trial_still_counts(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    monkeypatch.setattr(trials, "keep_result", lambda *a, **k: None)
    out = press(client, graph(setup_node()), "s", auth)
    assert out["ok"] is False and out["code"] == "save_failed"
    assert "결과 요약을 남기지 못" in out["message"] and "시행은 기록" in out["message"]
    assert stored_rows() == 1                                                   # 해 본 것은 해 본 것이다


def test_when_no_bars_are_loaded_the_button_says_so_and_records_nothing(client, auth, monkeypatch):
    import src.api.intraday_routes as mod
    with_days(monkeypatch, [])
    out = press(client, graph(setup_node()), "s", auth)
    assert out["ok"] is False and out["code"] == "save_failed" and mod.EMPTY["not_loaded"] in out["message"]
    assert stored_rows() == 0


# ── 결과 노드 — 읽기만 · 본인만 ──────────────────────────────────────────────────────────
@pytest.fixture()
def kept(client, auth, monkeypatch) -> str:
    """alice 가 단추로 남긴 결과의 열쇠(실제 등급의 손 계산 열흘)."""
    with_days(monkeypatch, made_days())
    return press(client, graph(setup_node()), "s", auth)["saved_id"]


def test_the_owner_reads_back_exactly_what_the_button_kept(client, auth, kept, monkeypatch):
    no_bars_may_be_read(monkeypatch)                                            # 다시 계산하지 않는다
    before = table_rows()
    out = run(client, graph(load_node(kept)), auth)["l"]
    assert out["status"] == "ok", out["reason"]
    v, stored = out["view"], trials.result_of("alice", kept)
    assert v["trial_key"] == kept and v["runs"] == 1 and v["result_at"] == stored["result_at"]
    for part, value in stored["result"].items():
        assert v[part] == value, part
    assert v["gates"]["counts"] == {"ok": 2, "degraded": 1, "unknown": 4}        # 손 계산 열흘 — 판정 문과 같은 표
    assert {g["key"]: g["state"] for g in v["gates"]["gates"]} == {
        "data_integrity": "ok", "point_in_time": "unknown", "costs": "ok", "out_of_sample": "unknown",
        "cost_robustness": "degraded", "multiplicity": "unknown", "economic_value": "unknown"}
    assert table_rows() == before                                               # 읽기는 쓰지 않는다
    assert out["lineage"]["pit"] == "unknown" and out["lineage"]["practice"] is False


def test_someone_else_gets_the_same_sentence_as_for_a_key_that_does_not_exist(client, kept):
    bob = login(client, "bob")
    theirs = run(client, graph(load_node(kept)), bob)["l"]
    missing = run(client, graph(load_node("0" * 64)), bob)["l"]
    assert theirs["status"] == missing["status"] == "failed"
    assert theirs["reason"] == missing["reason"] and theirs["view"] is None


def test_the_result_node_needs_login_and_a_pick(client, auth, kept):
    out = run(client, graph(load_node(kept)))["l"]
    assert out["status"] == "failed" and NO_LOGIN in out["reason"]
    empty = run(client, graph(load_node(None)), auth)["l"]
    assert empty["status"] == "failed" and "선택" in empty["reason"] and NO_LOGIN not in empty["reason"]


def test_a_store_that_cannot_be_read_is_not_reported_as_missing(client, auth, kept, monkeypatch):
    missing = run(client, graph(load_node("0" * 64)), auth)["l"]["reason"]
    monkeypatch.setattr(trials, "result_of", lambda *a, **k: None)
    out = run(client, graph(load_node(kept)), auth)["l"]
    assert out["status"] == "failed" and out["reason"] != missing and "읽지 못" in out["reason"]


def test_a_synthetic_result_is_shown_as_practice_in_mock_mode_and_refused_in_production(client, auth, monkeypatch):
    with_days(monkeypatch, made_days(source="synthetic"))
    key = press(client, graph(setup_node()), "s", auth)["saved_id"]
    shown = run(client, graph(load_node(key)), auth)["l"]
    assert shown["status"] == "ok" and shown["lineage"]["practice"] is True
    assert any(t.get("kind") == "practice" for t in shown["explain"]["trust"])
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    refused = run(client, graph(load_node(key)), auth)["l"]
    assert refused["status"] == "failed" and "합성" in refused["reason"] and refused["view"] is None


def test_a_real_grade_result_is_still_read_in_production(client, auth, kept, monkeypatch):
    """짝 — 운영 게이트가 막는 것은 합성 등급뿐이다."""
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    assert run(client, graph(load_node(kept)), auth)["l"]["status"] == "ok"


def test_the_result_explains_itself_without_overclaiming(client, auth, kept):
    ex = run(client, graph(load_node(kept)), auth)["l"]["explain"]
    assert ex["headline"] == {"label": "비용 후 실현손익", "value": -3_195, "unit": "원", "text": "−3,195원"}   # 손 계산 — 열흘의 비용 후 −3,194.73원
    assert any("다시 계산하지 않" in t["text"] for t in ex["trust"])
    assert any("시점 정합" in t["text"] and t["state"] == "unknown" for t in ex["trust"])
    assert any("경제적 가치" in u for u in ex["unmeasured"])


# ── 결과 목록 문 ──────────────────────────────────────────────────────────────────────
def test_the_results_list_needs_login_and_is_registered_as_protected(client):
    from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
    assert client.get(RESULTS).status_code == 401
    assert PROTECTED[("GET", RESULTS)][0] == REQUIRE_LOGIN


def test_the_results_list_shows_only_my_results(client, auth, kept):
    mine = client.get(RESULTS, headers=auth).json()
    assert mine["available"] is True and [r["trial_key"] for r in mine["results"]] == [kept]
    row = mine["results"][0]
    assert row["rule_kind"] == "opening_range_breakout" and row["rule_label"] == "시가 범위 돌파"
    assert row["tickers"] == ["005930"] and (row["from"], row["to"]) == ("2026-03-02", "2026-03-13")
    assert row["synthetic"] is False and row["result_at"] > 0 and row["runs"] == 1
    theirs = client.get(RESULTS, headers=login(client, "bob")).json()
    assert theirs == {"available": True, "reason": None, "results": []}


def test_the_results_list_leaves_out_synthetic_results_in_production(client, auth, monkeypatch):
    with_days(monkeypatch, made_days(source="synthetic"))
    key = press(client, graph(setup_node()), "s", auth)["saved_id"]
    listed = client.get(RESULTS, headers=auth).json()["results"]
    assert [(r["trial_key"], r["synthetic"]) for r in listed] == [(key, True)]
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    assert client.get(RESULTS, headers=auth).json()["results"] == []


def test_a_results_list_that_cannot_be_read_says_so_instead_of_looking_empty(client, auth, kept, monkeypatch):
    monkeypatch.setattr(trials, "results_of", lambda *a, **k: None)
    out = client.get(RESULTS, headers=auth).json()
    assert out["available"] is False and out["reason"] and out["results"] == []


# ── 닫힌 길 ───────────────────────────────────────────────────────────────────────────
def test_neither_node_has_an_output_port_so_results_cannot_be_ranked_or_compared():
    for kind in ("intraday_setup", "intraday_load"):
        spec = REGISTRY.get(kind)
        assert spec.outputs == () and spec.wants_actor is True and spec.category == "백테스트"
    assert REGISTRY.get("intraday_setup").save_label == "분봉 백테스트 실행"
    assert REGISTRY.get("intraday_load").save is None                           # 읽는 노드는 남기지 않는다
    assert {"intraday_setup", "intraday_load"} <= set(HISTORY)


def test_a_graph_with_an_intraday_node_cannot_become_a_client_sheet(client, auth, monkeypatch):
    """한 장은 실행자 없이 다시 계산한다 → 분봉 노드가 실패한다 → 본 것과 달라 거절된다. 분봉 결과는 유통 표면에 실리지 않는다."""
    with_days(monkeypatch, made_days())
    u = {"id": "u", "type": "universe", "params": {"tickers": ["005930", "000660"], "weights": {"005930": 0.6, "000660": 0.4}}}
    w = {"id": "w", "type": "current_weights", "params": {}}
    edge = {"source": "u", "source_port": "universe", "target": "w", "target_port": "universe"}
    plain = graph(u, w, edges=[edge])
    seen = {nid: r["view_hash"] for nid, r in run(client, plain, auth).items()}
    assert pg.run_for_sheet(plain, "w", seen, REGISTRY)["ok"] is True            # 짝 — 분봉 노드가 없으면 된다
    mixed = graph(u, w, setup_node(), edges=[edge])
    seen = {nid: r["view_hash"] for nid, r in run(client, mixed, auth).items()}
    assert seen["s"] is not None
    out = pg.run_for_sheet(mixed, "w", seen, REGISTRY)
    assert out["ok"] is False and out["code"] == "stale"


def test_the_ai_helpers_are_not_offered_the_intraday_nodes():
    """도구는 규칙과 종목을 추천하지 않는다 — AI 추천과 말로 설계의 후보 표에 분봉 노드가 없다(설명·묻기의 표에는 있다)."""
    from src.api import allocation_graph_routes as graph_routes
    from src.api import canvas_assist_routes as assist
    offered = assist.offered_kinds()
    assert "intraday_setup" not in offered and "intraday_load" not in offered
    assert "universe" in offered and "backtest_setup" in offered                # 짝 — 다른 노드는 그대로 후보다
    assert "intraday_setup" in graph_routes._kinds()
    assert "intraday_setup" not in assist._draft_kinds() and "universe" in assist._draft_kinds()


# ── 매개변수 모델은 등록부에서 만든다 ─────────────────────────────────────────────────────────
def test_the_setup_form_is_built_from_the_registries_not_copied():
    """틀 · 포지션 · 비용의 칸은 등록부의 것 그대로다(기본값 · 범위 · 단위 · 순서) — 등록부가 바뀌면 캔버스의 폼도 따라 바뀐다."""
    import src.api.intraday_routes as mod
    from src.engine.intraday import rules
    props = {c["type"]: c for c in REGISTRY.catalog()}["intraday_setup"]["params_schema"]["properties"]
    templates = rules.describe()
    assert props["rule"]["enum"] == [t["kind"] for t in templates]
    assert props["rule"]["x-ui"]["order"] == [t["kind"] for t in templates]
    assert props["rule"]["x-ui"]["options"] == {t["kind"]: t["label"] for t in templates}
    assert props["rule"]["default"] == templates[0]["kind"]                     # 화면과 같이 첫 틀에서 시작한다
    seen = 0
    for t in templates:
        for d in t["params"]:
            p = props[f"{t['kind']}__{d['key']}"]
            assert p["x-ui"]["show_if"] == {"rule": [t["kind"]]} and p["x-ui"]["label"] == d["label"] and p["default"] == d["default"]
            if d["type"] in ("int", "float"):
                assert (p["minimum"], p["maximum"]) == (d["min"], d["max"]) and p["x-ui"]["widget"] == "input"
            seen += 1
    assert seen == sum(len(t["params"]) for t in templates) >= 10
    for d in (*mod.POSITION_FIELDS, *mod.COST_FIELDS):
        assert props[d["key"]]["x-ui"]["label"] == d["label"] and props[d["key"]].get("default") == d["default"]
    assert props["tickers"].get("default", []) == [] and props["start_date"]["default"] is None       # 종목·기간은 비어서 시작한다
    assert props["commission_bp"]["default"] is None                            # 수수료율은 모름에서 시작한다(0 이 아니다)
