# `GroupConstraint` 계약 — 설계 (Phase 6)

> 측정 근거: `scripts/t3_transmission.py --arch D` 의 `constraint_audit` ·
> 가드: `tests/test_t3_const_control.py`
> ★계약 정의다. 구현하지 않았다.★ 광범위 리팩터링 금지.

---

## 0. 왜 지금인가 — ★감사가 공백을 매 리밸런싱마다 인쇄한다★

`constraint_audit` 의 `effective_bounds` 는 그룹마다 `(하한, 상한)` 쌍을 낸다.
그 **하한은 언제나 `0.0`** 이다. `Constraints` 에 그룹 하한이 없기 때문이다
(`src/engine/constrained_opt.py` — `group_caps_pct` 만 존재, 8개 참조 지점 전부 상한).

실측 감사행:

```json
{"source": "regime_group_caps", "effective_bounds": {"EQ": [0.0, 100.0],
 "FI": [0.0, 94.97]}, "binding": ["FI"]}
```

★그리고 이 줄이 T3-D 결론의 정체를 드러냈다★ — D2 의 이득은 "EQ 상한" 이 아니라
**FI 상한**에서 온다. `Σw = 1` 에서 FI 상한은 EQ **하한**으로 작동한다.
자산군이 **둘이고 완전투자일 때만** 성립하는 우회다.

| 자산군 수 | "FI ≥ 40%" 를 표현할 수 있나 |
|---|---|
| 2 (EQ·FI), 완전투자 | ✔ 우회 가능 — `EQ ≤ 60%` |
| 3+ | ★**표현 불가**★ — 나머지를 다 눌러도 어디로 갈지 정할 수 없다 |

Phase 9 게이트가 **경제적으로 구분되는 자산군 4개 이상**을 요구하므로,
실계열로 가는 순간 이 우회는 **작동을 멈춘다.**

---

## 1. 계약

```python
@dataclass(frozen=True)
class GroupConstraint:
    group_id: str            # 정준 분류의 안정 ID (Phase 7)
    min_weight: float        # 0.0~1.0. ★일급 하한★
    max_weight: float        # 0.0~1.0
    as_of: str               # 이 제약이 정해진 시점 (YYYY-MM-DD)
    source: ConstraintSource # 아래 5종
    version: str             # 제약 세트의 버전
    rationale: str           # ★왜 걸었는지 — 없으면 완화 순서를 정할 수 없다★
    dynamic: bool            # 시점마다 재계산되나
    regime_dependency: str   # none | per_rebalance | frozen_at_<t>
```

### 불변식

| # | 규칙 | 왜 |
|---|---|---|
| 1 | `0 ≤ min ≤ max ≤ 1` | — |
| 2 | ★`Σ min_weight ≤ 1 ≤ Σ max_weight`★ | 아니면 완전투자가 **구조적으로** 불가능. 풀기 전에 거부한다 |
| 3 | 미배정 자산이 있으면 **거부** | 그룹 합이 무엇을 뜻하는지 정의되지 않는다 |
| 4 | `dynamic=False` 면 `regime_dependency ∈ {none, frozen_at_*}` | 정적인데 국면 의존은 모순 |
| 5 | 같은 `group_id` 에 둘 이상이면 **교집합** | `min` 은 최대, `max` 는 최소. 충돌(교집합 공집합)은 거부 |

★불변식 2 가 지금 실험이 손으로 하고 있는 일이다★ — `regime_group_caps` 는
상한 합이 100 미만이면 비례 확대한다. 그 확대가 곧 "하한이 없어서 생긴 우회" 다.
계약이 생기면 그 우회를 지운다.

---

## 2. ★출처를 타입으로 가른다★ — 같은 숫자라도 완화 순서가 다르다

```python
class ConstraintSource(str, Enum):
    MANDATE            = "mandate"             # 위임 계약·투자설명서
    LIQUIDITY          = "liquidity"           # 체결 가능성
    RISK               = "risk"                # 리스크 한도
    MACRO_DERIVED      = "macro_derived"       # ★국면이 만든 것★
    OPTIMIZER_SAFEGUARD = "optimizer_safeguard" # 수치 안정용
```

**완화 순서(해가 없을 때 무엇부터 푸나)** — `constrained_opt` 의 `skip` 로직이
이미 이 순서를 필요로 하는데, 지금은 그것을 **하드코딩된 이름**으로 판단한다:

```
optimizer_safeguard  →  macro_derived  →  risk  →  liquidity  →  mandate
    (먼저 푼다)                                              (마지막까지 지킨다)
```

★`mandate` 를 매크로 때문에 푸는 일이 절대 없어야 한다.★ 그리고 이 순서가
Phase 5 의 계층 귀속과 정확히 맞물린다 — `mandate/risk/liquidity` 는
**Portfolio Policy** 이고 `macro_derived` 만 **Macro → Policy 브리지**다.

★같은 그룹에 정책 하한과 매크로 하한이 동시에 걸릴 수 있다★ 그때 유효 하한은
둘 중 **큰 쪽**(불변식 5)이고, 감사행은 **어느 쪽이 물렸는지**를 낸다.
"매크로가 40% 를 요구했는데 정책이 이미 50% 였다" 와 "매크로가 50% 를 만들었다"
는 완전히 다른 사실이고, 지금은 구분할 방법이 없다.

---

## 3. 감사 계약

제약 하나가 실제로 무엇을 했는지가 리밸런싱마다 기록돼야 한다
(`constraint_audit` 을 일반화):

```json
{"t": "2021-07", "group_id": "FI", "min_weight": 0.40, "max_weight": 1.0,
 "source": "mandate", "version": "2026.1", "as_of": "2026-01-01",
 "dynamic": false, "regime_dependency": "none",
 "binding": "min", "achieved": 0.40,
 "overridden_by": null, "evidence_grade": "..."}
```

`binding ∈ {none, min, max}` — ★`binding` 이 늘 `none` 이면 그 제약은 존재하지 않는
것과 같고, 그 사실이 보여야 한다.★

---

## 4. 이번에 하지 않는 것

- `Constraints` 리팩터링 · SLSQP 하한 제약 추가 · 5종 출처 구현 · 완화 순서 배선.
- ★실험 스크립트의 비례 확대 우회도 지금은 **그대로 둔다**★ — 그것이 공백의 증거이고,
  `tests/test_t3_const_control.py::test_effective_bounds_always_carry_a_lower_bound`
  이 하한이 생기는 순간 red 가 되어 계약 변경을 알린다.

## 5. 선행조건

★Phase 7 의 정준 분류가 먼저다.★ `group_id` 가 안정적이고 전수 배정되지 않으면
불변식 3(미배정 거부)을 만족시킬 수 없고, 그러면 이 계약은 `sector_groups_for` 의
조용한 부분배정 문제를 그대로 물려받는다.
