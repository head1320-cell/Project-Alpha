# 규칙 가동(기록 전용) — 구현 계획 (W5b · 2026-11-14)

> 설계 [모의투자·관제](../specs/2026-11-14-paper-trading-monitor-design.md) §5 · §8 · 받은 결정 §12(D3 관문은 막지 않고 보여 준다 · D4 재시작하면 전부 꺼진다 · D6 W5a → W5b → W5c).
> 방식: 조각마다 빨강 먼저 → 짝 · 변이 → 게이트 → HISTORY → 커밋 · 푸시. 하위 에이전트 없음.
> ★이 조각은 증권사에 주문을 내지 않는다★ — 계좌의 모드가 기록 전용(`SHADOW`)일 때의 길만 만든다. 모의투자(`PAPER`) 주문은 탐침 뒤(W5d).

## 0. 구현 전에 조사로 정한 것 (설계와 달라지는 점 포함)

1. **시뮬레이터는 '끝나지 않은 하루'를 모른다.** `simulate` 는 종목의 마지막 봉에서 남은 수량을 강제 청산한다(`session_end`). 그날의 지금까지 봉으로 다시 돌리면 ★그 강제 청산이 봉마다 생기고★,
   보유 한도(`max_open`) · 하루 손실 한도 · 손실 뒤 쉬기가 걸린 설정에서는 그 가짜 청산이 **다른 종목의 가짜 진입**까지 만든다(풀린 자리로 들어간다). 가짜 줄을 사후에 걸러 내는 것으로는 막을 수 없다.
   → `Day` 에 스위치 하나(`final: bool = True`)를 더한다. `final=False` 면 마지막 봉의 강제 청산과 대기 진입 취소를 하지 않는다. 기본값은 지금 동작 그대로다(골든 불변 — 시험이 건다).
   설계 §5.4 의 "`simulate` 그대로"에서 달라지는 점이고, ★체결가 규칙(`fills.py`)과 규칙 평가(`expr.py`)는 0줄★이다.
2. **재생의 시계는 부르는 쪽이 민다.** 재생 가동은 `advance(봉 수)` 를 부를 때마다 그만큼 흐른다(배경 스레드 없음). 중간 상태(비상 정지 · 봉 끊김)를 시험과 화면이 그대로 볼 수 있고, 결정적이다.
   장중 조회 공급(`PollingFeed` — W5d)은 새 봉이 올 때 같은 `advance` 를 부르면 된다.
3. **신호를 내는 때**: 기록 전용에서는 ★체결 줄이 생긴 봉★에서 신호를 남긴다(신호 봉의 다음 봉). 실제 주문(W5d)은 신호 봉이 닫힐 때 나가야 다음 봉 시가 근처에서 체결된다 —
   그러려면 시뮬레이터가 '걸어 둔 진입 · 청산'을 내줘야 한다. ★W5d 에서 정한다(이 조각은 하지 않는다).★
4. **가동의 단위는 하루다.** 가동 하나 = 계좌 하나 × 시행 하나 × 날짜 하나. 하루를 넘기지 않는 규칙이라 날을 넘겨 이어 갈 상태가 없다.

## 1. 조각과 파일

| # | 조각 | 파일 | 끝났다는 판정 |
|---|---|---|---|
| b1 | 걸음 엔진(순수) | `src/engine/intraday/simulator.py`(`Day.final`) · 새 `src/engine/intraday/stepper.py` · `tests/test_intraday_stepper.py` | 모든 틀에서 **걸음마다 낸 체결의 이어 붙임 = 하루를 한 번에 돌린 체결**(줄 단위 · 순서까지) |
| b2 | 저장소 | 새 `src/data/rule_runs.py` · `tests/test_rule_runs_store.py` | 요청 · 가동 · 가상 체결을 본인 것만 읽고 쓴다 · 못 읽음 ≠ 없음 |
| b3 | 가동기 | 새 `src/execution/rule_runner.py` · `tests/test_rule_runner.py` | §5.6 의 성질 다섯(재생) |
| b4 | 문 | `src/api/broker_account_routes.py` · `src/api/intraday_routes.py` · `protected_routes.py` · `accessMap.json` · `tests/test_rule_run_routes.py` | 본인 계좌만 · 판정 없는 설정 거절 · 재시작하면 꺼짐 |
| b5 | 캔버스 노드 | `src/api/allocation_graph_nodes_act.py` · `…_nodes_backtest.py`(출력 포트 `IntradayRun`) · `tests/test_allocation_graph_arm_request.py` | 계산은 쓰기 0 ↔ 단추는 요청 한 줄 · AST 가드 · AI 후보 표 밖 |
| b6 | 화면 | `frontend/src/widgets/my-account/`(절 '규칙 가동') · `entities/broker-account` · 캔버스 결과 판 · `e2e/rule-arming.spec.ts` | 재생 E2E: 요청 → 가동 → 걸음 → 가상 체결 = 분봉 백테스트의 체결 |

b1 → b2 → b3 → b4 는 서버만이고 조각마다 커밋한다. b5 · b6 은 화면까지 한 묶음.

## 2. b1 — 걸음 엔진

```python
# simulator.py
@dataclass(frozen=True)
class Day:
    ...
    final: bool = True      # False: 아직 끝나지 않은 하루 — 마지막 봉의 강제 청산과 대기 진입 취소를 하지 않는다

# stepper.py (순수 · I/O 없음)
class StepError(ValueError): code  # not_monotone · out_of_order · finished
class Stepper:
    def __init__(self, date, base: dict[str, Session], rule, position, costs, *, rules=None): ...
    def step(self, label: str) -> list[dict]:     # 그 시각까지의 봉으로 다시 돌려 ★새로 생긴 체결 줄만★
    def finish(self) -> list[dict]:               # 하루가 끝났다 — 강제 청산 줄
    fills: list[dict]                             # 지금까지 낸 줄(낸 순서)
    events: list[dict]                            # 줄마다의 종류(entry_signal · stop · session_end …)
```

- `base` 는 그날의 전체 봉이 아니라 ★지금까지 받은 봉★을 가진 쪽이 채워 준다: `step(label)` 은 `time <= label` 인 봉만 잘라 `Day(final=False)` 로 돌린다. 재생 공급자는 하루치를 들고 시각만 민다.
- **단조 검사**: 다시 돌린 결과의 앞부분이 이미 낸 줄과 다르면 `StepError("not_monotone")` — 조용히 덮지 않는다(가동이 그 사유로 멈춘다).
- 시험(빨강 먼저): ① 틀 일곱 × 합성 여러 종목 하루 — `step` 전부 + `finish` 의 이어 붙임 == `simulate([Day])["fills"]` ② 보유 한도가 걸린 설정에서 가짜 진입이 없다(스위치를 끄면 빨강 — 변이)
  ③ `finish` 전에는 `session_end` 줄이 없다 ④ 같은 시각을 두 번 · 뒤로 가는 시각은 거절 ⑤ `final=True` 의 결과는 스위치를 더하기 전과 같다(기존 골든 · 기존 시험 전부 초록) ⑥ 봉이 없는 시각의 걸음은 빈 목록.

## 3. b2 — 저장소 `src/data/rule_runs.py`

| 표 | 칸 | 뜻 |
|---|---|---|
| `rule_arm_requests` | `id` · `username` · `trial_key` · `note` · `created_at` · `removed_at` | 캔버스가 남긴 '가동해 달라'는 요청 한 줄. 지우기는 표시(`removed_at`)만 한다 |
| `rule_runs` | `run_id`(정수) · `username` · `account_id` · `trial_key` · `request`(설정 사본 JSON) · `day` · `feed`(`replay`) · `mode`(시작할 때의 모드) · `grade` · `status`(`running`·`stopped`·`finished`·`interrupted`) · `stop_reason` · `stop_message` · `last_bar` · `bars` · `signals` · `started_at` · `ended_at` | 가동 하나. `run_id` 가 주문 · 감사 줄의 `strategy_id` 다 |
| `rule_run_fills` | `run_id` · `seq` · `executed_at` · `symbol` · `side` · `quantity` · `price` · `kind`(`virtual`) · `event` · `client_order_id` · `order_status` · `order_reason` | 가상 체결 한 줄 + 그 신호가 주문 경로에서 받은 답 |

- 전부 `username` 으로 갈린다(남의 것은 없는 것과 같은 답). 읽기 실패는 `None`(없음 `[]` 과 다르다) — `intraday_trials` 의 관례 그대로.
- `live_fills` 에는 쓰지 않는다(시험: 가동 전후 행 수).
- `mark_interrupted()` — 기동 때 한 번 불러 `running` 으로 남은 줄을 `interrupted`("서버 재시작")로 바꾼다.

## 4. b3 — 가동기 `src/execution/rule_runner.py` (프로세스 로컬)

```python
def start(username, account_id, trial_key, day, *, feed="replay") -> dict      # 가동 한 줄 + 메모리의 걸음 엔진
def advance(username, account_id, run_id, bars: int | None) -> dict            # bars=None 이면 끝까지
def stop(username, account_id, run_id, *, reason="user") -> dict
def active(account_id) -> list[dict]
```

- 설정은 시행 줄에서 읽는다(`intraday_trials` — 본인 것만). ★시행이 없는 설정은 가동할 수 없다★(`no_trial`). 운영 게이트에서 합성 등급의 시행은 거절(`synthetic_in_production`).
- 봉은 `minute_feed.build_days` 로 그날 하루를 읽는다(백테스트와 같은 준비 — 전일 값 · 품질 검사 · 운영의 합성 차단 포함). 그날이 적재돼 있지 않으면 `not_loaded`.
- 걸음마다: `Stepper.step(label)` → 새 줄마다 `get_account_executor(account_id).execute_signal(신호, actor="rule")`(★이 한 길뿐★) → `rule_run_fills` 에 가상 체결 + 주문의 답.
- 멈추는 조건(전부 `stop_reason` + 문장): `user` · `kill_switch`(신호가 `kill_switch_active` 로 거절됨) · `risk_rejections`(거절이 연달아 3번) · `feed_gap`(재생: 다음 봉까지 빈틈이 `GAP_MINUTES` 를 넘음) ·
  `not_monotone` · `mode_changed`(시작할 때의 모드와 달라짐 — 사람이 모드를 바꿨으면 다시 가동해야 한다) · `finished`(하루 끝) · `interrupted`(재시작).
- 상한: 계좌당 동시 가동 `MAX_RUNS_PER_ACCOUNT = 3` · 가동 하나의 종목 `MAX_RUN_TICKERS = 10`(재서 정한다 — 시험에 실행 시간 단언은 두지 않고 HISTORY 에 잰 값을 적는다).
- `OrderExecutor` 를 만들지 않는다 · `place_order` 를 부르지 않는다(정적 시험).

시험(재생 · 임시 DB · 모의 모드): ① ★끝까지 민 가상 체결 = 그 하루의 분봉 백테스트 체결★(틀마다) ② 가동 전후 `live_fills` 행 수 동일 · `live_orders` 는 신호 수만큼 `SHADOW_LOGGED`
③ 비상 정지 → 다음 걸음에서 멈춤(`kill_switch`) ↔ 풀고 새로 가동하면 돈다 ④ 봉 빈틈 → `feed_gap` ↔ 이어진 날은 끝까지 ⑤ 남의 계좌 · 남의 시행 → 없는 것과 같은 답
⑥ 시행 없는 설정 거절 · 운영에서 합성 등급 거절 ⑦ 가동기를 새로 만들면(재시작) 가동 0 · 남은 줄은 `interrupted` ⑧ 모드를 바꾸면 멈춤 ⑨ 동시 가동 상한.

## 5. b4 — 문

`GET/POST /api/v1/broker-accounts/{id}/rule-runs` · `POST …/rule-runs/{run_id}/advance` · `POST …/rule-runs/{run_id}/stop` · `GET …/rule-runs/{run_id}`(가상 체결 포함) ·
`GET /api/v1/intraday/arm-requests` · `DELETE /api/v1/intraday/arm-requests/{id}`. 전부 로그인 · 본인 계좌(`_owned_or_404`) · 보호 등록부 · 접근 지도.
응답마다: 지금 모드 · 비상 정지 상태 · 관문 일곱의 상태(시행 줄의 결과 요약이 있으면 — 없으면 "판정 결과를 남기지 않은 실행"이라고 적는다 · ★막지 않는다★) · 출처 등급.

## 6. b5 — 캔버스 '가동 요청' 노드

- `intraday_load` 에 출력 포트 하나(`run` · 종류 `IntradayRun`) — 비교 노드가 받지 않는 종류.
- `intraday_arm_request`(단계 `act` · 쉬운 이름 '가동 요청' · `wants_actor`): `run` 은 쓰기 0(미리보기) · `save`('가동 요청 남기기')가 `rule_arm_requests` 에 한 줄. ★가동하지 않는다.★
- 운영 게이트에서 합성 등급이면 `save` 거절 · 모의 모드에서는 연습용 표식. AST 가드(주문 경로 import 금지) · AI 후보 표 · 고객 한 장 밖 · 캔버스 골든 갱신(의도한 변화).

## 7. b6 — 화면

- 내 계좌(계좌·주문 화면)에 절 **'규칙 가동'**: 받은 요청 목록(가동 · 지우기) → 가동할 때 날짜(적재된 날 가운데) · 지금 모드 · 비상 정지 · 관문 상태를 보이고 확인 → 가동 중인 것: 상태 · 마지막 봉 · 신호 수 · '다음 봉 30개' · '끝까지' · '정지'.
- 가상 체결에는 늘 **가상** 표식. 합성 분봉이면 절 맨 위에 적는다. 새 메뉴 · 새 화면 없음.
- E2E(실제 서버 · 손으로 만든 열흘): 캔버스에서 요청 → 내 계좌에서 가동 → 끝까지 → 가상 체결 2줄(09:02 매수 99주 @10,080 · 09:03 매도 99주 @10,100) = 분봉 백테스트의 그날 체결.

## 8. 하지 않는 것

모의투자 주문(`PAPER` 에서의 가동은 문이 거절한다 — W5d) · 장중 조회 공급 · 배경 스레드 · 자동 재개 · 자동 청산 · 여러 날에 걸친 가동 · 자유 조건식 · 실계좌.
관제 화면의 '오늘의 가동' 요약(실현손익 · 한도까지 남은 폭)은 W5c 다.
