"""고객 한 장에게 묻기 (CF 3부 PB4 · PB6 고객 AI 가 같은 것을 쓴다) — ★근거는 그 한 장의 줄뿐★.
==============================================================================
한 장은 서버가 같은 그래프를 다시 계산해 만든 것이라(`pb_sheets.build_sheet`) 봉인 확인 없이 그대로 근거다 — 화면이 보낸 것을 믿지 않고
서버가 저장한 한 장을 읽는다. 줄: 주인공 비중 한 줄 → 흐름 순서의 단계마다 서버 설명 줄(AI3 와 같은 칸) · 계산 못 한 단계는 사유 한 줄.
답할 수 없으면 ★고객용 고정 문장★(`CANNOT_CLIENT` — 투자 판단은 담당 PB 와 상담하라고). 검사는 AI3 그대로(문장마다 줄 · 그 줄의 숫자만).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.services.canvas_assist.ask import _node_lines

CANNOT_CLIENT = {
    "not_in_facts": "이 한 장에 적힌 내용으로는 답할 수 없어요.",
    "judgement": "투자 판단은 담당 PB와 상담해 주세요 — 여기서는 이 한 장에 적힌 내용만 설명해요.",
    "off_topic": "이 한 장의 포트폴리오에 대해 물어 주세요.",
}
_PART = {"title": "제목", "headline": "핵심 값", "fact": "사실", "trust": "믿음", "unmeasured": "재지 않은 것"}


def ground_sheet(sheet: Mapping[str, Any], sheet_id: str, question: str,
                 previous: Mapping[str, str] | None) -> tuple[dict, dict[str, dict]]:
    """`(근거, refs {줄 id: {target_kind:"sheet", target_id, part, index, text}})`."""
    lines: list[dict] = []
    refs: dict[str, dict] = {}

    def add(where: str, part: str, index: int, text: str) -> None:
        fid = f"f{len(lines) + 1}"
        lines.append({"id": fid, "where": where, "part": part, "text": text})
        refs[fid] = {"target_kind": "sheet", "target_id": sheet_id, "where": where, "part": part, "index": index, "text": text}

    focus = sheet.get("focus") or {}
    ws = focus.get("weights") or []
    if ws:
        add(str(focus.get("label") or "비중"), "비중", 0, " · ".join(f"{w['name']} {w['pct']}%" for w in ws))
    for st in sheet.get("steps") or []:
        where = str(st.get("label") or st.get("node_id"))
        if isinstance(st.get("explain"), Mapping):
            for part, i, text in _node_lines(st["explain"]):
                add(where, _PART[part], i, text)
        elif st.get("reason"):
            add(where, "계산 못 함", 0, str(st["reason"]))
    g = {"target": {"kind": "sheet", "id": sheet_id, "label": str(sheet.get("title") or "한 장")}, "question": question,
         "previous": dict(previous) if previous else None, "lines": lines, "practice": bool(sheet.get("practice"))}
    return g, refs
