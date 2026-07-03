# 매크로 추천 — 신뢰도 가중 배분 + market 버그 수정 + 정직화 설계 스펙

- 날짜: 2026-07-03
- 브랜치: `claude/keen-thompson-bdk3e8`
- 배경: 기관 퀀트 관점 크리틱(신뢰도 27%인데 위험자산 고비중 / Kelly 오용 의심 / 후행성). 코드 검증 후
  유효 지적 반영. 크리틱의 Kelly "통짜 사용"은 오독(22전략 중 1개·완전투자 무레버리지)이나, ① market 미연결
  버그와 ② 신뢰도 무반영은 사실로 확정.
- 커밋 트레일러: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_01NSAuFjWec6ZwXi9wq7SbrA`
- 검증: `KIS_USE_MOCK=1 python -m pytest tests/ -q`(베이스라인 694 passed/10 skipped) + ruff/tsc/next build.

## 진단 (파일:라인 확정)
1. **market 버그**: `macro_recommender.py:96` `RegimeAnalyzer().analyze()` — market 인자 누락 → 항상 KR 국면.
   US 탭 추천 배분이 KR(Goldilocks) 적합도로 계산됨. (analyze는 market 지원 — 앞 작업서 연결 누락)
2. **신뢰도 무반영**: recommend()가 confidence를 산출조차 반환 안 함. 27%든 80%든 top 전략 100% 비중.
3. **Kelly**: `risk_allocations.py:369` s_kelly = Σ⁻¹μ long-only + 100% 완전투자 정규화(무레버리지). 22전략 중 1개.
   → 라벨이 오해 자초. 명확화만.
4. **후행성**: 매크로 데이터 본질. as-of·저확신 노출 + 시장가 선행신호(VIX/신용/곡선은 stress에 이미 반영) 명시.

## 설계 (핵심 세트)

### A. market 연결 (버그 수정)
- `recommend(market)` → `RegimeAnalyzer().analyze(market=("kr"|"us"))`. US 탭이 실제 US 국면·신뢰도 사용.

### B. 신뢰도 가중 디리스킹 (신규 순수함수 + 배선)
- **NEW `confidence_overlay(holdings, confidence, max_derisk=0.6, anchor="BIL", anchor_label="현금성(BIL 1-3M)")`**
  (`src/engine/macro_recommender.py` 또는 신규 모듈): 위험 배분을 신뢰도만큼만 유지, 나머지는 현금성 앵커로.
  - `cash = (1 - clamp(confidence,0,1)) * max_derisk` (예: conf .27 → cash .44 / conf .80 → cash .12)
  - 기존 holdings 각 weight × (1 - cash), 앵커에 cash×100 추가(앵커가 이미 있으면 합산). 합 100 정규화.
  - conf ≥ 0.999면 원본 그대로(오버레이 0). 빈 holdings 방어.
- recommend() 반환 확장: `confidence`(0~1), `top.holdings_final`(오버레이 적용), `top.cash_overlay_pct`,
  `low_conviction`(confidence < 0.35). 기존 `top.holdings`(원 전략)는 유지(하위호환·성과 랭킹 불변).
- 랭킹(fit+perf)·성과 계산은 원 holdings 기준 불변 — 오버레이는 **최종 표시 배분에만** 적용.

### C. 정직화
- Kelly 라벨: RISK_STRATEGIES kelly desc → "Σ⁻¹μ 성장최적 · long-only·완전투자(무레버리지)". strategy_profiles
  설명/프론트 툴팁 동기화.
- recommend 반환에 `data_lag_note`(정적): "매크로 지표는 후행(CPI 등 ~1개월). 시장가 선행신호(VIX·신용
  스프레드·수익률곡선)는 Stress에 반영됨. 지표별 실제 시점은 Indicators 탭 참조."
- 프론트 RecommendTab/OverviewTab: 신뢰도 % + 저확신 배지("저확신 — 현금 {N}% 확대") + 오버레이 배분
  (holdings_final) 표시 + lag 주석. HoldingsDonut는 holdings_final 사용.

## TDD
- `tests/test_confidence_overlay.py`: conf 0.27→cash≈0.44(±.01)·위험자산 축소·합100 / conf 1.0→원본 불변 /
  앵커 기존 존재 시 합산 / 빈 holdings 안전 / conf 0→cash=max_derisk.
- `tests/test_recommend_market.py`: recommend("us")가 analyze(market="us") 경유(monkeypatch로 market 전달 확인)
  + 반환에 confidence·holdings_final·low_conviction 키.

## 구현 순서(소커밋)
1. 스펙 커밋.
2. B-1: confidence_overlay 순수함수 (TDD).
3. A+B-2: recommend market 연결 + confidence/overlay/low_conviction 반환 (TDD).
4. C: Kelly 라벨 + lag_note.
5. 프론트: 타입 + RecommendTab/OverviewTab 신뢰도·배지·오버레이·주석.
6. 검증(pytest/ruff/tsc/build) → CLAUDE.md → 푸시.

## 하지 않을 것 (범위 밖·이유)
- 전체 배분을 MVO/RP로 교체 — 이미 22후보에 risk_parity/min_var/max_sharpe/hrp/black_litterman 포함, 사용자가
  고르면 1위로 표면화. 강제 불필요.
- 국면 히스테리시스/전환비용 페널티 — 표시용 대시보드라 confidence 가중이 경계 요동을 상당 흡수. 필요 시 후속.
- 볼타겟 Kelly 변형·alt-data NLP 나우캐스팅 — 별도 대형 과제.

## 정직한 한계
- 샌드박스 mock — 실 신뢰도·국면 값은 GCP. 오버레이·market 분기·랭킹 로직은 단위/픽스처로 검증.
- max_derisk 0.6은 디폴트 정책값(완전 현금화 방지) — 필요 시 조정 가능하게 파라미터로 노출.
