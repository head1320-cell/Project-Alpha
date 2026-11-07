# DeepSeek 개념 선별 도입 — 아키텍처 검토 (구현 전 권고)

> 상위: [`2026-08-30-macro-to-portfolio-architecture-review.md`](2026-08-30-macro-to-portfolio-architecture-review.md)(참조 21종, `48a58f7`)
> ★이 문서는 권고이고 구현은 별도 승인 사항이다.★ 아래 P5~P9 중 어느 것도
> 아직 착수하지 않았다.

작성: 2026-09-02 · HEAD `2210e29` · 선행 `9122497`(M7) · `48a58f7`(참조 21종 검토)
선행 확정 사실(재측정 안 함): A3 `inconclusive`(병목 SPA) · A4 `underpowered` ·
M7 최소 검출 150개월 · P3 용량 한계 미도달(검량 구간 ≤100억)

---

## 0. Executive Recommendation

★도입할 것은 **하나의 개념**이고, 나머지는 대부분 이미 있거나 측정이 반대한다.★

가장 값어치 있는 수입품은 **DeepSeek-Math-V2 의 generator–verifier 분리**다.
그런데 Alpha 는 verifier 를 **이미 갖고 있다**(`research_verdict` ·
`research_power` · `null_stats` · `regime_surrogates`). 빠진 것은 검증기가 아니라
★검증 결과가 생산 소비자에게 **돌아오는 경로**★ 다. 지금 `conditional=true` 는
A4 가 `underpowered`, A3 가 `inconclusive` 로 판정한 신호를 **그 판정을 한 번도
읽지 않고** 최적화기에 태운다.

나머지 판단은 대부분 **거부**이며, 그 근거는 취향이 아니라 실측이다:

- ★MoE / Economic Expert Routing → 거부★ A3 이 "후보를 늘리면 SPA 검정력이
  떨어진다" 를 측정했다. SPA 는 지금 **유일한 병목**이다. 전문가 라우팅은 후보를
  늘리는 장치이므로 정확히 반대 방향이다.
- ★columnar/lazy/batch 재설계(smallpond·3FS) → 거부★ 이번에 프로파일한 결과
  연구 비용의 **93%가 국면조건부 계산**이고 최적화기는 4%, 데이터 적재는
  **1회성 2.4초**다. 데이터 계층 재설계는 비용이 거의 0인 항을 겨냥한다.
- ★플러그인 프레임워크 → 거부, 서비스 추출 → 채택★ Alpha 에는 이미 레지스트리
  관용구가 다섯 곳 있다. 진짜 문제는 프레임워크 부재가 아니라 **2,448줄·92개
  import 짜리 `allocation_routes`** 하나다.
- ★GPU 커널(DeepGEMM·FlashMLA·DeepEP) → 거부★ 최적화 대상이 6×N 행렬이고 전체의
  4%다. 프로파일이 관련성을 입증하지 못했다(사용자 조건 그대로).

사용자 결정: 미검증 조건부는 **기본 라벨링 · 차단은 플래그 뒤**(동작 불변).

---

## 1. Current Architecture Gap — ★측정된 것만★

### G1. 검증이 층이 아니라 스크립트다 (최대 격차)

`research_verdict`·`research_power`·`research_panel`·`null_stats`·
`regime_surrogates` 의 소비자는 **`scripts/` 셋과 `research_runs` 스토어뿐**이다.
`src/api` 어디에도 매크로 **연구 판정**을 읽는 경로가 없다(라우트의 `verdict` 는
밸류에이션·스크리너의 다른 개념이다).

결과: 파이프라인은 "계산할 수 있었는가"(availability)에는 정직한데
★"그 신호가 스킬을 보인 적 있는가"(validity)에는 침묵한다.★ `_regime_override_at`
는 실패를 조용히 넘기지 않지만, **한 번도 관문을 통과한 적 없는 신호**를 태우는
것은 막지 않는다.

### G2. 사전등록이 문서 관행이지 기계 계약이 아니다

`regime_control` 은 `preregistered` 블록을 리포트에 싣는다(좋다). 그러나 격자를
결과를 보고 바꾸는 것을 **막는 장치는 없다**. 사양(markdown) → 실행 → 판정의
연결이 사람의 규율로만 유지된다.

### G3. `allocation_routes` 가 합성·정책·오케스트레이션을 겸한다

2,448줄 · 내부 import 92개(전 저장소 fan-out 1위). 반면 fan-in 상위는
`database`(66) · `mock_gate`(46) · `stock_master`(39) 로 **데이터 단일 출처**이며
이는 건강한 모양이다. ★결합 문제는 전역이 아니라 국소다.★

### G4. 연구 처리량이 국면조건부 재계산에 묶여 있다 (신규 실측)

```
walk_forward  무조건부 0.087s   ·   국면조건부 1.337s      → ★15.4배★
optimize ×70 (웜)        0.055s                            → 전체의 4%
stock_master 마스터 적재 2.4s (1회성, 관문 전체에 상각)
관문 1회 = 3비용 × (4팔 + 81 shift + 50 markov + 50 block) = ★555 백테스트★
        ≈ 12.4분  (P3 용량 스윕 실측 ~13분/관문과 일치)
```

★그리고 조건부 계산은 **비용 수준에 불변**이다★ — P3 에서 "비중 경로는 비용에
불변" 을 대수적 항등식으로 이미 증명했다. 즉 같은 조건부 모멘트를 **비용 3수준에
걸쳐 3번 재계산**하고 있다. 메모이제이션은 정당성이 이미 증명된 3배다.

---

## 2. DeepSeek 개념 → Alpha 매핑

★출처 확인 상태를 밝힌다★ — `deepseek-harness`("Everything is a Plugin")와
`Engram`(conditional memory: 정적 N-gram 지식 조회를 동적 추론에서 분리)은 검색으로
확인했다. **`Cordis`·`DeepSpec`·`DeepSeek-Math-V2` 는 확인하지 못했다** — 사용자가
기술한 개념 그대로 평가하며, 저장소 내부를 아는 척하지 않는다.

| DeepSeek 개념 | 판단 | Alpha 매핑과 근거 |
|---|---|---|
| **Math-V2 generator–verifier** | ★채택(개념)★ | 검증기는 이미 있다. 빠진 것은 **판정의 귀환 경로**. → P5 |
| **DeepSpec 실험 하네스**(미확인) | 적응 | 사전등록을 문서에서 **기계 계약**으로. → P6 |
| **Engram 정적/동적 분리** | 적응(축소) | `stock_master`·`FACTOR_PROXIES`·`ASSET_CLASS_TIERS`·`FIELD_BY_ID` 로 **씨앗은 있다**. 성능이 아니라 **빈티지·출처 거버넌스**로 가치. → P9 |
| **harness/Cordis 플러그인** | ★프레임워크 거부 · 서비스 추출 채택★ | 레지스트리 관용구 5곳 존재. 문제는 god-route 하나. → P8 |
| **Prover 계약 검증** | 대체로 **이미 있음** | 변이 배터리 · 오일러 항등식 · 비트 동일 골든이 곧 수치 계약 검증이다. 추가 도입 가치 낮음 |
| **V2/V3 MoE 라우팅** | ★거부★ | A3: 후보↑ ⇒ SPA 검정력↓. SPA 가 유일 병목 |
| **smallpond / 3FS** | ★거부★ | 비용의 93%가 조건부 계산, 데이터는 1회성 2.4초 |
| **DeepGEMM/FlashMLA/DeepEP** | ★거부★ | 최적화기는 전체의 4%, 6×N 행렬. 프로파일이 반증 |

---

## 3. Target Architecture

사용자 제안 사슬을 **부분 채택**한다:

```
Research Context ✅있음 → [Expert Providers ❌기각] → Research State → Verification ✅있음(미배선)
   → Investment Belief → Portfolio Decision
```

- `ResearchContext` 는 **이미 존재**하고 라우트·스토어 4곳에 배선돼 있다
  (`src/engine/research_context.py`). 새로 만들 것이 없다.
- **Expert Providers 노드는 넣지 않는다** — 그것이 MoE 함정이다(§2).
- 실제 목표 사슬은 기존 사슬에 **관문 하나를 삽입**하는 것이다:

```
… → Belief(μ/Σ) → ★Verification Gate(판정·등급·검증시점을 belief 에 부착)★
    → Portfolio Construction → …
```

즉 새 계층을 세우는 것이 아니라 ★이미 있는 두 부품을 잇는 **간선**을 만든다.★

---

## 4. Priority Order

| # | 항목 | 왜 이 순서인가 |
|---|---|---|
| **P7** | 조건부 모멘트 캐시 | ★먼저 한다★ — 비트 동일로 검증 가능하고, 이후 모든 측정이 3배 싸진다(관문 13분→~4분). 최고 **레버리지** |
| **P5** | ★증거 관문(판정 귀환)★ | 최고 **가치**(Q2 의 답). 라벨 기본·차단 플래그라 동작 불변 |
| **P6** | 사전등록 하네스 | P5 의 판정 영속화 위에 얹힌다 |
| **P8** | `allocation_routes` 서비스 추출 | 독립. 순수 구조 개선이라 언제든 |
| **P9** | 정적 참조데이터 경계(빈티지) | 가장 낮음. 데이터 거버넌스 |

★Q2 의 답은 P5, "먼저 할 것" 은 P7 이다 — 다른 질문이다.★

---

## 4-1. ★P7 실측 (2026-09-02 추가 — 위 권고문은 고치지 않았다)★

구현: `2c7a93d`(엔진 분리) · `ffcfc9b`(관문 루프 반전).

★처방이 바뀌었다★ — 이 문서는 P7 을 "조건부 모멘트 캐시" 로 적었다. 착수 시
프로파일이 그것을 뒤집었다: 국면조건부 1.337초 중 `conditional_moments` 는
0.78초(58%)뿐이고 나머지는 조건부 뷰가 유발한 SLSQP 다. 캐시는 58% 만 잡고,
무엇보다 ★키가 불완전하면 다른 백테스트의 수를 조용히 쓴다★. 그래서 캐시를 버리고
**계획/시뮬레이션 분리**로 갔다(사용자 결정) — 비용이 계획의 인자에서 사라지므로
불변성이 키 관리가 아니라 **구조**가 된다.

| | 권고문 추정 | ★실측★ |
|---|---|---|
| 관문 1회 | ~4.3분 | **5분 04초** |
| 배수 | 2.9배 | **2.6배** |
| 시뮬레이션 1회 | ~0.02초 | **~0.12초** |
| 계획 재사용 | 3배 | **3.0배**(185 계획 / 555 시뮬) |

★추정이 빗나간 이유★ — 시뮬레이션을 스칼라 자본곡선 루프만으로 셌고
`compute_metrics`·컨포멀·1,700일 numpy 반올림이 **시뮬마다** 도는 것을 빼먹었다.
실제는 추정의 6배다. 재사용 배수(3.0)는 산술 그대로 맞았다.

★값은 바뀌지 않았다★ — A3 을 한 자도 다르지 않게 재현한다(`sharpe_diff`
0.20207895 / 0.19939271 / 0.19132456 · SPA `p_max` 0.105 · `inconclusive`).
비트 동일은 `git worktree` 로 리팩터 직전 커밋을 꺼내 같은 호스트에서 전정밀도
대조해 확인했다(분기 격자 18개 전부 일치).

용량 스윕 추정: 66분 → **~25분**(2.6배 적용). ★아직 실측하지 않았다.★

---

## 5. Dependencies

- **P7 → 없음.** P3 가 증명한 비용 불변성에만 의존한다.
- **P5 → `research_runs`(있음) · `research_context`(있음).** 새 스토어 불필요.
- **P6 → P5.** 판정이 조회 가능해야 사양↔실행을 묶을 수 있다.
- **P8 → 없음**(단 P5 와 같은 파일을 만지므로 **P5 뒤에** 두는 편이 충돌이 적다).
- **P9 → 없음.**

---

## 6. Validation / TDD Gates

각 항목 공통: 감사 → 사전등록 → RED → GREEN → **변이 배터리** → 전체 게이트
(현재 **3,970 passed / 10 skipped**) → 원자적 커밋 → HISTORY → 푸시.

- **P7** ★비트 동일이 유일한 합격 기준★ — 캐시 on/off 가 `equity_curve` 를 한 자도
  바꾸면 실패. 짝: 캐시 히트가 실제로 발생함을 카운터로 관측(0 이면 공허).
  변이: 키에서 regime path 제거 · 윈도 제거 · 비용을 키에 포함(무효화 낭비).
- **P5** 계약: 미검증 조건부 응답이 **판정·등급·검증시점을 싣는다** · ★짝★ 검증된
  경로는 같은 필드에 통과를 싣는다 · 플래그 ON 이면 차단하고 **사유**를 남긴다 ·
  ★미상은 통과가 아니다★(판정 없음 → `no_evidence`, 통과로 읽지 않는다).
  변이: 판정 미상을 통과로 · 라벨 삭제 · 플래그 무시 · 등급 하드코딩.
- **P6** 계약: 사양 해시가 실행 기록에 박힌다 · ★짝★ 격자를 바꾸면 해시가 바뀐다 ·
  기록된 사양과 다른 격자로 돌리면 **거부**. 변이: 해시를 상수로 · 비교 생략.
- **P8** ★행동 불변★ — 추출 전후 응답 골든 동일. 변이: 추출한 서비스를 우회.
- **P9** 계약: 참조데이터가 **as-of/빈티지**를 달고 온다 · 미상이면 `None` + 사유.

---

## 7. Recommended Commit Boundaries

```
P7  ① perf(research): 조건부 모멘트 캐시 — 관문이 같은 계산을 비용마다 다시 했다
P5  ② feat(research): 판정 영속화 + 조회 (research_runs 읽기 경로)
    ③ feat(alloc): 증거 관문 — belief 가 자기 판정을 달고 다닌다 (라벨 기본)
    ④ feat(alloc): 미검증 차단 플래그 (기본 OFF)
P6  ⑤ feat(research): 사전등록 해시 결속 — 격자를 결과 보고 못 바꾸게
P8  ⑥ refactor(api): allocation_routes → 명명된 서비스 추출 (행동 불변 골든)
P9  ⑦ feat(data): 정적 참조데이터 빈티지 경계
```

---

## 8. 명시적으로 도입하지 않는 것

★MoE/전문가 라우팅★(A3 반증) · ★columnar/lazy/batch 재설계★(프로파일 반증) ·
★GPU 커널★(4% 항) · 분산 파일시스템 · **플러그인 프레임워크 자체** ·
LLM 에이전트가 전략을 생성하는 구조(후보 수를 늘린다 — A3 과 정면 충돌) ·
★생성기가 스스로를 검증하는 self-verification★(검증기는 서로게이트 널처럼
**적대적·독립적**이어야 한다) · 새 국면 모델 · 새 최적화기 · `MacroState` 추상.

★한 줄 요약★ — Alpha 에 필요한 것은 새 아키텍처가 아니라 **이미 만든 검증기의
판정이 소비자에게 돌아오는 간선 하나**, 그리고 그 측정을 3배 싸게 만드는 캐시다.

---

## Verification (검토 자체의 재현)

```bash
# G4 실측 재현 (프로파일)
KIS_USE_MOCK=1 python3 -c "import time;from scripts.t3_transmission import build_panel;\
from src.engine.allocation_backtest import walk_forward;\
n,R,d,p,_=build_panel(months=84);b=dict(model='bl',rebalance='M',min_train=252,cost_bps=10.0);\
walk_forward(n,R,d,**b);\
t=time.perf_counter();walk_forward(n,R,d,**b);print('무조건부',time.perf_counter()-t);\
t=time.perf_counter();walk_forward(n,R,d,**b,regime={'points':p,'weighting':'hard'});print('조건부',time.perf_counter()-t)"

# G1 실측 재현 (판정을 읽는 생산 경로가 없다)
grep -rln "research_verdict\|research_power" --include=*.py src/api/    # 비어 있어야 한다
```
