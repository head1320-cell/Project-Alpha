# 차트 라이브러리 경계 고정 + 늘 보이는 읽는 줄 — 설계 (2026-11-10)

> 결정 기록: [ADR 004](../../decisions/adr-004-chart-library-boundary.md) · 계획:
> [`docs/superpowers/plans/2026-11-10-chart-boundary-readout.md`](../plans/2026-11-10-chart-boundary-readout.md)

## 1. 맥락과 문제

성과 그림 문법 ①~③(2026-11-09)이 성과 그림을 직접 SVG 로 옮긴 뒤 사용자가 물었다: "recharts 를 제거하는 게 맞는지, 더 좋은 방식이 있는지".
판단: **전부 제거는 목표가 아니다.** 실제 문제는 셋이고 각각 더 싼 해법이 있다. 사용자는 "경계 고정 + 읽는 줄" 을 골랐다.

1. **캔버스 묶음의 무게** — 결과 패널이 recharts(96 kB gzip)를 바로 싣는다. 캔버스의 recharts 차트는 셋뿐이고 단순하다.
2. **값이 호버 툴팁에만** — recharts 파일 10 중 9 가 `<Tooltip>` 을 쓴다. 터치·키보드로 값을 못 읽고 ADR 003 §2.4 "툴팁 금지" 와 어긋난다.
3. **2.x 에 묶인 의존성** — recharts 3 은 재 보고 되돌렸다. import 가 흩어져 있어 바꿀 때 손댈 곳이 정해져 있지 않다.

## 2. 조사에서 확인한 것 (읽기 전용 · 2026-11-10)

- recharts import 파일 10 · 차트 21: 매크로 12(`analyticsParts.charts` 4 · `cockpitParts.charts` 3(도넛 포함) · `visualParts.charts` 1 ·
  `StudioPanel` 3 · `DrillDownModal` 1) · 기업 4(`company/charts.tsx`) · 파생 2(`derivatives/charts.tsx` — 툴팁 없음) · 캔버스 3
  (`Bl2Results::FrontierResult` 산점도 · `MacroResults::SimulationResult` 계단선 · `MacroW2Results::YieldCurveResult` 선 + 칠한 구간).
- 늦게 받기는 `/macro`·`/insights`·`/derivatives` 만(`shared/ui/lazyChart.tsx` · `e2e/charts-lazy.spec.ts`). 캔버스는
  `widgets/portfolio-graph/NodeResultPanel.tsx` 가 세 파일을 정적으로 import 한다. `StudioPanel.tsx` 는 recharts 를 직접 import 하고
  스튜디오 네 페이지(`src/app/macro/{causal-deepm,tsfm-latent,neural-sde,pinn-tail}/page.tsx`)가 정적으로 싣는다. `DrillDownModal` 은
  `MacroCockpit.tsx` 가 `dynamic()` 으로 불러 이미 늦게 온다.
- 손그림 도넛이 이미 있다: `widgets/portfolio-graph/StrategyDonut.tsx`(100 에 대한 몫 · `circle[data-port][data-share]` ·
  `.pg-donut[data-slices]`). 매크로 `HoldingsDonut`(recharts Pie + Tooltip · lazyChart)은 여섯 자리에서 쓰인다.
- E2E 가 거는 recharts 클래스: `portfolio-graph.spec`(프론티어 x축 눈금 · 수익률곡선 칠한 구간) · `macro-cards.spec`(롤링 상관 선 색 ·
  도넛 조각 색) · `macro-studios.spec`(선 수) · `insights.spec` · `derivatives.spec` · `module-motion.spec`(/insights 애니메이션) ·
  `charts-lazy.spec`(조각 표지 `recharts-wrapper`).
- 프론트 단위 시험 러너는 없다(Playwright 만) — 빨강 먼저는 E2E 로 한다.

## 3. 설계

### 3.1 A — 캔버스 차트 셋 → 직접 SVG (캔버스에서 recharts 0)

- `shared/ui/plot/plotGeo.ts`(순수 · 새): `linScale(d0, d1, r0, r1)` · `niceTicks(lo, hi, n)` · `xyPath(points)` · `stepPath(xs, ys)`.
  폭은 `shared/ui/perf/useMeasuredWidth.ts`, 글자 폭은 `shared/ui/perf/perfGeo.ts::textW`.
- `shared/ui/chart/useReadout.ts`(새): `useReadout(n, initial?)` → `{ idx, setIdx, onKeyDown }`(←→ Home End · 범위 안으로 자름).
- `widgets/portfolio-graph/MiniPlots.tsx`(새):
  - `FrontierPlot` — 구름 점(`.pg-plot-dot`) · 경계 선(`.pg-plot-line`) · 이은 비중 점(`.pg-plot-point`) · 고른 경계 점(`.pg-plot-active`) ·
    축 눈금(`.pg-plot-xtick`·`.pg-plot-ytick`) · 축 이름.
  - `StepPlot` — 0~100% 계단선. ★못 읽은 시점은 0 이 아니라 끊긴 선★(예전 코드는 `?? 0` 으로 0% 를 그렸다 — 고친다).
  - `CurvePlot` — 만기 범주 축 · 점마다 금리 글자(들어갈 때) · 뒤집힌 이웃 쌍 `.pg-curve-dip`.
- 값은 호버 없이: 셋 다 읽는 줄(`.pg-plot-read` · `aria-live`) + 표 쌍둥이(`<details class="pf-table">`). 기본 자리 — 프론티어는 지금의
  "가장 좋은 점", 계단선·수익률곡선은 마지막 점.
- 감싸는 계약은 그대로: `.pg-chart` · `.pg-frontier` · `.pg-curve` · `.pg-curve--inv` · `aria-label` · KV 행 · `.pg-note` · `.pg-tag`.
- 화면이 이미 하던 셈(프론티어 `best` 고르기 · 구름 3개 중 1개 솎기 · 뒤집힌 구간 찾기 · 노출을 % 로 서식)은 그대로 옮긴다(새 셈 0).

### 3.2 B — 보유 도넛 → 공용 손그림 고리

- `shared/ui/Donut.tsx`(새): `DonutRing({ slices: {key, value, color, data?}[], total, r, width, gap, trackClass })` — `StrategyDonut` 의 고리
  (`circle` + `strokeDasharray`)를 그대로 옮긴 조각 묶음(svg 는 부르는 쪽이 만든다). `total` 이 분모.
- `StrategyDonut` 은 `DonutRing(total = 100)` 을 쓰되 DOM 이 같아야 한다.
- `HoldingsDonut` — `cockpitParts.charts.tsx`(recharts Pie · lazy) → `cockpitParts.tsx` 의 평범한 부품. `total` = 값의 합(예전 Pie 와 같은
  비율) · `svg.tx-donut[role=img]` + 조각 전부를 적은 `aria-label` · `circle[data-slice]` · Tooltip 없음 · 12시에서 시계 방향.
- 카드의 보유 6줄 계약은 그대로다 — 7번째·기타 조각의 값은 전략 창 목록과 `aria-label` 에 있다.

### 3.3 C — 경계 고정

- `eslint.config.js`: `no-restricted-imports`(recharts) + 예외 `src/**/charts.tsx` · `src/**/*.charts.tsx`.
- `StudioPanel.tsx` 의 세 LineChart → `StudioPanel.charts.tsx` + `lazyChart`/`chartModule`. 스튜디오 네 페이지의 첫 화면에서 recharts 가 빠진다.
- `DrillDownModal.tsx` 의 AreaChart → `DrillDownModal.charts.tsx`(정적 import · 모달이 이미 `dynamic()`).

### 3.4 D — 읽는 줄 틀 + 첫 화면

- `shared/ui/chart/ChartReadout.tsx`(새 · recharts import 없음): `ReadoutFrame({ label, rows, idx, onKeyDown, children })` = 포커스 가능한 틀 +
  읽는 줄 `.cr-read`(`aria-live="polite"`) + 표 쌍둥이 `details.cr-table`(솎지 않은 전부) · `idxFromChartEvent(state)`.
  CSS 는 `.pf-read`·`.pf-table` 선언에 묶는다(같은 모양 · 새 토큰 0 · 이름은 `cr-*` 라 기존 선택자와 안 겹친다).
- 적용: `analyticsParts.charts.tsx` 의 `RollingCorrChart`·`AvgCorrChart`·`TimingHistory`(차트 `onMouseMove` → 자리 · 십자선 `ReferenceLine x`) ·
  `RegimeTrajectory`(점 `onMouseEnter` + 키보드로 달마다) · `DrillDownModal.charts.tsx`. 다섯 차트에서 `<Tooltip>` 을 뺀다.
- 읽는 줄 글자는 기존 서식 함수(`signed` · `toFixed` · `fmtNum`) 그대로 · em-dash 없음(매크로 글 규칙).

### 3.5 색·접근성·글

새 색 토큰 0(캔버스 `--pg-*` · 그 밖 `--tx-*` · 범주색 `--mc-c-*`). `title=` 0. 움직임 0(손그림). 해요체. 미상은 "몰라요"·"못 읽었어요"(0 아님).

## 4. 검증

- E2E 빨강 먼저(옛 빌드에서 새 단언이 실패하는지) → 구현 → 초록. 커밋마다 변이.
- `portfolio-graph.spec`(프론티어 눈금 < 300 · 구름 점 수 · 읽는 줄 = 서버 값 · ← 로 바뀜 · 수익률곡선 글자 = 서버 `yield_pct` · 칠한 구간 ·
  계단선 마지막 = 서버 마지막 노출 · `.recharts-wrapper` 0) · `charts-lazy.spec`(/allocation 은 한 번 돌려도 recharts 조각 0 · 스튜디오 초기
  script 에 recharts 0) · `macro-cards.spec`(도넛 조각 색 = 범례 색 · 조각 수 · 읽는 줄 · 표 행 수 · 툴팁 0).
- 측정: `/allocation` · 스튜디오 페이지 첫 화면 JS 전/후(압축 전송 · 3회 중앙값).
- 눈으로: 라이트·다크·390 스크린샷 → §7.
- 끝: 전체 E2E 1회 → `make all`.

## 5. 하지 않는 것

recharts 전부 제거 · 다른 차트 라이브러리 · recharts 3 · 남은 12개 차트의 읽는 줄(매크로 cockpit 2 · visual 1 · studio 3 · 기업 4 — 별도 승인 ·
파생 2 는 이미 툴팁이 없다) · 전략 카드 보유 6줄 계약 · 도넛을 100 기준으로 바꾸기 · 화면이 하던 기존 셈 고치기(프론티어 `best` ·
`foldHoldings` 기타 합 · 뒤집힌 구간) · 서버·정책·지표 변경 · 새 색 토큰 · PR.

## 6. 단계 (커밋 단위)

① 문서(ADR 004 · 이 문서 · 계획) → ② A 캔버스 셋 → ③ B 도넛 → ④ C 경계 → ⑤ D 읽는 줄 → ⑥ 측정·검수·게이트·기록.

## 7. 실물 대 설계 (구현 뒤 · 2026-11-10)

라이트·다크 스크린샷(캔버스 세 노드 · 전략 카드와 창의 도넛 · 상관·타이밍·국면 궤적 · 지표 흐름 창 · 390 한 장)과 §3 을 견줘 바뀐 것.

1. **`useReadout` 은 따로 파일이 아니다** — `shared/ui/chart/ChartReadout.tsx` 한 파일에 `useReadout` · `ReadLine` · `TableTwin` ·
   `ReadoutFrame` · `idxFromChartEvent` 가 있다. 직접 SVG 그림(캔버스 셋)은 svg 가 포커스를 받고 `ReadLine`·`TableTwin` 만 쓴다 · recharts
   그림은 `ReadoutFrame` 이 포커스를 받는다(틀 안의 다른 조작부에서 누른 키는 가로채지 않는다).
2. **시점별 노출의 시간 방향** — 받은 순서를 뒤집던 것을 날짜 순으로 바꿨다(서버는 옛날부터 준다). 예전엔 가로축이 숨겨져 있어 시간이
   오른쪽에서 왼쪽으로 흐르는 것이 안 보였다. 이제 축 양 끝에 가장 옛 날짜·가장 최근 날짜를 적는다(§3.1 에 없던 것).
3. **`.pg-expo`** — §3.1 은 감싸는 이름을 정하지 않았다. 처음 붙인 `.pg-step` 은 이야기 탭의 단계 줄이 쓰는 이름이었다.
4. **`role="img"` 는 svg 쪽으로** — 감싸는 `div` 에 `role="img"` 가 있으면 안의 읽는 줄·표가 보조 기술에 안 보인다. 그림(svg)이
   `role="group"` + 이름을 갖는다(성과 그림 `PerfCurve` 와 같은 짜임). 국면 궤적은 `.mc-scatter[role=img]` 를 틀 안에 그대로 둔다.
5. **수익률 곡선의 역전 표시** — `.pg-curve--inv` 의 왼쪽 빨간 줄이 그림뿐 아니라 읽는 줄·표까지 감싼다(같은 상자 안이라).
6. **도넛 조각의 이름** — `DonutRing` 에 `arcClass`(매크로는 `tx-donut-arc`). 스타일 골든이 class 없는 `circle` 로 뭉뚱그리지 않게.
   캔버스 도넛은 예전 DOM 그대로(class 없음).
7. **읽는 줄 틀의 이름** — `ReadoutFrame` 은 `data-chart` 를 낸다(`rolling-corr` · `avg-corr` · `timing-history` · `regime-trajectory` ·
   `drill-series`) — E2E 가 그림을 가리키는 이름.
8. **툴팁 없이도 마우스가 된다** — recharts 2 는 `<Tooltip>` 이 없어도 차트 `onMouseMove` 에 `activeTooltipIndex` 를 준다(E2E 가 건다).
   산점도는 점의 `onMouseEnter`.
9. **자료 배열 고정** — 읽는 줄 자리가 바뀌면 부품이 다시 그려진다. 자료 배열을 useMemo 로 고정했다. 다시 그림은 프레임 지문으로 쟀다(1).
10. **남긴 것** — 전략 카드 도넛의 7번째·기타 조각은 카드 목록(6줄)에 없다(`aria-label` 과 전략 창에 있다) · 롤링 상관은 범례와 읽는 줄이
    같은 색 표식을 두 번 보인다 · 지표 흐름 창은 그림 → 읽는 줄 → 표 → "점선은 지난 5년 평균" 순서다 · 프런티어의 읽는 줄은 경계 위 점만
    읽는다(구름 점은 읽지 않는다 — 예전 툴팁은 읽었다).

그대로인 것: §3.2 고리의 분모 규칙 · §3.3 린트 규칙과 예외 글롭 · §3.4 다섯 그림 · 새 색 토큰 0 · 서버 변경 없음.
