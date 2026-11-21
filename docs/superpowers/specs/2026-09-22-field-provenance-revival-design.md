# AW · 병합이 떨어뜨린 출처를 되살린다 — ★떨어진 것은 둘이었다★

작성 2026-09-22 · 구현 `src/engine/filter_ast.py` · 새 스토어
`src/data/base_fields_store.py` · 등급 규칙 `src/domain/signal_evidence.py` ·
안전장치 `tests/test_filter_ast_golden.py` · 앞 프로그램
[AV 스펙](2026-09-21-signal-provenance-grade-design.md) · 기록
`docs/HISTORY.md` 의 AW 항목

## 1. 무엇을 되살리는가

AV 가 신호 215개 중 **157개(73%)** 의 출처를 저장소가 말할 수 없다고 이름
붙였고, 원인을 한 줄로 지목했다 — `filter_ast` 의 세 병합 함수가 `FieldMeta`
를 만들 때 `FactorMeta.source` 를 떨어뜨린다. 이 프로그램이 그것을 되살린다.

## 2. ★실측이 AV 의 designation 을 뒤집었다★

되살리기 전에 `source` 가 **무엇을 담고 있는지** 먼저 쟀다.

| 스토어 | `source` 실측 분포 | 이것은 무엇인가 |
|---|---|---|
| `FUNDAMENTAL_FACTORS` | `'기본'` 29 · `'기관 표준'` 13 · `'DuPont'` 3 · `'Sloan (1996)'` 2 · `'Piotroski (2000)'` 1 … | **문헌·파생 근거** |
| `EXTENDED_FACTORS` | `'DART'` 26 · `'DART 파생'` 14 · `'KIS'` 4 | **데이터 제공자** |
| `PRICE_FACTORS` | `'기본'` 16 · `'KIS 투자자동향'` 6 · `'Wilder'` 1 · `'DART 지분공시'` 1 | ★한 칸에 둘이 섞여 있다★ |

★AV 는 이 칸을 *"문헌 인용"* 이라고 적었고, 그것은 틀렸다★ — 한 스토어에서만
맞는 말이다. 그러니 *"되살리면 등급이 붙는다"* 는 designation 도 틀렸다.
`'Piotroski (2000)'` 은 값이 **어디서 왔는지**를 말하지 않는다.

**어제 제가 쓴 문장을 오늘 실측이 뒤집었다** — 이 저장소에서 여덟 번째다.

## 3. ★그래서 되살릴 것이 둘로 갈렸다★

| 축 | 칸 이름 | 무엇 | 등급이 읽나 |
|---|---|---|---|
| **데이터 출처** | `origin` | 어느 스토어에서 병합됐나 | ✔ 읽는다 |
| **선언된 출처** | `source_declared` | 스토어가 `source` 에 적어 둔 **원문 그대로** | ✘ 안 읽는다 |

`origin` 은 ★해석이 필요 없는 구조적 사실★이다 — 병합 자리 자체가 알고 있고
기록만 안 했다. 그것이 `signal_evidence` 가 필요로 하는 데이터 출처다.

`source_declared` 는 ★해석하지 않고 원문 그대로 나른다★. 계획서의 이름
`literature` 를 쓰지 않은 이유가 §2 다 — `'DART'` 를 문헌 인용이라 부르게
된다. **문자열을 패턴으로 갈라 분류하는 것은 AR 이 `msg1` 에서 거부한 바로
그 일**이라 하지 않는다. `test_nothing_interprets_the_declared_source` 가
AST 로 `"DART"`·`"기본"` 과의 비교를 금지해 이 결정을 못 박는다.

## 4. 리터럴 14개 — 사용자 결정

실측: `FIELD_BY_ID` 157개 중 `fundamentals_store` 64 · `price_factors_store` 31
· `extended_factors_store` 50 · ★어느 스토어에도 없는 맨손 리터럴 14개★.

★경계 — 제가 우려를 말했고 사용자가 구조 이동을 택했다★. CLAUDE.md §6 은
스크리너 3-레이어와 `filter_ast` 를 리팩터링 대상이 아니라고 못 박는다.
그래서 **관측 가능한 것이 하나도 변하지 않았음을 먼저 증명하고** 옮겼다.

`src/data/base_fields_store.py` ★신규★ — `BaseFieldMeta`(일곱 칸, ★`source`
칸 없음★) + `BASE_FIELDS` 14개 + 파생된 `BASE_FIELD_BY_ID`.
`_register_base_fields()` 가 ★맨 먼저★ 돌아 등록 순서를 보존한다.

`source` 칸을 일부러 두지 않았다 — ★있는 척하면 빈 칸이 "근거가 없다" 가
아니라 "아직 안 적었다" 로 읽힌다★. 이 14개의 근거는 어디서도 확인하지
못했고, **적는 것이 곧 지어내기다.**

## 5. ★안전장치 — 골든 스냅샷을 먼저 만들었다★

`tests/test_filter_ast_golden.py` ★신규★ — 아무것도 건드리기 전에 현재
상태를 **기계로 떠내 체크인된 상수로 박았다**(현재 상태에서 뽑아 대조하면
언제나 통과하므로 증거가 아니다).

- 157개 id 와 **등록 순서**
- 각 필드의 기존 **일곱 속성값 전부**
- `fields_catalog()` 의 카테고리 구성과 멤버
- ★`len(GOLDEN) > 100`★ — 빈 스냅샷은 전칭의 근거가 아니다

★리터럴 14개를 옮긴 뒤에도 이 파일이 **한 줄도 안 고치고** 통과한다★ —
그것이 "구조를 바꾸지 않았다" 의 증명이다.

**실측한 파괴 위험 둘**

| 위험 | 실측 | 대응 |
|---|---|---|
| 위치인자 생성 | `FieldMeta(...)` **17곳** | 새 칸은 ★기본값 `None`, 맨 뒤★ |
| 통째 직렬화 | `fields_catalog()` 가 `asdict(f)` | 키가 **늘기만** 한다 — `test_the_api_catalog_lost_no_key` |

## 6. 등급 규칙이 달라진 것

`signal_grade` 가 `origin` 을 읽는다. ★그런데 여기서 한 번 더 틀릴 뻔했다★ —
처음엔 기존 `BACKING_PRICE` 를 재사용했고, 그 결과 재무 필드가
*"가격이 MockKISClient 에서 옵니다"* 라고 **거짓을 말했다**. 별도의
`BACKING_STORE` 와 전용 사유로 갈랐고
`test_a_store_backed_reason_does_not_claim_it_is_price` 가 그것을 지킨다.

AV 의 사유 문구(*"병합이 출처를 버립니다"*)는 ★이제 거짓이므로 고쳤다★ —
`test_the_stale_merge_reason_is_gone` 이 되살아나지 못하게 막는다.

## 7. 어떤 질문에 답하는가

CLAUDE.md 2절의 네 질문 중 **어느 것도 아니다**. 재는 것은 ★이 값이 어디서
왔는가★ 하나다. 증거 등급 `E1`(픽스처), 주장의 종류 `structural`.
어떤 투자 판단도 바꾸지 않는다.

## 8. ★이 설계가 하지 않는 것★

- **스크리너 3-레이어의 동작을 바꾸지 않는다.** 유동성 게이트·필터 kind·
  후처리 analyzer·`validate()` bypass 튜플 그대로. 리터럴 이동은 ★같은 필드가
  다른 파일에서 오는 것★일 뿐이고 골든 스냅샷이 그것을 증명한다.
- **`source_declared` 를 해석하지 않는다.** 분류도 정규화도 하지 않는다.
- **`source_declared` 를 등급에 쓰지 않는다.** 다른 축이다.
- **근거를 지어내지 않는다.** 스토어에 없으면 `None`, 기본 필드 14개는 비운다.
- **세 스토어의 `source` 값을 한 글자도 바꾸지 않는다.**
- **새 척도를 만들지 않는다.** AV 의 `PROV_*` 그대로.
- **미상을 0으로 만들지 않는다.** 14개는 여전히 미상이고 그것이 정직이다.
- **화면을 만들지 않는다. 채점표를 올리지 않는다.**
