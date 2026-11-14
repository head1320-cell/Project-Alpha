"""CF4c · 경유점은 화면 정보 — ★서버는 읽지 않는다★
==============================================================================
캔버스는 선 길(`edges[].waypoints`)을 문서에 남겨 파일 왕복에 싣고, 계산 요청에도 그대로 보낸다.
서버는 링크를 `source·source_port·target·target_port` 로만 읽는다 — 경유점이 있든 없든 검증·계산 결과가 같아야 한다.
(경유점이 계산을 바꾸면 '선 모양을 바꿨더니 숫자가 바뀌었다'가 된다.) 짝: 경유점이 정말 실렸는지 먼저 본다(공허한 비교 배제).
"""
from __future__ import annotations

import copy
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api.allocation_graph_routes import graph_run, graph_validate  # noqa: E402
from tests.test_allocation_graph import chain, market  # noqa: E402,F401


def _with_waypoints(g: dict) -> dict:
    g2 = copy.deepcopy(g)
    for i, e in enumerate(g2["edges"]):
        e["waypoints"] = [{"x": 100 + 11 * i, "y": -55}, {"x": 330, "y": 220 + i}]
    return g2


def _drop_times(x):
    """노드마다 걸린 시간(`elapsed_ms`)은 돌릴 때마다 다르다 — 그것만 빼고 견준다."""
    if isinstance(x, dict):
        return {k: _drop_times(v) for k, v in x.items() if k != "elapsed_ms"}
    if isinstance(x, list):
        return [_drop_times(v) for v in x]
    return x


def test_the_waypoints_are_really_in_the_document():
    g = _with_waypoints(chain())
    assert g["edges"] and all(len(e["waypoints"]) == 2 for e in g["edges"])
    assert all("waypoints" not in e for e in chain()["edges"])


def test_validate_ignores_waypoints(market):
    assert graph_validate(_with_waypoints(chain())) == graph_validate(chain())


def test_run_ignores_waypoints(market):
    a = graph_run(chain(), None)
    b = graph_run(_with_waypoints(chain()), None)
    assert a["nodes"] and _drop_times(b) == _drop_times(a)
