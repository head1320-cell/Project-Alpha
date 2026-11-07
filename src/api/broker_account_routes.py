"""내 증권 계좌 — 목록 · 연결 · 지우기 · 연결 확인 (BV4)
==============================================================================
계획: BV4 · 사용자 결정(2026-10-08·09) "사용자마다 자기 KIS 계좌를 연결하고 계좌마다 모의투자/실계좌를 고른다".
저장·암호화·가림은 `src/execution/broker_accounts.py`(BV3)가 한다. 이 파일은 그 앞의 문이다.

## ★소유자는 토큰에서만 온다★

본문에 `owner` 같은 칸을 넣어도 쓰지 않는다. 남의 계좌는 ★404★ — 없는 계좌와 같은 답이다(남의 계좌 id 가 있는지조차
드러내지 않는다). 관리자에게도 우회는 없다(관리자 보기는 BU9·BV6 에서 따로 만든다).

## ★연결 확인은 '확인한 만큼만' 말한다★

- 연습용 모드(`KIS_USE_MOCK=1`)에서는 증권사에 묻지 않는다 → `practice` — '연결됨' 이라 말하지 않는다.
- 운영에서는 잔고 조회 한 번 → 받아 주면 `ok`, 증권사·네트워크 실패면 `failed` + 사람 말 사유 + 원문(비밀은 가림).
- 그 밖 예외(프로그램 오류)는 잡지 않는다 — '연결 실패' 로 꾸미지 않는다.
- 결과(상태·사람 말 사유만)는 감사에 남긴다 — 실계좌 준비 목록이 읽는다(BV7). 잔고 숫자는 싣지 않는다(잔고는 `/balance` — BV9).
"""
from __future__ import annotations

import datetime as dt

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StrictBool

from src.api.auth import require_login
from src.api.stage13_routes import SignalRequest
from src.data.mock_gate import mock_allowed
from src.database import get_sync_engine
from src.domain.auth_identity import Principal, observed_actor
from src.domain.kis_failure import KIND_BLOCKED, KIND_BUSINESS, KIND_HTTP_STATUS, KIND_TOKEN, KIND_TRANSPORT
from src.domain.live_gate import LIVE_ALLOWED, live_gate
from src.execution import broker_accounts as ba
from src.execution import live_gate_store
from src.execution.account_executors import get_account_executor
from src.execution.audit_trail import AuditTrail, EventType
from src.execution.kis_client import KISCallError, get_kis_client

router = APIRouter(prefix="/api/v1/broker-accounts", tags=["broker-accounts"])

_NOT_FOUND = "그 계좌가 없어요."

#: 실패 종류 → 사람 말. 원문은 `detail` 에 따로 싣는다.
_REASON_BY_KIND = {
    KIND_TOKEN: "증권사가 토큰을 내주지 않았어요. 앱 키·시크릿이 맞는지, 1분 안에 다시 묻지 않았는지 확인해 주세요.",
    KIND_BUSINESS: "증권사가 요청을 거절했어요. 계좌번호와 상품 코드, 모의투자/실계좌 선택이 맞는지 확인해 주세요.",
    KIND_TRANSPORT: "증권사에 닿지 못했어요. 잠시 뒤 다시 해 주세요.",
    KIND_HTTP_STATUS: "증권사에 닿지 못했어요. 잠시 뒤 다시 해 주세요.",
    KIND_BLOCKED: "실패가 이어져 이 계좌의 호출을 잠시 멈췄어요. 잠시 뒤 다시 해 주세요.",
}
_REASON_OTHER = "증권사 확인에 실패했어요. 아래 원래 사유를 확인해 주세요."


class ConnectRequest(BaseModel):
    label: str
    app_key: str
    app_secret: str
    account_no: str
    #: 돈이 걸린 선택이라 JSON 참·거짓만 받는다("false" 같은 글자를 짐작하지 않는다).
    is_paper: StrictBool
    account_prdt: str = "01"


def _owned_or_404(p: Principal, account_id: str) -> dict:
    for acc in ba.list_masked(p.username):
        if acc["account_id"] == account_id:
            return acc
    raise HTTPException(404, _NOT_FOUND)


def _redact(text: str, secrets: tuple[str, ...]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "****")
    return text


@router.get("")
def list_accounts(p: Principal = Depends(require_login)):
    return {"accounts": ba.list_masked(p.username)}


@router.post("", status_code=201)
def connect_account(req: ConnectRequest, p: Principal = Depends(require_login)):
    try:
        return ba.connect(p.username, label=req.label, app_key=req.app_key, app_secret=req.app_secret,
                          account_no=req.account_no, is_paper=req.is_paper, account_prdt=req.account_prdt)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    except ba.CredentialVaultUnavailable as e:
        raise HTTPException(503, str(e)) from None


@router.delete("/{account_id}")
def delete_account(account_id: str, p: Principal = Depends(require_login)):
    if not ba.delete(p.username, account_id):
        raise HTTPException(404, _NOT_FOUND)
    return {"deleted": account_id}


def _record_check(account_id: str, actor: str, result: dict) -> dict:
    """연결 확인 결과를 감사에 남긴다(BV7 준비 목록이 읽는다) — 상태와 사람 말 사유만, 원문·비밀은 싣지 않는다."""
    AuditTrail(get_sync_engine(), account_id=account_id).log(
        event_type=EventType.BROKER_CHECK, actor=actor, decision=result["state"], message=result["reason"])
    return result


def _open_client(account_id: str):
    """그 계좌의 클라이언트와 가릴 비밀. ★호출 전에 소유 확인을 끝내야 한다★. 금고 실패는 503."""
    try:
        client = get_kis_client(account_id=account_id)
        acct = ba.open_account(account_id)
    except ba.CredentialVaultUnavailable as e:
        raise HTTPException(503, str(e)) from None
    return client, (acct.app_key, acct.app_secret, acct.account_no)


def _ask_balance(client, secrets: tuple[str, ...]) -> tuple[dict | None, dict | None]:
    """잔고 조회 한 번 → (잔고, None) 또는 (None, 실패). 증권사·네트워크 실패만 잡는다 — 프로그램 오류는 500 으로 둔다."""
    try:
        return client.get_balance(), None
    except KISCallError as e:
        return None, {"state": "failed", "reason": _REASON_BY_KIND.get(e.kind, _REASON_OTHER),
                      "detail": _redact(str(e), secrets)}
    except requests.RequestException as e:
        # `_fetch_token` 은 `requests` 예외를 감싸지 않는다(실측) — 네트워크 실패로 읽는다.
        return None, {"state": "failed", "reason": _REASON_BY_KIND[KIND_TRANSPORT],
                      "detail": _redact(str(e), secrets)}


@router.post("/{account_id}/check")
def check_account(account_id: str, p: Principal = Depends(require_login)):
    _owned_or_404(p, account_id)   # ★소유 확인이 먼저★ — 남의 자격은 풀지도 않는다
    out = {"account_id": account_id, "checked_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    client, secrets = _open_client(account_id)
    if mock_allowed():
        return _record_check(account_id, p.username, {**out, "state": "practice",
                "reason": "연습용 모드라 증권사에 묻지 않았어요. 키가 맞는지는 아직 몰라요."})
    _, failed = _ask_balance(client, secrets)
    if failed:
        return _record_check(account_id, p.username, {**out, **failed})
    return _record_check(account_id, p.username, {**out, "state": "ok",
            "reason": "증권사가 이 키와 계좌로 잔고 조회를 받아 줬어요."})


# ═══════════════════════════════════════════════════════════════════════════════
# 내 계좌 잔고 (BV9) — 읽기만. "내 계좌" 화면이 쓴다.
# ═══════════════════════════════════════════════════════════════════════════════
# ★증권사 원문(`raw`)은 싣지 않는다★(계좌 정보가 들어 있을 수 있다) · 종목 이름도 싣지 않는다(이름은 stock_master 가 정한다 —
# 화면이 `resolve-names` 로 묻는다) · 빠진 칸은 None(0 으로 메우지 않는다) · `practice` 가 이 숫자의 출처를 말한다.

_POSITION_KEYS = ("ticker", "quantity", "avg_price", "current_price", "eval_amount", "pnl_pct")


@router.get("/{account_id}/balance")
def account_balance(account_id: str, p: Principal = Depends(require_login)):
    _owned_or_404(p, account_id)
    out = {"account_id": account_id, "practice": mock_allowed(),
           "as_of": dt.datetime.now(dt.timezone.utc).isoformat()}
    client, secrets = _open_client(account_id)
    bal, failed = _ask_balance(client, secrets)
    if failed:
        return {**out, **failed}
    return {**out, "state": "ok", "cash_krw": bal.get("cash_krw"), "evaluated_total": bal.get("evaluated_total"),
            "positions": [{k: pos.get(k) for k in _POSITION_KEYS} for pos in bal.get("positions") or []]}


# ═══════════════════════════════════════════════════════════════════════════════
# 내 계좌로 모의 주문 · 실행 모드 · 비상 정지 (BV6)
# ═══════════════════════════════════════════════════════════════════════════════
# 계좌마다 Stage13 실행기 하나(`account_executors`). 기본은 SHADOW — 주문을 기록만 하고 보내지 않는다.
# 모든 경로가 ★소유 확인을 먼저★ 한다(남의 계좌 자격으로 클라이언트를 만들지 않는다). 누가 했는지는 토큰에서.
# LIVE 는 여기서 열지 않는다 — 실계좌 관문(BV1 `live_gate`)을 거치는 BV7 에서.

_LIVE_CLOSED = "실제 돈으로 주문하는 모드는 아직 열리지 않았어요. 운영자가 실계좌 관문을 연 뒤에 쓸 수 있어요."
_PAPER_ON_REAL = ("이 계좌는 실계좌로 연결돼 있어요. 가상으로 체결하는 모드(PAPER)는 모의투자 계좌에서만 써요. "
                  "모의투자 계좌를 따로 연결해 주세요.")


class AccountModeRequest(BaseModel):
    mode: str = Field(..., pattern="^(SHADOW|PAPER|LIVE)$")


class AccountKillRequest(BaseModel):
    reason: str = Field(..., min_length=4)
    #: 기본은 '그대로 둠'(hold) — 보유를 팔지 않고 새 주문과 미체결만 멈춘다.
    liquidation_mode: str = Field(default="hold", pattern="^(hold|gradual|immediate)$")


class AccountResolveRequest(BaseModel):
    notes: str = Field(default="")


def _executor(account_id: str):
    try:
        return get_account_executor(account_id)
    except ba.CredentialVaultUnavailable as e:
        raise HTTPException(503, str(e)) from None


@router.post("/{account_id}/orders")
def submit_account_order(account_id: str, req: SignalRequest, p: Principal = Depends(require_login)):
    _owned_or_404(p, account_id)
    who = observed_actor(p, None)
    return {**_executor(account_id).execute_signal(req.model_dump(), actor=who["actor"]), **who}


@router.get("/{account_id}/orders")
def list_account_orders(account_id: str, limit: int = Query(100, le=500), p: Principal = Depends(require_login)):
    _owned_or_404(p, account_id)
    orders = _executor(account_id).list_orders(limit=limit)
    return {"count": len(orders), "orders": orders}


@router.delete("/{account_id}/orders/{client_order_id}")
def cancel_account_order(account_id: str, client_order_id: str, p: Principal = Depends(require_login)):
    _owned_or_404(p, account_id)
    who = observed_actor(p, None)
    out = _executor(account_id).cancel_order(client_order_id, who["actor"])
    if out.get("status") == "not_found":
        raise HTTPException(404, "그 주문이 없어요.")
    return {**out, **who}


@router.get("/{account_id}/mode")
def get_account_mode(account_id: str, p: Principal = Depends(require_login)):
    _owned_or_404(p, account_id)
    st = _executor(account_id).state
    return {"mode": st.mode, "changed_by": st.changed_by,
            "last_mode_change": st.last_mode_change.isoformat() if st.last_mode_change else None}


@router.post("/{account_id}/mode")
def set_account_mode(account_id: str, req: AccountModeRequest, p: Principal = Depends(require_login)):
    acc = _owned_or_404(p, account_id)
    if req.mode == "LIVE":
        raise HTTPException(400, _LIVE_CLOSED)
    if req.mode == "PAPER" and not acc["is_paper"]:
        raise HTTPException(400, _PAPER_ON_REAL)
    who = observed_actor(p, None)
    return {**_executor(account_id).set_mode(req.mode, who["actor"]), **who}


@router.get("/{account_id}/kill-switch")
def get_account_kill(account_id: str, p: Principal = Depends(require_login)):
    _owned_or_404(p, account_id)
    ks = _executor(account_id).kill_switch
    # `active` 는 운영자 전역 정지도 센다(그때도 주문이 막힌다). `event` 는 이 계좌가 직접 건 정지만.
    return {"active": ks.is_active(), "event": ks.active_event()}


@router.post("/{account_id}/kill-switch/trigger")
def trigger_account_kill(account_id: str, req: AccountKillRequest, p: Principal = Depends(require_login)):
    _owned_or_404(p, account_id)
    ex = _executor(account_id)
    who = observed_actor(p, None)
    # 자산·드로다운은 싣지 않는다(None = "안 실었다") — 계좌별 자산 이력이 아직 없고, 잔고 조회 실패가 정지를 막으면 안 된다.
    out = ex.kill_switch.trigger(source=f"manual_{who['actor']}", reason=req.reason, equity=None, dd_pct=None,
                                 kis_client=ex.kis, liquidation_mode=req.liquidation_mode)
    return {**out, **who}


@router.post("/{account_id}/kill-switch/resolve")
def resolve_account_kill(account_id: str, req: AccountResolveRequest, p: Principal = Depends(require_login)):
    _owned_or_404(p, account_id)
    who = observed_actor(p, None)
    return {**_executor(account_id).kill_switch.resolve(who["actor"], req.notes), **who}


# ═══════════════════════════════════════════════════════════════════════════════
# 실계좌 준비 목록 (BV7) — 읽기만. 무엇이 왜 아직 안 됐는지 항목마다 말한다.
# ═══════════════════════════════════════════════════════════════════════════════
# ★LIVE 로 바꾸는 길은 아직 없다★ — 계좌별 대조 감시가 없어 마지막 항목이 늘 미통과이고, 전환 경로는 그 감시와 함께 만든다
# (사용자 결정 2026-10-09). 그래서 `ready` 는 지금 언제나 False 다.

_PRACTICE_ACCEPTED = "kis_paper_endpoint"   # client_realism.REASON_KIS_PAPER — 증권사 모의 서버가 받은 주문


def _last_check(account_id: str) -> dict | None:
    rows = AuditTrail(get_sync_engine(), account_id=account_id).query(event_type=EventType.BROKER_CHECK, limit=1)
    return rows[0] if rows else None


def _broker_accepted_paper_orders(owner: str) -> int:
    n = 0
    for acc in ba.list_masked(owner):
        if not acc["is_paper"]:
            continue
        for r in AuditTrail(get_sync_engine(), account_id=acc["account_id"]).query(event_type=EventType.ORDER_SUBMITTED):
            if (r.get("context") or {}).get("simulated_by") == _PRACTICE_ACCEPTED:
                n += 1
    return n


@router.get("/{account_id}/live-readiness")
def live_readiness(account_id: str, p: Principal = Depends(require_login)):
    acc = _owned_or_404(p, account_id)
    gate = live_gate(live_gate_store.current(), p.username)
    check = _last_check(account_id)
    practiced = _broker_accepted_paper_orders(p.username)

    if check is None:
        conn = (False, "이 계좌로 연결 확인을 한 적이 없어요. '연결 확인'을 먼저 해 주세요.")
    elif check["decision"] == "ok":
        conn = (True, "증권사가 이 계좌의 잔고 조회를 받아 줬어요.")
    elif check["decision"] == "practice":
        conn = (False, "마지막 확인이 연습용 모드라 증권사에 묻지 않았어요. 연습용 확인은 세지 않아요.")
    else:
        conn = (False, f"마지막 연결 확인이 실패했어요: {check.get('message') or '사유 없음'}")

    items = [
        {"key": "gate", "ok": gate["state"] == LIVE_ALLOWED,
         "reason": "운영자가 이 계정에 실계좌를 열었어요." if gate["state"] == LIVE_ALLOWED else gate["reason"]},
        {"key": "real_account", "ok": not acc["is_paper"],
         "reason": ("실계좌로 연결한 계좌예요." if not acc["is_paper"]
                    else "모의투자 계좌예요. 실계좌 주문은 실계좌로 연결한 계좌에서만 해요.")},
        {"key": "connection", "ok": conn[0], "reason": conn[1]},
        {"key": "paper_practice", "ok": practiced > 0,
         "reason": (f"내 모의투자 계좌에서 증권사 모의 서버가 받은 주문이 {practiced}건 있어요." if practiced
                    else "내 모의투자 계좌에서 증권사 모의 서버가 받은 주문이 아직 없어요. 연습용(mock) 주문은 세지 않아요.")},
        {"key": "reconciliation", "ok": False,
         "reason": "이 계좌를 증권사 잔고와 맞춰 보는 대조 감시가 아직 없어요. 그래서 실계좌 전환은 열지 않아요."},
    ]
    return {"account_id": account_id, "ready": all(i["ok"] for i in items), "items": items}
