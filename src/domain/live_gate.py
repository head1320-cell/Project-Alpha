"""실계좌(LIVE) 관문 — ★실제 돈으로 주문하는 모드는 운영자의 확인 기록 뒤에 있다★ (BV1)
==============================================================================
설계: `docs/plans/2026-09-12-ra-product-roadmap.md` ⑥ · "하지 않을 것" 의 실계좌 집행 코드 줄

## 왜 이 모듈이 있나

로드맵은 실계좌 집행을 "인가 확인 전 금지" 로 막아 두었다. 사용자는 그 규칙을 알고 2026-10-09 에
★사용자마다 자기 증권 계좌를 연결하고 모의투자/실계좌를 고른다 — 실계좌도 만든다★ 를 골랐다.
그래서 실계좌 집행 코드는 만든다. 그러나 ⑥ "인가 없이 켜지 않는다" 는 문자 그대로 참이어야 하므로,
★켜는 것★은 이 관문을 지나야 한다. 기본 답은 막힘 + 사유다.

## ★사용자 이름 목록으로 열린다★

검색 요약(원문 미검증)으로는 KIS 오픈API 로 ★다른 사람에게★ 주문 서비스를 하려면 증권사 제휴가
필요하고, 본인 계좌만 쓰면 필요 없다. 그래서 관문은 "열림/닫힘" 하나가 아니라 ★허용한 사용자 이름★을
든다 — 운영자는 본인만 열 수 있고, 남에게 여는 것은 이름이 남는 기록된 행위가 된다. `*` 나 빈 이름으로
모두에게 여는 길은 없다.

## ★환경변수 뒷문을 만들지 않는다 · 기록을 저장소에 박지 않는다★

`distribution_gate` 와 같은 규율이다. 이 모듈은 `os` 를 import 하지 않고, 완성된 `LiveAuthorization`
리터럴은 `src/` 어디에도 없다(`tests/test_live_gate.py` 가 전수로 확인한다). 기록은 운영자가 서버에
선언한다(BV7 — 선언한 사람은 로그인 토큰에서 온다).

## ★이 관문이 주장하지 않는 것★

- 실계좌 주문이 적법한지 판단하지 않는다 — 업권·약관 판단이고 이 저장소가 할 수 있는 일이 아니다.
- 운영자가 적은 근거가 참인지 확인하지 않는다 — 무엇을 근거로 열었는지 ★남길★ 뿐이다.
- 이것 하나로 LIVE 가 켜지지 않는다 — 계좌별 모의 검증·확인 단계(BV7)가 함께 필요하다.
"""
from __future__ import annotations

from dataclasses import dataclass, fields

#: 실계좌로 주문해도 된다 — ★이 저장소에서 기본으로는 도달할 수 없는 상태★
LIVE_ALLOWED = "allowed"
#: 실계좌로 주문할 수 없다. 기본값.
LIVE_BLOCKED = "blocked"

#: 확인 기록이 갖춰야 할 것. ★여섯이 **전부** 있어야 한다★
AUTH_FIELDS = ("basis", "authority", "reference_no", "verified_at", "scope", "allowed_users")

#: 이름 목록에 들어갈 수 없는 값 — 모두에게 여는 길.
_WILDCARDS = frozenset({"*", "all", "ALL", "everyone", "모두", "전체"})

UNVERIFIED_LIVE_REASON = (
    "실계좌 주문은 확인된 적이 없어 꺼져 있어요. 운영자가 근거·확인 기관·번호·확인일·범위와 "
    "허용할 사용자 이름을 선언해야 열려요."
)


@dataclass(frozen=True)
class LiveAuthorization:
    """운영자가 선언하는 실계좌 확인 기록. ★기본값은 전부 비어 있다★

    값 하나가 아니라 ★무엇을 근거로·누가 확인했고·누구에게 열었는가★가 함께 와야 나중에
    "무슨 근거로 실계좌를 열었나" 를 물을 수 있다(`distribution_gate.LicenseRecord` 와 같은 모양).
    """

    basis: str | None = None          # 근거 — 예: 본인 계좌만 쓴다 / 증권사 제휴 계약
    authority: str | None = None      # 확인한 곳
    reference_no: str | None = None   # 확인 번호(계약·인가·문서 번호)
    verified_at: str | None = None    # 언제 확인했나 (ISO)
    scope: str | None = None          # 무엇까지 열었나
    allowed_users: tuple[str, ...] = ()  # 실계좌를 열 사용자 이름 — 하나씩

    def to_dict(self) -> dict:
        out = {name: getattr(self, name) for name in AUTH_FIELDS}
        out["allowed_users"] = list(self.allowed_users)
        return out

    def missing(self) -> list[str]:
        """비어 있는 필드 이름들. ★공백만 있는 글자 · 빈 이름 · 와일드카드는 비어 있는 것으로 센다★"""
        out = [f.name for f in fields(self)
               if f.name != "allowed_users" and not (getattr(self, f.name) or "").strip()]
        users = self.allowed_users or ()
        if (not users
                or any(not (u or "").strip() for u in users)
                or any((u or "").strip() in _WILDCARDS for u in users)):
            out.append("allowed_users")
        return out


def live_gate(record: LiveAuthorization | None = None, username: str | None = None) -> dict:
    """이 사용자의 계좌로 실계좌 주문을 열어도 되는가. ★기본은 언제나 `blocked`★

    Returns:
        `state` (allowed|blocked) · `reason` · `missing`(빠진 필드) ·
        `authorization`(쓴 기록, 없으면 `None`).
    """
    if record is None:
        return {
            "state": LIVE_BLOCKED,
            "reason": UNVERIFIED_LIVE_REASON,
            "missing": list(AUTH_FIELDS),
            "authorization": None,
        }

    missing = record.missing()
    if missing:
        return {
            "state": LIVE_BLOCKED,
            # ★무엇이 빠졌는지 말한다★ — 막힌 사람이 무엇을 해야 하는지 모르면 그 거부는 절반만 정직하다.
            "reason": f"확인 기록이 불완전해요. 빠진 항목: {', '.join(missing)}. " + UNVERIFIED_LIVE_REASON,
            "missing": missing,
            "authorization": record.to_dict(),
        }

    if not (username or "").strip():
        return {
            "state": LIVE_BLOCKED,
            "reason": "누구의 계좌인지 몰라서 실계좌를 열 수 없어요.",
            "missing": [],
            "authorization": record.to_dict(),
        }

    # ★이름은 그대로 비교한다★ — 대소문자·공백을 맞춰 주면 목록에 없는 계정이 열린다.
    if username not in record.allowed_users:
        return {
            "state": LIVE_BLOCKED,
            "reason": f"'{username}' 계정은 운영자가 실계좌를 연 사용자 목록에 없어요.",
            "missing": [],
            "authorization": record.to_dict(),
        }

    return {
        "state": LIVE_ALLOWED,
        "reason": None,
        "missing": [],
        # ★어느 기록으로 열었는지 남긴다★
        "authorization": record.to_dict(),
    }
