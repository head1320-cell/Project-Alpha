# 성과 그림 문법 ③ — 다른 화면 넷: 둘 겹쳐 보기 + 단일 곡선 이식 (설계 · 2026-11-09)

> 앞선 둘: [캔버스 셋](2026-11-09-canvas-performance-viz-design.md) · [`/backtest` 결과 화면](2026-11-09-backtest-results-perf-grammar-design.md).
> 사용자 결정(이 세션): 범위 **넷 전부, 두 묶음** · 접근 **비교 부품 하나(두 곡선 + 차이 띠)** · 설계 다섯 절 승인.

## 1. 맥락과 문제

성과 그림(자산곡선·낙폭·지표)을 아직 제 방식대로 그리는 화면이 넷 남았다. 둘은 "두 곡선을 겹쳐 보는" 화면이고 둘은 "곡선 하나" 화면이다.

| | 화면 | 지금 | 문제 |
|---|---|---|---|
| ① | `/backtest/runs/[id]/compare` + 캔버스 `backtest_compare` 노드 | recharts 선 둘 · A/B 를 **순번**으로 겹침 · 차이를 화면이 뺌 · 노드는 표만 | 날짜가 다른 두 실행을 같은 x 에 놓고 말하지 않는다(글 한 줄만) · 툴팁 전용 값 · 서버 `perf` 블록(낙폭·해마다·사건)을 둘 다 버린다 |
| ② | 관리자 '현실성' 탭(이상 vs 현실) | recharts 선 둘 + 띠 · 화면 `joinByDate` | 틈(차이)이 음영일 뿐 수치가 없다 · 툴팁 0 이지만 읽는 줄도 0 |
| ③ | `/macro` 전략 상세 모달 | recharts 면 하나 + 지표 5 | 낙폭이 숫자(MDD)로만 · 달 라벨이 어림인데 화면이 말하지 않는다 |
| ④ | 캔버스 `scenario_stress` 과거 모드 | recharts 낙폭 선 둘(툴팁) | 서버가 계산한 자산곡선·벤치마크 곡선을 버리고 낙폭만 그린다 · 낙폭 사건 없음 |

나머지 recharts(시세·수익률곡선·효율 프론티어·노출 추이·MacroW2 수익률곡선)는 성과 그림이 아니라 이 문법 밖이다.

## 2. 조사에서 확인한 것 (읽기 전용)

- 비교 화면 `frontend/src/widgets/backtester/BacktestCompare.tsx`: A·B 를 `run_full` 로 따로 받는다(둘 다 `perf{drawdown_pct, periods, drawdowns}` 있음) · `normalize`(처음 100) · 지표 10행(`CMP_METRICS`) 의 차이를 화면이 뺀다 · 설정 표는 문자열 비교. E2E 계약: `.brun-select` · `.brun-cmp tbody tr` > 4 · `.brun-cmp tr` 차이 열 `td[3]` 색 = 부호 · `.brun-cmp-diff` · `.brun-cmp-labels .perf-label` · 카드 제목 "자산곡선 (시작 = 100)" · 답 "총수익률 +12.6%p" · "총수익률은 비교할 수 없어요".
- 캔버스 비교 노드 `src/api/allocation_graph_nodes_backtest.py::_compare`: `_STAT_KO` 7행 + `_COND_KO` 설정 차이 · 뷰 `{a, b, rows, differences}` · 렌더러 `BacktestCompareResult`(`.pg-cmp` 7행 · `.pg-cmp-warn`). 입력 `a/b` 는 `{run_id, run:{result, input_snapshot, is_mock_data, …}}`.
- 현실성 `frontend/src/widgets/live-trading/RealismTab.tsx`: `runRealism` 둘(`IDEAL_FLAGS`/`REAL_FLAGS`) → `GapChart` 가 `joinByDate` 로 합집합. E2E(`realism.spec.ts`): `.rl-chart[data-days]` = 합집합 수 · `.rl-missing` "현실 쪽에 없는 날 3일"/"이상 쪽에 없는 날 3일" · 강조 라디오 "현실" · 답 `.rl-ans-s`. 서버 기록 `daily_records[{date, portfolio_equity, cumulative_return, drawdown_pct}]`(프론트 타입은 `date·portfolio_equity` 만 선언). E2E 는 `**/api/v1/realism/**` 과 `**/api/v1/multibacktest/**` 만 스텁한다.
- `/macro` 모달 `frontend/src/widgets/macro/StrategyModal.tsx`: `GET /api/v1/macro/strategy/{sid}` → `perf.curve[{t:"24.03", v}]`(처음 100) · `perf.summary{total_return_pct, cagr_pct, mdd_pct, vol_pct, recent_12m_pct}` · `perf.perf_label`. 서버 `src/engine/strategy_profiles.py::_curve_summary` 가 라벨을 `오늘 − 30일 × k` 로 만든다(어림). E2E: `macro-cards.spec.ts` '그림 수 보존 — 전략 창' · `sm-modal`·`sm-body`.
- 스트레스 `src/api/allocation_stress_routes.py::historical_replay`: `eq = cumprod(1+port)` · `beq` 를 계산해 놓고 `dates·portfolio_dd·benchmark_dd(%)·max_dd_pct·total_return_pct` 만 돌려준다. 노드 `allocation_graph_nodes_check.py::_scenario_stress` 가 `prov.perf_label`(고정 비중 재생) 을 단다. 렌더러 `CheckResults.tsx::Drawdown`. E2E: `.pg-model-type` "역사 리플레이" · `.pg-side .pg-chart` 보임.
- 공용 부품 `frontend/src/shared/ui/perf/`(②에서 shared 로): `PerfCurve`(직접 SVG · 증거 띠 · 읽는 줄 · 키보드) · `YearTable`·`MonthGrid`·`DrawdownEpisodes`·`QuestionStrip`·`PerfTableView` · `perfView.ts`(`PerfView` · `PerfUnit = "x" | "krw"`). FSD: `shared` 는 `shared` 만 import — entities 타입을 쓰는 매퍼는 widgets 에.
- 서버 순수 함수 `src/engine/quant_metrics.py::period_returns`·`drawdown_episodes` — `run_full`·불러오기·전략 묶음이 쓴다.

## 3. 설계

### 3.1 서버 — 순수 모듈 `src/engine/perf_compare.py`

```
align_curves(dates_a, eq_a, dates_b, eq_b, *, base=1.0) -> {
  alignment: "date" | "index",
  x: [str],            # date: ISO 날짜 합집합 · index: "1일째", "2일째", …(서버가 글자까지)
  n, common, missing_a, missing_b,
  base: 1.0 | 100.0,
  a: [float|None], b: [float|None],   # 각자 첫 유효값을 base 로 · 한쪽만 있는 날은 그쪽 None(0 아님)
  diff_pp: [float|None],              # (b − a) / base × 100 — 둘 다 있을 때만
  note: str | None,                   # index 면 "두 실행의 기간이 달라 날짜가 아니라 시작부터 n일째로 맞췄어요 — 같은 날끼리가 아니에요."
}
```
- 판정: 공통 날짜 `common ≥ 2` 이고 `common ≥ 0.5 × min(len_a, len_b)` 면 **날짜 합집합**, 아니면 **순번**(`i = 0 … min(len)−1`).
- `yearly_diff(periods_a, periods_b) -> [{year, a_return_pct|None, b_return_pct|None, diff_pp|None, a_partial, b_partial}]` — 해 합집합 · `period_returns` 출력 둘을 받는다 · 연환산 없음.
- `metric_rows(stats_a, stats_b, spec) -> [{key, label, unit, a, b, diff}]` — `NODE_METRICS`(지금의 `_STAT_KO` 7 을 이 모듈로 옮김) · `PAGE_METRICS`(비교 화면의 10). 한쪽이 없으면 `diff: None`(0 아님).
- **같은 함수를 세 곳이 쓴다**: ⓐ 새 순수 엔드포인트 `POST /api/v1/perf/compare`(`src/api/perf_compare_routes.py` · prefix `/api/v1/perf` · DB·mock 무관 · 본문 `{a:{label, dates, equity, stats?, periods?}, b:{…}, base?: 1|100, metrics?: "page"|"node"}` → `{curves, yearly|null, rows|null}` · 길이 불일치·점 2개 미만은 422 + 사유) ⓑ 캔버스 비교 노드(서버 안에서 직접) ⓒ 현실성 탭(두 실행 뒤 ⓐ 를 부름). E2E 가 ⓐ 를 스텁하지 않으므로 **진짜 서버의 정렬**이 시험된다.
- 캔버스 비교 노드 `_compare`: 기존 `rows·differences` 그대로 + `view["compare"] = {curves(base 1), yearly, drawdowns:{a, b}(각 `drawdown_episodes` top 3), labels:{a: strategy_name, b: …}}`. 한쪽에 곡선이 없으면 `compare: None` + `compare_reason`.
- 스트레스 `historical_replay`: `equity_curve`(계산해 둔 `eq` 그대로 — 첫 점이 1+r₀ 라 "첫날 대비"로 읽힘) · `benchmark_curve`(`beq`) · `drawdowns = drawdown_episodes(dates, eq, top=3)` 추가. 기존 키는 그대로.
- `/macro` 전략 `_curve_summary`: `drawdown_pct`(점마다 고점 대비 % · ≤ 0) · `dates_note = "달 라벨은 오늘부터 30일씩 거슬러 센 어림이에요 — 실제 달과 한두 달 어긋날 수 있어요."`. 해마다·낙폭 사건은 **만들지 않는다**(날짜가 어림이라 며칠·몇 달을 셀 수 없다).
- 현실성: 서버 변경 없음.

### 3.2 부품 (`frontend/src/shared/ui/perf/`)

- `perfGeo.ts`(새): `PerfCurve` 의 `textW·day·days·pickIndexes·argExt·linePath·areaPath` 와 상수(`L_MIN·R_MIN·TOP·STRIP_H·XLAB_H·GAP`)를 옮겨 export. **동작 불변** — 기존 E2E 30(`canvas-perf-grammar` 12 · `canvas-perf-sheet` 8 · `backtest-results-perf` 10)이 지킨다.
- `perfView.ts`: `PerfUnit = "x" | "krw" | "base100"`(`fmtValue` base100 → 소수 1자리 "131.2" · 축 눈금 정수) · `PerfView.benchDrawdown?: PerfPoint[] | null` · `PerfView.note?: string | null` · 새 `PerfCompareView` + `compareViewOf(resp, meta)`(구조 타입만) · `perfViewOfStress(r, prov)`.

```
PerfCompareView {
  unit: PerfUnit; x: string[]; alignment: "date"|"index"; note: string|null;
  a: { label: string; values: PerfPoint[] }; b: { label: string; values: PerfPoint[] };
  diffPp: PerfPoint[]; practice: boolean|null;            # 한쪽이라도 연습용이면 true · 둘 다 모르면 null
  perfLabelA: PerfLabelValue|null; perfLabelB: PerfLabelValue|null;
  missingA: number; missingB: number; question: string;
  yearly: YearDiffRow[]|null; drawdowns: { a: DdEpisode[]|null; b: DdEpisode[]|null }|null;
}
```

- `PerfCompare.tsx`(새 · 직접 SVG · `perfGeo` 공용):

```
┌ A ──────── B ┐  ← 범례 .pf-legend: ● A 라벨(잉크) · ● B 라벨(--mc-c-1) · ▬ 차이 = B − A
│        ╱──── B ×1.21     ← 끝값 라벨 .pf-endlabel--a/--b (겹치면 안내선)
│   ╱╲╱╱       A ×1.12
│──────────── base(1 또는 100) 기준선
├ 차이(B − A, %p) ─────────┤  ← .pf-diff-area--up(빨강 12%)/--down(파랑 12%) + .pf-diff-line · 0 선
│ ▁▂▃▅▃▂  ▔▔▂▃
├ 증거 띠 ────────────────┤  ← .pf-strip-practice(한쪽이라도 연습용) · index 면 .pf-strip-index(점선)
2023-01-02         2023-06-30         2023-12-29     ← 폭이 모자라면 둘
읽는 줄 .pf-read: 2023-12-29 · A 1.12 (+12.0%) · B 1.21 (+21.0%) · 차이 +9.0%p   ← .pf-read-diff
띠 범례 .pf-strip-legend: 연습용 데이터 · "시작부터 n일째" 안내(.pf-strip-legend-align) · 한쪽만 있는 날 n일
▸ 표로 보기 (.pf-cmp-table: x · A · B · 차이)
```
  키보드 ←→(Shift ×10) Home End · `focus?: "a"|"b"|"both"`(`.pf-cmp--focus-a` 가 B 선·점을 0.25 로) · `[title]` 0 · 움직임 0 · `role="group"` aria-label.
- `CompareYearTable.tsx`(새): 해 · A · B · 차이(%p) · 일부 해 `.pf-partial` · 값 없으면 "주지 않았어요".
- `PerfCurve.tsx`: `benchDrawdown` → 낙폭 패널에 회색 선 `.pf-dd-bench`(범례 "벤치마크 낙폭") · `note` → `.pf-strip-legend-note` · base100 서식.
- CSS: `.pf-line-a{stroke:var(--pf-ink)}` · `.pf-line-b{stroke:var(--mc-c-1)}` · `.pf-diff-area--up/--down` · `.pf-diff-line` · `.pf-dd-bench` · `.pf-strip-index` · `.pf-cmp--focus-*` · `.pf-key--a/--b/--diff`. 새 토큰 0(`--mc-c-1` 은 범주색 1 · 라이트/다크 검증기 통과 기록).
- `frontend/src/entities/perf/api.ts`(새): `perfApi.compare(body)` → `postJson("/api/v1/perf/compare")`.

### 3.3 화면

- **비교 화면**: 답 문장·`.brun-cmp-labels`·지표 표(`.brun-cmp` · 차이 열 `td[3]`)·설정 표(`.brun-cmp-diff`)·`.brun-select`·카드 제목 "자산곡선 (시작 = 100)" 은 **그대로**(계약). B 를 고르면 `perfApi.compare({a:{label, dates: equity_dates, equity: equity_curve, stats: statistics, periods: perf?.periods}, b:…, base:100, metrics:"page"})` 한 번. 그 카드 안은 `PerfCompare`(unit base100) + 서버 `note` + `CompareYearTable` + 낙폭 사건 두 열(`DrawdownEpisodes` ×2 · 각 실행 `perf.drawdowns` — 없으면 "주지 않았어요"). 답의 차이 셋과 지표 표의 차이는 **서버 `rows`** 로(값이 없으면 `rows[].a/b` 로 어느 쪽이 없는지 — 기존 문장 그대로). 설정 표는 문자열 비교라 그대로. 이 파일의 recharts import 0.

```
답: B 는 A 와 이만큼 달라요 — 총수익률 +12.6%p · 최대 낙폭 -3.8%p · 샤프 지수 +0.41   (서버 rows)
[자산곡선 (시작 = 100)] PerfCompare(base100) · 정렬 글 · 해마다 차이 표 · 낙폭 사건 A | B
[지표 차이] 표 10행 (서버 rows)      [설정 차이] 그대로
```
- **캔버스 비교 노드**: `.pg-cmp-warn` · `.pg-cmp`(7행) 위에 `PerfCompare`(unit x) + 해마다 차이 + 낙폭 사건. `compare` 가 없으면 `.pg-note` 에 `compare_reason`.
- **현실성 탭** `GapChart`: 두 실행이 끝나면 `perfApi.compare({a:{label:"이상", dates, equity: portfolio_equity}, b:{label:"현실", …}, base:1})` → `.rl-chart[data-days = curves.n]` 안에 `PerfCompare`(focus = 기존 Segmented) · `.rl-missing` 은 `missing_b`("현실 쪽에 없는 날 n일") · `missing_a`("이상 쪽에 없는 날 n일") · `.rl-legend` 는 부품 범례로(이상 · 현실 · 차이 = 현실 − 이상). 맞추는 중/실패는 그 절 안 `role=alert` + 다시 시도. `joinByDate` 삭제. 답 문장·폭포·카드·용량 절은 그대로.
- **/macro 모달**: `PerfCurve`(unit base100 · `dates = curve[].t` · `equity = curve[].v` · `drawdown = perf.drawdown_pct` · bench null · `note = perf.dates_note` · practice = `perf_label.data_real`) + `.sm-perf-label`·`.sm-perf-stats` 그대로. `.sm-note` "점선은 처음 값(100)" 은 부품 범례 "(처음을 100으로)" 가 대신한다. 이 파일의 recharts import 0(`DrillDownModal` 등은 범위 밖).
- **스트레스 과거 모드**: `Drawdown` → `PerfCurve(perfViewOfStress)`(unit x · bench 회색 · `drawdown = portfolio_dd` · `benchDrawdown = benchmark_dd` · practice = prov) + `DrawdownEpisodes`. KV 행·`.pg-model-type`·`.pg-chart` 보임 계약 그대로. 이 파일의 recharts import 0.

### 3.4 색·접근성·글
- A = 잉크 · B = `--mc-c-1`(범주색 · 직접 라벨 필수) · 차이 = 등락 두 팔(`--pf-up/--pf-down` 12% + 선은 잉크) · 벤치마크·벤치마크 낙폭 = 회색. 색만으로 말하지 않는다(범례 글 · 읽는 줄).
- 해요체 · 가운뎃점 메타 문자열 0 · `title=` 0 · 금지어 6 전수(기존 시험) · "낫다·우위" 를 말하지 않는다(차이만).
- 4종 분리: 비교 화면 A/B 라벨 그대로 · 현실성 두 실행의 `perf_label` 은 답 절에 그대로 · 모달·스트레스 라벨 그대로.

## 4. 검증

- 서버 `tests/test_perf_compare.py`(빨강 먼저): 날짜 합집합·null 보존·missing 수 · 순번 판정 짝(common ≥ 반 → date · 미만 → index + note) · base 1/100 · diff 부호·None · yearly 합집합 + partial · metric rows None · 엔드포인트 200 모양·422 · 라우트 등록(`flat_routes`) · 노드 `compare` 유무 짝 · 스트레스 세 키 · 매크로 두 키. 변이: 합집합 → 교집합 · base 무시 · diff 부호 뒤집기 — 각 죽음.
- E2E 새 `e2e/perf-compare.spec.ts`(실행 둘은 스텁 · `/perf/compare` 는 진짜 서버): (a) 두 선·차이 선 · 읽는 줄 · ArrowLeft (b) 같은 날짜 → 정렬 글 0 · B 에서 2일 빼면 n = 합집합 + 한쪽만 있는 날 글 · B 날짜를 통째로 바꾸면 "시작부터" 글(짝) (c) 해마다 차이 행 = 해 합집합 (d) 지표 차이 = 서버 `rows[].diff` · B 값 삭제 → "비교할 수 없어요" (e) recharts 0 · `[title]` 0 (f) 라이트·다크 AA (g) 390 가로 넘침 0.
- 기존 스펙: 비교 계약 셋 그대로 · `portfolio-graph.spec` 비교 블록에 `.pg-side .pf-cmp` · 스트레스에 `.pf-curve`·`.pf-dd-bench` · `realism.spec` 기존 그대로 + `.rl-chart .pf-cmp`·`.pf-read-diff` · `macro-cards.spec` 전략 창에 `.pf-curve`·`.pf-dd-area`·"어림".
- 변이(한 빌드): 정렬 index 강제 · 차이 띠 안 그림 · 벤치 낙폭 안 그림 · 매크로 낙폭 ×100 · 현실성 `data-days` 를 이상 길이로.
- 측정: 첫 화면 JS 전/후 `/backtest/runs/x/compare` · `/admin/live-trading` · 모달 조각 · 캔버스 묶음(recharts 가 남음을 적는다) · 엔진 수 대조(서버 `rows[].diff` = 옛 `vb − va` · 현실성 `curves.n` = 옛 합집합 수).
- 눈으로: 라이트·다크·390 스크린샷(다섯 자리) → §5.1.

## 5. 하지 않는 것

성과가 아닌 recharts(시세·수익률곡선·프론티어·노출 추이·MacroW2) · `/macro` 전략의 실제 달력 날짜(데이터 계층) · 현실성 서버 통합 엔드포인트 · 비교 화면 설정 표의 의미 변경 · 새 지표·판단·정책 · 새 색 토큰 · 기존 CSS 클래스 이름 변경 · `lazyChart` 로 성과 부품 지연.

## 5.1 실물 대 와이어프레임 (구현 뒤 · 2026-11-09)

라이트·다크·390 스크린샷(비교 화면 · 현실성 탭 · /macro 전략 창 — 실제 실행 둘(2023-01~12 · 2023-03~2024-02)과 현실성 픽스처)을 §3 과 견줘 바꾼 것.

1. **역할 변수는 `:root` 에** — `--pf-*` 가 `.pg-theme`·`.rs` 에만 있어 캔버스 밖(현실성 탭 `.rl` · 전략 창 `.sm-modal`)에서는 선의 `stroke` 가
   비어 그려지지 않았다(커밋 ④의 현실성 틈 그림 — E2E 는 요소 수만 세어 못 봤다 · 커밋 ⑤에서 고침). `:root` 에 `--tx-*` 로 매핑하고 캔버스는
   제 `--pg-*` 로 덮는다.
2. **두 패널 눈금 충돌** — 위 패널 아래 눈금("×0.87")과 차이 패널 위 눈금("+6%p")이 8px 간격에서 겹쳤다 → `PerfCompare` 의 패널 간격 20px.
3. **해마다 차이의 "(일부)"** — 어느 쪽이 일부인지 없었다 → "(B 일부)" · "(둘 다 일부)".
4. **지표 차이 "-0%p"** — 최대낙폭 14.9 대 14.9 의 차이 −0.004 가 "-0%p" 로 보였다 → 보이는 자리에서 0 이면 "같아요"(답 문장도).
5. **390 의 낙폭 사건 표** — "되찾기까지" 가 네 줄로 꺾였다 → 칸 nowrap + 가로 스크롤 상자(`.pf-eps-wrap`) · 두 열 격자 칸 `min-width: 0`
   (캔버스·결과 화면의 같은 표에도 적용).
6. **/macro 전략 창의 글 규칙** — 그 화면은 보이는 em-dash 0 · 서버 글은 `data-server` 로 뺀다. `dates_note` 는 `data-server`, PerfCurve 의
   "벤치마크 없음 — …" 줄은 `benchNoneText={null}` 로 뺐다(비교 지수라는 개념이 없는 화면). 보유 도넛(recharts)은 범위 밖이라 그대로.
7. **비교 화면 읽는 줄의 기본 자리** — 마지막 날인데 A 가 먼저 끝나면 A 는 "—" 로 보인다(합집합의 정직한 결과 · 바꾸지 않았다 — ← 로 옮기면 값).
8. **캔버스 두 노드의 스크린샷** — 임시 스펙으로 문서 불러오기·팔레트 흐름을 재현하지 못해 찍지 못했다. 같은 부품이고 `portfolio-graph.spec`
   의 단언(그림·차이 0 · 낙폭 축 글자 = 서버 % · 벤치마크 낙폭 선 · 사건 행 수)으로 갈음한다. 다크 대비는 캔버스 성과 스펙이 같은 패널을 잰다.
9. **현실성 탭** — §3.3 대로: 서버 변경 없음 · `.rl-legend` 는 부품 범례로 · `data-days` 는 서버 합집합 수. AA 시험은 두 번째 누름이 결과를
   내렸다 다시 그리는 사이에 재던 것(이전부터의 간헐)이라 단추 글·틈 그림을 기다린 뒤 재도록 했다.

그대로인 것: §3.1 서버 모듈·엔드포인트 모양 · 비교 화면·노드·탭·창·스트레스의 읽는 순서 · 카드 제목·표 계약 · 새 토큰 0 · recharts 는 네 화면의
성과 그림에서 0(보유 도넛·프론티어·노출 추이·수익률곡선은 범위 밖).

## 6. 단계 (커밋 단위)

① 설계·계획 문서 ② 서버(TDD) ③ 부품 + 비교 화면 + 비교 노드 ④ 현실성 탭 ⑤ 매크로 모달 + 스트레스 노드 ⑥ 측정 · 전체 E2E · `make all` · HISTORY · §5.1.
