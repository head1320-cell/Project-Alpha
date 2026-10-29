"""고객 한 장 짓기 (CF 3부 PB4) — ★서버가 다시 계산한 보고에서 옮기기만 한다★(리포트 AD5 규율 — 새 숫자를 만들지 않는다).
==============================================================================
- 단계(`steps`) — 흐름 순서의 ★모든★ 노드: 계산되면 서버 설명(제목·핵심 값·사실·믿음·재지 않은 것) 그대로, 못 되면 '계산 못 함' + 사유.
  막힘도 사유와 함께 남는다(빠뜨리지 않는다). 쉬운 이름은 노드 카탈로그의 것.
- 주인공(`focus`) — PB 가 고른 비중 노드의 view 비중 표(종목 코드 → %) ★그대로★ · 이름은 view 의 이름표(`stock_master` 가 낸 것).
  반올림·합계·정렬 외의 가공을 하지 않는다(정렬은 큰 비중부터 — 숫자를 바꾸지 않는다).
- 연습용(`practice`) — 어느 노드라도 합성 계보면 참 + 고정 문장. 판단은 계보가 하고 이 모듈은 옮긴다.
- 기준(`computed_at`) — 서버가 다시 계산한 때(UTC). 데이터의 기준일은 각 노드 설명이 말한다.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from src.services.canvas_assist.narrate import NOTICE, flow_order

#: 한 장이 담는 서버 설명 칸 — 이 밖의 칸(그림 등)은 옮기지 않는다.
_EXPLAIN_KEYS = ("title", "headline", "facts", "trust", "unmeasured")


def _explain(ex: Any) -> dict | None:
    if not isinstance(ex, Mapping):
        return None
    return {k: ex[k] for k in _EXPLAIN_KEYS if k in ex and ex[k] is not None}


def build_sheet(graph: dict, report: dict, focus_id: str, *, title: str, client_alias: str,
                kinds: Mapping[str, Mapping]) -> dict:
    nodes = report["nodes"]
    types = {n["id"]: n.get("type") for n in graph["nodes"] if isinstance(n, dict)}
    label = {nid: str((kinds.get(str(t)) or {}).get("plain_label") or t) for nid, t in types.items()}
    steps = []
    for nid in flow_order(graph):
        r = nodes.get(nid) or {}
        ok = r.get("status") == "ok"
        steps.append({"node_id": nid, "type": types.get(nid), "label": label.get(nid, nid), "status": r.get("status"),
                      "explain": _explain(r.get("explain")) if ok else None,
                      "reason": None if ok else (r.get("reason") or "사유를 받지 못했어요")})
    view = nodes[focus_id].get("view") or {}
    names = view.get("labels") or {}
    weights = [{"code": str(k), "name": str(names.get(k) or k), "pct": v} for k, v in view["weights"].items()]
    weights.sort(key=lambda w: -(w["pct"] if isinstance(w["pct"], (int, float)) else 0))
    practice = any(bool((r.get("lineage") or {}).get("practice")) for r in nodes.values())
    return {
        "title": title, "client_alias": client_alias,
        "computed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "focus": {"node_id": focus_id, "label": label.get(focus_id, focus_id), "weights": weights},
        "steps": steps, "practice": practice, "practice_note": NOTICE if practice else None,
        "note": "이 한 장은 서버가 같은 설계를 다시 계산한 설명과 비중을 옮겼어요 — 새 숫자를 만들지 않았어요.",
    }
