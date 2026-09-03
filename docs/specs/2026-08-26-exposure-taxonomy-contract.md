# 정준 자산군 / 경제노출 분류 계약 — 설계 (Phase 7)

> ★계약과 매핑 규약만 정의한다. 대규모 매핑을 만들지 않는다.★
>
> ### ★2026-08-26 구현됨 — 두 곳을 되돌렸다★
> `src/data/exposure_taxonomy.py` (레지스트리 **55종** · 국내 35 + 미국 20) · `tests/test_exposure_taxonomy.py` (31)
> 1. ★**부하 계수를 담지 않는다**★ — 아래 §1 은 노출마다 부하를 두자고 적었으나,
>    그대로 하면 `credit 0.8 · duration 0.4` 같은 **숫자를 지어내게** 된다.
>    구현은 **상품 정의에서 따라 나오는 노출 이름만** 선언한다. 부하는
>    `factor_exposure` 가 데이터에서 재는 것이다.
> 2. ★**통화 노출도 담지 않는다**★ — 통화 노출은 상품의 성질이 아니라 투자자의
>    기준통화 + 헤지 여부의 함수다. `listing` 만 기록한다.
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
     └───────(1:N)→   EconomicExposure   (~~부하 계수 포함~~ → ★이름만★, 위 정정 1)
```

**셋은 서로 다른 것이다.** 하나의 상품이 여러 경제노출을 갖는다:

★아래 표의 부하 숫자는 **구현하지 않았다**★ — 개념 설명으로만 읽을 것.

| 예 | AssetClass | EconomicExposure (~~부하~~ · 구현은 이름만) |
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
    exposures: tuple[str, ...]  # ★이름만★ (초안의 (ID, 부하) 를 되돌렸다)
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
| 각 상품의 `EconomicExposure` **이름** | 전수 ✔ (부하는 별건) |
| 분류 버전·`as_of` | 존재 |

### ★"unknown" 이었던 것의 답 (2026-08-26 실측)★

국내 상장만으로 **3개 자산군**이 나온다 — `stock_master.ETF_NAMES`(40종, 체크인):

| 자산군 | 국내 상장 |
|---|---|
| `EQUITY` | 34종 (지수·섹터·테마·해외추종) |
| `RATES` | 3종 — 273130 종합채권액티브 · 153130 단기채권 · 214980 단기채권PLUS |
| `COMMODITY` | 2종 — 132030 골드선물(H) · 130680 원유선물Enhanced(H) |
| `CREDIT`·`FX`·`REAL_ASSET` | ★없음★ |

★처음에 "국내는 주식뿐" 이라고 보고했던 것은 틀렸다★ — `ticker_universe` 의
"Korea ETF" 8종만 보고 `ETF_NAMES` 40종을 놓쳤다.

**4번째 자산군은 미국 상장으로만 채워진다**(`CREDIT` = LQD·HYG, `REAL_ASSET` = VNQ).
그런데 `etf_prices.py` 가 US 실시세를 **mock 폴백**이라고 적고 있다.
→ 게이트 조건 5(자산군 4개+)는 **분류가 아니라 가격 데이터가 병목**이다.
레버리지·인버스 5종은 배정하지 않는다(사유: `directional_or_leveraged`).

## 5. 하지 않은 것 (2026-08-26 기준)

★분류 모듈과 레지스트리는 **구현했다**.★ 아직 안 한 것:

- ★`sector_groups_for` 교체★ · `constrained_solve(groups_of=)` 호출부 2곳
  (`allocation_backtest.py:66` · `allocation_routes.py:953`) — **둘 다 배분 결정이라
  Macro→Allocation 정책 로직**이고, 이번 승인 범위 밖이다.
- `view_rows.group_spread_row` 배선 · 노출 **부하** 추정 · US 실시세.
- `instrument_selector.EXPOSURES` 의 어휘 정리 — 독스트링에 4/13 사실만 적어 두었다.

합성 실험은 계속 `t3_transmission.class_of`(티커 접두사)를 쓴다 — 그 함수는 자신이
합성 전용임을 독스트링에 적고 있고, 정준 분류로 갈아끼우는 것도 별건이다.
