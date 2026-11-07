"""CF 3부 R3 · 결과 칸 높이는 화면 정보 — ★서버는 읽지 않는다★
==============================================================================
캔버스는 노드의 결과 칸 높이(`nodes[].size.slot_h`)를 문서에 남겨 파일 왕복에 싣고, 계산 요청에도 그대로 보낸다.
서버는 노드를 `id·type·params` 로만 읽는다 — 크기가 있든 없든 검증·계산 결과(보기 서명 `view_hash` 포함)가 같아야 한다.
(크기가 계산을 바꾸면 '칸을 늘렸더니 숫자가 바뀌었다'가 된다.) 짝: 크기가 정말 실렸는지 먼저 본다(공허한 비교 배제).
`test_cf4c_waypoints_ignored.py` 와 같은 모양.
"""
from __future__ import annotations

import copy
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api.allocation_graph_routes import graph_run, graph_validate  # noqa: E402
from tests.test_allocation_graph import chain, market  # noqa: E402,F401


def _with_size(g: dict) -> dict:
    g2 = copy.deepcopy(g)
    for i, n in enumerate(g2["nodes"]):
        n["size"] = {"slot_h": 200 + 11 * i}
    return g2


def _drop_times(x):
    """노드마다 걸린 시간(`elapsed_ms`)은 돌릴 때마다 다르다 — 그것만 빼고 견준다."""
    if isinstance(x, dict):
        return {k: _drop_times(v) for k, v in x.items() if k != "elapsed_ms"}
    if isinstance(x, list):
        return [_drop_times(v) for v in x]
    return x


def test_the_size_is_really_in_the_document():
    g = _with_size(chain())
    assert g["nodes"] and all(n["size"]["slot_h"] >= 200 for n in g["nodes"])
    assert all("size" not in n for n in chain()["nodes"])


def test_validate_ignores_size(market):
    assert graph_validate(_with_size(chain())) == graph_validate(chain())


def test_run_ignores_size(market):
    a = graph_run(chain(), None)
    b = graph_run(_with_size(chain()), None)
    assert a["nodes"] and _drop_times(b) == _drop_times(a)
    assert {k: v.get("view_hash") for k, v in b["nodes"].items()} == {k: v.get("view_hash") for k, v in a["nodes"].items()}
    assert any(v.get("view_hash") for v in a["nodes"].values())
