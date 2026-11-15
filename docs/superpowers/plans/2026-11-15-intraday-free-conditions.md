# 분봉 규칙의 자유 조건식 — 구현 계획 (묶음 F · 2026-11-15)

> 설계 [자유 조건식](../specs/2026-11-15-intraday-free-conditions-design.md) · 받은 결정 §11(캔버스까지 · 조건 줄 편집기 · 지표 보탬은 f4 · 상수 격자와 이름 칸은 뺌).
> 방식: 조각마다 빨강 먼저 → 짝 · 변이 → 게이트 → HISTORY → 커밋 · 푸시 → 보고. 하위 에이전트 없음. 중간 승인 없음(받은 결정).
> ★이 문서는 지금 f1(엔진 · 문)의 계획이다.★ f2(편집 화면) · f3(캔버스) · f4(지표 보탬)는 그 조각을 시작할 때 이 문서에 절을 더한다(설계 §10).
> ★시뮬레이터 · `expr.evaluate` · 지표 계산 · 체결 규칙 · 관문 · 주문 경로는 0줄★ — 더하는 것은 "나무를 직접 받는 길"과 이름표뿐이다.

## 0. 구현 전에 조사로 정한 것 (설계와 달라지는 점 포함)

1. **`custom` 은 `TEMPLATES` 에 넣지 않는다.** 틀은 일곱 그대로다(`rules.TEMPLATES` 를 도는 골든 · 걸음 엔진 시험이 그대로 선다). `rules.CUSTOM = "custom"` 을 `resolve` · `build` · `describe` 가 갈라 다룬다.
2. **하나의 꼴(정규화)** — `rules.resolve("custom", params)` 가 돌려주는 사전:
   - 열쇠는 `entry` · `entry_stop` · `exit` 가운데 있는 것만(값이 `None` 인 자리는 뺀다). 그 밖의 열쇠는 `unknown_param`.
   - 자리마다 먼저 `expr.validate` 를 지난다(문법 · 종류 · 나무마다의 상한 — 엔진의 사유 그대로). 그다음 다시 짓는다:
     상수는 `float` 로(`30` 과 `30.0` 은 같은 시행) · 지표는 `indicators.resolve` 가 채운 매개변수로 · 연산은 ★아는 열쇠만★(`op` · `args` · `held_before` 의 `bars` · `time_between` 의 `from` · `to`)으로.
     연산 마디에 그 밖의 열쇠가 있으면 조용히 버리지 않고 `unknown_key` 로 거절한다(검사기는 지금 그것을 보지 않는다 — 관측). `time_between` 은 `args: []` 를 적는다(마디의 꼴을 하나로).
   - 조건의 순서는 건드리지 않는다(설계 §4 — 다른 순서 = 다른 시행).
3. **상한**: 마디 수는 셋을 ★합쳐★ `expr.MAX_NODES`(64) · 깊이는 나무마다 `expr.MAX_DEPTH`(12). 합을 세려고 `expr.size(tree) → (마디 수, 깊이)` 를 더한다(검사 · 평가는 그대로).
   'M봉 동안'의 한도(1~240)는 지금 검사기 안의 숫자다 → `expr.HELD_BARS = (1, 240)` 로 이름을 붙여 문법 표가 같은 값을 읽게 한다(뜻 불변 — 경계 시험을 먼저 건다: 240 은 받고 241 은 거절).
4. **거절의 문장**: 문은 엔진의 사유 코드에 문장이 없으면 `bad_setting` 으로 뭉갠다(지금 틀에서는 날 수 없는 코드들이라 문장이 없었다). `custom` 에서는 그 코드들이 실제로 난다 →
   문장을 더한다: `no_entry` · `entry_not_a_condition` · `entry_stop_not_a_price` · `exit_not_a_condition` · `too_many_nodes` · `too_deep` · `not_a_node` · `bad_const` · `unknown_op` · `wrong_arity` · `wrong_kind` · `bad_bars` · `unknown_indicator` · `unknown_key`.
   `unknown_param` 의 문장은 지표의 매개변수에도 맞게 고친다("그 규칙 틀이나 지표에 없는 매개변수가 있습니다." — 시험 · E2E 에 고정돼 있지 않음을 확인했다). 거절에는 어느 자리인지(`slot`)를 싣는다.
5. **격자의 규칙 축 — 설계와 달라진다.** 설계 §7 은 "엔진의 사유(`unknown_param`)로 거절된다"고 적었다. 축의 이름이 매개변수 이름(`n` …)이면 그렇다.
   그러나 축의 이름이 자리(`entry` …)이고 값이 나무면 ★500 으로 깨진다★ — 격자가 겹친 값을 걷는 자리(`dict.fromkeys`)가 사전을 해시하지 못한다(변이 R4 로 관측 · 2026-11-15).
   → `custom` 에 규칙 축이 하나라도 오면 문이 먼저 사유와 함께 거절한다(새 사유 `grid_rule_axis_custom`). 포지션 축은 그대로다.
   ★바로잡음★: 이 문서의 첫 판은 "나무 전체를 갈아 끼우는 격자가 그대로 지나간다(관측)"고 적었다 — 코드를 읽고 한 추론을 관측이라고 적은 것이고 틀렸다.
6. **`describe()` 의 `custom` 항목**: `{"kind": "custom", "label": "직접 구성", "custom": true, "params": [], "needs_prev": null, …}` — 전일 값이 필요한지는 ★조건에 따라 다르다★(틀처럼 미리 말할 수 없다 → `null` · 실제 값은 `rules/expand` 의 답이 말한다). 틀 일곱에는 `"custom": false` 가 붙는다.
   편집기의 두 문장(시행 횟수 · 덥혀지지 않은 지표)은 이 항목의 `notes` 로 서버가 낸다.
7. **f1 에서는 아직 고를 수 없다.** 틀 목록에 `custom` 이 실리면 편집기가 없는 화면과 캔버스에 빈 선택지가 생긴다 →
   화면의 틀 고르기(`SetupForm`)와 캔버스 분봉 설정 노드의 매개변수 모형은 `custom: true` 를 ★거른다★(f2 · f3 에서 각각 걷는다 — 걷을 때 뒤집힐 시험을 지금 건다). 캔버스의 결과 노드 · 내 계좌의 이름표는 여덟 전부를 읽는다(문으로 돌린 `custom` 시행이 이미 있을 수 있다).
8. **규칙의 글(`rule_text`)**: `rules.rule_text(rule) → {"rule_text": 글 | None, "rule_text_reason": None | 사유}`. 시행 목록 · 결과 목록 · 가동 요청 · 가동 줄이 싣는다. 틀의 줄에도 싣는다(매개변수가 드러난다).
   지금의 문법으로 읽히지 않는 설정이면 글은 `None` 이고 사유가 붙는다(빈 글이나 종류 이름으로 때우지 않는다).
9. **`rules/expand` 의 답**: `{rule: {kind: "custom", params}, source: {kind, label}, text, nodes, depth, limits: {nodes, depth}, needs_prev, notes}`. 거절은 400 `{code, reason, detail, slot}`.
   포지션 · 비용은 받지 않는다(규칙만 본다). 틀이면 `rules.as_custom(rules.build(kind, params))` 를, `custom` 이면 검사한 하나의 꼴을 돌려준다 — 한 번 푼 것을 다시 풀어도 같다.
10. **이름표의 자리**: 지표의 이름표 · 단위는 등록부(`Indicator.label` · `.unit`), 매개변수의 이름표 · 단위는 `Range.label` · `.unit`, 연산의 이름표 · 기호는 `expr.OP_LABELS` · `OP_SYMBOLS`. 기본값이 `""` 라 기존 시험의 손으로 만든 지표는 그대로 선다 —
    등록부의 것은 ★전부 이름표가 있어야 하고 서로 달라야 한다★(시험). 단위는 `price · volume · minute · index · flag` 다섯.
11. **글의 문법(`rules.text_of`)** — 화면의 조건 줄과 같은 순서(좌변 · 연산 · 우변)로 적는다. 서로 다른 나무가 같은 글이 되지 않게 묶음을 전부 적는다:
    지표 `이동평균(20봉)` · 상수 `30` · 산술 `(A + B)` · 조건부 값 `(C 충족 시 X)` · 비교 `A > B`(기호) · 돌파 `A 상향 돌파 B` · 묶음 `A 그리고 B`(안쪽 묶음은 괄호) · `아님(C)` · `직전 3봉 동안(C)` · `시각 09:30~14:50`.
    자리 이름을 붙여 한 줄로 잇는다: `진입 조건: … · 미리 건 매수 가격: … · 청산 조건: …`.

## 1. 파일

| 파일 | 하는 일 |
|---|---|
| `src/engine/intraday/indicators.py` | `Range` · `Indicator` 에 `label` · `unit` · 등록부 21개의 이름표 · `UNITS` |
| `src/engine/intraday/expr.py` | `OP_LABELS` · `OP_SYMBOLS` · `HELD_BARS` · `size()` (검사 · 평가의 뜻 불변) |
| `src/engine/intraday/rules.py` | `CUSTOM` · `SLOTS` · `resolve/build` 의 `custom` · `as_custom` · `describe` 의 여덟째 · `grammar` · `text_of` · `notes_of` · `rule_text` |
| `src/api/intraday_routes.py` | 새 문 `POST /rules/expand` · `GET /templates` 의 `grammar` · 사유 문장 · 격자의 규칙 축 거절 · 목록 셋의 `rule_text` |
| `src/execution/rule_runner.py` | 가동 줄의 `rule_text`(읽기만 — 가동의 뜻 불변) |
| `src/api/allocation_graph_nodes_intraday.py` | 설정 노드는 `custom` 을 거른다(f3 전) · 결과 노드의 이름표는 여덟 전부 |
| `src/api/protected_routes.py` · `frontend/src/entities/session/accessMap.json` | 새 문 등록(로그인 전용) |
| `frontend/src/entities/intraday/types.ts` · `widgets/intraday/SetupForm.tsx` | `Template.custom` · `needs_prev: boolean \| null` · 틀 고르기에서 `custom` 거르기(f2 전) |
| `docs/specs/2026-11-11-ui-terminology.md` §3.12 | '직접 구성' · 자리 셋의 이름 |
| 새 `tests/test_intraday_custom_rules.py` · 새 `tests/test_intraday_custom_route.py` | 아래 §3 |
| 고치는 시험 | `test_intraday_rules.py`(목록이 여덟) · `test_intraday_simulate_route.py`(틀 목록) · `test_allocation_graph_intraday.py`(설정 노드는 일곱 · 짝) · `test_rule_runner.py`(직접 지은 시행의 재생) · `e2e/intraday.spec.ts`(틀 고르기에 '직접 구성' 없음 — f2 에서 뒤집는다) |

## 2. 계약

```python
# rules.py
CUSTOM = "custom"
SLOTS = (("entry", "bool", "진입 조건"), ("entry_stop", "number", "미리 건 매수 가격"), ("exit", "bool", "청산 조건"))
resolve("custom", params) -> dict            # 하나의 꼴 · 어긋나면 RuleError(code, detail, slot=자리)
build("custom", params) -> RuleSpec          # RuleSpec(**resolve(...))
as_custom(spec: RuleSpec) -> dict            # 틀이 만든 나무 → custom 의 하나의 꼴
describe() -> list[dict]                     # 여덟 · 항목마다 "custom": bool
grammar() -> dict                            # slots · indicators · ops · units · limits
text_of(spec: RuleSpec) -> str               # 한 줄
notes_of(spec: RuleSpec) -> list[str]        # 덥힘 주석 (+ 전일 값을 쓰면 전일 주석)
rule_text(rule: Any) -> dict                 # {"rule_text", "rule_text_reason"}
# expr.py
size(tree) -> tuple[int, int]                # (마디 수, 깊이)
```

`grammar()`:
- `slots`: `[{key, label, kind}]` + `entry_rule`(문장: 진입 조건과 미리 건 매수 가격 가운데 하나는 있어야 합니다).
- `indicators`: `[{name, label, unit, needs_prev, params: [{key, label, type: "int"|"float", min, max, default, unit}]}]` — 등록부의 순서.
- `ops`: `[{name, label, symbol | None, gives, args: [종류…], variadic: None | {kind, min, max}, extra: [{key, label, type, min?, max?, unit?}]}]`.
- `units`: `{price, volume, minute, index, flag}` → 이름표 · `limits`: `{nodes: 64, depth: 12}`.

## 3. 시험 (빨강 먼저)

**엔진 — `tests/test_intraday_custom_rules.py`**
1. ★틀 일곱 = 같은 나무의 `custom`★: 틀마다(고르는 칸의 값마다) `as_custom(build(kind))` 를 `custom` 으로 돌린 결과가 골든의 요약값과 같다(골든 시험의 하루 · 설정 둘을 그대로 쓴다 — 체결 · 사건 · 건너뜀 · 센 것이 바이트 단위로 같다).
2. ★무작위 나무에 앞보기 0★: 문법에서 뽑은 나무 300개(씨앗 고정)가 "봉 k 뒤를 잘라도 k 앞이 그대로". 뽑힌 나무가 연산 15 · 지표 21 을 전부 덮는지 센다 · 어디선가 참이 되는 나무의 수를 센다(공허하지 않게).
3. 모름은 참이 아니다: `아님(종가 > 이동평균(20))` 은 첫 19봉에 신호가 없다 ↔ 덥혀진 뒤에는 난다.
4. 하나의 꼴: 열쇠 순서 무관 · 기본값을 채운 것과 안 채운 것이 같다 · `30` = `30.0` ↔ 값이 다르면 다르다 · 조건 순서가 다르면 다르다 · 틀과 같은 나무여도 종류가 달라 다른 설정이다.
5. 거절과 사유(코드 · 자리): 모르는 열쇠 · 자리의 종류(셋) · `no_entry` · 합친 마디 65 ↔ 64 는 받는다 · 깊이 · 모르는 지표 · 범위 밖 매개변수 · 연산 마디의 모르는 열쇠 · 나무가 아닌 값.
6. 이름표: 등록부의 지표 · 매개변수 · 연산 전부에 이름표가 있고 서로 다르다 · 단위는 다섯 가운데 하나 · `grammar()` 의 범위 · 기본값이 등록부와 같다 · `describe()` 는 여덟(`custom` 만 `true`).
7. 글: 손으로 적은 글 셋과 일치(틀 둘 + 직접 지은 것 하나) · ★다른 나무는 다른 글★(무작위 나무 300개의 글이 전부 다르다) · 줄표(—) 없음.
8. `expr.size` 가 검사기의 세는 법과 같다(64 마디 나무 = 64) · `held_before` 240 은 받고 241 은 거절.

**문 — `tests/test_intraday_custom_route.py`**
1. `rules/expand`: 걸려 있다 · 로그인 전용(보호 표 · 접근 지도) · 로그인 없이 401.
2. 틀 → 나무(= `as_custom(build(...))`) · 글 · 마디 수 · 전일 값 필요(변동성 돌파는 참 · 시가 범위 돌파는 거짓) · 다시 풀어도 같다 · `custom` → 기본값을 채운 하나의 꼴.
3. ★쓰기 0★: 모든 표의 줄 수가 그대로 · 분봉을 읽지 않는다(읽는 함수가 불리면 실패) · 시행이 늘지 않는다 ↔ 짝: 같은 규칙을 `simulate` 하면 시행이 한 줄 는다.
4. 거절: 사유 코드 · 문장(`bad_setting` 으로 뭉개지 않는다) · 자리.
5. `simulate` · `validate` · `divergence` 가 `custom` 을 받는다: 손으로 만든 하루에서 `종가 > 10,050` → 비용 전 +1,980원(분봉 시뮬레이터 시험의 손 계산) · 틀로 돌린 것과 같은 일지 · 시행은 따로 센다.
6. 같은 나무(열쇠 순서 · 기본값 생략)는 같은 시행 ↔ 조건 순서가 다르면 새 시행.
7. 격자: 포지션 축은 된다 ↔ 규칙 축은 `grid_rule_axis_custom`(축 이름이 `entry` 여도).
8. `GET /templates`: 여덟째가 `custom` · `grammar` 의 지표 21 · 연산 15 · 상한.
9. 목록의 글: 시행 · 결과 · 가동 요청에 `rule_text` ↔ 읽히지 않는 설정은 `None` + 사유.
10. 가동(`test_rule_runner.py`): `custom` 시행을 재생한 가상 체결 = 그날의 백테스트 체결 · 가동 줄에 `rule_text`.
11. 캔버스(`test_allocation_graph_intraday.py`): 설정 노드의 틀은 일곱(`custom` 없음) ↔ 결과 노드는 `custom` 시행의 이름표 '직접 구성'을 읽는다.
12. 화면(E2E `intraday.spec.ts`): 틀 고르기에 '직접 구성'이 없다 ↔ '시가 범위 돌파'는 있다.

## 4. 변이 (가드마다 — 죽어야 한다)

엔진: 기본값 채우기 제거 · 상수의 `float` 제거 · 합친 상한 제거 · 연산 마디의 모르는 열쇠 통과 · 자리의 종류 검사 약화 · `no_entry` 제거 · `build` 가 자리 하나를 버림 · `as_custom` 이 자리 하나를 버림 ·
글이 매개변수를 빠뜨림 · 글이 안쪽 묶음의 괄호를 빠뜨림 · `describe` 의 `custom` 표시 뒤집기 · 문법 표에서 지표 하나 빠뜨림 · ★앞보기 변이★(돌파가 다음 봉을 봄 · 'M봉 동안'이 그 봉을 포함 · 이동평균이 한 봉 앞을 봄 — 무작위 나무 시험만으로 죽는지).
문: `expand` 가 시행을 남김 · `expand` 가 분봉 계획을 읽음 · `expand` 의 로그인 걷기 · 격자의 규칙 축 가드 제거 · 사유를 `bad_setting` 으로 뭉갬 · `rule_text` 를 상수로 · 못 읽은 글의 사유 제거 · 캔버스의 거르기 제거 · 화면의 거르기 제거.

## 5. 게이트 · 커밋

ruff · 새 기본 DB 의 전체 pytest(격리 worktree) · tsc + 다크 구역 점검 · eslint(경고 96 기준선) · 빌드 · 닿는 E2E(분봉 · 캔버스 분봉 · 가동) → HISTORY → 커밋(이름 지은 파일만) → 푸시 → CI 세 잡 → PR #5 본문 → 보고.
커밋 둘: ① 이 문서 + 설계 문서의 받은 결정(문서만) ② f1(엔진 · 문 · 시험 · 용어집 · HISTORY).

## 6. f1 이 하지 않는 것

편집 화면(f2) · 캔버스 설정 노드의 '직접 구성'(f3) · 새 지표(f4) · 글자 수식 파서 · 조건의 추천과 자동 탐색 · 규칙 상수의 격자 · 직접 지은 규칙의 이름 · 나눗셈 ·
시뮬레이터 · 체결 규칙 · 관문 · 주문 경로 · 가동의 멈춤 조건 · 기존 틀 일곱의 뜻 · 시행 열쇠를 짓는 법(`intraday_trials`).

## 7. 주장의 범위

`structural` + `synthetic_mechanism` — "직접 지은 조건이 틀과 같은 엔진으로 같은 규칙에 따라 돈다"(골든 일치 · 손 계산 · 성질 시험)까지다. 실제 분봉으로는 확인하지 못한다.
표현력이 넓어진 것은 규칙의 가치가 아니다. 이 조각이 답하는 물음은 ① 정보 표현력뿐이다.

---

## 8. f2 — 편집 화면 (백테스트 › 분봉 규칙의 '직접 구성' · 2026-11-15 · f2 를 시작하며 더한 절)

### 8.0 조사와 구현 중에 정한 것 (설계와 달라지는 점 포함)

1. **편집기의 자료 = 조건 나무 그 자체**(설계 §6.2 그대로). 편집 중의 빈 칸만 다르다 — 마디는 `null`, 고르지 않은 연산과 적지 않은 시각은 빈 글자, 상수와 봉 수는 `null`.
   ★출발값을 지어 넣지 않는다★ — 지표의 매개변수만 서버 문법 표의 `default` 로 채운다.
2. **화면의 검사는 빈 칸의 자리만 말한다**(`issuesOf` — 자리마다 몇 곳 · 묶음의 줄 수 · 시각 창 · 범위 · 마디 상한). 빈 칸이 없을 때에만 서버에 묻는다(`POST /rules/expand`).
   거절(400 · 422)과 실패(그 밖)를 가른다 — 거절은 실행을 잠그고, 실패는 잠그지 않는다(실행의 문이 다시 검사한다).
3. **'이 틀을 조건으로 풀기'와 '내 시행에서 불러오기'는 둘 다 `rules/expand` 를 지난다** — 편집기에 싣는 것은 서버가 낸 한 꼴이다(화면이 틀의 나무를 지어내지 않는다).
4. ★설계에 없던 것 — 하나 남은 묶음은 풀린다★(`removeAt`): 지워서 조건이 하나만 남으면 묶음이 그 조건이 된다. `append` 가 둘째 조건에서 묶는 것의 짝이다.
   풀지 않으면 조건 둘 가운데 하나를 지운 사용자가 "묶음에는 조건이 둘 이상" 사유로 실행이 잠긴다(하나짜리 묶음은 서버가 받지 않는다 — 엔진의 인자 수 규칙은 건드리지 않는다).
   직접 놓은 묶음이 비면(0줄) 그대로 둔다 — 채우거나 지우는 것은 사용자가 한다.
5. ★설계 §6.2 "그 봉 자신은 보지 않는다는 것을 칸이 말한다"★ → 칸의 말은 `직전 [M] 봉 동안 계속`이고, 그 뜻은 ★서버의 주석★이 말한다(`rules.notes_of` — 그 연산을 쓰는 규칙에만).
   화면이 엔진의 뜻을 따로 적어 두지 않게 하려는 것이다(한 곳). 서버 한 줄(`_HELD_NOTE` · `_uses_op`)을 이 조각에서 더한다.
6. **규칙의 글을 보이는 자리**: 편집기 아래(검사 결과) · 불러오기 목록 · ★내 계좌의 가동 요청 줄과 가동 줄 · 매매일지의 '백테스트와 견주기'★.
   이름표가 같은 '직접 구성'을 가르려면 그 글이 있어야 한다. 틀에도 같은 글을 보인다(틀의 이름표는 매개변수를 말하지 않는다). 캔버스(결과 판 · 고르기 목록)는 f3.
7. **격자**: 직접 구성에는 이름 붙은 규칙 매개변수가 없어 규칙 축 칸이 생기지 않는다(받은 결정 — 포지션 축만). 그렇게 적는 한 줄을 둔다.
8. '직전 M봉'의 범위(1~240)도 문법 표(`ops[].extra`)에서 읽는다 — 화면에 범위를 따로 적어 두지 않는다.
9. 수 칸(`NumInput`)은 ★치는 동안만★ 글자를 따로 든다 — 줄의 열쇠가 순번이라, 줄을 지워 자리가 당겨질 때 앞 줄에 치던 글자가 남으면 안 된다.
10. 시각 칸은 브라우저의 `type="time"` 이다(보이는 꼴은 브라우저의 지역 설정을 따르고 값은 `HHMM` 으로 싣는다).

### 8.1 파일

| 파일 | 일 |
|---|---|
| `frontend/src/features/intraday-rule-editor/tree.ts`(새) | 나무를 고치는 순수 함수 — 새 마디 · 길을 따라 고치기 · 지우기 · 더하기 · 세기 · 빈 칸 찾기 · 서버와 주고받는 꼴 |
| `frontend/src/features/intraday-rule-editor/RuleEditor.tsx`(새) · `index.ts`(새) | 조건 줄 편집기(자리 셋). 화면과 캔버스(f3)가 함께 쓴다 |
| `frontend/src/widgets/intraday/RuleSection.tsx`(새) | 규칙 절 — 틀 여덟 · 매개변수 칸 또는 편집기 · 검사 결과 · 틀에서 풀기 · 내 시행에서 불러오기 |
| `frontend/src/widgets/intraday/{form.ts, SetupForm.tsx, IntradayView.tsx}` | 폼에 `custom`(나무 셋) · 요청 짓기 · 검사 질의 · 편집기로 옮기기 |
| `frontend/src/entities/intraday/{types.ts, api.ts}` | 문법 표 · 나무 · 풀이의 형 · `expandRule` |
| `frontend/src/entities/broker-account/ruleRuns.ts` · `widgets/my-account/RuleArming.tsx` · `widgets/trade-journal/CompareSection.tsx` | 규칙의 글(가동 요청 줄 · 가동 줄 · 견주기) |
| `frontend/src/app/globals.css` | 새 클래스만(`.ire-*` · `.itd-check` · `.itd-rule-text` · `.itd-load*` · `.ma-arm-text` · `.dv-rule*`) — 기존 클래스 0개 변경 |
| `src/engine/intraday/rules.py` | `notes_of` 에 '직전 M봉 동안'의 주석 한 줄(§8.0-5) |
| `frontend/e2e/intraday-rule-tree-logic.spec.ts`(새) · `intraday-custom.spec.ts`(새) · `intraday.spec.ts` · `divergence.spec.ts` · `rule-arming.spec.ts` | 시험 |
| `tests/test_intraday_custom_rules.py` · `test_intraday_custom_route.py` | 주석의 시험(짝) |
| `docs/specs/2026-11-11-ui-terminology.md` §3.12 | 편집기의 낱말 |

### 8.2 계약 (화면)

- 틀 고르기에 여덟째 **'직접 구성'**. 고르면 매개변수 칸 대신 자리 셋(진입 조건 · 미리 건 매수 가격 · 청산 조건)이 ★비어서★ 뜬다. 틀로 갔다 돌아와도 지은 조건은 남는다.
- 한 줄 = `[수] [연산] [수]`. 수 = 지표(+ 매개변수 칸) · 상수 · 계산(앞의 값이 왼쪽 항이 된다) · 조건부 값. 줄 앞의 '아님' · '직전 M봉 동안 계속'은 그 줄(또는 묶음)을 감싼다(바깥이 앞).
- 조건 하나에 조건을 더하면 '모두 충족' 묶음이 된다(묶음의 종류는 화면에서 바꾼다). 지워서 하나만 남으면 묶음이 풀린다.
- 빈 칸이 있으면 실행 · 판정 단추가 잠기고 `자리: 비어 있는 칸이 N곳 있습니다.` 꼴로 말하며 그 칸에 표시한다(`aria-invalid`). 쓰지 않는 자리(미리 건 매수 가격 · 청산 조건)는 빈 칸이 아니다.
- 다 채우면 서버의 검사 결과: 규칙의 글(서버 문장 그대로) · `마디 n/64 · 겹침 깊이 d/12` · 주석(전일 값 · 직전 M봉) · 거절 사유(서버 문장 그대로).
- ★검사는 시행으로 기록되지 않는다★ — 조건을 짓고 고치는 동안 시행 목록이 그대로다. 실행은 기록한다(틀과 같은 나무여도 다른 시행이다).
- 서버로 가는 본문의 `rule` = `{kind: "custom", params: 화면에서 지은 나무}`(쓰지 않는 자리는 싣지 않는다).

### 8.3 시험 (빨강 먼저)

- 순수 규칙(브라우저 없이 · `intraday-rule-tree-logic.spec.ts`): 새 마디의 빈 칸 · 더하기와 묶기 · 고치기와 지우기(원본 불변) · 하나 남은 묶음 풀기(짝: 둘 이상 · 빈 묶음) · 빈 칸 찾기(자리별 수 · 묶음 · 범위 · 시각 · 같은 사유 한 번) · 마디 상한(짝: 딱 상한) · 서버와 주고받는 꼴.
- 화면(`intraday-custom.spec.ts` · ★실제 서버★ · 손으로 만든 열흘): 빈 화면과 잠금 · 빈 칸이 있는 동안 서버에 묻지 않는다 · 손으로 지은 `종가 상향 돌파 10050` = 비용 전 +19,800원(틀의 손 계산과 같은 체결) · 본문 = 나무 ·
  틀에서 출발(같은 숫자 · 다른 시행) · 검사 ≠ 시행(짝: 실행은 시행) · 묶음 · 아님 · 직전 M봉 · 시각 창 · 가격 식의 글 · 줄 지우기(자리가 당겨져도 값이 맞다 · 하나 남으면 풀린다) ·
  전일 값 주석(짝) · 범위 밖 매개변수 · 서버의 거절과 실패(가로챈 응답 — 짝) · 내 시행에서 불러오기(누르기 전에는 묻지 않는다 · 규칙만) · 매매일지 견주기의 글(짝: 다른 시행을 고르면 그 글) · 라이트/다크 AA · 문체 · 390px.
- 기존 스펙: 분봉(틀 여덟) · 견주기와 가동(규칙의 글).
- 서버: 주석은 그 연산을 쓰는 규칙에만(짝 · 깊이 묻혀도 · 어느 자리든) · 그 말이 사실인지(손으로 만든 봉 여섯).

### 8.4 변이

순수 규칙: 출발값 지어 넣기 넷 · 묶기와 풀기 · 지우기 · 진입 규칙 · 빈 칸 세기 · 범위(정수 · 하한 · 상한) · 시각(앞뒤 · 시 · 분) · 마디 수(상한 · 자리 합) · 주고받는 꼴 · 조사 · 원본 불변 · 계산의 왼쪽 항.
화면: 빈 칸이 있어도 묻기 · 거절인데 잠그지 않기 · 풀기가 틀에 머묾 / 나무를 싣지 않음 · 본문에 나무를 싣지 않음 · 화면의 검사 끄기 · 마디 수 뒤바꿈 · 글을 다른 값으로 · 불러오기가 미리 물음 / 목록을 닫지 않음 ·
격자 안내 제거 · 전일 값 안내가 늘 뜸 · 서버 주석 버림 · 쓰지 않는 자리를 빈 칸으로 표시 · 계산이 앞의 값을 버림 · 아님 풀기가 조건까지 지움 · 감싸기 단추 뒤바꿈 · 지우기가 안쪽만 비움 · 시각 변환 제거 · 낡은 글자 · 뿌리에서 더하기가 바꿔 끼움 · 가동 줄 / 요청 줄 / 견주기의 글 제거.

### 8.5 게이트 · 커밋

ruff · 새 기본 DB 의 전체 pytest(격리 worktree) · tsc + 다크 구역 점검 · eslint(경고 96 기준선) · 빌드 · 닿는 E2E(직접 구성 · 순수 규칙 · 분봉 · 견주기 · 가동 · 캔버스 분봉 · 매매일지) · 스크린샷 검수(라이트 · 다크 · 390px) → HISTORY → 커밋(이름 지은 파일만) → 푸시 → CI 세 잡 → PR #5 본문 → 보고.

### 8.6 f2 가 하지 않는 것

캔버스 설정 노드의 직접 구성 · 캔버스의 결과 판과 고르기 목록의 글(f3) · 새 지표(f4) · 끌어서 줄 순서 바꾸기 · 조건 복사와 붙여넣기 · 되돌리기 · 글자로 조건을 치는 입력 · 조건의 추천 · 직접 지은 규칙의 이름과 따로 두는 저장소 ·
규칙 상수의 격자 · 나무 안의 오류 위치(서버가 자리까지만 말한다) · 시뮬레이터 · 조건 평가 · 지표 계산 · 체결 규칙 · 관문 · 주문 경로.

### 8.7 주장의 범위

화면이 한 일은 "지은 나무를 그대로 서버에 보내고, 서버가 낸 글과 사유를 그대로 보인다"까지다(`structural`). 숫자의 뜻과 한계는 분봉 백테스트의 것 그대로다 — ★편집기가 생겼다고 증거가 강해지지 않는다.★
답한 물음은 ① 정보 표현력뿐이다. 조건을 자유롭게 고칠수록 시행 횟수가 빨리 늘고, 그 사실은 편집기 아래의 주석이 말한다.
