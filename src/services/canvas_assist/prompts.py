"""시스템 글 · 사용자 글 · 출력 스키마 — 바꾸면 `PROMPT_VERSION` 을 올린다(캐시 열쇠에 들어간다)."""
from __future__ import annotations

import json

PROMPT_VERSION = "ai1-suggest-1"

SYSTEM = """너는 포트폴리오 설계 캔버스의 도우미다. 사용자가 지금 그래프에 다음으로 붙일 만한 노드를 고른다.

규칙:
- 추천은 1~3개. 노드 종류는 근거의 카탈로그(catalog)에 있는 것만 쓴다.
- 추천마다 새 노드(@new)와 지금 그래프의 노드를 잇는 선(attach)을 함께 낸다. 선의 한쪽 끝은 반드시 @new, 다른 쪽은 그래프에 있는 노드 id 다.
  포트 이름과 타입은 카탈로그 그대로 쓰고, 받는 쪽 입력에 이미 선이 있으면 그 자리에 잇지 않는다. 그래프가 비어 있을 때만 attach 를 비운다.
- 설정값(파라미터)은 추천하지 않는다. 노드 종류와 잇는 선만 낸다.
- 이유(reason)는 한국어 한 문장으로, 붙이면 무엇을 잴 수 있게 되는지 말한다. 숫자는 근거에 있는 숫자만 쓴다.
- 투자 판단이나 성과 약속을 하지 않는다. "검증됨", "입증됨", "견고함", "투자 우위", "더 나은 전략", "통과해요", "좋아져요" 같은 말을 쓰지 않는다.
- 근거의 procedure.next 와 procedure.by_gate 는 규칙이 이미 낸 추천이다. 같은 것을 내도 되지만, 근거가 있으면 다른 빈자리를 고른다.
- 답은 주어진 JSON 스키마대로만 낸다."""


def user_prompt(grounding: dict) -> str:
    return ("아래는 지금 캔버스의 근거 묶음(JSON)이다. 이것만 보고 다음에 붙일 노드를 추천해.\n\n"
            + json.dumps(grounding, ensure_ascii=False, sort_keys=True))


def output_schema(kinds: dict[str, dict]) -> dict:
    """★설정값 칸이 없다★(스펙 검사 ⑥) · 모든 객체가 닫혀 있다. 개수 한도(3)는 구조화 출력이 받지 않는 제약이라 서버 검사가 건다."""
    edge = {"type": "object", "additionalProperties": False,
            "required": ["source", "source_port", "target", "target_port"],
            "properties": {k: {"type": "string"} for k in ("source", "source_port", "target", "target_port")}}
    item = {"type": "object", "additionalProperties": False, "required": ["kind", "attach", "reason"],
            "properties": {"kind": {"type": "string", "enum": sorted(kinds)},
                           "attach": {"type": "array", "items": edge},
                           "reason": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": ["suggestions"],
            "properties": {"suggestions": {"type": "array", "items": item}}}


# ── AI2 풀어 쓰기 ─────────────────────────────────────────────────────────────

NARRATE_VERSION = "ai2-narrate-1"

NARRATE_SYSTEM = """너는 포트폴리오 설계 캔버스의 계산 결과를 사람이 읽기 쉬운 글로 풀어 쓴다.

규칙:
- 근거는 주어진 노드 설명(nodes)뿐이다. 거기 없는 사실·원인·전망을 더하지 않는다.
- 흐름 순서대로 해요체 2~5문단으로 쓴다. 문단마다 그 문단이 기댄 노드 id 를 node_ids 에 하나 이상 단다.
- 숫자는 그 문단이 댄 노드의 설명에 있는 숫자만 쓴다. 단계 번호는 쓰지 않는다(화면이 번호를 보여 준다).
- '몰라요'·'가정'으로 적힌 것은 숨기지 않고 그대로 말한다. 재지 않은 것(unmeasured)을 잰 것처럼 말하지 않는다.
- practice 가 true 면 연습용 합성 데이터로 계산한 결과라는 점을 글에서도 말한다.
- 투자 판단이나 성과 약속을 하지 않는다. "검증됨", "입증됨", "견고함", "투자 우위", "더 나은 전략", "통과해요", "좋아져요" 같은 말을 쓰지 않는다.
- 답은 주어진 JSON 스키마대로만 낸다."""


def narrate_user(grounding: dict) -> str:
    return ("아래는 계산을 마친 노드들의 설명(JSON, 흐름 순서)이다. 이것만 근거로 풀어 써.\n\n"
            + json.dumps(grounding, ensure_ascii=False, sort_keys=True))


def narrate_schema(node_ids: list[str]) -> dict:
    """문단마다 근거 노드 — 근거로 댈 수 있는 것은 확인된 노드뿐(enum). 문단 수 한도(5)는 서버 검사가 건다."""
    para = {"type": "object", "additionalProperties": False, "required": ["text", "node_ids"],
            "properties": {"text": {"type": "string"},
                           "node_ids": {"type": "array", "items": {"type": "string", "enum": list(node_ids)}}}}
    return {"type": "object", "additionalProperties": False, "required": ["paragraphs"],
            "properties": {"paragraphs": {"type": "array", "items": para}}}
