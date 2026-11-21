"""LLM 경계 등록부 — LLM 의 답이 계산 · 결정 계층에 들지 않는다는 사실을 시험이 걸 수 있게 한 곳에 적는다 (G7 ① · 2026-11-19)

순수 표다(설정 · 파일 · 네트워크 0). ★제품 코드는 이 표를 읽지 않는다★ — `tests/test_llm_boundary.py` 가 src 의 import 그래프
(`tests/import_graph.py`)를 읽어 이 표와 대조한다. 표를 고치는 것은 경계를 바꾸는 일이라 사유를 함께 적는다.

규칙(제품 규칙 `docs/specs/2026-09-12-ra-product-rules.md` §3-2):
- 계산 · 결정 계층(`CORE_PACKAGES`)은 LLM 모듈을 직접 들이지 않는다 — 예외 0.
- 그 밖에서 LLM 을 직접 들이는 모듈은 `DIRECT_USERS` 에 사유와 함께 있다(새 모듈은 시험이 막는다).
- 계산 계층에서 LLM 모듈로 가는 import 길은 `CORE_EDGES` 를 끊으면 0 이다(새 길은 시험이 막는다).
- LLM 모듈과 LLM 을 직접 들이는 모듈은 `ORDER_MODULES` 를 직접 들이지 않는다.

★말하지 않는 것★: 모듈 단위 그래프의 사실이다. 'LLM 이 주문에 닿지 않는다'의 증명이 아니다(시세 클라이언트가 계좌 등록부를
들여 모듈 그래프에서는 LLM 쪽에서 계좌 실행기까지 길이 있다 — 2026-11-19 관측). 주문은 기존 가드가 지킨다.
"""
from __future__ import annotations

#: LLM 을 부르는 모듈(접두 — 점 경계). 이 이름이거나 그 아래 모듈을 들이면 LLM 을 들인 것으로 본다.
LLM_MODULES: tuple[str, ...] = (
    "anthropic",
    "openai",
    "src.services.narrative",
    "src.services.canvas_assist",
    "src.services.screener_copilot",
)

#: 계산 · 결정 계층 — 수집 · 출처 · 품질 · 피처 · 국면 · 배분 · 백테스트 · 리스크 · 주문 실행(CLAUDE.md §3 의 층).
CORE_PACKAGES: tuple[str, ...] = ("src.engine", "src.domain", "src.execution", "src.data")

#: 주문을 낼 수 있는 모듈 — LLM 쪽은 이들을 직접 들이지 않는다.
ORDER_MODULES: tuple[str, ...] = (
    "src.engine.trading_engine",
    "src.execution.order_executor",
    "src.execution.account_executors",
    "src.execution.rule_runner",
    "src.execution.risk_gateway",
    "src.kis_order_executor",
    "src.api.trading_routes",
)

#: 계산 계층 밖에서 LLM 모듈을 직접 들이는 모듈 → 사유(무엇에 쓰고 왜 계산 값에 들지 않는가).
DIRECT_USERS: dict[str, str] = {
    "src.api.canvas_assist_routes": (
        "캔버스 AI 보조의 문(추천 · 초안 · 묻기 · 서술 · 길잡이) — 답은 유령 노드와 글이고 사용자가 받아들여야 "
        "그래프에 든다 · 서버 검사를 통과한 사실만 풀어 쓴다"),
    "src.api.macro_routes": (
        "전략 AI 심층분석 문(`/macro/strategy/{sid}/ai`) — 프로파일 · 국면 · 보유 맥락을 글로 풀어 쓴다 · "
        "키가 없으면 빈 글 · 추천 순위와 배분은 엔진이 따로 계산한다"),
    "src.api.narrative_routes": (
        "서술 문(종목 · 포트폴리오 · 매크로 · 운영 · What-If · 일일 요약) — 이미 계산된 결과를 글로 풀어 쓴다"),
    "src.api.pb_client_routes": (
        "PB 한 장 묻기(유통 관문 뒤 · `canvas_assist.service.ask_sheet`) — 한 장에 실린 사실을 글로 답한다"),
    "src.api.screener_routes": (
        "스크리너 코파일럿 문 셋(자연어 → 필터 AST) — 함수 안 늦은 import · validate 를 통과한 AST 만 돌려주고 "
        "사용자가 적용해야 스크리닝에 든다"),
    "src.services.pb_links": (
        "고객 공유 링크의 묻기(유통 관문 뒤 · 시간당 한도기) — 한 장의 사실을 글로 답한다"),
    "src.services.pb_sheets": (
        "LLM 을 부르지 않는다 — `canvas_assist.narrate` 의 순수 함수 `flow_order`(노드 차례)와 안내 문장 `NOTICE` 만 "
        "빌린다(그 모듈은 클라이언트를 들이지 않는다 — 시험이 새 프로세스에서 확인한다)"),
}

#: 계산 계층에서 LLM 모듈로 가는 import 길을 끊는 등록 간선 (출발, 도착) → 사유. 동작 시험이 사유를 건다.
CORE_EDGES: dict[tuple[str, str], str] = {
    ("src.engine.strategy_registry", "src.api.screener_routes"): (
        "전략 등록이 재실행 재료(요청 모형 `ScreenToBacktestRequest` · `_backtest_kwargs` · `_effective_strategy` · "
        "`_factor_weights`)를 늦은 import 로 빌린다 — 그 모듈의 코파일럿 import 는 코파일럿 문 함수 안에만 있고 "
        "빌리는 이름들은 코파일럿을 부르지 않는다(시험: 새 프로세스에서 불러와도 LLM 모듈 0). "
        "엔진 → 문 역방향 의존은 스크리너 영역이라 고치지 않는다(3-레이어 · 리팩터링 대상 아님)"),
}
