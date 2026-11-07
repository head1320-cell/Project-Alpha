"""유통 관문 — ★업권 경고를 산문에서 **기계가 읽는 관문**으로★ (AE1)
==============================================================================
설계: `docs/plans/2026-09-12-ra-product-roadmap.md` P4

## 왜 이 모듈이 있나

로드맵이 P4(마켓플레이스·구독·B2B 어드바이저 API)를 멈춰 세운 이유는 기능이 아니다:

> ★여기서 멈추는 이유★ — 외부 전략을 고객에게 **유통**하는 것은 기능 문제가 아니라
> **업권 문제**다. (…) 이 저장소는 그것을 확인한 적이 없다.

그리고 완료 판정을 일부러 비워 뒀다 — *"지금 적으면 근거 없는 판정이 스펙에 박힌다."*

★문제는 그 경고가 **산문**이라는 것이다.★ 산문은 코드가 조용히 지나간다. 6개월 뒤
누군가(나 포함) 구독 라우트를 하나 붙이면서 이 문단을 읽지 않을 수 있다. 그래서
경고를 **호출 가능한 관문**으로 바꾼다: 유통을 하려는 코드는 이 함수를 지나야 하고,
기본 답은 **막힘 + 사유**다.

## ★기본이 막힘이다★

`distribution_gate()` 를 인자 없이 부르면 언제나 `blocked` 다. 열리는 유일한 길은
운영자가 **인가 기록을 완전히 선언**하는 것이고, 그 기록은 ★이 저장소에 없다★ —
AD 의 법규 수치와 같은 규율이다(`tests/test_distribution_gate.py` 가 소스에 완성된
`LicenseRecord` 리터럴이 없는지 전수로 확인한다).

## ★환경변수 뒷문을 만들지 않는다★

`DISTRIBUTION_OK=1` 같은 플래그 하나로 업권 관문이 열리면 그것은 관문이 아니라
장식이다. 다섯 필드가 **전부** 있어야 하고, 하나라도 비면 무엇이 빠졌는지 적는다.
이 모듈은 `os.getenv` 를 **부르지 않는다**(테스트가 고정한다).

## ★이 관문이 주장하지 않는 것★

- **인가가 필요한지 아닌지를 판단하지 않는다.** 그것은 업권 판단이고 이 저장소가
  할 수 있는 일이 아니다. 관문은 *"확인된 적이 없다"* 만 말한다.
- **유통을 물리적으로 막지 않는다.** 코드를 고치면 열린다 — 이것은 **의도를 검증
  가능하게** 만든 것이지 접근 통제가 아니다.
"""
from __future__ import annotations

from dataclasses import dataclass, fields

#: 유통해도 된다 — ★이 저장소에서 기본으로는 도달할 수 없는 상태★
DISTRIBUTION_ALLOWED = "allowed"
#: 유통할 수 없다. 기본값.
DISTRIBUTION_BLOCKED = "blocked"

#: 인가 기록이 갖춰야 할 것. ★다섯이 **전부** 있어야 한다★
LICENSE_FIELDS = ("authority", "license_kind", "license_no", "verified_at", "scope")

UNVERIFIED_REASON = (
    "외부 전략 유통은 업권 사항입니다 — 이 저장소는 인가를 확인한 적이 없습니다. "
    "운영자가 인가 기관·종류·번호·확인일·범위를 선언해야 합니다."
)


@dataclass(frozen=True)
class LicenseRecord:
    """운영자가 선언하는 인가 기록. ★기본값은 전부 `None`★

    AD 의 `AccountLimit` 과 같은 모양이다 — 값 하나가 아니라 **누가·무엇을·언제
    확인했는가**가 함께 와야 나중에 "무슨 근거로 유통했나" 를 물을 수 있다.
    """

    authority: str | None = None       # 인가 기관
    license_kind: str | None = None    # 인가 종류
    license_no: str | None = None      # 인가 번호
    verified_at: str | None = None     # 언제 확인했나 (ISO)
    scope: str | None = None           # 무엇을 유통할 수 있나

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in LICENSE_FIELDS}

    def missing(self) -> list[str]:
        """비어 있는 필드 이름들. ★공백만 있는 문자열도 비어 있는 것으로 센다★"""
        return [f.name for f in fields(self)
                if not (getattr(self, f.name) or "").strip()]


def distribution_gate(license_record: LicenseRecord | None = None) -> dict:
    """외부에 유통해도 되는가. ★기본은 언제나 `blocked`★

    Returns:
        `state` (allowed|blocked) · `reason` · `missing`(빠진 필드) ·
        `license`(쓴 기록, 없으면 `None`).
    """
    if license_record is None:
        return {
            "state": DISTRIBUTION_BLOCKED,
            "reason": UNVERIFIED_REASON,
            "missing": list(LICENSE_FIELDS),
            "license": None,
        }

    missing = license_record.missing()
    if missing:
        return {
            "state": DISTRIBUTION_BLOCKED,
            # ★무엇이 빠졌는지 말한다★ — 막힌 사람이 무엇을 해야 하는지 모르면
            #   그 거부는 절반만 정직하다(`usable_for_portfolio` 와 같은 관용구).
            "reason": (f"인가 기록이 불완전합니다 — 빠진 항목: {', '.join(missing)}. "
                       + UNVERIFIED_REASON),
            "missing": missing,
            "license": license_record.to_dict(),
        }

    return {
        "state": DISTRIBUTION_ALLOWED,
        "reason": None,
        "missing": [],
        # ★어느 인가로 열었는지 남긴다★
        "license": license_record.to_dict(),
    }
