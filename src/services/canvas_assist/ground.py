"""근거 묶음 — Claude 에게 주는 것은 이것뿐이고, 답의 숫자는 이 안에 있어야 한다(`check` ③).

★설정값(params)은 싣지 않는다★ — 추천은 노드 종류와 잇는 선뿐이다(설정은 사람이 정한다). 그래서 같은 구조면 같은 근거다.
목표(AI1, 2026-10-23)는 문서 `meta.goal` 키를 서버 문장으로 바꿔 싣는다(`goals.goal_of` — 모르는 키는 없음).
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from src.services.canvas_assist.goals import goal_of

_NUM = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")


def ground(graph: dict, kinds: dict[str, dict], report: dict) -> dict:
    """`graph` 는 읽을 수 있는 문서(치명 오류 없음), `report` 는 그 문서의 `/validate` 응답."""
    proc = report.get("procedure") or {}
    return {
        "goal": goal_of(graph),
        "catalog": {t: {"stage": k["stage"], "label": k["plain_label"],
                        "inputs": [{"name": i["name"], "type": i["type"], "required": i["required"]} for i in k["inputs"]],
                        "outputs": [{"name": o["name"], "type": o["type"]} for o in k["outputs"]]}
                    for t, k in kinds.items()},
        "graph": {"nodes": [{"id": n.get("id"), "type": n.get("type")} for n in graph["nodes"] if isinstance(n, dict)],
                  "edges": [{k: e.get(k) for k in ("source", "source_port", "target", "target_port")}
                            for e in graph["edges"] if isinstance(e, dict)]},
        "procedure": {"steps": [{k: s.get(k) for k in ("key", "label", "need", "state", "node_ids", "text")}
                                for s in proc.get("steps") or []],
                      "next": proc.get("next"), "by_gate": proc.get("by_gate")},
        # 설정값 오류(bad_params)의 문장은 받은 값을 담는다 — 종류만 남긴다.
        "errors": [{"code": e.get("code"), "node_id": e.get("node_id"), "port": e.get("port"),
                    "message": None if e.get("code") == "bad_params" else e.get("message"), "fix": e.get("fix")}
                   for e in report.get("errors") or []],
    }


def _norm(tok: str) -> str | None:
    try:
        return format(Decimal(tok.replace(",", "")).normalize(), "f")
    except InvalidOperation:
        return None


def numbers_of(obj: Any) -> set[str]:
    """구조 안의 모든 숫자(글 속 숫자 포함)를 정규화해 모은다 — `0.30` = `0.3`, `1,234` = `1234`. 참/거짓은 숫자가 아니다."""
    out: set[str] = set()
    if isinstance(obj, dict):
        for v in obj.values():
            out |= numbers_of(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out |= numbers_of(v)
    elif isinstance(obj, bool) or obj is None:
        pass
    elif isinstance(obj, (int, float)):
        n = _norm(repr(obj))
        if n is not None:
            out.add(n)
    elif isinstance(obj, str):
        out |= {n for n in (_norm(m) for m in _NUM.findall(obj)) if n is not None}
    return out
