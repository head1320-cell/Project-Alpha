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
  (`{available:false, reason}`).
- ~~`compute_dcf:238` 의 `wacc = max(wacc, 0.03)` 클램프와 `(wacc - g) > 0.001` 가드가
  만드는 불연속이 실재한다.~~
  **★구현하며 정정(2026-08-22) — 격자 실측★** FCF 성장률을 미지수로 두면 **그 둘은
  불연속을 만들지 않는다.** `wacc` 는 `params.ke`·자본구조·`tax_rate` 에서만 나오고
  `fcf_growth_rates` 가 들어가지 않으며(실측: g=−0.30 과 g=+0.40 에서 둘 다 8.27%),
  `(wacc - g)` 의 `g` 는 `params.terminal_growth_rate` 이지 미지수가 아니다(둘 다 2.0%).
  함수 이름이 그럴듯해 보였을 뿐 **미지수와 무관한 상수**다.

  진짜 불연속은 셋이고 전부 실측했다(mock 삼성전자, 41점 격자):
  1. `per_share = max(0, equity_value/shares)` — **g ≤ −0.125 에서 0 으로 평평**.
  2. `round(per_share, 0)` — 원 단위 **계단함수**(계단 폭 Δg ≈ 1.7e-6 당 1원).
     → 허용오차를 가격이 아니라 **성장률**에 걸고, 달성 내재가와 시장가의 격차를
     함께 보고한다.
  3. `fcf_base <= 0 or shares <= 0` → 모든 g 에서 `available=False`, **근이 아예 없다.**
     ★적자·마이너스 FCF 기업이 정확히 여기다★(CLAUDE.md: mock 은 항상 흑자다).

  `(wacc - g) > 0.001` 은 **영구성장률을 미지수로 둘 때** 진짜 절벽이 된다 — TV 가
  통째로 0 으로 떨어진다. 그 축의 브래킷 상한이 WACC 아래인 근거가 이것이다.
- 산출: 시장내재 성장률 · **현재 가정과의 격차**. 이것이 "시장은 무엇을 믿고 있는가"
  이고, 언더라이팅의 출발점이다.
- ~~시장내재 마진~~ **★정정★** `compute_dcf` 는 FCF 를 **수준**으로 받지 매출×마진으로
  받지 않는다 — 매출과의 연결이 함수 안에 없으므로 진짜 내재 마진은 **매출 구동 DCF**
  라는 새 모델을 요구한다(Brief §18 후순위). 대신 이미 푼 해에서 파생되는 것만 낸다:
  FCF 궤적(새 가정 0)과, **오늘 매출을 고정했을 때**의 비율을 `assumes_flat_revenue`
  라벨과 **함께만**. 라벨 없이 "내재 마진" 이라 부르면 그것이 조용한 날조다.
- **현재 가정과의 격차**는 기본 성장 궤적의 기하평균이 아니라, 기본 경로가 낸 주가를
  재현하는 **상수 성장률을 같은 solver 로** 풀어서 낸다 — 궤적 공식을 두 곳에 두지
  않고 사과 대 사과가 된다.

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

---

# 부록 — 실측 근거와 `.md` §17·§19 보강 (2차 감사)

## C.1 CompanySnapshot 의 정량 근거 (실측)

`scripts/bench_company.py` 로 잰 것(벤치 문서 §6.5):

| 관측 | 값 | 스냅샷이 바꾸는 것 |
|---|---|---|
| 콜드 페이지 로드 | 83 ms (엔드포인트 8개) | 1회 조회로 축약 가능 |
| **`comps_table` DB 쿼리** | **48** | 피어 집합을 스냅샷에 담으면 재조회 0 |
| **`risk_deep` 내부 중복** | `_annual_rows` **2회** | 한 번 읽어 넘김 |
| 딥 탭 재무이력 읽기 | **3회** | **1회** |
| `evaluate` 호출 | **3회**(base/bull/bear) | 재무 1회 + 가정 3벌 |

★이 표에서 주장하지 **않는** 것★ `evaluate` 3회의 반복 비용은 실측 0.2 ms 로 사실상
0 이다 — DART 키가 없어 mock 재무로 계산하기 때문이다(`is_mock: true`). 실 키
환경에서는 재무제표 파싱이 3번 반복되므로 이 값은 **하한**이고, "스냅샷이 X ms 를
아낀다" 는 문장은 **실 키 재측정 전까지 쓰지 않는다.**

확실한 것은 시간이 아니라 **구조**다: 같은 재무이력을 3번 읽고, 같은 피어 질의를
48쿼리로 매번 다시 하고, 같은 가정 3벌을 위해 전체 스택을 3번 돈다.

## C.2 (§17) 이익의 질 — 이미 있는 것 위에 무엇을 얹는가

`financial_deep` 이 이미 낸다: 발생액비율 · OCF−NI 갭 · red flag R1~R3 ·
NWC/매출 · 듀폰 · 자본배치 워터폴 · ROIC−WACC 스프레드 · Sloan 발생액.

`.md` §17 이 더 요구하는 것 중 **실제로 없는 것**만:

| 항목 | 판정 |
|---|---|
| 현금전환(CCC) | 없음 — NWC 구성요소가 있으므로 파생 가능 |
| 일회성 항목 | 없음 — DART 계정과목 매핑 필요 |
| 마진 지속성 | 없음 — 시계열 분산/추세로 파생 가능 |
| 매출의 질 | 없음 — 매출채권 증가율 vs 매출 증가율 |
| capex 강도 | 부분 — 워터폴에 capex 가 있다 |
| 주식보상 · 리스부담 · 차환위험 | **데이터 없음** — DART 표준계정에서 안정적으로 못 뽑는다. ★없으면 없다고 적는다★ |

Altman/Beneish 는 `risk_deep` 에 있고, `.md` 대로 **구성요소로 강등**하되 지우지 않는다.

## C.3 (§19) 매크로 민감도 — 출력 형식을 고정한다

`.md` 가 요구한 형태는 서술이 아니라 **수치**다:

```
+100bp 10Y  → 적정가치 −8.4%
GDP −2σ     → EPS −11.2%
USD +10%    → EPS +4.7%
Oil +30%    → EBIT +5.1%
```

계약:
- **AI 가 서술하지 않는다**(`.md` §19). 계산된 수치이고 provenance 가 남는다.
- 각 줄은 `{shock, unit, target, value, method, n_obs, available, reason}` 를 갖는다.
- 표본이 얇으면 **숫자를 내지 않고 사유를 낸다** — 매크로 계열이 60개월이므로
  이것이 기본 경로가 될 수 있다. P4-MACRO 가 `span` 으로 세운 관례와 동일.
- 재사용: `regime_drivers`(정확 Shapley) · `macro_collector`(ECOS 40 + FRED 21) ·
  `regime_ensemble`.
