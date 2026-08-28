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
