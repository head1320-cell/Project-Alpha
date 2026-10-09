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
- 기록은 남기지 않는다(준비 목록이 생기는 BV7 에서). 잔고 숫자도 싣지 않는다(BV9).
"""
from __future__ import annotations

import datetime as dt

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StrictBool

from src.api.auth import require_login
from src.data.mock_gate import mock_allowed
from src.domain.auth_identity import Principal
from src.domain.kis_failure import KIND_BLOCKED, KIND_BUSINESS, KIND_HTTP_STATUS, KIND_TOKEN, KIND_TRANSPORT
from src.execution import broker_accounts as ba
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


@router.post("/{account_id}/check")
def check_account(account_id: str, p: Principal = Depends(require_login)):
    _owned_or_404(p, account_id)   # ★소유 확인이 먼저★ — 남의 자격은 풀지도 않는다
    out = {"account_id": account_id, "checked_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    try:
        client = get_kis_client(account_id=account_id)
        acct = ba.open_account(account_id)
    except ba.CredentialVaultUnavailable as e:
        raise HTTPException(503, str(e)) from None
    if mock_allowed():
        return {**out, "state": "practice",
                "reason": "연습용 모드라 증권사에 묻지 않았어요. 키가 맞는지는 아직 몰라요."}
    secrets = (acct.app_key, acct.app_secret, acct.account_no)
    try:
        client.get_balance()
    except KISCallError as e:
        return {**out, "state": "failed", "reason": _REASON_BY_KIND.get(e.kind, _REASON_OTHER),
                "detail": _redact(str(e), secrets)}
    except requests.RequestException as e:
        # `_fetch_token` 은 `requests` 예외를 감싸지 않는다(실측) — 네트워크 실패로 읽는다.
        return {**out, "state": "failed", "reason": _REASON_BY_KIND[KIND_TRANSPORT],
                "detail": _redact(str(e), secrets)}
    return {**out, "state": "ok", "reason": "증권사가 이 키와 계좌로 잔고 조회를 받아 줬어요."}
