"""과거 시점 뷰를 ★그때 알 수 있던 재무★ 로 만든다 (U3·U4)

## 무엇이 문제였나

`company_views(as_of=…)` 는 **뷰를 하나도 내지 않고 전 종목을 거부**했다.
소스가 이유를 적어 뒀다:

    as_of={as_of} 시점의 **빈티지 재무**를 이 경로가 아직 쓰지 않습니다
    (has_vintage=false) — 오늘 재무로 과거 뷰를 만들면 룩어헤드가 되므로 거부합니다.

그 거부는 옳았다. 그런데 V3 의 `history_as_of()` 가 정확히 그 일을 하게 됐으므로
거부의 **전제**가 고칠 수 있는 상태가 됐다.

## ★거부가 사라지는 것이 아니라 대상이 바뀐다★

빈티지가 없는 종목은 **여전히** `no_vintage_financials` 사유다 — 오늘 재무로
조용히 대체하지 않는다. 바뀌는 것은 "빈티지가 있는 종목도 함께 거부하던" 부분뿐이다.

## ★재무만 as-of 다★

`rf`·`erp`·`beta`·시가총액·가격은 **아직 오늘 값**이다. 재무만 시점 정합으로
바꾸고 나머지를 말하지 않으면 "as-of 뷰" 라는 이름이 거짓이 된다. 그래서
`as_of_inputs` 가 무엇이 시점 정합이고 무엇이 아닌지를 이름으로 밝힌다 —
0단계가 `price_basis`·`universe` 에 쓴 것과 같은 규율이다.

## ★게이트는 열지 않았다★

`_usage()` 의 `has_vintage=False` 는 그대로다(사용자 결정). `depth_ok` 가 재무
**이력**의 깊이를 재지 **빈티지**의 깊이를 재지 않아서, 라벨을 고치는 것과
게이트를 여는 것은 다른 작업이다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

import src.engine.valuation.valuation_distribution as VD  # noqa: E402
from src.engine.company_views import KIND_NO_VINTAGE, company_views  # noqa: E402

CODES = ["005930", "000660"]
PRICES = {"005930": 1000.0, "000660": 2000.0}


def _dist(p50: float, *, as_of: str | None = None) -> dict:
    """`valuation_distribution_for` 가 내는 모양의 최소본."""
    out = {
        "available": True, "corp_name": "테스트",
        "unified": {"available": True, "p10": p50 * 0.8, "p50": p50, "p90": p50 * 1.2},
        "base_assumptions": {"years": 5.0},
        "is_mock": False,
    }
    if as_of:
        out["as_of"] = as_of
        out["as_of_inputs"] = VD.AS_OF_INPUTS
    return out


def _install(monkeypatch, fn) -> list:
    calls: list = []

    def _spy(code, price, **kw):
        calls.append({"code": code, "price": price, **kw})
        return fn(code, price, **kw)

    monkeypatch.setattr(VD, "valuation_distribution_for", _spy)
    return calls


# ═══════════════════════════════════════════════════════════════════════════
# ① as-of 뷰가 나온다 (예전에는 전 종목 거부)
# ═══════════════════════════════════════════════════════════════════════════

def test_an_asof_view_is_produced_when_vintages_exist(monkeypatch):
    _install(monkeypatch, lambda c, p, **kw: _dist(p * 1.3, as_of=kw.get("as_of")))
    views, reasons = company_views(CODES, PRICES, as_of="2025-04-01")
    assert len(views) == 2, (views, reasons)
    assert reasons == {}, reasons


def test_the_asof_is_passed_down_not_dropped(monkeypatch):
    calls = _install(monkeypatch, lambda c, p, **kw: _dist(p * 1.3, as_of=kw.get("as_of")))
    company_views(CODES, PRICES, as_of="2025-04-01")
    assert all(c.get("as_of") == "2025-04-01" for c in calls), calls


def test_without_asof_the_today_path_is_unchanged(monkeypatch):
    """★오늘 경로는 한 자리도 안 바뀐다★ — `as_of` 를 넘기지 않는다."""
    calls = _install(monkeypatch, lambda c, p, **kw: _dist(p * 1.3))
    views, _ = company_views(CODES, PRICES)
    assert len(views) == 2
    assert all("as_of" not in c or c["as_of"] is None for c in calls), calls


# ═══════════════════════════════════════════════════════════════════════════
# ②④ ★거부는 남는다 — 대상이 바뀔 뿐이다★
# ═══════════════════════════════════════════════════════════════════════════

def test_a_ticker_without_vintages_is_still_refused(monkeypatch):
    """★오늘 재무로 조용히 대체하지 않는다★"""
    def _fn(code, price, **kw):
        if code == "000660":
            return {"available": False,
                    "reason": "2025-04-01 시점에 쓸 수 있는 재무 빈티지가 없습니다"}
        return _dist(price * 1.3, as_of=kw.get("as_of"))

    _install(monkeypatch, _fn)
    views, reasons = company_views(CODES, PRICES, as_of="2025-04-01")
    assert [v["assets"] for v in views] == [["005930"]], views
    assert "000660" in reasons, reasons
    assert reasons["000660"]["kind"] == KIND_NO_VINTAGE, reasons["000660"]
    assert "빈티지" in reasons["000660"]["reason"], reasons["000660"]


def test_every_code_is_covered_by_a_view_or_a_reason(monkeypatch):
    """기존 계약 유지 — ★조용히 빠지는 종목이 없다★"""
    def _fn(code, price, **kw):
        if code == "000660":
            return {"available": False, "reason": "빈티지가 없습니다"}
        return _dist(price * 1.3, as_of=kw.get("as_of"))

    _install(monkeypatch, _fn)
    views, reasons = company_views(CODES, PRICES, as_of="2025-04-01")
    covered = {a for v in views for a in v["assets"]} | set(reasons)
    assert covered == set(CODES), covered


def test_a_distribution_failure_under_asof_is_labelled_no_vintage(monkeypatch):
    """as-of 에서 분포가 안 나오는 지배적 원인은 빈티지 부재다 — 그렇게 라벨한다."""
    _install(monkeypatch, lambda c, p, **kw: {"available": False, "reason": "빈티지 없음"})
    _, reasons = company_views(CODES, PRICES, as_of="2025-04-01")
    assert all(r["kind"] == KIND_NO_VINTAGE for r in reasons.values()), reasons
    assert all(r.get("as_of") == "2025-04-01" for r in reasons.values()), reasons


# ═══════════════════════════════════════════════════════════════════════════
# ③ ★알맹이★ 정정 전/후로 뷰가 달라진다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_view_changes_across_a_restatement(monkeypatch):
    """정정 전에는 원본 적정가, 후에는 정정 적정가 — ★as-of 가 실제로 걸린다★"""
    def _fn(code, price, **kw):
        # 정정 전이면 적정가가 높고(원본 매출 1000), 후면 낮다(정정 900)
        p50 = price * (1.5 if kw.get("as_of") == "2025-04-01" else 1.1)
        return _dist(p50, as_of=kw.get("as_of"))

    _install(monkeypatch, _fn)
    before, _ = company_views(["005930"], PRICES, as_of="2025-04-01")
    after, _ = company_views(["005930"], PRICES, as_of="2025-07-01")
    assert before[0]["magnitude_pct"] != after[0]["magnitude_pct"], (before, after)


# ═══════════════════════════════════════════════════════════════════════════
# ⑤⑥ ★재무만 as-of 다★ · 게이트는 닫혀 있다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_view_names_which_inputs_are_still_today(monkeypatch):
    _install(monkeypatch, lambda c, p, **kw: _dist(p * 1.3, as_of=kw.get("as_of")))
    views, _ = company_views(["005930"], PRICES, as_of="2025-04-01")
    got = views[0]["as_of_inputs"]
    assert got["financials"] == "vintage", got
    # ★아직 오늘 값인 것들을 이름으로 밝힌다★
    for k in ("price", "params", "market_cap"):
        assert k in got, f"{k} 가 빠졌다 — 시점 정합인 척하게 된다"
        assert got[k] != "vintage", (k, got[k])


def test_the_asof_view_is_still_forward_only(monkeypatch):
    """★게이트는 열지 않았다★ — 배선과 게이트는 다른 작업이다."""
    _install(monkeypatch, lambda c, p, **kw: _dist(p * 1.3, as_of=kw.get("as_of")))
    views, _ = company_views(["005930"], PRICES, as_of="2025-04-01")
    assert views[0]["research_usage"] == "forward_only", views[0]


def test_the_view_carries_the_asof_date(monkeypatch):
    _install(monkeypatch, lambda c, p, **kw: _dist(p * 1.3, as_of=kw.get("as_of")))
    views, _ = company_views(["005930"], PRICES, as_of="2025-04-01")
    assert views[0]["as_of"] == "2025-04-01", views[0]


def test_a_today_view_does_not_claim_an_asof(monkeypatch):
    """★짝★ 오늘 뷰에 as_of 를 지어 넣지 않는다."""
    _install(monkeypatch, lambda c, p, **kw: _dist(p * 1.3))
    views, _ = company_views(["005930"], PRICES)
    assert views[0].get("as_of") is None, views[0]


# ═══════════════════════════════════════════════════════════════════════════
# ⑪ 합성이 끼어들지 않는다 — `valuation_distribution_for` 층
# ═══════════════════════════════════════════════════════════════════════════

def test_the_asof_path_never_calls_load_statement(monkeypatch):
    """★`load_statement` 는 오늘 재무를 가져온다★ as-of 가 그걸 타면 룩어헤드다."""
    from src.engine.valuation.valuation_models import ValuationEngine

    def _boom(*a, **k):
        raise AssertionError("as-of 경로가 오늘 재무 로더를 탔다")

    monkeypatch.setattr(ValuationEngine, "load_statement", _boom)
    monkeypatch.setattr("src.data.dart_history.statement_as_of",
                        lambda t, a, **k: (None, "빈티지 없음"))
    out = VD.valuation_distribution_for("005930", 1000.0, as_of="2025-04-01")
    assert out["available"] is False
    assert "빈티지" in (out.get("reason") or ""), out


def test_the_asof_path_reports_the_loader_reason_verbatim(monkeypatch):
    """★사유를 뭉개지 않는다★ — 못 읽음/없음/연간 없음이 그대로 올라온다."""
    monkeypatch.setattr("src.data.dart_history.statement_as_of",
                        lambda t, a, **k: (None, "financials_vintages 를 읽지 못했습니다: X"))
    out = VD.valuation_distribution_for("005930", 1000.0, as_of="2025-04-01")
    assert "읽지 못했" in out["reason"], out


def test_the_inputs_map_is_a_single_source(monkeypatch):
    """화면과 뷰가 같은 상수를 본다 — 두 벌이면 갈라진다."""
    assert VD.AS_OF_INPUTS["financials"] == "vintage"
    assert set(VD.AS_OF_INPUTS) >= {"financials", "price", "params", "market_cap"}


@pytest.mark.parametrize("as_of", [None, ""])
def test_a_falsy_asof_takes_the_today_path(as_of, monkeypatch):
    """빈 문자열을 as-of 로 읽어 빈티지를 뒤지지 않는다."""
    def _boom(*a, **k):
        raise AssertionError("as-of 경로를 탔다")

    monkeypatch.setattr("src.data.dart_history.statement_as_of", _boom)
    monkeypatch.setattr(
        "src.engine.valuation.valuation_models.ValuationEngine.load_statement",
        lambda self, c, p, **k: {"available": False, "reason": "오늘 경로", "fs": None,
                                 "corp_name": "", "is_mock": False})
    out = VD.valuation_distribution_for("005930", 1000.0, as_of=as_of)
    assert out["reason"] == "오늘 경로", out


# ═══════════════════════════════════════════════════════════════════════════
# ★눈으로 돌려 보고 나서야 드러난 결함 — 그래서 진짜 체인으로 못 박는다★
#
# 위 검사들은 `valuation_distribution_for` 를 가짜로 바꿔 배선만 봤다. 그런데
# 목업 DB 로 **실제로** 돌려 보니 정정 전/후 재무가 달라도 적정가가 한 자리도
# 바뀌지 않았다(양쪽 p50=169.0). 원인: as-of 경로가 `load_statement` 안의
# **준비 구간**(발행주식수·capex 보강 + `compute_ratios`)을 건너뛰어 `eps`·`bps`
# 가 비어 있었다 — 그 함수의 독스트링이 *"자기가 다시 불러오면 이 손질을 복제하게
# 된다"* 고 경고한 바로 그 실수를 **복제가 아니라 누락**으로 저질렀다.
#
# ★배선 테스트는 이 결함을 볼 수 없다★ 그래서 여기서는 가짜를 끼우지 않고
# 인메모리 DB → 빈티지 → 밸류에이션 → 뷰까지 **끝까지** 돌린다.
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def seeded(monkeypatch):
    """하향 정정 2건이 심긴 인메모리 DB — 원본 NI 1200 → 정정 700."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from src.data import dart_history as dh
    from src.data.dart_client import FinancialStatement

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    dh.ensure_history_table(eng)
    assert dh.ensure_vintage_table(eng)
    monkeypatch.setattr(dh, "_get_engine", lambda e=None: eng)

    def _mk(rcept_no, rcept_dt, revenue, ni):
        f = FinancialStatement(corp_code="00126380", corp_name="삼성전자",
                               bsns_year="2024", reprt_code="11011")
        f.revenue, f.net_income = revenue, ni
        f.total_assets, f.total_liabilities, f.total_equity = 20000.0, 12000.0, 8000.0
        f.shares_outstanding, f.dps = 100.0, 30.0
        f.operating_cf, f.capex = 900.0, 200.0
        f.rcept_no, f.rcept_dt = rcept_no, rcept_dt
        return f

    dh.upsert_statement(eng, "005930", _mk("20250314000777", "2025-03-14", 10000.0, 1200.0))
    dh.upsert_statement(eng, "005930", _mk("20250620000999", "2025-06-20", 9000.0, 700.0))
    yield eng
    eng.dispose()


def test_the_real_chain_produces_different_fair_values(seeded):
    """★알맹이 — 가짜 없이★ 정정 전후로 적정가가 실제로 달라진다."""
    before = VD.valuation_distribution_for("005930", 1000.0, as_of="2025-04-01")
    after = VD.valuation_distribution_for("005930", 1000.0, as_of="2025-07-01")
    assert before["available"] and after["available"], (before, after)
    assert before["unified"]["p50"] != after["unified"]["p50"], (
        "정정 전후 재무가 다른데 적정가가 같다 — 준비 구간을 건너뛰었을 때의 증상이다")


def test_the_statement_reaches_the_models_with_ratios(seeded):
    """★준비 구간을 실제로 탄다★ — `eps`/`bps` 가 비면 모델이 상수로 떨어진다."""
    from src.data import dart_history as dh
    from src.engine.valuation.valuation_models import ValuationEngine
    fs, why = dh.statement_as_of("005930", "2025-04-01")
    assert fs is not None, why
    assert fs.eps is None, "픽스처 전제: 준비 전에는 비어 있다"
    ValuationEngine.prepare_statement(fs, 1000.0)
    assert fs.eps is not None and fs.bps is not None, "준비 구간이 비율을 안 채웠다"


def test_the_real_chain_still_refuses_a_ticker_without_vintages(seeded):
    """★짝★ 같은 DB 에서 빈티지 없는 종목은 여전히 거부된다."""
    out = VD.valuation_distribution_for("000660", 2000.0, as_of="2025-07-01")
    assert out["available"] is False
    assert "빈티지" in out["reason"], out


def test_the_real_chain_names_the_company_deterministically(seeded):
    """★`stock_master` 가 단일 진실 공급원★ — "Unknown Corp" 를 만들지 않는다."""
    out = VD.valuation_distribution_for("005930", 1000.0, as_of="2025-04-01")
    assert out["corp_name"], out
    assert "Unknown" not in str(out["corp_name"]), out
