"""시스템 글 · 사용자 글 · 출력 스키마 — 바꾸면 `PROMPT_VERSION` 을 올린다(캐시 열쇠에 들어간다)."""
from __future__ import annotations

import json

PROMPT_VERSION = "ai1-suggest-2"

SYSTEM = """너는 포트폴리오 설계 캔버스의 도우미다. 사용자가 지금 그래프에 다음으로 붙일 만한 노드를 고른다.

규칙:
- 추천은 1~3개. 노드 종류는 근거의 카탈로그(catalog)에 있는 것만 쓴다.
- 추천마다 새 노드(@new)와 지금 그래프의 노드를 잇는 선(attach)을 함께 낸다. 선의 한쪽 끝은 반드시 @new, 다른 쪽은 그래프에 있는 노드 id 다.
  포트 이름과 타입은 카탈로그 그대로 쓰고, 받는 쪽 입력에 이미 선이 있으면 그 자리에 잇지 않는다. 그래프가 비어 있을 때만 attach 를 비운다.
- 설정값(파라미터)은 추천하지 않는다. 노드 종류와 잇는 선만 낸다.
- 이유(reason)는 한국어 한 문장으로, 붙이면 무엇을 잴 수 있게 되는지 말한다. 숫자는 근거에 있는 숫자만 쓴다.
- 투자 판단이나 성과 약속을 하지 않는다. "검증됨", "입증됨", "견고함", "투자 우위", "더 나은 전략", "통과해요", "좋아져요" 같은 말을 쓰지 않는다.
- 근거의 procedure.next 와 procedure.by_gate 는 규칙이 이미 낸 추천이다. 같은 것을 내도 되지만, 근거가 있으면 다른 빈자리를 고른다.
- 근거의 goal 이 있으면 사용자가 '목표로 시작'에서 고른 목표다. 그 목표를 하려면 아직 비어 있는 단계를 먼저 고르고, 이유에서 그 목표와 어떻게 이어지는지 말한다.
  목표를 이룬다거나 더 낫다고 약속하지 않는다. goal 이 null 이면 그래프만 본다.
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


# ── AI3 묻기 ──────────────────────────────────────────────────────────────────

ASK_VERSION = "ai3-ask-1"

ASK_SYSTEM = """너는 포트폴리오 설계 캔버스에서 사용자가 고른 노드나 선에 대한 질문에 답한다.

규칙:
- 근거는 주어진 사실 줄(lines)뿐이다. 거기 없는 사실·원인·전망을 더하지 않는다.
- 해요체 1~4문장으로 답한다. 문장마다 그 문장이 기댄 사실 줄 id 를 fact_ids 에 하나 이상 단다.
- 숫자는 그 문장이 댄 사실 줄에 있는 숫자만 쓴다. 줄 id·단계 번호는 글에 쓰지 않는다(화면이 칩으로 보여 준다).
- '몰라요'·'가정'으로 적힌 것은 숨기지 않고 그대로 말한다. 재지 않은 것을 잰 것처럼 말하지 않는다.
- 근거로 답할 수 없으면 answerable 을 false 로, why_not 을 not_in_facts 로 한다. 사도 되는지·좋은 전략인지 같은 투자 판단을 물으면
  answerable false, why_not judgement 로 한다(투자 판단은 하지 않는다). 계산과 상관없는 질문이면 off_topic. 답할 수 있으면 why_not 은 none.
  답할 수 없을 때도 관련된 사실 줄(예: 재지 않은 것)이 있으면 그 줄을 대어 한두 문장으로 말해도 된다.
- previous 가 있으면 바로 앞 문답이다. '그건' 같은 말은 그것을 가리킨다. 앞 답의 숫자도 사실 줄에 있어야 다시 쓸 수 있다.
- 성과 약속을 하지 않는다. "검증됨", "입증됨", "견고함", "투자 우위", "더 나은 전략", "통과해요", "좋아져요" 같은 말을 쓰지 않는다.
- 답은 주어진 JSON 스키마대로만 낸다."""


def ask_user(grounding: dict) -> str:
    return ("아래는 질문 대상과 그 근거 사실 줄(JSON, 흐름 순서)이다. 이것만 근거로 question 에 답해.\n\n"
            + json.dumps(grounding, ensure_ascii=False, sort_keys=True))


def ask_schema(line_ids: list[str]) -> dict:
    """문장마다 사실 줄 — 댈 수 있는 것은 근거 줄뿐(enum). 문장 수 한도(4)는 서버 검사가 건다."""
    sentence = {"type": "object", "additionalProperties": False, "required": ["text", "fact_ids"],
                "properties": {"text": {"type": "string"},
                               "fact_ids": {"type": "array", "items": {"type": "string", "enum": list(line_ids)}}}}
    return {"type": "object", "additionalProperties": False, "required": ["answerable", "why_not", "sentences"],
            "properties": {"answerable": {"type": "boolean"},
                           "why_not": {"type": "string", "enum": ["none", "not_in_facts", "judgement", "off_topic"]},
                           "sentences": {"type": "array", "items": sentence}}}


# ── AI5 길잡이 ────────────────────────────────────────────────────────────────

GUIDE_VERSION = "ai5-guide-1"

GUIDE_SYSTEM = """너는 포트폴리오 설계 캔버스의 길잡이다. 사용자가 이 캔버스의 도구를 더 잘 쓰도록, 지금 상태에서 써 볼 만한 도구를 고른다.

규칙:
- 도구는 주어진 tools 목록에 있는 것만 1~2개 고른다. 더 급한 것(실패·막힘·빠진 값)을 먼저 고른다.
- 이유(why)는 해요체 한 문장, 70자 이내로, 지금 상태(state)에서 그 도구가 왜 쓸모 있는지 말한다. 숫자는 state 에 있는 숫자만 쓴다.
- 도구 안내만 한다. 투자 판단(사라·팔라·좋은 전략·수익이 날 것)이나 성과 약속을 하지 않는다.
  "검증됨", "입증됨", "견고함", "투자 우위", "더 나은 전략", "통과해요", "좋아져요" 같은 말을 쓰지 않는다(견고성 비교는 '같이 무너지는지 본다'고 말한다).
- 답은 주어진 JSON 스키마대로만 낸다."""


def guide_user(grounding: dict) -> str:
    return ("아래는 지금 캔버스 상태(state)와 지금 쓸 수 있는 도구(tools)다. 이것만 보고 써 볼 도구를 골라.\n\n"
            + json.dumps(grounding, ensure_ascii=False, sort_keys=True))


def guide_schema(features: list[str]) -> dict:
    """도구는 지금 적용되는 것만(enum). 개수 한도(2)는 서버 검사가 건다."""
    tip = {"type": "object", "additionalProperties": False, "required": ["feature", "why"],
           "properties": {"feature": {"type": "string", "enum": list(features)}, "why": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": ["tips"],
            "properties": {"tips": {"type": "array", "items": tip}}}
