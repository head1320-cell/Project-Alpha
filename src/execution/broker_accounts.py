"""사용자 증권 계좌 — ★자격을 암호화해 두고, 본인 것만 보이고, 비밀은 어디에도 찍지 않는다★ (BV3)
==============================================================================
계획: `/root/.claude/plans` BV3 · 사용자 결정(2026-10-08·09) "사용자마다 자기 증권 계좌를 연결하고
계좌마다 모의투자/실계좌를 고른다".

## 무엇을 하나

- `connect` — 앱 키·시크릿·계좌번호를 `BROKER_CRED_KEY`(Fernet 키)로 봉인해 `broker_accounts` 에 둔다.
- `list_masked` — 그 사용자의 계좌만, 끝 4자리로 가려서.
- `delete` — 그 사용자의 계좌만 지우고, 열려 있던 계좌 클라이언트도 내린다.
- `open_account` — 계좌 클라이언트를 만들 때(`kis_client.get_kis_client(account_id=…)`) 자격을 푼다.
  ★여기서는 소유자를 보지 않는다★ — 내부 통로다. 누가 이 계좌를 쓸 수 있는지는 경로(BV4)가 본다.

## ★금고 키가 없으면 저장하지 않는다★

키가 없거나 틀리면 `CredentialVaultUnavailable(사유)` 이고 아무 행도 쓰지 않는다. 평문으로 대신 두는 길은 없다.
키가 바뀌어 옛 암호문을 풀 수 없으면 그것도 사유와 함께 거절한다(빈 자격으로 삼키지 않는다).

## 하지 않는 것

키 교체(키 하나) · 연결 확인 기록(BV4·BV7) · 토큰 저장 · 실키로 KIS 왕복 — 이 환경에는 실키가 없어
★실제 증권사 연결은 관측하지 못했다★.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken

from src.database import BrokerAccount, session_scope
from src.execution.kis_client import evict_account_client

logger = logging.getLogger(__name__)

KEY_ENV = "BROKER_CRED_KEY"
_ACCOUNT_NO = re.compile(r"\d{8}")
_PRDT = re.compile(r"\d{2}")


class CredentialVaultUnavailable(RuntimeError):
    """금고 키가 없거나 틀려서 자격을 봉인하거나 풀 수 없다."""


class BrokerAccountNotFound(LookupError):
    """그런 계좌가 없다."""


@dataclass(frozen=True)
class AccountSecrets:
    """푼 자격. ★비밀 세 칸은 repr 에 나오지 않는다★(`KISCredentials` 와 같은 규칙)."""
    account_id: str
    owner_username: str
    is_paper: bool
    account_prdt: str
    app_key: str = field(repr=False)
    app_secret: str = field(repr=False)
    account_no: str = field(repr=False)


def _vault() -> Fernet:
    raw = os.getenv(KEY_ENV, "").strip()
    if not raw:
        raise CredentialVaultUnavailable(
            f"{KEY_ENV} 미설정 — 증권 계좌 자격을 암호화할 키가 없어 저장하지 않습니다. "
            "`.env.example` 의 한 줄로 키를 만들어 서버에 넣어 주세요.")
    try:
        return Fernet(raw.encode())
    except ValueError:
        # ★키 값은 사유에 적지 않는다★ — 그것도 비밀이다.
        raise CredentialVaultUnavailable(
            f"{KEY_ENV} 형식이 맞지 않습니다(Fernet 키 — 32바이트를 url-safe base64 로). "
            "자격을 저장하지 않았습니다.") from None


def _masked(row: BrokerAccount) -> dict:
    return {
        "account_id": row.account_id,
        "label": row.label,
        "is_paper": row.is_paper,
        "account_prdt": row.account_prdt,
        "app_key_last4": row.app_key_last4,
        "account_no_masked": "****" + row.account_no_last4,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def connect(owner: str, *, label: str, app_key: str, app_secret: str, account_no: str,
            is_paper: bool, account_prdt: str = "01") -> dict:
    """계좌를 연결한다. 틀린 입력은 `ValueError(사유)` — 아무것도 쓰지 않는다. 가린 행을 돌려준다."""
    label = (label or "").strip()
    app_key = (app_key or "").strip()
    app_secret = (app_secret or "").strip()
    account_no = (account_no or "").strip()
    account_prdt = (account_prdt or "").strip()
    if not label or len(label) > 64:
        raise ValueError("계좌 이름은 1~64자로 넣어 주세요.")
    if not app_key or not app_secret:
        raise ValueError("앱 키와 앱 시크릿을 모두 넣어 주세요.")
    if not _ACCOUNT_NO.fullmatch(account_no):
        raise ValueError("계좌번호는 앞 8자리 숫자만 넣어 주세요.")
    if not _PRDT.fullmatch(account_prdt):
        raise ValueError("상품 코드는 숫자 2자리예요(위탁 계좌는 01).")
    if not isinstance(is_paper, bool):
        # 돈이 걸린 선택이다 — "false" 같은 글자를 참·거짓으로 짐작하지 않는다.
        raise ValueError("모의투자 계좌인지 실계좌인지 정해 주세요.")

    vault = _vault()
    seal = lambda v: vault.encrypt(v.encode()).decode()  # noqa: E731
    account_id = "ba_" + secrets.token_hex(8)
    with session_scope() as s:
        row = BrokerAccount(
            account_id=account_id, owner_username=owner, label=label, is_paper=is_paper,
            account_prdt=account_prdt, app_key_enc=seal(app_key), app_secret_enc=seal(app_secret),
            account_no_enc=seal(account_no), app_key_last4=app_key[-4:],
            account_no_last4=account_no[-4:])
        s.add(row)
        s.flush()
        s.refresh(row)
        out = _masked(row)
    logger.info("증권 계좌 연결: %s (%s, %s)", account_id, owner, "모의투자" if is_paper else "실계좌")
    return out


def list_masked(owner: str) -> list[dict]:
    """그 사용자의 계좌만, 가려서. 비밀은 끝 4자리 말고는 없다."""
    with session_scope() as s:
        rows = (s.query(BrokerAccount).filter_by(owner_username=owner)
                .order_by(BrokerAccount.created_at, BrokerAccount.account_id).all())
        return [_masked(r) for r in rows]


def delete(owner: str, account_id: str) -> bool:
    """그 사용자의 계좌면 지우고 True. 남의 것이거나 없으면 False — 무엇도 지우지 않는다."""
    with session_scope() as s:
        row = s.query(BrokerAccount).filter_by(account_id=account_id, owner_username=owner).first()
        if row is None:
            return False
        s.delete(row)
    from src.execution.account_executors import evict_account_executor  # 순환 import 를 피해 여기서

    evict_account_client(account_id)
    evict_account_executor(account_id)
    logger.info("증권 계좌 삭제: %s (%s)", account_id, owner)
    return True


def open_account(account_id: str) -> AccountSecrets:
    """자격을 푼다. 없으면 `BrokerAccountNotFound` · 풀 수 없으면 `CredentialVaultUnavailable`."""
    with session_scope() as s:
        row = s.query(BrokerAccount).filter_by(account_id=account_id).first()
        if row is None:
            raise BrokerAccountNotFound(f"증권 계좌 {account_id} 가 없습니다.")
        sealed = (row.app_key_enc, row.app_secret_enc, row.account_no_enc)
        meta = (row.account_id, row.owner_username, row.is_paper, row.account_prdt)
    vault = _vault()
    try:
        app_key, app_secret, account_no = (vault.decrypt(v.encode()).decode() for v in sealed)
    except InvalidToken:
        raise CredentialVaultUnavailable(
            f"저장된 자격을 풀 수 없습니다 — {KEY_ENV} 가 연결할 때의 키와 다를 수 있어요. "
            "키를 되돌리거나 계좌를 다시 연결해 주세요.") from None
    return AccountSecrets(*meta, app_key=app_key, app_secret=app_secret, account_no=account_no)
