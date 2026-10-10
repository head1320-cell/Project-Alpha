"""BT7 · 고치는 법 한 줄 — ★오류마다 서버가 고치는 법을 말한다★ (HISTORY:20587 미결 "How to fix line per error")
==============================================================================
대상 `src/domain/design_procedure.py`(`fixes`) · `POST /api/v1/allocation/graph/validate`(`fix` 문장)

## 거는 것 (짝으로 항상-제안·항상-침묵을 배제한다)
- 빠진 필수 입력마다 고치는 법 하나: 있는 생산자를 먼저 잇고(하류는 빼고), 없으면 붙여 잇는다 — 다음 한 걸음 규칙 1과 같은 판단.
- 빠진 입력이 없으면 `fixes` 는 비어 있다. 생산자가 카탈로그에 아예 없으면 지어내지 않는다(그 입력은 빠진다).
- `/validate` 의 `missing_input` 오류는 절차의 그 고치는 법 문장을 그대로 `fix` 로 싣는다 — 화면이 둘을 따로 만들지 않는다.
- `type_mismatch` 는 받는 자리가 무엇을 받는지 말한다(카탈로그 쉬운 이름). 선은 고치는 법이 "다른 선"이라 노드를 제안하지 않는다.
- 금지 표현이 없다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from fastapi.testclient import TestClient  # noqa: E402

from src.api import allocation_graph_routes as routes  # noqa: E402
from src.api.allocation_graph_nodes import PORT_PLAIN, STAGES  # noqa: E402
from src.domain import design_procedure as proc  # noqa: E402

KINDS = routes._kinds()
F = {"format": "project-alpha.portfolio-graph", "version": 1}
BANNED = ("검증됨", "입증됨", "견고함", "프로덕션 레디", "투자 우위", "더 나은 전략", "통과해요", "좋아져요")


def _n(i, t, **p):
    return {"id": i, "type": t, "params": p, "position": {"x": 0, "y": 0}}


def _e(s, sp, t, tp):
    return {"id": f"{s}.{sp}->{t}.{tp}", "source": s, "source_port": sp, "target": t, "target_port": tp}


def _proc(nodes, edges):
    return proc.evaluate(nodes, edges, KINDS, STAGES, PORT_PLAIN)


def _client():
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


UNI = _n("u", "universe", tickers=["005930", "000660"])


def test_each_node_missing_an_input_gets_one_fix_connecting_an_existing_producer_first():
    # 수익률이 있는데 비중 계산에 잇지 않았다 → 있는 것을 잇는다(붙이지 않는다)
    nodes = [UNI, _n("r", "returns"), _n("o", "optimizer")]
    p = _proc(nodes, [_e("u", "universe", "r", "universe")])
    fx = p["fixes"]["o"]
    assert fx["action"] == "connect" and fx["kind"] is None
    assert {"source": "r", "source_port": "returns", "target": "o", "target_port": "returns"} in fx["attach"]
    assert set(p["fixes"]) == {"o"}                                       # ★짝★ 빠진 게 없는 노드는 없다


def test_without_a_producer_the_fix_adds_one_wired_to_the_gap():
    p = _proc([_n("o", "optimizer")], [])
    fx = p["fixes"]["o"]
    assert fx["action"] == "add" and fx["kind"] == "returns"
    assert fx["attach"] == [{"source": proc.NEW, "source_port": "returns", "target": "o", "target_port": "returns"}]


def test_a_downstream_node_is_never_the_fix_for_its_own_upstream():
    # 위험 나누기(비중을 받음)는 비중 계산의 하류 — 비중 계산의 빠진 입력을 하류에서 끌어오면 고리가 생긴다
    nodes = [_n("o", "optimizer"), _n("k", "risk")]
    p = _proc(nodes, [_e("o", "weights", "k", "weights")])
    assert all(a["source"] != "k" for a in p["fixes"]["o"]["attach"])


def test_no_missing_inputs_means_no_fixes():
    nodes = [UNI, _n("r", "returns")]
    assert _proc(nodes, [_e("u", "universe", "r", "universe")])["fixes"] == {}


def test_a_fix_is_not_invented_when_nothing_in_the_catalog_produces_the_type():
    kinds = {k: dict(v) for k, v in KINDS.items()}
    # 수익률을 내는 종류를 모두 지운 가상 카탈로그 — 비중 계산의 수익률 입력은 고칠 길이 없다
    for k, v in kinds.items():
        kinds[k] = {**v, "outputs": [o for o in v["outputs"] if o["type"] != "Returns"]}
    p = proc.evaluate([_n("o", "optimizer")], [], kinds, STAGES, PORT_PLAIN)
    assert all(a["target_port"] != "returns" for fx in p["fixes"].values() for a in fx["attach"])


def test_validate_missing_input_errors_carry_the_procedure_fix_sentence():
    doc = {**F, "nodes": [_n("o", "optimizer")], "edges": []}
    body = _client().post("/api/v1/allocation/graph/validate", json=doc).json()
    errs = [e for e in body["errors"] if e["code"] == "missing_input"]
    assert errs, body["errors"]
    fixed = [e for e in errs if e.get("fix")]
    assert fixed, "빠진 입력 오류에 고치는 법이 없다"
    assert body["procedure"]["fixes"]["o"]["text"] in {e["fix"] for e in fixed}
    for e in errs:
        assert "fix" in e                                                 # 없으면 None 으로 — 키는 늘 있다


def test_validate_type_mismatch_says_what_the_slot_takes():
    doc = {**F, "nodes": [UNI, _n("r", "returns"), _n("o", "optimizer"), _n("k", "risk")],
           "edges": [_e("u", "universe", "r", "universe"), _e("r", "returns", "k", "weights")]}
    body = _client().post("/api/v1/allocation/graph/validate", json=doc).json()
    tm = next(e for e in body["errors"] if e["code"] == "type_mismatch")
    assert PORT_PLAIN["Weights"] in tm["fix"] and PORT_PLAIN["Returns"] in tm["fix"]


def test_fix_sentences_carry_no_banned_claims():
    doc = {**F, "nodes": [_n("o", "optimizer"), _n("k", "risk")], "edges": [_e("o", "weights", "k", "weights")]}
    body = _client().post("/api/v1/allocation/graph/validate", json=doc).json()
    texts = [e.get("fix") or "" for e in body["errors"]] + [f["text"] for f in body["procedure"]["fixes"].values()]
    assert texts and all(not any(b in t for b in BANNED) for t in texts)
