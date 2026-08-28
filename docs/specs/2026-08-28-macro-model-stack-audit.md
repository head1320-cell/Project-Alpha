# 매크로 모델 기술 스택 감사 — ★설명된 모델과 구현된 모델이 다르다★

> 읽기 전용 감사. `src/` 무변경. 실측 시점 2026-08-28.
> 선행: [`매크로 계층 아키텍처`](2026-08-25-macro-layer-architecture.md) ·
> [`능력-계보 감사`](2026-08-27-capability-lineage-audit.md)(§0 에 `E0~E5` 정의)
>
> **결론을 먼저 적는다** — 다섯 구성요소 중 넷은 실재하고 잘 갖춰져 있다. 어긋난
> 것은 **국면 추론**이고, 저장소는 그것을 우연히 빠뜨린 것이 아니라 **재서 기각**했다.
> 그리고 여섯 채택 조건이 전부 닫혀 있어 **증거 기반으로 진행할 관문이 없다.**

---

## 0. ★전제 정정 — HMM 은 없고, 없는 것이 의도다★

작업 설명은 이 플랫폼을 *"Hidden Markov regime inference"* 로 규정한다.
`src/engine/regime_transitions.py:14` 가 정반대를 적고 있다:

> ★왜 4상태 HMM(hmmlearn)이 아닌가 — 재서 기각했다★
> 4상태 Gaussian HMM 은 평균 8 + 공분산 12 + 전이 12 ≈ **32개 모수**다. 실사용
> 관측 48개에 32개 모수는 과적합이고 … **수렴한 것처럼 보이는 4×4 행렬이 이 화면에서
> 가장 위험한 종류의 거짓이다 — 그럴듯할수록 그렇다.** … hmmlearn 은 이 저장소에
> 설치돼 있지도 않다.

`src/engine/capability.py:8` 도 `hmmlearn` 을 **미설치**로 선언한다.

★이것은 결함이 아니라 규율이다★ — 모수가 관측을 넘는 모형을 붙이면 화면은 더
정교해 보이지만 숫자는 잡음이다. `CLAUDE.md` §5 의 *"정교함을 위한 정교함 금지"* 와
같은 판단이며, 그 규칙보다 먼저 코드에 있었다.

**표본이 늘면 재검토할 문제로 남긴다**(§5).

---

## 1. 다섯 구성요소 → 코드 매핑

| 설명된 것 | 실제 구현 | 위치 |
|---|---|---|
| HMM regime inference | ★4상태 HMM 없음 · 명시적 기각★ — §2 참조 | `regime_*.py` 9개 모듈 |
| Point-in-time macro | ★인프라 있음 · 데이터 없음★ — `ResearchUsage`·`derive_usage`·`assert_backtest_eligible` · 관측 스토어 · 빈티지 백필 | `data/pit_macro.py`(203) · `data/macro_observation_store.py`(376) · `data/macro_vintage_backfill.py`(269) |
| Ledoit–Wolf shrinkage | sklearn `LedoitWolf`, 실패 시 표본+ridge · 별도 경로는 `"none"`/고정 λ/`"auto"` 3분기이고 **λ 를 함께 반환** | `engine/risk_allocations.py::_cov` · `engine/conditional_market.py::_shrunk_cov` |
| Black–Litterman | posterior 공식 2곳, 주석이 서로를 참조해 갈라짐을 막는다 | `engine/risk_allocations.py::s_black_litterman` · `engine/allocation_studio.py::bl_posterior` |
| Entropy Pooling | `_posterior`·`entropy_pool`·`pool_weights` | `engine/entropy_pooling.py`(228) |
| Walk-forward | `min_train` · M/Q 리밸런스 · **반환이 전부 OOS** | `engine/allocation_backtest.py::walk_forward` |

★넷은 문제가 없다.★ 이 감사가 다루는 것은 ①의 어긋남과, 그것들이 **무엇 위에서
돌고 있는가**(§3)이다.

---

## 2. 국면 추론의 실제 구성 — 셋을 병렬로 돌리고 합치지 않는다

| 층 | 무엇 | 근거 |
|---|---|---|
| 분류 | **규칙 기반 사분면** — `quadrant(growth, inflation)` 이 부호 둘로 Reflation/Goldilocks/Stagflation/Disinflation 을 가른다 | `regime_axes.py:211` |
| 불확실성 | `quadrant_probs` — 축 z 와 표준오차로 사분면 확률(독립 가우시안 가정) | `regime_axes.py:223` |
| 전이 | **Dirichlet-multinomial 사후** — 행별 `Dir(α + n)`, 주변 Beta 로 신용구간을 `beta.ppf` 로 정확히 | `regime_transitions.py:134` |
| 앙상블 | `axis` · `markov`(**2상태** `MarkovRegression`) · `cluster`(`GaussianMixture`) | `regime_ensemble.py` |

**2상태를 쓰는 이유**(`_markov_probs` 독스트링): *"4상태는 월 데이터 수십 개로는
거의 항상 미수렴하거나 한 상태가 비고, 그러면 '나온 숫자' 가 노이즈다."* 성장축만
2상태(확장/수축)로 추정한 뒤 물가축 부호와 교차해 4국면으로 편다 — 상태전환이
실제로 말해 주는 것은 **성장 국면의 지속성**이기 때문이다.

★세 결과를 평균내지 않는다★ — *"평균을 내면 어느 모형이 무슨 말을 했는가가
사라진다. 세 방법이 갈릴 때 그 불일치 자체가 정보다."* 그래서 병렬로 돌려주고
`agreement` 로 일치 여부만 계산한다.

★미가용을 날조하지 않는다★ — 미설치·표본 부족·미수렴은 각각
`{"available": False, "reason": ...}` 다. 0 이나 균등분포로 채우지 않는다.

---

## 3. 증거 등급 — ★전부 E0★

| 축 | 값 |
|---|---|
| 데이터 출처 | **E0**(합성) — `real_share = 0.0`, 61계열 중 실데이터 0 |
| 주장의 종류 | 계약·행합 등 구조적 사실만 `structural`. Sharpe·CE·CVaR 는 전부 `synthetic_mechanism` |

`scripts/t3_transmission.py` 가 이것을 상수로 못 박아 두었다 — *"등급을 올려 적지
않는다. 이 스크립트가 내는 모든 수치는 합성 패널에서 나온다."*

### 네 질문 중 답할 수 있는 것

아키텍처 스펙이 이미 표로 갈라 놓았다 — ① 정보 표현력 ★답 가능★ · ② 전달 안정성
★답 가능★ · ③ 예측 스킬 ★답 불가★(국면 경로를 우리가 생성했다) · ④ 경제적 가치
★답 불가★(`real_share = 0.0`).

★Ledoit–Wolf·BL·EP·walk-forward 가 잘 구현돼 있다는 사실은 ①②에 대한 답이지
③④에 대한 답이 아니다.★ 이 구분이 이 문서의 존재 이유다.

---

## 4. 여섯 채택 조건 — 현재 코드 실측

원본 표는 [아키텍처 스펙 §6](2026-08-25-macro-layer-architecture.md) 이고 그날의
기록이다. 아래는 **2026-08-28 재실측**이다.

| # | 조건 | 실측 | 성격 |
|---|---|---|---|
| 1 | 정준 자산군 분류 | `exposure_taxonomy` 55종 | ✔ |
| 6 | BL+EP 완결 평가 | 완료(합성 한정) | ✔ |
| 2 | 계열별 `revision_bias` | `unmanaged` · KR 4계열 `blocked_by="source"` · **US 6계열 `blocked_by="path"`** | ★§4.1★ |
| 3 | 240개월 이력 | 최장 **60** · **중앙값 0** (`store_cap=240` 은 이미 준비됨) | 키 차단 |
| 4 | 투자가능 자산 6~10 | 합성 6 · 실계열 0 | 키 차단 |
| 5 | 국면 전이 30회+ | 합성만 | 키 차단 |

### 4.1 ★`source` 와 `path` 는 다른 종류의 차단이다★

`regime_axes.py:69-70` 이 둘을 상수로 갈라 놓았다:

```python
BLOCKED_BY_SOURCE = "source"   # 제공자가 빈티지를 주지 않는다 (영구)
BLOCKED_BY_PATH   = "path"     # 제공자는 주는데 수집 경로가 안 쓴다 (고칠 수 있다)
```

실측:

| 시장 | 계열 | 차단 |
|---|---|---|
| KR | ECOS 4 | `source` — ★영구★. ECOS 에 빈티지 엔드포인트가 없다 |
| KR | FRED 1 | `path` |
| US | FRED 6 | **전부 `path`** — ★고칠 수 있다★ |

봉합선은 `AXIS_PATH_USES_VINTAGE = False` 하나다. 그 상수의 주석이 왜 선언인지를
적어 두었다 — *"레지스트리만 보고 판정하면 과대주장한다. `has_vintage=True` 는
**API 가 줄 수 있다**는 뜻이지 **우리가 가져온다**는 뜻이 아니다."*
`tests/test_axis_revision_status.py` 가 이 선언과 실제 코드를 대조해, 빈티지를
배선하면 red 가 되어 상수를 함께 고치도록 강제한다.

★열지 않았다★ — 국면 출력이 바뀌면 배분이 바뀐다(`CLAUDE.md` §3: Macro→Allocation
동작 변경은 별도 승인). 게다가 지금 열어도 **검증할 데이터가 없다**(§4.2).

### 4.2 빈티지 저장소는 비어 있다

`macro_observations` 240행 · **계열 1개(`PROBE_DEPTH`)** · **`with_vintage` 0건**.
깊이 프로브 산물이지 실 관측이 아니다. 스토어 자신이 정직하게 말한다:
`research_usage = "forward_only"`, 사유 *"충족되지 않은 조건: 빈티지 전량 · 공표시각
전량 — 개정 편향을 재려면 빈티지가 필요합니다."*

### 4.3 부수 실측 — 국면·배분 경로는 깨끗하다

`regime_analyzer`·`regime_ensemble`·`regime_probability`·`regime_transitions`·
`regime_forecast`·`regime_axes`·`regime_snapshot_builder`·`conditional_market`·
`risk_allocations`·`entropy_pooling`·`allocation_backtest` **11개 모듈 전부
합성값 제조 0건**. `regime_transitions` 의 난수 1건은 Dirichlet 사후 표본이지
데이터 날조가 아니다.

★같은 검사가 `liquidity_gate` 에서는 실제 결함을 찾았다★(`2aff832`) — 이 경로가
깨끗하다는 것은 검사가 무력해서가 아니다.

---

## 5. 무엇이 막고 있는가 · 획득 계획

| 단계 | 무엇 | 여는 조건 |
|---|---|---|
| A | `FRED_API_KEY` · `BOK_API_KEY` 발급 → `.env`(★커밋 금지★) | — |
| B | ★이 컨테이너가 아니라 로컬에서★ — 여기는 두 호스트 모두 CONNECT 403 | — |
| C | 수집 깊이 확인(`MACRO_HISTORY_YEARS=20`·`store_cap=240` 은 이미 준비됨) | #3 |
| D | `macro_vintage_backfill` 로 ALFRED 빈티지 적재 → `macro_observations` | #2(US) |
| E | 실계열이 붙으면 국면 전이 횟수·투자가능 자산 재실측 | #4 · #5 |
| F | ★그때 비로소★ `AXIS_PATH_USES_VINTAGE` 개방을 **별도 승인**으로 논의 | #2 확정 |
| G | 표본이 240개월에 이르면 **4상태 HMM 재검토**(모수 32 vs 관측 240) | §0 |

★조건 2(KR)는 이 목록에 없다★ — ECOS 에 빈티지 엔드포인트가 없어 **영구 불가**다.
KR 국면 축은 구조적으로 forward-only 이고, 그 사실은 결함이 아니라 제약이다.

---

## 6. 하지 않을 것

- ★4상태 HMM 도입★ — 저장소가 모수 32 vs 관측 48 로 기각했고, 표본은 그때보다
  나아지지 않았다(관측 **중앙값 0**). 지금 붙이면 §0 이 경고한 "그럴듯한 거짓" 이 된다.
- ★`AXIS_PATH_USES_VINTAGE` 무단 개방★ — 배분 정책 변경이고, 검증할 빈티지도 없다.
- ★합성 Sharpe 최적화★ — `real_share = 0.0` 에서 올린 Sharpe 는 ③④ 어느 쪽의
  증거도 아니다.
- 기존 아키텍처 스펙 §6 표 수정 — 원본은 그날의 기록이다. 재실측은 이 문서 §4 다.
- 어떤 아키텍처의 **채택 선언** — 여섯 조건 중 넷이 열려 있다.

---

## 부록 A — 재검토 (2026-08-28, P0~P3 이후) ★하중을 받는 노드가 다르다★

본문 §4 의 수치는 P0~P3 이전 것이다. 아래는 재실측이고, 본문에 없던 **두 가지
구조적 사실**을 추가한다.

### A.1 스택 서술의 정정 — ★"HMM 계열" 이 하중을 받고 있지 않다★

본문 §0 이 "4상태 HMM 은 없고, 없는 것이 의도다" 를 확정했다. 재검토에서 **그보다
한 걸음 더 중요한 사실**이 나왔다: 실재하는 상태전환 성분(`MarkovRegression`,
성장축 2상태)조차 **배분에 흘러들지 않는다.**

```
[진단 전용]  regime_ensemble{axis, markov, cluster}
             → 소비자: API 라우트 2곳뿐(`macro_routes.py:75, 785`)
             → `regime_probability.from_axis`/`from_markov` = USAGE_DIAGNOSTIC

[하중 경로]  regime_axes.quadrant  (★규칙 기반 사분면★)
             → regime_transitions.regime_path()
             → conditional_market.regime_by_month_from_path
             → conditional_moments (μ/Σ) → Ledoit-Wolf → BL/EP → optimizer
             (`allocation_backtest.py:257-280` · `allocation_routes.py:567-615`)
```

★이것이 왜 중요한가★ 스택을 "Regime Inference (HMM 계열)" 로 그리면 다음 작업이
**포트폴리오에 닿지 않는 팔**을 고도화하게 된다. 하중을 받는 자리에 있는 것은
규칙 기반 사분면이다.

### A.2 ★계약에 기본값 우회로가 있다★

`regime_probability.py` 는 *"배분에 닿을 수 있는 것은 `k_step_forecast` 하나뿐"*
이라는 계약과 `USAGE_*`/`SOURCE_*`/`require_portfolio_source()` 를 갖췄고, 자기
독스트링에 이미 적어 뒀다 — *"그런데 포트폴리오에는 **넷째** — `regime_path` 의
하드 라벨, 즉 1.000 — 이 간다."*

실측(`allocation_backtest.py`):

```python
weighting = regime.get("weighting", "hard")     # ★기본값이 "hard"★
if weighting == "hard":
    cond = conditional_moments(df, by_month, current)   # ← usage 검사 없음
else:
    for pr in probs: require_portfolio_source(pr)       # ← 검사 있음
```

★계약이 **비기본 분기에서만** 강제된다.★ 기본 경로는 "오늘 국면이 보유기간 동안
지속된다" 는 **가정**을 쓰는데 그 가정이 라벨되지 않았다. `ms1b_eval.py` 가
B1(hard) vs N(probabilistic) 를 비교하지만 그것은 실험이지 경로의 자기 신고가 아니다.

**조치(이번)**: `regime_audit` 에 `prob_source`/`prob_usage`/`prob_note` 를 남기고
(`USAGE_ASSUMPTION`·`SOURCE_HARD_LABEL`·`ASSUMPTION_NOTE` 신설),
`regime_ensemble()` 페이로드에 `usage`/`usage_note` 를 실었다.
★기록만 추가했고 결정은 바뀌지 않았다★ — 계약을 강제로 거는 것은 Macro → Allocation
정책 변경이라 **별도 승인**이다(CLAUDE.md §3).

### A.3 재실측 — 채택 조건과 증거

| 항목 | 값 (2026-08-28) |
|---|---|
| 제공자 키 | **8개 전부 미설정** (FRED·BOK·KRX·DART·KIS·ANTHROPIC·NAVER·GOOGLE) |
| `real_share` | **0.0** — 61계열 중 실데이터 0 |
| 관측 스토어 | 240행 · 계열 **1개**(깊이 프로브 산물) · 빈티지 **0건** · `forward_only` |
| capability | **L1** · `L0` 차단(`frontier_sample` 60 < 240 · torch · cvxpylayers · LLM · trends) |
| 조건2 KR | `unmanaged` — ECOS 4 = `source` ★영구★ · FRED 1 = `path` |
| 조건2 US | `unmanaged` — FRED 6 **전부** `path` ★고칠 수 있다★ |

★본문 §4.1 의 "봉합선은 `AXIS_PATH_USES_VINTAGE` 하나다" 는 낡았다★ — P0/P2
커밋(`4983f71`)이 그 상수를 **두 사실의 논리곱 측정**으로 대체했다(⑵ 수집 경로가
빈티지를 읽는가 ∧ ⑶ 그 계열에 실제 빈티지 행이 있는가). 그래서 빈티지가 적재되고
경로가 배선되는 순간 **자동으로** 판정이 열린다.

### A.4 성숙도는 ★세 열로★ 갈라야 한다

한 별점에 구현 품질과 증거를 담으면 "Macro data ingestion ★★★★☆" 같은 표현이
나온다 — **코드**에 대해서는 맞고 **데이터**에 대해서는 0 이다.

| 계층 | 구현 | 배선 | 증거 |
|---|---|---|---|
| 매크로 수집(FRED·ECOS) | 있음 | 있음 | **E0** — 키 없음, `real_share=0.0` |
| PIT/빈티지 | 있음(ALFRED·스토어·백필) | ★부분★ 수집기가 빈티지를 읽지 않음 | **E0** — 빈티지 0건 |
| 매크로 팩터 | 있음 | 있음 | E0 |
| 국면 추론 | 규칙 사분면 + Dirichlet 사후 | 있음(하중) | E0 |
| 상태전환(MarkovRegression 2상태) | 있음 | ★진단 전용★ | E0 |
| 국면조건부 μ/Σ | 있음 | 있음 | E0 |
| Ledoit–Wolf | 있음 | 있음 | 구조적 |
| BL / EP / optimizer | 있음 | 있음 | 구조적 |
| RegimeAdaptiveAllocator(EWMA λ=0.85 · 3모드 · 상관붕괴) | 있음 | `realism_engine` + 라우트 1곳 | E0 |
| walk-forward · 예측 적중률 하네스 | 있음 | 있음 | 하네스는 준비됨, 입력이 합성 |

### A.5 다음 워크플로우 — ★남은 관문이 전부 키로 막혀 있다★

**Track A (키 없이 · 배분 동작 불변)**

| | 항목 | 상태 |
|---|---|---|
| A1 | 계약 우회로·진단/하중 구분 신고 | ✔ 이번 |
| A2 | 수집기 빈티지 경로 배선(`COLLECTOR_READS_VINTAGE`) | 다음 — 오늘은 빈티지 0건이라 논리곱 때문에 축 판정 **불변**, 키가 오면 자동 개방 |
| A3 | 질문③ 하네스의 **음성 통제** — 합성 패널에서 적중률이 우연과 구분되는가 | 다음 — 하네스가 무력하지 않음을 먼저 보여야 한다 |

**Track B (키가 오면 — 순서가 곧 게이트)**

`FRED_API_KEY` → 21계열 + ALFRED 빈티지 적재 → 조건2(US) `path` 해제 → 깊이
240개월 → 조건3 + capability `L0` → 조건4·5 재실측 → ★그때 비로소★ 축 빈티지
개방을 **별도 승인**으로 → 표본 240이면 4상태 HMM 재검토(§0 의 조건).

★조건2(KR)는 이 목록에 없다★ — ECOS 에 빈티지 엔드포인트가 없어 **영구 불가**.

**하지 않을 것** — HSMM · sticky HMM · TVTP · MS-VAR · DFM · 베이지안 HMM ·
regime-switching GARCH · 입자필터 · 신경 상태공간. 지금 붙이면 ⑴ **하중을 받지 않는
팔**을 고도화하거나 ⑵ 관측(중앙값 0)보다 모수가 많은 모형을 붙이는 것이다.
