"""
Kill Switch — 비상 정지 시스템
====================================
모든 trading 활동을 즉시 중단. 가장 중요한 안전장치.

발동 트리거:
  · MANUAL    — 사용자 버튼 클릭
  · AUTO_DD   — 누적 drawdown -10% 초과
  · AUTO_RISK — Stage 9 systemic_risk_score = PANIC (>85)
  · AUTO_API  — KIS API 연속 실패 (circuit breaker)
  · AUTO_CB   — Daily loss -5% 초과 (intraday circuit breaker)

발동 시 액션:
  ① 모든 신규 주문 거부 (executor에 lock)
  ② 미체결 주문 일괄 취소 (KIS cancel API 호출)
  ③ (옵션) 포지션 청산
       · gradual: 시장가 분할 매도 (5분 간격)
       · immediate: 시장가 즉시 전량
       · hold: 미체결만 취소, 포지션 유지
  ④ Slack/Email 알림 (옵션)
  ⑤ Audit trail CRITICAL 기록
  ⑥ live_kill_events 테이블에 영구 기록

해제:
  · 사용자가 명시적으로 resolve 호출 (수동 해제만)
  · resolved_at + resolved_by + resolution_notes 기록
  · 자동 해제 없음 (안전을 위해)
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

from src.domain.kill_action import (
    ACTION_BLOCK_NEW_ORDERS,
    ACTION_CANCEL_OPEN,
    ACTION_LIQUIDATE,
    ACTION_NOTIFY,
    STATE_DONE,
    STATE_FAILED,
    STATE_SKIPPED,
    ActionRecord,
    action_rollup,
    observations,
    unknown_actions,
)

logger = logging.getLogger(__name__)

#: ★`gradual` 은 간이 구현이다★ — 1/5 만 매도하고 나머지는 남는다. 그 사실을 값으로
#: 들고 다니지 않으면 호출자는 청산이 끝났다고 읽는다(AF).
_GRADUAL_PARTIAL_REASON = (
    "gradual 모드는 1/5 만 매도하는 간이 구현입니다 — "
    "나머지 수량은 매도되지 않았습니다."
)

#: ★시도하지 않은 것과 할 일이 없던 것을 가른다★ (AP4)
_NO_CLIENT_CANCEL = (
    "브로커 클라이언트 없이 발동해 미체결 주문 취소를 ★시도하지 않았습니다★ — "
    "★미체결 주문이 남아 있을 수 있습니다.★ 자동 발동 경로"
    "(`execution/risk_monitor.run_once`)가 이 모양입니다."
)
_NO_CLIENT_LIQUIDATE = (
    "브로커 클라이언트 없이 발동해 청산을 ★시도하지 않았습니다★ — "
    "보유는 그대로입니다."
)
_HOLD_LIQUIDATE = (
    "청산 모드가 `hold` 라 포지션을 ★팔지 않았습니다★ — 발동은 이후 신규 주문을 "
    "막을 뿐 보유를 줄이지 않습니다."
)
_NOTIFY_DISABLED = "통지가 꺼져 있습니다(`notification_enabled=False`)."
_NOTIFY_FAILED = "통지 중 오류가 났습니다: {}"
#: ★발동 즉시 구조적으로 참인 유일한 조치★ — 이벤트 행이 생기면 `is_active()` 가
#: 참이 되고 실행기가 **두 지점**에서 막는다(검증 시점 · 발주 직전 레이스).
_BLOCK_GUARD = ("execution/order_executor.py — 사전 검증(kill_switch_active)과 "
                "발주 직전 재확인(kill_switch_race), 두 지점")
_UNOBSERVED_TEXT = "미상"

#: 조치 기록이 없는 행의 사유. ★소급해 채우지 않는다★ — 이 어휘(AP)가 생기기
#: 전에 쓰인 행은 무엇을 했는지 **적히지 않았을** 뿐이고, 안 적힌 것을 "했다" 로
#: 채우면 없는 관측을 만든다.
_NO_ACTION_RECORD = (
    "이 발동에는 조치 기록이 없습니다 — 조치를 기록하기 시작하기(AP) 전에 쓰인 "
    "행이거나 기록에 실패했습니다. ★무엇을 했는지 알 수 없다는 뜻이고, "
    "아무것도 안 했다는 뜻도 다 했다는 뜻도 아닙니다.★")
_BROKEN_ACTION_RECORD = (
    "조치 기록을 읽을 수 없습니다({}) — ★읽히지 않는 기록은 미상입니다.★")


def decorate_event(row: dict | None) -> dict | None:
    """저장된 발동 행 → 조치 기록을 붙인 행. ★없으면 `unknown`★ (AP5)

    표면 둘(`/kill-switch/status` 의 `active_event` · `/kill-switch/events`)이
    **같은 함수**를 쓴다 — 두 벌로 만들면 한쪽만 고쳐도 아무 테스트가 깨지지 않고,
    화면에 따라 다른 사실이 보인다(`run_evidence.rollup` 이 세운 규율).
    """
    if not row:
        return row
    raw = row.get("actions_json")
    if raw:
        try:
            return {**row, "actions": json.loads(raw)}
        except Exception as e:                           # noqa: BLE001
            return {**row, "actions": action_rollup(
                unknown_actions(_BROKEN_ACTION_RECORD.format(e)))}
    return {**row, "actions": action_rollup(unknown_actions(_NO_ACTION_RECORD))}


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class KillSwitchConfig:
    auto_dd_threshold:        float = 0.10   # 누적 -10%
    auto_intraday_loss:       float = 0.05   # 일중 -5%
    auto_risk_score:          float = 85.0   # PANIC 임계값
    api_failure_threshold:    int = 5

    default_liquidation_mode: str = "hold"   # gradual | immediate | hold
    notification_enabled:     bool = True


# ═══════════════════════════════════════════════════════════════════════════════
# KillSwitch
# ═══════════════════════════════════════════════════════════════════════════════

class KillSwitch:
    """
    Trading 시스템 비상 정지.

    Usage:
        ks = KillSwitch(engine, audit_trail, config=KillSwitchConfig())

        # 수동 발동
        event = ks.trigger(
            source="manual",
            reason="사용자 직접 정지",
            equity=100_000_000,
            kis_client=client,
            liquidation_mode="hold",
        )

        # 자동 발동 (모니터링 루프에서 호출)
        if ks.should_auto_trigger(account_state, regime_state):
            ks.trigger(source="auto_dd", reason="drawdown 한도 초과", ...)

        # 상태 확인
        if ks.is_active():
            # 모든 주문 거부

        # 해제
        ks.resolve(resolved_by="admin", notes="시장 안정화 확인")
    """

    def __init__(self, engine, audit_trail=None, config: KillSwitchConfig | None = None):
        self.engine = engine
        self.audit = audit_trail
        self.config = config or KillSwitchConfig()
        self._cached_active: bool | None = None

    # ─────────────────────────────────────────────────────────────────────
    # 상태 확인
    # ─────────────────────────────────────────────────────────────────────

    def is_active(self) -> bool:
        """현재 kill switch 활성 여부."""
        try:
            with self.engine.connect() as conn:
                row = conn.execute(text("""
                    SELECT COUNT(*) AS cnt FROM live_kill_events
                    WHERE resolved_at IS NULL
                """)).fetchone()
                return (row._mapping["cnt"] if row else 0) > 0
        except Exception as e:
            logger.error(f"Kill switch 상태 조회 실패: {e}")
            return True   # 안전: 조회 실패 시 active 가정

    def _store_actions(self, event_id: str, actions: dict) -> None:
        """조치 기록을 이벤트 행에 남긴다. ★기록 실패가 발동을 무르지 않는다★

        컬럼이 아직 없는 DB 에서도 발동 자체는 성립해야 한다 — 그래서 실패를
        삼키되 흔적을 남긴다(`equity_history.record_observation` 과 같은 관용구).
        """
        try:
            with self.engine.begin() as conn:
                conn.execute(text(
                    "UPDATE live_kill_events SET actions_json = :a "
                    "WHERE event_id = :eid"),
                    {"a": json.dumps(actions, ensure_ascii=False), "eid": event_id})
        except Exception as e:                           # noqa: BLE001
            logger.warning(f"조치 기록 저장 실패(발동은 유효): {e}")

    def active_event(self) -> dict | None:
        """현재 미해결 kill 이벤트 (있다면)."""
        try:
            with self.engine.connect() as conn:
                row = conn.execute(text("""
                    SELECT * FROM live_kill_events
                    WHERE resolved_at IS NULL
                    ORDER BY triggered_at DESC LIMIT 1
                """)).fetchone()
                # ★조치 기록을 함께 낸다★ — 없으면 `unknown`(AP5)
                return decorate_event(dict(row._mapping)) if row else None
        except Exception as e:
            logger.error(f"Kill event 조회 실패: {e}")
            return None

    # ─────────────────────────────────────────────────────────────────────
    # 자동 발동 트리거 검사
    # ─────────────────────────────────────────────────────────────────────

    def should_auto_trigger(
        self,
        account_state: dict,
        regime_state: dict | None = None,
    ) -> tuple[str, str] | None:
        """
        자동 발동 조건 검사. 발동 필요 시 (source, reason) 튜플 반환.
        """
        if self.is_active():
            return None  # 이미 발동된 상태

        # ★미상을 0 으로 읽지 않는다★ — 예전에는 `_fetch_account_state` 가 드로다운을
        # 하드코딩 0 으로 주어 1·2 가 **구조적으로 발동할 수 없었다**(P1-a).
        # 못 본 항목은 건너뛰고, 무엇을 못 봤는지는 `unverified_checks()` 가 말한다.

        # 1. 누적 drawdown
        raw_cumul = account_state.get("cumulative_dd_pct")
        if raw_cumul is not None:
            cumul_dd = abs(raw_cumul)
            if cumul_dd >= self.config.auto_dd_threshold:
                return ("auto_dd",
                         f"누적 drawdown 한도 초과 ({cumul_dd:.1%} >= {self.config.auto_dd_threshold:.0%})")

        # 2. 일중 손실
        raw_intraday = account_state.get("current_drawdown_pct")
        if raw_intraday is not None:
            intraday = abs(raw_intraday)
            if intraday >= self.config.auto_intraday_loss:
                return ("auto_cb",
                         f"일중 손실 한도 초과 ({intraday:.1%} >= {self.config.auto_intraday_loss:.0%})")

        # 3. Systemic risk PANIC
        if regime_state:
            risk_score = regime_state.get("systemic_risk_score", 0) or 0
            if risk_score >= self.config.auto_risk_score:
                return ("auto_risk",
                         f"PANIC 국면 감지 (risk_score={risk_score:.0f})")

        # 4. API 실패율 (외부에서 주입)
        # ★미상을 0 으로 읽지 않는다★ — 위 1·2 에 적용한 P1-a 규율이 이 분기에만
        #   빠져 있었다. `.get(…, 0)` 이면 아무도 기록하지 않는 값이 언제나 0 이 되어
        #   `auto_api` 가 **구조적으로 발동할 수 없고**, 그 사실조차 보이지 않았다.
        raw_api = account_state.get("api_failure_count")
        if raw_api is not None and raw_api >= self.config.api_failure_threshold:
            return ("auto_api",
                     f"KIS API 연속 실패 ({raw_api}회)")

        return None

    def unverified_checks(
        self,
        account_state: dict,
        regime_state: dict | None = None,
    ) -> tuple[str, ...]:
        """★무엇을 보지 못했나★ — 발동하지 않은 것과 **못 본 것**은 다르다.

        `should_auto_trigger()` 가 `None` 을 돌려줬을 때 그것이 *"한도 안에 있다"* 인지
        *"잴 수 없었다"* 인지 구분할 방법이 없었다. 감시 루프가 "정상" 을 기록하려면
        먼저 이것이 비어 있어야 한다.
        """
        out: list[str] = []
        reason = account_state.get("drawdown_reason") or "unknown"
        if account_state.get("cumulative_dd_pct") is None:
            out.append(f"auto_dd: 누적 drawdown 미상 ({reason})")
        if account_state.get("current_drawdown_pct") is None:
            out.append(f"auto_cb: 일중 손실 미상 ({reason})")
        if not regime_state or regime_state.get("systemic_risk_score") is None:
            out.append("auto_risk: 국면 systemic_risk_score 미상")
        if account_state.get("api_failure_count") is None:
            out.append("auto_api: KIS API 실패 횟수 미상 "
                       "(이 저장소에는 그 값을 기록하는 코드가 없습니다)")
        return tuple(out)

    #: 자동 트리거 넷. ★`should_auto_trigger` 가 내는 `source` 문자열 그대로★
    AUTO_TRIGGERS = ("auto_dd", "auto_cb", "auto_risk", "auto_api")

    def trigger_readiness(self, account_state: dict,
                          regime_state: dict | None = None) -> dict:
        """★무엇이 무장됐고 무엇이 왜 불능인가★

        `unverified_checks()` **위에 세운다** — 같은 사실을 두 곳에서 판정하면 갈린다.
        운영 화면이 "킬스위치: 미발동" 만 보여 주면 안전망 넷이 서 있다고 읽히는데,
        재료가 없는 트리거는 **영원히 발동하지 않는다**. 그 차이를 값으로 낸다.
        """
        unverified = self.unverified_checks(account_state, regime_state)
        reasons = {u.split(":", 1)[0]: u.split(":", 1)[1].strip() for u in unverified}

        inoperable = [{"trigger": name, "reason": reasons[name]}
                      for name in self.AUTO_TRIGGERS if name in reasons]
        armed = [{"trigger": name, "basis": "재료가 있어 임계 검사가 실제로 돈다"}
                 for name in self.AUTO_TRIGGERS if name not in reasons]
        return {
            "armed": armed,
            "inoperable": inoperable,
            "summary": (f"자동 트리거 {len(self.AUTO_TRIGGERS)}개 중 "
                        f"{len(armed)}개 무장 · {len(inoperable)}개 불능"),
        }

    # ─────────────────────────────────────────────────────────────────────
    # 발동
    # ─────────────────────────────────────────────────────────────────────

    def trigger(
        self,
        source: str,
        reason: str,
        equity: float | None = None,
        dd_pct: float | None = None,
        regime: str | None = None,
        kis_client=None,
        liquidation_mode: str | None = None,
    ) -> dict:
        """
        Kill switch 발동.

        Args:
            source:           manual | auto_dd | auto_cb | auto_risk | auto_api
            reason:           발동 사유 (자유 텍스트)
            equity:           발동 시점 자산. ★`None` 은 "안 실었다" 이고 `0` 이
                              아니다★ — 예전 기본값 `0` 이 관측 행세를 했다(AP2).
            dd_pct:           발동 시점 drawdown. 같은 규율 — ★어느 호출부도 이
                              값을 넘기지 않아 저장소 전체에서 언제나 `0` 이었다.★
            regime:           발동 시점 regime
            kis_client:       KIS API 클라이언트 (미체결 취소용)
            liquidation_mode: gradual | immediate | hold

        Returns:
            event 정보 dict
        """
        if self.is_active():
            logger.warning("Kill switch 이미 발동 중 — 중복 trigger 무시")
            return self.active_event() or {}

        event_id = f"KILL-{uuid.uuid4().hex[:12]}"
        liq_mode = liquidation_mode or self.config.default_liquidation_mode

        # 1. DB 이벤트 기록
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO live_kill_events (
                        event_id, trigger_source, trigger_reason,
                        equity_at_trigger, dd_at_trigger, regime_at_trigger,
                        liquidation_mode
                    ) VALUES (
                        :eid, :ts, :tr, :eq, :dd, :rg, :lm
                    )
                """), {
                    "eid": event_id, "ts": source, "tr": reason,
                    "eq": equity, "dd": dd_pct, "rg": regime, "lm": liq_mode,
                })
        except Exception as e:
            logger.error(f"Kill event DB 기록 실패: {e}")

        # 2. Audit trail CRITICAL 기록
        if self.audit:
            self.audit.log_kill_switch(event_id, source, reason, equity, dd_pct)

        logger.critical(f"🚨 KILL SWITCH ACTIVATED — {source}: {reason}")

        # 3. 미체결 주문 취소 — ★시도하지 않은 것과 0 건을 가른다★
        acts: list[ActionRecord] = [
            ActionRecord(action=ACTION_BLOCK_NEW_ORDERS, state=STATE_DONE,
                         detail={"guard": _BLOCK_GUARD}),
        ]
        cancelled_count: int | None = None
        if kis_client:
            cancelled_count = self._cancel_open_orders(kis_client)
            acts.append(ActionRecord(action=ACTION_CANCEL_OPEN, state=STATE_DONE,
                                     detail={"n_cancelled": cancelled_count}))
        else:
            acts.append(ActionRecord(action=ACTION_CANCEL_OPEN,
                                     state=STATE_SKIPPED, reason=_NO_CLIENT_CANCEL))

        # 4. 청산 (옵션) — ★안 판 것을 "완료" 라고 적지 않는다★
        positions_closed: int | None = None
        krw_recovered: float | None = None
        #: ★`complete: None` 은 "시도하지 않았다"★ — 예전 초기값은 `True` 였고
        #: `hold` 모드에서 교체되지 않아, 팔지 않고도 완료라고 말했다(AP4).
        liquidation: dict = {"closed": None, "partial": [], "failed": [],
                             "krw_recovered": None, "mode": liq_mode,
                             "complete": None, "note": None}
        if liq_mode in ("immediate", "gradual") and kis_client:
            liquidation = self._liquidate_positions(kis_client, mode=liq_mode)
            # ★감사 컬럼에는 **전량 청산분만** 간다★
            positions_closed = liquidation["closed"]
            krw_recovered = liquidation["krw_recovered"]
            acts.append(ActionRecord(action=ACTION_LIQUIDATE, state=STATE_DONE,
                                     detail={k: liquidation[k] for k in
                                             ("mode", "closed", "partial",
                                              "failed", "complete", "note")}))
        else:
            acts.append(ActionRecord(
                action=ACTION_LIQUIDATE, state=STATE_SKIPPED,
                reason=_HOLD_LIQUIDATE if liq_mode == "hold" else _NO_CLIENT_LIQUIDATE,
                detail={"mode": liq_mode}))

        # 5. 통계 업데이트
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE live_kill_events
                    SET n_orders_cancelled = :nc,
                        n_positions_closed = :np,
                        krw_recovered = :kr
                    WHERE event_id = :eid
                """), {
                    "nc": cancelled_count, "np": positions_closed,
                    "kr": krw_recovered, "eid": event_id,
                })
        except Exception:
            pass

        # 6. 알림 (placeholder — Slack/Email 통합 가능)
        if self.config.notification_enabled:
            try:
                self._send_notification(event_id, source, reason, equity, dd_pct)
                acts.append(ActionRecord(action=ACTION_NOTIFY, state=STATE_DONE))
            except Exception as e:                       # noqa: BLE001
                acts.append(ActionRecord(action=ACTION_NOTIFY, state=STATE_FAILED,
                                         reason=_NOTIFY_FAILED.format(e)))
        else:
            acts.append(ActionRecord(action=ACTION_NOTIFY, state=STATE_SKIPPED,
                                     reason=_NOTIFY_DISABLED))

        actions = action_rollup(acts)
        self._store_actions(event_id, actions)

        return {
            "event_id":             event_id,
            "triggered_at":         datetime.now().isoformat(),
            "trigger_source":       source,
            "trigger_reason":       reason,
            "equity_at_trigger":    equity,
            "dd_at_trigger":        dd_pct,
            "liquidation_mode":     liq_mode,
            "n_orders_cancelled":   cancelled_count,
            "n_positions_closed":   positions_closed,
            "krw_recovered":        krw_recovered,
            # ★반만 판 것을 조용히 성공으로 보이게 하지 않는다★
            "liquidation":          liquidation,
            # ★시도하지 않았으면 `False` 가 아니라 `None`★ (미상 ≠ 거짓)
            "liquidation_complete": liquidation["complete"],
            "liquidation_note":     liquidation["note"],
            # ★발동했는가 ⟂ 무엇을 했는가★ (AP)
            "actions":              actions,
            # ★값과 그 값을 어떻게 알았나를 함께 낸다★
            "observations":         observations(equity_krw=equity, dd_pct=dd_pct,
                                                 regime=regime),
        }

    # ─────────────────────────────────────────────────────────────────────
    # 해제
    # ─────────────────────────────────────────────────────────────────────

    def resolve(self, resolved_by: str, notes: str = "") -> dict:
        """Kill switch 수동 해제."""
        event = self.active_event()
        if not event:
            return {"status": "no_active_event"}

        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE live_kill_events
                    SET resolved_at = CURRENT_TIMESTAMP,
                        resolved_by = :rb,
                        resolution_notes = :rn
                    WHERE event_id = :eid
                """), {
                    "rb": resolved_by, "rn": notes, "eid": event["event_id"],
                })
        except Exception as e:
            logger.error(f"Kill 해제 실패: {e}")
            return {"status": "db_error", "error": str(e)}

        # Audit
        if self.audit:
            from src.execution.audit_trail import EventCategory, EventType, Severity
            self.audit.log(
                event_type=EventType.KILL_SWITCH_RESOLVED,
                category=EventCategory.EMERGENCY,
                severity=Severity.CRITICAL,
                actor=resolved_by,
                context={"event_id": event["event_id"], "notes": notes},
                message=f"Kill switch 해제: {notes or '사유 없음'}",
            )

        logger.warning(f"Kill switch 해제: event {event['event_id']} by {resolved_by}")
        return {
            "status":      "resolved",
            "event_id":    event["event_id"],
            "resolved_by": resolved_by,
            "notes":       notes,
        }

    # ─────────────────────────────────────────────────────────────────────
    # Internal: 미체결 취소
    # ─────────────────────────────────────────────────────────────────────

    def _cancel_open_orders(self, kis_client) -> int:
        """모든 미체결 주문 일괄 취소."""
        cancelled = 0
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT client_order_id, kis_order_id, kis_order_org_no,
                           filled_quantity, quantity
                    FROM live_orders
                    WHERE status IN ('PENDING', 'SUBMITTED', 'PARTIAL_FILL')
                """)).fetchall()

            for r in rows:
                m = r._mapping
                remaining = (m["quantity"] or 0) - (m["filled_quantity"] or 0)
                if remaining <= 0 or not m["kis_order_id"]:
                    continue
                try:
                    kis_client.cancel_order(
                        kis_order_id=m["kis_order_org_no"] or m["kis_order_id"],
                        kis_order_no=m["kis_order_id"],
                        cancel_qty=remaining,
                    )
                    # 상태 업데이트
                    with self.engine.begin() as conn:
                        conn.execute(text("""
                            UPDATE live_orders
                            SET status = 'CANCELLED', cancelled_at = CURRENT_TIMESTAMP,
                                reason_code = 'kill_switch'
                            WHERE client_order_id = :coid
                        """), {"coid": m["client_order_id"]})
                    cancelled += 1
                except Exception as e:
                    logger.error(f"주문 취소 실패 ({m['client_order_id']}): {e}")
        except Exception as e:
            logger.error(f"미체결 조회 실패: {e}")

        return cancelled

    # ─────────────────────────────────────────────────────────────────────
    # Internal: 청산
    # ─────────────────────────────────────────────────────────────────────

    def _liquidate_positions(self, kis_client, mode: str = "gradual") -> dict:
        """
        보유 포지션 청산.

        gradual: 큰 포지션부터 분할 매도 (시장 충격 최소화)
        immediate: 시장가 즉시 전량 매도
        """
        n_closed = 0
        krw_recovered = 0.0
        # ★청산·부분매도·실패를 가른다★ — 예전에는 셋이 전부 `n_closed` 였다.
        partial: list[dict] = []
        failed: list[dict] = []

        try:
            balance = kis_client.get_balance()
            positions = balance.get("positions", [])

            for pos in positions:
                ticker = pos["ticker"]
                qty = pos["quantity"]
                if qty <= 0:
                    continue

                if mode == "immediate":
                    # 즉시 시장가
                    try:
                        kis_client.place_order(
                            ticker=ticker, side="SELL", quantity=qty,
                            order_type="MARKET",
                        )
                        n_closed += 1
                        krw_recovered += pos.get("eval_amount", 0)
                        logger.warning(f"비상 청산: {ticker} {qty}주 시장가 (event)")
                    except Exception as e:
                        logger.error(f"청산 실패 ({ticker}): {e}")
                        failed.append({"ticker": ticker, "requested_qty": qty,
                                       "reason": f"주문 실패: {e}"})

                elif mode == "gradual":
                    # 5분할 — 실제 구현은 백그라운드 task로 (간이 구현: 1/5만 즉시)
                    portion = max(1, qty // 5)
                    try:
                        kis_client.place_order(
                            ticker=ticker, side="SELL", quantity=portion,
                            order_type="MARKET",
                        )
                        # ★`n_closed` 를 올리지 않는다★ — 1/5 을 판 것은 청산이
                        #   아니다. 예전에는 여기서 올려 감사 테이블
                        #   `live_kill_events.n_positions_closed` 까지 거짓이 갔다.
                        krw_recovered += portion * pos["current_price"]
                        partial.append({
                            "ticker": ticker,
                            "sold_qty": portion,
                            "remaining_qty": qty - portion,
                            "reason": _GRADUAL_PARTIAL_REASON,
                        })
                        logger.warning(
                            f"점진 청산 1/5: {ticker} {portion}/{qty}주 "
                            f"(추가 4회 분할 매도 필요)"
                        )
                    except Exception as e:
                        logger.error(f"점진 청산 실패 ({ticker}): {e}")
                        failed.append({"ticker": ticker, "requested_qty": portion,
                                       "reason": f"주문 실패: {e}"})

        except Exception as e:
            logger.error(f"청산 절차 실패: {e}")
            failed.append({"ticker": None, "requested_qty": None,
                           "reason": f"청산 절차 실패: {e}"})

        complete = not partial and not failed
        note = None
        if not complete:
            bits = []
            if partial:
                bits.append(f"부분 매도 {len(partial)}종목(잔량 남음)")
            if failed:
                bits.append(f"실패 {len(failed)}건")
            note = ("청산이 완료되지 않았습니다 — " + " · ".join(bits)
                    + ". 남은 포지션은 매도되지 않았습니다.")

        return {
            "closed": n_closed,          # ★전량 청산된 포지션만★
            "partial": partial,
            "failed": failed,
            "krw_recovered": krw_recovered,
            "mode": mode,
            "complete": complete,
            "note": note,
        }

    # ─────────────────────────────────────────────────────────────────────
    # Internal: 알림
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _send_notification(event_id: str, source: str, reason: str,
                            equity: float | None, dd_pct: float | None):
        """Slack/Email 알림 (현재는 로깅만, 추후 webhook 통합).

        ★미상을 0 으로 찍지 않는다★ — `f"{None:,.0f}"` 는 `TypeError` 라 예전
        서명(기본값 `0`)에서는 이 분기가 필요 없었다. 기본값을 `None` 으로
        바꾸면서(AP2) 여기가 곧바로 터지므로, 미상은 **미상이라고 적는다.**
        """
        def _num(v, fmt):
            return format(v, fmt) if isinstance(v, (int, float)) \
                and not isinstance(v, bool) else _UNOBSERVED_TEXT
        msg = (
            f"🚨 KILL SWITCH ACTIVATED\n"
            f"Event: {event_id}\n"
            f"Source: {source}\n"
            f"Reason: {reason}\n"
            f"Equity: {_num(equity, ',.0f')}원\n"
            f"Drawdown: {_num(dd_pct, '.2%')}\n"
            f"Time: {datetime.now().isoformat()}"
        )
        logger.critical(msg)
        # TODO: webhook integration
        #   requests.post(SLACK_WEBHOOK_URL, json={"text": msg})
