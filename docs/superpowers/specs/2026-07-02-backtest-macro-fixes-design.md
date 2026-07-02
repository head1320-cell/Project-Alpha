# 백테스터 4수정 + 매크로 국면 재구축 — 설계 스펙

- 날짜: 2026-07-02
- 브랜치: `claude/keen-thompson-bdk3e8` (이 브랜치 외 푸시 금지, PR 명시 요청 시만)
- 상태: 승인됨("네. 만약 작업하다가 우월하고 객관적인 방식을 찾으면 수정해서 진행줘")
- 커밋 트레일러(필수):
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NSAuFjWec6ZwXi9wq7SbrA
  ```
- 검증: 백엔드 `KIS_USE_MOCK=1 python -m pytest tests/ -q`(베이스라인 **668 passed/10 skipped**) + `ruff check`; 프론트 `npx tsc --noEmit && npx next build`.

## 사용자 요청
① 백테스트에서 전종목 선택했는데 로딩이 "200/200 종목" ② 승률·손익비·거래·평균손익이 0으로 나옴(+366%인데) ③ Constituents가 종목명 칩뿐 — 진입/청산일·가격·손익·보유기간 등 구체화 ④ 매크로 "Stagflation" 국면 타당성 의심 — 공신력 있는 방법론으로 재검토, 한국+미국 국면 표시, 잘못 입력된 값 수정. "깊이 생각해서 완성도 있게."

## 진단 (파일:라인)

| 증상 | 원인 |
|---|---|
| 전종목→200 | `TerminalBacktester.tsx:115` `universe_eval_cap: 200` 하드코딩. 백엔드는 4,000 지원(`screener_routes.py:1347,1412-1413`), 병렬 OHLCV(10워커, `kis_backtest_engine.py:372-383`)+SSE 진행률 완비. |
| 거래통계 0 | 매도 미발동 전략은 포지션이 기간 끝까지 보유됨 → 자산곡선은 평가액 반영(+366%)하나 통계는 청산 거래만 집계(`_compute_statistics` sell legs). **기간종료 청산 로직 부재.** |
| Constituents 부실 | 백엔드가 `symbol_results`+`round_trips` 반환하는데 프론트는 `screened_tickers.slice(0,12)` 칩만 렌더. |
| Stagflation 고정 | **버그 1**: `macro_collector.py:117` z-score가 원시 시리즈에 계산되는데 CPI는 **지수 레벨**(US ~330, KR ~113) → 항상 우상향 → 물가 축 구조적 +1.5~2.0 (관측된 +1.78). **버그 2**: `:465` yoy가 지수에 대해 %가 아닌 점차(`v[-1]-v[-13]`). **방법론**: 성장 축이 실물 아닌 시장심리(KOSPI/T10Y2Y/VIX/DXY, `regime_analyzer.py:164-199`). **불일치**: 궤적(`macro_analytics.py:302-309`)은 다른 축 정의(INDPRO/GDP/고용)+다른 명칭(Disinflation vs Deflation). |

## 설계

### A. 기간종료 청산 (백엔드 엔진)
- `BacktestConfig += liquidate_at_end: bool = False` (엔진 기본 OFF — 기존 단위테스트 회귀 불변).
- `run()` 메인 루프 종료 후: 잔여 포지션 전량을 마지막 거래일 종가(sell_fill_type 적용)로 `_execute_sell` — reason `"기간종료 청산"`, 수수료·슬리피지 반영(정직한 청산 비용).
- `run_backtest()`/`ScreenToBacktestRequest += liquidate_at_end: bool = True` (**API 기본 ON** — 사용자 관측 동작 수정).
- stats에 `eod_liquidated`(청산 종목 수) 추가 → 프론트 보조바에 "기간종료 청산 N종목" 표기.
- TDD: 매수만 하는 전략 → liquidate OFF: num_trades 0 / ON: num_trades==보유수, 승률·PF 채워짐, equity는 청산비용만큼 미세 감소.

### B. 평가 상한 UI (프론트)
- `TerminalBacktester` 고급 옵션에 "평가 종목 상한" 셀렉트(500/1000/2000/4000·전체) — **기본 4000(전체)**. `universe_eval_cap: evalCap` 전송. 하드코딩 200 제거.
- 안내 문구: 첫 실행(미적재 종목)은 시세 수집으로 수 분 소요 — 진행률 표시, 2회차부터 DB 즉시.

### C. Constituents → 종목별 성과 테이블
- 백엔드 `_compute_symbol_results` 확장(라운드트립 기반): 기존 필드 유지 + `realized_pnl`, `avg_return_pct`, `avg_hold_days`, `contribution_pct`(총 실현손익 대비), `trades`, `win_rate`. 라운드트립 전수로 계산(응답 round_trips[:500] 캡과 무관).
- 프론트: CONSTITUENTS 칩 → 정렬 가능한 테이블(기여도 기본 내림차순): 종목(코드)/거래수/승률/실현손익/평균수익률/평균보유일/기여도. 20행 페이지(이전/다음). 행 클릭 → 해당 종목 라운드트립 상세(진입/청산일·가격·수량·수익률·보유일·사유) 인라인 펼침 — 데이터는 `round_trips` 클라이언트 필터(500캡 초과 시 "일부 표시" 주석).
- REAL/MOCK 배지 유지.

### D. 매크로 국면 재구축 (성장×물가 2×2 표준 관행 — Bridgewater 4국면/Fidelity 사이클류)
**우월-방식 결정(승인된 재량)**: 변환을 `macro_collector`(전 소비자 공유)가 아닌 **신규 축 모듈에서만** 수행 → 기존 차트/대시보드/다른 탭 영향 0, 변환·축 정의가 한 파일에 응집.

- **NEW `src/engine/regime_axes.py`** (순수함수, TDD):
  - `yoy_pct(values, lag=12)` — 지수→전년比 % 시계열. `zscore_last(vals, window=60)` — 시계열 z(표본 부족 시 None).
  - 축 정의(단일 진실 공급원):
    - `US_GROWTH = [(INDPRO, yoy, +, .35), (PAYEMS, yoy, +, .25), (UNRATE, level, −, .20), (GDPC1, yoy, +, .20)]`
    - `US_INFLATION = [(CPIAUCSL, yoy, +, .60), (T10YIE, level, +, .40)]`
    - `KR_GROWTH = [(KR_LEADING_CYCLE, level, +, .40), (KR_IP, yoy, +, .30), (KOSPI, yoy, +, .30)]`
    - `KR_INFLATION = [(KR_CPI, yoy, +, .70), (T10YIE, level, +, .30)]`
  - `compute_axis(series_map, axis_def, back=0)` — 시리즈 미가용 시 **가중치 재정규화**(허위값 금지), back=k개월 전 값(궤적용).
  - 사분면 명칭 통일: `quadrant(g, i)` → Goldilocks/Reflation/Stagflation/Deflation (전 모듈 공용).
- **macro_collector**: BOK 신규 2종 수집 추가 — `KR_LEADING_CYCLE`(경기선행지수 순환변동치, ECOS 901Y067) + `KR_IP`(산업생산지수, ECOS 901Y033). 코드 오류/미가용 시 기존 `_collect_one` 폴백(unavailable) → 축에서 자동 제외. yoy 필드 계산을 단위 인지형으로 수정(지수형: %변화, %형: 점차). ※ ECOS item 코드는 GCP 실호출로 검증 — 소스 패널에 시리즈별 real/mock 표시 유지.
- **regime_analyzer**: `_compute_growth_axis/_compute_inflation_axis`를 regime_axes 호출로 교체. `analyze(market="kr")` 파라미터화 → KR/US 각각의 RegimeState. `get_regime_state()`(KR)는 기존 시그니처 유지(트레이딩엔진 등 소비자 무영향), 신규 `get_regime_states() -> {"kr","us"}`.
- **macro_analytics.regime_trajectory**: 자체 `_GROWTH_DEF/_INFL_DEF` 제거 → regime_axes 공유(헤더와 궤적 일치). `_quadrant_of` → 공용 quadrant.
- **API**: `/api/v1/macro/regime` 응답에 `markets: {kr: {...}, us: {...}}` 추가(기존 최상위 필드는 KR 값 유지 — 하위호환).
- **프론트 콕핏 헤더**: 현재 단일 국면 카드 → **KR/US 두 카드**(국면·성장/물가 축·모드·신뢰도, 기존 디자인 토큰).
- 스트레스 지수·수익률곡선 분석은 방법론 타당 → 유지.
- TDD: 합성 시계열로 ① CPI 지수 연 3% 등속 상승 → 물가 z ≈ 0 (가속 시 +, 감속 시 −) ② 성장 지표 하락 시 growth<0 ③ 시리즈 결손 시 재정규화 ④ 사분면 명칭 4종.

## 구현 순서(단계 커밋)
1. A: 엔진 기간종료 청산 + eod_liquidated (TDD) → API 기본 ON.
2. C-백엔드: symbol_results 확장 (TDD).
3. B+C-프론트: 평가상한 셀렉트 + 종목별 성과 테이블(+substats 청산 표기).
4. D-1: regime_axes.py (TDD) + collector 신규 시리즈/yoy 수정.
5. D-2: analyzer KR/US + trajectory 공유 + API markets + 콕핏 두 카드.
6. 전체 검증(pytest/ruff/tsc/build + mock 라이브) → CLAUDE.md → 푸시.

## 정직한 한계
- 실제 국면 값·BOK 신규 시리즈 코드 검증은 GCP(실키)에서 — 샌드박스는 변환·축·분류 로직을 합성/mock으로 검증.
- 기간종료 청산 ON은 최종 자산이 청산비용만큼 미세 감소(정직) — 기존 결과와 수치 차이 발생은 의도된 수정.
- KR 성장 축은 BOK 신규 시리즈 실패 시 KOSPI YoY 중심으로 재정규화되어 계속 동작(허위 국면 대신 가용 데이터 기준).
