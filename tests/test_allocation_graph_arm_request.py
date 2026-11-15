"""캔버스의 '가동 요청' 노드 (W5b · 구현 계획 §6) — 분봉 결과 조회(`intraday_load`) → 가동 요청(`intraday_arm_request`)
==============================================================================
★요청은 가동이 아니다★ — 캔버스는 '이 시행을 가동해 달라'는 한 줄만 남긴다. 가동 · 정지 · 비상 정지는 내 계좌에서만 한다.

여기서 거는 약속:

- **길 하나.** 분봉 결과의 출력 포트(`IntradayRun`)는 가동 요청만 받는다 — 비교 · 순위 · 비중으로 가는 길이 구조에 없다.
- **계산은 쓰지 않는다.** 미리보기(`/graph/run`)는 어떤 표에도 한 줄도 쓰지 않는다. 단추(`/graph/save`)만 요청 한 줄을 남긴다.
- **아무것도 가동하지 않는다.** 단추 뒤에 늘어난 것은 요청 표의 한 줄뿐이다 — 가동 · 가상 체결 · 주문 줄은 0.
- **본인 것만 · 로그인.** 남의 시행으로는 요청을 만들 수 없다. 로그인하지 않으면 노드가 사유와 함께 실패한다.
- **운영 게이트.** 합성 분봉으로 돌린 시행은 운영에서 요청으로 남기지 않는다 — 모의 모드에서는 연습용 표식을 달고 남는다.
- **못 읽음 ≠ 없음.** 요청 목록을 못 읽으면 '이미 남겼는지'는 미상이다(없다고 하지 않는다).
- **도구는 추천하지 않는다.** AI 후보 표 · 고객 한 장에 실리지 않는다. 주문 경로를 import 하지 않는다(정적).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import src.api.allocation_graph_nodes as gn
import src.api.allocation_graph_nodes_intraday as nodes
import src.data.rule_runs as rr
from src.api import graph_actor
from src.api.allocation_graph_nodes import REGISTRY
from src.engine import portfolio_graph as pg
from tests.graph_write_guard import WRITERS, graph_write_guard  # noqa: F401
from tests.test_allocation_graph_intraday import (  # noqa: F401 — 고정물은 이름으로 들여와야 쓰인다
    _the_run_stores_table_flag_is_left_as_found,
    auth,
    client,
    graph,
    kept,
    load_node,
    press,
    run,
    setup_node,
    table_rows,
)
from tests.test_intraday_validate_route import login, made_days, with_days

pytestmark = pytest.mark.usefixtures("graph_write_guard")

ROOT = Path(__file__).resolve().parents[1]
ARM = "intraday_arm_request"
REQS = "/api/v1/intraday/arm-requests"
EDGE = {"source": "l", "source_port": "run", "target": "a", "target_port": "run"}
NO_LOGIN = "로그인하지 않았습니다"


def arm_node(**params) -> dict:
    return {"id": "a", "type": ARM, "params": params}


def armed(key: str | None, **params) -> dict:
    return graph(load_node(key), arm_node(**params), edges=[EDGE])


def _actor(client, user="alice") -> graph_actor.Actor:
    """노드 함수를 직접 부를 때의 실행자 — 문이 신원을 확인한 뒤 엔진에 넘기는 것과 같은 값."""
    return graph_actor.Actor(user)


# ── 길 하나 ───────────────────────────────────────────────────────────────────────────
def test_the_result_node_hands_its_run_only_to_the_request_node():
    load, arm = REGISTRY.get("intraday_load"), REGISTRY.get(ARM)
    assert [(p.name, p.type) for p in load.outputs] == [("run", "IntradayRun")]
    assert [(p.name, p.type, p.required) for p in arm.inputs] == [("run", "IntradayRun", True)] and arm.outputs == ()
    takers = sorted(c["type"] for c in REGISTRY.catalog() if any(p["type"] == "IntradayRun" for p in c["inputs"]))
    givers = sorted(c["type"] for c in REGISTRY.catalog() if any(p["type"] == "IntradayRun" for p in c["outputs"]))
    assert takers == [ARM] and givers == ["intraday_load"]        # 비교 · 순위 · 비중 노드는 이 종류를 받지 않는다
    assert REGISTRY.get("intraday_setup").outputs == ()
    assert "IntradayRun" in gn.PORT_TYPES and gn.PORT_PLAIN["IntradayRun"]


def test_the_request_node_sits_in_the_act_stage_and_only_its_button_writes():
    arm = REGISTRY.get(ARM)
    assert (arm.stage, arm.category, arm.wants_actor, arm.save_label) == ("act", "실행", True, "가동 요청 남기기")
    assert arm.save is not None and arm.plain_label == "가동 요청"
    assert "가동하지 않습니다" in arm.plain_description
    for name in ("add_request", "remove_request", "open_run", "update_run", "add_fill", "mark_interrupted"):
        assert ("src.data.rule_runs", name) in WRITERS, name      # 계산 중 쓰기 감시가 가동 기록의 쓰기를 전부 안다


# ── 계산은 쓰지 않는다 ───────────────────────────────────────────────────────────────────
def test_computing_the_request_writes_nothing_and_shows_what_would_be_requested(client, auth, kept):
    before = table_rows()
    out = run(client, armed(kept), auth)
    assert table_rows() == before
    assert out["l"]["status"] == "ok" and out["a"]["status"] == "ok", out["a"].get("reason")
    v, seen = out["a"]["view"], out["l"]["view"]
    assert (v["trial_key"], v["tickers"], v["from"], v["to"]) == (kept, ["005930"], "2026-03-02", "2026-03-13")
    assert (v["rule_kind"], v["grade"], v["synthetic"], v["runs"]) == ("opening_range_breakout", "E3", False, 1)
    assert v["rule_label"] and v["rule_label"] != v["rule_kind"]
    assert v["gates"] == {"known": True, "counts": seen["gates"]["counts"]} and sum(v["gates"]["counts"].values()) == 7
    assert (v["requested"], v["request_id"], v["mock"]) == (False, None, True)


def test_a_request_node_without_a_result_says_what_is_missing(client, auth):
    out = run(client, graph(arm_node()), auth)["a"]
    assert out["status"] != "ok" and "필수 입력" in out["reason"]


# ── 단추 — 요청 한 줄 · 가동 0 ──────────────────────────────────────────────────────────────
def test_the_button_leaves_one_request_and_starts_nothing(client, auth, kept):
    before = table_rows()
    done = press(client, armed(kept, note="장 시작 전에 다시 봄"), "a", auth)
    assert done["ok"] is True and "내 계좌" in done["text"] and "가동" in done["text"]
    after = table_rows()
    grown = {t: after[t] - before.get(t, 0) for t in after if after[t] != before.get(t, 0)}
    assert grown == {"rule_arm_requests": 1}                      # ★가동 · 가상 체결 · 주문 줄은 0★
    rows = rr.requests_of("alice")
    assert [(r["trial_key"], r["note"]) for r in rows] == [(kept, "장 시작 전에 다시 봄")] and done["saved_id"] == str(rows[0]["id"])
    listed = client.get(REQS, headers=auth).json()["requests"]   # 내 계좌의 문이 같은 줄을 읽는다
    assert [(r["id"], r["trial"]["found"], r["gates"]["known"]) for r in listed] == [(rows[0]["id"], True, True)]


def test_pressing_again_does_not_leave_a_second_request(client, auth, kept):
    first = press(client, armed(kept), "a", auth)
    seen = run(client, armed(kept), auth)["a"]["view"]
    assert (seen["requested"], seen["request_id"]) == (True, int(first["saved_id"]))
    again = press(client, armed(kept), "a", auth)
    assert again["ok"] is True and again["saved_id"] == first["saved_id"] and "이미" in again["text"]
    assert len(rr.requests_of("alice")) == 1


def test_a_removed_request_can_be_left_again(client, auth, kept):
    first = press(client, armed(kept), "a", auth)
    assert rr.remove_request("alice", int(first["saved_id"])) is True
    assert run(client, armed(kept), auth)["a"]["view"]["requested"] is False
    second = press(client, armed(kept), "a", auth)
    assert second["ok"] is True and second["saved_id"] != first["saved_id"] and "이미" not in second["text"]


# ── 신원 · 본인 것만 ────────────────────────────────────────────────────────────────────
def test_without_login_the_request_node_fails_and_the_button_does_nothing(client, auth, kept):
    out = run(client, armed(kept))
    assert out["a"]["status"] != "ok"
    alone = REGISTRY.get(ARM)
    nobody = graph_actor.Actor(None, graph_actor.NOT_SIGNED_IN)   # 문이 로그인하지 않은 요청에 넘기는 실행자
    with pytest.raises(pg.NodeFailure) as err:                    # 앞 노드가 통과했더라도 이 노드가 스스로 묻는다
        alone.run({"run": {"trial_key": kept, "grade": "E3", "gates": None}}, alone.params_model(), nobody)
    assert NO_LOGIN in err.value.reason and "가동 요청" in err.value.reason
    with pytest.raises(pg.NodeFailure) as err:                    # 단추도 스스로 묻는다(미리보기를 거치지 않은 호출)
        alone.save({}, {"trial_key": kept, "synthetic": False, "note": None}, alone.params_model(), nobody)
    assert NO_LOGIN in err.value.reason
    done = press(client, armed(kept), "a")
    assert done["ok"] is False and rr.requests_of("alice") == []


def test_someone_elses_result_cannot_be_requested(client, auth, kept):
    bob = login(client, "bob")
    out = run(client, armed(kept), bob)
    assert out["l"]["status"] != "ok" and out["a"]["status"] != "ok"
    spec = REGISTRY.get(ARM)
    with pytest.raises(pg.NodeFailure) as err:                    # 열쇠를 알아도 내 시행이 아니면 없는 것과 같은 문장
        spec.run({"run": {"trial_key": kept, "grade": "E3", "gates": None}}, spec.params_model(), _actor(client, "bob"))
    assert err.value.reason == nodes.REASONS["not_found"]
    assert press(client, armed(kept), "a", bob)["ok"] is False
    assert rr.requests_of("bob") == [] and rr.requests_of("alice") == []


# ── 운영 게이트 ─────────────────────────────────────────────────────────────────────────
def test_a_synthetic_trial_is_requested_as_practice_in_mock_mode_and_refused_in_production(client, auth, monkeypatch):
    with_days(monkeypatch, made_days(source="synthetic"))
    key = press(client, graph(setup_node()), "s", auth)["saved_id"]
    out = run(client, armed(key), auth)["a"]
    assert out["status"] == "ok" and (out["view"]["grade"], out["view"]["synthetic"]) == ("E0", True)
    assert any(t.get("kind") == "practice" for t in out["explain"]["trust"])
    spec, actor = REGISTRY.get(ARM), _actor(client)
    values = {"run": {"trial_key": key, "grade": "E0", "gates": None}}
    monkeypatch.setattr(nodes, "mock_allowed", lambda: False)
    with pytest.raises(pg.NodeFailure) as err:
        spec.run(values, spec.params_model(), actor)
    assert err.value.reason == nodes.REASONS["synthetic_in_production"]
    with pytest.raises(pg.NodeFailure) as err:                    # 미리보기를 모의 모드에서 본 뒤 단추가 운영에서 눌려도 남기지 않는다
        spec.save({}, out["view"], spec.params_model(), actor)
    assert err.value.reason == nodes.REASONS["synthetic_in_production"]
    assert rr.requests_of("alice") == []


def test_the_weaker_of_the_two_grades_decides(client, auth, kept, monkeypatch):
    """시행 줄의 등급과 넘겨받은 결과의 등급이 다르면 ★약한 쪽★이 정한다 — 어느 한쪽만 합성이어도 합성이다."""
    spec, actor = REGISTRY.get(ARM), _actor(client)
    handed_weaker = spec.run({"run": {"trial_key": kept, "grade": "E0", "gates": None}}, spec.params_model(), actor)
    assert (handed_weaker.view["grade"], handed_weaker.view["synthetic"]) == ("E3", True)     # 시행은 실제 · 넘겨받은 결과는 합성
    with_days(monkeypatch, made_days(source="synthetic"))
    synthetic_key = press(client, graph(setup_node(amount=2_000_000)), "s", auth)["saved_id"]
    assert synthetic_key != kept
    trial_weaker = spec.run({"run": {"trial_key": synthetic_key, "grade": "E3", "gates": None}}, spec.params_model(), actor)
    assert (trial_weaker.view["grade"], trial_weaker.view["synthetic"]) == ("E0", True)       # 시행은 합성 · 넘겨받은 결과는 실제라고 함
    monkeypatch.setattr(nodes, "mock_allowed", lambda: False)
    for values in ({"trial_key": kept, "grade": "E0", "gates": None}, {"trial_key": synthetic_key, "grade": "E3", "gates": None}):
        with pytest.raises(pg.NodeFailure) as err:
            spec.run({"run": values}, spec.params_model(), actor)
        assert err.value.reason == nodes.REASONS["synthetic_in_production"]


def test_a_real_grade_trial_is_still_requested_in_production(client, auth, kept, monkeypatch):
    """짝 — 운영 게이트가 모든 요청을 막는 구현이 아님을 건다."""
    monkeypatch.setattr(nodes, "mock_allowed", lambda: False)
    done = press(client, armed(kept), "a", auth)
    assert done["ok"] is True and len(rr.requests_of("alice")) == 1


# ── 못 읽음 ≠ 없음 ──────────────────────────────────────────────────────────────────────
def test_when_the_request_list_cannot_be_read_already_requested_is_unknown(client, auth, kept, monkeypatch):
    monkeypatch.setattr(rr, "requests_of", lambda *a, **k: None)
    out = run(client, armed(kept), auth)["a"]
    assert out["status"] == "ok" and out["view"]["requested"] is None
    assert any(t["state"] == "unknown" and "확인하지 못했습니다" in t["text"] for t in out["explain"]["trust"])


def test_when_the_request_cannot_be_kept_the_button_says_so(client, auth, kept, monkeypatch):
    monkeypatch.setattr(rr, "add_request", lambda *a, **k: None)
    done = press(client, armed(kept), "a", auth)
    assert done["ok"] is False and done["code"] == "save_failed" and done["message"] == nodes.REASONS["request_not_kept"]


def test_when_the_trial_record_cannot_be_read_the_node_does_not_call_it_missing(client, auth, kept, monkeypatch):
    spec, actor = REGISTRY.get(ARM), _actor(client)
    monkeypatch.setattr(nodes.trials, "trial_of", lambda *a, **k: None)
    with pytest.raises(pg.NodeFailure) as err:
        spec.run({"run": {"trial_key": kept, "grade": "E3", "gates": None}}, spec.params_model(), actor)
    assert err.value.reason == nodes.REASONS["store_unreadable"] != nodes.REASONS["not_found"]


def test_a_result_handed_over_without_gate_counts_is_shown_as_unknown_not_as_passed(client, auth, kept):
    """관문 수가 넘어오지 않으면 '안다'고 하지 않는다 — 수를 지어내지 않고 미상이라고 적는다(가동은 막지 않는다)."""
    spec = REGISTRY.get(ARM)
    out = spec.run({"run": {"trial_key": kept, "grade": "E3", "gates": None}}, spec.params_model(), _actor(client))
    assert out.view["gates"] == {"known": False, "counts": None}
    said = spec.explain(out.view, {}, spec.params_model())
    assert any("판정 결과를 남기지 않은 실행" in f for f in said["facts"]) and not any("통과" in f for f in said["facts"])


# ── 메모 ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("note", ["010-1234-5678 로 연락", "kim@example.com", "계좌 50123456789"])
def test_a_note_shaped_like_personal_data_is_refused(client, auth, kept, note):
    out = run(client, armed(kept, note=note), auth)["a"]
    assert out["status"] != "ok" and "메모" in out["reason"]
    assert press(client, armed(kept, note=note), "a", auth)["ok"] is False and rr.requests_of("alice") == []


def test_a_plain_note_and_no_note_both_pass(client, auth, kept):
    assert run(client, armed(kept, note="2026-03-04 개장 전 점검"), auth)["a"]["status"] == "ok"   # 날짜는 개인정보가 아니다
    assert run(client, armed(kept), auth)["a"]["view"]["note"] is None
    schema = {c["type"]: c for c in REGISTRY.catalog()}[ARM]["params_schema"]
    assert list(schema["properties"]) == ["note"] and schema.get("additionalProperties") is False


# ── 설명 ─────────────────────────────────────────────────────────────────────────────
def test_the_request_explains_itself_without_overclaiming(client, auth, kept):
    ex = run(client, armed(kept), auth)["a"]["explain"]
    text = " ".join([ex["title"], *ex["facts"], *(t["text"] for t in ex["trust"]), *ex["unmeasured"]])
    assert "요청은 가동이 아닙니다" in text and "내 계좌" in text and "증권사로 주문을 전송하지 않습니다" in text
    assert "통과" in text and "미달" in text and "미상" in text       # 관문은 보여 주기만 한다
    for word in ("검증됨", "입증", "견고", "투자 우위", "더 나은 전략", "추천", "권장"):
        assert word not in text, word
    assert any("실제 계좌" in u or "체결" in u for u in ex["unmeasured"])


# ── 닫힌 길 ───────────────────────────────────────────────────────────────────────────
def test_the_ai_helpers_are_not_offered_the_request_node():
    from src.api import allocation_graph_routes as graph_routes
    from src.api import canvas_assist_routes as assist
    assert ARM in nodes.NOT_OFFERED and ARM not in assist.offered_kinds() and ARM not in assist._draft_kinds()
    assert ARM in graph_routes._kinds() and "order_preview" in assist.offered_kinds()      # 짝 — 다른 실행 노드는 그대로 후보다


def test_a_graph_with_a_request_node_cannot_become_a_client_sheet(client, auth, kept):
    g = armed(kept)
    seen = {nid: r["view_hash"] for nid, r in run(client, g, auth).items()}
    assert seen["a"] is not None
    out = pg.run_for_sheet(g, "a", seen, REGISTRY)                # 한 장은 실행자 없이 다시 계산한다 → 본 것과 달라 거절
    assert out["ok"] is False


def _order_path_imports(source: str) -> list[str]:
    banned = ("trading_engine", "order_executor", "kis_client", "src.execution", "rule_runner", "account_executors",
              "broker_account")
    tree = ast.parse(source)
    names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    names += [f"{n.module}.{a.name}" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names]
    names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    return sorted({n for n in names if any(b in n for b in banned)})


def test_the_intraday_node_module_never_imports_the_order_path():
    """정적 시험 — 캔버스는 요청까지만이다. 가동기 · 계좌 실행기 · 증권사 클라이언트를 들이는 순간 캔버스가 주문 경로에 닿는다."""
    assert _order_path_imports("from src.execution import rule_runner\n") == ["src.execution", "src.execution.rule_runner"]
    assert _order_path_imports("from src.api import broker_account_routes\nimport src.execution.kis_client\n")   # 심은 표본을 잡는다
    assert _order_path_imports("from src.data import rule_runs\n") == []                                      # 저장소는 주문 경로가 아니다
    source = (ROOT / "src/api/allocation_graph_nodes_intraday.py").read_text(encoding="utf-8")
    assert _order_path_imports(source) == []
