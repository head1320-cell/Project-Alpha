"""길잡이(AI5) — 캔버스의 도구를 쓰게 이끄는 코치. ★도구 안내만, 투자 판단은 말하지 않는다★(스펙 §AI5 · 사용자 결정 2026-10-23: 규칙 줄 + 누르면 AI).
==============================================================================
- `FEATURES` — 도구 목록(이름·하는 일·쓸 때, 숫자 없음). 화면 `frontend/src/entities/portfolio-graph/guide.ts` 가 같은 id·이름으로 적용 조건과 실행을 갖는다
  (`tests/test_ai5_guide.py` 패리티). 서버는 설명만 갖는다 — 상태는 화면에만 있다(선택·창·켬끔·계산 결과).
- `ground` — 화면이 센 상태(수·참거짓, 막힌 관문은 서버 `GATES` 키만 받아 서버 이름으로) + ★지금 적용되는 도구★의 설명 + 노드 종류 이름. 설정값은 싣지 않는다.
- `check` — 최대 2 · 같은 도구 하나 · 적용되는 도구만 · 이유 70자 · 숫자 ⊆ 상태 · 금지 표현 + 투자 판단 표현. 탈락은 사유와 함께.

한계(적어 둠): 상태는 화면이 센 값이라 서버가 다시 재지 않는다(틀리게 보내면 길잡이가 엉뚱한 도구를 권할 뿐 — 숫자는 그 상태 안에서만, 도구는 목록 안에서만).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.domain.workflow_gates import GATES
from src.services.canvas_assist.check import BANNED
from src.services.canvas_assist.ground import numbers_of

MAX_TIPS = 2
MAX_WHY = 70
#: 길잡이 이유에 쓰지 않는 투자 판단 표현(금지 표현에 더해) — 도구 안내만 한다.
JUDGEMENT = ("사세요", "파세요", "좋은 전략", "나쁜 전략", "수익을 낼", "수익이 날", "돈이 될", "추천 종목")

FEATURES: dict[str, dict[str, str]] = {
    "cause": {"label": "원인 따라가기", "does": "실패하거나 막힌 노드에서 위로 거슬러 올라가 처음 막힌 곳을 보여 줘요.",
              "when": "계산했는데 실패하거나 막힌 노드가 있을 때"},
    "wire_check": {"label": "전달 점검 보기", "does": "선을 따라 넘어가며 빠지거나 바뀐 값을 보여 줘요.",
                   "when": "빠지거나 바뀐 것이 있는 선이 있을 때"},
    "run": {"label": "계산하기", "does": "그래프 전체를 계산해 노드마다 결과와 설명을 내요.",
            "when": "절차를 다 채웠는데 아직 계산하지 않았을 때"},
    "layout": {"label": "자동 정리", "does": "흐름 순서대로 왼쪽에서 오른쪽으로 카드를 놓아요.",
               "when": "카드가 겹쳐 있을 때"},
    "branch": {"label": "갈래 만들기", "does": "노드와 그 아래를 복제해 설정만 바꿔 두 설계를 나란히 비교해요.",
               "when": "계산했고 아직 갈래가 없을 때"},
    "strategy_add": {"label": "전략 더하기", "does": "비중을 내는 다른 방식의 흐름을 하나 더 붙여요.",
                     "when": "비중을 내는 노드가 하나뿐일 때"},
    "compare": {"label": "견고성 비교", "does": "비중 노드 여럿이 평소·위기 때 같이 움직이는지, 크게 잃은 구간이 겹치는지 봐요.",
                "when": "비중을 내는 노드가 둘 이상인데 견고성 비교 노드가 없을 때"},
    "story_ai": {"label": "AI 로 풀어 쓰기", "does": "계산 결과의 서버 설명을 읽는 순서대로 Claude 가 풀어 써요.",
                 "when": "계산했고 결과가 낡지 않았을 때"},
    "ask_ai": {"label": "노드에게 묻기", "does": "고른 노드나 선의 계산 결과에 대해 Claude 에게 물어요.",
               "when": "계산했을 때"},
    "records": {"label": "기록함", "does": "저장한 계산 기록과 일별 손익을 모아 봐요.",
                "when": "과거로 돌려 보기를 계산했을 때"},
    "lanes": {"label": "단계 레인", "does": "흐름 단계를 세로 띠로 깔아 노드가 어느 단계인지 보여 줘요.",
              "when": "노드가 많고 레인이 꺼져 있을 때"},
    "minimap": {"label": "미니맵", "does": "캔버스 전체를 작은 지도로 보여 줘요.",
                "when": "노드가 많고 미니맵이 꺼져 있을 때"},
}
GATE_NAMES = dict(GATES)


def tools(applicable: list[str]) -> list[str]:
    """적용되는 도구 — 서버 목록에 있는 것만, 목록 순서로, 겹친 것은 하나로."""
    want = set(applicable)
    return [k for k in FEATURES if k in want]


def ground(graph: Any, state: Mapping[str, Any], applicable: list[str], kinds: Mapping[str, Mapping]) -> dict:
    types = sorted({str(n.get("type")) for n in (graph.get("nodes") or []) if isinstance(n, dict)}) if isinstance(graph, dict) else []
    st = {k: v for k, v in state.items() if k != "gates_blocked"}
    st["gates_blocked"] = [GATE_NAMES[g] for g in state.get("gates_blocked") or [] if g in GATE_NAMES]
    return {"state": st,
            "tools": [{"id": k, **FEATURES[k]} for k in tools(applicable)],
            "kinds": [(kinds.get(t) or {}).get("plain_label") or t for t in types]}


def _rej(code: str, reason: str) -> dict:
    return {"code": code, "reason": reason}


def check(raw: Any, grounding: dict) -> tuple[list[dict], list[dict]]:
    """`(통과 [{feature, label, why}], 탈락 [{code, reason}])`."""
    items = raw.get("tips") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return [], [_rej("shape", "답에 도구 목록이 없어요")]
    allowed_ids = {t["id"] for t in grounding["tools"]}
    allowed_nums = numbers_of(grounding["state"])
    ok: list[dict] = []
    bad: list[dict] = []
    for it in items:
        if not isinstance(it, dict) or set(it) != {"feature", "why"} or not isinstance(it.get("why"), str) or not it["why"].strip():
            bad.append(_rej("shape", "도구 안내의 형식이 맞지 않아요"))
            continue
        f, why = it["feature"], it["why"].strip()
        if f not in allowed_ids:
            bad.append(_rej("not_applicable", "지금 쓸 수 있는 도구가 아니에요"))
        elif any(x["feature"] == f for x in ok):
            bad.append(_rej("duplicate", "같은 도구를 두 번 권했어요"))
        elif len(ok) >= MAX_TIPS:
            bad.append(_rej("limit", f"{MAX_TIPS}개를 넘어요"))
        elif len(why) > MAX_WHY:
            bad.append(_rej("too_long", f"이유가 {MAX_WHY}자를 넘어요"))
        elif (word := next((w for w in (*BANNED, *JUDGEMENT) if w in why), None)):
            bad.append(_rej("banned", f"쓰지 않는 표현 ‘{word}’이 들어 있어요"))
        elif extra := numbers_of(why) - allowed_nums:
            bad.append(_rej("numbers", f"상태에 없는 숫자 {', '.join(sorted(extra))} 를 썼어요"))
        else:
            ok.append({"feature": f, "label": FEATURES[f]["label"], "why": why})
    return ok, bad
