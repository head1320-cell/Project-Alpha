# AX · `timing_rule` 이 출처를 싣는다 — ★인용문이 아니라 로더가 안다★

작성 2026-09-22 · 선언 `src/engine/timing_factor_meta.py` · 트립와이어
`tests/test_timing_origin.py` · 등급 `src/domain/signal_evidence.py` ·
앞 프로그램 [AW](2026-09-22-field-provenance-revival-design.md) ·
기록 `docs/HISTORY.md` 의 AX 항목

## 1. 왜 이것인가

AW 이 `screener_field` 157개를 닫아 등급을 18개(8%) → 161개(75%)로 올렸고,
★남은 미상 54개의 가장 큰 덩어리가 `timing_rule` 33개★였다.

AW 은 지정하면서 ★"이 지정을 믿지 말 것 — 어댑터가 **알면서 안 싣는가**,
**애초에 모르는가**를 재기 전에는 시작하지 말라. 후자면 이 프로그램은 하지
않는 것이 맞다"★ 고 적었다. **쟀고, 전자였다.**

## 2. ★실측 ① — 구조적 사실이 존재한다★

| 경로 | 개수 | 로더 |
|---|---|---|
| `timing_factors.evaluate()` | 24 | `src.data.etf_prices` — 직접, 또는 `tactical_allocations` 경유(그 모듈이 최상위에서 임포트) |
| `timing_rules_v2.read_factor()` | 5 | `src.data.pit_macro` (FRED/ALFRED/ECOS) |
| 평가 함수 없음 | 4 | ★없음★ — 스스로 `availability: "unavailable"` 이라고 광고 중 |

어느 로더를 부르는가는 ★해석이 필요 없는 구조적 사실★이다. AW 의 `origin`
과 같은 모양이고, 문자열도 같은 규칙(**스토어 모듈 이름**)을 따른다.

## 3. ★실측 ② — `provenance` 는 AW 의 `source` 와 똑같이 섞여 있다★

    데이터 제공자   5   'FRED/ALFRED (NFCI)'
    ETF 대용물      3   'ETF proxy (KODEX 229200 / 069500)'
    문헌 근거       7   'Keller & Keuning (VAA/DAA)'
    ★출처가 아님   17   'generic (realized volatility)'   ← 기법의 종류다
    명시적 없음     4   'spec §6.1 (no source)'

★유혹을 미리 이름 붙인다★ — `timing_factor_meta.classify()` 가 **이미** 이
문자열을 패턴 매칭해 `provenance_class` 를 만든다. 그러니 *"origin 도 여기서
뽑으면 되지 않나"* 가 자연스럽다. **안 된다**: `provenance_class` 는 *"누가
공개했나"* 라서 인용문에 적혀 있지만, `origin` 은 *"값이 어디서 오는가"* 이고
★17개가 아무것도 말하지 않는다★. 이 사실을 테스트가 못 박는다
(`test_the_origin_is_not_derivable_from_the_provenance_text`).

## 4. ★실측 ③ — 제가 세운 경보 셋이 전부 틀렸다★

`evaluate()` 가 모르는 9개를 "공허한 분기"(카탈로그가 광고하는데 평가기가
모름)로 의심했다. 재 보니:

- 4개는 `requires_as_of` 라 `read_factor` 가 **전용 리더**로 보낸다
- `indicator` 는 as_of 가 없으면 ★사유와 함께★ unavailable 이고, 그 이유가
  코드 주석에 적혀 있다(플래그를 붙이면 UI 가 "추가 불가"로 막는다)
- 나머지 4개는 스스로 `unavailable` 이라고 광고한다

★찾으러 간 결함이 없었다.★ 그것도 측정 결과이므로 기록한다 —
**이 부분에서 저장소는 이미 제 규율을 지키고 있었다.**

## 5. ★실측 ④ — AW 의 함정이 여기 그대로 있다★

- `etf_prices` 는 `load_ohlcv_unified(DB→KIS→mock)` 를 **재사용**한다
  → mock 게이트가 지배한다 → AW 의 `BACKING_STORE` 사유가 **그대로 참**이다
- `pit_macro` 는 **`FRED_API_KEY`** 에 의존하고 ★mock 게이트와 무관★하다
  → 기존 규칙을 그대로 쓰면 *"mock 게이트가 열려 있어 합성입니다"* 라는
  **거짓 사유**가 붙는다. AW 에서 `BACKING_PRICE` 를 재사용했다가 재무
  필드에 *"가격이 mock 에서 옵니다"* 를 붙인 것과 **똑같은 모양**이다

## 6. 구성 요소

### 6.1 선언 — `timing_factor_meta` 에 9줄

`enrich()` 가 이미 카탈로그 항목에 메타를 덧입히고, `_SOURCE_TIMING` 이
★"기관 시계열만 적고 나머지는 가격 파생 기본값"★ 이라는 **정확히 같은
패턴**을 쓴다. 그 옆에 `_ORIGIN_OVERRIDES`(5줄)를 두고 기본값을
`ORIGIN_ETF_PRICES` 로 한다. 소스 없는 4개는 `UNAVAILABLE_FACTORS` 가
`origin: None` 을 스스로 들고 온다 — ★두 군데서 같은 사실을 관리하지 않는다★.

`CATALOG` 33항목도 `evaluate()`·`read_factor()` 의 분기도 **한 줄도 안
고친다**. 이 프로그램은 **관측을 더하는 것**이고 평가 동작은 그대로다.

### 6.2 ★트립와이어 — 선언이 참인지 코드에서 확인한다★

`tests/test_timing_origin.py`. **선언만 있고 검증이 없으면 그것은 증거가
아니라 주장이다**(AS 의 증거파일+수집기, AU 의 문+트립와이어와 같은 꼴).

AST 로 **모듈 내 1홉 + 모듈 간 1홉**을 따라간다 — 실측으로 확인된 경로만:
`target_vol_size` 는 스스로 임포트하지 않고 `realized_vol` 을 부르고,
`_score_13612` 는 `tactical_allocations` 에 있으며 그 모듈이 최상위에서
`etf_prices` 를 임포트한다.

★작성 중 이 파일이 스스로 한 번 샜다★ — 처음엔 문자열 리터럴만 찾았고,
`read_factor` 가 `CURVE_SLOPE_FACTOR_ID` 같은 **모듈 상수**로 비교하는 네
팩터를 통째로 놓쳤다. 이름을 값으로 푸는 `_str_constants` 를 더해 고쳤다.
**어휘로 걸면 이렇게 샌다** — AR 이 `msg1` 에서, AU 가 원문 grep 에서 만난
것과 같은 종류다.

### 6.3 등급 — ★두 로더가 다른 것에 지배된다★

| origin | 뒷받침 | 무엇이 가르나 | 결과 |
|---|---|---|---|
| `etf_prices` | `BACKING_STORE`(기존) | **mock 게이트** | 열림 `E0` · 닫힘 `E2` |
| `pit_macro` | ★`BACKING_VINTAGE`(신규)★ | **`FRED_API_KEY`** | 없음 → ★미상 + 사유★ · 있음 → `E2` |
| `None` | 없음 | — | 미상 + *"평가 함수가 아예 없다"* |

★`E4`(시점 고정)로 올리지 않는다★ — 빈티지 리더를 **지나는 것**과 빈티지가
실제로 **고정됐음을 확인한 것**은 다르고, 순수 규칙은 후자를 모른다. 사유가
그 이유를 적는다.

`FRED_API_KEY` 를 읽는 것은 `mock_allowed()` 를 읽는 것과 **같은 종류의
관측**이다 — 환경변수이지 네트워크 호출이 아니다. 그리고 ★짝★이 된다:
키를 넣으면 빈틈이 실제로 줄어드는 것을 테스트가 증명한다(항상-거부 배제).

### 6.4 어댑터

`_timing_rules()` 에 `origin=item.get("origin")` 한 줄. ★`provenance` 는
싣지 않는다★ — AW 이 `source_declared` 에 대해 세운 경계와 같다(두 축이
만나는 지점을 늘리지 않는다). `provenance` 는 이미 타이밍 카탈로그 API 로
나간다.

## 7. 실측 결과

| | AW 이후 | AX 이후 |
|---|---|---|
| 등급이 붙은 신호 | 161 (75%) | ★**185 (86%)**★ |
| 미상 | 54 | ★**30**★ |

미상 30개의 **네 묶음이 서로 다른 사유**를 단다: 기본 필드 14 ·
`alpha_expr`(fund) 7 · `pit_macro` 키 없음 5 · 소스 없음 4.
★"키가 없다" 와 "평가 함수가 아예 없다" 는 처방이 정반대라 다르게 말한다.★

## 8. 어떤 질문에 답하는가

CLAUDE.md 2절의 네 질문 중 **어느 것도 아니다**. 재는 것은 ★이 값이 어디서
오는가★ 하나다. 증거 등급 `E1`(픽스처), 주장의 종류 `structural`.
어떤 투자 판단도 바꾸지 않는다.

## 9. ★이 설계가 하지 않는 것★

- **평가 동작을 바꾸지 않는다.** `evaluate()`·`read_factor()`·`CATALOG` 그대로.
- **`provenance` 를 해석하지 않는다.** `classify()` 가 만드는
  `provenance_class` 는 **다른 축**이고 값도 규칙도 손대지 않았다.
- **`availability` 로 `origin` 을 추론하지 않는다.** 쓸 수 있는가 ⟂ 어디서 오나.
  AST 테스트가 `enrich()` 안에서 그 참조를 금지한다.
- **소스 없는 4개에 출처를 적지 않는다.** 적는 것이 곧 지어내기다.
- **`pit_macro` 를 `E4` 로 올리지 않는다.**
- **적재·응답을 확인하지 않는다.** 키가 있다는 것은 읽혔다는 것이 아니고,
  그 한계를 사유가 적는다.
- **미상을 0 으로 만들지 않는다.** 키를 넣어도 25개가 남는다.
- **새 척도를 만들지 않는다.** AV 의 `PROV_*`, AW 의 origin 어휘 그대로.
- **화면을 만들지 않는다. 채점표를 올리지 않는다.**
