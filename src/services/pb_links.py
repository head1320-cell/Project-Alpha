"""고객 주소 · 고객 세션 · 고객 AI (CF 3부 PB6) — ★유통 관문 뒤★
==============================================================================
사용자 결정(2026-10-23): 고객 접속은 '비밀 주소 + PIN'(만료·언제든 끄기, 고객 계정 없음) · 고객 화면은 관문 뒤.
관문 판정은 경로가 맨 앞에서 한다(`src/api/distribution_surface.py::require_distribution_open`) — 이 모듈은 그 뒤의 일이다.

## 주소 — ★토큰은 한 번만, 해시만★

토큰은 `secrets.token_urlsafe(32)`(256비트) · sha256 해시만 저장한다. 평문은 만들 때 PB 에게 한 번 돌려주고 끝 — 주소의
조각(`/c#t=…`)으로만 건너가 서버 로그·리퍼러에 남지 않는다. PIN 은 6자리 숫자(같은 숫자·차례대로·되풀이 거절) · bcrypt 해시.
기간은 7·30·90일. 그 고객의 한 장만 · 보관한 고객은 못 만든다 · 만들면 그 한 장은 '보여 준 것'(PB4 — 지울 수 없다).

## 고객이 여는 차례 — ★잠긴 주소는 PIN 이 맞는지 드러내지 않는다★

토큰을 모르면 → 틀린 PIN 과 ★같은 말★(401) · 철회·만료·보관 → 410 · 잠김 → 423(PIN 을 보지도 세지도 않는다) ·
PIN 이 틀리면 하나 세고 401(5번째면 잠그고 그 요청이 바로 423) · 맞으면 센 것을 비우고 30분 세션. 잠김을 PIN 보다 먼저 보는 까닭: 잠긴 뒤에도
PIN 을 대 보게 하면 '맞으면 423, 틀리면 401' 로 PIN 을 계속 맞혀 볼 수 있다.

## 세션 — ★주소에 묶이고, 요청마다 주소 상태를 다시 본다★

세션은 서명한 짧은 표(`{주소, 만료}` + HMAC — 키는 `auth.derived_key(SESSION_PURPOSE)`, 부르는 쪽이 넘긴다). 서버에 세션 표가 없다 —
대신 ★매 요청 주소의 지금 상태★를 본다: 철회·만료·보관이면 410, 잠기면 423. 그래서 PB 가 철회하면 살아 있는 세션도 즉시 막힌다
(관문은 경로가 매 요청 본다 — 관문을 닫아도 즉시 막힌다).

## 고객 AI — 주소마다 시간당 10번

근거는 그 주소가 지금 보여 주는 한 장뿐(PB4 `ask_sheet` — 고객용 고정 문장). 주소마다 시간당 10번(캐시 적중도 센다 — 보수 쪽).
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import secrets
import time

from src.database import PbClient, PbClientLink, PbClientSheet, hash_password, session_scope, verify_password
from src.services import pb_clients as pc
from src.services.canvas_assist.limiter import HourlyLimiter

PIN_LEN = 6
DAYS = (7, 30, 90)
MAX_FAILURES = 5
SESSION_TTL = dt.timedelta(minutes=30)
ASK_PER_HOUR = 10
SESSION_PURPOSE = "pb-share-session"

DENIED = "주소나 PIN 이 맞지 않아요."
GONE = "이 주소는 더 이상 열 수 없어요 — 담당 PB 에게 새 주소를 받아 주세요."
LOCKED = "PIN 을 여러 번 틀려 잠겼어요 — 담당 PB 에게 다시 열어 달라고 해 주세요."
ASK_LIMITED = f"이 주소로는 한 시간에 {ASK_PER_HOUR}번까지 물을 수 있어요 — 잠시 뒤에 다시 물어 주세요."

_ask_limiter = HourlyLimiter()


class LinkNotFound(LookupError):
    """PB 쪽 — 그 고객의 주소가 아니다(404)."""


class LinkClosed(RuntimeError):
    """PB 쪽 — 철회·만료된 주소는 다시 열거나 바꿀 수 없다(409)."""


class ShareDenied(PermissionError):
    """고객 쪽 — 주소·PIN·세션이 맞지 않는다(401, 늘 같은 말)."""


class ShareGone(RuntimeError):
    """고객 쪽 — 철회·만료·보관(410)."""


class ShareLocked(RuntimeError):
    """고객 쪽 — 잠김(423)."""


def pin_reason(pin: object) -> str | None:
    """쓸 수 없는 PIN 이면 사유. 숫자 6자리 · 같은 숫자 · 차례대로(오르내림) · 2·3자리 되풀이는 거절."""
    if not isinstance(pin, str) or len(pin) != PIN_LEN or not pin.isascii() or not pin.isdigit():
        return f"PIN 은 숫자 {PIN_LEN}자리예요."
    d = [int(x) for x in pin]
    steps = {b - a for a, b in zip(d, d[1:])}
    if len(set(pin)) == 1 or steps in ({1}, {-1}) or pin[:2] * 3 == pin or pin[:3] * 2 == pin:
        return "쉬운 PIN 이에요 — 같은 숫자·차례대로 이어지는 숫자·되풀이는 쓰지 않아요."
    return None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(t: dt.datetime | None) -> dt.datetime | None:
    """SQLite 는 시간대를 지운다 — 저장한 값은 UTC 다."""
    return t if t is None or t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _state(x: PbClientLink, client: PbClient | None, now: dt.datetime) -> str:
    if x.revoked_at is not None:
        return "revoked"
    if _aware(x.expires_at) <= now:
        return "expired"
    if client is None or client.archived_at is not None:
        return "archived"
    if x.locked_at is not None:
        return "locked"
    return "open"


def _meta(s, x: PbClientLink, client: PbClient | None) -> dict:
    sheet = s.query(PbClientSheet.title).filter(PbClientSheet.sheet_id == x.sheet_id).first()
    return {"link_id": x.link_id, "client_id": x.client_id, "sheet_id": x.sheet_id,
            "sheet_title": sheet[0] if sheet else None, "state": _state(x, client, pc._now()),
            "created_by": x.created_by, "created_at": pc._iso(_aware(x.created_at)),
            "expires_at": pc._iso(_aware(x.expires_at)), "failures": x.failures, "locked_at": pc._iso(_aware(x.locked_at)),
            "last_viewed_at": pc._iso(_aware(x.last_viewed_at)), "views": x.views,
            "revoked_by": x.revoked_by, "revoked_at": pc._iso(_aware(x.revoked_at))}


def _own_link(s, owner: str, client_id: str, link_id: str) -> tuple[PbClient, PbClientLink]:
    c = pc._owned(s, owner, client_id)
    x = s.query(PbClientLink).filter(PbClientLink.link_id == link_id, PbClientLink.client_id == c.client_id).first()
    if x is None:
        raise LinkNotFound(link_id)
    return c, x


def _show(s, owner: str, client_id: str, sheet_id: str) -> None:
    """그 고객의 한 장인지 확인하고 '보여 준 것' 으로 적는다(처음 때를 남긴다)."""
    _c, sheet = pc._owned_sheet(s, owner, client_id, sheet_id)
    if sheet.shared_at is None:
        sheet.shared_at = pc._now()


# ── PB 쪽 ──────────────────────────────────────────────────────────────────

def create_link(owner: str, client_id: str, *, sheet_id: str, pin: str, days: int) -> dict:
    """주소를 만들고 ★평문 토큰을 이번 한 번만★ 돌려준다."""
    why = pin_reason(pin)
    if why:
        raise ValueError(why)
    if days not in DAYS:
        raise ValueError(f"기간은 {'·'.join(map(str, DAYS))}일 중에서 골라 주세요.")
    token = secrets.token_urlsafe(32)
    now = pc._now()
    with session_scope() as s:
        c = pc._writable(s, owner, client_id)
        _show(s, owner, client_id, sheet_id)
        x = PbClientLink(link_id="ln_" + secrets.token_hex(8), client_id=c.client_id, sheet_id=sheet_id,
                         token_hash=_hash_token(token), pin_hash=hash_password(pin), created_by=owner,
                         created_at=now, expires_at=now + dt.timedelta(days=days), failures=0, views=0)
        s.add(x)
        s.flush()
        return {"link": _meta(s, x, c), "token": token}


def list_links(owner: str, client_id: str) -> list[dict]:
    with session_scope() as s:
        c = pc._owned(s, owner, client_id)
        rows = (s.query(PbClientLink).filter(PbClientLink.client_id == c.client_id)
                .order_by(PbClientLink.created_at.desc()).all())
        return [_meta(s, x, c) for x in rows]


def revoke_link(owner: str, client_id: str, link_id: str) -> dict:
    """끈다 — 관문과 무관하게 늘 된다. 이미 끈 주소는 처음 끈 때를 그대로 둔다."""
    with session_scope() as s:
        c, x = _own_link(s, owner, client_id, link_id)
        if x.revoked_at is None:
            x.revoked_by, x.revoked_at = owner, pc._now()
        return _meta(s, x, c)


def _live(x: PbClientLink) -> None:
    if x.revoked_at is not None or _aware(x.expires_at) <= pc._now():
        raise LinkClosed("철회했거나 만료된 주소는 다시 열 수 없어요 — 새 주소를 만들어 주세요.")


def reopen_link(owner: str, client_id: str, link_id: str) -> dict:
    """잠김 풀기 — 센 실패를 비운다."""
    with session_scope() as s:
        c, x = _own_link(s, owner, client_id, link_id)
        pc._writable(s, owner, client_id)
        _live(x)
        x.failures, x.locked_at = 0, None
        return _meta(s, x, c)


def change_sheet(owner: str, client_id: str, link_id: str, sheet_id: str) -> dict:
    """같은 주소로 보여 줄 한 장을 바꾼다(그 고객의 한 장만 · 새 한 장도 '보여 준 것')."""
    with session_scope() as s:
        c, x = _own_link(s, owner, client_id, link_id)
        pc._writable(s, owner, client_id)
        _live(x)
        _show(s, owner, client_id, sheet_id)
        x.sheet_id = sheet_id
        return _meta(s, x, c)


# ── 고객 쪽 ─────────────────────────────────────────────────────────────────

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _issue_session(link_id: str, *, key: bytes, ttl: dt.timedelta = SESSION_TTL) -> str:
    exp = int((pc._now() + ttl).timestamp())
    body = _b64(json.dumps({"l": link_id, "e": exp}, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_b64(hmac.new(key, body.encode('ascii'), hashlib.sha256).digest())}"


def _session_link(session: str | None, key: bytes) -> str:
    """서명·만료를 통과한 세션의 주소 id. 아니면 `ShareDenied`."""
    try:
        body, sig = (session or "").split(".")
        want = hmac.new(key, body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(want, _unb64(sig)):
            raise ShareDenied(DENIED)
        data = json.loads(_unb64(body))
        if not isinstance(data, dict) or int(data["e"]) <= int(time.time()):
            raise ShareDenied(DENIED)
        return str(data["l"])
    except ShareDenied:
        raise
    except Exception:
        raise ShareDenied(DENIED) from None


def _check_live(s, x: PbClientLink) -> PbClient:
    c = s.query(PbClient).filter(PbClient.client_id == x.client_id).first()
    st = _state(x, c, pc._now())
    if st in ("revoked", "expired", "archived"):
        raise ShareGone(GONE)
    if st == "locked":
        raise ShareLocked(LOCKED)
    return c


def open_session(token: str, pin: str, *, key: bytes) -> dict:
    """토큰 + PIN → 30분 세션. 차례: 토큰 → 철회·만료·보관(410) → 잠김(423) → PIN(틀리면 세고 401)."""
    wrong: Exception | None = None
    with session_scope() as s:
        x = s.query(PbClientLink).filter(PbClientLink.token_hash == _hash_token(token or "")).first()
        if x is None:
            raise ShareDenied(DENIED)
        _check_live(s, x)
        if not verify_password(pin or "", x.pin_hash):
            x.failures = (x.failures or 0) + 1
            wrong = ShareDenied(DENIED)
            if x.failures >= MAX_FAILURES:
                x.locked_at = pc._now()
                wrong = ShareLocked(LOCKED)   # 잠근 그 요청이 바로 말한다(틀린 PIN 이라 드러나는 것이 없다)
            # 센 것을 남기고(커밋) 나서 거절한다 — 안에서 던지면 되돌려진다
        else:
            x.failures = 0
            link_id = x.link_id
    if wrong is not None:
        raise wrong
    exp = pc._now() + SESSION_TTL
    return {"session": _issue_session(link_id, key=key), "expires_at": pc._iso(exp)}


def _sheet_for(s, x: PbClientLink) -> PbClientSheet:
    sheet = s.query(PbClientSheet).filter(PbClientSheet.sheet_id == x.sheet_id,
                                          PbClientSheet.client_id == x.client_id).first()
    if sheet is None:
        raise ShareGone(GONE)
    return sheet


def read_sheet(session: str | None, *, key: bytes) -> dict:
    link_id = _session_link(session, key)
    with session_scope() as s:
        x = s.query(PbClientLink).filter(PbClientLink.link_id == link_id).first()
        if x is None:
            raise ShareDenied(DENIED)
        _check_live(s, x)
        sheet = _sheet_for(s, x)
        x.views = (x.views or 0) + 1
        x.last_viewed_at = pc._now()
        return {"sheet_id": sheet.sheet_id, "sheet": json.loads(sheet.sheet),
                "link_expires_at": pc._iso(_aware(x.expires_at))}


def ask(session: str | None, question: str, previous: dict | None, *, key: bytes) -> dict:
    """고객 AI — 근거는 이 주소가 지금 보여 주는 한 장뿐 · 주소마다 시간당 10번."""
    from src.services.canvas_assist import service as assist
    link_id = _session_link(session, key)
    with session_scope() as s:
        x = s.query(PbClientLink).filter(PbClientLink.link_id == link_id).first()
        if x is None:
            raise ShareDenied(DENIED)
        _check_live(s, x)
        sheet = _sheet_for(s, x)
        sheet_id, data = sheet.sheet_id, json.loads(sheet.sheet)
    if not _ask_limiter.allow(link_id, ASK_PER_HOUR, time.monotonic()):
        return {"available": False, "source": "unavailable", "reason_code": "share_rate_limited", "reason": ASK_LIMITED}
    return assist.ask_sheet(data, sheet_id, question, previous, f"share:{link_id}")
