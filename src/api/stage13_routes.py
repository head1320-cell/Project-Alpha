"""
Stage 13 API Routes — Live Trading
=========================================
11개 엔드포인트:
  · POST /init-schema            — 스키마 초기화
  · POST /orders/submit          — 단일 신호 → 검증 → 실행
  · GET  /orders                 — 주문 목록
  · GET  /orders/{coid}          — 단일 주문 상세 + 체결
  · DELETE /orders/{coid}        — 주문 취소
  · GET  /balance                — KIS 잔고 조회
  · POST /mode                   — 실행 모드 변경 (SHADOW/PAPER/LIVE)
  · GET  /mode                   — 현재 모드
  · POST /kill-switch/trigger    — Kill switch 수동 발동
  · POST /kill-switch/resolve    — Kill switch 해제
  · GET  /kill-switch/events     — Kill 이벤트 이력
  · GET  /audit                  — 감사 로그 조회 (filters)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.auth import require_admin, require_login
from src.database import get_engine
from src.domain.auth_identity import Principal, observed_actor
from src.domain.breaker_change_gate import gate_summary
from src.domain.kis_rt_cd import (
    fold_observations,
    gap_list,
    table_summary,
)
from src.domain.perf_kind import execution_label
from src.execution.drawdown import drawdown_from_history

router = APIRouter(prefix="/api/v1/live", tags=["live-trading"])


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton (간이) — 실제로는 의존성 주입이나 캐시 사용 권장
# ═══════════════════════════════════════════════════════════════════════════════

_EXECUTOR = None


def get_executor():
    """Lazy 초기화 executor 인스턴스."""
    global _EXECUTOR
    if _EXECUTOR is not None:
        return _EXECUTOR

    from src.data.mock_gate import mock_allowed
    from src.database import get_sync_engine
    from src.execution.audit_trail import AuditTrail
    from src.execution.kill_switch import KillSwitch, KillSwitchConfig
    from src.execution.kis_client import get_order_client
    from src.execution.order_executor import ExecutionMode, OrderExecutor
    from src.execution.risk_gateway import RiskGateway, RiskLimits

    # ★KIS 클라이언트는 단일 경로에서(BV2)★ — 예전에는 여기서 `KIS_USE_MOCK` 을 직접 읽고 `.env` 로
    # `KISClient` 를 하나 더 만들었다(같은 앱 키로 토큰·속도 제한·회로 차단기가 둘). 이제 `get_kis_client()` 와
    # 같은 인스턴스를 쓰고, 운영에서 계좌번호가 비면 실행기를 만들지 않고 사유를 낸다(`get_order_client`).
    kis = get_order_client()
    use_mock = mock_allowed()

    engine = get_sync_engine()

    audit = AuditTrail(engine)
    kill_switch = KillSwitch(engine, audit, KillSwitchConfig())
    risk_gw = RiskGateway(
        engine,
        limits=RiskLimits(),
        universe=set(),  # 운영 시 종목 화이트리스트 주입
        bypass_market_hours=bool(use_mock),
    )

    _EXECUTOR = OrderExecutor(
        engine=engine, kis_client=kis,
        risk_gateway=risk_gw, audit_trail=audit,
        kill_switch=kill_switch,
        mode=ExecutionMode.SHADOW,
    )
    return _EXECUTOR


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 스키마 초기화
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/init-schema", dependencies=[Depends(require_admin)])
def live_init_schema():
    """live_* 테이블 생성 + 체결 중복 방지 인덱스.

    ★인덱스 결과를 삼키지 않는다★ — 기존 `live_fills` 에 같은 `kis_fill_id` 가
    둘 이상이면 생성이 실패하고, 그 사실이 응답에 실린다(Y1-③).
    """
    try:
        from src.database import get_sync_engine
        from src.execution.live_schemas import (
            ensure_fill_dedup_index,
            init_live_trading_schema,
        )
        engine = get_sync_engine()
        n = init_live_trading_schema(engine)
        dedup_ok, dedup_reason = ensure_fill_dedup_index(engine)
        return {"status": "OK", "ddls_executed": n,
                "fill_dedup_index": dedup_ok, "fill_dedup_reason": dedup_reason}
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 주문 발주 + 조회 + 취소
# ═══════════════════════════════════════════════════════════════════════════════

class SignalRequest(BaseModel):
    strategy_id: int
    ticker:      str = Field(..., min_length=4, max_length=10)
    side:        str = Field(..., pattern="^(BUY|SELL)$")
    quantity:    int = Field(..., gt=0)
    price:       float | None = None
    order_type:  str = Field(default="MARKET", pattern="^(MARKET|LIMIT)$")
    source:      str = Field(default="manual")


@router.post("/orders/submit")
def live_submit_order(req: SignalRequest, principal: Principal = Depends(require_admin)):
    """신호 → 위험 검증 → 모드 라우팅 → 실행. ★누가 냈는지는 토큰에서★(BV5 — 예전엔 감사 행이 'system')."""
    try:
        executor = get_executor()
        who = observed_actor(principal, None)
        result = executor.execute_signal(req.model_dump(), actor=who["actor"])
        return {**result, **who} if isinstance(result, dict) else result
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/orders", dependencies=[Depends(require_login)])
def live_list_orders(
    status: str | None = None,
    strategy_id: int | None = None,
    ticker: str | None = None,
    limit: int = Query(100, le=500),
):
    try:
        executor = get_executor()
        orders = executor.list_orders(status, strategy_id, ticker, limit)
        return {"count": len(orders), "orders": orders}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/orders/{client_order_id}", dependencies=[Depends(require_login)])
def live_get_order(client_order_id: str):
    try:
        executor = get_executor()
        order = executor.get_order(client_order_id)
        if not order:
            raise HTTPException(404, "주문 없음")
        return order
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/orders/{client_order_id}")
def live_cancel_order(client_order_id: str, actor: str = "user",
                      principal: Principal = Depends(require_admin)):
    try:
        executor = get_executor()
        who = observed_actor(principal, actor)
        result = executor.cancel_order(client_order_id, who["actor"])
        return {**result, **who} if isinstance(result, dict) else result
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 계좌 + 잔고
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/balance", dependencies=[Depends(require_login)])
def live_balance():
    """KIS 잔고 + 평가 + 보유 종목."""
    try:
        executor = get_executor()
        return executor.kis.get_balance()
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 실행 모드 (SHADOW/PAPER/LIVE)
# ═══════════════════════════════════════════════════════════════════════════════

class ModeChangeRequest(BaseModel):
    mode:          str = Field(..., pattern="^(SHADOW|PAPER|LIVE)$")
    actor:         str = Field(default="user")
    confirm_token: str | None = None


@router.post("/mode")
def live_set_mode(req: ModeChangeRequest,
                  principal: Principal = Depends(require_admin)):
    """⚠ LIVE 진입은 confirm_token='EXPLICIT_LIVE_CONFIRMED' 필요."""
    try:
        executor = get_executor()
        # ★감사에 적히는 이름은 토큰에서 관측된 것이다★ — `req.actor` 는 넘기지 않는다.
        who = observed_actor(principal, req.actor)
        result = executor.set_mode(req.mode, who["actor"], req.confirm_token)
        return {**result, **who}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/mode")
def live_get_mode():
    try:
        executor = get_executor()
        return {
            "mode": executor.state.mode,
            "started_at":         executor.state.started_at.isoformat() if executor.state.started_at else None,
            "last_mode_change":   executor.state.last_mode_change.isoformat() if executor.state.last_mode_change else None,
            "changed_by":         executor.state.changed_by,
            "enabled_strategies": list(executor.state.enabled_strategies),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Kill Switch
# ═══════════════════════════════════════════════════════════════════════════════

class KillTriggerRequest(BaseModel):
    reason:           str = Field(..., min_length=4)
    liquidation_mode: str = Field(default="hold", pattern="^(hold|gradual|immediate)$")
    actor:            str = Field(default="user")


@router.post("/kill-switch/trigger")
def live_kill_trigger(req: KillTriggerRequest,
                      principal: Principal = Depends(require_admin)):
    """🚨 비상 정지."""
    try:
        executor = get_executor()
        who = observed_actor(principal, req.actor)
        balance = executor.kis.get_balance()
        # ★발동 시점의 드로다운을 **관측해** 싣는다★ (AP3) — 예전에는 아무도
        # `dd_pct` 를 넘기지 않아 `dd_at_trigger` 가 저장소 전체에서 언제나 `0`
        # 이었다. 못 재면 `None` 이고, 그 사실은 응답의 `observations` 가 말한다.
        # ★이 값은 관측이지 원인이 아니다★ — 수동 발동은 사람이 일으킨 것이고
        # `trigger_source` 가 그렇게 적는다.
        dd = drawdown_from_history(get_engine())
        result = executor.kill_switch.trigger(
            source=f"manual_{who['actor']}",
            reason=req.reason,
            # ★`, 0` 폴백을 지웠다★ — 조회 실패가 "잔고 0" 이 되면 안 된다.
            equity=balance.get("evaluated_total"),
            dd_pct=dd.cumulative_pct,
            kis_client=executor.kis,
            liquidation_mode=req.liquidation_mode,
        )
        return {**result, **who}
    except Exception as e:
        raise HTTPException(500, str(e))


class KillResolveRequest(BaseModel):
    #: ★선택 항목이 됐다★(AC5) — 해제자는 토큰에서 **관측**하므로 본문이 이름을
    #: 주장할 필요가 없다. 필드를 지우지 않는 이유는 기존 호출자를 422 로 깨뜨리지
    #: 않기 위해서이고, 주장이 토큰과 다르면 응답의 `claimed_actor` 에 남는다.
    resolved_by: str | None = Field(default=None)
    notes:       str = Field(default="")


@router.post("/kill-switch/resolve")
def live_kill_resolve(req: KillResolveRequest,
                      principal: Principal = Depends(require_admin)):
    try:
        executor = get_executor()
        who = observed_actor(principal, req.resolved_by)
        result = executor.kill_switch.resolve(who["actor"], req.notes)
        return {**result, **who}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/kill-switch/status")
def live_kill_status():
    try:
        executor = get_executor()
        return {
            "is_active": executor.kill_switch.is_active(),
            "active_event": executor.kill_switch.active_event(),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/kill-switch/kis-codes", dependencies=[Depends(require_login)])
def live_kis_codes(limit: int = 5000):
    """★우리가 본 KIS 업무 코드와, 아직 뜻을 모르는 것들★ (AS4)

    AR 이 `business`(HTTP 200 + `rt_cd != "0"`)를 다른 실패와 갈라 놓았지만
    ★그 종류의 뜻을 저장소가 모른다★ — `rt_cd`/`msg_cd` 를 뜻으로 옮기는 표가
    없다. 장 종료 같은 정상 업무 응답과 KIS 장애가 같은 breaker 카운터에
    들어가는 안전 역전이 거기서 나온다.

    이 라우트는 그 표를 ★채우기 위한 재료★를 낸다:

    - `observed` — 감사 로그에 쌓인 `(rt_cd, msg_cd, 실행 모드)` 별 관측.
      ★모드를 합치지 않는다★ — 모의와 실계좌를 섞으면 수치가 뜻을 잃는다.
    - `gaps` — 그중 표에 없는 것. ★표가 비어 있으면 gaps 가 곧 observed 이고,
      그것이 지금의 진실이다.★
    - `table` — 표의 크기와, 비어 있다면 왜 비어 있는지.

    ★관측 횟수는 뜻의 증거가 아니다★ — 99번 본 코드도 KIS 문서나 실계좌
    응답이 있기 전까지는 미상이다. 새 테이블은 만들지 않았다(감사 로그를
    읽기 시점에 집계한다).
    """
    try:
        executor = get_executor()
        rows = executor.audit.kis_code_rows(limit=limit)
        observed = fold_observations(rows)
        return {
            "observed": observed,
            "gaps": gap_list(observed),
            "table": table_summary(),
            # ★이 코드를 breaker 카운트에서 뺄 수 있는가★(AU) — 오늘은 전부
            #   막혀 있고 조건마다 사유가 붙는다. 판정 단위가 코드 하나하나인
            #   이유는 `business` 가 의미가 아니라 모양이기 때문이다.
            "gate": gate_summary(observed),
            "note": ("표가 비어 있으면 모든 코드가 미상입니다 — 본 적이 있다는 "
                     "것과 뜻을 안다는 것은 다릅니다. 표를 채우려면 KIS 문서나 "
                     "실계좌 응답이 필요하고, 그것은 코드로 답할 수 없습니다."),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/kill-switch/readiness", dependencies=[Depends(require_login)])
def live_kill_readiness():
    """★자동 트리거 넷 중 무엇이 무장됐고 무엇이 왜 불능인가★ (AF4)

    `/kill-switch/status` 는 `is_active` 만 말한다. 운영자가 그것만 보면 안전망 넷이
    서 있다고 읽는데, ★재료가 없는 트리거는 영원히 발동하지 않는다★. 그 사실을 아는
    것은 백그라운드 감시 데몬뿐이었다.

    ★넷의 현황은 AP 에서 다시 실측했다(2026-09-21).★ `auto_dd`·`auto_cb` 는 AI 가
    에쿼티 기록 경로를 만들어 **잴 수 있게 됐다**(다만 리더가 브로커 행만 계열에
    넣으므로 mock 환경에서는 `mock_equity_only` 로 남는다). `auto_risk` 는
    `systemic_risk_score` 의 생산자가 저장소에 없고, `auto_api` 는 실패 횟수를
    기록하는 코드가 없다 — ★이 응답이 매 요청 다시 재어 말한다.★

    ★`/status` 를 건드리지 않는다★ — 그쪽은 열려 있고 싸다. 이 라우트는 계좌 상태에서
    파생되므로 로그인을 요구한다.
    """
    try:
        executor = get_executor()
        # ★조회 실패를 빈 응답으로 삼키지 않는다★ — 빈 목록은 "다 무장됨" 으로 읽힌다.
        try:
            account_state = executor._fetch_account_state()
            fetch_reason = None
        except Exception as e:
            account_state = {}
            fetch_reason = f"계좌 상태를 조회하지 못했습니다: {type(e).__name__}"

        # ★감시 데몬과 같은 국면 입력★ (BH1) — 예전에는 `None` 을 하드코딩해 데몬이
        # 무엇을 보든 `auto_risk` 를 불능으로 보고했다. 모듈 속성으로 부른다(교체 가능).
        from src.execution import risk_monitor
        regime_state = risk_monitor.current_regime_state()
        readiness = executor.kill_switch.trigger_readiness(account_state, regime_state)
        return {
            **readiness,
            "is_active": executor.kill_switch.is_active(),
            # ★왜 무장됐고 왜 아닌지의 재료★(AQ) — 판정은 위 `readiness` 가 하고,
            # 이 블록은 `auto_api` 가 본 숫자와 그 출처·차단 상태를 그대로 낸다.
            "api_failure_observation": account_state.get("api_failure_observation"),
            "account_state_reason": fetch_reason,
            "note": ("불능 트리거는 임계값 문제가 아니라 재료가 없어서 발동하지 "
                     "않습니다 — 임계를 낮춰도 달라지지 않습니다."),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/kill-switch/events", dependencies=[Depends(require_login)])
def live_kill_events(limit: int = Query(50, le=200)):
    try:
        from sqlalchemy import text

        from src.database import get_sync_engine
        with get_sync_engine().connect() as conn:
            rows = conn.execute(text("""
                SELECT * FROM live_kill_events
                ORDER BY triggered_at DESC LIMIT :lim
            """), {"lim": limit}).fetchall()
        # ★`active_event()` 와 **같은 함수**로 조치를 붙인다★ — 두 표면이 같은
        # 사실을 말해야 한다. 기록이 없는 과거 행은 `unknown` + 사유다(AP5).
        from src.execution.kill_switch import decorate_event
        return {"count": len(rows),
                "events": [decorate_event(dict(r._mapping)) for r in rows]}
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Audit Trail 조회
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/audit", dependencies=[Depends(require_login)])
def live_audit(
    event_type:     str | None = None,
    category:       str | None = None,
    severity_min:   str | None = None,
    strategy_id:    int | None = None,
    client_order_id: str | None = None,
    limit:          int = Query(100, le=500),
):
    """감사 로그 조회 (다중 필터)."""
    try:
        executor = get_executor()
        events = executor.audit.query(
            event_type=event_type, category=category,
            severity_min=severity_min,
            strategy_id=strategy_id, client_order_id=client_order_id,
            limit=limit,
        )
        return {"count": len(events), "events": events}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/audit/summary", dependencies=[Depends(require_login)])
def live_audit_summary(date: str | None = None):
    """단일 거래일 audit 요약."""
    try:
        executor = get_executor()
        return executor.audit.daily_summary(date)
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Daily P&L
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/daily-pnl", dependencies=[Depends(require_login)])
def live_daily_pnl(limit: int = Query(30, le=365)):
    """일별 P&L 이력."""
    try:
        from sqlalchemy import text

        from src.database import get_sync_engine
        with get_sync_engine().connect() as conn:
            rows = conn.execute(text("""
                SELECT * FROM live_daily_pnl
                ORDER BY trade_date DESC LIMIT :lim
            """), {"lim": limit}).fetchall()
        # ★행마다 다를 수 있다★ — 같은 표에 SHADOW/PAPER/LIVE 가 섞인다.
        # `execution_mode` 가 비어 있으면 `unknown` 이다(어느 쪽으로도 기울지 않는다).
        out = []
        for r in rows:
            row = dict(r._mapping)
            row["perf_label"] = execution_label(
                execution_mode=row.get("execution_mode")).to_dict()
            out.append(row)
        return {"count": len(out), "pnl_history": out}
    except Exception as e:
        raise HTTPException(500, str(e))
