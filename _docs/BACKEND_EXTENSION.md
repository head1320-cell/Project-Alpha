# 백엔드 확장 — 조건식 기반 진입/청산 (Genport식)

`screen-to-backtest` 가 **매수/매도 조건(팩터식)을 받아 봉마다 진입/청산 시그널로 평가**하도록 확장.
조건이 없으면 기존 named-strategy 경로 그대로(하위호환). py-compile + 단위 테스트 통과.

## 1) 신규 파일 (그대로 추가)

`src/kis_strategies/condition_strategy.py` — `ConditionStrategy(BaseStrategy)` + 팩터식 평가기.
import 시 `STRATEGY_REGISTRY["Condition"]` 에 자기 등록. 엔진 `get_strategy("Condition", buy_conditions=…, sell_conditions=…)` 로 사용됨.

## 2) `src/api/screener_routes.py` 편집 (2곳)

**(a) `ScreenToBacktestRequest` 에 필드 추가** — `max_buy_count` 아래:
```python
    # 조건식 기반 진입/청산 (Genport식). 있으면 strategy_name 무시하고 조건식 전략 사용.
    # 각 조건 dict: {factor_token, function_id, params{n,v,dir}, op(gte|lte|eq|between), rhs, rhs2?}
    buy_conditions: list[dict] | None = None
    sell_conditions: list[dict] | None = None
```

**(b) `screen_to_backtest()` 의 `# 2) 백테스트` 직전에 분기 추가**하고 `run_backtest(...)` 인자 교체:
```python
        # 조건식 전략 분기 (Genport식 진입/청산)
        eff_strategy = req.strategy_name
        eff_params = dict(req.strategy_params or {})
        if req.buy_conditions or req.sell_conditions:
            from src.kis_strategies import condition_strategy  # noqa: F401 (레지스트리 자기등록)
            _ = condition_strategy
            eff_strategy = "Condition"
            eff_params = {
                "buy_conditions": req.buy_conditions or [],
                "sell_conditions": req.sell_conditions or [],
            }
```
- `run_backtest(... strategy_name=req.strategy_name ...)` → `strategy_name=eff_strategy`
- `run_backtest(... strategy_params=req.strategy_params ...)` → `strategy_params=eff_params`
- 응답 `"strategy": req.strategy_name` → `"strategy": eff_strategy`

## 3) `frontend/src/lib/screenerApi.ts` 편집 (1곳)

`screenToBacktest` 요청 타입의 `max_buy_count?` 아래에 추가:
```ts
    buy_conditions?: Array<{ factor_token: string; function_id: string; params: Record<string, string>; op: string; rhs: number; rhs2?: number | null }> | null;
    sell_conditions?: Array<{ factor_token: string; function_id: string; params: Record<string, string>; op: string; rhs: number; rhs2?: number | null }> | null;
```

## 4) 프론트 (이미 rewrite 패키지에 포함)

`TerminalBacktester.tsx` 의 `strategyToRun()` 이 `s.buy.conditions`/`s.sell.conditions` 를
`{factor_token, function_id, params, op, rhs, rhs2}` 로 매핑해 전송한다.

## 동작 방식

1. universe(프리셋) + `filter_ast` 로 후보 상위 `max_tickers` 종목을 추린다(펀더멘털 스크리닝).
2. `ConditionStrategy` 가 그 후보들에 대해 **봉마다** 매수 조건(전부 충족 시 BUY)·매도 조건(하나라도 충족 시 SELL)을 평가. 손절/익절/보유일은 기존 청산룰과 함께 동작.

## 지원 범위 / 한계 (중요)

- **봉별 평가 가능**: 가격·거래량 팩터(`{시가}{고가}{저가}{종가}{거래량}{거래대금}`) + 18개 함수
  (기본/과거값/이동평균/최고값/최저값/변화량_기간/변화율_기간/절대값/기간총합/비교/큰값/작은값/큰개수/작은개수/평균모멘텀스코어/표준편차).
- **평가 불가(무시)**: 비율·순위(횡단면, 전체 종목 필요), 그리고 펀더멘털·점수·뉴지·가치 팩터(봉별 단일종목 데이터에 없음). → 이런 팩터는 **스크리닝 `filter_ast`** 로 분리하는 게 맞다. 매수 조건이 전부 평가 불가면 진입하지 않는다.
- 후보군은 여전히 `filter_ast` 스크린 상위 N — 젠포트의 "조건이 매일 전체 유니버스에서 종목 선택"과는 다른 **하이브리드**(유니버스/펀더멘털로 후보 → 조건으로 타이밍). 전체 유니버스 일별 조건평가는 추가 작업.
- granular 시총군·업종을 실제 백테스트에 반영하려면 `screener_universe_count.py` 의 `_load_universe_frame` 어댑터를 공유해 후보 생성에 쓰면 됨(다음 단계).

## 검증 결과 (단위 테스트)

합성 OHLCV(상승장)에서: 매수 전조건 충족→`buy`, 미충족→`hold`, 매도 우선→`sell`, 평가불가(`{PER}`)→무시→`hold`, between/평균모멘텀스코어/큰개수 무크래시. 레지스트리 등록 확인.

## 통합 호출 예시

```bash
curl -X POST localhost:8000/api/v1/screener/screen-to-backtest -H "Content-Type: application/json" -d '{
  "universe":"kospi200","filter_ast":{"logic":"AND","conditions":[{"kind":"field","field":"per","op":"gt","value":0}],"groups":[]},
  "max_tickers":10,"start_date":"2023-01-01","end_date":"2024-12-31",
  "buy_conditions":[{"factor_token":"{종가}","function_id":"ma","params":{"n":"5"},"op":"gte","rhs":0}],
  "sell_conditions":[{"factor_token":"{종가}","function_id":"pct","params":{"n":"1"},"op":"lte","rhs":-5}]
}'
```
