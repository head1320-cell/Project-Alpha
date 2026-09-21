# AV · 신호마다 출처 등급을 파생한다 — ★같은 글자, 다른 축★

작성 2026-09-21 · 구현 `src/domain/signal_evidence.py` · 카탈로그
`src/domain/signal_definition.py` · 표면 `src/api/signal_routes.py` ·
같은 모양의 선례 `src/engine/research_panel.evidence_grade` ·
기록 `docs/HISTORY.md` 의 AV 항목

## 1. 왜 이 축인가

지난 여섯 프로그램(AP~AU)이 모두 실거래·킬스위치 축이었고, AU 가 ★그 축은
코드로 더 갈 수 없다★고 판정했다(KIS 두 호스트 CONNECT 403). 실측하니
**데이터 제공자 다섯(ECOS·FRED·DART·KRX·NAVER)도 전부 프록시 차단**이다.

그래서 다음 프로그램은 픽스처·체크인된 레지스트리만으로 도는 **순수 로직**
이어야 했고, 사용자가 축 ③ **설명가능성**을 골랐다 — CLAUDE.md 의 세 번째
축이자 ★외부 접근이 전혀 필요 없는★ 유일한 축이다.

## 2. ★실측 ① — 선언만 되고 아무도 안 쓰는 필드★

`signal_definition.SignalDefinition.evidence_grade` 는 저장소 전체에서
**대입 0건**이었다. ★같은 dataclass 의 `availability`·`unavailable_reason` 은
채워진다 — 셋 중 그 하나만 빠졌다.★ `GET /signals` 는 그 칸을 이미 내보내고
있었으니, 소비자는 지금까지 언제나 `null` 을 받았다.

갭 분석 §1 이 지목한 균열이고, 그것을 닫으려 만든 모듈에서 아직 안 닫혔다.

## 3. ★실측 ② — 같은 글자가 두 척도다★

| 어디 | 척도 | `E2` 의 뜻 |
|---|---|---|
| CLAUDE.md 2절 | **출처** | 제공자 파생 |
| `source_registry.EVIDENCE_GRADES` | **확신도** | 메타 API 응답에서 관측 |
| `research_panel.GRADE_E0/E3/E4` | 출처 | (CLAUDE.md 와 같음) |

★그리고 빈 필드의 주석은 확신도 쪽을 가리키고 있었다.★ CLAUDE.md 가
`capability.py` 의 `L0~L3` 에 대해 *"방향이 정반대니 절대 섞지 마세요"* 라고
적어 둔 바로 그 위험이 한 번 더 있었다.

**해결** — 신호에는 출처 척도를 쓰고 상수 이름을 `PROV_*` 로 달리한다.
`source_registry` 의 값은 **하나도 바꾸지 않고** 그것이 확신도 척도임을
docstring 에 명시한다(그 척도를 쓰는 ECOS 경로가 이미 있다).
★`signal_evidence` 가 `source_registry` 를 임포트하지 않는지 AST 로 건다★ —
docstring 이 그것을 *설명*하는 것은 의존이 아니므로 원문 grep 은 쓰지 않는다
(AU 에서 원문 grep 이 설명까지 잡은 적이 있다).

## 4. ★실측 ③ — 무엇을 말할 수 있고 무엇을 말할 수 없나★

신호 215개를 실제로 모아 본 결과:

| 종류 | 개수 | 출처를 말할 수 있나 |
|---|---|---|
| `strategy_token` | 8 | ✔ `BASE_TOKENS` 가 전부 가격·거래량(실측) |
| `alpha_expr` (`price`) | 10 | ✔ `alpha_lab.FIELDS` 가 그룹으로 가른다 |
| `alpha_expr` (`fund`) | 7 | ✘ 재무 적재 상태를 순수 규칙이 모른다 |
| `timing_rule` | 33 | ✘ 개정 정책은 아는데 **출처**는 안 실어 나른다 |
| `screener_field` | 157 | ✘ ★병합이 출처를 버린다★ |

★마지막 줄이 이 프로그램의 발견이다★ — `filter_ast._register_fundamental_fields`
가 `FieldMeta` 를 만들 때 `FactorMeta.source`(문헌 인용, 예: `"Novy-Marx
(2013)"`)와 `description` 을 **떨어뜨린다**. `FieldMeta` 에는 출처 칸 자체가
없다. 기록이 없는 것이 아니라 **옮기다 잃어버린 것**이고, 그래서 157개(73%)의
출처를 저장소가 말할 수 없다.

## 5. 어떤 질문에 답하는가

CLAUDE.md 2절의 네 질문 중 **어느 것도 아니다** — 예측력도 경제적 가치도
전달 안정성도 재지 않는다. 재는 것은 ★이 값이 어디서 왔는가★ 하나다.

증거 등급은 `E1`(픽스처)이고 주장의 종류는 `structural` 이다. 이 경로는
어떤 투자 판단도 바꾸지 않는다.

## 6. 구성 요소

### 6.1 `src/domain/signal_evidence.py` ★NEW★ (순수)

`PROV_E0~E4` + `PROVENANCE_GRADES` · `KNOWN_BACKING`(★실측으로 확인한 것만★) ·
`signal_grade(signal)` → `{signal_id, grade, reason, basis, note}` ·
`grade_catalog(catalog)` → 분포와 **빈틈 목록**.

- `basis` 는 ★무엇을 보고 그렇게 정했는지★를 남긴다. 등급만 내면 다음 사람이
  그 등급을 검증할 수 없다.
- ★`KNOWN_BACKING` 에 없으면 미상★ — 새 어댑터나 새 그룹이 생겨도 조용히
  통과시키지 않는다.
- ★미상을 `E0`(합성)으로 접지 않는다★ — `E0` 은 *"합성이라고 안다"* 는
  주장이고, 미상은 아무 주장도 아니다.
- `complete` 는 `n_graded > 0 and not ungraded` — ★빈 카탈로그에 전칭을
  주장하지 않는다★(파이썬에서 `all([])` 은 `True` 다; AT 에서 같은 함정).

### 6.2 mock 게이트가 판정을 움직인다

가격에 뒷받침되는 신호는 mock 게이트가 열려 있으면 `E0`(MockKISClient 가
값을 지어낸다), 닫혀 있으면 `E2`(제공자 파생)다. ★실데이터 모드에서 적재를
확인하지는 않는다★ — 순수 규칙은 저장 상태를 알 수 없고, 아는 척하면 그것이
곧 지어내기다. 그 한계를 사유가 적는다.

### 6.3 표면

`collect_signals()` 가 규칙을 불러 `evidence_grade` 와 새 칸
`evidence_grade_reason` 을 채운다(★어댑터가 아니라 규칙이 붙인다★ — 다섯
어댑터가 각자 적으면 다섯 벌이 되고 한쪽만 고쳐도 안 깨진다).
`GET /signals` 가 둘을 내고 `evidence` 롤업으로 빈틈 목록을 낸다.
★롤업은 `kind` 필터와 무관하게 전체를 센다★ — 걸러서 세면 빈틈이 줄어 보인다.

**프런트는 0줄이다** — 실측: `frontend/src/` 어디에서도 `/signals` 를 부르지
않는다. ★쓰지 않는 타입을 만드는 것은 이 저장소가 경계하는 바로 그 패턴★이다.

## 7. 오류 처리

| 상황 | 결과 |
|---|---|
| 종류·카테고리가 표에 없음 | 미상 + *"조용히 통과시키지 않는다"* 사유 |
| `screener_field` | 미상 + ★병합이 출처를 버린다★ 사유 |
| `timing_rule` | 미상 + ★개정 정책 ⟂ 출처★ 사유 |
| 어댑터가 죽음 | 기존 계약 그대로 `unavailable_sources` 에 사유 |
| 신호 0개 | `complete: False` — 빈 것은 전칭의 근거가 아니다 |

## 8. ★이 설계가 하지 않는 것★

- **다섯 어댑터를 고치지 않는다.** 지금 실어 나르는 것으로만 파생한다 —
  ★모르는 것을 알게 만들지 않는다★. 대신 규칙이 그 별건을 **이름으로**
  가리킨다(`filter_ast` 의 병합).
- **`source_registry.EVIDENCE_GRADES` 의 값을 바꾸지 않는다.**
- **신호의 뜻·유용성을 말하지 않는다.**
- **`availability` 축과 섞지 않는다.** 쓸 수 있는가와 어디서 왔는가는 다르다.
- **실데이터 모드의 적재를 확인하지 않는다.**
- **새 척도를 만들지 않는다.**
- **화면을 만들지 않는다.** 프런트는 0줄이다.
- **채점표를 올리지 않는다.** ★등급을 붙인 것이 등급이 옳다는 뜻은 아니고★,
  13개 기준 중 신호 출처에 맞는 행이 애초에 없다(그 사실을 HISTORY 에 적는다).
