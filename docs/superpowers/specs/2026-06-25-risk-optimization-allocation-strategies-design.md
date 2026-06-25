# 리스크·최적화 기반 자산배분 전략 9종 추가 (13 → 22)

> Macro Allocation Cockpit의 택티컬 전략 라이브러리를 모멘텀 일변도에서
> **리스크 기반 + 최적화 기반 + 추세추종**으로 확장. 퀀트 학계·헤지펀드에서
> 각광받는 전략을 현 아키텍처(시점 가중치 벡터, long-only, 합100, US/KR 토글)에 맞춰 이식.

날짜: 2026-06-25 · 브랜치: `claude/keen-thompson-bdk3e8`

---

## 1. 배경 / 문제

`src/engine/tactical_allocations.py`의 기존 13전략은 **전부 모멘텀·추세 타이밍 로테이션**이다
(절대/상대 모멘텀·13612W·가속·이동평균 타이밍). 자산 선택만 모멘텀으로 하고 **비중은 동일가중 또는
고정**이며, **공분산을 한 번도 계산하지 않는다.**

→ 자산배분의 나머지 절반인 **리스크 기반(공분산 구동) / 최적화 기반 / 추세추종(매니지드 퓨처스)** 이
통째로 비어 있다. 학계·업계에서 "각광받는" 전략 대부분이 이 영역이다(Bridgewater 리스크패리티,
López de Prado HRP, AQR 추세추종, TOBAM 최대분산, Goldman 블랙-리터만).

현 아키텍처는 이 확장에 적합하다: 각 전략은 `monthly_closes/daily_closes`로부터 **시점 가중치 벡터**를
내는 순수 함수이고, 리스크 기반 전략도 "트레일링 수익률 → 공분산 → 가중치"인 시점 계산이다.
numpy/scipy/sklearn 사용 가능(확인: scipy 1.13.1, sklearn 1.5.0), long-only·합100(`_norm`)도 그대로 맞는다.

---

## 2. 로스터 (신규 9종, 13 → 22)

공통 유니버스(별도 명시 없으면): **크로스에셋 8종** = `SPY EFA EEM TLT IEF GLD PDBC VNQ`
(주식 3·채권 2·금·원자재·리츠 — 기존 FAA/AAA가 쓰는 것 재사용). 모두 `US_UNIVERSE`에 존재 확인.
공분산 룩백: **36개월**(`monthly_closes` 37 close → 36 수익률), 공통 최소길이로 절단.

| id | 이름 | family | 출처 | 알고리즘(요약) |
|---|---|---|---|---|
| `equal_weight` | 동일가중 1/N | benchmark | DeMiguel·Garlappi·Uppal 2009 | wᵢ = 100/N. 최적화 전략 비교 기준선 |
| `risk_parity` | 리스크 패리티(ERC) | risk | Bridgewater All Weather, AQR | 각 자산 리스크 기여 동일화. 반복 risk-budgeting |
| `hrp` | 계층적 리스크 패리티 | risk | López de Prado 2016 | corr→거리→계층 클러스터링→재귀이분(역분산) |
| `min_var` | 최소분산 | risk | Markowitz 코너, 저변동성 | min wᵀΣw, w≥0, Σw=1 (SLSQP) |
| `max_div` | 최대분산 | risk | Choueifaty 2008 (TOBAM) | max (wᵀσ)/√(wᵀΣw), w≥0, Σw=1 |
| `max_sharpe` | 최대 샤프(탄젠시) | optim | Markowitz | max (wᵀμ)/√(wᵀΣw), Ledoit-Wolf 수축 Σ |
| `black_litterman` | 블랙-리터만 | optim | Black·Litterman 1992 (Goldman) | 시장균형 prior + **국면 틸트 뷰** → 사후 μ → 가중치 |
| `managed_futures` | 매니지드 퓨처스(TSMOM) | trend | Moskowitz·Ooi·Pedersen 2012; AQR·Man AHL | 자산별 12M 추세>0 시 **역변동성 long, 아니면 현금**(long-flat) |
| `kelly` | 하프-켈리 성장최적 | sizing | Kelly 1956, Thorp | w ∝ Σ⁻¹μ, ×0.5, long-only 클립 |

### 2.1 전략별 정밀 명세

**equal_weight** — 8자산 각 12.5%. 데이터 무관(항상 산출).

**risk_parity (ERC)** — Σ = 샘플 공분산(+미세 ridge). 반복식(Spinu/cyclical):
초기 w ∝ 1/σ → 반복 `wᵢ ← wᵢ · (목표RC) / (Σw)ᵢ` 후 정규화, 수렴까지(≤50회). long-only 자연 충족.

**hrp** — corr → 거리 d=√((1−corr)/2) → `scipy.cluster.hierarchy.linkage(method="single")` →
quasi-diagonalization(클러스터 순서) → 재귀이분(각 분할에 역분산 비중 배분). 행렬역산 없음.

**min_var** — Σ = `LedoitWolf().fit(R).covariance_`. `scipy.optimize.minimize(SLSQP)`로
min wᵀΣw, bounds [0,1], Σw=1. 정규화 100.

**max_div** — σ = 자산 표준편차 벡터. max DR=(wᵀσ)/√(wᵀΣw) (= min −DR), SLSQP, long-only.

**max_sharpe** — μ = 트레일링 평균수익(연율화), Σ = Ledoit-Wolf 수축. max (wᵀμ)/√(wᵀΣw), SLSQP.
★추정오차 큰 전략 → 수축추정 필수(없으면 코너 솔루션 쏠림).

**black_litterman** — ★콕핏 차별화 통합★
- Prior: 정적 시장 프록시 w_mkt = `{SPY:.40, EFA:.13, EEM:.07, TLT:.12, IEF:.08, GLD:.06, PDBC:.06, VNQ:.08}`
  (시총 실데이터 부재 시 프록시 — 정직 라벨). 균형수익 Π = δ·Σ·w_mkt (δ=2.5).
- 뷰: `regime_analyzer.asset_tilts`(5범주 `growth_stocks/value_stocks/bonds/commodities/cash`, 값 `++/+/0/-/--`)를
  `_TILT_TO_ASSETS` 로 유니버스에 매핑 → 절대 뷰 P·Q:
  `growth_stocks→{SPY,EEM}`, `value_stocks→{EFA,VNQ}`, `bonds→{TLT,IEF}`, `commodities→{PDBC,GLD}`, `cash→(전체 리스크 스케일)`.
  뷰 강도 Q: `++=+3%, +=+1.5%, 0=0, −=−1.5%, --=−3%`(연율, 해당 자산 절대 뷰), Ω=대각 불확실성(τ=0.05).
- 사후 μ_BL = [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹[(τΣ)⁻¹Π + PᵀΩ⁻¹Q] → max-Sharpe(μ_BL, Σ) long-only 정규화.
- 폴백: 국면 조회 실패 시 w_mkt(프록시) 그대로 반환.

**managed_futures (TSMOM, long-flat)** — 자산별 signal = 1 if `_ret(12M)>0` else 0.
on 자산에 역변동성 가중 wᵢ ∝ signalᵢ/σᵢ → 정규화 100. 전부 off → `{BIL:100}`(현금).
※ 정통 TSMOM의 숏·레버리지는 제외(사용자 결정: long-only·합100·백테스터 이식 일관성 유지).

**kelly (하프-켈리)** — f = Σ⁻¹μ (Σ=Ledoit-Wolf), w = 0.5·f, 음수 클립(long-only), 정규화 100.
전부 ≤0 → `{BIL:100}`. 풀켈리 과대레버리지 회피 위해 분율 0.5.

---

## 3. 아키텍처 (격리 · 기존 패턴 보존)

### 3.1 신규 `src/engine/risk_allocations.py`
모멘텀(`tactical_allocations.py`)과 분리된 공분산/최적화 모듈.
- `_returns_matrix(tickers, mk, lookback=37) -> (names, np.ndarray)` — `monthly_closes`로 수익률 행렬,
  히스토리 부족 자산 제외, 공통 최소길이 절단. <2자산이면 None.
- `_cov_shrink(R) -> np.ndarray` — `sklearn.covariance.LedoitWolf` 수축 공분산(폴백: 샘플+ridge).
- `_to_holdings(weights, names) -> dict` — np 가중치 → `{ticker: weight%}` (`_norm` 호환).
- 9개 `s_*(mk) -> dict[ticker, weight%]` — 전부 long-only·합100, 기존과 동형 시그니처.
- `RISK_STRATEGIES: list[tuple[id, name, desc, family, fn]]` — 9종 등록.
- **견고성 가드**: `scipy`/`sklearn` import를 try/except → 실패 시 폴백
  (min_var/max_div/max_sharpe/kelly → inverse-vol, hrp → inverse-vol, 수축 → 샘플+ridge). torch 패턴과 동일 사상.

### 3.2 `tactical_allocations.py` 변경 (최소)
- `STRATEGIES` 튜플에 `family` 필드 추가(기존 13 = `"momentum"`). 형식: `(id, name, desc, family, fn)`.
- 파일 끝에서 `from src.engine.risk_allocations import RISK_STRATEGIES` import 후
  `ALL_STRATEGIES = STRATEGIES + RISK_STRATEGIES` 구성. `compute_strategies`가 `ALL_STRATEGIES` 순회.
- `compute_strategies` 출력 dict에 `"family"` 추가(프론트 그룹핑용). 순환 import 방지: 함수 내부 지연 import.

### 3.3 추천엔진 `macro_recommender.py`
9종을 `_ARCHETYPE`에 매핑:
- defensive: `min_var`
- aggressive: `max_sharpe`, `kelly`
- diversified: `risk_parity`, `hrp`, `max_div`, `black_litterman`, `managed_futures`, `equal_weight`

`_FIT`(국면×아키타입)는 무변경 → 랭킹·추천에 22종 자동 편입. `ranking` 길이 13→22.

### 3.4 프론트 (소규모)
- `screenerApi.ts`: `TacticalStrategy`에 `family?: string` 추가, `RecommendRankItem`/랭킹은 무변경.
- `MacroCockpit.tsx` 05 Strategies: StrategyBoard를 **family별 그룹 섹션**으로(모멘텀/리스크/최적화/추세/사이징/벤치마크).
  22개 평면 그리드 → 패밀리 헤더 + 그룹. 기존 StrategyCard 재사용, 그룹 라벨만 추가.
- 06 Recommend 랭킹 테이블: 22행 자동(변경 없음, 스크롤). 행에 family 태그(선택).

---

## 4. 검증

### 4.1 단위 (`tests/test_risk_allocations.py` 신규)
- 각 9전략: 합100(±0.5)·long-only(음수 없음)·결정론(mock 동일입력 동일출력).
- US/KR 토글: `compute_strategies("kr")` 티커 6자리 매핑, us_ticker 보존.
- 엣지: 단일자산 유니버스, 히스토리 부족(자산 제외), 공분산 특이(폴백), 전부 추세 off(→BIL).
- 폴백: scipy/sklearn 가드 경로(모킹) → inverse-vol 산출.
- `black_litterman`: 국면 뷰 주입 시 prior 대비 가중치 이동 확인, 국면 실패 시 prior 폴백.

### 4.2 통합
- `compute_strategies("us")` 22전략, 각 holdings 합100.
- `recommend("us")` ranking 22, `ranking[0]==top`.
- 콕핏: StrategyBoard family 그룹 렌더, recommend 22행.
- ★기존 테스트 갱신 필수★ `tests/test_tactical_allocations.py`:
  `test_all_strategies_sum_to_100_us`의 `== len(STRATEGIES) == 13` → `== len(ALL_STRATEGIES) == 22`,
  `test_recommend_structure`의 `len(r["ranking"]) == 13` → `== 22`. (모멘텀 13 회귀 불변은 별도 보존 어서션으로.)

### 4.3 게이트
- `python -m ruff check src/engine/risk_allocations.py src/engine/tactical_allocations.py src/engine/macro_recommender.py`
- `KIS_USE_MOCK=1 python -m pytest tests/ -q` — 기준 544 passed/10 skipped + 신규 통과(목표 ≥560).
- `cd frontend && npx tsc --noEmit`(0) · `npx next build`(16/16, /macro 빌드).
- 회귀 불변: 기존 13전략 산출 동일, 백테스트 52거래 -8.1% 불변.

---

## 5. 구현 순서 (안전 커밋 단위)
1. `risk_allocations.py`: 헬퍼(`_returns_matrix`/`_cov_shrink`/`_to_holdings`) + 가드 + 9전략 + `RISK_STRATEGIES` + 단위테스트. (백엔드 격리, 엔드포인트 무변경 — 커밋①)
2. `tactical_allocations.py` family 필드 + `ALL_STRATEGIES` 합성 + `compute_strategies` family 출력. `macro_recommender.py` 아키타입 매핑. 통합 검증(22종). (커밋②)
3. 프론트: `screenerApi.ts` family 타입 + `MacroCockpit.tsx` StrategyBoard family 그룹. tsc/build. (커밋③)
4. 푸시 `git push -u origin claude/keen-thompson-bdk3e8`. (PR 금지 — 명시 요청 시에만)

커밋 트레일러:
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_01NSAuFjWec6ZwXi9wq7SbrA`. 모델ID 커밋 금지.

---

## 6. 정직한 한계
- **추정오차**: max_sharpe/kelly/BL은 기대수익 추정에 민감 → Ledoit-Wolf 수축·하프켈리·long-only 제약으로
  완화하되 만능 아님(스펙·UI 명시). min_var/리스크패리티/HRP는 기대수익 불요라 더 견고.
- **mock 공분산**: 샌드박스 mock 가격은 합성 → 분산효과·상관이 비현실적. **실 분산효과는 GCP 실시세(KIS)에서.**
  여기선 로직·합100·long-only·폴백·결정론만 검증.
- **BL 시장균형 prior**: 시총 실데이터 부재 시 정적 프록시 가중 사용(정직 라벨). 실 시총 연동은 후속.
- **TSMOM long-flat**: 정통 대비 숏·레버리지 제외 → 하락장 crisis-alpha 축소(현금 회피만). 설계상 의도된 제약.
- 백테스트 성과는 보장 아님 — 콕핏 06의 트레일링 성과 추정과 동일 디스클레이머 적용.

---

## 7. 비범위 (YAGNI)
- 멀티에셋 리스크프리미아(value/carry/defensive 신호) — ETF 가격만으론 데이터 부족 → 제외.
- CPPI/포트폴리오 보험 — 경로의존(상태 필요) → 시점 스냅샷 모델 부적합 → 제외.
- 정통 TSMOM 숏/레버리지, BL 실시총, 동적 vol-targeting 오버레이 — 후속 후보.

---

## 8. 구현 완료 (Implementation — ★기록★)
브랜치 `claude/keen-thompson-bdk3e8`. 3 커밋 단위 + 푸시 완료.
- `572345c` Unit 1: `src/engine/risk_allocations.py`(9전략 + 헬퍼 + scipy/sklearn 가드 폴백) +
  `tests/test_risk_allocations.py`(10개, TDD red→green). 합100·long-only·결정론·균등·현금·BL 뷰이동 검증.
- `a0eef32` Unit 2: `tactical_allocations.py` family 필드 + `ALL_STRATEGIES`(22) + `compute_strategies` family 출력 ·
  `macro_recommender.py` `_ARCHETYPE` 9종 매핑 · `test_tactical_allocations.py` 카운트 13→22 + family 파티션.
- `4eb5158` Unit 3: `screenerApi.ts` family 타입 · `MacroCockpit.tsx` StrategiesTab family 그룹핑 · `globals.css` mc-fam*.

검증(완료): `KIS_USE_MOCK=1 pytest` **555 passed/10 skipped**, ruff 통과, tsc 0, next build 16/16(/macro 21.1kB).
E2E: `/macro/strategies` 22전략 6family, `/macro/recommend` 22랭킹. mock 산출 차별화 확인
(리스크기반 분산·optim 집중·BL SPY 50.9% 국면틸트 반영). 실 분산효과는 GCP 실시세에서.

검증 후 평가(블랙-리터만 long-only/완전투자 형태에서 Kelly와 max_sharpe 수렴 경향은 mock 한계 —
실데이터서 분리). 정직 라벨·폴백·회귀 불변(모멘텀 13·52거래 -8.1%) 유지.
