# AS · `rt_cd` 표를 채울 수 있게 만든다 — ★열쇠부터 잡는다★

작성 2026-09-21 · 구현 `src/domain/kis_rt_cd.py` ·
증거 `docs/specs/kis-rt-cd-evidence.json` · 수집기 `scripts/collect_kis_rt_cd.py`
· 선행 AR(`src/domain/kis_failure.py`) · 기록 `docs/HISTORY.md` 의 AS 항목

## 1. 왜

AR 이 KIS 호출 실패를 일곱 종류로 갈랐지만, 가장 많이 나오는 종류
(`business` = HTTP 200 + `rt_cd != "0"`)의 **뜻을 모른다**. 그래서 책임 소재가
`unknown` 이고, 장 종료·잔고 부족 같은 정상 업무 응답이 KIS 장애와 **같은
breaker 카운터**에 들어가는 안전 역전이 살아 있다. 연속 5회면 breaker 가
`OPEN` 이 되어 `get_balance` 까지 막히고, AQ 가 통로를 이었으므로 `auto_api` 가
"KIS API 연속 실패 5회" 라는 **틀린 진단**으로 킬스위치를 겨냥한다.

로드맵은 다음 프로그램을 "`rt_cd` 표를 확보한다" 로 지정했다.

## 2. ★실측이 지정을 뒤집었다★

### ① 열쇠가 아예 기록되지 않고 있었다

`msg_cd` 는 저장소 전체에서 **0건**이다 — 코드에도, 픽스처에도, 테스트에도
없고 **AR 이 쓴 문서에만** 있다. `_request` 는 `rt_cd` 와 `msg1` 만 읽고
응답의 나머지를 버린다. `rt_cd` 는 이 저장소에서 `!= "0"` 이분법으로만 쓰이는
거친 값이라 혼자서는 서로 다른 업무 응답을 가르지 못한다.

★표를 받아와도 join 할 것이 없다.★

### ② 이 환경은 KIS 에 닿지 못한다

프록시가 `apiportal.koreainvestment.com` 과 `openapi.koreainvestment.com` 에
**CONNECT 403**(정책 거부)을 돌려준다. 공식 문서를 받아올 수도, 실계좌·모의계좌
응답으로 확인할 수도 없다.

### 그래서 프로그램의 이름이 바뀐다

★확보한다 → **채울 수 있게** 만든다.★ 표를 얻는 것은 접근 권한이 있는 사람의
일이고, 로드맵의 "이 로드맵이 기대는 미상" 표에 이미 그렇게 적혀 있다.

## 3. 어떤 질문에 답하는가

CLAUDE.md §2 가 섞지 말라는 네 질문 중 **어느 것도 아니다.** 이 작업은 예측력도
경제적 가치도 전달 안정성도 재지 않는다. 재는 것은 ★운영 관측 가능성★ 하나다:
*"우리가 어떤 KIS 업무 코드를 얼마나 봤고, 그중 무엇의 뜻을 모르는가."*

증거 등급은 `E1`(픽스처)~`E2`(제공자 파생)이고, 주장의 종류는 `structural` 이다.
표가 채워지기 전까지 이 경로는 **아무 투자 판단도 바꾸지 않는다**.

## 4. ★정직성 핵심 — 관측은 뜻을 주지 않는다★

코드를 100번 본다고 그 뜻을 알게 되지 않는다. 그래서 등급을 하나로 두되
**관측 등급이 적용선 아래**에 있게 한다.

| 등급 | 뜻 | 누가 만드나 |
|---|---|---|
| `K0` | 증거 없음 — 추측. 이 파일에 쓰지 않는다 | (아무도) |
| `K1` | ★관측★ — 이 코드를 응답에서 봤다. **뜻은 모른다** | 수집기 |
| `K2` | KIS 공식 문서에 근거 | 사람 |
| `K3` | 문서 + 실계좌 응답 교차 확인 | 사람 |

`min_grade_to_apply: "K2"` — ★`K1` 은 절대 `fault` 를 정하지 못한다.★

한국어 `msg1` 문구 패턴 매칭은 **하지 않는다**. `"장 종료"` 를 매칭해 *"이건
업무 거절"* 이라고 단정하면 ★어휘로 거는★ 실수이고, 이 저장소가 확인한 적 없는
것을 주장하는 것이다(AR 이 같은 이유로 거부했다). AST 테스트가 이를 막는다.

## 5. 저장소의 선례를 그대로 잇는다

`src/data/source_registry.py` + `docs/specs/ecos-frequency-evidence.json` 이
**정확히 이 상황의 선례**다:

- 사실은 파이썬 레지스트리에, **그 사실의 증거**는 체크인된 JSON 에
  (`grade`·`evidence_source`·`probed_at`).
- `min_grade_to_apply` 미만이면 ★적용하지 않는다★.
- 그 증거 파일은 **지금 비어 있고** `why_empty` 가 이유를 적는다 —
  *"키가 없고 `ecos.bok.or.kr` 이 프록시 CONNECT 403"*. ★KIS 와 똑같다.★
- 채우는 것은 스크립트이고 **사람이 diff 를 검토해 커밋한다**.

그 밖에: `sector_labels.SECTOR_CODE_LABELS = {}`(추측 금지로 의도적인 빈 표) ·
`version_registry.MISSING_AXES`(부재의 레지스트리) ·
`macro_observation_store`(최초 관측 시각은 UPDATE 하지 않는다) ·
`audit_trail.daily_summary`·`order_tracker.state_distribution`(집계는 읽기
시점에).

## 6. 구성 요소

### 6.1 열쇠를 잡는다 (`kis_client` · `kis_failure` · `order_executor`)

- `_request` 가 `data.get("msg_cd")` 를 읽어 `KISCallError.msg_cd` 로 나른다.
  ★있다고 가정하지 않는다★ — 없으면 `None` 이고, `None` 은 "KIS 가 주지
  않는다" 가 아니라 **미상**이다(이 저장소는 응답 봉투를 확인한 적이 없다).
- `failure_label(..., msg_cd=None)` 이 그 칸을 싣는다.
- `KISClient.last_failure_msg_cd` 한 칸. ★새 카운터가 아니다.★
- `_fail_order` 가 감사 `context` 에 `execution_mode` 를 남긴다 —
  `live_audit_trail` 에 모드 칸이 없어서, 없으면 나중에 모의와 실계좌 관측이
  조용히 합쳐진다. ★DDL 변경 0줄.★
- ★예외 메시지 문구는 한 글자도 바꾸지 않는다★ —
  `tests/test_ingest_doctor.py` 가 `"토큰 발급 실패"` 부분문자열을 단언한다.

### 6.2 표의 자리 (`src/domain/kis_rt_cd.py`, 순수)

`code_key(rt_cd, msg_cd)`(열쇠는 둘이고, `msg_cd` 가 없으면 그 사실이 열쇠에
남는다) · `load_evidence()`(★없거나 깨져도 예외 없음★) · `meaning_of` ·
`fault_from_table`(★사유 없는 미상 금지★) · `enriched_label` ·
`fold_observations`(순수 — 이미 읽어 온 행을 접는다) · `gap_list` ·
`table_summary`(★`K1` 항목은 표의 크기가 아니다★).

`fold_observations` 는 `(rt_cd, msg_cd, execution_mode)` 별로 접는다 —
★모드를 키에 넣는다★. 모의와 실계좌 관측을 합치면 그 수치는 아무것도 뜻하지
않는다. 모드를 모르는 행은 버리지 않고 미상으로 남긴다.

### 6.3 본 것을 센다 — ★새 테이블 0개★

AR 이 실패마다 `context_json` 에 종류·`rt_cd` 를 남기기 시작했고 6.1 이
`msg_cd` 와 모드를 더했다. 그러니 **이미 쌓이고 있다** — 새 카운터를 만들면
같은 사실이 두 곳에 있게 되고, 둘이 어긋날 때 무엇이 진실인지 정하는 문제가
새로 생긴다.

`AuditTrail.kis_code_rows()` 가 SQL 만 하고, 접는 것도 판정도 도메인이 한다.
`GET /api/v1/live/kill-switch/kis-codes` 가 `observed`·`gaps`·`table` 을 낸다.
★표가 비어 있으면 `gaps` 가 곧 `observed` 다 — 그것이 지금의 진실이다.★

### 6.4 수집기 (`scripts/collect_kis_rt_cd.py`)

★ECOS 스크립트와 결정적으로 다른 점★ — ECOS 는 API 를 **프로브**해 증거를
만들지만, KIS 오류 코드는 일부러 일으킬 수 없다(장 종료를 만들 수도, 잔고를
비울 수도 없다). 그래서 이 수집기는 **이미 일어난 것을 수확한다**.

네 가지를 지킨다: ⑴ `--write` 없이는 쓰지 않는다 · ⑵ 사람이 적은 칸
(`meaning`·`fault`·`grade`·`evidence_source`·`probed_at`)을 덮지 않는다 ·
⑶ `first_seen` 을 UPDATE 하지 않는다 · ⑷ 0건이면 `skipped` 라고 말한다
(★"0건 성공" 은 "확인했더니 문제가 없었다" 로 읽힌다★).

★mock 에서는 영원히 빈손이다★ — `MockKISClient` 는 언제나 `rt_cd="0"` 을
돌려준다(실측). CLAUDE.md §6 의 *"mock 은 항상 흑자라 테스트를 통과한다"* 와
같은 모양이라, 리포트가 어느 모드에서 돌았는지 라벨한다.

### 6.5 표면

`enriched_label` 을 `api_failure_probe._last_failure` 가 부른다 —
★아무도 안 부르는 계약은 계약이 아니다★. 프런트는 **타입만**(화면 없음).

## 7. 오류 처리

| 상황 | 결과 |
|---|---|
| 증거 파일 없음·깨짐 | 빈 표 + 기본 적용선. ★예외를 던지지 않는다★ — 여기서 터지면 임포트 경로 전체가 죽는다 |
| 등급이 어휘 밖 | 적용하지 않는다 — ★어휘 밖의 값은 사실이 아니다★ |
| 책임 소재가 어휘 밖 | `unknown` + 사유 |
| 감사 로그를 못 읽음 | `[]`(저장소 관행) · 수집기는 `skipped` + 사유 |
| `context_json` 이 JSON 이 아님 | 그 행은 관측이 아니다 — 건너뛴다 |
| 관측 0건 | ★`skipped`★ — 성공이 아니다 |

## 8. 테스트

`tests/test_kis_code_key.py`(열쇠) · `tests/test_kis_rt_cd.py`(표) ·
`tests/test_kis_code_ledger.py`(집계·라우트) ·
`tests/test_collect_kis_rt_cd.py`(수집기) · `tests/test_kis_rt_cd_wiring.py`
(표면). 변이 배터리 a~l 로 각 가드가 특정 변이를 죽이는지 확인한다.

★오늘은 아무것도 바뀌지 않으므로 짝으로 잰다★ — 같은 항목을 `K2` 로 두면
표면이 책임 소재를 말하고, `K1` 로 낮추면 **다시 미상**이 된다. 그래야 공허한
분기가 아님이 증명된다.

## 9. ★이 설계가 하지 않는 것★

- **`rt_cd` 표를 확보하지 않는다.** 이 환경은 KIS 에 CONNECT 403 이다.
- **모델 지식으로 코드를 씨앗으로 넣지 않는다.** 확인할 수 없는 것을 저장소에
  적는 일이다.
- **`msg1` 을 해석하지 않는다.**
- **breaker 가 무엇을 세는지 바꾸지 않는다.** 표가 채워져도 세는 것은 그대로다
  — `COUNTED_BY_BREAKER` 는 **종류** 단위이고, 바꾸는 것은 실거래 호출 경로
  동작 변경이라 별도 승인 사항이다(CLAUDE.md §6).
- **`kis_failure.fault_of(kind)` 를 바꾸지 않는다.** AR 의 총함수 계약 그대로.
- **새 테이블·새 카운터를 만들지 않는다.**
- **재시도·백오프를 만들지 않는다.**
- **채점표 #12 를 올리지 않는다.** ★잴 준비는 잰 것이 아니다.★
- **화면을 만들지 않는다.**
