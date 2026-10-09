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
    # ── BV0a — 감사가 찾은, 인증 없이 열려 있던 실거래 확장 경로(stage13_extensions) ──
    ("POST", "/api/v1/live/reconcile/sync"):
        (REQUIRE_ADMIN, "브로커와 즉시 대조 — 로컬 계좌 상태를 덮고, 차이가 크면 킬스위치를 당겨 "
                        "미체결 주문을 실제로 취소한다"),
    ("POST", "/api/v1/live/reconcile/periodic/start"):
        (REQUIRE_ADMIN, "자동 대조 켜기 — 위 동작을 300초마다 백그라운드로 돌린다"),
    ("POST", "/api/v1/live/reconcile/periodic/stop"):
        (REQUIRE_ADMIN, "자동 대조 끄기 — 안전 감시 하나를 멈춘다"),
    ("POST", "/api/v1/live/notifier/test"):
        (REQUIRE_ADMIN, "알림 발송 — CRITICAL 을 포함해 운영자에게 가는 경보를 보낸다"),

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
    ("GET", "/api/v1/live/kill-switch/readiness"):
        (REQUIRE_LOGIN, "자동 트리거 무장 여부(AF4) — 계좌 상태에서 파생된다"),
    ("GET", "/api/v1/live/kill-switch/kis-codes"):
        (REQUIRE_LOGIN, "본 KIS 업무 코드와 뜻 미상 목록(AS4) — 감사 로그의 "
                        "실패 이력에서 파생되고 표본 `msg1` 원문이 실린다"),
    ("GET", "/api/v1/account/holdings"):
        (REQUIRE_LOGIN, "보유 종목"),
    ("GET", "/api/v1/account/balance"):
        (REQUIRE_LOGIN, "예수금·평가금액"),
    # ── BV0a — 감사가 찾은 열린 계좌 조회(예전 면제 사유는 다른 경로를 설명했다) ──
    ("GET", "/api/v1/trading/status"):
        (REQUIRE_LOGIN, "브로커의 예수금·평가금액·보유 종목 전체(TradingEngine.get_account_status)"),
    ("GET", "/api/v1/live/reconcile/status"):
        (REQUIRE_LOGIN, "마지막 대조 결과 — 현금·보유 차이가 실린다"),
    ("GET", "/api/v1/live/reconcile/history"):
        (REQUIRE_LOGIN, "대조 이력 — 현금·보유 차이가 실린다"),
    ("GET", "/api/v1/live/notifier/stats"):
        (REQUIRE_LOGIN, "알림 발송 통계 — 경보 횟수로 운영 상황이 드러나고, 부르면 알림 작업자가 켜진다"),
    ("GET", "/api/v1/live/gateway/stats"):
        (REQUIRE_LOGIN, "KIS 호출 큐 통계 — 처리량으로 활동량이 드러나고, 부르면 게이트웨이 작업자가 켜진다"),
    ("GET", "/api/v1/live/health"):
        (REQUIRE_LOGIN, "실거래 종합 상태 — 주문 상태 분포(/orders/state-distribution 과 같은 값)를 싣는다"),

    # ── 경로에 남의 이름이 들어간다 ───────────────────────────────────────
    ("GET", "/trade-history/{username}"):
        (REQUIRE_SELF_OR_ADMIN, "★타인 PII★ — 로드맵 완료 판정의 403 이 이 라우트다"),

    # ── 계정 (BS1) — 공개 가입은 없다: 발급은 관리자만 ─────────────────────
    ("POST", "/api/v1/auth/password"):
        (REQUIRE_LOGIN, "내 비밀번호 바꾸기 — 바꿀 차례여도 열린다(여기를 막으면 영영 못 바꾼다)"),
    ("GET", "/api/v1/auth/users"):
        (REQUIRE_ADMIN, "계정 목록 — 누가 이 시스템에 들어올 수 있는지 드러난다"),
    ("POST", "/api/v1/auth/users"):
        (REQUIRE_ADMIN, "계정 발급 — 로그인만 하면 실계좌 잔고가 열리므로 운영자만"),
    ("POST", "/api/v1/auth/users/{username}/reset-password"):
        (REQUIRE_ADMIN, "남의 비밀번호 초기화 — 그 사람의 토큰이 모두 죽는다"),

    # ── 내 증권 계좌 (BV4) — 로그인 + ★본인 계좌만★: 소유자는 토큰에서 오고, 남의 계좌는 404 ──
    ("GET", "/api/v1/broker-accounts"):
        (REQUIRE_LOGIN, "내 증권 계좌 목록(가림) — 소유자로 거른다"),
    ("POST", "/api/v1/broker-accounts"):
        (REQUIRE_LOGIN, "증권 계좌 연결 — 앱 키·시크릿·계좌번호를 받아 암호화해 둔다"),
    ("DELETE", "/api/v1/broker-accounts/{account_id}"):
        (REQUIRE_LOGIN, "내 증권 계좌 지우기 — 남의 계좌는 404"),
    ("POST", "/api/v1/broker-accounts/{account_id}/check"):
        (REQUIRE_LOGIN, "내 증권 계좌 연결 확인 — 그 계좌 자격으로 증권사에 잔고를 한 번 묻는다. 남의 계좌는 404"),
}

#: 돈·PII 키워드에 걸리지만 **의도적으로 열어 둔** 라우트 → ★왜 열었는지★.
#: 사유 없는 면제는 금지 — 여기 비어 있는 값이 있으면 트립와이어가 실패한다.
OPEN_WITH_REASON: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/live/mode"):
        "현재 실행 모드 표시 — 관리 화면이 로그인 전에 상태를 읽어야 하고, 값이 돈을 옮기지 않는다",
    ("GET", "/api/v1/live/kill-switch/status"):
        "정지 상태 표시 — 같은 이유. 막혀 있다는 사실은 숨길수록 위험하다",
    ("GET", "/api/v1/trading/mode"):
        "mock/paper/real 라벨 표시 — 계좌 자료가 아니다",
    # BV0a 정정: 이 사유는 예전에 `/api/v1/trading/status` 에 붙어 있었다. 그 경로는 브로커 잔고를
    # 내므로 보호로 옮겼고, 사유가 실제로 설명하던 이 경로에 글을 옮겨 왔다.
    ("GET", "/trading-status"):
        "프로세스 로컬 설정값(trading_config) 표시 — 계좌 자료가 아니다",
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
    # ★`/strategies/` 마커에 걸린 BG5 의 새 문★ — 멀티전략 레지스트리는 연구 표면이다.
    # 실측: `StrategyRegistry` 를 쓰는 곳은 stage11·stage12 라우트 · 멀티전략 엔진 ·
    # 귀인 분해뿐이고, 주문·계좌·킬스위치 경로는 한 곳도 읽지 않는다.
    ("DELETE", "/api/v1/multibacktest/strategies/{strategy_id}"):
        "멀티전략 연구 레지스트리의 전략 비활성(BG5) — 지우지 않고 표시만 바꾼다. 레지스트리는 "
        "백테스트·귀인만 읽고 주문·계좌 경로는 읽지 않는다(실측)",
    ("POST", "/api/v1/accounts/diagnose"):
        "요청 본문의 보유·계좌유형·한도로 도는 판정(AD4) — 저장된 계좌를 읽지 않는다",
    ("POST", "/api/v1/accounts/glidepath"):
        "요청 본문의 보유·기간·곡선·적립 계획으로 도는 관측(AO4) — 저장된 계좌를 읽지 않고 아무것도 저장하지 않는다",
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
    # BV0a — 실거래 표면 전체. 예전 조각들(/live/mode 등)만으로는 대조·알림·게이트웨이·종합 상태
    # 경로가 사정거리 밖이었다. 앞으로 생길 /live 경로도 여기서 자동으로 걸린다.
    "/api/v1/live/",
    "reconcile",
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
    # BV4 — 사용자 증권 계좌. `"/accounts/"` 는 `broker-accounts` 에 걸리지 않는다(실측).
    "broker-account",
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
    from src.api.auth import (
        require_admin,
        require_login,
        require_login_to_change_password,
        require_self_or_admin,
    )

    by_call = {
        require_admin: REQUIRE_ADMIN,
        require_login: REQUIRE_LOGIN,
        # 바꿀 차례여도 통과하는 로그인 — 요구 수준은 로그인이다(BS1).
        require_login_to_change_password: REQUIRE_LOGIN,
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
