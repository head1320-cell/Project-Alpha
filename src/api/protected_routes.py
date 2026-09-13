"""보호 라우트 ★단일 레지스트리★ — 무엇이 잠겼고 무엇이 왜 열렸는가 (AC4)
==============================================================================
설계: `docs/plans/2026-09-12-ra-product-roadmap.md` P-1
관용구: `src/engine/filter_ast.py::FIELD_BY_ID` 와 같다 — 흩어진 진실 대신 **한 곳**.

## 왜 목록을 따로 두는가

`Depends(...)` 를 라우트마다 붙이면 잠긴 것은 잠기지만 ★빠뜨린 것을 아무도 모른다★.
새 주문 라우트가 조용히 열려도 테스트가 초록이면 통과한다. 그래서 목록을 **코드로**
두고, 실제 라우트 테이블과 **양방향으로** 대조한다:

  ① 레지스트리에 적힌 것이 실제로 잠겨 있나 (빠뜨림 검출)
  ② 잠겨 있는 것이 레지스트리에 적혀 있나 (몰래 추가 검출)
  ③ 돈·PII 키워드에 걸리는데 **양쪽 어디에도 없는** 것이 있나 (새 라우트 검출)

③ 때문에 `OPEN_WITH_REASON` 이 필요하다 — "열어 둔다" 는 판단도 **기록된 판단**
이어야 한다. 사유 없는 면제는 면제가 아니라 누락이다(Z 의 allowlist 관용구).

## ★범위★ — 돈·PII 만

사용자가 정한 범위다. 나머지 300여 개 연구·조회 라우트는 열려 있고, 그것은
의도이지 누락이 아니다. ★이 파일은 "저장소가 안전하다" 고 주장하지 않는다★ —
"이 목록이 잠겼다" 고만 말한다.
"""
from __future__ import annotations

#: 실행 모드·주문·킬스위치처럼 **돈을 움직이는** 것 — admin 역할.
REQUIRE_ADMIN = "admin"
#: 잔고·감사·체결처럼 **남의 것을 보면 안 되는** 것 — 로그인만.
REQUIRE_LOGIN = "login"
#: 경로에 `username` 이 있는 것 — 본인이거나 admin.
REQUIRE_SELF_OR_ADMIN = "self_or_admin"

REQUIREMENTS = (REQUIRE_ADMIN, REQUIRE_LOGIN, REQUIRE_SELF_OR_ADMIN)

#: (METHOD, 경로) → (요구 수준, ★왜★)
PROTECTED: dict[tuple[str, str], tuple[str, str]] = {
    # ── 돈을 움직인다 ──────────────────────────────────────────────────────
    ("POST", "/api/v1/live/mode"):
        (REQUIRE_ADMIN, "실행 모드 전환 — LIVE 진입을 포함한다"),
    ("POST", "/api/v1/live/orders/submit"):
        (REQUIRE_ADMIN, "실주문 제출"),
    ("DELETE", "/api/v1/live/orders/{client_order_id}"):
        (REQUIRE_ADMIN, "주문 취소"),
    ("POST", "/api/v1/live/orders/cleanup-eod"):
        (REQUIRE_ADMIN, "장 마감 미체결 정리 — 미체결 주문을 실제로 취소한다"),
    ("POST", "/api/v1/live/kill-switch/trigger"):
        (REQUIRE_ADMIN, "비상 정지 — 청산 모드에 따라 포지션을 건드린다"),
    ("POST", "/api/v1/live/kill-switch/resolve"):
        (REQUIRE_ADMIN, "★비상 정지 해제★ — 막아 둔 것을 다시 연다"),
    ("POST", "/api/v1/live/init-schema"):
        (REQUIRE_ADMIN, "live_* 테이블 DDL"),
    ("POST", "/api/v1/trading/kill-switch"):
        (REQUIRE_ADMIN, "킬스위치 on/off"),
    ("POST", "/api/v1/trading/execute"):
        (REQUIRE_ADMIN, "매매 실행 — safety 파라미터로 dry_run 해제가 가능하다"),
    ("POST", "/api/v1/trading/screen-to-trade"):
        (REQUIRE_ADMIN, "스크리닝 통과 종목을 그대로 발주한다"),
    ("POST", "/api/v1/orders/execute"):
        (REQUIRE_ADMIN, "단일 주문 — 현재 dry_run 고정이나 주문 경로다"),
    ("POST", "/api/v1/orders/batch"):
        (REQUIRE_ADMIN, "일괄 주문 — 현재 dry_run 고정이나 주문 경로다"),
    ("POST", "/toggle-auto-trading"):
        (REQUIRE_ADMIN, "자동매매 토글"),

    # ── 남의 것을 보면 안 된다 ────────────────────────────────────────────
    ("GET", "/api/v1/live/balance"):
        (REQUIRE_LOGIN, "실계좌 잔고"),
    ("GET", "/api/v1/live/audit"):
        (REQUIRE_LOGIN, "감사 로그 — 누가 무엇을 했는지"),
    ("GET", "/api/v1/live/audit/summary"):
        (REQUIRE_LOGIN, "감사 요약"),
    ("GET", "/api/v1/live/daily-pnl"):
        (REQUIRE_LOGIN, "일별 손익"),
    ("GET", "/api/v1/live/orders"):
        (REQUIRE_LOGIN, "주문 이력 — 무엇을 거래 중인지 드러난다"),
    ("GET", "/api/v1/live/orders/{client_order_id}"):
        (REQUIRE_LOGIN, "주문 상세"),
    ("GET", "/api/v1/live/orders/active"):
        (REQUIRE_LOGIN, "미체결 주문 목록"),
    ("GET", "/api/v1/live/orders/state-distribution"):
        (REQUIRE_LOGIN, "주문 상태 분포 — 활동량이 드러난다"),
    ("GET", "/api/v1/live/kill-switch/events"):
        (REQUIRE_LOGIN, "킬스위치 이력 — 이벤트에 당시 자기자본이 실린다"),
    ("GET", "/api/v1/account/holdings"):
        (REQUIRE_LOGIN, "보유 종목"),
    ("GET", "/api/v1/account/balance"):
        (REQUIRE_LOGIN, "예수금·평가금액"),

    # ── 경로에 남의 이름이 들어간다 ───────────────────────────────────────
    ("GET", "/trade-history/{username}"):
        (REQUIRE_SELF_OR_ADMIN, "★타인 PII★ — 로드맵 완료 판정의 403 이 이 라우트다"),
}

#: 돈·PII 키워드에 걸리지만 **의도적으로 열어 둔** 라우트 → ★왜 열었는지★.
#: 사유 없는 면제는 금지 — 여기 비어 있는 값이 있으면 트립와이어가 실패한다.
OPEN_WITH_REASON: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/live/mode"):
        "현재 실행 모드 표시 — 관리 화면이 로그인 전에 상태를 읽어야 하고, 값이 돈을 옮기지 않는다",
    ("GET", "/api/v1/live/kill-switch/status"):
        "정지 상태 표시 — 같은 이유. 막혀 있다는 사실은 숨길수록 위험하다",
    ("GET", "/api/v1/trading/status"):
        "프로세스 로컬 설정값(auto_mode·var_limit) 표시 — 계좌 자료가 아니다",
    ("GET", "/api/v1/trading/mode"):
        "mock/paper/real 라벨 표시 — 계좌 자료가 아니다",
    ("GET", "/trading-status"):
        "위와 같은 설정값의 레거시 경로",
    ("POST", "/api/v1/portfolio/rebalance"):
        "요청 본문의 티커로 도는 리밸런싱 **시뮬레이션** — 계좌를 건드리지 않는다",
    ("POST", "/api/v1/allocation/rebalance-decision"):
        "배분 판단 계산 — 주문을 내지 않는다(AA2)",
    ("POST", "/api/v1/diagnostics/holdings"):
        "요청 본문의 보유로 도는 진단 — 저장된 계좌를 읽지 않는다(AA5)",
    ("POST", "/api/v1/explain/daily"):
        "요청 본문의 보유로 도는 설명 — 저장된 계좌를 읽지 않는다(AB4)",
    ("POST", "/api/v1/strategies/scorecard"):
        "알파 등록부·건강도·증거를 읽는 연구 표면(AE4) — 계좌·주문을 건드리지 않는다",
    # ── `/strategies/` 마커를 넓히며 사정거리에 들어온 기존 연구 표면들(AE4) ──
    # ★전수 검사가 분류되지 않은 라우트 열 개를 찾아냈다★ — 실측으로 확인한 결과
    # `strategy_routes.py` 는 `TradingEngine`·`OrderExecutor`·`place_order` 를
    # 한 번도 부르지 않는다. 시그널은 `daily_prices` 에서 **계산**될 뿐 집행되지 않는다.
    ("GET", "/api/v1/strategies/list"):
        "등록된 전략 목록 — 연구 자료이고 계좌·주문을 건드리지 않는다",
    ("GET", "/api/v1/strategies/templates"):
        "전략 템플릿 목록 — 체크인된 정의를 읽을 뿐이다",
    ("POST", "/api/v1/strategies/build"):
        "전략 정의 조립 — 저장·집행하지 않는다",
    ("POST", "/api/v1/strategies/backtest"):
        "과거 데이터 위의 시뮬레이션 — 주문 경로가 아니다",
    ("POST", "/api/v1/strategies/import-and-backtest"):
        "요청 본문의 정의를 백테스트한다 — 주문 경로가 아니다",
    ("POST", "/api/v1/strategies/optimize"):
        "파라미터 탐색 — 주문 경로가 아니다",
    ("POST", "/api/v1/strategies/signal"):
        "단일 종목 시그널 **계산** — 집행하지 않는다(실측: 주문 호출 0건)",
    ("POST", "/api/v1/strategies/batch-signal"):
        "일괄 시그널 **계산** — 집행하지 않는다(실측: 주문 호출 0건)",
    ("POST", "/api/v1/strategies/dsl/validate"):
        "전략 DSL 문법 검사 — 계산조차 하지 않는다",
    ("POST", "/api/v1/strategies/dsl/backtest"):
        "DSL 정의를 백테스트한다 — 주문 경로가 아니다",

    ("POST", "/api/v1/multibacktest/init-schema"):
        "백테스트 결과 테이블 DDL — 연구 인프라이고 계좌·주문을 건드리지 않는다",
    ("POST", "/api/v1/accounts/diagnose"):
        "요청 본문의 보유·계좌유형·한도로 도는 판정(AD4) — 저장된 계좌를 읽지 않는다",
    ("POST", "/api/v1/report/portfolio"):
        "요청 본문으로 도는 표면 넷의 조립(AD5) — 저장된 계좌를 읽지 않고 새 수치도 만들지 않는다",
}

#: 이 조각이 경로에 들어 있으면 "돈·PII 후보" 로 본다(트립와이어 ③).
#: ★넓게 잡는다★ — 거짓 양성은 사유 한 줄로 면제하면 되지만, 거짓 음성은 열린 문이다.
MONEY_PATH_MARKERS = (
    "order",
    "kill-switch",
    "trade-history",
    "auto-trading",
    "trading-status",
    "/api/v1/trading/",
    "/live/mode",
    "/live/balance",
    "/live/audit",
    "/live/daily-pnl",
    "init-schema",
    "account/holdings",
    "account/balance",
    "rebalance",
    "holdings",
    # AD4·AD5 로 계좌·리포트 표면이 생겼다 — 마커가 닿지 않으면 전수 검사가
    # 그 영역을 **보지 못한다**. 넓게 잡고 면제는 사유로 적는다.
    "/accounts/",
    "/report/",
    # AE4 로 전략 평가 표면이 생겼다 — 유통(P4)과 인접한 영역이라 전수 검사의
    # 사정거리 안에 둔다.
    "/strategies/",
)


def looks_like_money_route(path: str) -> bool:
    return any(marker in path for marker in MONEY_PATH_MARKERS)


def requirement_for(method: str, path: str) -> str | None:
    """레지스트리가 요구하는 수준. 적혀 있지 않으면 `None`."""
    entry = PROTECTED.get((method.upper(), path))
    return entry[0] if entry else None


def auth_requirement_of_route(route) -> str | None:
    """★라우트가 **실제로** 무엇을 요구하는가★ — 선언이 아니라 의존성 그래프에서 읽는다.

    레지스트리와 대조하려면 "적어 둔 것" 이 아니라 "붙어 있는 것" 을 봐야 한다.
    """
    from src.api.auth import require_admin, require_login, require_self_or_admin

    by_call = {
        require_admin: REQUIRE_ADMIN,
        require_login: REQUIRE_LOGIN,
        require_self_or_admin: REQUIRE_SELF_OR_ADMIN,
    }
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return None

    seen: list = []

    def _walk(d) -> None:
        for sub in getattr(d, "dependencies", []) or []:
            call = getattr(sub, "call", None)
            if call in by_call:
                seen.append(by_call[call])
            _walk(sub)

    _walk(dependant)
    if not seen:
        return None
    # 한 라우트에 둘 이상 붙으면 **가장 강한** 것을 그 라우트의 요구로 본다.
    for level in (REQUIRE_ADMIN, REQUIRE_SELF_OR_ADMIN, REQUIRE_LOGIN):
        if level in seen:
            return level
    return None
