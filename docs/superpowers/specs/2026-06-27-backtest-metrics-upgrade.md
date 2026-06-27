# 백테스트 성과지표 대폭 확장 + 거래로그/데이터소스 정직화 — 설계·구현 스펙

- 날짜: 2026-06-27
- 브랜치: `claude/keen-thompson-bdk3e8` (이 브랜치 외 푸시 금지, PR 명시 요청 시만)
- 상태: 승인됨("어 그렇게 구현해") — 구현 진행. ★이 문서는 강제압축 대비 resume 앵커★
- 커밋 트레일러(필수):
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NSAuFjWec6ZwXi9wq7SbrA
  ```
- 검증: 백엔드 `KIS_USE_MOCK=1 python -m pytest tests/ -q` + `ruff check`; 프론트 `cd frontend && npx tsc --noEmit && npx next build`. 현재 베이스라인 **641 passed / 10 skipped**. 출처: QuantStats(ranaroussi/quantstats), empyrical(quantopian).

## 사용자 요청 (원문 의도)
백테스트 실행 후 ① 성과지표가 너무 부족, ② 값이 빈 공백("—") 보임, ③ 매크로(PAA) 백테스트에 MOCK_DATA 배지(실데이터여야 함), ④ GitHub 공신력 라이브러리(QuantStats) 참고해 개선. "깊이 생각하고 구현."

## 진단 (원인 — 파일:라인)
1. **지표 부족(14종)** — `src/kis_backtest_engine.py` `_compute_statistics()` (≈1544–1609)가 반환: total_return, total_return_pct, cagr, sharpe_ratio, sortino_ratio, calmar_ratio, max_drawdown(_pct), num_trades, win_rate, profit_factor, avg_trade_return, total_commission, total_slippage. 벤치마크는 `_compute_benchmark()`(≈1321)에서 beta/alpha/excess.
2. **매크로 엔진 지표** — `src/engine/strategy_backtest_map.py` `_full_stats(vals, port)` (≈129–159) 월간 기반으로 같은 12종 산출. `num_trades=월수`. `run_tactical_backtest()`(≈158–192)가 `trades: []`(개별 체결 없음) 반환.
3. **거래로그 공백** — 백엔드 trades는 **매수/매도 개별 leg**(`Trade` dataclass, `_trade_to_dict` ≈1431, append 지점 765/889/908/1135/1197/1247). 프론트 `TradeLog`(`frontend/src/components/backtest/TerminalBacktester.tsx` ≈700)는 **라운드트립** 필드 기대: `corp_name|stock_code, entry_date, exit_date, entry_price, exit_price, return_pct`. 불일치 → 전부 "—". 프론트 타입 `BacktestTrade` = `frontend/src/lib/screenerApi.ts:877`.
4. **MOCK_DATA** — 매크로 엔진 `_ds()`(strategy_backtest_map ≈116–118) = `{"fundamentals":"mock","market_data":"KIS" if real else "mock","fully_real": bool(KIS_APP_KEY)}` — **실제 사용한 ETF 시계열의 실/mock 여부와 무관**. 조건식 경로는 정직한 `_detect_data_source`(kis_backtest_engine) 사용 → 둘 불일치. 프론트 배지: TerminalBacktester ≈465(prov 배너), ≈600–601(REAL_DATA/MOCK_DATA), 거래로그 게이트 ≈586 `trades?.length>0`.

## 프론트 표시 위치 (TerminalBacktester.tsx)
- `const st = result?.backtest?.statistics;` (≈281)
- 헤드라인 6카드 `.tbt-stats.tbt-stats-6` (≈490–514): Total Return/CAGR/Sharpe/Sortino/Calmar/Max DD
- 보조 바 (≈521): 거래수/승률/PF/평균손익/수수료/슬리피지
- 벤치마크 카드, equity/drawdown/monthly, Trade Log(≈586–592), CONSTITUENTS+배지(≈600)
- `fmt(v, unit, dp)` / `posColor()` 헬퍼 사용. CSS: `tbt-stat`, `tbt-stats-6`, `trisk-table` 등 globals.css.

## 구현 계획

### A. 공용 지표 모듈 `src/engine/quant_metrics.py` (신규) — ★핵심★
period-agnostic 함수:
```
compute_metrics(returns: list[float]|pd.Series, equity: list[float]|pd.Series,
                periods_per_year: int, trades_pnl: list[float]|None=None,
                benchmark_returns=None, risk_free=0.035) -> dict
```
- daily 경로 = periods_per_year 252, 매크로 = 12. equity로 DD계열, returns로 분포/위험.
- 산출(QuantStats 명칭, 기존 키 유지 + 신규 추가):
  - 위험: `volatility_pct`(=std*sqrt(ppy)*100), `downside_deviation_pct`, `var_pct`(일/월 95% = quantile 0.05*100), `cvar_pct`(≤VaR 평균*100), `ulcer_index`(sqrt(mean(dd%^2))), `max_drawdown_days`(최장 수중 구간), `avg_drawdown_pct`
  - 위험조정: `omega`(sum(+r)/|sum(-r)|), `recovery_factor`(total_return/|maxDD|), `gain_to_pain`(sum(r)/|sum(-r)|), `tail_ratio`(|q95/q05|)  (+기존 sharpe/sortino/calmar)
  - 분포: `skew`, `kurtosis`, `best_period_pct`, `worst_period_pct`
  - 거래(trades_pnl 있을 때): `payoff_ratio`(avg_win/avg_loss), `expectancy_pct`, `avg_win`/`avg_loss`, `kelly_pct`  (+기존 win_rate/profit_factor)
  - 벤치마크(benchmark_returns 있을 때): `information_ratio`((annRet-annBench)/trackingErr)
- 순수함수, numpy/pandas만. 0분모·빈입력 방어(None/0). NaN→0/None.
- **TDD**: `tests/test_quant_metrics.py` — 알려진 시계열로 vol/var/cvar/ulcer/omega/tail/skew/recovery/payoff 공식 검증 + 빈입력 안전.

### A2. 양 경로 배선
- `kis_backtest_engine._compute_statistics`: 기존 dict에 `compute_metrics(returns, equity, 252, trades_pnl=[t.pnl for sell t], benchmark_returns=...)` 결과 병합(기존 키 우선, 신규 추가).
- `strategy_backtest_map._full_stats`: 동일하게 `compute_metrics(port, vals→equity, 12, ...)` 병합.
- 회귀: 기존 키/값 불변(테스트 52거래 -8.1% 등). 신규 키만 추가.

### B. 프론트 — 전체 지표 테이블
- TerminalBacktester: 헤드라인 6카드 유지 + 아래 **QuantStats 티어시트식 표**(그룹: 수익/위험/위험조정/거래/벤치마크). `trisk-table` 또는 `tbt-stat` 그리드 재사용, 디자인 토큰 유지.
- 신규 키 옵셔널 렌더(없으면 "—"). `screenerApi.ts` `BacktestStatistics` 타입에 신규 필드 추가(옵셔널).
- 검증: tsc 0, next build.

### C. 거래로그 라운드트립
- 백엔드: 매수→매도 매칭으로 라운드트립 dict 생성 `{stock_code, corp_name, entry_date, exit_date, entry_price, exit_price, return_pct, pnl}`. `_trade_to_dict`/`run()`의 `trade_dicts`(≈1431) 또는 신규 `_round_trips(self.trades)`. 엔진모드(trades=[])는 그대로 빈 배열.
- 프론트: 엔진모드(trades 0 + 월간)면 "월간 리밸런싱 — 개별 체결 없음" 안내(현재는 섹션 숨김). 조건모드는 채워진 표.
- TDD: 라운드트립 매칭 단위테스트(매수2+매도2 → 라운드트립2, 수익률 부호).

### D. 데이터소스 정직화
- 매크로 엔진: `backtest_strategy`/`monthly_closes`가 실제 실데이터를 썼는지 신호를 받아 `data_source.fully_real`을 **실 사용 기준**으로. 최소: ETF 시계열이 mock 폴백이면 `fully_real=False`, 실DB/실KIS면 True. (키 유무가 아님)
- 검증: mock 모드 → MOCK_DATA, 실데이터 경로 → REAL_DATA.

## 구현 순서(단계 커밋)
1. A: `quant_metrics.py` + `test_quant_metrics.py` (TDD) → 커밋.
2. A2: 양 경로 배선 + 회귀 → 커밋.
3. C: 라운드트립(백+프론트) → 커밋.
4. D: 데이터소스 정직화 → 커밋.
5. B: 프론트 지표 테이블 + 타입 → 커밋.
6. 전체 검증(pytest/ruff/tsc/build) → 푸시.

## 주의/불변식
- 기존 stats 키·값 회귀 불변(하위호환). 신규 키만 추가.
- 샌드박스: 키/네트워크 없음 → 지표 공식·라운드트립·data_source 분기는 단위/픽스처로 검증, 실데이터는 GCP.
- 재배포 후 프론트는 하드새로고침 필요(번들 캐시).
