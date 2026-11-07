"""실데이터 경로가 ★값을 지어내지 않는다★ (합성 재무값 → None)

## 무엇이 문제였나

`FundamentalsStore._real_raw_financials` 는 **실데이터 경로**다(mock 게이트 뒤가
아니다). 그런데 DART 값이 없으면 하드코딩된 비율로 값을 만들어 냈다 — 27곳:

    gross_profit = revenue * 0.3          current_assets = total_assets * 0.4
    operating_cf = operating_profit * 1.1 capex = revenue * 0.05
    mcap = total_equity * 1.2             interest_expense = total_liabilities * 0.03
    revenue_prev = revenue * 0.95         shares = 10000
    cash/rnd/sga/depreciation = revenue * (0.25/0.03/0.12/0.04)   ...

실측: DART 가 실수 **6개**(매출·영업이익·순이익·자산·자본·부채)만 준 종목에서
파생 팩터 **64개 중 57개에 값**이 나갔다. `pbr = 1.2`(가정 상수 그대로),
`revenue_growth_yoy = 5.26%`(0.95 상수 — **어떤 종목이든 동일**),
`gross_margin = 30.0`. 스크리너가 그 위에서 순위를 매겼다.

CLAUDE.md §6: *"운영에서는 합성값을 만들지 않습니다 — 실패하면 None + 사유."*

## 이 파일이 거는 두 계약

① **미상은 `None` 이다** — 지어내지도, 0 으로 만들지도 않는다.
② ★**완전 적재면 결과가 하나도 안 바뀐다**★ — DART 가 다 있으면 오늘과 똑같이
   동작해야 한다. 이것이 이 작업의 핵심 계약이다.

## ★해네스 함정을 한 번 밟았다★

완전 적재 픽스처의 연도별 감쇠율을 처음에 **0.95** 로 잡았는데, 그것이 조작
상수(`revenue_prev = revenue * 0.95`)와 **정확히 같아** 실측을 썼는지 조작을
썼는지 구별할 수 없었다(양쪽 다 `revenue_growth_yoy = 5.26%`). **0.11** 로 바꿔
12.36% 가 나오는 것을 확인한 뒤에야 골든으로 인정했다.
"""
from __future__ import annotations

import hashlib
import json
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.data.fundamentals_store import FundamentalsStore  # noqa: E402

#: ★조작 상수(0.95·0.93·0.94·0.8·0.78)와 겹치지 않는 감쇠율★
_DECAY = 0.11
_CUR_YEAR_OFFSET = 1        # `_real_raw_financials` 는 datetime.now().year - 1 부터 본다


class _Full:
    """DART 가 **전부** 적재된 연도."""

    def __init__(self, m: float = 1.0):
        self.revenue = 1000e8 * m
        self.operating_profit = 100e8 * m
        self.net_income = 80e8 * m
        self.total_assets = 2000e8 * m
        self.total_equity = 800e8 * m
        self.total_liabilities = 1200e8 * m
        self.gross_profit = 320e8 * m
        self.current_assets = 900e8 * m
        self.current_liabilities = 500e8 * m
        self.inventory = 180e8 * m
        self.operating_cf = 120e8 * m
        self.investing_cf = -60e8 * m
        self.shares_outstanding = 5e7
        self.dps = 1000
        self.eps = None
        self.is_mock = False

    def __getattr__(self, name):
        return None


class _Sparse(_Full):
    """DART 가 **핵심 6개만** 준 연도 — 실데이터에서 흔하다."""

    def __init__(self, m: float = 1.0):
        super().__init__(m)
        for f in ("gross_profit", "current_assets", "current_liabilities",
                  "inventory", "operating_cf", "investing_cf",
                  "shares_outstanding", "dps"):
            setattr(self, f, None)


def _store(by_year_cls, years: int = 4):
    """연도별 재무를 주는 스토어. `years` 만큼 과거로 채운다(0 이면 당해만)."""
    from datetime import datetime
    st = FundamentalsStore.__new__(FundamentalsStore)
    cur = datetime.now().year - _CUR_YEAR_OFFSET
    table = {cur - i: by_year_cls(1.0 - _DECAY * i) for i in range(years)}
    st._get_fs = lambda dart, code, year, **kw: table.get(year)
    st._market_snapshot = lambda code: {"mcap_억": 12000.0, "price": 24000.0}
    return st


def _factors(st) -> dict:
    raw = st._real_raw_financials("005930")
    assert raw is not None, "픽스처가 핵심 5필드 게이트를 통과하지 못했다"
    return raw, st._derive_factors("005930", raw)


# ══ ① 완전 적재 — 결과 불변 ═══════════════════════════════════════════════

#: ★계획이 측정에 뒤집힌 지점 — 기록해 둔다★
#: 처음에는 "완전 적재면 64개 전부 불변" 을 계약으로 잡았다. 틀렸다. `cash`·`rnd`·
#: `sga`·`depreciation`·`interest_expense` 는 **DART 재무제표가 애초에 주지 않는**
#: 항목이라, '완전 적재' 종목에서도 예전엔 항상 조작값이었다(매출의 몇 %). 그것을
#: 제거하면 그 항목에 의존하는 팩터는 완전 적재에서도 미상이 된다 — 그것이 옳다.
#:
#: 그래서 계약을 실측으로 다시 썼다: **아래 12개를 뺀 52개는 비트 동일**.
_UNPROVIDED_BY_DART = sorted([
    "acquirers_multiple",   # ev ← cash
    "cash_ratio",           # cash
    "ebitda_margin",        # depreciation
    "ev_ebitda", "ev_fcf", "ev_ic", "ev_sales",   # ev ← cash
    "interest_coverage",    # interest_expense
    "net_debt_to_ebitda",   # cash · depreciation
    "rnd_intensity",        # rnd
    "sga_to_revenue",       # sga
    "sloan_accruals",       # depreciation
])

#: 변경 전 코드가 완전 적재 픽스처에서 낸, **위 12개를 뺀** 나머지의 지문.
GOLDEN_UNCHANGED_SHA256 = "6bc4d54830d86251dc616d516d87149ce0d60f06558ac1c0f73442dd3bcabe65"


def test_a_fully_loaded_company_keeps_every_factor_dart_can_support():
    """★핵심 계약★ DART 가 주는 것으로 계산되는 팩터는 **한 글자도** 안 바뀐다.

    사용자 요구: "dart 데이터가 모두 적재되면 무조건 실측 기준으로 작동하게 해".
    """
    _raw, fac = _factors(_store(_Full))
    vals = {k: v for k, v in sorted(fac.items())
            if not k.startswith("_") and k not in _UNPROVIDED_BY_DART}
    got = hashlib.sha256(json.dumps(vals, default=str, sort_keys=True).encode()).hexdigest()
    assert len(vals) == 52, f"팩터 집합이 달라졌다: {len(vals)}개"
    assert got == GOLDEN_UNCHANGED_SHA256, (
        "완전 적재인데 결과가 바뀌었다 — 조작 제거가 실측 경로까지 건드렸다")


@pytest.mark.parametrize("factor", _UNPROVIDED_BY_DART)
def test_a_factor_needing_data_dart_never_gives_is_none_not_a_number(factor):
    """★짝★ 위 테스트만 있으면 "12개를 아무 값으로나 둔다" 도 통과한다.

    이 12개는 DART FS 에 없는 항목(현금·R&D·판관비·감가상각·이자비용)에 의존한다.
    예전에는 매출의 몇 %로 지어내 **완전 적재 종목에서도 조작값**이었다.
    """
    _raw, fac = _factors(_store(_Full))
    assert fac[factor] is None, (
        f"{factor} 가 DART 에 없는 항목에서 값을 만들었다: {fac[factor]!r}")


def test_no_factor_silently_becomes_zero_instead_of_none():
    """★0 은 미상이 아니라 주장이다★

    이 슬라이스 초안에서 내가 실제로 만든 버그다 — `round(safe_div(None, x) or 0, 2)`
    가 남아 `ev_ebitda`·`ev_fcf`·`ev_sales` 가 **0** 으로 나왔다. `EV/EBITDA = 0` 은
    "극도로 싸다" 로 읽힌다.
    """
    _raw, fac = _factors(_store(_Full))
    for f in _UNPROVIDED_BY_DART:
        assert fac[f] != 0, f"{f} 가 미상인데 0 으로 나갔다 — 저평가 신호를 제조한다"


def test_the_full_fixture_does_not_accidentally_match_the_fabrication_constant():
    """★해네스 비공허성★ 감쇠율이 0.95 면 조작값과 구별이 안 된다.

    이 테스트가 없으면 위 골든이 "실측을 썼다" 를 증명하지 못한다 — 실제로 처음에
    그 함정에 빠졌다.
    """
    _raw, fac = _factors(_store(_Full))
    g = fac["revenue_growth_yoy"]
    assert g == pytest.approx(12.36, abs=0.01), f"실측 전년도를 안 썼다: {g}"
    assert g != pytest.approx(5.26, abs=0.01), "조작 상수 0.95 와 구별되지 않는다"


# ══ ② 부분 적재 — 지어내지 않는다 ═══════════════════════════════════════════

@pytest.mark.parametrize("field", [
    "gross_profit", "current_assets", "current_liabilities", "inventory",
    "operating_cf", "capex", "interest_expense", "cash", "receivables",
    "rnd", "sga", "depreciation",
    # ★`shares` 는 여기 없다★ 시총÷현재가로 **실측 도출**되기 때문이다(조작이 아니다).
    # 아래 전용 테스트가 "시장 데이터마저 없을 때" 를 따로 건다.
])
def test_an_unloaded_field_is_none_not_a_ratio_of_something_else(field):
    """★미상은 다른 값의 비율이 아니다★"""
    raw, _fac = _factors(_store(_Sparse))
    assert raw[field] is None, (
        f"{field} 를 지어냈다: {raw[field]!r} — DART 가 주지 않은 값이다")


@pytest.mark.parametrize("field", ["revenue_prev", "op_prev", "ni_prev",
                                   "revenue_3y_ago", "ni_3y_ago"])
def test_a_missing_prior_year_is_none_not_a_decayed_copy(field):
    """★전년도를 당해의 95% 로 지어내지 않는다★ 그러면 모든 종목이 같은 성장률이 된다."""
    st = _store(_Sparse, years=1)          # 당해만 있고 과거가 없다
    raw, _fac = _factors(st)
    assert raw[field] is None, f"{field} 를 지어냈다: {raw[field]!r}"


def test_the_derived_growth_rate_is_none_rather_than_a_constant():
    """★스크리닝이 상수를 거르지 않게 한다★

    예전에는 전년도가 없으면 `revenue_prev = revenue * 0.95` 라 매출액증가율이
    **어떤 종목이든 정확히 +5.26%** 였다.
    """
    _raw, fac = _factors(_store(_Sparse, years=1))
    assert fac["revenue_growth_yoy"] is None, (
        f"성장률이 상수에서 나왔다: {fac['revenue_growth_yoy']}")


def test_unknown_is_not_dressed_up_as_financial_distress():
    """★미상에서 부실 신호를 제조하지 않는다★

    `interest_coverage = safe_div(op, interest_expense) or 0` 이면 이자비용 미상이
    **0 = "이자를 못 갚는다"** 가 된다. 그것은 미상이 아니라 **주장**이다.
    """
    _raw, fac = _factors(_store(_Sparse))
    assert fac["interest_coverage"] is None, (
        f"이자보상배율을 0 으로 단정했다: {fac['interest_coverage']}")


def test_unknown_quality_is_not_the_worst_quality():
    """★짝★ `gp_to_assets ... or 0` 이면 미상이 '최악의 퀄리티' 로 QMJ 에 전파된다."""
    _raw, fac = _factors(_store(_Sparse))
    assert fac["gp_to_assets"] is None, f"퀄리티를 0 으로 단정했다: {fac['gp_to_assets']}"


# ══ ③ 조용한 실종 방지 ═══════════════════════════════════════════════════════

def test_a_sparse_company_does_not_crash_the_factor_computation():
    """★1순위 리스크★ `attach_fundamentals` 는 종목별로 예외를 삼키고 `continue` 한다.

    즉 `_derive_factors` 가 `None` 산술로 터지면 **그 종목이 조용히 사라진다** —
    실패하는 테스트도, 눈에 보이는 크래시도 없이 유니버스가 줄어든다.
    예외를 **직접** 걸어야만 잡힌다.
    """
    st = _store(_Sparse, years=1)
    raw = st._real_raw_financials("005930")
    st._derive_factors("005930", raw)      # 예외가 나면 여기서 실패한다


def test_the_raw_key_set_is_unchanged_so_mock_values_cannot_leak_back():
    """★키를 빼면 mock 난수가 되살아난다★

    `_real_raw_financials` 는 `raw = self._mock_raw_financials(...)` 로 시작해
    덮어쓴다. 키를 빼면 그 자리에 **mock 값이 남는다** — 값을 None 으로 만들려다
    오히려 합성값을 들이는 셈이다.
    """
    raw_full, _ = _factors(_store(_Full))
    raw_sparse, _ = _factors(_store(_Sparse))
    assert set(raw_full) == set(raw_sparse), (
        f"부분 적재에서 키가 사라졌다: {set(raw_full) ^ set(raw_sparse)}")


def test_the_sparse_company_still_reports_what_it_does_know():
    """★전부 None 으로 만드는 것도 틀렸다★ 실측 6개에서 나오는 팩터는 나와야 한다."""
    _raw, fac = _factors(_store(_Sparse))
    for f in ("roe", "roa", "net_margin", "operating_margin", "debt_to_equity"):
        assert fac[f] is not None, f"{f} 는 실측 6개로 계산 가능한데 None 이다"


def test_shares_is_none_only_when_neither_dart_nor_market_knows():
    """★도출과 조작을 구별한다★

    주식수는 DART 가 안 줘도 **시총 ÷ 현재가**로 도출된다 — 두 항이 모두 실측이면
    그것은 조작이 아니다. 예전 `shares = 10000` 폴백은 그 둘마저 없을 때의
    **순수한 조작**이었고("BPS ₩566만" 버그의 절반), 그것만 없앤다.
    """
    st = _store(_Sparse)
    st._market_snapshot = lambda code: {"mcap_억": None, "price": None}
    raw, fac = _factors(st)
    assert raw["shares"] is None, f"주식수를 지어냈다: {raw['shares']!r}"
    assert fac["bps"] is None, "주식수 미상인데 BPS 가 나왔다(자본총계가 그대로 노출)"


def test_a_capex_loaded_in_history_is_carried_through(monkeypatch):
    """★적재된 실측을 버리지 않는다★ (변이 E6)

    `financials_history` 에는 `capex` 컬럼이 **있는데** `_fs_from_history` 가 그것을
    복사하지 않아, DB 경로에서는 늘 미적재로 보였다. 그러면
    `_real_raw_financials` 가 `investing_cf`(DB 경로에서 절대 안 채워짐)를 보고
    실패한 뒤 `revenue * 0.05` 로 지어냈다 — **실측이 있는데 조작을 쓴 것이다.**

    ★소스 텍스트가 아니라 동작을 본다★ 처음엔 복사 목록을 `co_consts` 로 들여다
    봤는데, 인덱스가 틀렸고 애초에 취약한 방식이다.
    """
    import src.data.dart_history as dh
    snap = {"revenue": 1000e8, "operating_profit": 100e8, "net_income": 80e8,
            "total_assets": 2000e8, "total_liabilities": 1200e8, "total_equity": 800e8,
            "operating_cf": 120e8, "capex": 70e8}
    monkeypatch.setattr(dh, "history_snapshot", lambda t, y, r, engine=None: snap)
    fs = FundamentalsStore._fs_from_history("005930", 2024)
    assert fs is not None, "픽스처가 핵심값 게이트를 통과하지 못했다"
    assert getattr(fs, "capex", None) == 70e8, (
        f"적재된 capex 가 전달되지 않았다: {getattr(fs, 'capex', None)!r}")


def test_the_raw_dict_keeps_every_key_even_when_the_value_is_unknown():
    """★키를 빼면 mock 난수가 되살아난다★ (변이 E5)

    `_real_raw_financials` 는 `raw = self._mock_raw_financials(...)` 로 시작해
    덮어쓴다. `update` 에서 키를 빼면 그 자리에 **mock 난수가 남는다** — 값을
    None 으로 만들려다 오히려 합성값을 들이는 셈이다.
    """
    raw, _ = _factors(_store(_Sparse))
    # DART FS 가 주지 않는 항목 — 미상이어야 한다
    for k in ("inventory", "cash", "rnd", "sga", "depreciation", "capex",
              "interest_expense", "receivables", "tax"):
        assert k in raw, f"{k} 키가 사라졌다 — mock 시드 값이 노출된다"
        assert raw[k] is None, f"{k} 가 mock 값으로 남았다: {raw[k]!r}"
    # ★도출은 조작이 아니다★ EPS 는 순이익 ÷ 실측 주식수라 값이 있는 것이 옳다.
    # (주식수는 시총÷현재가로 실측 도출된다 — 처음엔 이걸 조작으로 착각해 걸었다.)
    assert raw["eps"] is not None, "실측 순이익·주식수가 있는데 EPS 가 미상이다"


def test_market_cap_is_never_guessed_from_book_equity():
    """★PBR 이 상수 1.2 로 나오던 것★ (변이 E10)

    예전에는 시총이 없으면 `mcap = total_equity * 1.2`(PBR≈1.2 가정)로 만들었다.
    그러면 시총 미상 종목이 **전부 정확히 PBR 1.2** 로 스크리닝됐다 — 가치 지표가
    데이터가 아니라 상수에서 나온 것이다.

    앞의 `_Sparse` 테스트들은 시총을 실측으로 주기 때문에 이 분기를 타지 않는다.
    여기서만 시장 데이터를 통째로 없앤다.
    """
    st = _store(_Sparse)
    st._market_snapshot = lambda code: {"mcap_억": None, "price": None}
    raw, fac = _factors(st)
    assert raw["market_cap"] is None, f"시총을 지어냈다: {raw['market_cap']!r}"
    assert fac["pbr"] is None, f"PBR 이 가정 상수에서 나왔다: {fac['pbr']}"
    assert fac["per"] is None, f"PER 이 가정 상수에서 나왔다: {fac['per']}"
    assert fac["book_to_market"] is None, f"장부/시장이 상수에서 나왔다: {fac['book_to_market']}"


def test_the_update_block_does_not_drop_inventory():
    """★변이 E5 재조준★ mock 경로에 같은 문자열이 있어 앵커가 2건이었다.

    `raw.update(dict(...))` 에서 키가 빠지면 그 자리에 mock 난수가 남는다.
    실경로 결과의 `inventory` 가 미적재인데 값이 있으면 그것은 mock 이다.
    """
    raw, _ = _factors(_store(_Sparse))
    assert raw["inventory"] is None, (
        f"재고가 mock 값으로 남았다: {raw['inventory']!r} — update 에서 키가 빠졌다")
