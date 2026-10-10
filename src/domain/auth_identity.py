"""신원 — ★"누가 눌렀는가" 를 **관측**으로 만드는 어휘★ (AC1)
==============================================================================
설계: `docs/plans/2026-09-12-ra-product-roadmap.md` P-1
소비자: `src/api/auth.py` · `src/api/auth_routes.py` · `src/api/protected_routes.py`
        · `src/api/stage13_routes.py` · `src/api/account_order_routes.py`

## 왜 필요한가 — ★감사 로그의 행위자가 **자칭**이었다★

`POST /api/v1/live/mode` 의 `actor`, `kill-switch/resolve` 의 `resolved_by` 는
요청 본문의 문자열이었고, 그대로 `audit_trail.log_mode_change(actor=…)` 를 지나
`live_audit_log.actor` 에 **적혔다**. 누구든 `actor="admin"` 이라 적으면 감사 로그가
그렇게 기록했다 — ★관측이 아니라 주장을 저장한 것★이고, CLAUDE.md §2 의
`관측 ≠ 가정`, §4 의 `미검증 ≠ 검증` 을 저장소가 스스로 어기던 자리다.

그래서 P-1 은 문을 잠그는 일이면서 동시에 **감사 로그의 한 컬럼을 미검증에서
관측으로 옮기는 일**이다. 이 모듈은 그 "관측된 신원" 의 어휘를 정의한다.

## ★두 축을 섞지 않는다★

    role      무엇을 **할 수 있나**   admin / analyst
    source    그것을 **어떻게 알았나**  서명 검증된 토큰 / 제시 없음

역할만 들고 다니면 "이 admin 을 어떻게 알았지?" 가 사라진다. 신원의 출처를 값에
남겨야 감사 로그가 `actor_source` 를 말할 수 있다.

## ★순수 계층★

DB 도 FastAPI 도 JWT 도 여기서는 모른다. 토큰을 **푸는** 일은 `src/api/auth.py`
이고, 이 모듈은 그 결과를 담는 타입과 **판정 함수 둘**만 갖는다. 역할 문자열을
라우트마다 비교하기 시작하면 정책이 333곳으로 흩어진다 — 판정은 여기 한 곳이다.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── 역할 ────────────────────────────────────────────────────────────────────
#: 실행 모드·주문·킬스위치를 움직일 수 있다.
ROLE_ADMIN = "admin"
#: 읽고 연구한다. 돈을 옮기지 않는다. (`User.role` 의 기본값)
ROLE_ANALYST = "analyst"
#: ★이 둘이 전부다★ — `src/database.py` 의 `User.role` 이 실제로 갖는 값.
ROLES = (ROLE_ADMIN, ROLE_ANALYST)

# ── 신원의 출처 ─────────────────────────────────────────────────────────────
#: 서명이 검증된 JWT 에서 **관측**했다.
SOURCE_TOKEN = "token"
#: 신원을 제시하지 않았다. ★"익명" 이 아니라 "묻지 않은 상태" 다★ —
#: 이 값을 가진 Principal 로는 어떤 보호 라우트도 통과하지 못한다.
SOURCE_ABSENT = "absent"

# ── 비밀키의 상태 ───────────────────────────────────────────────────────────
#: `AUTH_SECRET` 환경변수가 있다 — 토큰이 재시작을 넘어 산다.
SECRET_CONFIGURED = "configured"
#: 환경변수가 없어 프로세스마다 난수를 만들었다 — ★재시작하면 전원 로그아웃★.
#: 조용한 폴백이 아니라 **라벨 붙은 열화**다: 의미가 알려졌고, 동등 품질로 위장하지
#: 않으며, `GET /api/v1/auth/me` 로 관측 가능하다(CLAUDE.md §4 의 네 조건).
SECRET_EPHEMERAL = "ephemeral"


@dataclass(frozen=True)
class Principal:
    """검증을 마친 신원 하나.

    ★frozen★ — 요청이 통과하는 도중에 역할이 바뀔 수 없다. 권한 상승은 토큰을
    다시 받는 길밖에 없다.
    """

    username: str
    role: str
    source: str
    #: 토큰의 발급·만료 시각(ISO8601). ★모르면 `None` 이고 0 이 아니다★.
    issued_at: str | None = None
    expires_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "role": self.role,
            "source": self.source,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }


def is_admin(p: Principal) -> bool:
    """★모르는 역할은 admin 이 아니다★ — 미상을 통과로 접지 않는다."""
    return p.role == ROLE_ADMIN


def can_read_user(p: Principal, username: str | None) -> bool:
    """`username` 의 자원을 이 신원이 읽어도 되는가 — 자기 자신이거나 admin.

    ★대소문자·공백을 관대하게 접지 않는다★ — `User.username` 은 기본키이고 DB 가
    `Alice` 와 `alice` 를 다른 사람으로 취급한다. 여기서 같다고 지어내면 인가가
    저장소와 다른 사실 위에 서게 된다.
    """
    if not username:
        return False
    if is_admin(p):
        return True
    return p.username == username


#: 감사 기록의 행위자가 **서명된 토큰에서 관측**됐다는 표시.
ACTOR_SOURCE_AUTHENTICATED = "authenticated"

#: 본문의 `actor` 기본값들 — 이름을 주장한 것이 아니라 **비워 둔** 것이다.
#: 이것을 충돌로 기록하면 모든 요청이 거짓말한 것처럼 보여 로그가 쓸모없어진다.
_UNCLAIMED = frozenset({"", "user", "admin", "system"})


def observed_actor(p: Principal, claimed: str | None = None) -> dict:
    """감사 계층에 넘길 행위자 — ★자칭이 아니라 관측★ (AC5).

    이 저장소에서 `POST /api/v1/live/mode` 의 `actor` 와
    `kill-switch/resolve` 의 `resolved_by` 는 **요청 본문의 문자열**이었고, 그대로
    `live_audit_log.actor` 에 적혔다. 누구든 `actor="admin"` 이라 쓰면 감사 로그가
    그렇게 기록했다 — 관측이 아니라 주장을 저장한 것이다.

    ★자칭을 지우지 않는다★ — 본문이 토큰과 **다른** 이름을 주장했다면 그 사실 자체가
    기록할 가치가 있는 사건이다. 지우면 "누가 남을 사칭하려 했다" 를 영영 모른다.
    주장이 없거나(기본값 포함) 토큰과 같으면 충돌이 아니므로 `None` 이다.

    반환 키는 셋:
        actor         감사 계층에 넘길 이름 — **언제나** 토큰의 username
        actor_source  그 이름을 어떻게 알았나
        claimed_actor 본문이 **다르게** 주장했다면 그 값, 아니면 `None`
    """
    normalized = (claimed or "").strip()
    conflict = (
        normalized
        and normalized.lower() not in _UNCLAIMED
        and normalized != p.username
    )
    return {
        "actor": p.username,
        "actor_source": ACTOR_SOURCE_AUTHENTICATED,
        "claimed_actor": normalized if conflict else None,
    }
