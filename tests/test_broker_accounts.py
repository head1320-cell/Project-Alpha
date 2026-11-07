"""BV3 — ★사용자마다 자기 증권 계좌를 연결한다★: 자격 금고 · 계좌 표 · 계좌별 클라이언트.

사용자 결정(2026-10-08·09): 사용자마다 자기 KIS 계좌를 연결하고 계좌마다 모의투자/실계좌를 고른다.
BV0 감사: 암호화 도구 0 · 계정별 자격 표 0 · 클라이언트는 `.env` 하나뿐.

여기서 고정하는 것:
  ① 금고 키(`BROKER_CRED_KEY`)가 없거나 틀리면 ★저장하지 않는다★(평문 대체 0) · 짝: 키가 있으면 저장한다
  ② 저장된 칸은 암호문이다 · 짝: 같은 키로 풀면 원래 값 · 다른 키로는 사유와 함께 거절
  ③ 목록은 가려서, 본인 것만 · 짝: 본인은 자기 계좌를 본다
  ④ 지우기는 본인 것만 · 지우면 계좌 클라이언트도 사라진다
  ⑤ 계좌 클라이언트 등록부 — 같은 계좌 = 같은 인스턴스 · 다른 계좌 = 다른 · 서버 클라이언트와 섞이지 않는다
  ⑥ 운영 모드에서 계좌 클라이언트는 그 계좌의 모의/실계좌 주소로 간다(계좌마다)
  ⑦ 로그·예외·repr 에 비밀이 없다
  ⑧ 입력 검사 — 틀린 값은 사유와 함께 거절하고 아무것도 쓰지 않는다

★실제 증권사 연결은 여기서 관측하지 않는다★ — 이 환경에는 실키가 없다. `KISClient` 생성은 토큰을
받지 않으므로(네트워크 0) 주소·자격 값까지만 확인한다.
"""
from __future__ import annotations

import logging
import os
import tempfile

import pytest
from cryptography.fernet import Fernet

import src.database as dbmod
import src.execution.kis_client as kc
from src.execution import broker_accounts as ba

APP_KEY = "PSappkey-ALICE-0123456789abcdef"
APP_SECRET = "secret-ALICE-zyxwvutsrqponmlkjihgfedcba9876543210"
ACCOUNT_NO = "50123456"
SECRETS = (APP_KEY, APP_SECRET, ACCOUNT_NO)


@pytest.fixture()
def db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("BROKER_CRED_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(kc, "_kis_singleton", None, raising=False)
    monkeypatch.setattr(kc, "_account_clients", {}, raising=False)
    dbmod.reset_session()
    dbmod.init_db()
    dbmod.create_user("alice", "alice-pw")
    dbmod.create_user("bob", "bob-pw")
    yield
    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def _connect(owner="alice", **kw):
    args = dict(label="내 모의 계좌", app_key=APP_KEY, app_secret=APP_SECRET,
                account_no=ACCOUNT_NO, is_paper=True)
    return ba.connect(owner, **{**args, **kw})


def _rows():
    with dbmod.session_scope() as s:
        return [(r.account_id, r.owner_username, r.app_key_enc, r.app_secret_enc, r.account_no_enc)
                for r in s.query(dbmod.BrokerAccount).all()]


# ── ① 금고 키가 없으면 저장하지 않는다 ─────────────────────────────────────

def test_without_a_vault_key_nothing_is_stored(db, monkeypatch):
    monkeypatch.delenv("BROKER_CRED_KEY", raising=False)
    with pytest.raises(ba.CredentialVaultUnavailable) as err:
        _connect()
    assert "BROKER_CRED_KEY" in str(err.value)
    assert _rows() == [], "키가 없는데 무언가를 저장했다(평문 대체?)"


def test_with_a_vault_key_the_account_is_stored(db):
    """★짝★ — 항상-거절 구현을 배제한다."""
    out = _connect()
    assert out["account_id"].startswith("ba_")
    assert len(_rows()) == 1


@pytest.mark.parametrize("bad", ["not-a-fernet-key", "x" * 44, "   "])
def test_a_malformed_vault_key_is_refused_with_a_reason(db, monkeypatch, bad):
    monkeypatch.setenv("BROKER_CRED_KEY", bad)
    with pytest.raises(ba.CredentialVaultUnavailable) as err:
        _connect()
    assert "BROKER_CRED_KEY" in str(err.value)
    assert bad.strip() == "" or bad not in str(err.value), "사유에 키 값을 그대로 적었다"
    assert _rows() == []


# ── ② 저장된 칸은 암호문 ───────────────────────────────────────────────────

def test_stored_fields_are_ciphertext(db):
    _connect()
    (_, _, key_enc, secret_enc, acct_enc), = _rows()
    for stored, plain in ((key_enc, APP_KEY), (secret_enc, APP_SECRET), (acct_enc, ACCOUNT_NO)):
        assert stored != plain
        assert plain not in stored


def test_opening_with_the_same_key_gives_back_the_values(db):
    """★짝★ — 저장값이 쓰레기가 아니라 같은 키로 되돌릴 수 있는 암호문이다."""
    acc = _connect()
    opened = ba.open_account(acc["account_id"])
    assert (opened.app_key, opened.app_secret, opened.account_no) == SECRETS
    assert opened.is_paper is True and opened.account_prdt == "01"
    assert opened.owner_username == "alice"


def test_opening_with_a_different_key_is_refused_with_a_reason(db, monkeypatch):
    acc = _connect()
    monkeypatch.setenv("BROKER_CRED_KEY", Fernet.generate_key().decode())
    with pytest.raises(ba.CredentialVaultUnavailable) as err:
        ba.open_account(acc["account_id"])
    assert "키" in str(err.value)
    for secret in SECRETS:
        assert secret not in str(err.value)


def test_opening_a_missing_account_says_not_found(db):
    with pytest.raises(ba.BrokerAccountNotFound):
        ba.open_account("ba_does_not_exist")


# ── ③ 가린 목록 · 본인 것만 ────────────────────────────────────────────────

def test_the_list_hides_the_secrets_but_shows_the_last_four(db):
    _connect()
    rows = ba.list_masked("alice")
    assert len(rows) == 1
    text = repr(rows)
    for secret in SECRETS:
        assert secret not in text, f"목록에 {secret} 가 보인다"
    assert rows[0]["account_no_masked"] == "****" + ACCOUNT_NO[-4:]
    assert rows[0]["app_key_last4"] == APP_KEY[-4:]
    assert rows[0]["is_paper"] is True and rows[0]["label"] == "내 모의 계좌"
    # ★칸은 이것뿐이다★ — 암호문도 밖으로 나가지 않는다(키가 새면 암호문이 곧 평문이다).
    assert set(rows[0]) == {"account_id", "label", "is_paper", "account_prdt",
                            "app_key_last4", "account_no_masked", "created_at"}


def test_another_user_does_not_see_the_account(db):
    _connect("alice")
    assert ba.list_masked("bob") == []


def test_each_user_sees_only_their_own(db):
    """★짝★ — 언제나 빈 목록을 주는 구현을 배제한다."""
    a = _connect("alice")
    b = _connect("bob", label="밥의 계좌")
    assert [r["account_id"] for r in ba.list_masked("alice")] == [a["account_id"]]
    assert [r["account_id"] for r in ba.list_masked("bob")] == [b["account_id"]]


# ── ④ 지우기 — 본인 것만, 클라이언트도 함께 ────────────────────────────────

def test_another_user_cannot_delete_the_account(db):
    acc = _connect("alice")
    assert ba.delete("bob", acc["account_id"]) is False
    assert len(_rows()) == 1


def test_the_owner_deletes_it_and_its_client_goes_with_it(db):
    """★짝★ — 언제나 False 인 구현을 배제한다."""
    acc = _connect("alice")
    kc.get_kis_client(account_id=acc["account_id"])
    assert acc["account_id"] in kc._account_clients
    assert ba.delete("alice", acc["account_id"]) is True
    assert _rows() == []
    assert acc["account_id"] not in kc._account_clients, "지운 계좌의 클라이언트가 남았다"
    with pytest.raises(ba.BrokerAccountNotFound):
        kc.get_kis_client(account_id=acc["account_id"])


def test_deleting_an_unknown_account_is_false(db):
    assert ba.delete("alice", "ba_nope") is False


# ── ⑤ 계좌 클라이언트 등록부 ──────────────────────────────────────────────

def test_the_same_account_gets_the_same_client(db):
    acc = _connect()
    assert kc.get_kis_client(account_id=acc["account_id"]) is kc.get_kis_client(account_id=acc["account_id"])


def test_different_accounts_get_different_clients(db):
    """★짝★ — 모든 계좌에 하나를 주는 구현을 배제한다(mock 잔고가 계좌끼리 섞이면 안 된다)."""
    a = _connect("alice")
    b = _connect("bob")
    ca = kc.get_kis_client(account_id=a["account_id"])
    cb = kc.get_kis_client(account_id=b["account_id"])
    assert ca is not cb


def test_the_server_client_is_not_an_account_client(db):
    acc = _connect()
    assert kc.get_kis_client() is not kc.get_kis_client(account_id=acc["account_id"])


def test_reloading_the_server_client_keeps_account_clients(db):
    acc = _connect()
    before = kc.get_kis_client(account_id=acc["account_id"])
    kc.get_kis_client(force_reload=True)
    assert kc.get_kis_client(account_id=acc["account_id"]) is before


def test_force_reload_with_an_account_is_refused(db):
    """조용히 무시하지 않는다 — 계좌 클라이언트는 `evict_account_client` 로 비운다."""
    acc = _connect()
    with pytest.raises(ValueError):
        kc.get_kis_client(force_reload=True, account_id=acc["account_id"])


# ── ⑥ 운영 모드 — 계좌마다 모의/실계좌 ─────────────────────────────────────

def test_in_production_each_account_goes_to_its_own_environment(db, monkeypatch):
    paper = _connect(is_paper=True)
    real = _connect(label="내 실계좌", is_paper=False, account_no="70123456")
    monkeypatch.setenv("KIS_USE_MOCK", "0")

    cp = kc.get_kis_client(account_id=paper["account_id"])
    cr = kc.get_kis_client(account_id=real["account_id"])
    assert type(cp).__name__ == "KISClient" and type(cr).__name__ == "KISClient"
    assert cp.base_url == kc.KIS_BASE_URL_PAPER and cp.creds.is_paper is True
    assert cr.base_url == kc.KIS_BASE_URL_REAL and cr.creds.is_paper is False
    assert (cp.creds.app_key, cp.creds.app_secret, cp.creds.account_no) == SECRETS
    assert cr.creds.account_no == "70123456"


def test_in_production_the_server_env_does_not_leak_into_an_account(db, monkeypatch):
    """계좌 클라이언트는 `.env` 의 운영자 계좌가 아니라 금고의 값을 쓴다."""
    acc = _connect()
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.setenv("KIS_APP_KEY", "operator-key")
    monkeypatch.setenv("KIS_APP_SECRET", "operator-secret")
    monkeypatch.setenv("KIS_ACCOUNT_NO", "99999999")
    monkeypatch.setenv("KIS_IS_PAPER", "0")
    c = kc.get_kis_client(account_id=acc["account_id"])
    assert c.creds.app_key == APP_KEY and c.creds.account_no == ACCOUNT_NO
    assert c.base_url == kc.KIS_BASE_URL_PAPER


# ── ⑦ 비밀이 새지 않는다 ───────────────────────────────────────────────────

def test_no_secret_reaches_the_logs(db, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    acc = _connect()
    ba.open_account(acc["account_id"])
    ba.list_masked("alice")
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    kc.get_kis_client(account_id=acc["account_id"])
    ba.delete("alice", acc["account_id"])
    monkeypatch.setenv("BROKER_CRED_KEY", "broken")
    with pytest.raises(ba.CredentialVaultUnavailable):
        _connect()
    assert caplog.records, "로그를 하나도 잡지 못했다 — 검사가 공허하다"
    text = "\n".join(r.getMessage() for r in caplog.records)
    for secret in SECRETS:
        assert secret not in text, f"로그에 {secret} 가 보인다"


def test_the_opened_secrets_hide_themselves_in_repr(db):
    acc = _connect()
    opened = ba.open_account(acc["account_id"])
    text = repr(opened) + str(opened)
    for secret in SECRETS:
        assert secret not in text
    # ★짝★ — 빈 repr 이 아니다.
    assert acc["account_id"] in text and "is_paper=True" in text


# ── ⑧ 입력 검사 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    dict(account_no="5012345"),          # 7자리
    dict(account_no="5012345a"),         # 문자 섞임
    dict(account_no="50123456-01"),      # 상품 코드까지 붙임
    dict(app_secret=""),
    dict(app_key="   "),
    dict(label=""),
    dict(label="가" * 65),
    dict(account_prdt="1"),
    dict(is_paper="false"),              # 문자열은 모의/실계좌 선택이 아니다
])
def test_bad_input_is_refused_and_nothing_is_written(db, bad):
    with pytest.raises(ValueError) as err:
        _connect(**bad)
    assert str(err.value).strip(), "사유 없는 거절"
    assert _rows() == []


def test_good_input_with_surrounding_spaces_is_accepted(db):
    """★짝★ — 언제나 거절하는 검사를 배제한다. 앞뒤 공백은 지우고 받는다."""
    out = _connect(account_no=" 50123456 ", label=" 내 계좌 ")
    assert out["label"] == "내 계좌"
    assert ba.open_account(out["account_id"]).account_no == ACCOUNT_NO
