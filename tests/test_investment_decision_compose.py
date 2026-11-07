"""`decide()` 도메인 합성 — ★결정 원시함수 8개가 전부 호출부 1개였다★ (S2)
==============================================================================
설계: `docs/superpowers/specs/2026-08-28-investment-decision-layer-design.md`
선행: S1 결정 스토어(`da39c27`) — 만들었지만 아직 아무도 부르지 않는다.

## 이 파일이 막는 것

Phase 0 감사의 **M3**: 결정 원시함수(`rebalance_decision`·`dynamic_band`·
`build_plan`·`save_decision` …)가 전부 **호출부 1개 = API 라우트**였다. 사람이
라우트를 올바른 순서로 눌러야만 결정이 성립하고, 도메인 계층에서 합성하는 코드가
**없었다**.

## ★`decide()` 는 계산하지 않는다★

세 가지를 **절대** 하지 않는다 — 하는 순간 두 번째 진실 공급원이 생긴다:

    optimize()      포트폴리오 **구성**이지 결정이 아니다 (§5)
    build_plan()    `_cost_block` 이 이미 재사용한다 — 세 번째 비용 경로 금지
    효용·밴드 산수   `rebalance_decision` 안에 있다

하는 일은 넷이다: **판단 호출 · 상류→스토어 매핑 · legs 유도 · 영속**.
★매핑이 위험한 부분이다★ — 설계 초안이 `*_bps` 라고 적어 100배 오류가 날 뻔했다.

## ★제약 구속은 포트폴리오 수준이다★

`constrained_solve` 의 `binding` 은 `"종목 상한 40%"` 같은 **포트폴리오 수준**
문자열이다. 어느 종목이 그 구속을 유발했는지는 재유도해야 알 수 있고 그것은
지어내기다. 그래서 부모의 `evidence` 에 담고 leg 는 **빈 채로 둔다**.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

import src.data.investment_decisions as idec  # noqa: E402
import src.engine.investment_decision as dec_mod  # noqa: E402
import src.engine.rebalance_policy as rp  # noqa: E402

_CUR = {"005930": 50.0, "000660": 50.0}
_TGT = {"005930": 58.0, "000660": 42.0}
_NAMES = ["005930", "000660"]
_MU = np.array([0.12, 0.04])
_SIGMA = np.array([[0.09, 0.02], [0.02, 0.06]])
_PV = 100_000_000.0


@pytest.fixture
def eng():
    return create_engine("sqlite://", connect_args={"check_same_thread": False})


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, eng):
    monkeypatch.setattr(idec, "_engine", lambda engine=None: eng)
    yield


def _prices(code):
    return 70_000.0


def _adv(code):
    return 5.0e11


def _decide(**over):
    kw = dict(portfolio_value=_PV, names=_NAMES, mu=_MU, sigma=_SIGMA,
              price_of=_prices, adv_of=_adv, as_of="2026-08-28",
              case_id="rc_1", persist=True,
              # ★`decide` 는 트리거를 만들지 않는다★ "왜 검토했나" 는 상류(라우트의
              # `detect_triggers`)가 안다. 여기서 만들면 두 번째 트리거 경로가 된다.
              triggers={"calendar": True, "drift": False})
    kw.update(over)
    cur = kw.pop("current_weights", _CUR)
    tgt = kw.pop("target_weights", _TGT)
    return dec_mod.decide(cur, tgt, **kw)


# ══════════════════════════════════════════════════════════════════════════
# R1·R2 ★계산을 새로 하지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_it_delegates_the_judgement_to_the_existing_primitive(monkeypatch):
    """★기록 스파이★ — 판단을 다시 구현하면 두 번째 진실 공급원이 된다."""
    seen: list[dict] = []
    real = rp.rebalance_decision

    def spy(cur, tgt, **kw):
        seen.append(kw)
        return real(cur, tgt, **kw)

    monkeypatch.setattr(rp, "rebalance_decision", spy)
    _decide(persist=False)
    assert len(seen) == 1, "판단 원시함수를 부르지 않았다"
    assert seen[0]["portfolio_value"] == _PV


def test_it_does_not_open_a_third_cost_path():
    """★`build_plan` 을 직접 부르지 않는다★

    `rebalance_policy._cost_block` 이 이미 재사용하며 *"비용 산수를 두 곳에 두지
    않는다"* 고 적어 뒀다. 여기서 또 부르면 **세 번째** 경로가 된다.

    ★산문이 아니라 코드 토큰만 본다★ — 주석·독스트링은 걷어낸다(설명은 호출이 아니다).
    """
    import io
    import pathlib
    import tokenize

    src = pathlib.Path(dec_mod.__file__).read_text(encoding="utf-8")
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    banned = {"build_plan", "optimize", "constrained_solve", "entropy_pool",
              "bl_posterior", "dynamic_band"}
    hits = {t.string for t in toks
            if t.type not in (tokenize.COMMENT, tokenize.STRING)
            and t.string in banned}
    assert not hits, f"결정 계층이 구성·비용 산수를 직접 부른다: {hits}"


# ══════════════════════════════════════════════════════════════════════════
# R3·R4·R5 ★증거가 없으면 강등된다★ (음성 통제)
# ══════════════════════════════════════════════════════════════════════════
def test_without_mu_and_sigma_it_degrades_to_undetermined(eng):
    """★핵심 음성 통제★ 편익을 모르면 거래를 권하지 않는다 — 그래도 **저장된다**.

    "검토했으나 판단할 수 없었다" 와 "검토 자체가 없었다" 는 다른 사실이다.
    """
    out = _decide(mu=None, sigma=None)
    assert out["decision"] == "undetermined"
    assert out["reason"]
    assert out["persisted"] is True and out["dec_id"]
    assert idec.get_decision(out["dec_id"], engine=eng)["decision_status"] == "undetermined"


def test_with_mu_and_sigma_it_reaches_a_real_verdict(eng):
    """★짝★ 없으면 위 테스트가 '항상 undetermined' 구현으로도 통과한다."""
    out = _decide()
    assert out["decision"] in ("trade", "hold")
    assert out["reason"]


def test_a_zero_portfolio_value_is_undetermined_not_a_crash(eng):
    """평가액을 모르면 비용을 모르고, 비용을 모르면 판단할 수 없다."""
    out = _decide(portfolio_value=0.0)
    assert out["decision"] == "undetermined" and out["reason"]


# ══════════════════════════════════════════════════════════════════════════
# R6 ★단위 무변환★
# ══════════════════════════════════════════════════════════════════════════
def test_the_stored_numbers_equal_the_upstream_numbers(eng):
    """★설계 초안이 저지를 뻔한 100배 오류★ 상류는 percent 를 준다."""
    out = _decide()
    got = idec.get_decision(out["dec_id"], engine=eng)

    assert got["gain_pct"] == pytest.approx(out["benefit"]["gain_pct"])
    assert got["cost_pct"] == pytest.approx(out["cost"]["cost_pct"])
    assert got["hysteresis_mult"] == pytest.approx(out["hysteresis_mult"])
    # ★회전율을 따로 계산하지 않는다★ 비용 블록이 이미 낸다.
    assert got["turnover_pct"] == pytest.approx(out["cost"]["turnover_pct"])


# ══════════════════════════════════════════════════════════════════════════
# R7·R8 legs 는 밴드에서 나온다
# ══════════════════════════════════════════════════════════════════════════
def test_legs_come_from_the_per_asset_bands(eng):
    out = _decide()
    got = idec.get_decision(out["dec_id"], engine=eng)
    legs = {leg["ticker"]: leg for leg in got["legs"]}

    assert set(legs) == set(_CUR) | set(_TGT)
    band = out["band"]["by_asset"]
    for tk, leg in legs.items():
        assert leg["half_width_pct"] == pytest.approx(band[tk]["half_width_pct"])
        assert leg["low_pct"] == pytest.approx(band[tk]["low_pct"])
        assert leg["outside_band"] is (tk in out["band"]["outside"])
    assert legs["005930"]["delta_w"] == pytest.approx(8.0)


def test_legs_exist_even_when_the_band_is_unavailable(eng):
    """★짝★ 밴드를 몰라도 무엇을 얼마나 바꾸려 했는지는 남아야 한다."""
    out = _decide(portfolio_value=0.0)
    assert out["decision"] == "undetermined"
    got = idec.get_decision(out["dec_id"], engine=eng)
    legs = {leg["ticker"]: leg for leg in got["legs"]}
    assert set(legs) == set(_CUR)
    assert legs["005930"]["delta_w"] == pytest.approx(8.0)
    assert legs["005930"]["half_width_pct"] is None, "없는 밴드를 지어냈다"


# ══════════════════════════════════════════════════════════════════════════
# R9 ★저장 실패가 계산을 되돌리지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_failed_persist_still_returns_the_decision(monkeypatch):
    monkeypatch.setattr(idec, "_engine", lambda engine=None: None)
    out = _decide()
    assert out["decision"] in ("trade", "hold", "undetermined")
    assert out["persisted"] is False and out["persist_reason"]
    assert out["dec_id"] is None


def test_persist_false_skips_the_store_without_pretending(eng):
    out = _decide(persist=False)
    assert out["dec_id"] is None and out["persisted"] is False
    assert idec.list_decisions(engine=eng) == []


# ══════════════════════════════════════════════════════════════════════════
# R10·R11 provenance · ★식별 불가를 식별한 척하지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_provenance_and_belief_are_recorded(eng):
    out = _decide(belief={"mu_source": "conditional", "measured": False})
    got = idec.get_decision(out["dec_id"], engine=eng)
    assert got["decision_version"] == idec.DECISION_LOGIC_VERSION
    assert got["code_version"] and got["code_version"] != got["decision_version"]
    assert got["belief"]["mu_source"] == "conditional"
    assert got["as_of"] == "2026-08-28" and got["case_id"] == "rc_1"


def test_constraint_binding_stays_at_the_portfolio_level(eng):
    """★`constrained_solve` 의 binding 은 포트폴리오 수준이다★

    어느 **종목**이 그 구속을 유발했는지는 재유도해야 알 수 있고 그것은 지어내기다.
    """
    out = _decide(evidence={"constraints_binding": ["종목 상한 40%", "회전율 상한 20%"]})
    got = idec.get_decision(out["dec_id"], engine=eng)

    assert got["evidence"]["constraints_binding"] == ["종목 상한 40%", "회전율 상한 20%"]
    for leg in got["legs"]:
        assert leg["constraint_binding"] == [], "포트폴리오 구속을 종목에 배분했다"


# ══════════════════════════════════════════════════════════════════════════
# R12 왕복
# ══════════════════════════════════════════════════════════════════════════
def test_the_decision_round_trips_through_the_store(eng):
    out = _decide()
    got = idec.get_decision(out["dec_id"], engine=eng)
    assert got["decision_status"] == out["decision"]
    assert got["reason"] == out["reason"]
    assert got["max_gap_pct"] == pytest.approx(out["max_gap_pct"])
    assert got["gradual"] is not None, "부분 이동 제안이 사라졌다"
    # 트리거는 **넘긴 것이 그대로** 돌아온다 — 결정 계층이 다시 만들지 않는다.
    assert got["triggers"] == {"calendar": True, "drift": False}
