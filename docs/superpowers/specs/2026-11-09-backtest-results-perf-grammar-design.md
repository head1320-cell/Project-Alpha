# 백테스트 결과 화면에 성과 그림 문법 옮기기 — 설계 (2026-11-09)

> 앞선 설계 [`2026-11-09-canvas-performance-viz-design.md`](2026-11-09-canvas-performance-viz-design.md)(캔버스 세 노드 + 성과 시트)의
> 둘째 소비자. 같은 부품·같은 규칙을 `/backtest/runs/<id>/results` 에 붙인다. 사용자 결정(2026-11-09): ① 범위 = **C. 그림 전부 +
> 기여도까지**(이 화면에서 recharts 가 빠진다) ② 접근 = **`run_full` 에 `perf` 블록 + 부품 접두어 `pg-pf-*` → `pf-*`** ③ 설계 7절 승인.

## 1. 맥락과 문제

`/backtest/runs/<id>/results`(`frontend/src/widgets/backtester/BacktestResults.tsx` · 765줄)는 BU4 토스화 뒤로 **답 한 문장 → 자산곡선 →
낙폭 → 핵심 지표 6(+사유 있는 '산출 불가' · 지표 모두 보기) → 월별 수익률 → 기여도 → 종목별 → 거래 기록 → 데이터와 한계** 순이다.
그림 넷(자산곡선 LineChart · 낙폭 AreaChart · 월별 BarChart · 기여도 BarChart)은 recharts 이고 떠다니는 `Tooltip` 을 쓴다.

- **단위 결함**: 엔진(`kis_backtest_engine`)의 `drawdown_curve` 는 비율(−0.15)이고 통계 `max_drawdown_pct` 는 %(14.9)다. 화면은 비율을 그대로
  축에 그리고 툴팁에 `%` 를 붙인다 → "−0.1%" 로 읽힌다. E2E 픽스처(`e2e/helpers.ts::completedRun`)는 %(−1.9)로 적혀 있어 시험이 이 결함을
  보지 못했다. 캔버스 불러오기 노드는 서버 뷰가 `drawdown_pct` 로 옮겨 적는 것으로 이미 고쳤다(앞선 설계 §4.5).
- 그림이 "무엇을 모르는지" 말하지 않고(연습용 여부는 칩에만), 값은 툴팁에만 있어 키보드로 읽을 수 없다(ADR-003 §2.4).
- 캔버스와 같은 실행을 다른 모양으로 그린다 — 해마다·달마다·낙폭 사건이 없고, 월별은 막대 하나.

## 2. 조사에서 확인한 것 (읽기 전용)

- 응답: `GET /api/v1/backtest/runs/{id}` = `src/api/backtest_run_routes.py::run_full` — 저장 행 + `perf_label` + `execution_assumption` 을
  **응답에 붙여 돌려준다**(응답이 스스로 말한다). `result.backtest` = `statistics` · `equity_curve`(원) · `equity_dates` · `drawdown_curve`(비율) ·
  `monthly_returns`(`{year, month, return_pct}` · 엔진 `_compute_monthly_returns` — 값 골든) · `benchmark{label, curve(원), total_return_pct,
  excess_return_pct, beta, alpha_pct}` · `trades`/`round_trips` · `symbol_results[{symbol, corp_name, contribution_pct, …}]`. `result` 에
  `pit_evidence`·`macro_lookahead`·`fundamentals_pit`·`price_basis`·`universe`(데이터와 한계의 글).
- 화면 계약(`e2e/backtest-results.spec.ts`·`e2e/backtest.spec.ts`): `.tx-answer` 문장 = 서버 값 · `.perf-label` 이 답 문장 안 · "GCP"·"실데이터"
  글자 없음 · `.terminal-main [title]:not(.perf-label)` 0 · `.brun-card-t`(H2) 로 절을 찾음("자산곡선" 이 `.rs-key` 보다 위 · "기여도") ·
  `.rs-kpis--key .brun-kpi` 6 · `details.rs-all` 접힘 · `.rs-na .brun-kpi-na` 사유 · `.brun-kpi-v` 등락색 토큰 · `.brun-kpi-tip` 글 있음 ·
  주 단추 `.tx-btn--main` 1 · 390 가로 넘침 없음 · 다크 AA · **recharts 계약 둘** — 자산곡선 세로축 눈금(`.recharts-yAxis … tick-value`:
  잘림 없음·서로 다름·오름차순·맨 위 ≥ 최댓값·만/억 단위·100 언저리는 단위 없음) · S1c `.recharts-line-curve` 의 stroke 가 토큰으로 해석됨.
- 픽스처: `completedRun()` — 곡선 다섯 점(100 언저리) · `equity_dates` 가 "2023-01" 꼴(월 단위) · `drawdown_curve` 가 %로 적힘 ·
  `monthly_returns` 가 숫자 배열. 라우트를 가로채 그대로 돌려주므로 서버 `perf` 블록은 픽스처에 손으로 넣는다.
- 부품: `frontend/src/widgets/portfolio-graph/perf/`(14 파일) · 클래스 `pg-pf-*` — CSS 103곳 · 스펙 둘 86곳 · `tests/test_badge_axis_registry.py`
  1곳(`pg-pf-strip-practice`). 색은 역할 변수 `--pf-*` 만 읽고 `.pg-theme` 이 넣는다.
- `BacktestCompare.tsx` 도 recharts 를 쓴다(비교 화면 — 이번 범위 밖). `RunMonitor` 는 안 쓴다.

## 3. 설계

### 3.1 읽는 순서 (페이지)

```
답 한 문장(그대로: 서버 값 · PerfLabel · 연습용/시점 정합 칩 · 사유 줄 · 행동 넷)
질문 띠 ─ 답하는 것: 이 조건식이 과거에 어떤 성과를 냈나 (② 전달)
        답하지 않는 것: ③ 예측 스킬 · ④ 경제적 가치 — 이 화면은 둘을 재지 않아요 (관문은 캔버스에서)
[자산곡선과 낙폭] ─ 그림 하나(곡선 + 벤치마크 회색 + 낙폭 물속 + 증거 띠 + 읽는 줄) · 범례 · 띠 범례 · ▸ 표로 보기
[핵심 지표] ─ 그대로(6 · 산출 불가 · 지표 모두 보기 · eod 정리 메모)
[기간별] ─ 해마다 표 · 달마다 격자
[큰 낙폭 사건] ─ 표(고점·바닥·깊이·바닥까지·되찾은 날·되찾기까지 / 아직 못 찾음)
[기여도] ─ HTML 막대(이름 · 막대 · 부호 숫자)
[종목별 성과] · [거래 기록] · [데이터와 한계] ─ 그대로
```

자산곡선·낙폭 두 카드가 한 카드 "자산곡선과 낙폭" 이 되고(제목 `.brun-card-t` 는 "자산곡선"으로 시작해 기존 `/^자산곡선/` 찾기가 산다), 월별
카드가 "기간별" 카드로 바뀐다. 카드 구조(`Card` · `.brun-card` · `.rs-card-h/.rs-card-b`)와 순서 계약(곡선이 `.rs-key` 보다 위)은 그대로.

### 3.2 수는 서버가 낸다 — `run_full` 의 `perf` 블록

`run_full` 이 `perf_label`·`execution_assumption` 옆에 `perf` 를 붙인다(`src/api/backtest_run_routes.py`):

```
perf: {
  unit: "krw",
  drawdown_pct: [비율 × 100, 소수 4자리] | null,      # 저장된 drawdown_curve 가 없으면 null
  periods: period_returns(equity_dates, equity_curve), # 해마다·달마다 (quant_metrics · partial · 연환산 없음)
  drawdowns: drawdown_episodes(equity_dates, equity_curve, top=3),
} | null                                               # result 가 없거나 끝나지 않은 실행이면 null
```

- 같은 함수(`quant_metrics.period_returns`·`drawdown_episodes`)라 캔버스 불러오기 노드와 **같은 수**가 나온다. 화면은 세지 않는다.
- 엔진 `monthly_returns` 는 그대로 싣되 화면은 `perf.periods.monthly` 만 그린다. 둘은 같은 곡선에서 나오므로 같아야 한다 — 구현 때 실제 실행
  하나로 대조해 HISTORY 에 적는다(다르면 그 사실을 적고 고치지 않는다 — 엔진 함수는 값 골든).
- `perf` 가 없으면(옛 응답·픽스처) 화면은 세 절(그림의 낙폭 · 기간별 · 낙폭 사건)에서 "서버가 … 주지 않았어요" 라고 말한다. 곡선 자체는
  `equity_curve` 로 그린다(낙폭 없이). ★화면이 비율에 ×100 하지 않는다★.
- 시험(빨강 먼저): `tests/test_backtest_run_perf_block.py` — 끝난 실행 → `perf.drawdown_pct` = 저장 비율×100 · `periods`·`drawdowns` 가 같은
  곡선의 재계산과 같음 · 낙폭 곡선이 없는 결과 → `drawdown_pct: null` · 끝나지 않은 실행 → `perf: null`. `test_perf_label_wiring::test_the_run_response_keeps_every_existing_key` 는 기존 키가 남아 있는지만 걸어(정확한 집합이 아님) 그대로 통과한다
  — `perf` 의 계약은 새 파일이 건다.

### 3.3 부품 재사용 + 접두어 `pf-*`

- 이름 바꾸기: `pg-pf-*` → `pf-*`(부품 14 파일 · `globals.css` · `canvas-perf-grammar.spec.ts` · `canvas-perf-sheet.spec.ts` ·
  `tests/test_badge_axis_registry.py`). 둘째 소비자가 생기는 지금 바꾼다 — 캔버스 밖 화면에 `pg-` 가 남으면 이름이 거짓말을 한다. CSS 클래스명은
  E2E 계약이라 스펙과 **같은 커밋**에서 바꾼다. `.pg-sheet--wide`·`.pg-pf-open` 같은 캔버스 전용(시트·단추)은 그대로.
- 역할 변수(`.rs` 에 · 새 토큰 0): `--pf-ink: var(--tx-ink)` · `--pf-body: var(--tx-sub)` · `--pf-mute: var(--tx-mute)` · `--pf-line:
  var(--tx-line)` · `--pf-soft: var(--tx-soft)` · `--pf-surface: var(--tx-surface)` · `--pf-up/--pf-up-ink/--pf-down/--pf-down-ink: var(--tx-up…)` ·
  `--pf-assume: var(--tx-warn)`(연습용·가정 칩이 쓰는 색 — 값이 `--pg-assume` 과 같다 #a15c00/#f5b453) · `--pf-unknown: var(--tx-mute)`(몰라요 글 —
  `--pg-unknown` #5b6573 과 가까운 회색 · 흰 바탕 대비 5.6:1). 다크는 `.dark` 의 같은 토큰이 받는다.
- 쓰는 부품: `PerfCurve`(높이 300 · 원 단위 → 세로축 자리 자동) · `YearTable` · `MonthGrid` · `DrawdownEpisodes` · `PerfTableView` ·
  `QuestionStrip`. 안 쓰는 부품: `PerfFigures`(답 문장·핵심 지표가 그 자리) · `PerfSheet`(페이지가 이미 넓다) · `PeriodBars` · `MetricGroups`
  (이 화면의 '산출 불가' 사유 논리가 더 낫다 — 그대로).
- 뷰 옮기기: `frontend/src/widgets/backtester/perfOfRun.ts::perfViewOfRun(run) → PerfView` — `equity`·`bench`(길이가 같을 때만)·`drawdown =
  perf.drawdown_pct`·`periods`·`drawdowns`·`practice`(`perf_label.data_real`)·`question`·`rebalances: []`·`learnFrom/asOf: null`·`figures: []`.
  리밸런싱 날짜는 이 엔진에 없으니 띠는 리밸런싱을 말하지 않는다(모름 ≠ 0). 부품 폴더는 `widgets/portfolio-graph/perf/` 에 둔 채 import 한다
  (옮기는 리팩터는 이번에 하지 않는다 — 두 화면이 쓰는 것이 확인된 뒤 `shared/ui/perf` 로 올린다 · HISTORY 에 적는다).

### 3.4 질문 띠 (관문 없는 화면)

`QuestionStrip` 에 `noGatesText?: string` 을 더한다. `gates === null` 이고 이 글이 있으면 "관문 판정이 없어요 — 계산 전…" 대신 그 글을 적는다:
"이 화면은 예측 스킬·경제적 가치를 재지 않아요. 캔버스에서 이 실행을 불러오면 관문(표본 밖 · 경제적 가치)이 매겨져요." 답하는 것:
"이 조건식이 과거에 어떤 성과를 냈나 (네 질문 중 ② 전달 안정성)". 캔버스 쪽 글은 그대로.

### 3.5 기여도 — HTML 막대

recharts 가로 막대 → 표 한 줄 = 종목 이름 · 막대(`--pf-up`/`--pf-down` · 길이 = |기여도|/최대) · 부호 숫자(등락 잉크색). 상위 8 + 하위 8 규칙 그대로.
클래스 `.brun-attr-table`·`.brun-attr-bar`(새로) — 캔버스 `Bars` 와 같은 문법(별도 복제 — 캔버스 것은 `pg-table`·`pg-bar` 계약에 묶여 있다).
이로써 `BacktestResults.tsx` 의 recharts import 가 0 이 된다. `useChartAnimation` 도 뺀다.

### 3.6 색·접근성·글

- 색은 `--pf-*` 만. 등락 숫자만 `--pf-up-ink/--pf-down-ink`. 툴팁(`title=`) 0 — 기존 계약 `[title]:not(.perf-label)` 0 이 그대로 건다.
- 그림은 `role="group"` + `aria-label` · 키보드 ←→ Home End · 읽는 줄 `aria-live`. 390 에서 그림 폭은 `ResizeObserver` 로 맞고 달마다 격자는
  가로 스크롤(`.pf-months-wrap`).
- 글은 해요체 · 부품의 글 그대로. 카드 제목: "자산곡선과 낙폭" · "기간별" · "큰 낙폭 사건" · "기여도".

## 4. 검증

- 기존 계약 유지(§2 목록 전부). **바꾸는 계약(동작은 같게)**: 세로축 눈금 시험 셋 → `.pf-ytick`(잘림 없음·서로 다름·오름차순·맨 위 ≥ 최댓값·
  만/억·100 언저리 단위 없음 — 눈금 수 하한은 2 로: 부품은 위·기준선·아래 셋이되 기준선이 가까우면 둘) · S1c → `.pf-line-port` 의 stroke 가
  토큰으로 해석됨.
- 새 스펙 `e2e/backtest-results-perf.spec.ts`(옛 빌드에서 빨강): (a) 그림 하나 — `.pf-line-port`·`.pf-line-bench`·`.pf-dd-area` · 읽는 줄 마지막
  날 · ArrowLeft (b) 낙폭 단위 = 통계 `max_drawdown_pct` 와 같은 단위(픽스처 `perf.drawdown_pct` 로) (c) 달마다 칸 수 = `perf.periods.monthly` ·
  값 = 서버 (d) 낙폭 사건 행 수 = `perf.drawdowns` · 회복 null 은 "아직" (e) 기여도 막대 수 = contribution 있는 종목 수(≤16) · 부호·색
  (f) 짝: `perf` 를 빼면 낙폭·기간별·낙폭 사건이 "주지 않았어요" 이고 곡선은 그대로 (g) 질문 띠 글(관문 없음 문장) (h) recharts 요소 0 · `[title]` 0
  (i) 다크 AA(`.brun-results`).
- 변이(한 빌드): 화면이 periods 를 제 손으로 세면(픽스처에서 `perf` 를 빼도 격자가 나옴) → (f) 실패 · 낙폭에 화면이 ×100 → (b) 실패 ·
  기여도 막대 색 뒤집음 → (e) 실패.
- 서버: §3.2 시험 넷 · 금지어 · 기존 라우트 시험.
- 측정: 첫 화면 JS `/backtest/runs/x/results` 전/후(L5 기준 343.6 kB · recharts 포함) · 결과 화면 열림 → 첫 그림 ms.
- 눈으로: 라이트·다크·390 스크린샷 대 §3.1 — 바꾼 것을 §5.1 에 적는다.

## 5. 하지 않는 것

비교 화면(`BacktestCompare`)의 recharts · 핵심 지표 타일과 '산출 불가' 사유 논리 · 엔진의 월별 함수(`_compute_monthly_returns` — 값 골든) · 답
문장을 서버 explain 으로 옮기기(지금처럼 화면이 서버 값으로 조립) · 부품 폴더를 `shared/ui` 로 올리기(둘째 화면이 붙은 뒤 별도) · 진행·비교 화면.

## 5.1 실물 대 와이어프레임 (구현 뒤 · 2026-11-09)

라이트·다크·390 스크린샷(`pfshot5.js` · 실제 실행 하나 · 2023년 kospi50 GoldenCross)을 §3.1 과 견줘 바꾼 것. 숫자는 그 실행에서 본 값.

1. **부품 폴더** — §3.3·§5 의 "widgets 에 둔 채 import · `shared/ui` 로 올리기는 하지 않음" 은 FSD 규칙(`eslint.config.js` `import/no-restricted-paths`:
   widgets 끼리 import 금지)에 막혀 바뀌었다. 공용 부품 11개는 `shared/ui/perf/` 로, 캔버스 전용 셋(PerfPanel·PerfSheet·useCanvasGates)은 widgets 에.
   부품은 entities 의 `NodeExplain`·`GateState` 대신 제 구조 타입 `PerfExplain`·`PerfGate` 를 읽는다. `tests/test_perf_label_contract.py` 의 허용 항목 둘을
   지우고 공허 방지 하한을 10 → 8 로(사유 주석).
2. **`pg-pf-open`** — §3.3 은 "그대로" 라 했으나 규칙(`pg-pf-*` → `pf-*`)대로 `pf-open` 으로. 캔버스 전용으로 남은 이름은 컨테이너 `.pg-pf` 와 `.pg-sheet--wide` 둘뿐.
3. **날짜 라벨** — 390px 에서 처음·가운데·끝 셋이 겹쳤다(그림 폭 ≈ 226px · 라벨 ≈ 68px). 폭이 `라벨 × 3 + 16px` 보다 좁으면 처음·끝 둘만(공용 부품이라 캔버스도).
4. **표 쌍둥이** — 390px 에서 "1.0억원" 이 "1.0억 / 원" 으로 꺾였다. 칸은 nowrap, 넘치면 가로 스크롤(이미 세로 스크롤 상자).
5. **읽는 줄의 누적 %** — 곡선 첫날 대비(+25.2%)라 머리글의 총수익(초기 자본 대비 +24.9%)과 달랐다 — 첫날 값이 이미 비용을 뺀 9,983만원이라서. 초기 자본은
   서버가 응답에 싣지 않으니 기준을 바꾸지 않고 "(첫날 대비 +25.2%)" 로 기준을 적었다(캔버스도 같은 글).
6. **기여도 숫자** — 두 자리·모노(`.num`)였던 것을 아래 종목 표와 같은 한 자리·같은 글꼴로.
7. **달마다 격자의 글** — "점선 테두리는 그 달의 일부만 있는 달" 은 서버가 아는 것보다 세게 말했다(서버 `partial` 은 곡선의 첫 달·마지막 달 표시 — 1월 2일 시작은
   달력상 첫 영업일인데도 partial). "곡선이 시작하거나 끝나는 달이에요 — 달 전체가 아닐 수 있어서 그 기간 수익을 그대로 적었어요" 로. 캔버스 시트 스펙 (n) 의
   글 확인도 같이.
8. **`.rs` 의 `--pg-*` 다리** — 부품이 쓰는 전역 도우미(`.pg-note`·`.pg-table`·`.pg-h4`·`.pg-td-num`)는 `--pg-ink/body/mute/line` 을 읽으므로 `.rs` 에서 그 넷도
   `--tx-*` 로 잇는다(§3.3 의 역할 변수 목록에 없던 것 · 새 토큰 0).
9. **E2E 재겨냥 하나 더** — `backtest.spec.ts` 의 `page.locator("table").first()` 가 접힌 `details.pf-table` 안의 숨은 표를 잡아 `.brun-table` 로.
10. **서버 결함(E2E 가 잡음)** — ① 커밋이 `_perf_block` 을 GET 데코레이터와 `run_full` 사이에 끼워 넣어 GET 이 422 를 냈고 `run_full` 은 경로에서 빠졌다. 함수를
    직접 부르던 단위 시험은 전부 통과했다. 결과 화면 E2E(404 → '찾지 못했어요')가 잡았고 별도 커밋으로 고치며 라우트 표 시험을 더했다.

그대로인 것: 읽는 순서(§3.1 열 줄) · 카드 구조·순서 계약 · 핵심 지표·종목별·거래·한계·진행·비교 절 · 질문 띠 글 · 기여도 막대 ≤ 16 · 다크는 같은 토큰.

## 6. 단계 (커밋 단위)

① 서버 `perf` 블록(TDD) ② 접두어 `pg-pf-*` → `pf-*`(부품·CSS·스펙·레지스트리 — 한 커밋 · 캔버스 두 스펙 통과 확인) ③ 결과 화면 — 뷰 옮기기 ·
그림 하나 · 기간별 · 낙폭 사건 · 질문 띠 · 기여도 막대 · 눈금 시험 재겨냥 · 새 스펙 · 변이 ④ 측정 · 전체 E2E · `make all` · HISTORY · §5.1.
