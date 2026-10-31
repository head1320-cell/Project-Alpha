"""BU6a+ — 기업 분석 화면의 시나리오 가중 경우 셋이 캔버스 노드 기본값과 같은지.

화면(`frontend/src/entities/company/modelsApi.ts` 의 `DEFAULT_SCENARIOS`)은 캔버스 노드
`company_scenarios` 의 기본값(`ScenariosParams.scenarios`)을 옮겨 쓴다. 두 곳이 따로 바뀌면 같은 종목의
"확률로 묶은 적정가"가 화면마다 달라진다 — ★서버 기본값이 진실이고 화면은 거울이다★.
"""
from __future__ import annotations

import pathlib
import re

from src.api import allocation_graph_nodes  # noqa: F401 — 레지스트리를 먼저 올려야 아래 모듈이 순환 없이 읽힌다
from src.api.allocation_graph_nodes_company_models import ScenariosParams  # noqa: E402

TS = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src" / "entities" / "company" / "modelsApi.ts"


def _front() -> list[dict]:
    src = TS.read_text(encoding="utf-8")
    block = re.search(r"export const DEFAULT_SCENARIOS = \[(.*?)\] as const;", src, re.S)
    assert block, "DEFAULT_SCENARIOS 를 찾지 못했다 — 이름을 바꿨다면 이 테스트도 함께"
    rows = []
    for obj in re.findall(r"\{([^}]*)\}", block.group(1)):
        row: dict = {}
        for k, v in re.findall(r"(\w+):\s*(\"[^\"]*\"|[\d.]+)", obj):
            row[k] = v.strip('"') if v.startswith('"') else float(v)
        rows.append(row)
    return rows


def _back() -> list[dict]:
    out = []
    for it in ScenariosParams.model_fields["scenarios"].default:
        out.append({k: v for k, v in it.model_dump().items() if v is not None})
    return out


def test_front_scenarios_mirror_the_canvas_node_default():
    assert _front() == _back()


def test_the_mirror_is_not_vacuous():
    """짝 — 비교가 공허하지 않다: 세 경우가 있고, 확률의 합은 1, 하나라도 바꾸면 다르다."""
    front = _front()
    assert len(front) == 3
    assert abs(sum(r["prob"] for r in front) - 1.0) < 1e-9
    changed = [dict(r) for r in front]
    changed[0]["prob"] = 0.3
    assert changed != _back()
