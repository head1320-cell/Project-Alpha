# BA · 남은 문을 잇는다 — ★문이 세 종류였고 "열셋" 은 틀린 숫자였다★

작성 2026-09-22 · 어휘·레지스트리 `src/domain/cost_provenance.py` ·
문 `src/api/strategy_routes.py` · 검증 `tests/test_cost_door_wiring.py` ·
정적 축(읽기만) `src/engine/cost_model_registry.py` ·
앞 프로그램 [AZ](2026-09-22-cost-rate-provenance-design.md) ·
기록 `docs/HISTORY.md` 의 BA 항목

## 1. AZ 가 남긴 경고

AZ 는 `screener` 한 문을 잇고 *"남은 문 열셋"* 이라 적으면서 경고를 달았다:
*"열넷 중 몇이 **API 문**이고 몇이 **내부 호출부**인지 재지 않았다. 내부
호출부는 *'요청이 명시했는가'* 라는 질문 자체가 성립하지 않을 수 있다 —
★그러면 `unknown` 이 영구적으로 맞는 답이고 잇는 것이 오히려 거짓★."*

**쟀고, 경고가 맞았다. 그리고 실측이 두 번 더 뒤집었다.**

## 2. ★실측 ① — "열셋" 은 틀린 숫자다★

| 종류 | 자리 | 이을 수 있나 |
|---|---|---|
| pydantic 요청 · `kis_backtest_engine` 을 부름 | **2** | ✔ (`screener` 는 AZ, `legacy_schemas` 는 BA) |
| pydantic 요청 · **다른 엔진** | 3 | ✘ ★`cost_model` 블록 자체가 없다★ |
| dataclass·함수 기본값 | 6 | ✘ 요청이 없다 |
| DB DDL `DEFAULT` | 1 | ✘ ★저장 시점 — 축이 다르다★ |
| `market_rules` 계열 | 2 | ✘ ★이미 설정 단일 출처★ |

## 3. ★실측 ② — `cost_model` 을 내는 엔진은 하나뿐이다★

`"cost_model"` 전수: **`src/kis_backtest_engine.py` 한 곳**.
`multi_strategy_backtest`·`realism_engine`·`graph_runner` 는 **수수료를
부과하면서 블록을 아예 안 낸다**(`graph_runner` 는 `cost` 키 0건).

> ★정정 (2026-09-24, BB)★ — `graph_schema` 문은 `graph_runner` 가 아니라
> **`dag_runner`** 로 간다. `graph_runner` 는 호출자가 0건이다. 위 문장과 §5 의
> `other_engine` 사유는 그 점에서 거짓이었다 — BB 가 바로잡았다
> ([BB 스펙](2026-09-24-engine-cost-blocks-design.md)).
★`rate_provenance` 이전에 비용을 말할 표면 자체가 없다.★

**BA 는 관측·등록만 한다** — 세 엔진의 결과 모양을 바꾸는 일이라 저장된
응답·프런트 계약을 먼저 재야 하고, 별건으로 지정한다.

## 4. ★실측 ③ — 문이 세 종류였다★

| | `ImportAndBacktest` | `KISBacktest` | `Optimize` | `DSLBacktest` |
|---|---|---|---|---|
| `commission_rate` 칸 | ★없음★ | 있음 | 있음 | 있음 |
| `slippage_rate` 칸 | ★없음★ | 있음 | ★없음★ | 있음 |

★칸이 없으면 요청자가 줄 방법이 없다.★ 그것을 `door_default`(*"요청이
안 실어서"*)라고 부르면 **사유가 거짓**이 된다. AZ 가 `unknown ≠
door_default` 를 가른 것과 **정확히 같은 모양의 실수**이고 한 단계 더 안쪽에
있었다.

그래서 `RATE_NO_FIELD = "door_has_no_field"` 를 만들고 `rate_provenance` 가
`available`(문이 **가진** 칸, `type(req).model_fields`)을 받는다:

| 문이 묻나 | 요청이 답했나 | 결과 |
|---|---|---|
| ✔ | ✔ | `request` |
| ✔ | ✘ | `door_default` |
| ★✘★ | — | ★`door_has_no_field`★ |
| 미상(안 이음) | 미상 | `unknown` |

★`available=None` 이면 예전 그대로★ — AZ 가 이은 `screener` 가 안 깨진다.

## 5. 못 잇는 자리를 종류별로

`UnwiredCostSite(key, kind, reason, promotes_when, permanent)` —
`version_registry.MissingAxis`·`signal_supply.UnsuppliedSignal` 과 같은 모양.

| `kind` | 개수 | 영구? |
|---|---|---|
| `other_engine` | 3 | ✘ — 그 엔진이 `cost_model` 을 내면 이을 수 있다 |
| `no_request` | 6 | ★✔★ 호출부가 값을 정하는 것이 설계다 |
| `db_default` | 1 | ★✔★ 저장 시점이라 런타임 질문이 성립하지 않는다 |
| `config_layer` | 2 | ★✔★ 이미 단일 출처라 이을 대상이 아니다 |

★`permanent` 를 **칸으로** 둔다★ — 처음 쓴 테스트는 `promotes_when` 문자열
에서 *"영구"·"아니"* 를 찾았고 *"해당 없습니다"* 라고 적은 항목을 놓쳤다.
**어휘로 건 것이다.** 구조로 고쳤다.

**트립와이어** — ★이은 `key` + 못 이은 `key` = `COST_SITES` 의 `key` 전부★.
개수를 손으로 세지 않고 **정적 레지스트리에서 읽어 대조한다**. 누가 자리를
하나 더하면 여기가 red 가 된다.

## 6. 실측 결과

    문                                commission         slippage
    strategies/import-and-backtest    door_has_no_field  door_has_no_field
    strategies/backtest               door_default       door_default
    strategies/optimize               door_default       ★door_has_no_field★
    strategies/dsl/backtest           door_default       door_default

★`optimize` 가 한 요청 안에서 성분마다 다르게 나온다★ — 한 값으로 접었다면
둘 중 하나가 거짓이 됐다.

## 7. ★이 설계가 하지 않는 것★

- **세 엔진에 `cost_model` 블록을 만들지 않는다.** 가장 큰 발견이지만 결과
  모양을 바꾸는 일이라 별건이다.
- **기본값을 통일하지 않는다.** 재본 적이 없다(AZ 와 같다).
- **요율 값을 한 자리도 안 바꾼다.** 체크인된 골든 상수가 지킨다.
- **`cost_model_registry` 를 고치지 않는다.** 읽기만 한다.
- **`no_request`·`db_default`·`config_layer` 를 "나중에 할 일" 로 적지
  않는다.** ★영구적으로 맞는 답이다★ — 임시라 적으면 갚을 수 없는 부채가 된다.
- **열넷을 손으로 세지 않는다.** 레지스트리에서 읽는다.
- **체결 모델을 만들지 않는다.** §6 보호 구역이다.
- **채점표를 올리지 않는다.** #6 은 여전히 **부분**이다.
- **화면을 만들지 않는다.**
