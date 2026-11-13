"""과거 시점(as_of) 스크리닝에서 쓸 수 있는 조건·정렬 항목 — ★그 시점 값이 있는 것만★ (2026-11-13 · 감사 §11~§12).

`ValuationScreener.run(as_of_date=…)` 은 종목마다 평가(그 시점 종가 + 그 시점 공시 재무)한 뒤 세 저장소의 팩터를 ★붙인다★ —
붙이는 것은 오늘 값이다(저장소에 기준일 개념이 없다). 재 보니 조건 필드 대부분이 그 붙이는 팩터였다. 그 필드에 건 조건·정렬은
미래 정보로 과거 유니버스를 고르고, 그 결과가 생존편향 보정 백테스트의 후보 풀로 들어간다.

사용자 결정(2026-11-13): ★막는다★ — 시점 값이 없는 항목을 쓴 과거 시점 요청은 계산하지 않고, 그 항목을 짚어 사유를 낸다
(조용히 오늘 값으로 거르지 않는다 — CLAUDE.md §4). 판정은 이 파일 하나이고 `ValuationScreener.run` 이 부른다 —
`/screener/run-pit` · 백테스트의 시점 유니버스 · 캔버스 스크리닝 노드가 모두 거기를 지난다.

★'시점 값이 있다'의 뜻과 한계★ — 그 시점에 알 수 있던 값으로 ★계산하는 경로★가 있다는 뜻이다. 값이 늘 있다는 뜻이 아니다
(공시를 못 읽으면 미상 · 공시가 주지 않는 칸은 미상). 정정공시(빈티지) · 분할 전후 주식 수의 정합은 미검증이다.
"""
from __future__ import annotations

from src.engine.pit_store import PIT_FIN_KEYS

#: 평가 때 정해지는 값 — 그 시점 종가 × 그 시점에 공시됐을 사업연도의 재무(`engine.evaluate(…, bsns_year=…)`). 붙이기가 건드리지 않는다.
PIT_VALUATION_FIELDS = ("intrinsic_value", "gap_pct", "composite_score", "gap_score", "roe_score", "stability_score")

#: 과거 시점에 조건·정렬로 쓸 수 있는 항목 — 재무 여덟 칸(그 시점 공시) + 가치평가.
#: `tests/test_pit_asof_block.py` 가 이 집합을 동작에 묶는다(붙이기가 이 항목을 바꾸면 시험이 죽는다).
PIT_CAPABLE_FIELDS = frozenset(PIT_FIN_KEYS) | frozenset(PIT_VALUATION_FIELDS)

#: 과거 시점에 쓸 수 있는 조건 종류 — 항목에 실린 값만 읽는 것. 그 밖의 종류는 오늘의 데이터로 문맥을 만든다(기술적 지표·이벤트·추정치 등).
PIT_CAPABLE_KINDS = ("field", "formula", "peer")

#: 조건 종류의 화면 이름(개발자 낱말을 그대로 싣지 않는다 — 용어집 §6). 모르는 종류는 받은 이름 그대로.
_KIND_LABEL = {"technical": "기술적 지표", "event": "이벤트", "estimate": "실적 추정치", "z_score": "Z-Score",
               "behavioral": "수급 행태", "graph": "관계 그래프", "sentiment": "센티먼트", "vector_sim": "유사 종목"}

#: 과거 시점에는 유동성 게이트를 적용하지 않는다 — 응답·화면에 그대로 실리는 문장.
ASOF_LIQUIDITY_NOTE = "유동성 문턱은 오늘의 거래대금·거래 상태로 판정하므로 과거 시점에는 적용하지 않았습니다."


def _named(field: str) -> str:
    """‘ROE’(roe) — 이름표와 id 를 함께(이름이 같은 항목이 있다: ROE 는 `roe`·`roe_pct` 둘이다)."""
    from src.engine.filter_ast import FIELD_BY_ID
    meta = FIELD_BY_ID.get(field)
    return f"‘{meta.label}’({field})" if meta else f"‘{field}’"


def _conditions(group):
    yield from getattr(group, "conditions", None) or []
    for g in getattr(group, "groups", None) or []:
        yield from _conditions(g)


def pit_violations(group, sort_by: str | None, sort_by_secondary: str | None) -> list[str]:
    """과거 시점에 쓸 수 없는 것의 목록(화면 문장 조각) — 비어 있으면 통과. 조건 묶음은 중첩까지 훑는다."""
    out: list[str] = []

    def add(text: str) -> None:
        if text not in out:
            out.append(text)

    for c in _conditions(group) if group is not None else ():
        kind = getattr(c, "kind", "field") or "field"
        if kind not in PIT_CAPABLE_KINDS:
            add(f"조건 종류 ‘{_KIND_LABEL.get(kind, kind)}’")
            continue
        if kind == "formula":
            from src.engine.formula_parser import extract_fields
            for f in sorted(extract_fields(c.formula or "")):
                if f not in PIT_CAPABLE_FIELDS:
                    add(f"수식 속 {_named(f)}")
            continue
        if c.field not in PIT_CAPABLE_FIELDS:
            add(f"조건 {_named(c.field)}")
    for key in (sort_by, sort_by_secondary):
        if key and key not in PIT_CAPABLE_FIELDS:
            add(f"정렬 기준 {_named(key)}")
    return out


class PitFieldNotAvailable(ValueError):
    """과거 시점 요청이 그 시점 값이 없는 항목을 썼다 — 계산하지 않는다. 문장은 화면에 그대로 실린다."""

    def __init__(self, violations: list[str]):
        self.violations = list(violations)
        super().__init__(
            "과거 시점 선별에는 그 시점 값이 있는 항목만 쓸 수 있습니다 — 현재 값으로만 계산되는 항목: "
            + ", ".join(self.violations)
            + ". 쓸 수 있는 항목: 재무 8개(ROE(roe_pct)·ROA·PER·PBR·부채비율·배당수익률·잉여현금흐름·시가총액)와 "
              "가치평가(종합 점수·적정가·괴리율·세부 점수).")
