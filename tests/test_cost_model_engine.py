"""AK3·AK4 — 엔진의 비용 계산을 한 함수로, 옵트인 셋은 ★기본 꺼짐★.

## ★이 파일의 절반은 "안 바뀌었음" 을 지킨다★

`kis_backtest_engine` 은 `value * self.cfg.commission_rate` 를 **7곳**,
`value * self.cfg.slippage_rate` 를 **6곳**에서 손으로 썼다. 성분을 늘리려면
열셋을 다 고쳐야 하고 ★그것이 곧 한 곳만 빠뜨리는 길★ 이라 한 함수로 모았다.

모으면서 값이 바뀌면 안 된다. 아래 골든은 **리팩터 전에 실측한 수치**다 —
`2026-09-15`, 합성 상승·하락 계열 + 트레일링 스탑 10%.

## ★옵트인은 기본 꺼짐★

세금·스프레드·충격을 켜는 순간 저장된 모든 실행과 골든의 뜻이 바뀐다. 기본이
꺼져 있어야 기존 수치가 보존되고, 켠 실행은 `cost_model` 이 그 사실을 선언한다
(`allow_snapshot_fundamentals` 가 AH3 에서 세운 관용구).
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.domain.cost_model import STATE_CHARGED, STATE_OFF, STATE_UNMEASURABLE
from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy  # noqa: F401 — 레지스트리 등록

START = "2024-04-01"

#: ★리팩터 전 실측(2026-09-15)★ — 이 숫자가 움직이면 비용 통합이 값을 바꾼 것이다.
GOLDEN = {
    "total_return": 254335.0, "total_return_pct": 2.54, "cagr": 39.53,
    "sharpe_ratio": 2.364, "sortino_ratio": 23.52, "max_drawdown_pct": 6.32,
    "num_trades": 2, "win_rate": 50.0,
    "total_commission": 15398.0, "total_slippage": 5133.0,
}


def _df() -> pd.DataFrame:
    closes = ([100.0] * 60 + [100.0 + 5 * i for i in range(11)]
              + [150.0 - 5 * i for i in range(1, 9)])
    n = len(closes)
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=60)
    idx = idx.append(pd.bdate_range(start=START, periods=n - 60))
    s = pd.Series(closes, index=idx)
    return pd.DataFrame({"open": s, "high": s, "low": s, "close": s,
                         "volume": [10_000] * n}, index=idx)


@pytest.fixture()
def loader(monkeypatch):
    df = _df()
    import src.data.ohlcv_loader as ldr
    monkeypatch.setattr(ldr, "load_ohlcv_unified", lambda *a, **k: df.copy())
    return df


@pytest.fixture()
def master(monkeypatch):
    """S1(2026-11-19) — 켠 매도세는 종목 마스터가 시장 · 상품을 아는 종목에만 붙는다(모르면 미상).
    이 파일의 시험 종목을 코스피 주식으로 아는 고정물(세율 판정만 겨눈다)."""
    import src.kis_backtest_engine as kbe
    monkeypatch.setattr(kbe, "_master_flags", lambda: {"000111": {"market": "KOSPI", "group_code": "ST"}})


def _rate_bp(day: str) -> float:
    """그 거래일의 코스피 주식 매도세(bp) — 세율표(`sell_tax_bp_on`) 그대로."""
    import src.data.market_rules as mr
    return mr.sell_tax_bp_on(day, "KOSPI", "stock")["bp"]


def _cfg(**over) -> BacktestConfig:
    base = dict(
        symbols=["000111"], strategy_name="Condition",
        strategy_params={"buy_conditions": [
            {"factor_token": "{종가}", "function_id": "base", "params": {},
             "op": "gte", "rhs": 0}]},
        start_date=START, end_date="2024-06-28", initial_capital=10_000_000,
        commission_rate=0.0015, slippage_rate=0.0005, trailing_stop_pct=10.0,
    )
    base.update(over)
    return BacktestConfig(**base)


def _run(**over):
    eng = BacktestEngine(_cfg(**over))
    res = eng.run()
    return eng, (res.get("result") or {}).get("statistics") or {}, res


# ═══════════════════════════════════════════════════════════════════════════
# ② ★골든★ — 기본 실행의 수치가 리팩터 전과 동일하다
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("key", sorted(GOLDEN))
def test_the_default_run_is_numerically_unchanged(loader, key):
    """★이것이 이 작업의 경계 판정★ — 열셋을 한 함수로 모아도 값이 같다."""
    _, st, _ = _run()
    assert st[key] == pytest.approx(GOLDEN[key], rel=1e-9), key


def test_every_trade_still_costs_commission_plus_slippage(loader):
    """① 개별 거래 수준에서도 산수가 같다."""
    eng, _, _ = _run()
    assert eng.trades, "거래가 없으면 이 검사가 공허하다"
    for t in eng.trades:
        assert t.commission == pytest.approx(t.value * 0.0015)
        assert t.slippage == pytest.approx(t.value * 0.0005)
        assert t.tax == 0.0 and t.spread == 0.0 and t.impact == 0.0


def test_the_new_totals_are_zero_by_default(loader):
    _, st, _ = _run()
    for key in ("total_tax", "total_spread", "total_impact"):
        assert st[key] == 0.0, key


# ═══════════════════════════════════════════════════════════════════════════
# ⑥⑦ 증권거래세 — ★켜야 붙고, 매도에만★
# ═══════════════════════════════════════════════════════════════════════════
# S1(2026-11-19 받은 결정 · 의도한 변화): 켜면 고정 18bp 가 아니라 ★그 거래일 · 시장 · 상품의 세율★이다.
# 이 파일의 매도는 2024 년이라 세율은 여전히 18bp(코스피 3 + 15)지만, 기대값을 세율표에서 읽어 날짜가 바뀌어도 뜻이 같게 했다.
# 종목 마스터가 모르는 종목의 매도세는 미상이다(`test_sell_tax_trade_date.py`).

def test_switching_the_sell_tax_on_charges_sells_only(loader, master):
    eng, st, _ = _run(charge_sell_tax=True)
    sells = [t for t in eng.trades if t.side == "sell"]
    buys = [t for t in eng.trades if t.side == "buy"]
    assert sells, "매도가 없으면 이 검사가 공허하다"
    assert all(t.tax == pytest.approx(t.value * _rate_bp(t.date) / 1e4) for t in sells)
    assert all(t.tax == 0.0 for t in buys)
    assert st["total_tax"] > 0


def test_switching_the_sell_tax_on_lowers_the_return(loader, master):
    """★짝★ 켜도 아무것도 안 변하는 구현을 배제한다."""
    _, base, _ = _run()
    _, taxed, _ = _run(charge_sell_tax=True)
    assert taxed["total_return_pct"] < base["total_return_pct"]


def test_the_commission_rate_is_untouched_when_the_tax_is_on(loader, master):
    """★새 성분이 기존 성분의 **요율**을 건드리지 않는다★

    ★총액은 같지 않다 — 그리고 그것이 옳다.★ 세금이 현금을 줄이면 이후 매수
    수량이 달라지고, 그러면 거래 금액이 달라져 수수료 총액도 달라진다. 비용은
    경로를 바꾼다. 여기서 못 박을 것은 총액이 아니라 **거래당 요율**이다.
    """
    eng, _, _ = _run(charge_sell_tax=True)
    assert eng.trades
    for t in eng.trades:
        assert t.commission == pytest.approx(t.value * 0.0015)
        assert t.slippage == pytest.approx(t.value * 0.0005)


# ═══════════════════════════════════════════════════════════════════════════
# ⑧ 스프레드 — 양방향 편도 절반
# ═══════════════════════════════════════════════════════════════════════════

def test_switching_the_spread_on_charges_both_sides(loader):
    eng, st, _ = _run(charge_spread=True)
    assert st["total_spread"] > 0
    for t in eng.trades:
        assert t.spread == pytest.approx(t.value * 0.00025), t.side


# ═══════════════════════════════════════════════════════════════════════════
# ④⑤ 시장충격 — ★참여율을 모르면 0 이 아니라 미상★
# ═══════════════════════════════════════════════════════════════════════════

def test_market_impact_is_measured_when_volume_is_present(loader):
    """거래대금이 있으면 충격이 **숫자로 나온다** — ⑤ 짝."""
    eng, st, res = _run(charge_market_impact=True)
    assert st["total_impact"] > 0, "거래대금이 있는데 충격이 0 이다"
    assert res["cost_model"]["components"]["impact"]["state"] == STATE_CHARGED


def test_market_impact_without_volume_is_unmeasurable_not_zero(monkeypatch):
    """★0 은 '충격이 없었다' 는 관측이 되어 비용을 조용히 싸게 만든다★"""
    df = _df()
    df["volume"] = 0
    import src.data.ohlcv_loader as ldr
    monkeypatch.setattr(ldr, "load_ohlcv_unified", lambda *a, **k: df.copy())

    eng, st, res = _run(charge_market_impact=True)
    assert st["total_impact"] == 0.0
    block = res["cost_model"]["components"]["impact"]
    assert block["state"] == STATE_UNMEASURABLE
    assert block["reason"]
    assert res["cost_model"]["n_unmeasured_trades"] == len(eng.trades) > 0


def test_an_unmeasured_impact_is_not_the_same_as_switched_off(loader, monkeypatch):
    """③ ★같은 0 원인데 다른 사실★ — 이 둘이 결과에서 구별되어야 한다."""
    _, _, off = _run()
    df = _df(); df["volume"] = 0
    import src.data.ohlcv_loader as ldr
    monkeypatch.setattr(ldr, "load_ohlcv_unified", lambda *a, **k: df.copy())
    _, _, foggy = _run(charge_market_impact=True)

    assert off["cost_model"]["components"]["impact"]["state"] == STATE_OFF
    assert foggy["cost_model"]["components"]["impact"]["state"] == STATE_UNMEASURABLE
    assert off["cost_model"]["n_unmeasured_trades"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# ⑨⑩ ★요율은 `market_rules` 한 곳에서★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_rates_come_from_market_rules(loader, master, monkeypatch, tmp_path):
    """★엔진이 세율을 재하드코딩하면 이 검사가 죽는다★ — S1 부터 매도세는 세율표(증거 파일)에서 읽는다.

    증거 파일을 덮어써(`SELL_TAX_EVIDENCE_PATH`) 2024 년 코스피 주식 세율을 두 배로 바꾸면 매도세도 두 배가 된다.
    (옛 판: `mr.sell_tax_bp` 를 36 으로 바꿔 0.0036 을 기대했다 — 그 고정 함수는 이제 실행 준비실만 쓴다.)
    """
    import json

    import src.data.market_rules as mr
    doc = json.loads(mr.SELL_TAX_EVIDENCE_PATH.read_text(encoding="utf-8"))
    for row in doc["schedule"]:
        if (row["market"], row["instrument"], row["from"]) == ("KOSPI", "stock", "2024-01-01"):
            row["transaction_tax_bp"] *= 2
            row["rural_special_tax_bp"] *= 2
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("SELL_TAX_EVIDENCE_PATH", str(path))
    eng, _, _ = _run(charge_sell_tax=True)
    sells = [t for t in eng.trades if t.side == "sell"]
    assert sells and all(t.date.startswith("2024") for t in sells), "2024 년 매도가 있어야 이 검사가 뜻이 있다"
    assert all(t.tax == pytest.approx(t.value * 0.0036) for t in sells)


def test_all_three_on_round_trip_leaves_the_trade_date_tax_out_and_says_so(loader):
    """⑩ 셋 다 켜면 수수료 · 스프레드는 실행 준비실과 ★같은 단일 출처★(`market_rules`)다.

    S1(의도한 변화): 매도세는 거래일 · 시장 · 상품마다 달라 왕복 bp 에 넣지 않고 그 사실을 함께 낸다(옛 판은
    매도 1.5 + 18 + 2.5 = 22 를 기대했다). 실행 준비실은 여전히 고정 18bp 를 쓴다(받은 결정 — 한계로 적는다).
    """
    import src.data.market_rules as mr
    from src.domain.cost_model import round_trip_bps
    from src.kis_backtest_engine import policy_from_config

    cfg = _cfg(commission_rate=mr.commission_bp() / 1e4, slippage_rate=0.0,
               charge_sell_tax=True, charge_spread=True, charge_market_impact=True)
    rt = round_trip_bps(policy_from_config(cfg))
    # 매수 1.5 + 2.5 = 4 · 매도 1.5 + 2.5 = 4 (매도세는 빠짐 — 그 사실이 함께 실린다)
    assert rt["buy_bps"] == pytest.approx(4.0)
    assert rt["sell_bps"] == pytest.approx(4.0)
    assert rt["tax_excluded"] is True and rt["tax_reason"]
    assert mr.sell_tax_bp() == 18.0


# ═══════════════════════════════════════════════════════════════════════════
# ⑪ 결과가 비용 정책을 선언한다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_result_declares_the_cost_policy(loader):
    _, _, res = _run()
    block = res["cost_model"]
    assert set(block["components"]) == {"commission", "slippage", "tax",
                                        "spread", "impact"}
    assert block["policy"]["commission_bps"] == pytest.approx(15.0)
    assert block["policy"]["impact_coeff_note"], "설정값임을 밝혀야 한다"
    assert block["round_trip_bps"] == pytest.approx(40.0)


def test_the_declared_totals_match_the_trades(loader, master):
    """★선언이 거래와 어긋나면 그 선언은 증거가 아니다★"""
    eng, _, res = _run(charge_sell_tax=True, charge_spread=True)
    comps = res["cost_model"]["components"]
    assert comps["tax"]["krw"] > 0, "세금이 0 이면 대조가 공허하다(마스터가 종목을 알아야 붙는다)"
    assert comps["tax"]["krw"] == pytest.approx(sum(t.tax for t in eng.trades))
    assert comps["spread"]["krw"] == pytest.approx(sum(t.spread for t in eng.trades))
    assert comps["commission"]["krw"] == pytest.approx(
        sum(t.commission for t in eng.trades))


# ═══════════════════════════════════════════════════════════════════════════
# ⑫ AM5 · 결과가 **비용 설정의 판본**을 선언한다
# ═══════════════════════════════════════════════════════════════════════════
#
# 채점표 #7 은 `cost_model_version` 을 없는 축으로 적었다. 지금은 비용 설정이
# 다른 두 백테스트가 기록에서 **구별되지 않는다** — 옵트인 셋을 켜고 돌린 실행과
# 끄고 돌린 실행이 같아 보인다.

def test_the_result_declares_the_cost_model_version(loader):
    from src.domain.cost_model import POLICY_VERSION_LEN
    _, _, res = _run()
    v = res["cost_model"]["version"]
    assert isinstance(v, str) and len(v) == POLICY_VERSION_LEN


def test_turning_on_a_cost_component_changes_the_version(loader):
    """★이것이 요점이다★ — 다른 비용으로 돈 실행은 다른 판본이어야 한다."""
    _, _, off = _run()
    _, _, on = _run(charge_sell_tax=True)
    assert off["cost_model"]["version"] != on["cost_model"]["version"]


def test_the_version_matches_the_declared_policy(loader):
    """선언된 판본이 **선언된 정책에서 나온 값**인지 대조한다.

    ★상수를 실어도 통과하는 테스트는 증거가 아니다★ — 엔진이 쓴 정책으로
    직접 계산해 맞춰 본다.
    """
    from src.domain.cost_model import policy_version
    from src.kis_backtest_engine import policy_from_config
    cfg = _cfg(charge_sell_tax=True)
    _, _, res = _run(charge_sell_tax=True)
    assert res["cost_model"]["version"] == policy_version(policy_from_config(cfg))
