"""하루를 ★설명하되, 설명하지 못한 몫을 숨기지 않는다★ (AB1)
==============================================================================
설계: `docs/plans` AB · 로드맵 P3 · 도메인 아키텍처 §5
소비자: `src/engine/daily_explain_backtest.py` · `daily_explain_holdings.py` ·
        `src/api/explain_routes.py`

로드맵의 완료 판정이 이 모듈의 계약이다 — *"하루치 설명이 한국어 한 문단으로 나오고,
같은 입력에 **항상 같은 문장**이며, 설명하지 못한 몫이 `residual` 과
`missing_drivers` 로 **보인다**."*

## ★드라이버 집합이 둘이다 — 합치지 않는다★

    strategy_effects  전략 수준 5효과 분해   배분·선택·매크로·청산·비용
    holding_drivers   보유 수준 하루 분해    가격·리밸런스·수수료 (+ 미측정 둘)

둘은 **다른 질문에 답한다**. 한 목록에 넣으면 "배분 효과" 와 "가격" 이 나란히 놓여
합이 의미를 잃는다 — Z 에서 `kind`(무슨 성과)와 `data_real`(무슨 데이터)을 가른 것과
같은 규율이다. `DailyExplanation.driver_set` 이 어느 쪽인지 **선언**한다.

## ★설계 문서의 드라이버 다섯을 실측이 고쳤다★

도메인 문서 §5 는 `price`·`fx`·`dividend`·`rebalance`·`fee` 를 제안했다. 그런데
**일별 배당락·지급일 데이터가 없고**(연간 DPS 공시뿐) **해외 직접보유 데이터도 없다**.
그래서 `price` ⟂ `dividend` 분리는 ★데이터로 불가능★하다 — 수정주가를 쓰면 배당이
가격 축에 흡수되고, 원주가를 쓰면 배당락이 "손실" 로 보인다.

없는 축을 지어내지 않는다. 어휘에는 남기되 `UNMEASURABLE_DRIVERS` 가 **왜 못 재는지**
를 들고 있고, 문장이 그 이름을 부른다.

## ★잔차 어휘를 새로 만들지 않는다★

`attribution_decomposer` 가 이미 갈라 놓았다 — 커버리지가 완전하면 잔차는 복리
`interaction`, 불완전하면 복리와 미관측이 섞인 `unexplained`. 그 구분을 그대로 쓴다.

## ★결정론★

같은 입력에 같은 문장이 나와야 감사가 된다. 위험은 100번 부르는 것이 아니라
**상류의 딕트 삽입 순서**가 문장 순서로 새는 것이다 — 그래서 기여 절댓값 내림차순으로
정렬하고 **동률은 드라이버 이름 사전순**으로 깬다. LLM 이 아니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ══════════════════════════════════════════════════════════════════════════
# 드라이버 집합 둘
# ══════════════════════════════════════════════════════════════════════════
DRIVER_SET_STRATEGY = "strategy_effects"
DRIVER_SET_HOLDING = "holding_drivers"
DRIVER_SETS = (DRIVER_SET_STRATEGY, DRIVER_SET_HOLDING)

#: ★`attribution_decomposer.IDENTITY_DRIVERS` 와 **같아야 한다**★ — 테스트가 대조한다.
#: 여기 적어 두는 이유는 `src/domain/` 이 엔진을 import 하지 않기 위해서다(순수 계층).
#: ★수익률 항등식의 드라이버만이다★ (BH2) — `net = EW + alloc + cost (+ cash)`.
#: 예전 여섯(선택·매크로·청산 포함)은 수익률에 없는 네팅을 기여 순위에 올렸다.
STRATEGY_DRIVERS = ("baseline_effect", "allocation_effect", "cost_effect",
                    "cash_effect")

DRIVER_PRICE = "price"
DRIVER_REBALANCE = "rebalance"
DRIVER_FEE = "fee"
#: ★언제나 미측정★ — 아래 `UNMEASURABLE_DRIVERS` 가 사유를 들고 있다.
DRIVER_DIVIDEND = "dividend"
DRIVER_FX = "fx"

HOLDING_DRIVERS = (DRIVER_PRICE, DRIVER_REBALANCE, DRIVER_FEE,
                   DRIVER_DIVIDEND, DRIVER_FX)

#: 문장이 부르는 이름. 전략 다섯은 ★`attribution_decomposer._build_waterfall` 이
#: 이미 쓰는 한국어 그대로★ — 같은 것을 두 이름으로 부르지 않는다.
DRIVER_LABELS = {
    "baseline_effect": "동일가중 기준",
    "allocation_effect": "배분 효과",
    "selection_effect": "전략 선택",
    "macro_effect": "매크로 오버레이",
    "netting_effect": "청산 효과",
    "cost_effect": "거래 비용",
    # ★현금이자는 비용이 아니다★ (AL3) — 예전에는 `cost_effect` 에 더해져
    # "거래 비용" 이라는 이름으로 화면에 나갔다.
    "cash_effect": "현금 이자",
    DRIVER_PRICE: "가격 변동",
    DRIVER_REBALANCE: "그날의 매매",
    DRIVER_FEE: "수수료와 세금",
    DRIVER_DIVIDEND: "배당",
    DRIVER_FX: "환효과",
}

#: ★이 둘은 데이터가 없어서 못 잰다 — 구현이 게을러서가 아니다★
#: 누가 값을 넣으려 하면 **그 데이터부터** 필요하다는 사실을 여기가 말한다.
UNMEASURABLE_DRIVERS = {
    DRIVER_DIVIDEND: (
        "일별 배당락·지급일 데이터가 없습니다 — 연간 DPS 공시만 있어 그날 들어온 "
        "배당을 잴 수 없습니다. 연간 값을 일할 계산하면 그것은 관측이 아니라 추정입니다."),
    DRIVER_FX: (
        "해외 직접보유 데이터가 없습니다 — 이 저장소가 다루는 해외 노출은 원화 상장 "
        "ETF 라 환효과가 이미 가격 안에 들어 있고, 따로 떼어 낼 근거가 없습니다."),
}

# ══════════════════════════════════════════════════════════════════════════
# 잔차 — ★`attribution_decomposer` 의 구분 그대로★
# ══════════════════════════════════════════════════════════════════════════
#: 적재된 축의 커버리지가 **완전**할 때의 잔차 = 복리 상호작용.
RESIDUAL_INTERACTION = "interaction"
#: 커버리지가 불완전할 때 = 복리와 **미관측분**의 혼합. ★복리라 부를 수 없다★
RESIDUAL_UNEXPLAINED = "unexplained"
#: ★하루의 항등식이 닫힌다★ (BH2) — 하루에는 복리가 없으므로 드라이버가 전부 있으면
#: 잔차는 부동소수 오차뿐이다. 그것을 "복리 상호작용" 이라 부르면 없는 것을 말한다.
RESIDUAL_CLOSED = "closed"
RESIDUAL_KINDS = (RESIDUAL_INTERACTION, RESIDUAL_UNEXPLAINED, RESIDUAL_CLOSED)

#: 가격 기준 → 문장이 말할 한 절. `price_quality.BASIS_*` 와 키가 같다.
#: ★평문이다 — 마크다운 강조를 쓰지 않는다★ 이 문자열은 API 응답으로 나가고
#: 렌더러를 가정할 수 없다. `**` 가 그대로 보이면 그것이 곧 결함이다.
_BASIS_CLAUSE = {
    "uniform_raw": ("가격 축은 원주가 기준이라 배당락일의 하락이 손실처럼 "
                    "보일 수 있습니다"),
    "uniform_adjusted": ("가격 축은 수정주가 기준이라 배당이 가격 안에 녹아 "
                         "있고 따로 떼어 낼 수 없습니다"),
    "mixed": ("가격 축에 원주가와 수정주가가 섞여 있어 종목 간 비교가 같은 "
              "정의 위에 있지 않습니다"),
    "unknown": "가격 축이 어느 정의인지 알 수 없습니다",
}


#: `price_quality.BASIS_*` 의 값. 이 모듈은 순수 계층이라 그 모듈을 import 하지
#: 않고 **문자열 계약**만 공유한다(테스트가 둘을 대조한다).
BASIS_UNIFORM_RAW = "uniform_raw"
BASIS_UNIFORM_ADJUSTED = "uniform_adjusted"
BASIS_MIXED = "mixed"
BASIS_UNKNOWN = "unknown"


def fold_price_basis(basis_counts: dict[str, int] | None) -> str:
    """티커별 기준 개수 → **한 실행의 기준** 하나. ★순수 함수★

    ★전부-아니면-전무 계약이다★ — `price_quality.basis_rollup` 의 `state` 가 쓰는
    규율과 같다. 한 종목이라도 정의가 다르면 `mixed` 이고, 아무것도 라벨되지
    않았으면 `unknown` 이다(결함이 없다는 뜻이 **아니라** 재지 못했다는 뜻).
    """
    counts = {k: int(v) for k, v in (basis_counts or {}).items() if int(v or 0) > 0}
    if not counts:
        return BASIS_UNKNOWN
    if BASIS_MIXED in counts:
        return BASIS_MIXED
    labelled = {k for k in counts if k != BASIS_UNKNOWN}
    if len(labelled) > 1:
        return BASIS_MIXED
    if labelled:
        return next(iter(labelled))
    return BASIS_UNKNOWN


@dataclass(frozen=True)
class DailyExplanation:
    """하루 하나의 설명. ★값을 옮길 뿐 판정하지 않는다.★"""
    as_of: str
    scope: str            # portfolio | run
    scope_id: str
    driver_set: str
    total_change_pct: float | None
    #: 드라이버 → 기여(%p). ★미측정은 키를 빼지 말고 `None` 을 넣는다★
    drivers: dict[str, float | None] = field(default_factory=dict)
    #: 드라이버 → **왜** 못 쟀나. ★목록이 아니라 사전이다★ — 이름만 나열하면
    #: "왜 없는지" 가 사라지고, 그러면 다음 사람이 그 축을 0 으로 채운다.
    missing_drivers: dict[str, str] = field(default_factory=dict)
    residual_pct: float | None = None
    residual_kind: str | None = None
    residual_reason: str | None = None
    #: ★없는 축★ (BH2) — 미상과 다르다. 드라이버 → 왜 이 엔진에 없는지.
    #: (예: 현금 모델이 없는 엔진의 `cash_effect` — 수익률에도 들어 있지 않다)
    not_modeled: dict[str, str] = field(default_factory=dict)
    #: 보유 수준에서만. `{"basis": <price_quality.BASIS_*>, "reason": …}`
    price_basis: dict | None = None

    @property
    def summary_ko(self) -> str:
        return summarize_ko(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of, "scope": self.scope, "scope_id": self.scope_id,
            "driver_set": self.driver_set,
            "total_change_pct": self.total_change_pct,
            "drivers": dict(self.drivers),
            "missing_drivers": dict(self.missing_drivers),
            "residual_pct": self.residual_pct,
            "residual_kind": self.residual_kind,
            "residual_reason": self.residual_reason,
            "not_modeled": dict(self.not_modeled),
            "price_basis": self.price_basis,
            "summary_ko": self.summary_ko,
        }


#: 한글 음절 블록. 종성 유무로 조사를 고른다.
_HANGUL_START, _HANGUL_END = 0xAC00, 0xD7A3

#: 받침이 있는 것으로 치는 숫자·영문 끝소리. ★읽을 때의 소리로 정한다★
#: (예: "7" 은 "칠" 이라 받침이 있고, "2" 는 "이" 라 없다)
_CODA_DIGITS = {"0", "1", "3", "6", "7", "8"}


def _has_coda(word: str) -> bool | None:
    """마지막 글자에 받침이 있는가. ★판정할 수 없으면 `None`★"""
    w = (word or "").strip()
    if not w:
        return None
    ch = w[-1]
    code = ord(ch)
    if _HANGUL_START <= code <= _HANGUL_END:
        return (code - _HANGUL_START) % 28 != 0
    if ch.isdigit():
        return ch in _CODA_DIGITS
    return None


def _josa(word: str, with_coda: str, without_coda: str) -> str:
    """`word` 뒤에 붙는 조사. ★판정 불가면 받침 없는 쪽★ — 둘 중 하나는 써야
    문장이 되고, 어느 쪽이든 **같은 입력에 항상 같은 선택**이면 결정론은 지켜진다."""
    return with_coda if _has_coda(word) else without_coda


def _pct(v: float | None) -> str:
    return "미상" if v is None else f"{v:+.2f}%p"


def _ranked(drivers: dict[str, float | None]) -> list[tuple[str, float]]:
    """기여 절댓값 내림차순. ★동률은 이름 사전순으로 깬다★

    정렬이 불안정하면 같은 입력에 다른 문장이 나오고, 그 순간 이 모듈의 존재
    이유(감사 가능성)가 사라진다.
    """
    known = [(k, float(v)) for k, v in drivers.items() if v is not None]
    return sorted(known, key=lambda kv: (-abs(kv[1]), kv[0]))


def summarize_ko(exp: DailyExplanation) -> str:
    """★결정론적 한국어 한 문단★ — LLM 이 아니다.

    문장은 네(보유 수준은 다섯) 절로 고정된다:
      ① 전체 변동 ② 기여 순위 ③ 미측정 축 ④ 잔차 (⑤ 가격 기준)

    ★잔차 절은 절대 생략되지 않는다★ — 빠지면 읽는 사람이 "설명이 완전하다" 로
    받아들인다. 0 이어도, 미상이어도 자리를 지킨다.
    """
    parts: list[str] = []

    # ① 전체
    total = ("알 수 없습니다" if exp.total_change_pct is None
             else f"{exp.total_change_pct:+.2f}% 입니다")
    parts.append(f"{exp.as_of} 기준 {exp.scope_id}의 하루 변동은 {total}.")

    # ② 기여 순위
    ranked = _ranked(exp.drivers)
    if ranked:
        # ★구분자는 `, ` 다★ — 라벨 자체가 `·` 를 포함할 수 있어 `·` 로 잇면
        # 어디까지가 한 드라이버인지 읽는 쪽이 가를 수 없다.
        bits = ", ".join(f"{DRIVER_LABELS.get(k, k)} {_pct(v)}" for k, v in ranked)
        parts.append(f"기여가 큰 순서로 {bits} 입니다.")
    else:
        parts.append("기여를 잰 축이 하나도 없습니다.")

    # ③ 미측정 축 — ★이름을 부른다★
    if exp.missing_drivers:
        labels = [DRIVER_LABELS.get(k, k) for k in sorted(exp.missing_drivers)]
        names = ", ".join(labels)
        # ★조사는 **마지막** 낱말의 받침을 따른다★
        parts.append(f"{names}{_josa(labels[-1], '은', '는')} 재지 못했습니다.")

    # ③′ 없는 축 — ★미상과 다르다★ (BH2)
    if exp.not_modeled:
        labels = [DRIVER_LABELS.get(k, k) for k in sorted(exp.not_modeled)]
        names = ", ".join(labels)
        parts.append(f"{names}{_josa(labels[-1], '은', '는')} 이 엔진이 모델링하지 않는 "
                     "축입니다(수익률에 들어 있지 않습니다).")

    # ④ 잔차 — ★항상 있다★
    if exp.residual_pct is None:
        why = exp.residual_reason or "전체 변동 또는 축의 합을 알 수 없습니다"
        parts.append(f"잔차를 계산하지 못했습니다 — {why}.")
    elif exp.residual_kind == RESIDUAL_CLOSED:
        parts.append(
            f"축의 합이 실제 변동과 맞습니다(차이 {_pct(exp.residual_pct)} — 부동소수 "
            "오차).")
    elif exp.residual_kind == RESIDUAL_INTERACTION:
        parts.append(
            f"축의 합과 실제 변동의 차이 {_pct(exp.residual_pct)} 는 복리 "
            "상호작용입니다(적재된 축의 커버리지가 완전합니다).")
    else:
        why = exp.residual_reason or "일부 축의 커버리지가 불완전합니다"
        parts.append(
            f"설명하지 못한 몫 {_pct(exp.residual_pct)} 가 남았습니다 — {why}.")

    # ⑤ 가격 기준 — 보유 수준에서만
    if exp.driver_set == DRIVER_SET_HOLDING and exp.price_basis:
        clause = _BASIS_CLAUSE.get(str(exp.price_basis.get("basis")))
        if clause:
            parts.append(f"{clause}.")

    return " ".join(parts)
