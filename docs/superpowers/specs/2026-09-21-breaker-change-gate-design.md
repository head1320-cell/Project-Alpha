# AU · 업무 응답을 breaker 에서 뺄지 정한다 — ★결정을 산문이 아니라 문으로★

작성 2026-09-21 · 구현 `src/domain/breaker_change_gate.py` · 트립와이어
`tests/test_breaker_change_blocked.py` · 선례 `src/domain/distribution_gate.py`
+ `tests/test_distribution_blocked.py` · 선행 AR·AS·AT ·
기록 `docs/HISTORY.md` 의 AU 항목

## 1. 왜

AR 이 드러낸 안전 역전이 네 프로그램째 살아 있다: `_request` 가
`rt_cd != "0"` 에서도 `record_failure()` 를 부르므로 정상 업무 응답이 KIS
장애와 같은 카운터에 들어가고, 5회면 `auto_api` 가 킬스위치를 겨냥한다.
AR·AS·AT 이 차례로 **보이게** 했고, 이제 **고칠지 정할** 차례다.

## 2. ★실측 — 두 전제조건이 0, 하나는 구조적으로 불가능★

| 전제 | 실측 |
|---|---|
| `rt_cd` 표 | **0개** 항목. KIS 는 프록시 CONNECT 403 |
| 운영 관측 | 이 환경 DB 에 `live_audit_trail`·`live_orders` 테이블이 **없다** |
| mock 으로 쌓을 수 있나 | ★불가능★ — `MockKISClient` 에 `circuit_breaker` 가 **0건** |

★'아직' 이 아니라 구조적으로 불가능하다.★ 그러니 지금 빼는 것은 증거 없이
안전장치를 무디게 하는 일이고, 정직한 산출은 ★"아직 아니다" 라는 판정★이다.

## 3. ★그런데 질문 자체가 잘못 놓여 있었다★

"업무 응답을 빼자" 는 **종류 단위** 질문인데, `business` 는 의미가 아니라
**모양**(HTTP 200 + `rt_cd != "0"`)이다. 그 안에 장 종료(안전 문제 아님)와
KIS 내부 오류(진짜 장애)가 섞여 있을 수 있으므로 ★종류 통째로 빼면 그 안의
진짜 장애까지 같이 빠진다★. 판정 단위는 `(rt_cd, msg_cd)` 코드 하나하나다.

부수효과로 ★AS 의 빈 표가 **왜** 중요한지가 기계적으로 증명된다★ — 표가
비어 있으면 어느 코드도 문을 통과하지 못한다.

## 4. ★어휘가 모자란다는 것도 실측이다★

AR 의 책임 소재 축은 `provider`·`self`·`unknown` 셋인데 장 종료의 정직한
답은 **아무의 문제도 아니다** 이고 그런 값이 없다. `self` 로 우겨 넣는 것은
어휘를 비트는 일이라, 증거 파일에 **목적 전용 칸** `outage`
(`true`/`false`/`null`)를 둔다. ★`fault` 는 이 판정과 무관하고★, AR 의 축에
네 번째 값을 더하는 것은 별건이다.

## 5. 왜 산문이 아니라 문인가

HISTORY 에 *"breaker 가 무엇을 세는지 바꾸지 않았다"* 고 적은 것이 **네 번**
이다. ★산문은 내일 누군가 그냥 바꿔도 아무것도 깨지지 않는다.★ 저장소에는
이미 같은 문제의 답이 있다 — `distribution_gate` + `test_distribution_blocked`
가 *"인가 확인 전까지 유통 표면을 만들지 않는다"* 를 테스트로 박아 둔다.

## 6. 구성 요소

### 6.1 `src/domain/breaker_change_gate.py` ★NEW★ (순수)

조건 넷에 이름을 붙이고 **각각** 잰다. `distribution_gate` 의
`state`/`reason` 관용구를 그대로 쓰고, 미충족이면 **무엇이 빠졌는지** 말한다.

| 조건 | 무엇을 재나 |
|---|---|
| `meaning` | 뜻이 표에 있고 적용 등급(K2+) 이상 (`kis_rt_cd.meaning_of` 재사용) |
| `not_outage` | 표가 `outage: false` 라고 말한다 — ★`null` 도 `true` 도 막는다★ |
| `observed` | 브로커 출처에서 `MIN_OBSERVATIONS`(20)회 이상 |
| `real_source` | 그 관측의 실행 모드가 `live`/`paper` — ★모르는 모드는 합성으로 친다★ |

`gate_summary` 는 ★일부만 통과한 것은 통과가 아니다★ 로 잡고, ★빈 목록에
전칭을 주장하지 않는다★(파이썬에서 `all([])` 은 `True` 다 — AT 에서 같은
함정을 만났다).

### 6.2 `outage` 칸 · 수집기가 보존

`docs/specs/kis-rt-cd-evidence.json` 의 `fields` 에 `outage` 를 더하고
★`codes` 는 계속 비운다★. `collect_kis_rt_cd.CURATED_FIELDS` 에 추가해
수집기가 사람이 적은 값을 덮지 않게 한다(AS5 의 계약 그대로).

### 6.3 ★정직한 한계를 문이 스스로 말한다★

`observed` 는 AS4 의 원장으로 잰다. 그 원장은 `_request` 7개 호출부 중
**주문·취소 둘**만 본다(AT 실측) — 잔고·시세에서만 나오는 코드는 ★영원히 이
조건을 못 채운다★. 문은 그 사실을 사유에 적는다. 고치는 것은 별건이다.

### 6.4 표면 + 트립와이어

`GET /kill-switch/kis-codes` 에 `gate` 블록. 프런트는 **타입만**.

★트립와이어가 이 프로그램의 산출물★ — `COUNTED_BY_BREAKER` 에서 `business`
가 빠지면 `tests/test_breaker_change_blocked.py` 가 죽는다. 다섯 번째 산문이
아니라 **통과해야 하는 문**이 남는다.

## 7. ★검출기가 실제로 검출하는지도 잰다★

*"지금 없다"* 만 재면 검출기가 고장 나도 통과한다. 그래서
`test_distribution_blocked.py` 의 관용구를 따라 ⑴ 조건을 모두 갖춘 코드를
심으면 문이 **열리고** ⑵ 심은 것이 실제 파일로 새지 않았음을 함께 잰다.
이것이 없으면 `return blocked` 한 줄짜리 게이트가 모든 검사를 통과한다.

## 8. 오류 처리

| 상황 | 결과 |
|---|---|
| 표가 비었다 | 전부 blocked + `meaning` 미충족 사유 |
| `outage` 미상 | blocked — ★미상은 통과가 아니다★ |
| `outage: true` | blocked — ★세는 것이 이 코드의 목적이다★ |
| 관측 없음/모자람 | blocked + 원장의 한계를 함께 적는다 |
| 실행 모드 미상 | blocked — 실제라고 확인한 적 없는 것은 합성이다 |

## 9. ★이 설계가 하지 않는 것★

- **breaker 가 무엇을 세는지 바꾸지 않는다.** 업무 응답은 **여전히**
  카운트에 들어가고 **여전히 발동시킨다**. 문은 ★말할 뿐 막지 않는다★ —
  `_request` 에도 `COUNTED_BY_BREAKER` 에도 연결되지 않고, 그 사실을
  테스트가 지킨다(연결되면 표를 채우는 순간 아무도 승인하지 않은 동작
  변경이 조용히 일어난다).
- **임계값을 바꾸지 않는다.**
- **표를 채우지 않는다.** `outage` 값을 모델 지식으로 적지 않는다.
- **원장이 7개 호출부를 다 보게 만들지 않는다.** 한계를 사유로 말할 뿐이다.
- **AR 의 `fault` 축에 네 번째 값을 더하지 않는다.**
- **채점표 #12 를 올리지 않는다.** ★문을 만든 것은 통과한 것이 아니다.★
- **화면을 만들지 않는다.** 타입까지다.
