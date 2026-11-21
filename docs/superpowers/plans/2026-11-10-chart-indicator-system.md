# 한 체계로 읽히는 차트·지표 + 화면 다듬기 · 계획 2026-11-10

## Context
- 요청: "find skill 로 차트·시각 지표·UI 디자인을 발전시킬 스킬을 골라 세련되게 디벨롭 · 범위는 넓어도 됨".
- 고른 스킬 둘: **`dataviz`**(형태 → 색의 일 → 팔레트 검증기 → 표식 규격 → 상호작용 → 접근성 → 그려 보고 확인) ·
  **`impeccable`**(제품 UI 의 절대 금지·대비·글자 규칙). `ui-ux-pro-max` 는 쓰지 않는다 — 시각 언어는 ADR 003 이 이미 정했다.
- 스킬과 저장소 규칙이 부딪히는 곳은 저장소가 이긴다: dataviz 는 "호버 툴팁 기본"인데 ADR 003/004 는 툴팁 금지 →
  **읽는 줄 + 십자선 + 표 쌍둥이**가 같은 뜻(값은 호버 없이도 읽힌다 · 키보드 동등)을 채운다.
  impeccable 은 `SKILL.md` 본문만 설치돼 있다(scripts·reference 없음 · PRODUCT.md 없음) → 본문의 일반 규칙·절대 금지만 쓰고 ADR 003/004 를 디자인 맥락으로 삼는다.
- 읽기 전용 점검(2026-11-10 · **관측**):

| 무엇 | 결과 |
|---|---|
| 팔레트 검증기(`validate_palette.js`) | 범주 7색 라이트·다크 PASS(CVD ΔE 9.1 / 8.8 · 정상시 19.6 / 19.3) · 국면 4색 전쌍 PASS. ★라이트 대비 WARN 3색(#1baf7a 2.82 · #eda100 2.17 · #e87ba4 2.69)★ → 스킬 규칙상 "보이는 글자 또는 표"가 의무(무시 불가). **색 토큰은 바꾸지 않는다** |
| 이중 축 | 1 — `company/charts.tsx::StoryChart`(매출 막대 왼쪽 축 + 이익률 선 오른쪽 축). 스크린샷에서 이익률 선이 막대 높이와 관계있어 보인다 |
| 값이 툴팁에만 | `<Tooltip>` 9 차트(매크로 금리곡선·축 쌓기·스튜디오 3 · 기업 4) + 파생 기대노출 곡선은 읽을 길이 아예 없음 |
| 표식 규격 | 격자 점선 5/7 + `.pg-plot-grid` · 선 굵기 1.4~2.6 여섯 가지 · 점 r 2.5~3(고리 없음) · 면 그라데이션 0.18~0.24→0 · 막대 44px · 축 글자 11/12 섞임 |
| 겹친 띠 | `PriceValueChart` — 모형 7개 범위를 반투명 띠로 겹쳐 깐다 → 겹친 곳 색이 범례에 없는 색(스크린샷 확인) |
| 스파크라인 | 구현 5개(굵기 1 / 1.4 / 1.5 / 1.6 / 1.6 · 하나는 `preserveAspectRatio=none` 으로 선 굵기가 늘어남 · 하나는 값 1개면 NaN) |
| 화면 실측(10 라우트 첫 화면 · 계산된 스타일) | 라틴 대문자 꼬리표 0 · 모노 글꼴은 종목코드·키뿐 · 큰 숫자는 전부 Pretendard ✓. ★큰 숫자(≥20px)에 `tabular-nums` 9 계열★(`mx-stat-v`·`rv-gauge-v`·`mc-gauge-c b`·`ci-price`·`ci-sumcard-v`·`ci-model-v`·`tstat-val` 등) · 옆줄 테두리(>1px) 1(`.as-case-warn-cap`) |
| 옆줄 테두리(조건부 상태 · grep) | `.pg-ask-fact` · `.pg-claim` · `.pg-curve--inv` · `.set-error` · `.as-case-warn*` · `.ms-note` (그리고 src 에 쓰는 곳이 없는 `.pg-simple-result--blocked/failed`) |

- 규율(유지): 화면은 서버 값을 서식만 · 툴팁 0 · 금지어 6 · 해요체 · 미상은 "몰라요/없어요"(0 아님) · 새 색 토큰 0 · CSS 클래스명은 E2E 계약(바꾸면 스펙과 같은 커밋) ·
  recharts import 는 차트 파일만(ADR 004) · 라이트 골든은 의도한 라우트만 다시 얼리고 `golden-diff` 출력을 커밋 메시지에 · 서버·정책 변경 없음.

## 설계

### A. 표식 규격 한 곳 — `shared/ui/chart/chartSpec.ts`(새 · recharts import 없음)
```ts
export const MARK = { line: 2, quiet: 1.5, dotR: 4, ring: 2, wash: 0.1, barMax: 24, barR: 4 } as const;
export const AXIS_TICK = { fontSize: 12, fill: "var(--tx-sub)" } as const;
export const ringDot = (color: string) => ({ r: MARK.dotR, fill: color, stroke: "var(--tx-surface)", strokeWidth: MARK.ring });
```
- recharts 7 파일 + 손그림(`MiniPlots` · `.pg-plot-*` CSS)이 이 값을 쓴다: 선 2px(조용한 선 1.5 + 흐림 — 굵기로 강조하지 않는다 · 회전 상관의 2.6/1.4 포함) ·
  점 r4 + 표면색 고리 2px · 면은 그라데이션 대신 **단색 10% 물들임**(`<defs>` 3곳 삭제) · 격자는 **실선 1px**(점선 삭제 — 평균·손익분기·내재가치 같은
  **주석선의 점선은 그대로**) · 막대 `maxBarSize=24` + 자료 끝 4px 둥글림 · 축 글자 12 하나(`cockpitParts.AX` 는 이 값을 다시 내보낸다).
- 프론티어 구름 점(`.pg-plot-dot`)은 계열 표식이 아니라 배경 점이라 그대로.

### B. 형태 고침 둘(눈에 보이는 변화)
1. **StoryChart — 이중 축 → 위아래 두 칸**(`.ci-story` 안 · 같은 x). 위 `매출` 막대(≤24px · 눈금 조/억 · `0억` → `0`), 아래 `이익률` 선 둘(영업 실선+점 · 순 점선).
   두 칸 모두 `ComposedChart` + `XAxis scale="band"` + 같은 YAxis 폭(52)이라 막대 가운데와 점이 한 줄에 선다. 오른쪽 축 삭제. 범례 글에서 "왼쪽/오른쪽 눈금" 삭제.
   계약 유지: `.ci-story .recharts-bar-rectangle` = 기간 수 · `.recharts-line` 2 · `.ci-story-key` 글.
2. **PriceValueChart — 겹친 띠 → 오른쪽 "가치 범위 막대" 칸**. x 를 숫자 축(그림 px 단위 · `shared/ui/perf/useMeasuredWidth.ts` 로 잰 폭)으로 바꿔 주가 선은 왼쪽 구역,
   모형별 범위는 오른쪽 구역에 **겹치지 않는 가는 세로 막대**(넓은 화면 10px · 390 에서 6px · 네 귀 4px 둥글림 · 단색)로 — **같은 y 축을 공유**한다(지금처럼 `ReferenceArea`).
   내재가치 점선은 전폭 · 마지막 종가에 고리 점 + 범위 칸을 가로지르는 가는 선(지금 주가가 각 범위 안인지 한눈에). 주가가 없으면 선 구역 없이 막대만(지금처럼 "시세가 아직…" 글).
   계약 유지: `.ci-pv .recharts-line` 1/0 · `.recharts-reference-area` 수 + `.ci-pv-out li` = 쓸 수 있는 밴드 수 · `.ci-pv-leg li` = 띠 수. 범례 칸 불투명도 .75 → 1.
   셈은 그대로(4배↑·0.15배↓ 그림 밖 규칙 · lo/hi 는 서버 값).

### C. 값은 늘 읽힌다 — 읽는 줄을 남은 차트 10개에(ADR 004 §2.4 마무리)
- 기존 `shared/ui/chart/ChartReadout.tsx`(`useReadout` · `ReadoutFrame` · `idxFromChartEvent`) 그대로. 보탬 하나: `ReadoutFrame` 에 `table?: boolean`(기본 true) —
  **절에 이미 표가 있으면 표 쌍둥이를 겹치지 않는다**(기업 "돈 버는 힘" 절의 `표로 보기`).
- 대상과 `data-chart` 이름: 매크로 `yield-curve` · `axis-stack-growth|inflation` · 스튜디오 `studio-factor` · `studio-curve` · `studio-tp` ·
  기업 `price-1y` · `price-value` · `kpi-revenue|op|ni` · `story` · 파생 `cva-exposure`.
  선·면은 십자선(`ReferenceLine x`) + 고리 점, 막대는 고른 기간 뒤에 옅은 띠(`ReferenceArea` · `--tx-soft`). 처음 자리 = 마지막 점. 글자는 지금 툴팁이 쓰던 서식 함수 그대로.
- 다중 계열(축 쌓기 · 스튜디오 요인 · 스토리)은 읽는 줄의 선 표식(`.cr-key`)이 범례 구실도 한다 → 대비 WARN 3색의 의무("보이는 글자 또는 표")가 채워진다.
- 하지 않는 둘: `RegimeScatter`(점 하나 · 값이 글자로 있다) · 파생 `Payoff`(화면이 그린 61 표본 — 손익분기·최대 손실이 글로 있다).
- 끝나면 `<Tooltip>` 0 → 린트로 못 박는다: 차트 파일 예외 블록에 `no-restricted-imports` `{ name: "recharts", importNames: ["Tooltip"] }`.
  `chartStyle.ts` 의 `TIP_STYLE`·`TX_TIP_STYLE` 과 `cockpitParts` 의 재수출은 쓰는 곳이 없어지면 삭제.

### D. 지표
1. **스파크라인 하나** — `shared/ui/plot/plotGeo.ts::sparkPoints(values, w, h, pad)` + `shared/ui/plot/Spark.tsx`
   (1.5px · 둥근 이음 · `vector-effect: non-scaling-stroke` · 끝 점 r2.5 + 표면 고리 = "지금" · null/NaN 은 건너뜀 · 값이 둘 미만이면 빈 자리 — 선을 지어내지 않는다).
   다섯 자리(`feedback.Sparkline` · `cockpitParts.Sparkline` · `StudioPanel.Spark` · `MacroW2Results.Spark` · `company/parts.Spark`)가 이것을 쓰되
   **자기 클래스·속성은 그대로**(`mc-spark` · `ms-spark` · `pg-spark` · `ca-spark[data-dir]`) · 색 규칙(등락색/한 색)도 그대로. 끝 점 클래스가 `canvas-classes.json` 에 더해지면 의도한 갱신으로 기록.
2. **큰 숫자는 비례폭 숫자** — 홀로 선 값(≥20px)에서 `tabular-nums` 를 걷는다(위 9 계열 + grep 으로 찾은 같은 종류: `.bte-uni-count b` · `.rs .brun-kpi-v` ·
   `.rs-answer .tx-answer-s` · `.pg-simple-headline b` · `.ci-fd-spread`). 표·축·세로로 줄 서는 숫자는 그대로 고정폭. 조상에서 물려받는 곳(`.mc [role=tabpanel]`)은 값 쪽에 `normal` 을 명시.
3. 게이지·확률 막대·z 막대는 형태 그대로(숫자 규격만 2번을 따른다).

### E. 화면 다듬기(impeccable 절대 금지 — 옆줄 테두리)
- 알림·인용 상자의 `border-left ≥2px` → **전체 1px 테두리 + 옅은 바탕**(이미 있는 토큰만): `.pg-ask-fact` · `.pg-claim` · `.pg-curve--inv` · `.set-error` ·
  `.as-case-warn`/`-cap` · `.ms-note`. 쓰는 곳이 없는 `.pg-simple-result--blocked/failed` 규칙은 삭제하지 않고 보고만(내가 만든 고아가 아니다 — E2E 한 곳이 이름을 본다).
- 그대로 두는 것: 멀리 보기 줌의 노드 단계 색 띠(글자가 숨는 줌의 유일한 부호) · 0폭 위치 표식선(`.ci-q-mid` 등) · 세모·꺾쇠.

## 구현 단계 (TDD · 브랜치 `claude/backtest-modern-ui-refactor-akxvbc` · 커밋 일곱)
0. **문서** — 설계 `docs/superpowers/specs/2026-11-10-chart-indicator-system-design.md` · 계획 `docs/superpowers/plans/2026-11-10-chart-indicator-system.md` ·
   ADR 004 에 "표식 규격은 `chartSpec.ts` 한 곳 · Tooltip import 금지" 두 줄. 커밋 ①.
1. **A 규격** — 새 `e2e/chart-marks.spec.ts`(빨강 먼저): 차트 표(라우트 · 여는 법 · 뿌리 선택자)를 돌며 격자 `stroke-dasharray` = none · 선 굵기 ∈ {2, 1.5} ·
   점이 있으면 r ≥ 4 이고 선 2px · 면 `fill` 이 `url(` 이 아님 · 막대 폭 ≤ 24. 구현 → 초록 → 변이 셋(점선 되살림 · 굵기 2.5 · 점 r3). 커밋 ②.
2. **C-매크로** — `macro-cards.spec.ts` · `macro-studios.spec.ts` 에 "읽는 줄 — …" 시험(빨강): `.recharts-tooltip-wrapper` 0 · 읽는 줄 마지막 값 = 서버 마지막 점 서식 ·
   ← 로 앞 점 · 표 행 수 = 서버 점 수. `cockpitParts.charts` · `visualParts.charts` · `StudioPanel.charts` 구현. 변이(자리 0 고정 · 표 솎기). 커밋 ③.
3. **B+C-기업** — `insights.spec.ts`(빨강): 스토리 칸마다 y 축 1개(오른쪽 축 0) · 첫 막대 가운데 x ≈ 첫 영업이익률 점 x(±1.5px) · 읽는 줄 = 서버 마지막 기간 ·
   가치 범위 막대끼리 x 가 안 겹침 · 폭 ≤ 24 · 전부 마지막 주가 점 오른쪽 · `price-1y`/`kpi-*` 읽는 줄. `company/charts.tsx` · `MoneySection.tsx` · CSS 구현.
   변이(오른쪽 축 되살림 · 막대를 전폭 띠로 · scale=band 제거). 커밋 ④.
4. **C-파생 + 린트** — `derivatives.spec.ts`(빨강): 기대노출 읽는 줄 · 표 10행(= 서버 `ee` 길이 · 점 10개 계약 유지). `Tooltip` 린트 규칙 + 변이(차트 파일에 `Tooltip` import → eslint 오류 확인 후 되돌림).
   `TIP_STYLE` 정리. 커밋 ⑤.
5. **D 지표** — 새 `e2e/figures.spec.ts`(빨강): 라우트 표를 돌며 "홀로 선 숫자 ≥20px 는 `tabular-nums` 가 아니다" + 짝 "표 숫자 칸은 `tabular-nums` 다"(항상-통과 배제) ·
   스파크라인 다섯 자리의 선 굵기 1.5 · 끝 점 1개 · 값 1개면 선 없음. 구현 → 변이(tabular 되살림 · 끝 점 삭제). `canvas-golden` 갱신이 필요하면 diff 를 커밋 메시지에. 커밋 ⑥.
6. **E + 마무리** — 옆줄: 이미 그 상태에 닿는 스펙(`portfolio-graph` · `canvas-ai-question` · `macro-case` · `settings` · `macro-studios`)에
   `borderLeftWidth ≤ 1` + 짝 `borderTopWidth ≥ 1`(테두리를 통째로 지운 구현 배제) 단언(빨강 → CSS → 초록).
   라이트 골든: 색·테두리가 바뀌는 라우트만 다시 얼림(`UPDATE_LIGHT_GOLDEN=1 … -g "라이트 그대로: <라우트>$"`) + `node scripts/golden-diff.mjs --rev HEAD --expect-routes …` 출력.
   스크린샷 검수(라이트·다크·390: 스토리 두 칸 · 가치 범위 막대 · 금리곡선 · 축 쌓기 · 스튜디오 · 파생 · 캔버스 손그림 셋 · 지표 카드 · 요약 타일) → 겹침·잘림·다크 대비 고침.
   팔레트 검증기 다시 실행(색 불변 확인) · 전체 E2E(백그라운드) → 서버 내리고 `make all` → `npx eslint src` → HISTORY(무엇·왜·시험·변이·하지 않은 것) ·
   설계 문서 "실물 대 설계" 절 → 커밋 ⑦ → 푸시(재시도 2/4/8/16초). PR 은 만들지 않는다.

## 고칠 파일(대표)
- 새로: `frontend/src/shared/ui/chart/chartSpec.ts` · `frontend/src/shared/ui/plot/Spark.tsx` · `frontend/e2e/chart-marks.spec.ts` · `frontend/e2e/figures.spec.ts` · 설계·계획 문서.
- 고침: `frontend/src/widgets/company/{charts,MoneySection,parts}.tsx` · `widgets/macro/{cockpitParts,cockpitParts.charts,visualParts.charts,StudioPanel,StudioPanel.charts,analyticsParts.charts,DrillDownModal.charts}.tsx` ·
  `widgets/derivatives/charts.tsx` · `widgets/portfolio-graph/{MiniPlots,MacroW2Results}.tsx` · `shared/ui/{chartStyle.ts,feedback.tsx}` · `shared/ui/chart/ChartReadout.tsx` ·
  `shared/ui/plot/plotGeo.ts` · `app/globals.css` · `eslint.config.js` · `e2e/{insights,macro-cards,macro-studios,derivatives,portfolio-graph,canvas-ai-question,macro-case,settings}.spec.ts` ·
  `e2e/golden/{light-styles,canvas-classes}.json`(의도한 만큼만) · `docs/decisions/adr-004-chart-library-boundary.md` · `docs/HISTORY.md`.
- 다시 쓰는 것: `ReadoutFrame`·`useReadout`·`idxFromChartEvent`(`shared/ui/chart/ChartReadout.tsx`) · `linScale`·`niceTicks`(`shared/ui/plot/plotGeo.ts`) ·
  `useMeasuredWidth`(`shared/ui/perf/`) · `lazyChart`/`chartModule` · `useChartAnimation` · `catColor`(`shared/ui/vizColor.ts`).

## 검증
- 환경: `S=/tmp/claude-0/-home-user-Project-Alpha/0fe04482-a04d-5c82-835a-5814b8ac096a/scratchpad` · 빌드는 3000 을 내린 뒤 `( cd frontend && npm run build )` ·
  서버 `bash $S/stk/up.sh $S/venv314f/bin/python` · 스펙 `( cd frontend && PLAYWRIGHT_BASE_URL=http://localhost:3000 npx playwright test <spec> --trace off --reporter=line )`.
- 커밋마다: `npx tsc --noEmit` · `npx eslint <고친 파일>` · 대상 스펙 + 이웃(`charts-lazy` · `module-motion` · `dark-modules` · `canvas-golden` · `radix-dialogs`).
- 수 대조: 읽는 줄·표의 글자 = 같은 실행의 응답 값(서식만). 눈으로: 스크린샷(라이트·다크·390).
- 끝: 전체 E2E 1회(기록된 간헐 — `canvas-minimap-pick` U3 · `realism` ST3c AA 등 — 과 대조 · 실패는 홀로 다시) → `make all` → `npx eslint src`.
- 이 작업이 답하는 질문: **표현·전달**(값이 읽히는가 · 한 체계로 보이는가)뿐이다 — 예측력·경제적 가치의 증거가 아니다.

## 하지 않음
색 토큰 변경(검증기 PASS · WARN 은 글자·표로 채움) · 차트 라이브러리 교체·recharts 3 · 게이지를 미터로 바꾸기 · 숫자 타일 부품 통합(클래스 계약 다수 — 숫자 규격만 맞춤) ·
촘촘한 쌓은 막대의 2px 틈(달 수가 많아 막대가 가늘다) · z-index 토큰화(보이는 변화 없음) · 쓰지 않는 옛 CSS 청소(대문자 34 규칙 등 — 화면에 안 나옴) ·
`Payoff`·`RegimeScatter` 읽는 줄 · 전략 카드 보유 6줄 계약 · 화면이 하던 기존 셈 고치기 · 서버·정책·지표 변경 · `realism` ST3c 간헐 고침(별건) · README AI 그림(#87) · PR.
