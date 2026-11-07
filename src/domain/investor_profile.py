"""투자자 프로파일 — ★요청 인자를 **영속 신원**으로★ (AD2)
==============================================================================
설계: `docs/specs/2026-09-12-ra-domain-architecture.md` §1 (RA5)을 코드로 옮긴 것.

## 왜 필요한가

`investment_decision.decide()` 와 `rebalance_policy.rebalance_decision()` 이
`risk_aversion`·`horizon_days` 를 **매 요청마다** 받는다. 같은 사람에게 같은 값이
쓰인다는 보장이 없고, 계좌 유형 개념은 아예 없었다.

## ★미상을 지어내지 않는다★

`horizon_days=None` 을 `DEFAULT_HORIZON_DAYS = 63` 으로 채우지 않는다 — CLAUDE.md §4
의 `미상 ≠ 0`. 호출부가 기본값을 쓰기로 정하면 **그 사실을 결과에 라벨로 남긴다**
(`horizon_label()`). `source` 의 기본값도 `unknown` 이지 `survey` 가 아니다: 가장
신뢰도 높은 값을 기본으로 두면 모든 프로파일이 설문을 거친 것처럼 보인다.

★성향은 낡는다★ — 그래서 `assessed_at` 이 있다. 3년 전 설문으로 오늘의 배분을
정당화하는 것과 어제 설문으로 정당화하는 것은 같은 근거가 아니다.

## ★이번에 하지 않는 것★

RA5 가 스스로 적은 경계를 지킨다:

| 하는 것 | ★안 하는 것★ |
|---|---|
| 타입·어휘 정의 | `users`·`portfolios` 테이블 변경 |
| `decide()` 인자와의 대응 관계 기술 | ★`decide()` 시그니처 변경 — 승인 필요(결정 경로)★ |

계좌 어휘는 `account_policy` 의 것을 **그대로 쓴다** — 여기서 다시 선언하면 두 벌이
되고, 한쪽만 고쳐도 타입 에러가 나지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.domain.account_policy import ACCOUNT_TYPES

#: 위험 성향. ★숫자 하나로 뭉개지 않는다★ — 등급과 그 근거를 함께 든다.
RISK_TOLERANCE_LEVELS = ("conservative", "moderate_conservative",
                         "moderate", "moderate_aggressive", "aggressive")

#: 이 프로파일이 ★어떻게 정해졌나★ — 설문과 기본값은 같은 신뢰도가 아니다.
SOURCE_SURVEY = "survey"
SOURCE_USER_DECLARED = "user_declared"
SOURCE_DEFAULT = "default"
SOURCE_UNKNOWN = "unknown"
PROFILE_SOURCES = (SOURCE_SURVEY, SOURCE_USER_DECLARED, SOURCE_DEFAULT, SOURCE_UNKNOWN)

_HORIZON_UNKNOWN_REASON = (
    "투자기간이 선언되지 않았습니다 — 기본값으로 채우지 않았습니다."
)


@dataclass(frozen=True)
class InvestorProfile:
    """한 계좌의 투자자 신원. ★frozen★ — 판단 도중에 성향이 바뀌지 않는다."""

    profile_id: str
    owner_id: str                        # 인증 주체(P-1 의 `Principal.username`)
    account_type: str                    # ACCOUNT_TYPES
    risk_tolerance: str                  # RISK_TOLERANCE_LEVELS
    horizon_days: int | None = None      # ★None = 미상. 63 으로 지어내지 않는다★
    target_retirement_year: int | None = None
    risk_aversion: float | None = None   # 효용 계산용 λ
    source: str = SOURCE_UNKNOWN
    assessed_at: str | None = None       # ISO. 성향은 낡는다

    def __post_init__(self) -> None:
        if self.account_type not in ACCOUNT_TYPES:
            raise ValueError(
                f"알 수 없는 계좌 유형 {self.account_type!r} — 허용: {list(ACCOUNT_TYPES)}")
        if self.risk_tolerance not in RISK_TOLERANCE_LEVELS:
            raise ValueError(
                f"알 수 없는 위험 성향 {self.risk_tolerance!r} — "
                f"허용: {list(RISK_TOLERANCE_LEVELS)}")
        if self.source not in PROFILE_SOURCES:
            raise ValueError(
                f"알 수 없는 프로파일 출처 {self.source!r} — 허용: {list(PROFILE_SOURCES)}")

    def horizon_label(self) -> dict:
        """투자기간이 **선언된 것인지 미상인지**를 값으로 낸다.

        호출부가 기본값을 쓰기로 정하더라도 이 라벨이 결과에 남으면, 나중에
        "이 판단의 투자기간은 사용자가 준 것인가" 를 물을 수 있다.
        """
        if self.horizon_days is None:
            return {"state": "unknown", "days": None, "reason": _HORIZON_UNKNOWN_REASON}
        return {"state": "declared", "days": self.horizon_days, "reason": None}

    def to_dict(self) -> dict:
        """camelCase 표기 — 프런트가 그대로 받을 수 있는 모양.

        ★이 자리는 원래 **만들어진 적 없는 프런트 타입 파일**을 "프런트 타입"
        이라며 가리키고 있었다(AO 에서 실측). 설계 문서가 *(제안)* 이라고 적어 둔
        것을 docstring 이 이미 있는 것처럼 옮겨 적은 것이다 —
        `docs/specs/2026-09-12-ra-domain-architecture.md` §1 이 그 제안이고,
        대응하는 프런트 파일은 **아직 없다**. ★없는 파일을 가리키지 않는다★:
        죽은 포인터는 `tests/test_doc_pointers.py` 가 전수로 막는다.
        """
        return {
            "profileId": self.profile_id,
            "ownerId": self.owner_id,
            "accountType": self.account_type,
            "riskTolerance": self.risk_tolerance,
            "horizonDays": self.horizon_days,
            "targetRetirementYear": self.target_retirement_year,
            "riskAversion": self.risk_aversion,
            "source": self.source,
            "assessedAt": self.assessed_at,
            "horizonLabel": self.horizon_label(),
        }
