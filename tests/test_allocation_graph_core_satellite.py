"""캔버스 '매매 몫 결합'(`core_satellite_mix` · K4) — 정책 백테스트(핵심) + 분봉 결과 조회(위성) → 합친 곡선 두 판
==============================================================================
구현 계획 2026-11-16 §7.5 · 설계 2026-11-17 §5. 계산은 `tests/test_core_satellite.py`(엔진 손 계산)가 건다.
여기서는 ★캔버스에 놓였을 때의 약속★을 본다:

- **같은 손 계산.** 심은 시행 흐름 · 심은 국면 답 · 지은 핵심 곡선 → 엔진 손 계산과 같은 값(보기용 반올림 안에서).
- **칸은 비어서 시작한다.** 빈 칸은 그 칸의 이름과 함께 실패한다(기본값으로 대신 계산하지 않는다) · 국면 수보다 큰 번호의 칸(숨은 칸)은 쓰지 않는다.
- **본인 것만 · 못 읽음 ≠ 없음.** 운영에서는 합성 분봉의 시행을 합치지 않는다(모의 모드는 연습용 표식) · 비용 후 손익이 없는 시행은 합치지 않는다.
- **자본 하한** = 진입 금액 × min(동시 보유 상한, 종목 수) × (1 + 수수료율) — 하한과 같으면 돈다 ↔ 1원 모자라면 거절.
- **기간.** 겹치는 날이 없거나, 겹친 구간 안에서 날이 어긋나면(쪽마다 날 수) 거절 — 없는 날의 손익을 0 으로 채우지 않는다.
- **국면.** 저장소 장애 ≠ 적재 없음 · 몫을 정하는 날의 확률을 모르면 거절 ↔ 그 밖의 날을 몰라도 돈다.
- **끝 노드.** 출력 없음 · 단추 없음 · 쓰기 0 · AI 후보가 아니다 · 주문 경로를 들이지 않는다(정적) · 과거 시뮬레이션 표시 · 한 장(유통)으로 갈 수 없다.
- 실제 정책 백테스트 노드와 실제 시행 기록을 잇는 그래프 하나(`/graph/run`) — 몫 = 같은 국면 함수의 확률 × 표.
"""
from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import numpy as np
import pytest

import src.api.allocation_graph_nodes_core_satellite as mix
from src.api import canvas_assist_routes, graph_actor
from src.api import intraday_market_regime_routes as regime_routes
from src.api.allocation_graph_nodes import REGISTRY
from src.api.allocation_graph_roles import HISTORY, ROLES
from src.data import intraday_trials as trials
from src.domain.perf_kind import backtest_label
from src.engine import portfolio_graph as pg
from src.engine.intraday import Day, Session
from tests.graph_write_guard import graph_write_guard  # noqa: F401
from tests.test_allocation_graph_arm_request import _order_path_imports
from tests.test_allocation_graph_intraday import (  # noqa: F401 — 고정물은 이름으로 들여와야 쓰인다
    _the_run_stores_table_flag_is_left_as_found,
    auth,
    client,
    graph,
    press,
    run,
    setup_node,
    table_rows,
)
from tests.test_core_satellite import by_hand_fixed, by_hand_regime
from tests.test_intraday_validate_route import WIN, weekdays, with_days

pytestmark = pytest.mark.usefixtures("graph_write_guard")

ROOT = Path(__file__).resolve().parents[1]
KIND = "core_satellite_mix"
KEY = "ab" * 32
DAYS = ["2026-02-26", "2026-02-27", "2026-03-02", "2026-03-03"]
CORE_R = [0.01, -0.02, 0.0, 0.03]                    # 엔진 손 계산과 같은 핵심 수익
PNL = [10_000.0, 0.0, -5_000.0, 20_000.0]            # ÷ 1,000,000 = 엔진 손 계산의 위성 수익
CAPITAL = 1_000_000.0
PARAMS = {"index": "KOSPI", "k": 2, "share_1": 30, "share_2": 10, "capital": CAPITAL}
PROBS = {"2026-02-26": (1.0, 0.0), "2026-02-27": (0.9, 0.1), "2026-03-02": (0.0, 1.0), "2026-03-03": (0.2, 0.8)}
NOT_FULL = "적합 창이 덜 찼습니다(필요 750 · 있음 700)."
ALICE = graph_actor.Actor("alice")
DEFAULT = object()


# ── 심는 값 ────────────────────────────────────────────────────────────────────────────
def core_value(dates: list[str] | None = None, returns: list[float] | None = None, *, before=("2026-02-25",),
               after=("2026-03-04",), cost_bps: float | None = 10.0) -> dict:
    """정책 백테스트의 답 모양 — 시작 자본 1 에서 복리한 비용 후 곡선(앞뒤에 겹치지 않는 날)."""
    ds = list(before) + list(DAYS if dates is None else dates) + list(after)
    rs = [0.004] * len(before) + list(CORE_R if returns is None else returns) + [0.002] * len(after)
    eq, v = [], 1.0
    for r in rs:
        v *= 1.0 + r
        eq.append(v)
    config = {} if cost_bps is None else {"cost_bps": cost_bps}
    return {"error": False, "dates": ds, "equity_curve": eq, "config": config,
            "perf_label": backtest_label(is_mock_data=True).to_dict()}           # 실제 생산 함수의 모양(모의 시세)


def flow(dates=None, values=None, basis="net") -> dict:
    ds, vs = list(DAYS if dates is None else dates), list(PNL if values is None else values)
    return {"basis": basis, "values": vs, "trades": [1] * len(vs), "wins": [int(v > 0) for v in vs], "dates": ds}


def stored(*, grade="E3", daily=DEFAULT, amount=500_000.0, limit=None, commission=1.5, tickers=("005930",)) -> dict:
    return {"found": True, "trial_key": KEY, "grade": grade,
            "setting": {"rule": {"kind": "opening_range_breakout", "params": {"minutes": 1}},
                        "position": {"amount": amount, "max_open_positions": limit},
                        "costs": {"commission_bp": commission, "slippage_ticks": 1}},
            "tickers": list(tickers), "from": DAYS[0], "to": DAYS[-1], "runs": 1, "updated_at": 0.0,
            "daily": flow() if daily is DEFAULT else daily}


def answer(probs: dict | None = None, *, k=2, grade="E0", empty=None, reasons: dict | None = None) -> dict:
    """시장 국면 문과 같은 함수의 답 모양 — 날마다 확률 또는 사유."""
    rows = []
    for d, p in (PROBS if probs is None else probs).items():
        rows.append({"date": d, "probs": None if p is None else list(p),
                     "top": None if p is None else int(np.argmax(p)) + 1, "top_prob": None if p is None else max(p),
                     "reason": (reasons or {}).get(d, NOT_FULL) if p is None else None})
    return {"index": "KOSPI", "name": "코스피", "k": k, "mock": True, "days": [] if empty else rows,
            "grade": None if empty else grade, "grade_reason": None, "source": "mock", "empty": empty}


@pytest.fixture()
def planted(monkeypatch) -> dict:
    """노드가 읽는 두 가지(시행의 일별 흐름 · 국면 답)를 심는다 — 남의 열쇠는 '없음', `None` 은 '못 읽음'."""
    state: dict = {"trial": stored(), "answer": answer(), "calls": []}

    def daily_of(user, key):
        state["calls"].append(("daily_of", user, key))
        if state["trial"] is None:
            return None
        return state["trial"] if (user == "alice" and key == KEY) else {"found": False}

    def regime(index, k, from_, to):
        state["calls"].append(("regime", index, k, from_.isoformat(), to.isoformat()))
        return state["answer"]

    monkeypatch.setattr(mix.trials, "daily_of", daily_of)
    monkeypatch.setattr(mix, "regime_answer", regime)
    monkeypatch.setattr(mix, "mock_allowed", lambda: True)
    return state


def go(params: dict | None = None, *, core: dict | None = None, key: str = KEY, actor=ALICE) -> pg.NodeOutput:
    spec = REGISTRY.get(KIND)
    p = spec.params_model(**(PARAMS if params is None else params))
    inputs = {"core": core_value() if core is None else core, "run": {"trial_key": key, "grade": "E3", "gates": None}}
    return spec.run(inputs, p, actor)


def refused(*args, **kw) -> str:
    with pytest.raises(pg.NodeFailure) as err:
        go(*args, **kw)
    return str(err.value)


# ── 손 계산 ─────────────────────────────────────────────────────────────────────────────
def test_the_node_gives_the_engine_hand_calculation(planted):
    v = go().view
    equity, _share, moves = by_hand_regime()
    fixed = by_hand_fixed()
    assert v["window"] == {"from": "2026-02-26", "to": "2026-03-03", "days": 4, "core_days": 6, "trial_days": 4}
    assert v["request"] == {"index": "KOSPI", "name": "코스피", "k": 2, "table_pct": [30.0, 10.0], "capital": 1_000_000.0,
                            "cost_bps": 10.0}
    assert [(m["date"], m["probs_pct"], m["target_pct"]) for m in v["months"]] == [
        ("2026-02-26", [100.0, 0.0], 30.0), ("2026-03-02", [0.0, 100.0], 10.0)]
    assert [m["moved_pct"] for m in v["months"]] == pytest.approx([30.0, moves[1]["moved"] * 100], abs=1e-4)
    regime, held = v["panels"]
    assert (regime["key"], regime["label"], held["key"], held["label"]) == ("regime", "국면 몫", "fixed", "몫 고정")
    assert regime["total_return_pct"] == pytest.approx((equity[-1] - 1) * 100, abs=1e-4)
    assert held["total_return_pct"] == pytest.approx((fixed[-1] - 1) * 100, abs=1e-4)
    assert regime["cost_pct"] == pytest.approx((moves[0]["cost"] + moves[1]["cost"]) * 100, abs=1e-6)
    assert v["fixed_share_pct"] == pytest.approx(20.0) and held["avg_target_pct"] == pytest.approx(20.0)
    curves = v["compare"]["curves"]
    assert curves["alignment"] == "date" and curves["x"] == DAYS
    assert curves["a"][-1] == pytest.approx(equity[-1] / equity[0], rel=1e-6)
    assert curves["b"][-1] == pytest.approx(fixed[-1] / fixed[0], rel=1e-6)
    assert v["compare"]["labels"] == {"a": "국면 몫", "b": "몫 고정"}
    assert ("regime", "KOSPI", 2, "2026-02-26", "2026-03-03") in planted["calls"]      # 겹친 구간으로 묻는다


def test_the_panels_are_side_by_side_with_no_winner_key(planted):
    """줄 세우지 않는다 — 판에 '더 나은' · 순위 · 이긴 쪽을 가리키는 키가 없다(두 판은 늘 같은 순서)."""
    v = go().view
    assert [p["key"] for p in v["panels"]] == ["regime", "fixed"]
    words = ("best", "better", "winner", "rank", "recommend")
    assert not any(w in key for p in v["panels"] for key in p for w in words)
    assert not any(w in key for key in v for w in words)


# ── 칸 ─────────────────────────────────────────────────────────────────────────────────
def test_every_field_starts_empty():
    fields = REGISTRY.get(KIND).params_model.model_fields
    assert {name: f.default for name, f in fields.items()} == {
        "index": None, "k": None, "share_1": None, "share_2": None, "share_3": None, "share_4": None, "capital": None}


@pytest.mark.parametrize("missing, said", [
    ("index", mix.REASONS["no_index"]), ("k", mix.REASONS["no_k"]), ("capital", mix.REASONS["no_capital"]),
    ("share_1", "국면 1"), ("share_2", "국면 2"),
])
def test_a_blank_field_refuses_with_its_name_not_a_default(planted, missing, said):
    params = {k: v for k, v in PARAMS.items() if k != missing}
    assert said in refused(params)
    assert not any(c[0] == "daily_of" for c in planted["calls"])                       # 칸을 먼저 본다 — 기록을 읽지 않는다


def test_the_third_share_is_needed_only_when_there_are_three_regimes(planted):
    planted["answer"] = answer({d: (p[0], p[1] / 2, p[1] / 2) for d, p in PROBS.items()}, k=3)
    assert "국면 3" in refused({**PARAMS, "k": 3})
    ok = go({**PARAMS, "k": 3, "share_3": 50}).view
    assert ok["request"]["table_pct"] == [30.0, 10.0, 50.0]
    assert [m["target_pct"] for m in ok["months"]] == pytest.approx([30.0, 30.0])            # (0, 0.5, 0.5) → 0.5×10 + 0.5×50


def test_a_hidden_share_beyond_k_is_not_used(planted):
    """국면 수 2 이면 셋째 · 넷째 칸은 보이지 않고(화면) 서버도 쓰지 않는다 — 값이 남아 있어도 결과가 같다(짝)."""
    plain, hidden = go().view, go({**PARAMS, "share_3": 99, "share_4": 1}).view
    assert hidden["request"]["table_pct"] == [30.0, 10.0]
    assert hidden["panels"] == plain["panels"] and hidden["months"] == plain["months"]


def test_the_share_fields_show_by_the_number_of_regimes():
    ui = {n: (f.json_schema_extra or {}).get("x-ui", {}) for n, f in REGISTRY.get(KIND).params_model.model_fields.items()}
    assert "show_if" not in ui["share_1"] and "show_if" not in ui["share_2"]
    assert ui["share_3"]["show_if"] == {"k": [3, 4]} and ui["share_4"]["show_if"] == {"k": [4]}
    assert ui["index"]["options"] == {"KOSPI": "코스피", "KOSDAQ": "코스닥"}


# ── 신원 · 기록 ───────────────────────────────────────────────────────────────────────────
def test_only_a_signed_in_user_combines(planted):
    msg = refused(actor=graph_actor.Actor(None, graph_actor.NOT_SIGNED_IN))
    assert mix.WHO in msg and graph_actor.NOT_SIGNED_IN in msg


def test_someone_elses_trial_is_the_same_as_none_and_unreadable_is_different(planted):
    gone = refused(key="cd" * 32)
    assert gone == mix.REASONS["not_found"]
    planted["trial"] = None
    assert refused() == mix.REASONS["store_unreadable"] != gone


def test_production_refuses_a_synthetic_trial_and_mock_mode_marks_it_practice(planted, monkeypatch):
    planted["trial"] = stored(grade="E0")
    out = go()
    assert out.tags["practice"] is True and out.view["synthetic"] is True                  # 짝: 모의 모드는 연습용 표식과 함께
    monkeypatch.setattr(mix, "mock_allowed", lambda: False)
    assert refused() == mix.REASONS["synthetic_in_production"]
    planted["trial"] = stored(grade="E3")
    planted["answer"] = answer(grade="E3")
    real = go(core={**core_value(), "perf_label": backtest_label(is_mock_data=False).to_dict()})   # 핵심도 실제 시세(라벨)여야 실제다
    assert real.tags["practice"] is False and real.view["synthetic"] is False


def test_mock_mode_is_practice_even_when_every_grade_reads_real(planted, monkeypatch):
    """모의 모드의 답은 그 자체로 연습용이다 — 시행 · 국면이 실데이터로 적히고 핵심의 라벨이 없어도(합성 표식과 따로).
    짝: 운영 모드면 연습용이 아니다. (첫 판에는 이 약속을 거는 시험이 없어 '모의 모드를 연습용에서 빼기' 변이가 살아남았다.)"""
    planted["answer"] = answer(grade="E3")
    unlabeled = {k: v for k, v in core_value().items() if k != "perf_label"}
    out = go(core=unlabeled)
    assert out.view["synthetic"] is False and out.view["mock"] is True and out.tags["practice"] is True
    assert out.view["compare"]["practice"] is True
    monkeypatch.setattr(mix, "mock_allowed", lambda: False)
    real = go(core=unlabeled)
    assert real.view["mock"] is False and real.tags["practice"] is False and real.view["compare"]["practice"] is False


def test_the_result_says_it_is_a_backtest_and_on_what_data(planted, monkeypatch):
    """성과 숫자는 ★무슨 성과인지★ 말한다(Z4 · `tests/test_perf_label_contract.py` — 첫 판의 화면이 이 계약을 어겨 게이트에서 찾음).
    두 판은 과거 위의 시뮬레이션이다 — 종류는 늘 `backtest`(모의투자 · 실계좌가 아니다). 데이터 축은 세 입력과 모드에서:
    하나라도 합성이거나 모의 모드면 합성 · 셋 다 실제로 적혀 있으면 실제 · 그 밖(핵심의 라벨 없음 · 시행 등급 미상)은 미상 — 실제라고 하지 않는다.
    보기와 출처(provenance)에 같은 값을 싣는다(화면의 성과 라벨과 해설이 같은 것을 읽는다)."""
    mocked = go()                                                                        # 모의 모드 · 국면 E0 · 핵심 모의 시세
    assert mocked.view["perf_label"] == backtest_label(is_mock_data=True).to_dict()
    assert mocked.provenance["perf_label"] == mocked.view["perf_label"]
    planted["answer"] = answer(grade="E3")
    real_core = {**core_value(), "perf_label": backtest_label(is_mock_data=False).to_dict()}
    # 모의 모드면 셋 다 실제로 적혀 있어도 합성 — 다른 노드와 같은 관례(`backtest_label(is_mock_data=mock_allowed())`).
    # (첫 판에는 이 경우가 없어 '모의 모드를 데이터 축에서 빼기' 변이가 살아남았다.)
    assert go(core=real_core).view["perf_label"] == backtest_label(is_mock_data=True).to_dict()
    monkeypatch.setattr(mix, "mock_allowed", lambda: False)
    assert go(core=real_core).view["perf_label"] == backtest_label(is_mock_data=False).to_dict()     # 짝: 운영에서 셋 다 실제면 실제
    unlabeled = {k: v for k, v in core_value().items() if k != "perf_label"}
    assert go(core=unlabeled).view["perf_label"] == backtest_label(is_mock_data=None).to_dict()     # 핵심의 데이터 축 미상 → 미상
    planted["trial"] = stored(grade=None)
    assert go(core=real_core).view["perf_label"] == backtest_label(is_mock_data=None).to_dict()     # 시행 등급 미상 → 미상
    planted["trial"], planted["answer"] = stored(grade="E3"), answer(grade="E0")
    with_mock_index = go(core=real_core)                                                  # 국면만 합성이어도 합성
    assert with_mock_index.view["perf_label"] == backtest_label(is_mock_data=True).to_dict()
    assert with_mock_index.provenance["perf_label"]["kind"] == "backtest"


def test_a_trial_without_net_pnl_is_refused_not_combined_gross(planted):
    planted["trial"] = stored(daily=flow(basis="gross"))
    assert refused() == mix.REASONS["gross_only"]


@pytest.mark.parametrize("daily, code", [
    (None, "no_flow"),
    ({"basis": "net", "values": [1.0, 2.0], "dates": DAYS}, "bad_flow"),
    ({"basis": "net", "values": [1.0, None, 0.0, 0.0], "dates": DAYS}, "bad_flow"),
    ({"basis": "net", "values": PNL, "dates": ["2026-02-26", "2026-02-26", "2026-03-02", "2026-03-03"]}, "bad_flow"),
])
def test_an_unreadable_flow_is_refused_with_its_own_reason(planted, daily, code):
    planted["trial"] = stored(daily=daily)
    assert refused() == mix.REASONS[code]


# ── 자본 하한 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("limit, tickers, need", [
    (None, ("005930",), 500_075),                                        # 500,000 × 1 × 1.00015 — 상한 없음 → 종목 수
    (None, ("005930", "000660", "035420"), 1_500_225),                   # × 3
    (2, ("005930", "000660", "035420"), 1_000_150),                      # 상한이 종목 수보다 작다 → × 2
    (5, ("005930", "000660"), 1_000_150),                                # 상한이 종목 수보다 크다 — 닿을 수 없다 → × 2
])
def test_the_capital_floor_is_entry_times_reachable_positions_with_fees(planted, limit, tickers, need):
    planted["trial"] = stored(limit=limit, tickers=tickers)
    ok = go({**PARAMS, "capital": need}).view                           # 하한과 같으면 돈다
    assert ok["needed_capital"] == pytest.approx(need)
    msg = refused({**PARAMS, "capital": need - 1})                       # 1원 모자라면 거절
    assert msg.startswith(mix.REASONS["capital_short"].split("{")[0]) and f"{need:,.0f}원" in msg


def test_a_setting_without_entry_amount_or_fee_rate_is_unreadable(planted):
    planted["trial"] = stored(amount=None)
    assert refused() == mix.REASONS["bad_setting"]
    planted["trial"] = stored(commission=None)
    assert refused() == mix.REASONS["bad_setting"]


# ── 기간 ───────────────────────────────────────────────────────────────────────────────
def test_no_overlap_is_refused(planted):
    late = core_value(dates=["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-06"], before=("2026-03-31",), after=())
    assert refused(core=late) == mix.REASONS["no_overlap"]


def test_a_day_on_one_side_only_inside_the_overlap_is_refused_by_side(planted):
    """없는 날의 손익을 0 으로 채우지 않는다 — 겹친 구간 안에서 날이 어긋나면 쪽마다 날 수를 적고 거절한다."""
    no_core_day = core_value(dates=["2026-02-26", "2026-02-27", "2026-03-03"], returns=[0.01, -0.02, 0.03])
    msg = refused(core=no_core_day)
    assert msg == mix.REASONS["days_mismatch"].format(core_only=0, trial_only=1)
    planted["trial"] = stored(daily=flow(dates=["2026-02-26", "2026-03-02", "2026-03-03"], values=[1.0, 2.0, 3.0]))
    assert refused() == mix.REASONS["days_mismatch"].format(core_only=1, trial_only=0)


def test_the_overlap_ends_where_either_side_ends(planted):
    """시행이 3-03 에 끝나면 배분 결과의 3-04 는 버린다(겹친 구간 4일) — 짝: 시행이 더 길면 배분 결과의 끝까지."""
    assert go().view["window"]["days"] == 4
    planted["trial"] = stored(daily=flow(dates=DAYS + ["2026-03-04", "2026-03-05"], values=PNL + [1.0, 2.0]))
    w = go().view["window"]
    assert (w["from"], w["to"], w["days"], w["trial_days"]) == ("2026-02-26", "2026-03-04", 5, 6)


def test_the_first_core_day_uses_the_starting_capital(planted):
    """배분 결과의 첫날이 겹친 구간의 첫날이면 그날 수익은 시작 자본 1 대비다(앞 날이 없다) — 첫 곡선 값 대비로 하면 첫날 수익이 0 이 된다.
    값으로 건다(첫 판은 기간만 봐서 그 변이가 살아남았다). 짝: 앞 날이 있는 곡선도 같은 손 계산(그날 수익 = 이웃 비)."""
    equity, _share, _moves = by_hand_regime()
    first = go(core=core_value(before=())).view
    assert first["window"]["from"] == "2026-02-26" and first["window"]["core_days"] == 5
    assert first["panels"][0]["total_return_pct"] == pytest.approx((equity[-1] - 1) * 100, abs=1e-4)
    later = go(core=core_value(before=("2026-02-24", "2026-02-25"))).view
    assert later["window"]["core_days"] == 7
    assert later["panels"][0]["total_return_pct"] == pytest.approx((equity[-1] - 1) * 100, abs=1e-4)


def test_an_unreadable_core_curve_is_refused(planted):
    bad = core_value()
    bad["equity_curve"] = bad["equity_curve"][:-1]
    assert refused(core=bad) == mix.REASONS["core_unreadable"]
    neg = core_value()
    neg["equity_curve"][2] = 0.0
    assert refused(core=neg) == mix.REASONS["core_unreadable"]
    assert refused(core=core_value(cost_bps=None)) == mix.REASONS["cost_unknown"]


# ── 국면 ───────────────────────────────────────────────────────────────────────────────
def test_a_regime_store_failure_is_not_the_same_as_nothing_loaded(planted):
    planted["answer"] = answer(empty={"reason": "store_error", "message": "읽기 실패"})
    store = refused()
    planted["answer"] = answer(empty={"reason": "not_loaded", "message": "코스피 지수 일봉이 적재돼 있지 않습니다."})
    nothing = refused()
    assert store == mix.REASONS["regime_store"] and nothing.startswith(mix.REASONS["regime_unavailable"])
    assert "코스피 지수 일봉이 적재돼 있지 않습니다." in nothing and store != nothing


def test_an_unknown_probability_on_a_share_setting_day_is_refused(planted):
    planted["answer"] = answer({**PROBS, "2026-03-02": None})
    msg = refused()
    assert msg.startswith(mix.REASONS["regime_unknown"]) and "2026-03-02" in msg and NOT_FULL in msg
    planted["answer"] = answer({d: p for d, p in PROBS.items() if d != "2026-02-26"})   # 지수 일봉이 없는 날
    msg = refused()
    assert "2026-02-26" in msg and mix.NO_INDEX_DAY in msg


def test_an_unknown_probability_on_another_day_does_not_matter(planted):
    """짝: 몫을 정하는 날(첫날 · 달의 첫 거래일)의 확률만 쓴다 — 다른 날의 확률을 몰라도 같은 답이다."""
    plain = go().view
    planted["answer"] = answer({**PROBS, "2026-02-27": None, "2026-03-03": None})
    other = go().view
    assert other["panels"] == plain["panels"] and other["months"] == plain["months"]


def test_probabilities_that_do_not_fit_k_are_refused_as_a_regime_defect(planted):
    planted["answer"] = answer({d: (p[0], p[1] / 2, p[1] / 2) for d, p in PROBS.items()}, k=3)
    assert refused() == mix.REASONS["regime_shape"]


def test_a_daily_loss_beyond_the_sleeve_capital_is_refused_not_wrapped(planted):
    planted["trial"] = stored(daily=flow(values=[10_000.0, -1_000_000.0, 0.0, 0.0]))
    assert refused() == mix.ENGINE_REFUSALS["return_at_or_below_minus_one"]


# ── 보기 · 해설 ──────────────────────────────────────────────────────────────────────────
def test_the_view_carries_grades_notes_and_the_cost_basis_line(planted):
    out = go()
    v = out.view
    assert v["grades"] == {"trial": "E3", "regime": "E0", "core_mock": True} and v["synthetic"] is True   # 국면이 합성(모의 지수)
    assert v["notes"] == list(mix.NOTES)
    ex = REGISTRY.get(KIND).explain(v, out.provenance or {}, REGISTRY.get(KIND).params_model(**PARAMS))
    trust = " ".join(t["text"] for t in ex["trust"])
    assert "그날 분봉 손익(비용 후) ÷ 매매 몫 자본" in trust and "놀리는 자본" in trust and "10bp" in trust
    assert any("비용 전" in f and "샤프" in f for f in ex["facts"])                           # 배분 요약의 비용 기준
    assert "합친 것이 더 낫다는 증거(경제적 가치)" in ex["unmeasured"]
    assert any("국면 몫" in f for f in ex["facts"]) and any("몫 고정" in f for f in ex["facts"])


def test_the_view_rounds_for_display_only(planted):
    v = go().view
    for p in v["panels"]:
        for key in ("total_return_pct", "max_drawdown_pct", "avg_share_pct", "cost_pct"):
            assert round(p[key], 6) == p[key], key


def test_probabilities_keep_four_decimals_so_the_screen_rounds_only_once(planted):
    """화면은 확률을 소수 첫째 자리로 보인다 — 서버가 둘째 자리로 먼저 반올림해 싣으면 27.4471% 가 27.45 를 거쳐 27.5% 로 보인다(두 번 반올림).
    목표 몫 · 옮긴 몫과 같이 넷째 자리로 싣는다(E2E 에서 찾음)."""
    probs = dict(PROBS)
    probs["2026-02-26"] = (0.274471, 0.725529)
    planted["answer"] = answer(probs)
    v = go().view
    assert v["months"][0]["probs_pct"] == [27.4471, 72.5529]
    assert v["months"][1]["probs_pct"] == [0.0, 100.0]


def test_a_core_on_mock_prices_is_practice_even_when_the_trial_and_the_index_are_real(planted, monkeypatch):
    """핵심(정책 백테스트)이 모의 시세 위의 곡선이면 합친 결과도 연습용이다 — 시행 · 국면 등급만 보면 놓친다(계획 §7.5 의 보기 계약:
    등급 = 시행 · 국면 · 배분 결과의 성과 라벨). 짝: 실제 시세면 아니다 · 라벨이 없으면 미상(실제라고 하지 않는다)."""
    monkeypatch.setattr(mix, "mock_allowed", lambda: False)
    planted["answer"] = answer(grade="E3")
    mocked = go(core={**core_value(), "perf_label": backtest_label(is_mock_data=True).to_dict()})
    assert mocked.view["grades"] == {"trial": "E3", "regime": "E3", "core_mock": True}
    assert mocked.view["synthetic"] is True and mocked.tags["practice"] is True
    real = go(core={**core_value(), "perf_label": backtest_label(is_mock_data=False).to_dict()})
    assert real.view["grades"]["core_mock"] is False
    assert real.view["synthetic"] is False and real.tags["practice"] is False
    unlabeled = go(core={k: v for k, v in core_value().items() if k != "perf_label"})
    assert unlabeled.view["grades"]["core_mock"] is None
    unknown = go(core={**core_value(), "perf_label": backtest_label(is_mock_data=None).to_dict()})   # 라벨은 있으나 데이터 축이 미상
    assert unknown.view["grades"]["core_mock"] is None and unknown.view["synthetic"] is False


# ── 자리 ───────────────────────────────────────────────────────────────────────────────
def test_the_node_is_a_terminal_check_node_with_two_required_inputs():
    spec = REGISTRY.get(KIND)
    assert [(p.name, p.type, p.required) for p in spec.inputs] == [("core", "BacktestResult", True), ("run", "IntradayRun", True)]
    assert spec.outputs == () and spec.save is None and spec.save_label is None                # 끝 노드 · 단추 없음
    assert (spec.stage, spec.category, spec.wants_actor, spec.plain_label) == ("check", "백테스트", True, "매매 몫 결합")
    assert spec.simulates_history is True and KIND in HISTORY
    assert ROLES[(KIND, "core")].endswith("다.") and ROLES[(KIND, "run")].endswith("다.")


def test_the_module_stands_alone_and_keeps_the_registry_field_shape():
    """이 모듈은 등록부 모듈을 들이지 않는다(그 모듈이 끝에서 이것을 등록한다 — 먼저 들여도 깨지지 않는다) · 칸의 꼴은 같다."""
    import src.api.allocation_graph_nodes as gn
    source = (ROOT / "src/api/allocation_graph_nodes_core_satellite.py").read_text(encoding="utf-8")
    assert "allocation_graph_nodes import" not in source and "import src.api.allocation_graph_nodes\n" not in source
    assert mix._ui("지수", question="q", unit="%") == gn._ui("지수", question="q", unit="%")
    assert mix._ui("x", "advanced") == gn._ui("x", "advanced")
    assert mix._FORBID == gn._FORBID


def test_the_tool_does_not_offer_it():
    assert KIND in mix.NOT_OFFERED and KIND not in canvas_assist_routes.offered_kinds()


def test_the_module_never_imports_the_order_path():
    source = (ROOT / "src/api/allocation_graph_nodes_core_satellite.py").read_text(encoding="utf-8")
    assert _order_path_imports(source) == []


# ── 실제 그래프 하나 ─────────────────────────────────────────────────────────────────────
def _days(n: int, start: date) -> list[Day]:
    t, o, h, low, c, v = zip(*WIN)
    return [Day(d, {"005930": Session("005930", d, np.array(t), np.array(o, float), np.array(h, float), np.array(low, float),
                                      np.array(c, float), np.array(v, float), "kis", None, "KOSPI", "stock", "삼성전자")})
            for d in weekdays(n, start)]


def _real_graph(key: str, **params) -> dict:
    nodes = [{"id": "u", "type": "universe", "params": {"tickers": ["005930", "000660", "035420"]}},
             {"id": "r", "type": "returns", "params": {"lookback_days": 252, "as_of": "2026-06-30"}},
             {"id": "e", "type": "estimate", "params": {}},
             {"id": "o", "type": "optimizer", "params": {}},
             {"id": "b", "type": "backtest", "params": {"rebalance": "M", "cost_bps": 10}},
             {"id": "l", "type": "intraday_load", "params": {"trial_key": key}},
             {"id": "m", "type": KIND, "params": {**PARAMS, "capital": 2_000_000, **params}}]   # 진입 1,000,000 × 1종목 × 1.00015 이상
    pairs = [("u", "universe", "r", "universe"), ("r", "returns", "e", "returns"), ("r", "returns", "o", "returns"),
             ("e", "belief", "o", "belief"), ("r", "returns", "b", "returns"), ("o", "weights", "b", "weights"),
             ("b", "backtest", "m", "core"), ("l", "run", "m", "run")]
    edges = [{"source": s, "source_port": sp, "target": t, "target_port": tp} for s, sp, t, tp in pairs]
    return graph(*nodes, edges=edges)


def test_a_real_policy_backtest_and_a_real_trial_combine_with_the_same_regime_function(client, auth, monkeypatch):
    days = _days(10, date(2026, 2, 23))                                  # 2026-02-23 ~ 03-06 — 두 달에 걸친 열흘
    with_days(monkeypatch, days)
    key = press(client, graph(setup_node(start_date="2026-02-23", end_date="2026-03-06")), "s", auth)["saved_id"]
    before = table_rows()
    out = run(client, _real_graph(key), auth)
    m = out["m"]
    assert m["status"] == "ok", m["reason"]
    assert table_rows() == before                                        # 쓰기 0
    v = m["view"]
    assert (v["window"]["from"], v["window"]["to"], v["window"]["days"]) == ("2026-02-23", "2026-03-06", 10)
    same = regime_routes.regime_answer("KOSPI", 2, date(2026, 2, 23), date(2026, 3, 6))
    probs = {row["date"]: row["probs"] for row in same["days"]}
    want = [probs[d][0] * 0.3 + probs[d][1] * 0.1 for d in ("2026-02-23", "2026-03-02")]
    assert [mo["date"] for mo in v["months"]] == ["2026-02-23", "2026-03-02"]
    assert [mo["target_pct"] for mo in v["months"]] == pytest.approx([w * 100 for w in want], abs=1e-4)
    assert v["fixed_share_pct"] == pytest.approx((want[0] * 5 + want[1] * 5) / 10 * 100, abs=1e-4)
    assert v["grades"]["regime"] == "E0" and v["synthetic"] is True                       # 모의 지수 — 연습용


def test_a_graph_with_the_mix_cannot_become_a_client_sheet(client, auth, monkeypatch):
    days = _days(10, date(2026, 2, 23))
    with_days(monkeypatch, days)
    key = press(client, graph(setup_node(start_date="2026-02-23", end_date="2026-03-06")), "s", auth)["saved_id"]
    g = _real_graph(key)
    seen = {nid: r["view_hash"] for nid, r in run(client, g, auth).items()}
    assert seen["m"] is not None
    assert pg.run_for_sheet(g, "m", seen, REGISTRY)["ok"] is False      # 한 장은 실행자 없이 다시 계산한다 → 거절
