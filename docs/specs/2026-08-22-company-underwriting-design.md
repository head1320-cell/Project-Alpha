# Company 언더라이팅 엔진 설계 — 대시보드에서 심사 엔진으로

> 마스터 프롬프트 1차 산출물 ③. **설계다. 구현은 승인 후.**
> 맥락은 [`2026-08-22-project-alpha-vnext-audit.md`](./2026-08-22-project-alpha-vnext-audit.md).

## 0. ★프롬프트의 7개 업그레이드 중 2개는 이미 있다★

프롬프트는 "단순히 비율을 더하지 말라" 고 했다. 그 말이 맞다 — 재 보니 이 저장소는
생각보다 앞서 있었다. **없는 것만 짓는다.**

| # | 프롬프트의 업그레이드 | 실측 판정 |
|---|---|---|
| 1 | 역DCF / 시장내재 가정 | **없음 (0건)** |
| 2 | 확률적 밸류에이션 P10~P90 | **없음 (0건)** |
| 3 | 이익의 질 | **★이미 있음★** `company_analytics.financial_deep` — 발생액비율, OCF−NI 갭, red flag R1(OCF<NI 3년) · R2(발생액 3년 상승) · R3(NWC/매출 3년 상승), Sloan 발생액 |
| 4 | ROIC vs WACC + 자본배치 | **★이미 있음★** 같은 함수 `:299-309` 가 ROIC−WACC 스프레드를, `waterfall` 이 자본배치를, `dupont` 이 분해를 낸다 |
| 5 | 매크로 민감도 | **없음 (0건)** — Company 경로에 `macro` 참조가 하나도 없다 |
| 6 | 구조화된 논지 + kill 조건 | **없음 (0건)** |
| 7 | 논지 → 형식 신호 → 백테스트 다리 | **없음** — 파이프라인에서 유일하게 끊긴 칸 |

따라서 실제 작업은 **5개**이고, 그중 3·4 는 **CompanySnapshot 이 담아 나르기만** 하면 된다.

---

## 1. CompanySnapshot — ★새로 발명하지 않는다★

이 저장소에는 이미 검증된 불변 스냅샷 패턴이 있다: `src/data/regime_snapshots.py`
(M1 의 MES). 불변·write-once·`as_of`·provenance·모델버전·조각별 `{available, reason}`
을 전부 갖췄고 라우트·프론트·테스트가 붙어 있다. **그 관례를 그대로 복제한다.**

| 관례 | MES | CompanySnapshot |
|---|---|---|
| 저장 | `_engine()` → `_ensure_table()` → raw SQL | 동일 |
| ID | `rgs_<ts>_<hex8>` | `cs_<ts>_<hex8>` |
| 확장 | ADD COLUMN (SQLite `IF NOT EXISTS` 미지원 → 예외 흡수) | 동일 |
| 불변 | write-once, 두 번째 쓰기는 `False` | 동일 |
| 미가용 | 키는 **값이 없어도 존재**, `{available:false, reason}` | 동일 |

### 스키마

| 컬럼 | 내용 | 출처(재사용) |
|---|---|---|
| `snapshot_id` PK | `cs_*` | — |
| `code` · `as_of` · `created_at` · `code_version` | 신원·감사 | — |
| `price` | 시점 시세 | `ohlcv_loader` |
| `financials` | 연간 시계열(PIT) | `dart_history.load_history` + `pit_store` |
| `publication_dates` | **관측일 ≠ 공표일** | `pit_store` |
| `valuation` | RIM/DCF/DDM 값 + **가정 전체** | `valuation_models.ValuationParams`/`compute_*` |
| `valuation_dist` | **P10/P25/P50/P75/P90** (§3) | 신규 |
| `implied` | **역DCF 산출 시장내재 가정** (§2) | 신규 |
| `quality` | 발생액·QoE·red flag·듀폰·**ROIC−WACC** | **`financial_deep` 그대로** |
| `factors` | 팩터 노출 | `FundamentalsStore.get_factors` |
| `peers` | 비교군 | `comps_table` |
| `macro_sensitivity` | **국면·지표 민감도** (§4) | 신규 (`regime_drivers` 재사용) |
| `risk` | 리스크 | `risk_deep` |
| `thesis` | **논지·촉매·kill 조건** (§5) | 신규 |
| `provenance` | 소스·`verified_live`·미가용 사유 | `source_registry` |

★`quality` 는 계산을 옮기지 않고 **호출해서 담는다**★ — 같은 산수를 두 곳에 두면
반드시 갈라진다. 이 저장소가 A1(`currentSig`/`req`)과 R0(오버레이 컴파일)에서
두 번 겪었다.

---

## 2. 역DCF — 새 모델이 아니라 기존 함수의 역함수

`valuation_models.py:216 compute_dcf(...)` 는
`가정(성장률·마진·WACC·영구성장) → 내재가치` 다. 역DCF 는 그 반대다:
**현재 시가총액을 정당화하려면 어떤 가정이 필요한가.**

- 미지수 하나(예: 향후 N년 FCF 성장률)를 두고 `compute_dcf(...) == market_cap` 을
  **1차원 근 찾기**로 푼다. scipy `brentq` 는 이미 의존성에 있다(QuantLib·scipy 사용 중).
- 단조성이 깨지거나 구간에 근이 없으면 **숫자를 내지 않고 사유를 낸다**
  (`{available:false, reason}`) — `compute_dcf:238` 의 `wacc = max(wacc, 0.03)` 클램프와
  `(wacc - g) > 0.001` 가드가 만드는 불연속이 실재한다.
- 산출: 시장내재 성장률 · 시장내재 마진 · **현재 가정과의 격차**. 이것이 "시장은 무엇을
  믿고 있는가" 이고, 언더라이팅의 출발점이다.

## 3. 확률적 밸류에이션 P10~P90

같은 세 함수(`compute_rim`/`compute_dcf`/`compute_ddm`)를 **파라미터 분포로 감싼다.**
새 밸류에이션 모델을 만들지 않는다.

- `ValuationParams` 의 `risk_free_rate`·`market_premium`·`beta`·`terminal_growth_rate`
  에 분포를 준다. 상관을 무시하지 않는다 — 최소한 Rf 와 g 는 같이 움직인다.
- 표본 N 회 → 내재가치 분포 → **P10/P25/P50/P75/P90**.
- ★현재 주가가 그 분포의 몇 분위인지★ 를 함께 낸다. 이것이 football field 를
  "그림" 에서 "확률 진술" 로 바꾼다.
- **분포의 폭을 축소해 보이게 하지 않는다.** 표본이 적거나 가정이 넓으면 넓게 나온다.
  P4-MACRO 의 conformal 처리와 같은 원칙 — 구간을 좁혀 잘 맞히는 것처럼 보이게 하지 않는다.

## 4. 매크로 민감도 — P4-MACRO 자산 재사용

Company 경로에 `macro` 참조가 **0건**이다. 이미 만든 것을 붙이기만 하면 된다:

- `src/engine/regime_drivers.py` — **정확 Shapley**(32 부분집합 전수, 근사 아님).
- `src/services/macro_collector.py` — ECOS 40 + FRED 21 계열.
- `src/engine/regime_ensemble.py` — 국면 3도구.

산출: 종목 수익 ↔ 매크로 계열의 민감도, **국면별 조건부**. 표본이 모자라면 사유.
★그레인저·상관은 인과가 아니다★ 를 라벨로 남긴다 — `causal_deepm` 이 이미 쓰는 문구.

## 5. 구조화된 논지 + kill 조건 → 신호 → 백테스트 (프롬프트 6·7)

파이프라인에서 유일하게 끊긴 칸이다.

- **논지**: 주장 · 근거(스냅샷 필드 참조) · 촉매(기한 있음) · **kill 조건**.
- **kill 조건이 곧 형식 신호다.** 자유 텍스트로 두면 검증할 수 없다. 그래서
  `src/engine/filter_ast.py` 의 **`FIELD_BY_ID` 레지스트리**로 표현한다 — 스크리너·
  백테스트가 이미 쓰는 단일 필드 계약이다.
  ★새 DSL 을 만들지 않는다★ CLAUDE.md: 새 필터 kind 는 `validate()` 의 bypass 튜플에
  반드시 등록.
- 그러면 논지가 **그대로 백테스트 조건**이 된다: `buy_conditions`/`sell_conditions`
  (`ScreenToBacktestRequest`). 다리를 새로 놓는 게 아니라 **이미 있는 다리에 올린다.**
- 결과는 `rr_*`/`bt_*` 로 이어져 재현 사슬에 들어간다.

---

## 6. 관측성 (프롬프트 요구)

| 항목 | 방법 |
|---|---|
| 콜드/웜 지연 | 스냅샷 미스/히트 |
| DART/KIS 호출 수 | 클라이언트 카운터. **DART 쿼터 20,000/일** 이 실제 제약 |
| DB 읽기 | SQLAlchemy `before_cursor_execute` (백테스트 하네스와 동일 기법) |
| 밸류에이션 시간 | 세 모델 + 분포 표본 |
| 캐시 적중/미스 | 스냅샷 |
| 페이로드 크기 | 직렬화 바이트 |
| **미가용 데이터 카운트** | `{available:false}` 조각 수 — ★이 값이 오르면 화면이 조용히 비어 간다는 뜻★ |

★CompanySnapshot 자체가 DART 쿼터 방어다★ — 같은 종목·같은 `as_of` 를 두 번 받지 않는다.

## 7. 반드시 지키는 것

- **종목명**: `stock_master.get_stock_name()`/`resolve_name()` 단일 출처.
  `"Unknown Corp"`·가짜 종목코드 재도입 금지 (CLAUDE.md).
- **수치 안전**: 분수승·로그·제곱근에 음수가 들어갈 수 있는 파생식은 가드.
  ★적자기업 실데이터에서만 터진다 — mock 은 항상 흑자라 테스트를 통과한다★ (CLAUDE.md).
  역DCF 와 확률 표본이 정확히 이 위험 구간이다.
- **PIT**: 관측일 ≠ 공표일. 스냅샷은 `as_of` 시점에 **알 수 있었던 것만** 담는다.
- **미가용은 0 이 아니다**: `0` ≠ 미계산 ≠ 산출 불가. `EvidenceBadge` 어휘 재사용.

## 8. 첫 슬라이스 (권고)

**CompanySnapshot 저장소 + 기존 값(`financial_deep`·`valuation`·`factors`) 담기.**
새 모델을 하나도 안 짓고 **그릇과 재현 좌표만** 만든다. 그 위에 역DCF → 확률 →
매크로 민감도 → 논지 순으로 얹는다. 그릇이 없으면 뒤의 넷은 저장할 곳이 없다.
