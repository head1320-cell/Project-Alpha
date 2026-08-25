# 정준 자산군 / 경제노출 분류 계약 — 설계 (Phase 7)

> ★계약과 매핑 규약만 정의한다. 대규모 매핑을 만들지 않는다.★
> 선행: [`GroupConstraint`](2026-08-26-group-constraint-contract.md) ·
> [`RelativeView`](2026-08-26-relative-view-contract.md) — 둘 다 이것을 기다린다.

---

## 0. 지금 저장소에 있는 것 — ★둘 다 자산군이 아니다★

| 후보 | 실제 내용 | 왜 못 쓰나 |
|---|---|---|
| `constrained_opt.sector_groups_for` | genport **테마·섹터** | 자산군이 아니다. 그리고 ↓ |
| `market_impact.ASSET_CLASS_TIERS` | `kospi_mid` 등 **유동성 티어** | 시총·시장 구분이지 경제적 노출이 아니다 |

`sector_groups_for` 의 실제 구현(확인함):

```python
try:
    ...
    return {t: assign[t] for t in names if t in assign}
except Exception:
    return {}
```

★두 겹의 무음 실패가 있다★
1. 예외 → `{}` — 제약이 **통째로 사라진다**.
2. 예외가 없어도 `if t in assign` 이 **부분 배정**을 낸다 — 절반만 분류된 유니버스가
   정상처럼 보인다.

상대 뷰와 그룹 제약에서 **분류는 계약**이다. 조용히 비면 "뷰가 사라졌는데 응답은
정상" 이 되고, 부분 배정이면 "EQ−FI 스프레드" 가 실제로는 "EQ 일부 − FI 일부" 가 된다.
★후자가 더 위험하다 — 아무 신호도 나지 않는다.★

---

## 1. ★3층을 분리한다★

```
Instrument   ─(1:1)→   AssetClass
     │
     └───────(1:N)→   EconomicExposure   (부하 계수 포함)
```

**셋은 서로 다른 것이다.** 하나의 상품이 여러 경제노출을 갖는다:

| 예 | AssetClass | EconomicExposure (부하) |
|---|---|---|
| 하이일드 채권 ETF | `CREDIT` | 신용스프레드 0.8 · 듀레이션 0.4 · 주식베타 0.35 · 유동성 0.3 |
| 국고채 10년 | `RATES` | 듀레이션 1.0 |
| 원유 선물 | `COMMODITY` | 원자재베타 1.0 · 인플레 0.6 · USD −0.3 |
| KOSPI200 ETF | `EQUITY` | 주식베타 1.0 · USD −0.2 |
| MMF | `CASH` | 유동성 1.0 |

★`AssetClass` 를 노출로 쓰면 하이일드가 "채권" 이 되어 주식베타 0.35 가 사라진다.★
`EconomicExposure` 를 자산군으로 쓰면 한 상품이 여러 그룹에 들어가 그룹 비중 합이
1 을 넘는다 — 그룹 제약이 정의되지 않는다. **그래서 둘 다 필요하고, 섞으면 안 된다.**

### AssetClass (배타적 · 전수)

```
EQUITY · RATES · CREDIT · FX · COMMODITY · REAL_ASSET · CASH
```

배타적이므로 **그룹 제약(Phase 6)의 `group_id` 는 여기서만** 나온다.

### EconomicExposure (중첩 · 부하 있음)

```
EQUITY_BETA · DURATION · CREDIT_SPREAD · INFLATION · COMMODITY_BETA ·
USD · LIQUIDITY · VOLATILITY
```

`EconomicExposureRelativeView` 의 `P` 행은 여기서 나온다 — 노출 행렬 `B` 의
열을 **디민한 것**(`b − b̄`)이 예산중립 행이 된다. 팩터 상대 뷰와 같은 기하다.

---

## 2. 매핑 계약

```python
@dataclass(frozen=True)
class Classification:
    instrument_id: str          # 안정 ID (티커가 아니다 — 티커는 바뀐다)
    asset_class: AssetClass | None      # None = 명시적 미배정
    exposures: tuple[tuple[str, float], ...]  # (노출 ID, 부하)
    as_of: str                  # ★이 분류가 유효해진 날★
    source: str                 # 어디서 왔나
    version: str
    unassigned_reason: str | None       # asset_class 가 None 이면 필수
```

### 필수 속성

| # | 속성 | 규칙 |
|---|---|---|
| 1 | **안정 ID** | 티커 재사용·상장폐지에도 불변. 티커는 별칭 테이블 |
| 2 | **버전** | 분류 체계가 바뀌면 버전이 오른다 |
| 3 | ★**`as_of`**★ | 리밸런싱 시점에 **알 수 있었던** 분류를 쓴다 |
| 4 | **출처** | 사람이 정했는지, 규칙이 정했는지 |
| 5 | ★**전수 배정 요구**★ | 뷰·제약이 쓰는 유니버스에는 미배정이 있으면 **거부** |
| 6 | ★**명시적 미배정**★ | `None` + `unassigned_reason`. `{}` 로 사라지지 않는다 |
| 7 | **결정성** | 같은 입력 → 같은 출력. 외부 호출 실패가 분류를 바꾸지 않는다 |

### ★`as_of` 가 왜 룩어헤드인가★

리츠가 2019년에 `REAL_ASSET` 로 재분류됐다고 하자. 2015년 백테스트에 그 분류를
쓰면 **2015년의 나는 몰랐던 것**을 쓴 것이다. 자산군 상대 뷰에서 이것은 조용히
성과를 만든다 — 재분류는 보통 **그 자산의 성격이 드러난 뒤에** 일어나기 때문이다.

`revision_bias`(매크로 계열)와 **같은 계열의 오류**이고, PIT 3필드와 같은 규율이
분류에도 필요하다.

---

## 3. 관측 가능성 — ★빠진 분류가 보여야 한다★

```json
{"universe": 42, "classified": 38, "unassigned": 4,
 "unassigned_ids": ["A123456", "..."],
 "reasons": {"no_mapping": 3, "ambiguous": 1},
 "version": "2026.1", "as_of": "2026-08-26"}
```

- 뷰·제약이 이 블록을 **응답에 싣는다**. 4개가 빠졌다는 사실이 화면에 남는다.
- `strict` 모드(상대 뷰 기본, Phase 2 Q10)에서는 **미배정이 하나라도 있으면 거부**.
- ★`{}` 를 돌려주는 경로를 남기지 않는다.★ 실패는 예외이거나 명시적 미배정이다.

---

## 4. 실계열 최소 요구 (Phase 9 항목 1·2·5)

| 조건 | 값 |
|---|---|
| 투자가능 상품 | 6~10 |
| 경제적으로 구분되는 `AssetClass` | ★4개 이상★ |
| 각 상품의 `EconomicExposure` 부하 | 전수 |
| 분류 버전·`as_of` | 존재 |

★한국 유니버스에서 4개 자산군을 만들 수 있는지가 실제 병목이다.★ `EQUITY`·`RATES`
는 쉽고, `CREDIT`·`COMMODITY`·`FX` 는 국내 상장 ETF 커버리지 확인이 필요하다.
그 확인은 **데이터 조사**이지 설계가 아니므로 여기서 답하지 않는다 — **unknown**.

## 5. 하지 않은 것

분류 모듈 구현 · 실제 매핑 작성 · `sector_groups_for` 수정 · 노출 행렬 추정.
합성 실험은 `t3_transmission.class_of`(티커 접두사)로 **우회했고**, 그 함수는
자신이 합성 전용임을 독스트링에 적고 있다.
