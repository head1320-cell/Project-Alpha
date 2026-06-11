# 젠포트식 전환 — 해결/미해결 정리

첨부 스크린샷(젠포트 백테스터) 기준으로, 현재 구현 상태를 4단계로 정리한다.
(✅ 완료 / 🟡 부분 / 🔴 미해결-엔진·모델 / ⛔ 미해결-데이터부재)

## ✅ 완료

- **3탭 구조**: 매수 조건 / 매도 조건 / 매매 대상 (빨강/파랑/중립).
- **팩터 선택 창**: 대분류 → 팩터(344개, 가이드 14 대분류) → 함수(18종) 2-스텝.
- **조건식 진입/청산**: 가격·거래량·기술 팩터를 봉마다 평가(매수 전조건 충족 진입, 매도 충족 청산).
- **횡단면 순위/비율 매수**: `순위(팩터,DESC)<=N`, `비율(팩터,DESC)>=p` — 봉마다 전 종목 랭킹/백분위로 선택.
- **순위/비율 내부지표(중첩)**: `inner_function_id/inner_params` — `순위(변화율_기간(종가,20),DESC)<=5` 같은 파생지표 랭킹. 패널 구축 시 종목별 내부 함수 선적용, 단일종목 조건에도 동일 중첩 적용(`이동평균(변화량(종가))` 등). 팩터 선택 창 STEP2에 "내부 지표" 선택 + 중첩 미리보기/NL 합성. `required_days`가 내부 기간 반영, 캐시 키에 내부 파라미터 포함.
- **매매 대상**: 실제 업종(`/sectors`), 실제 시총 6단계 tier(시총 데이터), ETF 포함/미포함, 관심그룹(watchlistStorage 실종목).
- **전체 유니버스 일별 평가**: 후보 풀 ≤2000 + `max_positions`로 일별 보유 선택.
- **청산룰**: 손절·익절·최대 보유일 + **최소 보유일**(min_hold_days, 어댑터 연결됨).
- **트레일링 스탑(드래깅 청산)**: 엔진 `trailing_stop_pct`(종가 기준 고점 추적, min_hold 이후 발동) + 어댑터 연결. `tests/test_trailing_stop.py`.
- **체결가 유형**: 엔진 13종(`fill_price.py`) ↔ UI 선택기(매수/매도 패널) ↔ 어댑터 `buy/sell_fill_type` 연결. 카탈로그는 `lib/backtest/fillPrice.ts`(백엔드 미러).
- **리밸런싱 주기**: `rebalance_period`(weekly/monthly) — 신규 매수를 주·월 첫 거래일로 게이트(청산룰·손익절은 매일 유지). 포트 기본 설정 UI + 어댑터 연결. `tests/test_rebalance_timing.py`.
- **마켓타이밍**: `market_timing{index_ticker, action, conditions}` — 지수 봉에 조건식(18함수 재사용, 예: 평균모멘텀스코어·변화율) 매일 평가. OFF 시 신규 매수 차단(block_buy) 또는 전량 청산(exit_all). 평가 불가·데이터 부재 시 개입 안 함(fail-open). 매수 탭 "마켓타이밍" 섹션 + 어댑터 연결.
  - 한계: 조건은 `값 vs 상수` 비교라 "지수>20일선" 같은 시리즈 간 비교는 직접 표현 불가 — `ams`(평균모멘텀스코어)·`pct`(기간수익률)로 동등 표현. (중첩 모델도 랭킹 대상 파생이지 시리즈 간 비교가 아님 — 필요 시 좌우항 모델 확장 별도)
- **비용**: 수수료·슬리피지·유동성 하한.
- **결과**: 수익률곡선 + KOSPI 벤치마크 오버레이 + 초과수익/α/β, MDD, 월별 히트맵, 매매내역, CSV.
- **저장/불러오기 + 템플릿**: `lib/backtest/strategyLibrary.ts`(v2 키, BacktestStrategy 전체 보관, 스키마 병합 로드) — 탭 위 전략 라이브러리 바(이름·저장·내 전략 칩·삭제). 빌트인 템플릿 4종(모멘텀 상위 5 / 추세+거래대금 / 주간 리밸런싱 모멘텀 / 마켓타이밍 방어형)이 중첩 랭킹·리밸런싱·마켓타이밍 신기능을 시연.

## 🟡 부분 구현

(현재 없음 — 아래 ✅로 이동)

- ~~매수 비중 ATR~~ → ✅ **ATR 비중(역변동성)**: `buy_weight_mode="atr"` — NATR(ATR14/종가) 2% 기준 역비례 배수(0.5~1.5 클램프). `tests/test_atr_sizing.py`.
- ~~매수 정렬~~ → ✅ **매수 우선순위 1차/2차 정렬**: `sort_screener_items`(키별 방향 독립, 동점 시 stock_code 결정적) + 라우트 `sort_dir/sort_by_secondary/sort_secondary_dir` + 매수 탭 정렬 UI. 후보 풀 정렬 = 엔진 매수 순회 순서. `tests/test_buy_sort.py`.

## 🔴 미해결 — 엔진/모델 작업 필요

- ~~분할매수 / 돌파매수 / TWAP~~ → ✅ **분할매수**(토글+1회 비중%+최대 횟수 → buy_divide_pct/max_buy_count), ✅ **분할매도**(신호·손익절 매도 전반에 적용 — sell_divide_pct/max_sell_divisions), ✅ **돌파매수**(`breakthrough_buy` — 전일 고가 돌파 시에만 진입, 체결가 max(시가, 전일고가)). `tests/test_breakout_split.py`. **TWAP 토글은 제거** — 체결가 유형(twap/vwap, OHLC 근사)으로 일원화(분봉 연동 시 정밀화).

## ⛔ 미해결 — 데이터 부재

- ~~관리종목/감리종목 제외~~ → ✅ **KIS 마스터 테일 파싱으로 해결 (KRX 불필요)**: `kis_master_parser`가 공식 스펙(KOSPI 227B/KOSDAQ 221B 테일)으로 관리종목·시장경고·투자주의환기·거래정지·시가총액·업종코드 추출 → `master_flags_cache.json` → `stock_master.MANAGED_CODES/SUPERVISED_CODES` 자동 활성. **사용자 환경에서 `POST /api/v1/symbols/collect-master` 1회 실행(인증 불필요)이 트리거** — 응답 sanity(삼성전자 시총·tail_parsed_pct)로 실파일 오프셋 정합 확인. `tests/test_master_parser.py`.
- ~~펀더멘털 PIT 평가~~ → 🟡 **DART 연결 완료 (부분)**: `pit_store._period_asof`가 공시시차(분기 45일/연간 90일) 기준 공시완료 보고서를 선택해 DART에서 실값 조회(키 설정 시). **ROE/ROA/부채비율만 실값** — PER/PBR/배당/시총은 역사 시세 미연동이라 현재값 유지(소비자가 None 필드 비교체로 부분 적용). 키 없으면 기존 mock 불변. `tests/test_pit_dart.py`. 남은 것: 역사 시세 연동 시 가격 의존 지표 PIT화.
- ~~전체시장 일별 평가~~ → ✅ **시그널 벡터화로 완성**: 조건식을 전 봉 1회 사전계산(`precompute_signals`/`signal_at`) — per-bar 대비 **실측 142×**(20종목×320봉 기준 12.5s→0.09s). 등가성을 전 봉 스위프 + 엔진 on/off 거래 완전 일치 테스트로 고정(인과 연산만 사용 — look-ahead 없음). 후보 풀 가드 2000→**4000**(전 주권 ~2,700 커버). `vectorize_signals=False`로 per-bar 디버그 가능. `tests/test_vectorized_signals.py`.
  - 부수 수정: 엔진 슬라이스 date 포맷(YYYYMMDD) vs 패널 인덱스(YYYY-MM-DD) 불일치로 **횡단면(순위/비율) 조건이 엔진 경로에서 조용히 무시되던 버그** 수정 + per-bar 경로에도 수급 토큰 종목 식별(attrs) 일관성 부여.
- ~~수년치 OHLCV 적재·생존편향~~ → ✅ **KRX OpenAPI 연동 (키 발급 완료)**: `krx_client`(날짜 기준 전종목 1콜) + `krx_ingest` 백필(`python -m src.data.krx_ingest --start 2015-01-01`, 재개 가능, 지수 포함) → daily_prices를 채워 백테스트는 DB에서(젠포트식 사전 적재). **수정종가**는 등락률 체인으로 `adj_close` 재구성(분할 점프 제거). **시점 유니버스** `universe="all_asof"` — 백테스트 시작일 당시 거래 종목(이후 상폐 포함) → 생존편향 보정. `tests/test_krx_ingest.py`. 실수신 검증: verify_connection 【5】.
- **지수 편입 이력(KOSPI200 과거 구성)**: 여전히 미보유 — 편입 이력 기반 유니버스는 후속(KRX 지수 구성 API 또는 유료 데이터).

## 닫는 우선순위 제안

1. ~~트레일링 스탑 + 최소보유일 + 체결가 유형 어댑터 연결~~ ✅ 완료 (엔진 trailing + 13종 체결가 UI/어댑터, 테스트 포함).
2. ~~리밸런싱 주기 + 마켓타이밍~~ ✅ 완료 (엔진 모드 + UI/어댑터, 테스트 포함).
3. ~~순위/비율 내부지표(중첩 함수 모델) + 봉별 파생팩터 계산~~ ✅ 완료 (inner_function 중첩 + STEP2 UI, 테스트 포함).
4. ~~관리/감리 데이터 소스, PIT 재무 적재~~ ✅ 코드측 완료 (KIS 마스터 테일 + DART PIT — 사용자 환경 collect-master·DART 키로 활성. 잔여: 역사 시세 연동, 상폐 이력은 KRX 영역).
5. ~~저장/불러오기·전략 템플릿 재통합(UI)~~ ✅ 완료 (strategyLibrary v2 + 빌트인 템플릿 4종).
