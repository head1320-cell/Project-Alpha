"""S1 — 일봉 엔진의 매도세: ★켰을 때만★ 거래일 · 시장 · 상품별 세율 (2026-11-19 받은 결정)

## 계약

- **꺼짐(기본)은 바이트까지 그대로다** — 통계 · `cost_model` 블록(판본 포함) · 거래 줄을 바꾸기 전에 얼린
  골든(`tests/golden/daily_engine_default_cost_run.json` · HEAD `b91d3b7` 에서 잼)과 같아야 한다.
- **켜면 매도마다 그 체결일의 세율**이다 — `market_rules.sell_tax_bp_on(체결일, 시장, 상품)`. 시장 · 상품은
  매매일지와 ★같은 판정★(`trade_journal.costs.market_and_instrument` — 종목 마스터가 아는 것만)이다.
- **모르면 0 원이 아니라 미상**이다 — 마스터가 시장 · 상품을 모르거나 세율표가 답하지 못하면(표 밖 날짜 · 등급 미달)
  그 매도의 세금은 부과하지 않고 ★미상으로 세며★ 사유를 남긴다. 18bp 로 채우지 않는다.
- 도메인(`src/domain/cost_model.py`)은 세율표 · 설정을 읽지 않는다 — 엔진이 읽어 거래마다 넘긴다(경계 유지).
- 고정 함수 `sell_tax_bp()` 와 실행 준비실(`execution_plan.py`)은 그대로다(받은 결정).

세율표의 근거는 보도 · 안내 자료 요약(T1)이라 결과는 '추론'으로 적는다 — 법령 원문과 대조하지 않았다.
시험의 종목 마스터는 이 파일이 정한 고정물이다(세율 판정만 겨눈다 — 실제 종목의 시장과 다를 수 있다).
"""
from __future__ import annotations

import json
import pathlib

import pytest

import src.data.market_rules as mr
import src.kis_backtest_engine as kbe
from src.domain.cost_model import (
    STATE_CHARGED,
    STATE_UNMEASURABLE,
    TAX_SCHEDULE_TRADE_DATE,
    CostPolicy,
    SellTaxRate,
    policy_label,
    policy_version,
    round_trip_bps,
    trade_cost,
)
from src.engine.trade_journal.costs import TAX_UNKNOWN_MESSAGES
from src.kis_backtest_engine import BacktestEngine, policy_from_config
from tests.test_cost_model_engine import _cfg, _df, _run, loader  # noqa: F401 — 같은 합성 시세 · 같은 설정

GOLDEN_DEFAULT = pathlib.Path(__file__).parent / "golden" / "daily_engine_default_cost_run.json"

KOSPI_ST = {"market": "KOSPI", "group_code": "ST"}
KOSDAQ_ST = {"market": "KOSDAQ", "group_code": "ST"}
KONEX_ST = {"market": "KONEX", "group_code": "ST"}
KOSPI_ETF = {"market": "KOSPI", "group_code": "EF", "is_etf": True}

TD = {"charge_tax": True, "tax_schedule": TAX_SCHEDULE_TRADE_DATE}


def _pol(**kw) -> CostPolicy:
    base = {"commission_bps": 15.0, "slippage_bps": 5.0}
    base.update(kw)
    return CostPolicy(**base)


def _tax_of(bd):
    return {c.name: c for c in bd.components}["tax"]


# ═══════════════════════════════════════════════════════════════════════════
# ① 도메인 — 거래별 세율을 받는 길 · ★고정 세율 정책의 옛 동작은 그대로★
# ═══════════════════════════════════════════════════════════════════════════

def test_a_trade_date_buy_pays_no_tax_without_needing_a_rate():
    """매수에는 매도세가 없다 — 거래일별 정책은 매수에 세율을 묻지 않는다(마스터를 몰라도 미상이 아니다)."""
    bd = trade_cost(1e6, "buy", _pol(**TD))
    tax = _tax_of(bd)
    assert (tax.state, tax.krw, bd.n_unmeasurable) == (STATE_CHARGED, 0.0, 0)


def test_a_fixed_policy_without_a_rate_still_marks_the_buy_unmeasurable():
    """★짝★ 고정 세율 정책의 옛 동작(세율을 못 읽으면 매수까지 미상)은 바뀌지 않았다."""
    assert _tax_of(trade_cost(1e6, "buy", _pol(charge_tax=True, tax_bps=None))).state == STATE_UNMEASURABLE


def test_a_trade_date_sell_is_charged_at_the_rate_it_is_given():
    tax = _tax_of(trade_cost(1e6, "sell", _pol(**TD), sell_tax=SellTaxRate(bp=20.0)))
    assert tax.state == STATE_CHARGED and tax.bps == 20.0 and tax.krw == pytest.approx(2000.0)


def test_a_trade_date_sell_without_a_known_rate_is_unmeasured_not_zero():
    why = mr._SELL_TAX_MESSAGES["outside_schedule"]
    bd = trade_cost(1e6, "sell", _pol(**TD), sell_tax=SellTaxRate(bp=None, reason=why, code="outside_schedule"))
    tax = _tax_of(bd)
    assert (tax.state, tax.krw, tax.reason, bd.n_unmeasurable) == (STATE_UNMEASURABLE, 0.0, why, 1)


def test_a_trade_date_sell_with_no_rate_passed_is_unmeasured():
    """부르는 쪽이 세율을 넘기지 않으면 0 원 부과가 아니라 미상이다(조용한 0 을 막는다)."""
    tax = _tax_of(trade_cost(1e6, "sell", _pol(**TD)))
    assert tax.state == STATE_UNMEASURABLE and tax.krw == 0.0 and tax.reason


@pytest.mark.parametrize("bp", [True, float("nan"), float("inf"), -1.0])
def test_a_rate_that_is_not_a_finite_non_negative_number_is_not_a_rate(bp):
    tax = _tax_of(trade_cost(1e6, "sell", _pol(**TD), sell_tax=SellTaxRate(bp=bp)))
    assert tax.state == STATE_UNMEASURABLE and tax.krw == 0.0


def test_a_fixed_policy_ignores_a_per_trade_rate():
    """★짝★ 고정 세율 정책(기존 소비자)은 거래별 세율을 받아도 제 세율을 쓴다 — 바이트 불변."""
    tax = _tax_of(trade_cost(1e6, "sell", _pol(charge_tax=True, tax_bps=18.0), sell_tax=SellTaxRate(bp=99.0)))
    assert tax.krw == pytest.approx(1800.0) and tax.bps == 18.0


def test_a_switched_off_tax_ignores_a_per_trade_rate():
    tax = _tax_of(trade_cost(1e6, "sell", _pol(tax_schedule=TAX_SCHEDULE_TRADE_DATE), sell_tax=SellTaxRate(bp=20.0)))
    assert tax.krw == 0.0 and tax.state == "off"


#: ★바꾸기 전에 잰 판본★(2026-11-19 · HEAD `b91d3b7`). 새 필드를 기본값으로 둔 정책은 그 필드가 생기기 전의
#: 정책과 같은 판본이어야 한다 — 그래야 저장된 실행과 지금 실행이 같은 설정이면 같은 판본으로 견줘진다.
VERSION_BEFORE = {"empty": "14d4aeec3d47", "15/5": "103927a44d5b", "15/5 tax18": "52170bee874c"}


def test_an_unset_tax_schedule_keeps_every_old_version():
    assert policy_version(CostPolicy()) == VERSION_BEFORE["empty"]
    assert policy_version(_pol()) == VERSION_BEFORE["15/5"]
    assert policy_version(_pol(charge_tax=True, tax_bps=18.0)) == VERSION_BEFORE["15/5 tax18"]


def test_a_trade_date_schedule_is_a_different_version():
    """★짝★ 거래일별 세율로 돈 실행은 다른 판본이다(필드를 해시에서 늘 빼는 구현을 배제)."""
    assert policy_version(_pol(**TD)) != policy_version(_pol(charge_tax=True))


def test_the_label_of_a_fixed_policy_has_exactly_the_old_keys():
    assert set(policy_label(_pol())) == {"commission_bps", "slippage_bps", "charge_tax", "tax_bps", "charge_spread",
                                          "spread_bps", "charge_impact", "impact_coeff", "impact_coeff_note"}


def test_the_label_of_a_trade_date_policy_says_where_the_rate_comes_from():
    lab = policy_label(_pol(**TD))
    assert lab["tax_schedule"] == TAX_SCHEDULE_TRADE_DATE and lab["tax_bps"] is None
    assert "거래일" in lab["tax_schedule_note"] and lab["tax_schedule_note"].endswith("니다.")


def test_a_fixed_round_trip_is_unchanged():
    rt = round_trip_bps(_pol(charge_tax=True, tax_bps=18.0))
    assert (rt["buy_bps"], rt["sell_bps"], rt["round_trip_bps"]) == (20.0, 38.0, 58.0)
    assert "tax_excluded" not in rt


def test_a_trade_date_round_trip_leaves_the_tax_out_and_says_so():
    """왕복 bp 는 모델끼리 견주는 단일 자다 — 거래일마다 다른 세율은 한 숫자에 넣지 않고 그 사실을 말한다."""
    rt = round_trip_bps(_pol(**TD))
    assert (rt["buy_bps"], rt["sell_bps"], rt["round_trip_bps"]) == (20.0, 20.0, 40.0)
    assert rt["tax_excluded"] is True and "매도세" in rt["tax_reason"] and rt["tax_reason"].endswith("니다.")


# ═══════════════════════════════════════════════════════════════════════════
# ② 엔진 — 정책을 정하는 한 자리 · 거래 하나의 세율
# ═══════════════════════════════════════════════════════════════════════════

def test_switching_the_tax_on_makes_a_trade_date_policy():
    p = policy_from_config(_cfg(charge_sell_tax=True))
    assert (p.charge_tax, p.tax_schedule, p.tax_bps) == (True, TAX_SCHEDULE_TRADE_DATE, None)


def test_switching_the_tax_off_makes_the_old_policy():
    """★짝★ 꺼진 정책은 새 필드가 기본값인 옛 정책 그대로다."""
    assert policy_from_config(_cfg()) == CostPolicy(commission_bps=15.0, slippage_bps=5.0)


def _engine(monkeypatch, flags: dict, **over) -> BacktestEngine:
    monkeypatch.setattr(kbe, "_master_flags", lambda: flags)
    return BacktestEngine(_cfg(charge_sell_tax=True, **over))


def _tax(eng: BacktestEngine, ticker: str, day: str, side: str = "sell", value: float = 1_000_000.0) -> float:
    return eng._trade_cost(value, side, ticker, day).tax


def test_the_rate_is_the_trade_day_rate_on_both_sides_of_a_boundary(monkeypatch):
    """코스피 주식: 2025 년 구간 0 + 15bp → 2026 년 구간 5 + 15bp(경계의 전날 · 다음 거래일)."""
    eng = _engine(monkeypatch, {"005930": KOSPI_ST})
    assert _tax(eng, "005930", "2025-12-31") == pytest.approx(1500.0)
    assert _tax(eng, "005930", "2026-01-02") == pytest.approx(2000.0)


def test_kosdaq_and_konex_use_their_own_rows(monkeypatch):
    """코스닥 2024 = 18bp · 코넥스 2024 = 10bp — 시장을 무시하는 구현은 코넥스에서 갈린다."""
    assert _tax(_engine(monkeypatch, {"005930": KOSDAQ_ST}), "005930", "2024-05-02") == pytest.approx(1800.0)
    assert _tax(_engine(monkeypatch, {"005930": KONEX_ST}), "005930", "2024-05-02") == pytest.approx(1000.0)


def test_an_etf_sell_is_charged_zero_not_unknown(monkeypatch):
    eng = _engine(monkeypatch, {"069500": KOSPI_ETF})
    assert _tax(eng, "069500", "2026-01-02") == 0.0
    block = eng._cost_model_block()
    assert block["components"]["tax"]["state"] == STATE_CHARGED and block["n_unmeasured_trades"] == 0
    assert block["sell_tax"]["rates_bp"] == [{"bp": 0.0, "n": 1}]


def test_a_symbol_the_master_does_not_know_is_unmeasured_not_charged(monkeypatch):
    eng = _engine(monkeypatch, {})
    assert _tax(eng, "005930", "2024-05-02") == 0.0
    block = eng._cost_model_block()
    assert block["components"]["tax"]["state"] == STATE_UNMEASURABLE
    assert block["n_unmeasured_trades"] == 1
    st = block["sell_tax"]
    assert (st["n_sells"], st["n_charged"], st["n_unmeasured"]) == (1, 0, 1)
    assert st["unmeasured"] == [{"code": "unknown_market_or_instrument", "n": 1,
                                 "message": TAX_UNKNOWN_MESSAGES["unknown_market_or_instrument"]}]


def test_the_known_symbol_on_a_known_day_is_charged_at_that_days_rate(monkeypatch):
    """★짝★ 마스터가 알면 값이다(늘 미상인 구현을 배제) — 2025 년 코스피는 15bp(옛 고정 18bp 가 아니다)."""
    assert _tax(_engine(monkeypatch, {"005930": KOSPI_ST}), "005930", "2025-05-02") == pytest.approx(1500.0)


def test_a_day_outside_the_schedule_is_unmeasured_with_the_schedule_reason(monkeypatch):
    """코넥스 2026 년과 2019-05-30 전은 세율표 밖이다 — 가까운 구간의 값으로 채우지 않는다."""
    eng = _engine(monkeypatch, {"005930": KONEX_ST, "000660": KOSPI_ST})
    assert _tax(eng, "005930", "2026-01-02") == 0.0
    assert _tax(eng, "000660", "2019-05-29") == 0.0
    st = eng._cost_model_block()["sell_tax"]
    assert st["unmeasured"] == [{"code": "outside_schedule", "n": 2, "message": mr._SELL_TAX_MESSAGES["outside_schedule"]}]


def test_a_buy_needs_no_master_and_is_not_unmeasured(monkeypatch):
    eng = _engine(monkeypatch, {})
    assert _tax(eng, "005930", "2024-05-02", side="buy") == 0.0
    block = eng._cost_model_block()
    assert block["n_unmeasured_trades"] == 0 and block["sell_tax"]["n_sells"] == 0


def test_one_unknown_sell_makes_the_tax_unmeasurable_even_if_the_last_sell_was_known(monkeypatch):
    """성분의 상태는 마지막 거래가 아니라 ★모든 매도★로 정한다(거래일별일 때)."""
    eng = _engine(monkeypatch, {"005930": KOSPI_ST})
    _tax(eng, "000111", "2024-05-02")          # 마스터가 모름
    _tax(eng, "005930", "2024-05-03")          # 마지막 매도는 앎
    block = eng._cost_model_block()
    tax = block["components"]["tax"]
    assert tax["state"] == STATE_UNMEASURABLE and "2" in tax["reason"] and "1" in tax["reason"]
    st = block["sell_tax"]
    assert (st["n_sells"], st["n_charged"], st["n_unmeasured"]) == (2, 1, 1)
    assert st["rates_bp"] == [{"bp": 18.0, "n": 1}]


def test_when_every_sell_had_a_rate_the_tax_reason_does_not_come_from_the_last_trade(monkeypatch):
    """거래일별이면 세금 성분은 ★모든 매도로★ 정한다 — 마지막 거래가 매수여도 그 매수의 문장(매도에만 부과)이
    성분의 사유로 남지 않는다(결과 화면의 비용 분해가 이 사유를 그대로 보인다 · 거래 순서에 따라 달라지면 안 된다)."""
    eng = _engine(monkeypatch, {"005930": KOSPI_ST})
    _tax(eng, "005930", "2024-05-02")                    # 매도 · 마스터가 앎
    _tax(eng, "005930", "2024-05-03", side="buy")        # 마지막 거래는 매수
    tax = eng._cost_model_block()["components"]["tax"]
    assert (tax["state"], tax["reason"]) == (STATE_CHARGED, None)


def test_with_no_sell_at_all_the_tax_reason_stays_the_buy_sentence(monkeypatch):
    """★짝★ 매도가 한 건도 없으면 부과할 매도세가 없다 — 매수의 문장(매도에만 부과 · 0 원은 미상이 아님)이 그대로다
    (사유를 늘 지우는 구현을 배제한다)."""
    eng = _engine(monkeypatch, {"005930": KOSPI_ST})
    _tax(eng, "005930", "2024-05-03", side="buy")
    tax = eng._cost_model_block()["components"]["tax"]
    assert tax["state"] == STATE_CHARGED and "매도에만" in tax["reason"]


def test_the_run_block_counts_its_unmeasurable_components(monkeypatch):
    """실행 단위 블록의 `n_unmeasurable` 은 ★미상인 성분의 수★다 — 옛 블록은 늘 0 을 실었다(세금이 미상인 실행도
    '못 잰 성분 0' 으로 읽혔다 · 2026-11-19 화면을 만들며 찾음). ★짝★ 마스터가 알면 0 이다."""
    eng = _engine(monkeypatch, {})
    _tax(eng, "005930", "2024-05-02")
    assert eng._cost_model_block()["n_unmeasurable"] == 1
    known = _engine(monkeypatch, {"005930": KOSPI_ST})
    _tax(known, "005930", "2024-05-02")
    assert known._cost_model_block()["n_unmeasurable"] == 0


def test_the_sell_tax_block_names_its_basis(monkeypatch):
    eng = _engine(monkeypatch, {"005930": KOSPI_ST})
    _tax(eng, "005930", "2024-05-02")
    st = eng._cost_model_block()["sell_tax"]
    assert st["basis"] == TAX_SCHEDULE_TRADE_DATE and st["grades"] == ["T1"] and st["label"] == "추론"
    for k in ("note", "round_trip_note"):
        assert st[k].endswith("니다.") and "—" not in st[k]


# ═══════════════════════════════════════════════════════════════════════════
# ③ 실행 전체 — 꺼짐은 바이트 불변 · 켬은 매도마다 그날의 세율
# ═══════════════════════════════════════════════════════════════════════════

def _snapshot(eng, st, res) -> dict:
    trades = [{k: getattr(t, k) for k in ("date", "ticker", "side", "price", "quantity", "value", "commission",
                                          "slippage", "tax", "spread", "impact", "pnl", "reason")} for t in eng.trades]
    return json.loads(json.dumps({"cost_model": res["cost_model"], "statistics": st, "trades": trades},
                                 ensure_ascii=False, sort_keys=True, default=str))


def test_off_is_byte_identical_to_the_frozen_default_run(loader):  # noqa: F811
    """★이것이 이 조각의 경계 판정★ — 기본 실행의 통계 · 비용 블록(판본 포함) · 거래 줄이 바꾸기 전과 같다."""
    want = json.loads(GOLDEN_DEFAULT.read_text(encoding="utf-8"))
    assert _snapshot(*_run()) == want
    assert "sell_tax" not in want["cost_model"]


def test_on_charges_each_sell_at_its_own_trade_day_rate(loader, monkeypatch):  # noqa: F811
    monkeypatch.setattr(kbe, "_master_flags", lambda: {"000111": KOSPI_ST})
    eng, _, res = _run(charge_sell_tax=True)
    sells = [t for t in eng.trades if t.side == "sell"]
    assert sells, "매도가 없으면 이 검사가 공허하다"
    for t in sells:
        bp = mr.sell_tax_bp_on(t.date, "KOSPI", "stock")["bp"]
        assert t.tax == pytest.approx(t.value * bp / 1e4), t.date
    st = res["cost_model"]["sell_tax"]
    assert (st["n_sells"], st["n_charged"], st["n_unmeasured"]) == (len(sells), len(sells), 0)
    assert sum(r["n"] for r in st["rates_bp"]) == len(sells), "세율별 건수의 합 = 부과한 매도 수"
    assert res["cost_model"]["components"]["tax"]["state"] == STATE_CHARGED


def test_on_without_the_master_is_unmeasured_not_charged(loader, monkeypatch):  # noqa: F811
    monkeypatch.setattr(kbe, "_master_flags", lambda: {})
    eng, stats, res = _run(charge_sell_tax=True)
    sells = [t for t in eng.trades if t.side == "sell"]
    assert sells and all(t.tax == 0.0 for t in sells)
    assert res["cost_model"]["components"]["tax"]["state"] == STATE_UNMEASURABLE
    assert res["cost_model"]["n_unmeasured_trades"] == len(sells)
    assert stats["total_tax"] == 0.0


def test_the_execution_desk_still_uses_the_fixed_rate():
    """받은 결정: 고정 함수 `sell_tax_bp()` 와 실행 준비실은 그대로다(켠 백테스트와 다를 수 있다 — 한계로 적는다)."""
    assert mr.sell_tax_bp() == 18.0
