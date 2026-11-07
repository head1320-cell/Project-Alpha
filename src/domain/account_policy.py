"""계좌 제약 — ★틀은 만들되 **법규 수치는 적지 않는다**★ (AD1)
==============================================================================
설계: `docs/plans/2026-09-12-ra-product-roadmap.md` P3 멀티계좌 허브
어휘: `docs/specs/2026-09-12-ra-domain-architecture.md` §1 (RA5)이 이미 설계했다 —
      `ACCOUNT_*` 를 **새로 만들지 않고** 그대로 옮긴다.

## 왜 수치가 비어 있나

일반·연금저축·IRP·ISA 는 세제와 상품 제약이 다르고, 그 제약은 **실제 법규**다 —
IRP 위험자산 한도, ISA 납입한도·의무보유기간, 연금저축 세액공제 한도. 그런데
★이 저장소에는 그 수치의 근거가 없다★. 법은 개정되고, 가입 유형·시기에 따라 다르며,
여기에 숫자를 적는 순간 그것은 **검증되지 않은 주장**이 된다(CLAUDE.md §4 —
"경제 가정을 파이프라인을 돌리려고 지어내지 마세요 — 모르면 `None` 과 사유").

그래서 이 모듈은 **제약의 종류(슬롯)** 만 선언하고 **값은 비운다**. 값은 운영자가
출처·기준일과 함께 선언하고, 선언하지 않은 한도는 ★통과가 아니라 미판정★이다.

## ★슬롯 자체도 미검증 주장이다★

"IRP 에는 위험자산 한도가 있다" 도 엄밀히는 법규 진술이다. 다만 그것은 **구조**이고
수치가 아니며, 슬롯이 비어 있는 한 이 모듈은 어떤 계좌도 "적법하다" 고 말하지
않는다. 슬롯은 *무엇을 물어야 하는가* 의 목록이지 *답* 이 아니다.

## ★미선언은 통과가 아니다★

이 파일의 단 하나의 불변식이다. `run_evidence` 의 `AXIS_UNKNOWN` 이 통과가 아닌 것,
`decision_evidence` 의 미상이 통과가 아닌 것과 같은 규율이고, 계좌 제약에서는 그것이
곧 **"법규를 검증했다" 는 거짓 주장을 막는 장치**다.

## ★최적화기를 건드리지 않는다★

로드맵은 *"계좌별 제약을 `Constraints` 로 옮긴다"* 고 적었지만 이번에는 **관측만**
한다(사용자 결정, 2026-09-13). `constrained_opt.py` 와 배분 결정 경로는 한 줄도
바뀌지 않는다 — CLAUDE.md §3 의 별도 승인 사항이다. 여기의 판정은 **사후 관측**이고
배분은 여전히 계좌를 모른 채 나온다.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── 계좌 유형 (RA5 §1 그대로) ───────────────────────────────────────────────
ACCOUNT_GENERAL = "general"                    # 일반 위탁
ACCOUNT_PENSION_SAVINGS = "pension_savings"    # 연금저축
ACCOUNT_IRP = "irp"                            # 개인형 퇴직연금
ACCOUNT_ISA = "isa"                            # 개인종합자산관리계좌
ACCOUNT_TYPES = (ACCOUNT_GENERAL, ACCOUNT_PENSION_SAVINGS, ACCOUNT_IRP, ACCOUNT_ISA)

# ── 제약의 종류 ─────────────────────────────────────────────────────────────
#: 위험자산 비중 상한(%). ★무엇이 위험자산인지도 선언 대상이다★ — AD3 참고.
LIMIT_RISKY_ASSET_MAX_PCT = "risky_asset_max_pct"
#: 연간 납입 한도(원).
LIMIT_ANNUAL_CONTRIB_KRW = "annual_contribution_krw"
#: 총 납입 한도(원).
LIMIT_TOTAL_CONTRIB_KRW = "total_contribution_krw"
#: 의무 보유 기간(일). ★이것만 방향이 반대다★ — 넘겨야 통과.
LIMIT_MIN_HOLDING_DAYS = "min_holding_days"

LIMIT_KINDS = (LIMIT_RISKY_ASSET_MAX_PCT, LIMIT_ANNUAL_CONTRIB_KRW,
               LIMIT_TOTAL_CONTRIB_KRW, LIMIT_MIN_HOLDING_DAYS)

DIRECTION_MAX = "max"   # 관측값이 한도 **이하**여야 통과
DIRECTION_MIN = "min"   # 관측값이 한도 **이상**이어야 통과

#: ★상한과 하한을 섞지 않는다★ — 한 함수에서 부호만 뒤집으면 조용히 반대로 판정한다.
LIMIT_DIRECTION: dict[str, str] = {
    LIMIT_RISKY_ASSET_MAX_PCT: DIRECTION_MAX,
    LIMIT_ANNUAL_CONTRIB_KRW: DIRECTION_MAX,
    LIMIT_TOTAL_CONTRIB_KRW: DIRECTION_MAX,
    LIMIT_MIN_HOLDING_DAYS: DIRECTION_MIN,
}

#: 계좌 유형 → 적용된다고 **알려진** 제약 종류.
#: ★수치는 여기에 없다★ — 무엇을 물어야 하는가의 목록일 뿐이다.
ACCOUNT_LIMIT_SLOTS: dict[str, tuple[str, ...]] = {
    # 일반 위탁계좌에는 세제·상품 한도가 없다.
    ACCOUNT_GENERAL: (),
    ACCOUNT_PENSION_SAVINGS: (LIMIT_ANNUAL_CONTRIB_KRW,),
    ACCOUNT_IRP: (LIMIT_RISKY_ASSET_MAX_PCT, LIMIT_ANNUAL_CONTRIB_KRW),
    ACCOUNT_ISA: (LIMIT_ANNUAL_CONTRIB_KRW, LIMIT_TOTAL_CONTRIB_KRW,
                  LIMIT_MIN_HOLDING_DAYS),
}

#: 한도가 비어 있는 이유. ★고정 문구★ — 화면마다 다른 말을 하지 않도록.
UNDECLARED_REASON = (
    "이 저장소는 법규 수치를 검증할 수 없습니다 — "
    "운영자가 출처와 기준일을 함께 선언해야 합니다."
)

# ── 판정 어휘 ───────────────────────────────────────────────────────────────
VERDICT_PASS = "pass"
VERDICT_BREACH = "breach"
#: ★한도 미선언·관측 불가 — **통과가 아니다**★
VERDICT_UNDETERMINED = "undetermined"
VERDICTS = (VERDICT_PASS, VERDICT_BREACH, VERDICT_UNDETERMINED)


@dataclass(frozen=True)
class AccountLimit:
    """한도 하나. ★값 + 출처 + 기준일★ — 숫자 하나가 아니다.

    법이 개정되면 값이 바뀐다. 그때 **과거 판정의 의미가 조용히 바뀌면 안 되므로**
    판정 결과가 자기가 쓴 한도의 `value`·`source`·`as_of` 를 들고 다닌다
    (V2 bi-temporal · T1 `vintage_probe_at` 과 같은 규율).
    """

    kind: str
    value: float | None = None
    source: str | None = None      # 법령 조항·URL — 운영자가 선언
    as_of: str | None = None       # 언제 기준인가
    reason: str | None = None      # value 가 None 인 이유

    def __post_init__(self) -> None:
        # ★사유 없는 미상은 **생성 자체가 불가능**하다★ — 나중에 잊는 길을 막는다.
        if self.value is None and not self.reason:
            raise ValueError(
                f"한도 {self.kind!r} 의 값이 없는데 사유가 없습니다 — "
                "미상은 사유와 함께여야 합니다.")

    def to_dict(self) -> dict:
        return {"kind": self.kind, "value": self.value,
                "source": self.source, "as_of": self.as_of, "reason": self.reason}


def undeclared_limits(account_type: str) -> tuple[AccountLimit, ...]:
    """이 계좌 유형의 슬롯을 **전부 미선언 상태**로 만든다 — 기본값이다."""
    _require_known(account_type)
    return tuple(
        AccountLimit(kind=kind, value=None, reason=UNDECLARED_REASON)
        for kind in ACCOUNT_LIMIT_SLOTS[account_type]
    )


def _require_known(account_type: str) -> None:
    if account_type not in ACCOUNT_TYPES:
        raise ValueError(
            f"알 수 없는 계좌 유형 {account_type!r} — 허용: {list(ACCOUNT_TYPES)}")


def _interval(observed: float | tuple[float, float] | None
              ) -> tuple[float, float] | None:
    """관측값을 구간으로. ★스칼라는 폭 0 의 구간★ — 없는 불확실성을 만들지 않는다."""
    if observed is None:
        return None
    if isinstance(observed, (tuple, list)):
        lo, hi = float(observed[0]), float(observed[1])
        return (lo, hi) if lo <= hi else (hi, lo)
    value = float(observed)
    return (value, value)


def judge_limit(limit: AccountLimit,
                observed: float | tuple[float, float] | None) -> dict:
    """한도 하나에 대한 판정.

    ★관측값은 **구간**일 수 있다★ — 보유의 일부가 자산군 미배정이면 위험자산 비중이
    점이 아니라 폭이다. 구간이 한도를 걸치면 `UNDETERMINED` 다: 미배정분을 0 으로
    접어 "한도 이하입니다" 라고 말하면 없는 사실을 만든다(AD3).
    """
    direction = LIMIT_DIRECTION.get(limit.kind, DIRECTION_MAX)
    window = _interval(observed)
    out = {
        "kind": limit.kind,
        "direction": direction,
        "limit": limit.to_dict(),
        "observed": None if window is None else {"lo": window[0], "hi": window[1]},
    }

    if limit.value is None:
        # ★미선언은 통과가 아니다★ — 이 모듈의 단 하나의 불변식.
        return {**out, "verdict": VERDICT_UNDETERMINED, "reason": limit.reason}

    if window is None:
        return {**out, "verdict": VERDICT_UNDETERMINED,
                "reason": f"한도는 선언됐으나 {limit.kind} 관측값이 없습니다."}

    lo, hi = window
    cap = float(limit.value)
    if direction == DIRECTION_MAX:
        if hi <= cap:
            return {**out, "verdict": VERDICT_PASS, "reason": None}
        if lo > cap:
            return {**out, "verdict": VERDICT_BREACH,
                    "reason": f"관측 하한 {lo:.2f} 이 한도 {cap:.2f} 을 넘습니다."}
    else:
        if lo >= cap:
            return {**out, "verdict": VERDICT_PASS, "reason": None}
        if hi < cap:
            return {**out, "verdict": VERDICT_BREACH,
                    "reason": f"관측 상한 {hi:.2f} 이 기준 {cap:.2f} 에 못 미칩니다."}

    return {**out, "verdict": VERDICT_UNDETERMINED,
            "reason": (f"관측 구간 [{lo:.2f}, {hi:.2f}] 이 한도 {cap:.2f} 을 "
                       "걸칩니다 — 미배정분 때문에 판정할 수 없습니다.")}


def judge_account(account_type: str,
                  limits: tuple[AccountLimit, ...] | list[AccountLimit],
                  observations: dict[str, float | tuple[float, float] | None]) -> dict:
    """계좌 하나의 모든 슬롯을 판정한다.

    ★슬롯에 없는 한도는 무시하지 않고 **알린다**★ — 운영자가 엉뚱한 계좌에 한도를
    선언했다면 그것은 조용히 넘길 일이 아니다.
    """
    _require_known(account_type)
    slots = ACCOUNT_LIMIT_SLOTS[account_type]
    by_kind = {limit.kind: limit for limit in limits}

    verdicts = []
    for kind in slots:
        limit = by_kind.get(kind) or AccountLimit(kind=kind, value=None,
                                                  reason=UNDECLARED_REASON)
        verdicts.append(judge_limit(limit, observations.get(kind)))

    ignored = sorted(set(by_kind) - set(slots))
    summary = {v: sum(1 for x in verdicts if x["verdict"] == v) for v in VERDICTS}

    note = None
    if not slots:
        note = (f"{account_type} 계좌에는 이 저장소가 아는 제약 슬롯이 없습니다 — "
                "제약이 없다는 뜻이 아니라 묻지 않았다는 뜻입니다.")
    return {
        "account_type": account_type,
        "verdicts": verdicts,
        "summary": summary,
        "ignored_limits": ignored,
        "note": note or (f"{account_type} 계좌의 슬롯 {len(slots)}개를 판정했습니다."),
    }
