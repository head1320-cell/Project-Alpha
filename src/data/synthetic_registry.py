"""난수를 쓰는 자리의 ★단일 등록부★ — 무엇이 계산이고 무엇이 지어낸 데이터인가 (2026-11-14)
==============================================================================================
감사: `docs/specs/2026-11-14-synthetic-generation-audit.md` · 관용구: `protected_routes.py` · `cost_model_registry.py` 와 같다 —
흩어진 진실 대신 **한 곳**에 적고, 실제 소스와 **양방향으로** 대조한다(`tests/test_synthetic_registry.py`).

## 왜 목록을 따로 두는가

`mock_allowed()` 를 자리마다 부르면 부른 자리는 막히지만 ★빠뜨린 자리를 아무도 모른다★. 2026-11-14 감사에서 그런 자리가
일곱 나왔다 — 같은 스토어의 `get_factors` 는 게이트를 지나는데 `get_raw_financials` 만 빠져 있었고, 실데이터 표식이 붙은
팩터 둘에는 종목 코드로 씨앗을 준 난수가 섞여 있었다. 시험은 전부 초록이었다(mock 은 늘 값을 주므로).

그래서 **난수를 쓰는 함수 전부**를 여기 적는다. 새 함수가 난수를 쓰면 시험이 "분류하라"고 실패한다.

## 분류

- `SIMULATION` — 난수가 ★방법★이다. 받은 입력 위에서 분포·경로·표본을 만든다(몬테카를로 · 탐색 표본 · 모형 초기화).
  데이터를 지어내지 않는다. ★입력이 실데이터인지는 이 등록부가 보증하지 않는다★ — 그것은 그 계산의 출처 표기가 할 일이다.
- `SYNTHETIC` — 난수가 ★데이터★다. 시세·재무·일정·추정치를 만든다. mock 게이트(`mock_gate.mock_allowed()`) 뒤에서만
  난수를 뽑아야 한다 — 시험이 자리마다 운영 게이트에서 실제로 돌려 확인한다(`prod` 칸은 그때 대신 나가는 것이다).
- `PRIMITIVE` — 합성의 원시 함수(`DeterministicMockStore._rng` 등). 부르는 쪽이 `SYNTHETIC` 으로 등록된다.
- `UNREFERENCED` — 어디서도 임포트하지 않는 모듈의 자리. 누가 임포트하면 시험이 실패한다 — 그때 다시 분류한다.

'게이트 없는 합성'이라는 분류는 ★없다★ — 그런 자리는 등록할 수 없고, 등록하지 않으면 시험이 실패한다.

## 이 등록부가 말하지 않는 것

- 난수 없이 ★해시·상수로★ 값을 만드는 자리는 스캐너가 못 본다(알려진 것: `ohlcv_loader._mock_scale` — mock 전용 경로 안).
- 실데이터가 ★정확한지★는 말하지 않는다. 여기서 보는 것은 "지어냈는가" 하나다.
"""
from __future__ import annotations

from dataclasses import dataclass

SIMULATION = "simulation"
SYNTHETIC = "synthetic"
PRIMITIVE = "primitive"
UNREFERENCED = "unreferenced"
KINDS = (SIMULATION, SYNTHETIC, PRIMITIVE, UNREFERENCED)


@dataclass(frozen=True)
class Site:
    kind: str
    #: 무엇을 만드는가 / 왜 이 분류인가
    what: str
    #: `SYNTHETIC` 만 — 운영 게이트에서 대신 나가는 것(빈값·거절과 그 사유의 자리)
    prod: str | None = None


def _sim(what: str) -> Site:
    return Site(SIMULATION, what)


def _syn(what: str, prod: str) -> Site:
    return Site(SYNTHETIC, what, prod)


_STORE_EMPTY = "빈값 — 스토어가 `_source: unavailable`(또는 빈 dict)로 돌려주고 화면은 미상으로 그린다"

#: `경로::함수(클래스.메서드)` → 분류. 키는 `tests/synthetic_scan.py::scan_sources` 가 소스에서 뽑는 것과 같아야 한다.
SITES: dict[str, Site] = {
    # ── 계산(난수가 방법) ─────────────────────────────────────────────────────────────────────
    "src/api/allocation_routes.py::run_analyze":
        _sim("포트폴리오 일간 수익률의 평균·표준편차로 1년 수익 분포를 뽑는다(GBM 정규근사 · 씨앗 고정)"),
    "src/api/strategy_routes.py::kis_optimize":
        _sim("파라미터 조합이 상한을 넘으면 조합을 표본으로 줄인다(탐색 범위의 표본 — 데이터가 아니다)"),
    "src/engine/auto_alpha.py::_term": _sim("후보 알파 식의 항을 고른다(식의 탐색)"),
    "src/engine/auto_alpha.py::_random_expr": _sim("후보 알파 식을 만든다(식의 탐색)"),
    "src/engine/auto_alpha.py::_mutate": _sim("후보 알파 식을 변이한다(식의 탐색)"),
    "src/engine/auto_alpha.py::_crossover": _sim("후보 알파 식을 교배한다(식의 탐색)"),
    "src/engine/auto_alpha.py::generate_candidates": _sim("후보 알파 식의 탐색 — 씨앗을 받아 결정론적"),
    "src/engine/macro_allocation.py::macro_embedded_allocation":
        _sim("성장·물가 추정의 표준오차 아래에서 비중 분포를 뽑는다(신뢰구간 · 씨앗 고정). ★배분 결정 경로 — 이 감사는 손대지 않았다★"),
    "src/engine/regime_transitions.py::k_step_forecast": _sim("전이행렬 사후분포에서 k개월 뒤 국면 확률을 뽑는다"),
    "src/engine/research_preregistration.py::null_behaviour_fingerprint": _sim("귀무 경로 생성기의 동작 지문(사전등록 고정용)"),
    "src/engine/valuation/practice_models.py::driver_monte_carlo": _sim("성장률·마진·재투자율의 분포에서 가치 분포를 뽑는다"),
    "src/engine/valuation/valuation_distribution.py::valuation_distribution": _sim("할인율·성장률 가정의 분포에서 가치 분포를 뽑는다"),
    "src/models/credit_spread_idr.py::CreditSpreadRiskEngine.portfolio_credit_spread_var":
        _sim("받은 포지션의 등급 전이를 표본으로 뽑아 손익 분포를 만든다"),
    "src/models/lstm_engine.py::LSTMVolatilityEngine.__init__": _sim("모형 가중치 초기화의 씨앗"),
    "src/models/monte_carlo.py::MonteCarloVaR.simulate_gbm_single": _sim("받은 수익률 모수로 가격 경로를 뽑는다(VaR)"),
    "src/models/monte_carlo.py::MonteCarloVaR.simulate_gbm_multi": _sim("받은 평균·공분산으로 포트폴리오 손익을 뽑는다(VaR)"),
    "src/models/portfolio_optimizer.py::efficient_frontier": _sim("무작위 비중 표본으로 효율적 투자선을 그린다"),
    "src/models/ql_exotics_pricer.py::_py_barrier_mc": _sim("배리어 옵션 가격의 몬테카를로(받은 모수)"),
    "src/models/ql_exotics_pricer.py::price_stepdown_els": _sim("스텝다운 ELS 가격의 몬테카를로(받은 모수)"),
    "src/models/risk_analytics.py::mc_path_simulation": _sim("받은 수익률의 평균·표준편차로 가격 경로를 뽑는다"),

    # ── 합성 데이터(게이트 뒤에서만) ──────────────────────────────────────────────────────────
    "src/api/system_routes.py::live_risk":
        _syn("실시간 위험 흐름의 시세·보유 수량·VaR(전부 난수)", "사유 한 번(`reason: no_feed`) 보내고 닫는다"),
    "src/data/consensus_store.py::ConsensusStore._build_estimates": _syn("실적 추정치·목표가", _STORE_EMPTY),
    "src/data/event_calendar.py::_mock_event_date":
        _syn("실적 발표·배당락까지 남은 날", "미상 + 사유(`EVENTS_NO_FEED`) · 조건 종류 `event` 를 쓴 요청은 거절"),
    "src/data/extended_factors_store.py::ExtendedFactorsStore._build":
        _syn("확장 팩터의 바탕값(전형 범위의 균등 난수)", "실데이터에서 파생되는 칸만 남는다 — 나머지는 없다"),
    "src/data/fundamentals_store.py::FundamentalsStore._mock_raw_financials":
        _syn("원천 재무 42칸", "빈 dict — `get_raw_financials` · `get_factors` 가 운영에서 이 함수를 부르지 않는다"),
    "src/data/fundamentals_store.py::FundamentalsStore._derive_factors":
        _syn("mock 원천일 때의 팩터 일부(순위·FCF 성장·모멘텀·결측 흉내)",
             "실데이터 원천(`_source: dart_real`)이면 난수를 뽑지 않는다 — 원천이 없는 팩터는 미상"),
    "src/data/market_data.py::_mock_prices": _syn("종가 시계열", "`_source: unavailable`"),
    "src/data/market_data.py::_mock_ohlcv": _syn("일봉", "`_source: unavailable`"),
    "src/data/market_data.py::_mock_supply": _syn("투자자별 순매수", "`_source: unavailable`"),
    "src/data/minute_bars.py::_mock_minute_bars":
        _syn("분봉(390개)", "KIS 실호출 — 실패하면 그 종목의 분봉이 없다(호출부는 일봉 모델로 열화하고 그렇게 적는다)"),
    "src/data/ohlcv_loader.py::_mock_walk": _syn("일봉 종가의 걸음", "적재분·실제 원천만 — 없으면 빈 표"),
    "src/data/ohlcv_loader.py::_mock_ohlcv_df._noise": _syn("일봉의 시가·고가·저가·거래량 잡음", "적재분·실제 원천만 — 없으면 빈 표"),
    "src/data/price_factors_store.py::PriceFactorsStore._mock_factors": _syn("가격 팩터(모멘텀·변동성 등)", _STORE_EMPTY),
    "src/engine/dag_runner.py::_generate_gbm":
        _syn("그래프 백테스트의 일봉", "계산하지 않는다 — `success: false` + 사유(`data_origin.reason: not_loaded`)"),
    "src/engine/graph_store.py::GraphStore._build_graph": _syn("공급망·경쟁 관계 그래프", "빈 관계"),
    "src/engine/liquidity_gate.py::LiquidityStore._mock_liquidity": _syn("거래대금·호가 스프레드", _STORE_EMPTY),
    "src/engine/pit_store.py::PITStore.get_financials_asof":
        _syn("과거 시점 재무(현재 재무 × 추세 × 난수)", "여덟 칸 미상 + 사유(`_source: pit_unavailable`)"),
    "src/engine/pit_store.py::PITStore._mock_price_before_the_walk":
        _syn("mock 봉이 없는 날짜의 과거 가격", "실제 종가만 — 없으면 그 종목을 평가에서 빼고 사유를 싣는다"),
    "src/engine/vector_store.py::VectorStore.get_embedding":
        _syn("재무 없이 종목 코드로 만든 임베딩", "`None` — 비교하지 않는다"),
    "src/engine/vector_store.py::VectorStore._embed_from_financials":
        _syn("재무 임베딩에 더하는 종목 고유 잡음", "잡음 없이 재무 여덟 차원만"),
    "src/engine/z_score.py::compute_rolling_stats":
        _syn("종목의 과거 분포(20분기)", "`None` · 조건 종류 `z_score` 를 쓴 요청은 거절"),
    "src/execution/kis_client.py::MockKISClient.get_daily_ohlcv":
        _syn("mock 증권사 클라이언트의 일봉", "mock 클라이언트를 만들지 않는다 — 키가 없으면 `KISCredentialsMissing`"),
    "src/screener_pipeline.py::_generate_mock_equity_data":
        _syn("시장 스냅샷(주식)의 시세·재무", "야후 실시세만 — 꺼져 있거나 실패하면 0행 + 사유"),
    "src/screener_pipeline.py::fetch_ficc_snapshot":
        _syn("시장 스냅샷(채권·외환·옵션)", "0행 + 사유(`no_feed`)"),
    "src/services/macro_collector.py::_generate_mock_series": _syn("매크로 지표 시계열", "값 없음 + 지표별 사유"),
    "src/services/sentiment_worker.py::SentimentWorker._build_sentiment": _syn("뉴스·콜 센티먼트 점수", _STORE_EMPTY),

    # ── 합성의 원시 함수 ──────────────────────────────────────────────────────────────────────
    "src/data/mock_base.py::DeterministicMockStore._rng": Site(PRIMITIVE, "키에서 씨앗을 뽑아 RNG 를 만든다"),
    "src/data/mock_base.py::DeterministicMockStore._normal": Site(PRIMITIVE, "결정론적 정규분포 표본"),
    "src/data/mock_base.py::DeterministicMockStore._uniform": Site(PRIMITIVE, "결정론적 균등분포 표본"),
    "src/data/mock_base.py::DeterministicMockStore._choice": Site(PRIMITIVE, "결정론적 선택"),
    "src/data/mock_base.py::DeterministicMockStore._maybe_missing": Site(PRIMITIVE, "결측 흉내"),

    # ── 어디서도 임포트하지 않는 모듈 ─────────────────────────────────────────────────────────
    "src/engine/graph_runner.py::_generate_dummy_ohlcv":
        Site(UNREFERENCED, "옛 그래프 러너의 합성 일봉(게이트는 넣어 두었다 — `dag_runner` 가 대신 쓰인다)"),
    "src/models/curve_builder.py::generate_mock_market_data": Site(UNREFERENCED, "KOFR·IRS·SOFR·CRS 예시 시세"),
    "src/models/ql_interest_rate_models.py::generate_swaption_vol_grid": Site(UNREFERENCED, "스왑션 변동성 예시 격자"),
    "src/models/ql_portfolio_xva.py::simulate_exposure_profile": Site(UNREFERENCED, "스왑 노출 프로파일의 몬테카를로"),
    "src/models/volatility_surface.py::generate_mock_vol_quotes": Site(UNREFERENCED, "ATM·RR·BF 변동성 예시 호가"),
}


def keys_of(kind: str) -> list[str]:
    return sorted(k for k, s in SITES.items() if s.kind == kind)
