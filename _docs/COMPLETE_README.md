# Project Alpha — 백테스터 젠포트식 전면 개편 (완성본)

백테스터 탭을 **매수 조건 / 매도 조건 / 매매 대상**으로 재구성하고, 백엔드를 조건식 진입/청산 + granular 유니버스로 확장.
이후 완성도 작업(관심그룹 종목코드 · 실제 시총 tier · 전체 유니버스 일별 평가 · 펀더멘털 조건 · **횡단면 순위/비율** · 관리/감리 제외 seam)까지 반영했다.
프론트 `tsc --noEmit`(strict) 0 에러, 백엔드 py-compile + 단위 테스트 통과.

`frontend/` 와 `src/` 를 레포 루트에 반영(EDITED 덮어쓰기, NEW 추가)하고 `main_api.py` 에 카운트 라우터를 등록하면 끝.
설계·배경은 `_docs/`(PROJECT_HANDOFF · INTEGRATION · APPLY · BACKEND_EXTENSION), **젠포트 전환 갭은 `_docs/GENPORT_GAP.md`** 참고.

## 적용

1. 표대로 파일 반영. 2. `main_api.py`:
   ```python
   from src.api.screener_universe_count import router as universe_count_router
   app.include_router(universe_count_router)
   ```
3. 확인: `cd frontend && npx tsc --noEmit`, 백엔드 `python -m py_compile`. 서버 기동 후 `/backtest`.

## 파일 맵

| 상태 | 경로 | 역할 |
|---|---|---|
| EDITED | `frontend/src/app/backtest/page.tsx` | 탭/빌더/비교 제거 → TerminalBacktester 단독 |
| EDITED | `frontend/src/components/backtest/TerminalBacktester.tsx` | 패널형, 3탭, state→BacktestStrategy, run 어댑터(조건식·granular·전체평가·펀더멘털·max_positions 전송) |
| EDITED | `frontend/src/lib/screenerApi.ts` | screenToBacktest 요청 타입 확장 |
| NEW | `frontend/src/components/backtest/kit.tsx` | 부품 + Toggle + SummaryRail |
| NEW | `frontend/src/components/backtest/FactorPickerModal.tsx` | 팩터 선택 창 STEP1→STEP2 |
| NEW | `frontend/src/components/backtest/ConditionFormulaEditor.tsx` | 조건식 리스트 + 모달 + 자연어 |
| NEW | `frontend/src/components/backtest/panels/BuyConditionPanel.tsx` | 매수(빨강) + 펀더멘털 토글 |
| NEW | `frontend/src/components/backtest/panels/SellConditionPanel.tsx` | 매도(파랑) |
| NEW | `frontend/src/components/backtest/panels/UniversePanel.tsx` | 매매대상 + 실시간 종목 수 + 실제 업종 + 관심그룹 |
| NEW | `frontend/src/lib/backtest/strategy.ts` | BacktestStrategy 상태 + buildSummary |
| NEW | `frontend/src/lib/backtest/factorCatalog.ts` · `factorFunctions.ts` · `genportFactors.json` | 팩터 카탈로그·18함수·344팩터 |
| NEW | `frontend/src/lib/backtest/universeApi.ts` | universeCount + fetchSectors |
| EDITED | `src/api/screener_routes.py` | screen-to-backtest: 조건식·granular·전체평가(풀 ≤2000)·펀더멘털 분기 |
| EDITED | `src/kis_backtest_engine.py` | 봉 루프 전 `prepare_panel(ohlcv_map)` 호출 seam(횡단면 지원) |
| NEW | `src/api/screener_universe_count.py` | POST /universe-count (실데이터) |
| NEW | `src/engine/universe_select.py` | granular 유니버스 선택기 + 실제 시총 tier + 관리/감리 seam |
| NEW | `src/kis_strategies/condition_strategy.py` | 조건식 진입/청산 + 횡단면 순위/비율 + (옵트인) 펀더멘털 |

## 동작하는 것

- **UI**: 3탭, 팩터 선택 창, 조건식 자연어, 매매대상 실시간 종목 수.
- **유니버스**: 실제 업종 + **실제 시총 6단계 tier** + ETF + **관심그룹(실종목)**, 관리/감리 제외(데이터 연동 시).
- **진입/청산**: 조건식(가격·거래량·기술) 봉별 평가 + **횡단면 순위/비율 랭킹 선택** + 전체 유니버스 일별 평가(풀 ≤2000, max_positions 보유 한도) + 손절·익절·보유일.
- **펀더멘털 조건(옵트인)**: 매수 섹션 토글(기본 OFF). PER/PBR/ROE/시총/EPS/매출·이익/부채비율/PSR/PCR/PEG/매출성장률을 스냅샷으로 평가.
- **결과**: 수익률곡선 + KOSPI 벤치마크 + 초과수익/α/β, MDD, 월별, 매매내역, CSV.

## 완성도 작업 — 반영 내역

1. **관심그룹 종목코드**: `listWatchlists()` 실종목 → 카운트·백테스트에 `{mode,tickers}` 전송.
2. **실제 시총 tier**: `FundamentalsStore.market_cap` 으로 6단계 산출(임계값 `universe_select.CAP_TIER_THRESHOLDS` 튜닝). 시총 없으면 프리셋 proxy.
3. **전체 유니버스 일별 평가**: `full_universe_eval` + `universe_eval_cap`(≤2000) + `max_positions`.
4. **펀더멘털 조건(옵트인)**: `ConditionStrategy(allow_snapshot_fundamentals)` + `_FUND_TOKENS`. 기본 OFF(스냅샷·look-ahead).
5. **횡단면 순위/비율**: 엔진 `prepare_panel` seam → 봉마다 전 종목 랭킹/백분위 패널 사전계산 → `순위/비율` 조건 평가.
6. **관리/감리 제외**: `universe_select._status_codes()` seam — `stock_master.MANAGED_CODES/SUPERVISED_CODES` 정의 시 자동 활성.

## 범위 / 한계 (남은 — 상세는 `_docs/GENPORT_GAP.md`)

- **펀더멘털 PIT 부재(데이터)**: 옵트인 평가는 현재 스냅샷 상수라 look-ahead. 정확한 PIT는 역사적 재무 시계열 필요 → 엄밀하면 펀더멘털은 스크리닝으로 분리.
- **관리/감리 데이터 부재**: 제외 메커니즘 완성, 코드 목록만 없음(seam).
- **순위/비율 내부지표**: 현재 가격/거래량/거래대금 bare 토큰만 랭킹. 파생지표(예: 20일 수익률) 순위는 봉별 파생팩터 계산 + 중첩함수 모델 필요.
- **전체시장(>2000) 일별 평가**: 성능 가드 상한 2000.
- **엔진/어댑터 미연결**: 리밸런싱 주기 · 마켓타이밍 · 분할/돌파/TWAP 체결 · ATR 비중 · 트레일링 스탑 · 2차 정렬 · 13종 체결가(어댑터). (GENPORT_GAP 참고)
- **제거된 기존 기능**: 저장·불러오기/전략 템플릿(빌더는 `/builder` 유지).

## 검증 요약

- 프론트: 통합 `tsc --noEmit` strict + noUnusedLocals **0 에러**.
- 백엔드: 변경/신규 5파일 `py_compile` 통과.
- 단위 테스트: 조건식 전략(매수/매도/평가불가/펀더멘털 게이트), **횡단면 순위·비율 선택(3종목)**, 유니버스 선택기(실제 시총 tier·업종·ETF·관심그룹·관리/감리) 모두 통과.
