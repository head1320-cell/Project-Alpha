# E · 증거 없는 주장 — ★가장 강한 주장을 하는 배지가 증거가 가장 없다★

> 설계일 2026-09-18 · 채점표 [`2026-09-12-addendum-scorecard.md`](../../specs/2026-09-12-addendum-scorecard.md) #3
> · 선행 `Z`(perf_label) · `R2`(price_basis) · `R3`(survivorship) · `R4`(pit_evidence)
> · `AG`(execution_assumption) · `AH`(estimator_leakage) · `ADR 001`(CSS 클래스명 = E2E 계약)

## 1. 왜 하는가

채점표 #3 은 `부분` 의 이유로 둘을 적었다 — ⑴ 레거시 배지가 `PerfLabel` 과 축이 달라
한 화면에 겹친다, ⑵ 사유 붙은 허용목록 8건. **둘 다 사실이지만, 배지를 읽어 보니 더
큰 것이 있었다.**

### ★실측 (2026-09-18, 전부 직접 확인)★

| 배지 | 무엇을 주장하나 | 근거 |
|---|---|---|
| `brun-badge`(PIT) | 시점 정합 | ✅ `res.pit_evidence` 를 **읽는다** |
| `brun-badge`·`tbt-prov`·`as-badge-mock`(mock) | 데이터 출처 | ✅ 응답·`coverage.source` 를 읽는다 |
| **`as-bt-badge ok` — `"OOS · look-ahead 없음"`** | **룩어헤드 없음** | ❌ **하드코딩 상수** |

`frontend/src/widgets/allocation/PolicyBacktest.tsx:110` 은 `ok` 가 참이기만 하면
무조건 렌더된다. 응답 타입(`AllocationBacktestResult`)에 이 주장을 뒷받침할 필드가
**하나도 없고**, 백엔드(`src/api/allocation_routes.py:878`)도 그 문장을 **docstring
에만** 적어 두었다. 그러면서 같은 응답에 `perf_label` 은 **이미 싣는데**(`:911`) 이
화면은 그것을 그리지 않는다.

★AL 의 `selection_effect=0`, AM 의 `"dev"` 와 같은 모양이다★ — **상수가 관측 행세를
한다.** 그리고 AG·AH·R2·R3·R4 가 바로 그 룩어헤드를 **재는 법**을 이미 만들어 두었는데,
이 경로만 그것을 하나도 통과하지 않는다.

### ★E2E 테스트가 그 거짓 주장을 지키고 있다★

`frontend/e2e/allocation-backtest.spec.ts:25`

```ts
await expect(page.getByText("OOS · look-ahead 없음")).toBeVisible();
```

배지를 고치려면 이 스펙을 함께 고쳐야 한다 — ADR 001 이 정확히 요구하는 절차다.

### ★주장의 절반은 참이다★ — 섞지 않는다

`src/engine/allocation_backtest.py:471-472` 의 `R_win = R[lo:t]`(t **미포함**)는
리밸런싱 가중치가 창 밖 데이터를 쓰지 않음을 **구조적으로** 보장한다. 그러니 "OOS" 는
사실이다. 그러나 "look-ahead 없음" 은 네 축을 한꺼번에 주장한다:

| 축 | 이 경로의 실제 상태 |
|---|---|
| 창 격리 | ✅ 구조적으로 참 (`R[lo:t]`) |
| `as_of` 고정 | ⚠️ `coverage.as_of_requested` 가 `None` 이면 **고정하지 않았다** |
| 생존편향 | ❌ 유니버스가 사용자가 **지금** 고른 바구니 — R3 의 라벨을 안 쓴다 |
| 가격 기준(`adj_close` 소급 개정) | ❌ **재지 않는다** — R2 의 `basis_rollup` 을 안 통과한다 |

★CLAUDE.md §2 "네 질문을 섞지 마세요" 를 배지가 어기고 있다★ — 좁은 구조적 사실
하나로 네 축 전부를 주장한다.

## 2. ★검출기 프로토타입이 계획을 뒤집었다 — 이번엔 반대 방향★

"같은 부류를 전부 찾자" 는 방침으로 **주장 어휘**(룩어헤드·OOS·검증됨·보장·안전·
무결…) 검출기를 프런트 전체에 돌렸다. 21건이 잡혔고, **전수 분류 결과 진짜는 하나**
였다.

**진짜 상수 주장 — 1건**: `PolicyBacktest.tsx:110`

**약한 건 — 3건**(구조적으로는 참, 축이 뭉뚱그려짐): `app/page.tsx:90` 랜딩 카드
`["검증","워크포워드 OOS"]` · `app/allocation/journal/page.tsx` 제목
`정책 백테스트 (Walk-Forward · OOS)` · `ResearchRunsPanel.tsx:292` 툴팁
`inputs/outputs 정합 보장`

**오탐 — 17건.** ★오탐의 성격이 설계를 결정한다★:

- **무위험이자율·무위험수익률·무위험금리** ×4 — risk-free rate, 정당한 금융 용어
- `alphalab/page.tsx:24` `validated: "검증됨"` — 백엔드 `alpha_registry` 5단계의 **번역**
- `WizardTracker.tsx:49` `alphaTouched ? "검증됨" : "미검증"` — **삼항, 관측**
- `BacktestResults.tsx:263` `…"검증됨" 이 되지 않습니다` — **부정문, 모범**
- `BacktestResults.tsx:411,553` `시점 정합을 판정할 자료가 없습니다` — **모범적 미상**
- `MacroCockpit.tabs.strategy.tsx:204` `미래 수익을 보장하지 않습니다` — **면책**
- `BuyConditionPanel.tsx:147` `look-ahead 주의` — **경고**
- `macro_lookahead` — 필드명 · `IS / OOS` 표 헤더 — `report.is_oos` 를 읽는다

즉 **어휘 검출기의 신호 대 잡음은 1:17** 이다. 그대로 트립와이어로 만들면 허용목록이
17줄이 되고, 그것은 이 저장소가 경계하는 *"삭제하거나 상수로 박아도 통과하는 테스트"*
의 사촌이다 — **허용목록이 본문보다 길면 다음 사람은 읽지 않고 한 줄 더 붙인다.**

## 3. 설계

### E1 · `src/engine/allocation_evidence.py` ★NEW★ — 룩어헤드 축 롤업

`run_evidence.rollup` 을 재사용한다 — `pit_evidence`·`decision_evidence`·
`estimator_evidence`·`multiplicity_evidence`·`cost_model_registry`·
`attribution_evidence`·`version_registry` 와 **같은 함수**다(실측: 이 일곱이
`rollup` 을 부른다. `scorecard_builder` 는 `run_evidence` 를 import 하지만 `rollup`
은 부르지 않고, `daily_explain_holdings` 의 `basis_rollup` 은 **다른 함수**다 —
이름이 닮아 처음 셀 때 둘 다 잘못 넣었다).
★새 어휘를 만들지 않는다★ (CLAUDE.md §2) — 축 이름은 `run_evidence.AXIS_LABELS` 의
`price`·`universe` 를 그대로 쓰고 둘만 더한다.

| 축 | 판정 | 근거 |
|---|---|---|
| `window` 창 격리 | `ok` | `plan_walk_forward` 의 `R[lo:t]` — 구조적으로 참, 트립와이어가 지킨다 |
| `as_of` 절단일 고정 | `ok` / `degraded` | `coverage.as_of_requested` 가 `None` 이면 ★고정하지 않았다★ |
| `universe` 생존편향 | **`unknown`** | 이 경로는 R3 의 `survivorship_of` 를 통과하지 않는다 + 사유 |
| `price` 가격 기준 | **`unknown`** | 이 경로는 R2 의 `basis_rollup` 을 통과하지 않는다 + 사유 |

★미상은 통과가 아니다★ — 넷 중 둘이 `unknown` 이므로 롤업은 **절대 `verified` 가
되지 않는다**. 이것이 이 설계의 핵심 산출이다: 지금 화면이 단정하는 것을 롤업은
`partial` 이라고 말한다.

**경계** — 관측·기록만 한다. `walk_forward`·`_load_clean_returns`·`constrained_solve`
는 한 줄도 건드리지 않는다. CLAUDE.md §3 의 *"Macro → Allocation 동작·최적화기 의미·
국면-배분 정책 변경은 별도 승인 사항"* 에 닿지 않는다(같은 문장이 *"관측·검증·기록은
자유"* 라고 적는다).

`src/api/allocation_routes.py::allocation_backtest` 가 `out["lookahead_evidence"]` 로
싣는다. **docstring 의 거짓 문장도 함께 고친다** — 그 문장이 배지의 출처였다.

### E2 · 배지가 롤업을 읽는다 (프런트)

`PolicyBacktest.tsx:110` 의 상수를 걷어내고 롤업을 그린다. 응답이 이미 싣는
`perf_label` 도 `PerfLabel` 로 붙인다.

**CSS 클래스명 (ADR 001)**
- `as-bt-badge mock` / `as-bt-badge real` — `allocation-stages2.spec.ts:361-362` 가
  붙잡고 있다. ★한 글자도 안 건드린다.★
- `as-bt-badge ok` — 이 자리를 바꾼다. `allocation-backtest.spec.ts:25` 가 **문구를**
  단정하므로 그 스펙을 함께 고치고, **왜 바뀌었는지 스펙 주석에 적는다.**

`frontend/src/entities/allocation/api.ts` 의 `AllocationBacktestResult` 에 타입 추가.

### E3 · 트립와이어 — ★어휘가 아니라 구조로 건다★

`tests/test_evidence_claim_contract.py`(pytest 가 프런트 계약을 검사하는 선례:
`test_perf_label_contract.py`·`test_css_specificity_guard.py`·
`test_run_evidence_ui_contract.py`).

**규칙** — *"증거 축을 단정하는 리터럴이 있는데, 그 파일이 대응하는 응답 필드를 한 번도
참조하지 않는다."* 어휘 하나만으로는 걸지 않는다.

★테스트의 테스트★ — 위 §2 의 **오탐 17건이 전부 통과**하는지 못 박는다. 하나라도
걸리면 규칙이 아직 어휘 수준이라는 뜻이다. 그리고 짝으로, `PolicyBacktest` 의 옛
모양(상수 배지 + 응답 미참조)을 픽스처로 넣어 **반드시 걸리는지** 확인한다 —
★항상 통과·항상 거부 구현을 배제한다★.

### E4 · 배지 축 레지스트리 — ★관측만★

채점표 ⑴. 배지 클래스 → 축(성과 종류 · 데이터 출처 · 시점 정합 · 룩어헤드 · 실행 모드)
매핑을 등록하고 *"한 화면에 축이 다른 배지가 둘 이상"* 을 **관측**한다.

★통합하지 않는다★ — 축이 다른 배지가 함께 보이는 것은 결함이 아니라 사실이고,
`PerfLabel.tsx` 머리글이 이미 *"같은 화면에 축이 다른 배지가 둘 이상 보일 수 있다 —
그것은 결함이 아니라 사실이다"* 라고 적어 두었다. 레지스트리가 하는 일은 **그 사실을
세는 것**이지 줄이는 것이 아니다.

### E5 · 허용목록 · 문서 · 게이트

- `PolicyBacktest` 가 `PerfLabel` 을 달면 `test_perf_label_contract.ALLOWED` 가 8 → 7.
  ★나머지 7은 그대로 둔다★ — 사유가 타당하다. 특히 `CompanyCockpit`(종목 위험지표)에
  백테스트 라벨을 붙이면 **없는 시뮬레이션을 있다고** 말하게 된다. 줄이려고 붙이지 않는다.
- 채점표 #3 정정 — ⑴⑵ 외에 ★상수 주장★ 이 있었다는 사실과 검출기 실측(1 대 17)을 적는다.
- `docs/HISTORY.md` — 무엇을 · 왜 · **무엇을 하지 않았는지**.
- 변이 배터리 · `make all`(lint + test + typecheck + build).

## 4. 검증

1. `KIS_USE_MOCK=1 python3 -m pytest tests/ -q` — 기준선 **5,951 통과 / 10 스킵 / 0 실패**.
   (`make test` 는 못 쓴다 — bare `pytest` 가 pandas 없는 인터프리터로 간다.)
2. **실물 확인** — `/api/v1/allocation/backtest` 를 mock 으로 호출해
   `lookahead_evidence.status` 가 `verified` 가 **아닌지**, `universe`·`price` 축이
   `unknown` + 사유인지 본다. ★이것이 되지 않으면 이 작업은 라벨만 바꾼 것이다.★
3. `as_of` 를 주고 호출하면 그 축이 `ok` 로 **바뀌는지**(짝 테스트).
4. E2E `allocation-backtest.spec.ts` · `allocation-stages2.spec.ts` 를 함께 본다.
5. 변이 배터리 — 각 가드가 특정 변이를 죽이는지:
   `a` 롤업이 `unknown` 축을 `ok` 로 접는다 · `b` 배지가 다시 상수로 돌아간다 ·
   `c` 검출기가 오탐을 걸기 시작한다 · `d` 검출기가 진짜를 놓친다 ·
   `e` `as_of` 미고정이 `ok` 가 된다 · `f` 허용목록을 비워도 통과한다.
6. `make all` → 커밋 → `git push -u origin claude/backtest-modern-ui-refactor-akxvbc`.
   ★PR 은 만들지 않는다★ (요청받지 않음).

## 5. ★이 설계가 하지 않는 것★

- **룩어헤드가 없다고 말하지 않는다.** 네 축 중 둘을 **재지 않는다**고 말할 뿐이다.
  이 작업이 하는 일은 그 둘이 ★참인 척하지 못하게★ 하는 것이다.
- **생존편향·가격 기준을 재게 되지 않는다.** `_load_clean_returns` 는 배분 결정
  경로라 손대지 않는다(CLAUDE.md §3). 재는 것은 별도 승인이 필요한 다음 작업이다.
- **`walk_forward` 의 수치를 바꾸지 않는다.** 한 줄도 안 건드린다.
- **배지를 통합하지 않는다.** 축이 다른 배지는 함께 보이는 것이 맞다 — 세기만 한다.
- **허용목록을 줄이는 것을 목표로 삼지 않는다.** 7건은 사유가 타당해서 남는다.
- **랜딩 카피(`app/page.tsx:90`)를 고치지 않는다.** 제품 소개이고 walk-forward 는
  구조적으로 참이다 — 다만 검출기가 그것을 **약한 건으로 기록**한다.

---

# 부록 · ★구현이 설계를 뒤집은 지점★ (2026-09-18, 구현 후 추가)

설계 문서를 고쳐 쓰지 않고 **무엇이 왜 바뀌었는지** 여기에 남긴다 — 설계가 옳았던
척하면 다음 사람이 같은 함정에 빠진다.

## ① 규칙 ②(응답 필드를 읽는가)가 **면제 사유가 아니었다**

설계는 위반을 *"단정한다 **그리고** 대응 응답 필드를 안 읽는다"* 로 정의했다.
변이 배터리가 그것을 죽였다 — **옛 상수 배지를 그대로 되돌려도 통과했다.**
`PolicyBacktest.tsx` 가 파일의 다른 곳에서 `lookahead_evidence` 를 읽으니
면제된 것이다.

★증거를 읽는다고 상수로 단정할 권리가 생기지는 않는다.★ 상수 문자열은 파일이
무엇을 읽든 변하지 않는다. 그래서 필드 참조는 **면제에서 진단으로** 내렸다 —
위반 메시지가 *"이 파일은 그 값을 이미 받고 있으니 그것을 그려라"* 고 말할 뿐이다.

## ② `OOS`·`표본외` 는 **주장이 아니라 서술어**다

`\bOOS\b` 를 주장 패턴에 두었더니 표 머리글(`IS / OOS`)과 랜딩 카드가 걸렸고,
그것을 면제로 덮고 있었다. `무위험`(risk-free)을 뺀 것과 **같은 이유**로 뺐다 —
진짜 주장은 **부재**(`룩어헤드 없음`·`편향 없음`)와 **보장**(`정합 보장`)이다.
빼고 나니 랜딩 면제가 필요 없어졌다.

## ③ 부정·삼항·식별자 필터가 **한 번도 실행되지 않고 있었다**

변이 배터리가 그 필터들을 통째로 지워도 전부 초록이었다. 패턴이 이미 좁아
오탐이 필터까지 **닿지도 못했기** 때문이다 — ★공허한 분기는 증거가 아니다★
(AL 의 변이 `d` 와 같은 모양). 패턴을 **실제로 맞힌 뒤** 필터에 걸리는 픽스처
넷(`룩어헤드 없음을 뜻하지는 않습니다` · `정합 보장을 하지 않습니다` ·
`ok ? "룩어헤드 없음" : "룩어헤드 미상"` · `편향 없음을 확인하지 못했습니다`)을
넣어서 비로소 그 변이들이 죽었다.

## ④ 허용목록이 네 번 바뀌었고 매번 실측이 이겼다

셋 → (유령 하나 제거) 둘 → (유령 하나 더 제거) 하나 → (규칙 ②·`OOS` 변경) **하나**
(내용이 통째로 교체: 랜딩 → `ResearchRunsPanel` 툴팁). ★사유가 있다고 필요한
면제는 아니다★ — `test_every_weak_claim_is_actually_needed` 가 매번 잡아냈다.

## ⑤ 부분문자열 금지가 **세 번** 제 발을 걸었다

`note` 테스트 · 라우트 docstring 테스트 · 검출기 자체가 모두 *"`X` 라고 쓰지
않는다"* 는 **부정문**을 주장으로 읽었다. 같은 교훈이 한 프로그램 안에서 세 번
반복됐다는 사실 자체가 ★어휘로 걸면 안 된다★ 의 가장 강한 증거다.

## ⑥ 응답 키 계약이 **없어서** 두 가지가 숨어 있었다

`/analyze` 에는 `ANALYZE_KEYS` 골든이 있는데 `/backtest` 에는 없었다. 그래서
⑴ 응답이 `perf_label` 을 싣는데 프런트 타입에 **없어서 화면이 볼 수 없다**는 것과
⑵ 실제 키가 골든보다 다섯 개 많다(`error`·`impact`·`long_short`·`notes`·
`regime_audit`)는 것을 아무도 몰랐다. 이 커밋에서 `BACKTEST_KEYS` 를 세운다.
