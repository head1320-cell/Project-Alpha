# 백테스터 전면 재작성 — 적용 가이드 (젠포트식)

백테스터 탭을 **전략 실행 / 전략 설계 / 전략 비교** → **매수 조건 / 매도 조건 / 매매 대상**으로 갈아엎었다.
통합 상태로 타입체크(`tsc --noEmit`, strict) 통과. 결과·차트(에쿼티커브·드로다운·월별 히트맵·트레이드로그·벤치마크·데이터출처·CSV 내보내기)는 **그대로 보존**.

## 파일 적용 (레포 경로 그대로 덮어쓰기/추가)

**덮어쓰기 (2개):**
- `frontend/src/app/backtest/page.tsx` — 탭 스위치/빌더/비교 제거 → `TerminalBacktester` 단독.
- `frontend/src/components/backtest/TerminalBacktester.tsx` — 좌측 설정 → 우리 패널, 상단 탭 → 매수/매도/매매대상, state → `BacktestStrategy`, run → 어댑터.

**추가 (보조 컴포넌트·데이터·백엔드):**
- `frontend/src/components/backtest/{kit.tsx, FactorPickerModal.tsx, ConditionFormulaEditor.tsx}`
- `frontend/src/components/backtest/panels/{BuyConditionPanel, SellConditionPanel, UniversePanel}.tsx`
- `frontend/src/lib/backtest/{strategy.ts, factorCatalog.ts, factorFunctions.ts, universeApi.ts, genportFactors.json}`
- `src/api/screener_universe_count.py` (유니버스 실시간 카운트 — 어댑터 연결 시 동작)

적용 후: `cd frontend && npx tsc --noEmit` 로 0 에러 확인. `tsconfig.json` 에 `resolveJsonModule: true` 필요(Next 기본 on). `lucide-react` 사용(기존에 이미 의존).

## 무엇이 바뀌었나

- **상단 탭**: `tbt-mode-switch`/`tbt-mode` 클래스 그대로 재사용해 비주얼 유지 — 라벨만 01 매수 조건 / 02 매도 조건 / 03 매매 대상.
- **좌측 설정 컬럼 전체 제거** → 탭별로 `BuyConditionPanel`(빨강) / `SellConditionPanel`(파랑) / `UniversePanel`(중립) 렌더. 단일 `BacktestStrategy` 객체로 구동.
- **실행 버튼**(`tbt-run`) → `run()` → `strategyToRun(strategy, handoff)` 어댑터로 `backtestBridgeApi.screenToBacktest(...)` 호출. 결과/에러/로딩 동일.
- **스크리너 핸드오프 칩** 유지(스크리너에서 넘어온 `filter_ast` 사용).

## ⚠ 중요 — 현재 한계(백엔드 후속 필요)

기존 `screenToBacktest` 엔진은 **유니버스 프리셋(coarse) + 스크리너 필터(filter_ast) + 청산룰(손절/익절/보유일)** 을 받는 구조다. 그래서 지금:

- **매수/매도 "조건식"(팩터 조건)** 은 UI·상태(`strategy.buy.conditions`/`sell.conditions`)에 **수집되지만 아직 백테스트 엔진엔 전달되지 않는다.** run 어댑터는 `filter_ast`(스크리너 핸드오프가 있으면 그것, 없으면 `largeCapFilter()`) + 청산룰(손절/익절/보유일) + `max_tickers` + 비용만 보낸다.
- **시총군·업종(granular)** 도 `capsToUniverse()` 로 coarse 프리셋(kospi200/kosdaq150)으로 축약돼 전달된다. 시총군/업종 정밀 반영은 안 됨.
- 즉 **UI는 젠포트식으로 완성**됐고 바로 돌아가지만, **조건식 기반 진입/청산과 granular 유니버스를 실제 백테스트에 반영하려면 백엔드 run 엔드포인트 확장**이 필요하다(유니버스 카운트 엔드포인트를 만든 것과 같은 방식 — `screenToBacktest` 가 buy/sell 조건 AST와 granular 유니버스를 받아 평가하도록).

## 제거된 기존 기능

전략 템플릿 드롭다운, "전략 설계에서 편집" 링크, 고급 옵션 패널(체결가/수수료/손익절 — 일부는 매도 패널로 흡수), 전략 저장/불러오기 UI, 관심그룹 관리 모달. (전략 설계 빌더는 `/builder` 라우트에서 계속 사용 가능. 저장/관심그룹은 새 패널에 재통합 가능.)

## 다음 단계 (권장 순서)

1. 백엔드 `screenToBacktest` 확장: buy/sell 조건 AST 평가(진입/청산 시그널) + granular 유니버스(시총군·업종·관심그룹). 조건 AST는 `genportFactors.json`의 `{토큰}`/함수 템플릿을 백엔드 팩터 계산에 매핑.
2. `screener_universe_count.py` ADAPTER 4곳 연결 → `UniversePanel` 실시간 종목 수 라이브.
3. 관심그룹 include/exclude에 실제 종목코드 연결.
