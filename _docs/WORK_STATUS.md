# WORK_STATUS — 젠포트화 + 백테스터 정교화 작업 상태

> 세션 압축 전 스냅샷. 브랜치 `claude/keen-thompson-bdk3e8` (최신 `0582b17`).
> 게이트: pytest **539 passed / 10 skipped**, ruff 클린, tsc 0 errors, next build 15/15.

---

## 한 줄 요약
젠포트(Genport) 백테스터를 1:1 재현하는 작업을 단계적으로 완료. 조건식 엔진·체결
모델·매수/매도/매매대상 디테일·자산배분·조건 요약 패널·전략 저장까지 구현. 남은 건
외부 데이터 의존 항목뿐.

---

## 최근 커밋 흐름 (최신순)
- `0582b17` ⌘K 팔레트·상단 라이브러리 바 제거 + 우측 하단 액션 박스(저장·실행)
- `67e739e` 백테스터 UI 개선 1~4 + 장식 요소 삭제 + 실행 버튼 매매대상 한정
- `f40da46` 조건 요약 매매대상 정교화 (포함 업종 N/88)
- `9cdff20` 조건 요약 패널 — 젠포트 '내가 설정한 조건 보기' 미러
- `f5af363` 관심종목 모달 4단 카스케이드 (주식 유니버스/업종/테마/ETF)
- `417814d` 젠포트 88 taxonomy 인코딩 + 종목 시드 + 17→88 트리 UI
- `6c19597` 업종 세분류·ETF 배선 (마스터 코드 → 전 종목 그룹화)
- `47a994c` Phase 5 자산배분 ETF 바스켓
- `451385d` Phase 4 관심종목 그룹 관리 모달
- `f161d43` Phase 3 돌파 매수 확장(기준가·±%·양방) + 매수 시점
- `163e126` Phase 2 분할 래더(가격변동%·비중% 단계)
- `7f01db1` Phase 1 체결가 20종+수식입력 + 만기 매도 정밀화
- (이전) 분봉 수집기/하이브리드 체결, 점수 패널 메모리 다이어트, 자유 산술식·우선순위식·AI 변환, 당일매매, 체결가 오프셋 등

---

## 백엔드 핵심 (엔진/전략)

### `src/kis_backtest_engine.py` — BacktestConfig 필드 (전부 기본=기존 동작 불변)
- 체결: `buy/sell_fill_type`(20종), `buy/sell_fill_offset_pct`(지정가 도달검증), `buy/sell_fill_expr`(수식 기준가)
- 만기: `expiry_fill_type/offset_pct`, `expiry_sell_method`(all|ladder)
- 래더: `buy_ladder`/`sell_ladder` = [{move_pct, weight_pct}] (신호 당일 유효, 미도달 단계 소멸)
- 돌파: `breakthrough_buy`, `breakthrough_base_type`, `breakthrough_offset_pct`, `breakthrough_direction`(up|both)
- 매수시점: `buy_timing`(pre_open|intraday — intraday는 시가 갭 혜택 배제)
- 보유: `max/min_hold_days`, `day_trade`, `sell_divide_pct`, `max_sell_divisions`
- 매수정밀: `buy_weight_mode`(equal|factor|atr), `max_buy_per_day`, `max_buy_count`, `rebuy_block_days`, `max_buy_amount`
- 자산배분: `cash_reserve_pct`, `asset_alloc`{etf_pct, stock_pct, basket[], rebalance_months, fill_type, offset_pct} — ETF 슬리브 `_etf_pos` 별도 보유, `_usable_cash`가 주식 슬리브=equity×stock_pct/100 제한
- 신호: `signal_lag`(0=당일|1=전일 종가 기준), `vectorize_signals`(142×), `buy_sort_expr/desc`(일별 우선순위식)
- 하이브리드: `intraday_fill` + `buy/sell_time_start/end` (분봉 적재 시 정밀, 없으면 일봉 폴백)
- 결과 메타: `intraday`{applied,fallback,%}, `asset_alloc`{etf_pct_actual, holdings}

### 조건식 (`src/kis_strategies/`)
- `condition_strategy.py` ConditionStrategy: buy/sell_conditions + buy/sell_logic + factor_token2/inner2 + expr. `_signal_hits` 단일경로(per-bar=벡터화), `prepare_panel`(횡단면·점수·expr 패널), `signal_at`/`precompute_signals`
- `condition_logic.py`: and/or/not/before/any/every 재귀 파서 + Kleene 3치
- `factor_expr.py`: 자유 산술식 파서(사칙연산·괄호·인용부호·기간/정렬 인자, eval 없음)
- `factor_tokens.py`: 토큰 레지스트리(base/ohlcv/fundamental/market/macro/flow/score), token_support
- `score_factors.py`: 뉴지랭크 7점수 근사(공개 레시피), float32 메모리 다이어트
- `genport_themes.py`: **17그룹→88 세부업종 taxonomy(확정) + THEME_SEED 129종 시드(50/88 세부)** + group_members/theme_members

### 데이터
- `minute_bars.py`: KIS 당일/일별 분봉 수집기 (일자별 parquet, csv.gz 폴백), probe_history
- `genport_themes.py`, `sector_labels.py`(코드→한글 오버라이드, 추측 금지)
- `universe_select.py`: load_universe_frame(마스터 sector_code/sector_mid/ETF 반영), select_universe(theme:/themegroup: 해석)

### API (`src/api/screener_routes.py`)
- screen-to-backtest: 위 모든 필드 패스스루
- `/condition-tokens`, `/condition-logic/validate`, `/factor-expr/validate`, `/condition-nl`(AI)
- `/theme-tree`(17→88), `/stock-browse`(cls=tier/group/theme/etf 4단 카스케이드), `/sectors`(마스터 확장)

---

## 프론트엔드 핵심 (`frontend/src/components/backtest/`)

- `TerminalBacktester.tsx`: 2컬럼 레이아웃 — 좌(편집 탭 01매수/02매도/03매매대상) + 우(`tbt-right-col`: 조건요약 스크롤 + 액션박스 하단고정)
- `ConditionSummary.tsx`: '내가 설정한 조건 보기' — 편집 탭과 동기화(activeTab/onTabChange), 톤 자동(매수빨강/매도파랑/매매대상중립)
- `panels/`: BuyConditionPanel, SellConditionPanel, UniversePanel, AssetAllocPanel, ThemeTree(17→88 접이식), WatchGroupModal(4단 카스케이드 모달), LadderEditor, OffsetInput
- `lib/backtest/`: strategy.ts(BacktestStrategy 타입 + buildSummary 단일소스), strategyLibrary.ts(localStorage `alpha_bt_strategies_v2` 영속 저장/불러오기), conditionSets.ts, fillPrice.ts, assetPresets.ts, factorFunctions.ts
- 액션 박스: 전략명+전략저장+백테스트실행+저장목록(불러오기/삭제). 새로고침 후 유지 검증됨

### 최근 UI 변경 (0582b17, 67e739e)
- 삭제: ⌘K 커맨드 팔레트(layout.tsx), 셸 헤더 Quick Search·계정, 브랜드 v2.0.4, 사이드바 SYSTEM OPERATIONAL, meta-stamp(globals.css `display:none` 전역)
- 조건 요약 ↔ 편집 탭 동기화, 빈 조건식 문구 개선, 매매대상 '선택 현황' 4카드

---

## 정직한 한계 (외부 데이터 필요 — 코드로 불가)
- 젠포트 초세부 테마(애플OLED 등) — 독점 큐레이션
- ETF 6하위분류(국내시장지수/해외/채권 등) — KIS 마스터에 분류코드 없음
- THEME_SEED 미시드 38/88 세부 — 코드 추가 시 즉시 확장
- 장기 과거 분봉 — KIS 일별분봉 소급 한도(verify 【9】 실측) 또는 키움 REST(서버 가능, 실측 후 어댑터)
- 전략 저장은 localStorage(브라우저 한정) — 서버 영속 원하면 백엔드 API로 확장 가능

## GCP 견적 (실측 기반)
- 권장 e2-standard-2(8GB) / 절약 e2-medium(4GB, 점수패널 다이어트로 전시장 백테스트 가능)
- 분봉 수집기는 네트워크 바운드(초당 20콜), CPU<1코어

## 검증 환경 메모
- 스크린샷: `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` + playwright(executable_path 직접 지정, --no-sandbox)
- stale .next 증상 시: pkill node + rm -rf .next + 재빌드
- 백엔드 mock: KIS_USE_MOCK=1

## 다음 작업 후보
- 사용자 환경 실데이터 검증(collect-master → 백필 → verify_connection 【0.5】~【9】)
- 전략 저장 서버 영속(선택), 분봉 백필 후 하이브리드 체결 활성
