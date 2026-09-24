# BB · 세 엔진이 비용을 말한다 — ★셋은 같은 모양이 아니었고, BA 의 사유 하나가 거짓이었다★

작성 2026-09-24 · 빌더 `src/domain/cost_model.py::policy_only_block` ·
문 헬퍼 `src/domain/cost_provenance.py::door_cost_block` ·
문 `src/api/stage11_routes.py`·`stage12_routes.py`·`strategy_routes.py`(graph) ·
검증 `tests/test_engine_cost_blocks.py`·`tests/test_cost_door_wiring.py` ·
앞 프로그램 [BA](2026-09-22-cost-door-wiring-design.md)

## 1. BA 가 남긴 것

BA 는 *"`cost_model` 블록을 내는 엔진은 `kis_backtest_engine` 하나뿐"* 을 재고,
다른 엔진에 닿는 문 셋을 `other_engine`(움직일 수 있음)으로 등록한 뒤 별건으로
지정했다. 사용자가 진행하라고 했다.

## 2. ★실측 ① — BA 의 사유 하나가 거짓이었다★

BA 는 `graph_schema` 문의 사유를 *"graph_runner 를 부른다"* 로 적었다. 실제로
`GraphBacktestRequest` 는 `strategy_routes.py` 의 `graph_backtest` 에서
**`dag_runner.execute_dag_backtest`** 로 간다. `graph_runner` 는 ★`src/` 에
import 하는 곳이 0건★ 이다(AST 로 쟀다).

그래서 비용을 부과하면서 말하지 않는 엔진은 **넷이 아니라 셋**이다:

| 엔진 | 문 | 비용 합계를 세나 |
|---|---|---|
| `multi_strategy_backtest` | `multibacktest/run`·`multibacktest/counterfactual` | ✘ 셈 없음 |
| `realism_engine` | `realism/backtest` | △ 시장충격만(`realism_stats.total_market_impact_cost`) |
| `dag_runner` | `backtest/graph` | ✔ `total_commission`·`total_slippage` |
| ~~`graph_runner`~~ | ★없음★ | — ★쓸 곳이 없으므로 만들지 않는다★ |

## 3. ★실측 ② — 셋은 같은 모양이 아니다★

계획은 *"세금·스프레드·충격은 이 엔진들에 없다"* 였다. 재 보니
**`realism_engine` 은 시장충격을 기본으로 부과한다**(`enable_market_impact=True`).
그런데 그 충격은 메인 엔진의 `k·√참여율` 과 **다른 모델**이다 — 회전율 기반
`turnover_based_impact` 이고 ADV 는 요청의 `avg_adv_krw` ★가정값★, 변동성은
`0.018` ★고정★이다.

셋을 한 모양으로 접었다면 `realism` 의 충격이 *"이 엔진엔 없다"* 로 거짓말을
했다. 그래서 빌더가 **엔진마다 있는 성분**(`supported`)을 받는다.

## 4. ★세 상태를 가른다 — 기존 어휘를 쓴다★

`cost_model.py` 에는 AK 가 정의만 하고 **아무도 안 쓰던** `STATE_UNSUPPORTED`
가 있었다(*"다른 엔진을 레지스트리에 적을 때 쓴다"*). 새로 만들지 않고 그것을 쓴다.

| 상태 | 뜻 | 예 |
|---|---|---|
| `charged` | 부과했다 | 세 엔진의 수수료·슬리피지 |
| `off` | ★있는데 껐다★(선택) | `realism` 에서 `enable_market_impact=False` |
| `unsupported` | ★이 엔진엔 그 성분이 없다★ | 세 엔진의 세금·스프레드 |
| `unmeasurable` | 켰는데 재료가 없다(경고) | ★여기서는 안 쓴다★ |

계획은 `off` 였다. ★`off` 는 *"켤 수 있었는데 안 켰다"* 로 읽혀★ 켤 문이 없는
사용자를 헤매게 한다. `unmeasurable` 은 *"비용이 싸게 나왔다"* 는 경고인데
이 엔진들에서 그것은 사실이 아니라 **설계**다.

## 5. ★미상 ≠ 0★ — 거래별로 재지 않는 엔진

메인 엔진 블록의 키를 **전부 같은 이름으로** 싣는다(테스트가 메인 엔진을
**실제로 읽어** 부분집합임을 건다). 다른 점은 센 적이 없는 것을 `None` 으로 둔다는
것뿐이다:

- `n_unmeasured_trades: None` · `n_unmeasurable: None` · `total_bps: None`
- `breakdown: None` + `breakdown_reason`
- 성분 `krw` 는 **엔진이 실제로 센 것만** — `dag_runner` 는 둘, `realism` 은 충격만
- ★일부만 셌으면 `total_krw` 는 None★ — 센 것만 더하면 싼 합계가 된다
- 충격의 `bps` 는 None — 참여율에 달린 식이라 고정 bp 가 없다

## 6. 문에서 붙인다 — 엔진 내부는 0줄

`door_cost_block` 이 ★엔진에 넘긴 그 요율★로 정책을 만들고(`× 1e4`, 메인
엔진 `policy_from_config` 와 같은 환산), 출처는 메인 엔진과 같은
`rate_provenance` 가 답한다. ★돌지 않은 실행(`success` 가 거짓)에는 블록을
붙이지 않는다★ — *"부과했다"* 가 거짓이 된다.

## 7. 레지스트리

- `stage11_routes`·`stage12_routes`·`graph_schema` → `WIRED_SITE_KEYS`
- ★`other_engine` 이 비어서 어휘에서 뺐다★ — BA 의 `test_the_kinds_are_actually_used`
  가 그것을 **요구했다**(트립와이어가 일했다)
- ★남은 못 이은 자리는 전부 `permanent`★ — *"아직 할 일" 0개* 라는 강한 진술을
  테스트로 건다
- `graph_runner` 의 사유에 **호출자 0건**을 적고, 그 진술을 AST 로 잰다(대조군:
  같은 탐지기가 `dag_runner` 의 호출자를 찾는다)

## 8. ★실측 ③ — 문 둘은 오늘 돌지 않는다★

`multi_strategy_backtest.py:85` 가 `from src.engine.allocator import
MultiStrategyAllocator` 를 하는데 **그 모듈이 이 체크아웃에 없다**(이
체크아웃이 가진 이력에도 없다 — 얕은 클론이라 그 너머는 미상). 그래서 `multibacktest/run`·`counterfactual`·`realism/backtest` 는 ★오늘
항상 500★ 이다. 블록은 성공할 때만 붙으므로 **지금은 한 번도 안 나온다**.

★배분 결정 경로라 고치지 않았다★(CLAUDE.md §3 — 별도 승인). 테스트는 엔진을
가짜로 바꿔 ★엔진이 실제로 받은 config★ 와 블록의 bp 를 대조한다. `dag_runner`
문은 mock 데이터로 **실제로** 돌려 확인했다.

## 9. ★레지스트리의 거짓 기록 둘★ (변이 h 가 드러냈다)

문 기본값을 절대값 골든으로 걸고 정적 레지스트리와 대조하자 두 줄이 red 가 됐다:
`graph_schema` 의 수수료(`None` → 실제 **15bp**)와 `stage12_routes` 의 충격(기본
**켜짐**). 기록을 고쳤다 — 요율 값은 불변이다.

## 10. ★이 설계가 하지 않는 것★

- **엔진 내부를 고치지 않는다.** 블록은 문에서 붙인다(§6 보호 구역).
- **`graph_runner` 에 아무것도 만들지 않는다.** 호출자 0건이다.
- **없는 allocator 를 만들지 않는다.** 배분 정책이다 — 별건으로 남겼다.
- **요율 값·기본값을 바꾸지 않는다.** 골든 상수가 지킨다.
- **realism 의 충격 모델을 고치지 않는다.** 가정이라고 **말할** 뿐이다.
- **netting 절감 추정(`turnover × 1.5`)을 다루지 않는다.** 비용이 아니라 추정된
  절감이고 별개 질문이다.
- **프런트·채점표를 건드리지 않는다.** #6 은 여전히 **부분**이다.
