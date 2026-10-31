"""관계 문장 — 선 하나가 ★무엇을 · 어디서 어디로 · 무엇에 쓰이려고★ 나르는지 (CF3, 순수)
==============================================================================
스펙 `docs/superpowers/specs/2026-10-16-cf-comfy-canvas-claude-design.md` §CF3. 설명은 서버가 쓴다(BJ·ADR-002).

틀(조사 문제를 피한 꼴): `‘{보내는 노드}’의 {포트 쉬운 이름}({선 요약}) → ‘{받는 노드}’ {받는 포트 쉬운 이름} 자리. {받는 포트 role}`
- 선 요약(`briefs`)이 없으면(계산 전) 괄호를 뺀다 · 받는 포트에 확인한 역할(`role`)이 없으면 둘째 문장을 뺀다 — 지어내지 않는다.
- 노드·포트·타입이 맞는 선만 문장을 받는다(틀린 선은 오류가 따로 말한다).

★`src.*` 를 import 하지 않는다★(테스트가 AST 로 건다) — 종류 표·포트 쉬운 이름은 라우트가 넘긴다.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def relations(nodes: list, edges: list, kinds: Mapping[str, Mapping], port_plain: Mapping[str, str],
              briefs: Mapping[tuple[str, str], str] | None = None) -> dict[str, dict]:
    """`{edge_id: {text, flows, role, required, brief}}` — `edges` 의 `id` 는 라우트가 엔진 규칙으로 채워 넘긴다."""
    type_of = {str(n.get("id")): str(n.get("type")) for n in nodes if isinstance(n, Mapping)}
    out: dict[str, dict] = {}
    for e in edges:
        if not isinstance(e, Mapping):
            continue
        s, sp, t, tp = (str(e.get(k) or "") for k in ("source", "source_port", "target", "target_port"))
        sk, tk = kinds.get(type_of.get(s, "")), kinds.get(type_of.get(t, ""))
        if not sk or not tk:
            continue
        op = next((p for p in sk.get("outputs") or [] if p.get("name") == sp), None)
        ip = next((p for p in tk.get("inputs") or [] if p.get("name") == tp), None)
        if op is None or ip is None or op.get("type") != ip.get("type"):
            continue
        flows = str(port_plain.get(op["type"], op["type"]))
        brief = (briefs or {}).get((s, sp))
        role = ip.get("role") or None
        text = (f"‘{sk.get('plain_label')}’의 {flows}{f'({brief})' if brief else ''} → "
                f"‘{tk.get('plain_label')}’ {flows} 자리.") + (f" {role}" if role else "")
        out[str(e.get("id"))] = {"text": text, "flows": flows, "role": role,
                                 "required": ip.get("required") is not False, "brief": brief or None}
    return out


def briefs_of(report_nodes: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    """`/run` 보고서 → (노드, 출력 포트) 별 선 요약 — 계산이 끝난(ok) 노드만."""
    return {(nid, port): text for nid, r in report_nodes.items()
            if isinstance(r, Mapping) and r.get("status") == "ok"
            for port, text in (r.get("briefs") or {}).items()}
