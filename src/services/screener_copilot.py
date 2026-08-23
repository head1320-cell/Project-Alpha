"""
Screener Copilot — Screener V2 Milestone 2 (NL2AST)
==========================================================================
자연어 → FilterGroup AST 변환.

전략:
  · Phase 3 ClaudeClient 재사용 (캐시·서킷·재시도 무료 상속)
  · 시스템 프롬프트에 FIELD_CATALOG 화이트리스트 주입 → 유효 AST만 생성
  · 응답 JSON → parse_group → validate → 실패 시 1회 재시도 (에러 피드백)
  · API 키 없으면 규칙 기반 Mock fallback (키워드 매칭) → 데모 정상 동작

신뢰 경계 (LLM 환각 차단):
  · 생성된 AST는 반드시 validate() 통과해야 반환
  · 미통과 필드/연산자는 거부
  · 프론트는 미리보기 → 사용자 명시적 [적용] (human-in-the-loop)
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# System Prompt 구성 (FIELD_CATALOG 주입)
# ═══════════════════════════════════════════════════════════════════════════════

def build_copilot_system_prompt() -> str:
    from src.engine.filter_ast import FIELD_CATALOG

    field_lines = []
    for f in FIELD_CATALOG:
        direction = "높을수록 좋음" if f.higher_better else "낮을수록 좋음"
        field_lines.append(
            f'  - "{f.id}" ({f.label}, {f.unit}, {direction}, 범위 {f.typical_min}~{f.typical_max})'
        )
    fields_block = "\n".join(field_lines)

    return f"""당신은 한국 주식 스크리너의 자연어→필터 변환 엔진입니다.
사용자의 자연어 요청을 분석하여 JSON 필터 조건으로 변환합니다.

## 사용 가능한 필드 (이 목록의 id만 사용. 목록에 없는 필드는 절대 생성 금지)
{fields_block}

## 조건 유형 (kind)
1. "field" — 일반 필드 조건
   - 절대값: {{"kind":"field", "field":"per", "op":"lt", "value":15}}
   - 랭킹:   {{"kind":"field", "field":"roe_pct", "rank_mode":"top_pct", "rank_value":20}}
2. "peer" — 동종 그룹(섹터) 대비 비교
   - {{"kind":"peer", "field":"per", "peer_scope":"sector", "peer_stat":"mean", "op":"lt"}}
   - {{"kind":"peer", "field":"roe_pct", "peer_scope":"sector", "peer_stat":"rank_pct", "rank_value":10}}

## 연산자 (op): lt(미만) lte(이하) gt(초과) gte(이상) between(범위)
## 랭킹 (rank_mode): top_pct(상위%) bottom_pct(하위%) top_n(상위N개)
## peer_stat: mean(평균) median(중앙값) rank_pct(그룹내 상위%)

## 출력 형식 (반드시 이 JSON 구조만, 다른 텍스트 없이)
{{
  "logic": "AND",
  "conditions": [ ...조건들... ],
  "groups": [],
  "explanation": "한 줄 한국어 해석",
  "confidence": 0.0~1.0
}}

## 규칙
- 반드시 위 필드 id만 사용. 모르는 개념(예: PEG, EV/EBITDA)은 가장 가까운 필드로 근사하거나 생략.
- "저평가" → gap_pct 음수 또는 per 낮음. "고배당" → dividend_yield_pct 상위. "방어주" → 저부채+고배당.
- "우량주" → roe 높음 + 부채 낮음. "성장주" → roe 상위. "대형주" → market_cap_억 상위.
- 2~4개 조건이 적절. 과도하게 많이 만들지 말 것.
- JSON 외 텍스트 절대 출력 금지."""


def build_user_prompt(query: str, retry_error: str | None = None) -> str:
    base = f'다음 요청을 필터 JSON으로 변환하세요:\n"{query}"'
    if retry_error:
        base += f'\n\n이전 시도가 실패했습니다. 오류: {retry_error}\n반드시 사용 가능한 필드 id만 사용하여 다시 생성하세요.'
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# JSON 추출
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_json(text: str) -> dict | None:
    """Claude 응답에서 JSON 블록 추출."""
    # ```json ... ``` 블록 우선
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 첫 { ~ 마지막 }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Main: NL → AST
# ═══════════════════════════════════════════════════════════════════════════════

def nl_to_ast(query: str) -> dict:
    """
    자연어 → FilterGroup AST.

    Returns:
        {
          "ast": {logic, conditions, groups},   # 검증 통과한 AST
          "explanation": str,
          "confidence": float,
          "source": "claude" | "mock",
          "error": str | None,
        }
    """
    from src.engine.filter_ast import parse_group

    if not query or not query.strip():
        return {"ast": None, "explanation": "", "confidence": 0, "source": "none", "error": "빈 요청"}

    try:
        from src.services.narrative.claude_client import ClaudeClient, NarrativeRequest
        client = ClaudeClient.get_default()
    except Exception as e:
        logger.warning(f"ClaudeClient 로드 실패: {e}")
        client = None

    # ── Claude 경로 ──
    if client and client.is_configured:
        system = build_copilot_system_prompt()
        for attempt, err in [(1, None), (2, "필드 검증 실패")]:
            req = NarrativeRequest(
                system_prompt=system,
                user_prompt=build_user_prompt(query, err if attempt > 1 else None),
                max_tokens=800,
                temperature=0.2,
            )
            resp = client.invoke(req)
            parsed = _extract_json(resp.content)
            if not parsed:
                continue
            explanation = parsed.pop("explanation", "")
            confidence = parsed.pop("confidence", 0.7)
            try:
                ast = parse_group(parsed)
                verr = ast.validate()
                if verr:
                    if attempt == 1:
                        continue  # 재시도
                    # 2차도 실패 → mock fallback
                    break
                return {
                    "ast": parsed,
                    "explanation": explanation or "AI가 해석한 필터입니다.",
                    "confidence": confidence,
                    "source": "claude",
                    "error": None,
                }
            except Exception:
                continue

    # ── Mock fallback (규칙 기반) ──
    return _rule_based_fallback(query)


# ═══════════════════════════════════════════════════════════════════════════════
# Rule-based Fallback (API 키 없을 때)
# ═══════════════════════════════════════════════════════════════════════════════

# 키워드 → 조건 매핑
_KEYWORD_RULES = [
    (["고배당", "배당 높", "배당률 높", "배당주"],
     {"kind": "field", "field": "dividend_yield_pct", "rank_mode": "top_pct", "rank_value": 30}, "고배당"),
    (["저부채", "부채 적", "부채 낮", "재무 안정", "안정적"],
     {"kind": "field", "field": "debt_ratio_pct", "op": "lt", "value": 100}, "낮은 부채"),
    (["저평가", "싼", "저렴", "할인"],
     {"kind": "field", "field": "gap_pct", "op": "lt", "value": -10}, "저평가(괴리율 음수)"),
    (["저per", "per 낮", "저 per"],
     {"kind": "field", "field": "per", "op": "lt", "value": 12}, "낮은 PER"),
    (["저pbr", "pbr 낮", "자산주"],
     {"kind": "field", "field": "pbr", "op": "lt", "value": 1.5}, "낮은 PBR"),
    (["고roe", "roe 높", "수익성", "성장주", "고성장"],
     {"kind": "field", "field": "roe_pct", "rank_mode": "top_pct", "rank_value": 30}, "높은 ROE"),
    (["우량", "퀄리티", "안전"],
     {"kind": "field", "field": "composite_score", "op": "gte", "value": 60}, "종합점수 우량"),
    (["대형", "대형주", "시총 큰"],
     {"kind": "field", "field": "market_cap_억", "rank_mode": "top_pct", "rank_value": 30}, "대형주"),
    (["현금", "fcf", "현금흐름"],
     {"kind": "field", "field": "fcf_억", "op": "gt", "value": 0}, "현금흐름 흑자"),
    (["섹터 평균", "동종", "업계 평균", "peer"],
     {"kind": "peer", "field": "per", "peer_scope": "sector", "peer_stat": "mean", "op": "lt"}, "섹터 평균 대비 저PER"),
]

# 복합 키워드 (방어주 = 저부채 + 고배당)
_COMPOSITE_RULES = {
    "방어주": ["저부채", "고배당"],
    "방어": ["저부채", "고배당"],
}


def _rule_based_fallback(query: str) -> dict:
    q = query.lower().replace(" ", "")
    q_orig = query.lower()
    matched_conditions = []
    matched_labels = []
    seen_fields = set()

    # 복합 키워드 우선 처리
    expanded_keywords = []
    for comp, parts in _COMPOSITE_RULES.items():
        if comp in q_orig.replace(" ", ""):
            expanded_keywords.extend(parts)

    # 일반 규칙 매칭
    for keywords, cond, label in _KEYWORD_RULES:
        hit = any(kw.replace(" ", "") in q for kw in keywords)
        # 복합에서 확장된 키워드도 체크
        if not hit and any(ek in [k for k in keywords] for ek in expanded_keywords):
            hit = True
        if hit:
            fld = cond.get("field")
            if fld in seen_fields:
                continue
            matched_conditions.append(cond)
            matched_labels.append(label)
            seen_fields.add(fld)

    if not matched_conditions:
        # 기본: 종합점수 상위
        matched_conditions.append({"kind": "field", "field": "composite_score", "op": "gte", "value": 50})
        matched_labels.append("종합점수 50 이상")
        explanation = f'"{query}"를 명확히 해석하지 못해 기본 필터를 적용했습니다. 좌측에서 직접 조건을 추가하세요.'
        confidence = 0.3
    else:
        explanation = f"규칙 기반 해석: {' + '.join(matched_labels)}"
        confidence = 0.6

    return {
        "ast": {"logic": "AND", "conditions": matched_conditions, "groups": []},
        "explanation": explanation,
        "confidence": confidence,
        "source": "mock",
        "error": None,
    }


# 추천 예시 (UI용)
EXAMPLE_QUERIES = [
    "부채 적고 배당 높은 방어주",
    "저평가된 고ROE 성장주",
    "PER이 섹터 평균보다 낮은 우량주",
    "현금흐름 좋은 저PBR 자산주",
    "대형 고배당 안정주",
]
