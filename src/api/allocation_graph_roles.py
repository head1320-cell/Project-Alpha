"""노드 링크의 관계 — 포트 역할 · 요구값 · 싣는 값 · 과거 시뮬레이션 표시 (BT1)
==============================================================================
스펙 `docs/superpowers/specs/2026-09-30-bt-canvas-procedure-node-link-design.md` §1

캔버스 선 판("무엇에 쓰이나요")과 편집 순간의 연결 설명(`needs_unmet`)이 읽는 단일 출처다. 노드 모듈을
건드리지 않고 등록이 끝난 뒤 한 곳에서 붙인다(`allocation_graph_glance` 와 같은 방식).

- **역할(`ROLES`)** 은 받는 노드가 그 입력을 **무엇에 쓰는지**다. 노드 설명과 코드에서 확인한 것만 적는다 —
  확인하지 못한 포트는 비워 두고, 화면은 그 줄을 생략한다(지어내지 않는다).
- **요구값(`NEEDS`)·싣는 값(`GIVES`)** 은 타입이 같아도 계산할 때 실패하는 규칙을 선언으로 옮긴 것이다. 선언이
  참인지는 `tests/test_graph_port_contract.py` 가 노드를 실제로 돌려 확인한다(선언한 키는 실리고, 선언하지 않은
  키는 실리지 않는다).
- **과거 시뮬레이션(`HISTORY`)** — 증거 관문이 "과거로 돌려 보는 단계가 없어요"라고 사실과 다르게 말하지 않게 한다.
"""
from __future__ import annotations

from src.engine import portfolio_graph as pg

#: 값 키 → 사람 말(연결 설명 문장에 쓴다).
NEED_PLAIN = {
    "req": "되돌려 볼 규칙(비중 계산의 설정)",
    "sigma_annual": "공분산(종목끼리 같이 움직이는 정도)",
}

#: (노드 종류, 입력 포트) → 역할.
ROLES: dict[tuple[str, str], str] = {
    ("returns", "universe"): "이 종목들의 과거 가격으로 날마다의 수익률을 만들어요.",
    ("optimizer", "returns"): "기대 수익과 종목끼리 같이 움직이는 정도(공분산)를 재는 데 써요.",
    ("optimizer", "belief"): "기대 수익을 과거 기준으로 잡을지, 경기 국면을 반영할지 그 설정을 받아요.",
    ("optimizer", "views"): "블랙-리터먼·EP 방식일 때만 내 생각을 비중에 반영해요.",
    ("risk", "weights"): "이 비중과 함께 온 공분산으로 종목마다 위험을 얼마나 만드는지 나눠요.",
    ("backtest", "returns"): "시점마다 그때까지의 수익률만으로 비중을 다시 정하는 데 써요.",
    ("backtest", "weights"): "이 비중을 만든 규칙을 받아 과거 시점마다 다시 풀어요.",
    ("scenario_stress", "weights"): "과거 위기나 가정한 충격에 넣어 볼 비중이에요.",
    ("corr_stress", "returns"): "평소의 흔들림과 상관을 재는 데 써요.",
    ("corr_stress", "weights"): "상관이 치솟을 때 흔들림이 얼마나 커지는지 볼 비중이에요.",
    ("sensitivity", "returns"): "기대 수익을 조금씩 바꿔 비중을 다시 푸는 데 써요.",
    ("sensitivity", "weights"): "이 비중을 만든 규칙(위험 회피·생각)을 받아 다시 풀어요.",
    ("factor_xray", "weights"): "가치·모멘텀 같은 성격이 어디로 기울었는지 잴 비중이에요.",
    ("screener", "universe"): "조건으로 거를 후보 종목이에요.",
    ("factor_scores", "universe"): "점수를 매길 종목이에요.",
    ("alpha_score", "universe"): "알파 식으로 점수를 낼 종목이에요.",
    ("valuation_scores", "universe"): "적정가를 계산해 점수를 매길 종목이에요.",
    ("scores_to_weights", "scores"): "점수 상위 종목을 고르는 데 써요.",
    ("scores_to_weights", "returns"): "흔들림을 쓰는 나누기 방식(역변동성·위험 균등 등)에 써요.",
    ("neutralize", "weights"): "시장 민감도·업종 쏠림을 없앨 비중이에요.",
    ("sleeve_combine", "a"): "위험 기준으로 합칠 첫째 묶음이에요.",
    ("sleeve_combine", "b"): "위험 기준으로 합칠 둘째 묶음이에요.",
    ("sleeve_combine", "c"): "있으면 위험 기준으로 함께 합칠 셋째 묶음이에요.",
    ("exposure_overlay", "weights"): "타이밍·국면 판단대로 주식 비중을 줄일 비중이에요.",
    ("exposure_overlay", "signal"): "주식 비중을 얼마나 줄일지 정하는 타이밍 신호예요.",
    ("exposure_overlay", "regime"): "주식 비중을 얼마나 줄일지 정하는 경기 국면이에요.",
    ("timing_simulation", "signal"): "과거 시점마다 다시 계산해 볼 타이밍 신호예요.",
    ("order_preview", "weights"): "지금 비중에서 옮겨 갈 목표 비중이에요.",
    ("target_version", "weights"): "실행 목표로 만들 비중이에요.",
    ("decision_journal", "target"): "무엇을 정했는지 기록할 실행 목표예요.",
    ("decision_journal", "trades"): "함께 남길 주문 목록이에요.",
    ("decision_journal", "stress"): "함께 남길 충격 결과예요.",
    ("company_views", "returns"): "전망을 만들 종목과 기준일을 여기서 가져와요.",
    ("frontier", "returns"): "기대 수익과 흔들림의 경계를 그리는 데 써요.",
    ("frontier", "weights"): "이으면 경계 옆에 이 비중의 기대 수익·흔들림을 점으로 찍어요.",
    ("scenario_three_way", "weights"): "세 갈래를 같은 충격에 넣어 볼 비중이에요.",
    ("scenario_three_way", "signal"): "‘타이밍만’ 갈래에 쓰는 신호예요.",
    ("scenario_three_way", "regime"): "‘타이밍+국면’ 갈래에 쓰는 경기 국면이에요.",
    ("custom_scenario", "weights"): "직접 정한 충격에 넣어 볼 비중이에요.",
    ("backtest_attribution", "run"): "수익을 매크로 흐름별로 나눠 볼 백테스트 실행이에요.",
    ("backtest_compare", "a"): "나란히 놓을 첫째 백테스트 실행이에요.",
    ("backtest_compare", "b"): "나란히 놓을 둘째 백테스트 실행이에요.",
    ("var_es", "returns"): "드문 날의 손실을 재는 과거 수익률이에요.",
    ("mc_var", "returns"): "모의 경로를 만드는 흔들림을 재는 데 써요.",
    ("vol_models", "returns"): "지금의 변동성과 앞으로의 흐름을 추정하는 데 써요.",
    ("holding_var", "returns"): "하루 손실을 재는 과거 수익률이에요.",
    ("frtb_es", "returns"): "꼬리 손실과 스트레스 구간을 찾는 데 써요.",
    ("rolling_sharpe", "returns"): "창을 밀어 가며 샤프 비율을 재는 수익률이에요.",
    ("dcc_corr", "returns"): "종목 쌍의 상관이 어떻게 바뀌었는지 재는 데 써요.",
    ("futures_hedge", "returns"): "비중과 함께 이으면 이 포트폴리오의 시장 민감도(β)를 과거 표본으로 재요.",
    ("rebalance_decision", "weights"): "옮겨 갈 목표 비중과 그 비중을 만든 규칙이에요.",
    ("cash_yield", "weights"): "이으면 투자 비중을 이 비중의 합으로 재요 — 없으면 설정한 값을 써요.",
    ("current_weights", "universe"): "유니버스에 적은 지금 비중을 그대로 꺼내요.",
}
for _p in ("a", "b", "c", "d"):
    ROLES[("sleeve_analytics", _p)] = "평소·위기 때 함께 움직이는지 볼 비중 묶음이에요."
for _i in range(1, 9):
    ROLES[("portfolio_combine", f"s{_i}")] = f"한 포트폴리오로 합칠 {_i}번째 전략의 비중이에요."
for _p in ("r1", "r2", "r3", "r4"):
    ROLES[("record_robustness", _p)] = "날짜를 맞춰 함께 무너졌는지 볼 백테스트 실행이에요."
for _p in ("t1", "t2"):
    ROLES[("record_robustness", _p)] = "날짜를 맞춰 함께 무너졌는지 볼 정책 백테스트 결과예요."
for _k in ("var_es", "mc_var", "vol_models", "holding_var", "frtb_es", "rolling_sharpe"):
    ROLES.setdefault((_k, "weights"), "‘무엇을 볼까’가 포트폴리오일 때 이 비중으로 포트폴리오 수익률을 만들어요.")
ROLES[("futures_hedge", "weights")] = "수익률과 함께 이으면 이 비중의 포트폴리오 β 를 재요 — 없으면 설정한 β 를 써요."

#: (노드 종류, 입력 포트) → 보내는 쪽이 꼭 실어야 하는 값. 코드에서 확인한 실패 조건 그대로다.
NEEDS: dict[tuple[str, str], tuple[str, ...]] = {
    ("backtest", "weights"): ("req",),            # allocation_graph_nodes._backtest
    ("rebalance_decision", "weights"): ("req",),  # allocation_graph_nodes_alloc_extra._rebalance_request
    ("sensitivity", "weights"): ("req",),         # allocation_graph_nodes_check._sensitivity
    ("risk", "weights"): ("sigma_annual",),       # allocation_graph_nodes._risk
}

#: (노드 종류, 출력 포트) → 싣는 값. 선언하지 않은 값은 싣지 않는다(테스트가 실제로 돌려 확인한다).
GIVES: dict[tuple[str, str], tuple[pg.Gives, ...]] = {
    ("optimizer", "weights"): (pg.Gives("req"), pg.Gives("sigma_annual")),
    ("scores_to_weights", "weights"): (pg.Gives("sigma_annual", when="returns"),),
    ("exposure_overlay", "weights"): (pg.Gives("sigma_annual", from_="weights"),),
}

#: 과거를 시뮬레이션하거나 그 기록을 읽는 노드. ★새로 생기면 사람이 판단해 더한다★(트립와이어가 목록을 고정).
HISTORY = ("backtest", "strategy_backtest", "backtest_setup", "backtest_load", "backtest_compare",
           "backtest_attribution", "timing_simulation", "counterfactual", "record_robustness")


def register(registry: pg.Registry) -> None:
    for (kind, port), role in ROLES.items():
        registry.set_port_meta(kind, port, role=role)
    for (kind, port), keys in NEEDS.items():
        registry.set_port_meta(kind, port, needs=keys)
    for (kind, port), gives in GIVES.items():
        registry.set_port_meta(kind, port, gives=gives)
    for kind in HISTORY:
        registry.mark_history(kind)
