# 백테스터 재설계 — 통합 가이드

`tsc --noEmit` 통과(strict + noUnusedLocals). 인라인 스타일 + 너의 CSS 변수(`--text-primary`, `--border`, `--danger`, `--bg-section`, `--bs-border-radius`, `--bs-font-mono` …)로 짜서 Tailwind 설정과 무관하게 동작. 아이콘은 `lucide-react`.

## 파일 배치

| 이 파일 | → 넣을 경로 |
|---|---|
| `lib/genportFactors.json` | `frontend/src/lib/backtest/genportFactors.json` |
| `lib/factorCatalog.ts` | `frontend/src/lib/backtest/factorCatalog.ts` |
| `lib/factorFunctions.ts` | `frontend/src/lib/backtest/factorFunctions.ts` |
| `lib/strategy.ts` | `frontend/src/lib/backtest/strategy.ts` |
| `components/kit.tsx` | `frontend/src/components/backtest/kit.tsx` |
| `components/FactorPickerModal.tsx` | `frontend/src/components/backtest/FactorPickerModal.tsx` |
| `components/ConditionFormulaEditor.tsx` | `frontend/src/components/backtest/ConditionFormulaEditor.tsx` |
| `components/BacktesterRedesignDemo.tsx` | `frontend/src/components/backtest/BacktesterRedesignDemo.tsx` |
| `components/panels/BuyConditionPanel.tsx` | `frontend/src/components/backtest/panels/BuyConditionPanel.tsx` |
| `components/panels/SellConditionPanel.tsx` | `frontend/src/components/backtest/panels/SellConditionPanel.tsx` |
| `components/panels/UniversePanel.tsx` | `frontend/src/components/backtest/panels/UniversePanel.tsx` |
| `lib/universeApi.ts` | `frontend/src/lib/backtest/universeApi.ts` |
| `backend/screener_universe_count.py` | `src/api/screener_universe_count.py` |

`tsconfig.json` 에 `"resolveJsonModule": true` 가 있어야 함(Next 기본 on).

## 바로 보기

아무 페이지에서:
```tsx
import BacktesterRedesignDemo from "@/components/backtest/BacktesterRedesignDemo";
export default function Page() { return <BacktesterRedesignDemo />; }
```
매수 조건 섹션의 "조건식 추가 / 팩터·함수 선택" → STEP1·STEP2 모달 → 입력 시 조건이 리스트에 쌓이고, 우측 요약 레일이 실시간 반영. 우측 레일의 탭(매수·매도·대상)을 누르면 좌측 화면이 `BuyConditionPanel` / `SellConditionPanel` / `UniversePanel` 로 전환되고, 셋 다 같은 `strategy` 상태를 읽고 쓴다.

## 부품 (kit.tsx)

`Section`(카드+토글) · `SubToggle`(고급 하위토글) · `QuickStepper`(숫자+퀵칩) · `Segmented` · `Field`(라벨 행) · `Toggle` · `SummaryRail`(상시 요약).
색은 `tone="buy" | "sell" | "neutral"` 으로 주입(매수 빨강 / 매도 파랑 / 중립). `TONES` 를 `globals.css` 의 `--buy`/`--sell` 변수로 빼도 됨.

## TerminalBacktester 로 이식 (핵심)

지금 흩어진 `useState`(stopLoss·takeProfit·maxHoldDays·sellDividePct·buyDividePct·maxBuyPerDay…)를 `strategy.ts` 의 `BacktestStrategy` 객체 하나로 모으는 게 전부:

```tsx
const [strategy, setStrategy] = useState<BacktestStrategy>(initialStrategy);
```

- 각 섹션은 `strategy.buy`/`.sell`/`.universe` 의 필드를 읽고 쓴다.
- 우측 `<SummaryRail strategy={strategy} tab={tab} onTab={setTab} />` 는 `buildSummary()`(strategy.ts) 로 같은 상태를 읽어 자동 반영 — 켜진 옵션만 행으로 추가됨.
- 기존 백테스트 실행부는 `strategy` 를 기존 payload 모양으로 매핑하는 어댑터 한 겹만 두면 됨(스키마는 동일 개념).

## 팩터 데이터 메모

`genportFactors.json` = 가이드 v1.82 에서 추출한 344개. **카테고리는 가이드 표의 대분류 열을 위치 기반으로 복원**한 14개(종합·모멘텀·펀더멘탈·뉴지지표·가격·수급·성장·가치·기술지표·마켓타이밍·환율·금리·지수·기타) — 라벨·순서가 가이드와 일치. 대분류 라벨이 병합셀이라 **블록 경계의 일부 팩터는 인접 카테고리로 들어갈 수 있음**(예: 공매도→수급, 캔들→가격 정도만 수동 보정함). 팩터 이름·`{토큰}`(`expr`)은 가이드와 일치. 카테고리를 더 손보려면 JSON 의 `categories[*].id/label` 과 각 `factors` 배치를 바꾸면 됨.

## 함수 카탈로그 메모

`factorFunctions.ts` = trading.js 의 18개 함수(기본/과거값/이동평균/비율/순위/최고값/최저값/변화량_기간/변화율_기간 + 전체 9). 각 함수에 입력 파라미터(기간 N / 비교값 V / 정렬)와 미리보기 템플릿(`{f}{n}{v}{dir}`)이 있어 STEP2 가 자동으로 입력칸과 `조건식 미리보기`를 렌더.

## 매매 대상 실시간 종목 수 (라이브)

`UniversePanel` 은 시총군·업종·ETF/관리/감리·관심그룹이 바뀔 때마다 300ms 디바운스로
`POST /api/v1/screener/universe-count` 를 호출해 `matched`/`total` 을 갱신한다(`live` prop, 기본 on).

라이브로 만드는 건 백엔드 `src/api/screener_universe_count.py` 의 **★ADAPTER 4곳**만 네 데이터에 연결:
1. `_load_universe_frame()` — `stock_master`/`ticker_universe` 로 전체 매매가능 종목 프레임 구성(ticker·market·market_cap·sector·is_etf·is_managed·is_supervised).
2. `CAP_TIER_RULES` — 시총군 id ↔ 시장/시총 기준(임계값은 근사치, 네 정의로 조정).
3. `SECTOR_THEME_MAP` — 17개 업종 그룹 ↔ 네 섹터 문자열(네 88업종을 묶어 채움).
4. 컬럼명 상수(`COL_*`) — 네 프레임 컬럼명에 맞춤.

`main_api.py` 등록:
```python
from api.screener_universe_count import router as universe_count_router
app.include_router(universe_count_router)
```
연결 전에는 엔드포인트가 **501** 을 반환하고, 프론트는 기존 숫자를 그대로 유지(silent 0 방지). 어댑터만 채우면 즉시 동작.
관심그룹 include/exclude 정밀도는 그룹의 실제 종목코드가 필요 — `UniversePanel` 의 `universeCount({ groups: ... tickers: [] })` 자리에 `watchlistStorage` 의 종목코드를 넣으면 됨.
