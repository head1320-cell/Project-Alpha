# 차트 라이브러리 경계 고정 + 늘 보이는 읽는 줄 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** recharts 를 지우는 대신 경계를 고정하고(차트 파일에서만 import), 캔버스에서는 빼고, 값을 호버 툴팁에서 늘 보이는 읽는 줄로 옮긴다.

**Architecture:** 직접 SVG 부품(`shared/ui/plot` · `shared/ui/Donut` · `widgets/portfolio-graph/MiniPlots`) + 읽는 줄 틀(`shared/ui/chart`) + ESLint 경계. 서버 변경 없음.

**Tech Stack:** Next 16 · React 19 · recharts 2.15(남김) · Playwright E2E · ESLint 9 flat config.

---


## Context
- 사용자 질문: "recharts 를 제거하는 게 맞는지, 더 좋은 방식이 있는지". 판단을 드렸고 사용자가 **"경계 고정 + 읽는 줄"** 을 골랐다.
- 판단 요지: 전부 제거는 목표가 아니다. 실제 문제는 셋 — ⑴ 캔버스 묶음이 recharts(96 kB gzip)를 바로 싣는다 ⑵ 값이 호버 툴팁에만 있다
  (ADR 003 "툴팁 금지" · 터치·키보드로 못 읽음) ⑶ recharts 3 은 재 보고 되돌려(HISTORY · `docs/plans/2026-11-08-stack-upgrade.md` 5b) 2.15 에
  묶여 있는데 import 가 흩어져 있다.
- 조사(읽기 전용 · 2026-11-10) 사실:
  - recharts import 파일 10 · 차트 21: 매크로 11(`analyticsParts.charts` 4 · `cockpitParts.charts` 3 · `visualParts.charts` 1 · `StudioPanel` 3 ·
    `DrillDownModal` 1 — 합 12 중 도넛 1 포함) · 기업 4(`company/charts.tsx`) · 파생 2(`derivatives/charts.tsx` — **툴팁 없음**) · 캔버스 3
    (`Bl2Results::FrontierResult` 산점도 · `MacroResults::SimulationResult` 계단선 · `MacroW2Results::YieldCurveResult` 선+칠한 구간).
  - 늦게 받기(`shared/ui/lazyChart.tsx`)는 `/macro`·`/insights`·`/derivatives` 만. 캔버스는 `NodeResultPanel.tsx` 가 세 파일을 정적 import.
    `StudioPanel.tsx` 는 recharts 를 직접 import 하고 스튜디오 네 페이지(`src/app/macro/{causal-deepm,tsfm-latent,neural-sde,pinn-tail}/page.tsx`)가
    정적으로 싣는다. `DrillDownModal` 은 `dynamic()` 이라 이미 늦게 온다.
  - `<Tooltip>` 을 쓰는 파일 9/10. recharts 클래스에 걸린 E2E 11 스펙 54곳.
  - 손그림 도넛이 이미 있다: `widgets/portfolio-graph/StrategyDonut.tsx`(100 에 대한 몫 · `circle[data-port][data-share]` · `.pg-donut[data-slices]`).
    매크로 `HoldingsDonut`(recharts Pie + Tooltip · lazyChart)은 여섯 자리에서 쓰인다.
- 규율(유지): 화면은 서버 값을 서식만 · 툴팁 0(`title=` 포함) · 금지어 6 · 해요체 · 미상은 "몰라요" · 새 색 토큰 0 · CSS 클래스명은 E2E 계약(바꾸면
  스펙과 같은 커밋) · FSD(`shared` 는 `shared` 만 import · 위젯끼리 import 금지) · `NEXT_PUBLIC_*` 금지 · 서버 변경 없음.

## 설계

### A. 캔버스 차트 셋 → 직접 SVG (캔버스에서 recharts 0)
- 새 `frontend/src/shared/ui/plot/plotGeo.ts`(순수): `linScale(d0, d1, r0, r1)` · `niceTicks(lo, hi, n)` · `xyPath(points)`.
  폭은 `shared/ui/perf/useMeasuredWidth.ts`, 글자 폭·솎기는 `shared/ui/perf/perfGeo.ts`(`textW`·`linePath`) 재사용.
- 새 `frontend/src/widgets/portfolio-graph/MiniPlots.tsx`: `FrontierPlot`(구름 점 · 경계 선 · 이은 비중 점 · 축 끝 눈금 `.pg-plot-xtick/.pg-plot-ytick`) ·
  `StepPlot`(0~100% 계단선) · `CurvePlot`(만기 범주 축 · 점마다 금리 글자 늘 보임 · 뒤집힌 이웃 쌍 `.pg-curve-dip`).
- 값은 호버 없이: 프론티어·계단선은 읽는 줄(`.pg-plot-read` · ←→ Home End · 기본 자리 = 프론티어는 지금의 "가장 좋은 점", 계단선은 마지막 시점) +
  표 쌍둥이(`<details class="pf-table">`) · 수익률곡선은 점이 열 개 안팎이라 글자를 점 위에 직접.
- 감싸는 계약은 그대로: `.pg-chart` · `.pg-frontier` · `.pg-curve` · `.pg-curve--inv` · `aria-label` · KV 행 · `.pg-note` · `.pg-tag`.
- 화면이 이미 하던 셈(프론티어 `best` 고르기 · 구름 3개 중 1개 솎기 · 뒤집힌 구간 찾기 · 노출 ×100 서식)은 **그대로 옮기기만** 한다(새 셈 0).

### B. 보유 도넛 → 공용 손그림 고리
- 새 `frontend/src/shared/ui/Donut.tsx`: `DonutRing({ slices: {key, value, color, data?}[], total, size, children })` — `StrategyDonut` 의 고리
  (`circle` + `strokeDasharray`)를 그대로 옮긴 것. `total` 이 분모(캔버스 = 100 · 매크로 = 값의 합 → 지금 recharts Pie 와 같은 비율).
- `StrategyDonut` 은 `DonutRing` 을 쓰되 **DOM 이 같아야** 한다(`data-port`·`data-share`·범례·가운데 글자 — `canvas-golden.spec` ·
  `canvas-workspace.spec:1115` 가 지킨다).
- `HoldingsDonut`: `cockpitParts.charts.tsx`(recharts Pie · lazy) → `cockpitParts.tsx` 의 평범한 부품(`DonutRing` · `foldHoldings` 그대로 ·
  `role="img"` + 조각 전부를 적은 `aria-label` · Tooltip 없음). 12시에서 시계 방향(지금은 3시에서 반시계 — 보이는 차이로 기록).
- 카드의 보유 6줄 계약(`macro-cards.spec:370`)은 그대로 — 7번째·기타 조각의 값은 전략 창 목록과 `aria-label` 에 있다.

### C. 경계 고정 — 린트 + 스튜디오 늦게 받기
- `frontend/eslint.config.js`: `"no-restricted-imports": ["error", { paths: [{ name: "recharts", message: "… 차트 파일에서만 · ADR 004" }] }]` +
  예외 블록 `files: ["src/**/charts.tsx", "src/**/*.charts.tsx"]`.
- `StudioPanel.tsx` 의 세 LineChart(`FactorViz`·`CurveViz` 안) → 새 `StudioPanel.charts.tsx` + `lazyChart`/`chartModule`(기존 문법 그대로 ·
  `derivatives/parts.tsx`·`macro/analyticsParts.tsx` 가 본보기). 스튜디오 네 페이지의 첫 화면에서 recharts 가 빠진다.
- `DrillDownModal.tsx` 의 AreaChart → 새 `DrillDownModal.charts.tsx`(모달이 이미 `dynamic()` 이라 정적 import · 동작 불변).
- 새 `docs/decisions/adr-004-chart-library-boundary.md`: recharts 는 일반 차트에 남긴다 · 성과 그림과 단순한 그림은 손그림 · 값은 호버에만 두지
  않는다 · 다른 라이브러리로 갈아타지 않는다 · 다시 볼 때(보안 공지 · React 비호환 · 2.x 유지 종료).

### D. 읽는 줄 틀 + 첫 화면(매크로 분석 탭 넷 + 지표 흐름 창 하나)
- 새 `frontend/src/shared/ui/chart/ChartReadout.tsx`(recharts import 없음): `useReadout(n, initial = n − 1)` → `{ idx, setIdx, keyProps }` ·
  `<ReadoutFrame label rows idx onIdx>` = 포커스 가능한 틀(←→ Home End) + 늘 보이는 읽는 줄 `.cr-read`(`aria-live="polite"`) +
  표 쌍둥이 `<details class="cr-table">`(솎지 않은 전부) · `idxFromChartEvent(state)`(recharts 2 의 `activeTooltipIndex` 를 읽는 **한 곳**).
  CSS 는 `.pf-read`·`.pf-table` 선언에 묶어 쓴다(같은 모양 · 새 토큰 0 · 선택자 충돌 없게 이름은 `cr-*`).
- 적용: `analyticsParts.charts.tsx` 의 `RollingCorrChart`·`AvgCorrChart`·`TimingHistory`(시계열 — 차트 `onMouseMove` → `setIdx` · 십자선 =
  `ReferenceLine x` · 점 = `ReferenceDot`) · `RegimeTrajectory`(산점도 — 점 `onMouseEnter` + 키보드로 달마다) · `DrillDownModal.charts.tsx`.
  다섯 차트에서 `<Tooltip>` 제거. 읽는 줄 글자는 기존 서식 함수(`signed`·`toFixed`·`fmtNum`) 그대로 · em-dash 없음(매크로 글 규칙).
- 이번에 하지 않는 나머지 12개(매크로 cockpit 2 · visual 1 · studio 3 · 기업 4 · 파생 2)는 recharts 그대로. 파생 2는 이미 툴팁이 없다.
  매크로 나머지·기업은 이 틀이 자리 잡은 뒤 별도 승인으로.

## 구현 단계 (TDD · 커밋 여섯 · 브랜치 `claude/backtest-modern-ui-refactor-akxvbc`)
0. **문서** — ADR 004 · 설계 `docs/superpowers/specs/2026-11-10-chart-boundary-readout-design.md` · 계획
   `docs/superpowers/plans/2026-11-10-chart-boundary-readout.md`. 커밋 ①.
1. **측정 기준선** — 직전 커밋 워크트리 빌드(:3002 · `cp -al node_modules`)로 `/allocation` 과 스튜디오 한 페이지의 첫 화면 JS(압축 전송 · 3회 중앙값).
2. **A 캔버스 셋** — `portfolio-graph.spec.ts` 를 먼저 고쳐 빨강: 프론티어 눈금(`:970` `.recharts-xAxis …` → `.pg-plot-xtick` < 300) · 구름 점 수 =
   서버 구름/3 · 읽는 줄 기본 = 서버 가장 좋은 점 · ← 로 바뀜 · 수익률곡선 점 글자 = 서버 `yield_pct` · 칠한 구간(`:1218` → `.pg-curve-dip`) ·
   계단선 읽는 줄 마지막 = 서버 마지막 노출 · 세 노드에서 `.pg-side .recharts-wrapper` 0. `charts-lazy.spec.ts` 에 "/allocation 은 한 번 돌려도
   recharts 조각을 받지 않는다". 구현 → 초록 → 변이(구름 ×100 · 읽는 줄 자리 고정 · 칠한 구간 안 그림). 커밋 ②.
3. **B 도넛** — `macro-cards.spec.ts:538`(`.recharts-pie-sector path` → 고리 `circle` 색 = 범례 칸 색) + 조각 수 = min(보유, `CAT_N`) ·
   `aria-label` 에 첫 종목과 비중. 빨강 → `Donut.tsx` · `StrategyDonut` · `HoldingsDonut` → 초록. `canvas-golden`·`canvas-workspace` 통과 확인.
   변이(분모를 100 으로 → 합이 100 이 아닌 픽스처에서 길이 단언이 죽는지). 커밋 ③.
4. **C 경계** — `charts-lazy.spec.ts` SCREENS 에 스튜디오 페이지 추가(빨강: 초기 script 에 recharts) → `StudioPanel.charts.tsx`·
   `DrillDownModal.charts.tsx` → 린트 규칙 → `npm run lint` 0 오류. 린트 변이: 차트 파일이 아닌 곳에 `import … from "recharts"` 를 넣어 오류가 나는지
   확인하고 되돌림. `macro-studios.spec`(`:302~308`) 그대로 통과. 커밋 ④.
5. **D 읽는 줄** — `macro-cards.spec.ts` 새 시험(빨강 먼저): 상관·타이밍 탭과 지표 흐름 창에서 `.recharts-tooltip-wrapper` 0 · 읽는 줄 마지막 날짜와
   값 = 서버 마지막 점 서식 · ← 로 앞 날짜 · 표 행 수 = 서버 점 수 · `[title]` 0. 기존 "글 — 탭" · AA · 390 시험 통과. 변이(자리 0 고정 ·
   표 솎기 · Tooltip 남김). 커밋 ⑤.
6. **마무리** — 측정(전/후 표) · 스크린샷 검수(라이트·다크·390: 캔버스 세 노드 · 전략 카드와 창의 도넛 · 상관·타이밍 탭 · 지표 흐름 창) → 고칠 것
   고침 · 전체 E2E(백그라운드) → 서버 내리고 `make all` → HISTORY(무엇·왜·시험·측정·하지 않은 것) · 설계 문서 "실물 대 설계" 절 → 커밋 ⑥ →
   푸시(재시도 2/4/8/16초) → 포트·임시 폴더 정리. PR 은 만들지 않는다.

## 고칠 파일(대표)
- 새로: `shared/ui/plot/plotGeo.ts` · `shared/ui/Donut.tsx` · `shared/ui/chart/ChartReadout.tsx` · `widgets/portfolio-graph/MiniPlots.tsx` ·
  `widgets/macro/StudioPanel.charts.tsx` · `widgets/macro/DrillDownModal.charts.tsx` · `docs/decisions/adr-004-…` · 설계·계획 문서.
- 고침: `widgets/portfolio-graph/{Bl2Results,MacroResults,MacroW2Results,StrategyDonut}.tsx` · `widgets/macro/{cockpitParts,cockpitParts.charts,
  analyticsParts.charts,StudioPanel,DrillDownModal}.tsx` · `app/globals.css` · `eslint.config.js` · `e2e/{portfolio-graph,charts-lazy,macro-cards}.spec.ts` ·
  `docs/HISTORY.md`.

## 검증
- 환경: `S=/tmp/claude-0/-home-user-Project-Alpha/0fe04482-a04d-5c82-835a-5814b8ac096a/scratchpad` · 서버 `bash $S/stk/up.sh $S/venv314f/bin/python`
  (3000/8000 · 빌드는 3000 을 내린 뒤 `( cd frontend && npm run build )`) · 스크립트는 `$S/stk/*.js`.
- 커밋마다: `npx tsc --noEmit` · `npx eslint <고친 파일>` · 대상 스펙(`portfolio-graph` · `charts-lazy` · `macro-cards` · `macro-studios` ·
  `canvas-golden` · `canvas-workspace` · `module-motion` · `radix-dialogs` · 성과 스펙 셋).
- 끝: 전체 E2E 1회(기록된 간헐과 대조 — 실패는 홀로 다시 돌려 확인) → `make all`(lint + pytest + typecheck + build).
- 눈으로: 스크린샷에서 겹침·잘림·다크 대비 확인. 수 대조: 프론티어·수익률곡선·노출의 화면 글자 = 응답 값(같은 실행).

## 하지 않음
recharts 전부 제거 · 다른 차트 라이브러리 · recharts 3 올리기 · 남은 12개 차트의 읽는 줄(매크로 나머지·기업 — 별도 승인) · 파생 차트 손대기 ·
전략 카드 보유 6줄 계약 · 도넛을 100 기준으로 바꾸기 · 화면이 하던 기존 셈 고치기(프론티어 `best` · `foldHoldings` 기타 합 · 뒤집힌 구간) ·
서버·정책·지표 변경 · 새 색 토큰 · PR.
