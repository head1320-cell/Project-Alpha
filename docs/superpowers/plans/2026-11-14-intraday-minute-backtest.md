# 분봉 백테스트(W4) — 구현 계획 (2026-11-14)

> 설계: [`../specs/2026-11-14-intraday-minute-simulator-design.md`](../specs/2026-11-14-intraday-minute-simulator-design.md)(승인됨 — W4a~W4d 전체).
> 실행: 이 세션에서 순서대로(하위 에이전트 없음). 과제마다 ★시험 먼저(빨강 확인) → 최소 구현 → 초록 → 짝·변이★.
> 묶음마다: ruff · 전체 pytest · tsc · eslint · 빌드 · 관련 E2E → HISTORY(무엇·왜·시험·하지 않은 것·내 실수) → 이름 지은 파일만 커밋 → 푸시 → CI 세 잡.
> 고치지 않는 파일: `src/kis_backtest_engine.py` · `src/engine/fill_price.py` · 스크리너 3-레이어 · `constrained_opt.py` · 주문 경로 · `/backtest` 화면 · `tests/conftest.py`.

## W4a — 분봉 데이터의 출처와 품질

**과제 a1 — 행 단위 출처와 운영 차단** (`src/data/minute_bars.py` · 시험 `tests/test_minute_bars_origin.py`)
- 시험: 모의 수집 파일의 모든 행이 `source == "synthetic"` · 실 수집(가짜 클라이언트 주입)은 `"kis"` · 출처 열이 없는 옛 파일은 `"unknown"` 으로 읽힌다 ·
  ★운영 게이트(`KIS_USE_MOCK=0`)에서 합성 행은 `load_minute_bars` 가 돌려주지 않는다(`None`)★ · 짝: 같은 파일이 모의 게이트에서는 390행 · `kis` 행은 운영에서 그대로 ·
  한 일파일에 합성 종목과 실 종목이 섞여 있으면 운영에서 실 종목만 · 기존 엔진의 하이브리드 체결이 그 경우 `fallback` 으로 센다(엔진 0줄 — 동작으로).
- 구현: `SOURCE_KIS/SOURCE_SYNTHETIC/SOURCE_UNKNOWN` · `_fetch_minute_bars → (봉, 출처)` · `collect_day` 가 행마다 출처를 쓴다 · `_read_day_file` 이 출처 열이 없으면 `unknown` 을 채운다 ·
  `load_minute_bars` 는 운영에서 합성 행을 뺀다(반환 열은 예전 그대로 — 기존 소비자 불변) · 새 `load_day_frame(date) → (표 | None, 사유 | None)`(출처 열 포함 · 사유 `not_loaded` · `synthetic_rows_blocked`).
- 씨앗: `hash()` → `zlib.crc32`. 시험: 서로 다른 `PYTHONHASHSEED` 의 하위 프로세스 둘이 같은 봉을 낸다(고치기 전 빨강).
- 새 파일은 거래량을 `float64` 로. 머리말의 "신호는 일봉" 문장을 ADR 006 대로 고친다.

**과제 a2 — 장 운영 규칙 증거 파일** (`docs/specs/krx-session-rules-evidence.json` · `src/data/market_rules.py` 에 읽는 함수 하나)
- 정규장 시작·끝 · 종가 단일가 시작 · 등급·출처. 확인하지 못한 칸은 `null` + 사유. `session_rules() → dict`(파일을 못 읽으면 값 없음 + 사유 — 시각을 코드에 박지 않는다).
- 시험: 파일의 값이 그대로 나온다 · 파일을 지우면 `None` + 사유(짝) · 기존 `market_rules` 함수 불변.

**과제 a3 — 품질 검사** (`src/data/minute_quality.py` — 순수 · 시험 `tests/test_minute_quality.py`)
- `check_session(bars) → dict`: 봉 수(정규장 안/밖) · 시각 형식·순서·중복 · OHLC 정합 · 0 이하 가격 · 음수 거래량 · 거래 없는 봉 · 1분 넘는 빈틈 · 첫·마지막 봉. ★고치지 않고 센다.★
- `check_day(day) → dict`: 종목별 결과 + 출처별 행 수 + `session_shifted`(모든 종목의 첫 봉이 평소 개장보다 30분 넘게 늦음 — 관측한 시각과 함께).
- 시험: 결함마다 "있는 봉/없는 봉" 짝 · 빈 표 · 규칙 파일이 없을 때(정규장 안/밖을 가르지 못함 — `None` + 사유).

**과제 a4 — 적재 범위 라우트** (`src/api/intraday_routes.py` · `GET /api/v1/intraday/coverage`)
- 로그인 필요(`protected_routes` · 접근 지도) · `ROUTER_MODULES` 등록 · 기간 상한(92일) · 파일만 읽음(외부 호출 0 — 클라이언트 생성이 없다는 것을 동작으로).
- 응답: 날짜마다 {종목 수 · 봉 수 · 출처별 행 수 · 결함 수 · `session_shifted` · 사유} + `unknowns`(봉 시각 규약 · 소급 한도 · VI/단일가/정지 — 사유와 확인 방법).
- 시험: 401 · 모양 · 빈 폴더(빈 목록 + 사유) · 운영 게이트에서 합성 파일은 `synthetic_rows_blocked` · 기간 상한 400.

**과제 a5 — 마무리**: 합성값 등록부 문구 · `retention` 문구 확인 · 변이(운영 차단 제거 · 출처를 늘 `kis` · 옛 파일을 `kis` 로 · 씨앗 되돌리기 · 결함 세기 각각) · 게이트 · HISTORY · 커밋·푸시.

## W4b — 시뮬레이터 코어 (`src/engine/intraday/`)

**과제 b1 — 지표 등록부** (`indicators.py` · 시험 `tests/test_intraday_indicators.py`)
- `INDICATORS: dict[str, Indicator]` — `open·high·low·close·volume·vwap·day_open·or_high(N)·or_low(N)·or_done(N)·sma(n)·rsi(n)·bb_mid/upper/lower(n,k)·vol_avg(L)·highest_close(L)·prev_close·prev_high·prev_low·minute`.
- 시험: 손 계산 값(봉 10개) · ★성질 시험 — 등록부의 모든 지표에 대해 임의의 k 에서 뒤를 지우거나 바꿔도 앞 k 개 값이 같다★ · 덥혀지지 않은 자리는 `NaN`(0 이 아니다) · 전일 값이 없으면 전부 `NaN`.

**과제 b2 — 표현식 나무** (`expr.py` · 시험 `tests/test_intraday_expr.py`)
- 잎 `ind`·`const` · 가지 `gt·ge·lt·le·cross_up·cross_down·and·or·not·held(M)·between_time` · `validate(tree)`(모르는 지표·연산·깊이 상한 → 사유) · `evaluate(tree, ctx) → bool 배열`(`NaN` 이 낀 비교는 거짓).
- 시험: 연산마다 참/거짓 짝 · `cross_up` 은 앞 봉이 필요하다(첫 봉은 거짓) · 검증 거절 사유 · 성질 시험(뒤를 바꿔도 앞이 같다).

**과제 b3 — 체결가** (`fills.py` · 시험 `tests/test_intraday_fills.py`)
- 호가 단위 불리 맞춤(`market_rules.tick_size`) · 슬리피지(틱) · 손절 갭 · 익절 관통 · 참여율 상한 · 수량 `floor`.
- 시험: 설계 §6.3 표의 줄마다 손 계산 + 짝.

**과제 b4 — 시뮬레이터** (`simulator.py` · `__init__.py::run` · 시험 `tests/test_intraday_simulator.py`)
- 하루를 시각 순으로 한 번 · 신호는 봉 i 종가까지 → 체결은 봉 i+1 시가 · 미리 건 주문은 앞 봉까지의 가격으로 그 봉 안에서 · 포지션·위험 규칙(§6.4) · 강제 청산 · 건너뜀과 사유 · 가정 횟수.
- `run(days, rule, position, costs, master) → {fills, journal, origin, assumptions, skipped}` — `journal` 은 `trade_journal.analyze` 그대로(요율만 넘긴다).
- 시험: ★손 계산 하루 둘★(모든 체결가·수량·손익) · ★앞보기 0 성질 시험(봉 k 뒤를 바꿔도 k 앞의 체결이 같다)★ · 한 봉 손절·익절 동시(손절 먼저) · 거래 없는 봉 · 하루 최대 손실이 종목을 가로지른다 · 재진입 금지 · 15:20 뒤 진입 없음 · 운영 시간이 다른 날 건너뜀 · 합성 섞임 → `origin.grade == "E0"` · 수수료율 미상 → 순손익 `None`.
- 변이: 다음 봉 → 같은 봉 · 손절 먼저 → 익절 먼저 · 갭 시가 → 손절가 · 관통 → 닿음 · 미리 건 가격을 그 봉 값으로 · 종목 가로지르기 제거 · 미상 → 0.
- 재기: 종목 30 × 거래일 66(약 77만 봉)의 실행 시간 → 라우트 상한을 정한다.

## W4c — 규칙 틀과 화면

**과제 c1 — 틀 일곱** (`rules.py` · 시험 `tests/test_intraday_rules.py`): 매개변수 검증(범위 밖 → 사유) · 틀마다 손으로 만든 하루에서 "신호가 나는 봉/안 나는 봉" 짝 · 전일 값이 필요한 틀은 없으면 건너뜀 · 모든 틀이 앞보기 성질 시험을 통과.
**과제 c2 — 실행 라우트** (`POST /api/v1/intraday/simulate`): 로그인 · 상한(종목 30 · 종목×거래일 · 사유) · 손익분기 비용 · 슬리피지 0·1·2틱 민감도 · 외부 호출 0 · 주문 경로에 닿지 않음(정적 시험) · 로그에는 수만.
**과제 c3 — 화면** (`/intraday` · `entities/intraday` · `widgets/intraday`): 매매일지 결과 부품을 두 화면이 쓰게 옮긴다(`tj-*` 클래스 불변 — 기존 E2E 초록 확인 먼저) · 절 여섯 · 합성 고정 표시 · 내비 · 다크 · 접근 지도 · 용어집 절.
**과제 c4 — E2E `intraday.spec.ts`** + 프론트 변이 + 스크린샷 검수(라이트/다크/390px) → 전송.

## W4d — 판정

**과제 d1 — 시행 기록** (`src/data/intraday_trials.py`): 기록·가족 세기(기간이 겹치고 종목이 하나라도 겹침)·같은 설정 재실행은 새 시행 아님·DB 실패 시 `None` + 사유(N=1 로 꾸미지 않는다). 보존 분류 등록.
**과제 d2 — 검사** (`validate.py`): 시간순 70/30 분할 · 워크포워드(선언한 격자 ≤ 12칸) · 비용 2배·+1틱 · DSR(`deflated_sharpe` — 거래 없는 날 0).
**과제 d3 — 관문 표** (`gates.py`): 일곱 관문 · 상태는 `ok/degraded/unknown` · 경제적 가치·모의/실계좌는 늘 `unknown` · 맺는 문장. `multiplicity_evidence` 등록부와 그 모듈의 문장 고침.
**과제 d4 — 라우트·화면·E2E** (`POST /api/v1/intraday/validate` · 판정 절) → 게이트 · HISTORY · PR 본문.

## 범위 밖 (다시 적는다)
자유 조건식을 받는 문·편집 화면 · 스크리너 연동 · 틱·호가 · 공매도 · 하루를 넘기는 보유 · 선물옵션 · 자동 주문 · 전 종목 분봉 수집 자동화 · 규칙 추천 · 기존 엔진 수정.
