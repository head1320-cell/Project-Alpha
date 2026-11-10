# ADR 004 — 차트 라이브러리 경계: recharts 는 차트 파일 안에만, 값은 늘 보이는 줄에

- 상태: 채택 (2026-11-10)
- 결정한 사람: 사용자 질문("recharts 를 제거하는 게 맞는지, 더 좋은 방식이 있는지", 2026-11-10) 뒤 AskUserQuestion 답
  **"경계 고정 + 읽는 줄"**(네 방향 중: 경계 고정 + 읽는 줄 · 캔버스만 손그림 · 전부 제거 · 지금은 그대로)
- 스펙: [`docs/superpowers/specs/2026-11-10-chart-boundary-readout-design.md`](../superpowers/specs/2026-11-10-chart-boundary-readout-design.md)

## 1. 맥락 — 재 본 것 (2026-11-10 · 읽기 전용)

성과 그림 문법 ①~③ 이 성과 그림을 직접 SVG 로 옮긴 뒤 "남은 recharts 도 지울 것인가" 가 남았다.

| 무엇 | 값 |
|---|---|
| recharts 를 import 하는 파일 · 차트 | 10 · 21 (매크로 12 · 기업 4 · 파생 2 · 캔버스 결과 3) |
| 늦게 받는 화면(`shared/ui/lazyChart.tsx`) | `/macro` · `/insights` · `/derivatives` |
| 바로 싣는 곳 | 캔버스 결과 패널(`NodeResultPanel` → 세 파일) · 스튜디오 네 페이지(`StudioPanel`) |
| recharts 조각 | 96 kB(gzip · `docs/plans/2026-11-08-stack-upgrade.md`) |
| `<Tooltip>` 을 쓰는 파일 | 9 / 10 (파생만 없다) |
| recharts 클래스에 걸린 E2E | 11 스펙 · 54 곳 |
| recharts 3 | 재 보고 되돌림(차트 화면 JS +16~22 kB · 타입 검사 +13%) — 2.15.4 유지 |

문제는 라이브러리가 "있다"가 아니라 셋이다: ⑴ 캔버스 묶음이 통째로 싣는다 ⑵ 값이 호버 툴팁에만 있다(ADR 003 §2.4 "툴팁 금지" ·
터치·키보드로 못 읽는다) ⑶ 2.x 에 묶여 있는데 import 가 흩어져 있어 바꿀 때 손댈 곳이 정해져 있지 않다.

## 2. 결정

1. **recharts 는 남긴다.** 가격 밴드·누적 막대·이중 축·산점도 같은 일반 차트는 라이브러리가 잘하는 영역이다.
2. **import 는 차트 파일에서만.** `charts.tsx` · `*.charts.tsx` 밖에서 `recharts` 를 import 하면 ESLint 오류(`no-restricted-imports`).
   소비자는 `lazyChart` 로 받는다. 이미 `dynamic()` 으로 늦게 오는 창(`DrillDownModal`)은 제 차트 파일을 정적으로 import 해도 된다.
3. **손그림이 맞는 자리 셋.** ㈎ 성과 그림 — 증거 띠·낙폭 물속처럼 라이브러리가 못 그리는 문법(①~③). ㈏ 한 화면 묶음에서 라이브러리를
   통째로 뺄 수 있는 단순한 그림 — 캔버스 결과 셋(산점도 · 계단선 · 수익률곡선). ㈐ 이미 손그림 부품이 있는 것 — 도넛.
4. **값을 호버에만 두지 않는다.** 늘 보이는 읽는 줄 + 표 쌍둥이 + 키보드(←→ Home End). recharts `<Tooltip>` 은 새로 쓰지 않고 화면 단위로
   걷어 낸다. 첫 화면은 매크로 분석 탭의 넷과 지표 흐름 창 하나.
5. **recharts 이벤트 모양을 아는 곳은 한 곳.** `shared/ui/chart/ChartReadout.tsx::idxFromChartEvent`(2.x 의 `activeTooltipIndex`).
6. **다른 차트 라이브러리로 갈아타지 않는다.**

## 3. 기각한 것

- **전부 제거** — 복합 차트마다 축·눈금·겹침 처리를 다시 만들고 E2E 54 곳을 다시 써야 한다. 얻는 것은 늦게 받는 조각 96 kB 뿐이고
  세 화면의 첫 화면에는 이미 없다. 순서가 아니다(CLAUDE.md §5 "정교함을 위한 정교함 금지").
- **라이브러리 교체(visx · uPlot · ECharts)** — 재작성 비용은 같고 위 세 문제는 하나도 풀리지 않는다. 캔버스(`<canvas>`) 렌더는 DOM 을
  보는 E2E 계약·읽는 줄 접근성과 어긋난다.
- **recharts 3** — 재 보고 되돌린 기록 그대로(얻은 것이 측정되지 않았다).
- **지금은 그대로** — 캔버스 묶음과 호버 전용 값이 남는다.

## 4. 다시 볼 때

- recharts 2.x 에 보안 공지가 나거나 React·Next 와 맞지 않게 되거나 유지가 끝나면: 3 을 다시 재거나 교체를 검토한다. 그때 손댈 곳은
  차트 파일 목록(린트 예외 글롭)과 `idxFromChartEvent` 다.
- 손그림으로 더 넘어가 recharts 차트가 한 화면 묶음에만 남으면: 그 묶음에서의 제거를 다시 잰다.

## 5. 지키는 것

- 린트: `frontend/eslint.config.js` 의 `no-restricted-imports`(변이로 오류가 나는지 확인하고 HISTORY 에 적는다).
- E2E: `charts-lazy.spec.ts`(초기 script 에 recharts 0 · 캔버스는 한 번 돌려도 조각 0) · 읽는 줄 시험(`macro-cards.spec.ts`).
- 변하지 않는 것: 화면은 서버 값을 서식만 · CSS 클래스명은 E2E 계약 · 새 색 토큰 0 · 서버 변경 없음.
