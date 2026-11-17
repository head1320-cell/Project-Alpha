"""내 증권 계좌 — 목록 · 연결 · 삭제 · 연결 확인 (BV4)
==============================================================================
계획: BV4 · 사용자 결정(2026-10-08·09) "사용자마다 자기 KIS 계좌를 연결하고 계좌마다 모의투자/실계좌를 고른다".
저장·암호화·가림은 `src/execution/broker_accounts.py`(BV3)가 한다. 이 파일은 그 앞의 문이다.

## ★소유자는 토큰에서만 온다★

본문에 `owner` 같은 칸을 넣어도 쓰지 않는다. 남의 계좌는 ★404★ — 없는 계좌와 같은 답이다(남의 계좌 id 가 있는지조차
드러내지 않는다). 관리자에게도 우회는 없다(관리자 보기는 BU9·BV6 에서 따로 만든다).

## ★연결 확인은 '확인한 만큼만' 말한다★

- 합성 데이터 모드(`KIS_USE_MOCK=1`)에서는 증권사에 묻지 않는다 → `practice` — '연결됨' 이라 말하지 않는다.
- 운영에서는 잔고 조회 한 번 → 받아 주면 `ok`, 증권사·네트워크 실패면 `failed` + 사람 말 사유 + 원문(비밀은 가림).
- 그 밖 예외(프로그램 오류)는 잡지 않는다 — '연결 실패' 로 꾸미지 않는다.
- 결과(상태·사람 말 사유만)는 감사에 남긴다 — 실계좌 준비 목록이 읽는다(BV7). 잔고 숫자는 싣지 않는다(잔고는 `/balance` — BV9).
"""
from __future__ import annotations

import datetime as dt

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from src.api import intraday_context, intraday_routes
from src.api.auth import require_login
from src.api.stage13_routes import SignalRequest
from src.data.mock_gate import mock_allowed
from src.database import get_sync_engine
from src.domain.auth_identity import Principal, observed_actor
from src.domain.kis_failure import KIND_BLOCKED, KIND_BUSINESS, KIND_HTTP_STATUS, KIND_TOKEN, KIND_TRANSPORT
from src.domain.live_gate import LIVE_ALLOWED, live_gate
from src.execution import broker_accounts as ba
from src.execution import live_gate_store, rule_monitor, rule_runner
from src.execution.account_executors import get_account_executor
from src.execution.audit_trail import AuditTrail, EventType
from src.execution.kis_client import KISCallError, get_kis_client

router = APIRouter(prefix="/api/v1/broker-accounts", tags=["broker-accounts"])

_NOT_FOUND = "그 계좌가 없습니다."

#: 실패 종류 → 사람 말. 원문은 `detail` 에 따로 싣는다.
_REASON_BY_KIND = {
    KIND_TOKEN: "증권사가 토큰 발급을 거부했습니다. 앱 키·시크릿이 올바른지, 1분 이내에 재요청하지 않았는지 확인하십시오.",
    KIND_BUSINESS: "증권사가 요청을 거절했습니다. 계좌번호와 상품 코드, 모의투자/실계좌 선택이 맞는지 확인하십시오.",
    KIND_TRANSPORT: "증권사 연결 실패. 잠시 후 다시 시도하십시오.",
    KIND_HTTP_STATUS: "증권사 연결 실패. 잠시 후 다시 시도하십시오.",
    KIND_BLOCKED: "연속 실패로 이 계좌의 호출을 일시 중단했습니다. 잠시 후 다시 시도하십시오.",
}
_REASON_OTHER = "증권사 확인에 실패했습니다. 아래 원래 사유를 확인하십시오."


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
                "reason": "합성 데이터 모드라 증권사에 묻지 않았습니다. 키가 맞는지는 미상입니다."})
    _, failed = _ask_balance(client, secrets)
    if failed:
        return _record_check(account_id, p.username, {**out, **failed})
    return _record_check(account_id, p.username, {**out, "state": "ok",
            "reason": "증권사가 이 키와 계좌의 잔고 조회를 수락했습니다."})


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

_LIVE_CLOSED = "실제 자금으로 주문하는 모드는 아직 개방되지 않았습니다. 운영자가 실계좌 관문을 개방한 뒤 사용할 수 있습니다."
_PAPER_ON_REAL = ("이 계좌는 실계좌로 연결돼 있습니다. 가상 체결 모드(PAPER)는 모의투자 계좌에서만 사용합니다. "
                  "모의투자 계좌를 별도로 연결하십시오.")


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
        raise HTTPException(404, "그 주문이 없습니다.")
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
# 규칙 가동 (W5b) — 기록 전용 · 재생. 분봉 백테스트로 돌려 본 설정을 이 계좌에서 봉 단위로 다시 흘린다.
# ═══════════════════════════════════════════════════════════════════════════════
# ★증권사로는 아무것도 나가지 않는다★ — 가동기(`rule_runner`)는 기록 전용 모드에서만 열리고, 신호는 이 계좌의 실행기 한 길로만 간다.
# 설정은 본문으로 받지 않는다: 시행 열쇠와 날짜뿐이다(가동되는 것은 분봉 백테스트로 세어진 설정뿐 — 다른 규칙을 끼울 칸이 없다).
# 소유 확인은 ★의존성★이다 — 본문 · 경로 값의 검사보다 먼저 돈다. 남의 계좌는 본문이 틀려도 404 다(422 로 계좌가 있음을 흘리지 않는다).

_NO_RUN = "그 가동이 없습니다."
_DAY_NOT_LOADED = "그 날짜의 분봉이 적재돼 있지 않습니다."


class RuleRunStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trial_key: str
    day: dt.date


class RuleRunAdvance(BaseModel):
    #: 민 봉의 수. 없으면 끝까지. 글자 · 참거짓 · 0 은 받지 않는다.
    bars: StrictInt | None = Field(default=None, ge=1)


def _own_account(account_id: str, p: Principal = Depends(require_login)) -> dict:
    return _owned_or_404(p, account_id)


def _run_refused(err: rule_runner.RunRefused) -> HTTPException:
    if err.code == "not_found":
        return HTTPException(404, _NO_RUN)
    return HTTPException(503 if err.code == "store_unavailable" else 400,
                         detail={"code": err.code, "reason": err.message, **err.extra})


def _run_context(account_id: str) -> dict:
    """가동을 보는 화면이 함께 읽어야 하는 것 — 지금 모드 · 비상 정지 · 상한 · 모의 모드인지."""
    ex = _executor(account_id)
    return {"mode": ex.state.mode, "kill_switch": ex.kill_switch.is_active(),
            "limits": {"runs": rule_runner.MAX_RUNS_PER_ACCOUNT, "tickers": rule_runner.MAX_RUN_TICKERS,
                       "gap_minutes": rule_runner.GAP_MINUTES},
            "gate": {"mock": mock_allowed()}}


def _day_of(username: str, tickers: list[str], rule, day: dt.date):
    """그 종목들의 하루의 봉 — ★분봉 백테스트와 같은 준비★(같은 함수 · 같은 종목 마스터 · 같은 장 운영 규칙 · 같은 전일 값 판정 ·
    같은 규칙 맥락). 규칙이 하루 유형을 쓰면 그 사용자의 모형을 ★봉을 읽기 전에★ 읽는다 — 학습이 그날 전에 끝나지 않았으면
    사유와 함께 거절한다(`intraday_context`).

    → `(Day, session)` · 그 날짜가 적재돼 있지 않으면 `None`. 규칙이 시장 국면을 쓰면 그날 시가 전에 알던 확률을 싣는다 —
    그날 확률을 모르면(지수 일봉이 아직 없거나 적합 창이 덜 찼으면) 사유와 함께 거절한다(가동하지 않는다)."""
    feed = intraday_routes.minute_feed
    planned = feed.plan(day, day).dates
    loaded = intraday_context.load(username, rule, day, end=day, dates=planned)
    if not planned:
        return None
    session = intraday_routes.session_rules()
    days = feed.build_days(tickers, day, day, rules=session, master=intraday_routes.master_lookup(),
                           need_prev=intraday_routes._needs_prev(rule))
    days = intraday_context.attach(days, loaded)
    return (days[0], session) if days else None


def _monitor_day(username: str, tickers: list[str], rule, day: str):
    """관제가 그날의 백테스트를 다시 지을 때 — 맥락을 읽지 못한 사유는 '적재되지 않음'이 아니라 그 사유로 넘긴다."""
    try:
        return _day_of(username, tickers, rule, dt.date.fromisoformat(day))
    except HTTPException as err:
        detail = err.detail if isinstance(err.detail, dict) else {}
        raise rule_monitor.DayUnavailable(str(detail.get("reason") or err.detail)) from None


def _day_for_run(username: str, trial_key: str, day: dt.date):
    """가동할 하루의 봉 — 시행의 종목 · 시행의 규칙으로 짓는다. 적재돼 있지 않으면 사유와 함께 거절."""
    setting = rule_runner.setting_of(username, trial_key)
    built = _day_of(username, list(setting.tickers), setting.rule, day)
    if built is None:
        raise HTTPException(400, detail={"code": "not_loaded", "reason": _DAY_NOT_LOADED})
    return built


@router.get("/{account_id}/rule-runs")
def list_rule_runs(account_id: str, limit: int = Query(50, ge=1, le=200), _acc: dict = Depends(_own_account),
                   p: Principal = Depends(require_login)):
    ctx = _run_context(account_id)
    try:
        rows = rule_runner.runs(p.username, account_id, limit)
    except rule_runner.RunRefused as err:
        if err.code != "store_unavailable":
            raise _run_refused(err) from None
        return {**ctx, "available": False, "reason": err.message, "runs": []}       # 못 읽음은 빈 목록이 아니다
    return {**ctx, "available": True, "reason": None, "runs": rows}


@router.post("/{account_id}/rule-runs", status_code=201)
def start_rule_run(account_id: str, req: RuleRunStart, _acc: dict = Depends(_own_account), p: Principal = Depends(require_login)):
    try:
        day, session = _day_for_run(p.username, req.trial_key, req.day)
        run = rule_runner.start(p.username, account_id, req.trial_key, day, session=session)
    except rule_runner.RunRefused as err:
        raise _run_refused(err) from None
    return {**_run_context(account_id), "run": run}


@router.get("/{account_id}/rule-runs/{run_id}")
def get_rule_run(account_id: str, run_id: int, _acc: dict = Depends(_own_account), p: Principal = Depends(require_login)):
    try:
        run = rule_runner.get(p.username, account_id, run_id)
    except rule_runner.RunRefused as err:
        raise _run_refused(err) from None
    return {**_run_context(account_id), "run": run}


@router.get("/{account_id}/rule-runs/{run_id}/monitor")
def monitor_rule_run(account_id: str, run_id: int, _acc: dict = Depends(_own_account), p: Principal = Depends(require_login)):
    """가동 하나의 관제 — ★읽기만★(주문 · 체결 · 실현손익 · 한도까지 남은 폭 · 비상 정지 · 그날의 백테스트와 같은지)."""
    ctx = _run_context(account_id)
    try:
        seen = rule_monitor.view(p.username, account_id, run_id, master=intraday_routes.master_lookup(),
                                 day_of=lambda tickers, rule, day: _monitor_day(p.username, tickers, rule, day))
    except rule_runner.RunRefused as err:
        raise _run_refused(err) from None
    return {**ctx, **seen}


@router.post("/{account_id}/rule-runs/{run_id}/advance")
def advance_rule_run(account_id: str, run_id: int, req: RuleRunAdvance, _acc: dict = Depends(_own_account),
                     p: Principal = Depends(require_login)):
    try:
        run = rule_runner.advance(p.username, account_id, run_id, req.bars)
    except rule_runner.RunRefused as err:
        raise _run_refused(err) from None
    return {**_run_context(account_id), "run": run}


@router.post("/{account_id}/rule-runs/{run_id}/stop")
def stop_rule_run(account_id: str, run_id: int, _acc: dict = Depends(_own_account), p: Principal = Depends(require_login)):
    try:
        run = rule_runner.stop(p.username, account_id, run_id)
    except rule_runner.RunRefused as err:
        raise _run_refused(err) from None
    return {**_run_context(account_id), "run": run}


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
        conn = (False, "이 계좌로 연결 확인을 한 적이 없습니다. '연결 확인'을 먼저 하십시오.")
    elif check["decision"] == "ok":
        conn = (True, "증권사가 이 계좌의 잔고 조회를 수락했습니다.")
    elif check["decision"] == "practice":
        conn = (False, "마지막 확인이 합성 데이터 모드라 증권사에 묻지 않았습니다. 합성 확인은 세지 않습니다.")
    else:
        conn = (False, f"마지막 연결 확인이 실패했습니다: {check.get('message') or '사유 없음'}")

    items = [
        {"key": "gate", "ok": gate["state"] == LIVE_ALLOWED,
         "reason": "운영자가 이 계정에 실계좌를 열었습니다." if gate["state"] == LIVE_ALLOWED else gate["reason"]},
        {"key": "real_account", "ok": not acc["is_paper"],
         "reason": ("실계좌로 연결한 계좌입니다." if not acc["is_paper"]
                    else "모의투자 계좌입니다. 실계좌 주문은 실계좌로 연결한 계좌에서만 합니다.")},
        {"key": "connection", "ok": conn[0], "reason": conn[1]},
        {"key": "paper_practice", "ok": practiced > 0,
         "reason": (f"내 모의투자 계좌에서 증권사 모의 서버가 받은 주문이 {practiced}건 있습니다." if practiced
                    else "내 모의투자 계좌에서 증권사 모의 서버가 접수한 주문이 아직 없습니다. 합성(mock) 주문은 집계하지 않습니다.")},
        {"key": "reconciliation", "ok": False,
         "reason": "이 계좌를 증권사 잔고와 맞춰 보는 대조 감시가 아직 없습니다. 그래서 실계좌 전환은 열지 않습니다."},
    ]
    return {"account_id": account_id, "ready": all(i["ok"] for i in items), "items": items}
