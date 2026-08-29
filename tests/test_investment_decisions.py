"""InvestmentDecision 스토어 — ★결정이 응답과 함께 사라지고 있었다★ (S1)
==============================================================================
설계: `docs/superpowers/specs/2026-08-28-investment-decision-layer-design.md`
선행 감사: Phase 0 — 결정 원시함수 8개가 전부 호출부 1개(=라우트)이고,
`rebalance_decision` 의 trade/hold/undetermined 판단은 **어디에도 저장되지 않았다.**

## 이 파일이 지키는 것

★단위 계약이 가장 위험하다★ 설계 스펙 초안은 `benefit_bps · cost_bps ·
hysteresis_bps` 라고 적었는데, `rebalance_policy` 의 실제 반환은
`benefit.gain_pct` · `cost.cost_pct` · `hysteresis_mult`(**배수**)다. 단위가
**percent** 이지 bps 가 아니다. 스펙대로 만들었으면 저장 시 **100배 오류**가
조용히 들어갔을 것이다 — `T6` 가 그것을 막는다.

★사유 없는 결정은 블랙박스다★ `hold`/`undetermined` 를 사유 없이 저장하면 나중에
"왜 거래하지 않았나" 에 답할 수 없다. 그것이 저널의 존재 이유(*"결과는 좋았지만
결정은 나빴나"*)와 정면으로 어긋난다.

★자식 테이블의 존재 이유★ 이 저장소의 관례는 `execution_store` 처럼 **단일 테이블 +
JSON** 이다. 여기서 두 테이블로 가는 이유는 하나뿐이다 — *"어느 종목이 가장 자주
밴드 밖이었나"* 는 **결정 간** 질의라 JSON 으로는 SQL 로 답할 수 없다. `T9` 가
그 이유를 못 박는다. 그 테스트가 사라지면 두 테이블일 이유도 사라진다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

import src.data.investment_decisions as idec  # noqa: E402


@pytest.fixture
def eng():
    return create_engine("sqlite://", connect_args={"check_same_thread": False})


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, eng):
    """★프로세스 공용 DB 를 건드리지 않는다★"""
    monkeypatch.setattr(idec, "_engine", lambda engine=None: eng)
    yield


def _decision(status: str = "trade", **over) -> dict:
    d = {
        "as_of": "2026-08-28", "scope": "portfolio",
        "decision_status": status,
        "gain_pct": 0.0345, "cost_pct": 0.0120, "hysteresis_mult": 0.25,
        "threshold_pct": 0.0150, "net_pct": 0.0195,
        "max_gap_pct": 3.2, "turnover_pct": 12.5, "portfolio_value": 100_000_000.0,
        "reason": "효용 개선이 비용 문턱을 넘습니다",
        "belief": {"mu_source": "conditional", "prob_usage": "persistence_assumption",
                   "uncertainty_source": "assumed_widths", "measured": False},
        "evidence": {"mes_id": "rgs_1", "run_id": "rr_1", "tpv_id": "tpv_1",
                     "thesis_ids": ["th_1"]},
        "gradual": {"step_pct": 50.0, "note": "절반만 이동"},
        "triggers": ["calendar", "drift"],
    }
    d.update(over)
    return d


def _legs(*tickers, outside=("005930",)) -> list[dict]:
    return [{"ticker": t, "current_w": 30.0, "target_w": 33.2, "delta_w": 3.2,
             "half_width_pct": 1.1, "low_pct": 32.1, "high_pct": 34.3,
             "outside_band": t in outside,
             "constraint_binding": ["max_weight"] if t == "000660" else [],
             "view_refs": [{"source": "macro"}],
             "contribution": {"macro": None, "company": None,
                              "risk_model": None, "constraint": None}}
            for t in tickers]


# ══════════════════════════════════════════════════════════════════════════
# T1 왕복
# ══════════════════════════════════════════════════════════════════════════
def test_a_decision_round_trips_with_its_legs(eng):
    dec_id = idec.save_decision(_decision(), _legs("005930", "000660"), engine=eng)
    assert dec_id and dec_id.startswith("dec_")

    got = idec.get_decision(dec_id, engine=eng)
    assert got["decision_status"] == "trade"
    assert got["as_of"] == "2026-08-28"
    assert got["evidence"]["mes_id"] == "rgs_1"
    assert {leg["ticker"] for leg in got["legs"]} == {"005930", "000660"}


def test_an_unknown_id_is_none_not_an_error(eng):
    assert idec.get_decision("dec_nope", engine=eng) is None


# ══════════════════════════════════════════════════════════════════════════
# T2·T3 ★세 status 전부 저장하되, 사유 없는 결정은 거부★
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("status", ["trade", "hold", "undetermined"])
def test_every_status_is_persisted(eng, status):
    """★`hold`/`undetermined` 도 결정이다★ 저장하지 않으면 '검토했으나 안 했다'와
    '검토 자체가 없었다' 를 영원히 구분할 수 없다."""
    dec_id = idec.save_decision(_decision(status), _legs("005930"), engine=eng)
    assert dec_id, status
    assert idec.get_decision(dec_id, engine=eng)["decision_status"] == status


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_a_decision_without_a_reason_is_refused(eng, bad):
    """★짝★ 사유 없는 결정은 블랙박스다 — 저널이 물을 수 있는 것이 없어진다."""
    assert idec.save_decision(_decision(reason=bad), _legs("005930"), engine=eng) is None


def test_an_unknown_status_is_refused(eng):
    """★셋 말고는 없다★ 오타가 조용히 새 상태를 만들면 질의가 갈라진다."""
    assert idec.save_decision(_decision("maybe"), _legs("005930"), engine=eng) is None


# ══════════════════════════════════════════════════════════════════════════
# T4 고아 금지
# ══════════════════════════════════════════════════════════════════════════
def test_legs_never_outlive_their_parent(eng):
    """부모가 거부되면 자식도 남지 않는다 — 반쪽 결정은 결정이 아니다."""
    idec.save_decision(_decision(reason=""), _legs("005930"), engine=eng)
    assert idec.legs_of("dec_any", engine=eng) == []
    assert idec.list_decisions(engine=eng) == []


def test_a_decision_with_no_legs_is_still_a_decision(eng):
    """★짝★ 자산이 없는 결정(예: 전량 현금 유지)도 기록돼야 한다."""
    dec_id = idec.save_decision(_decision("hold", reason="전부 밴드 안"), [], engine=eng)
    assert dec_id and idec.get_decision(dec_id, engine=eng)["legs"] == []


# ══════════════════════════════════════════════════════════════════════════
# T5 DB 없으면 조용히 실패 (저장소 관례)
# ══════════════════════════════════════════════════════════════════════════
def test_without_a_database_it_returns_none_instead_of_raising(monkeypatch):
    monkeypatch.setattr(idec, "_engine", lambda engine=None: None)
    assert idec.save_decision(_decision(), _legs("005930")) is None
    assert idec.get_decision("dec_x") is None
    assert idec.list_decisions() == []
    assert idec.legs_of("dec_x") == []
    assert idec.outside_band_counts() == {}


# ══════════════════════════════════════════════════════════════════════════
# T6 ★단위 계약 — percent 를 bps 로 바꾸지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_percent_fields_survive_the_round_trip_unscaled(eng):
    """★설계 초안이 저지를 뻔한 사고★ 스펙은 `*_bps` 라고 적었지만 상류는
    **percent** 를 준다(`cost.cost_pct`·`benefit.gain_pct`). 100배 하면 조용히 틀린다.
    """
    dec_id = idec.save_decision(_decision(), _legs("005930"), engine=eng)
    got = idec.get_decision(dec_id, engine=eng)
    assert got["gain_pct"] == pytest.approx(0.0345)
    assert got["cost_pct"] == pytest.approx(0.0120)
    assert got["threshold_pct"] == pytest.approx(0.0150)
    assert got["net_pct"] == pytest.approx(0.0195)
    # ★히스테리시스는 **배수**다★ threshold = cost_pct × (1 + mult)
    assert got["hysteresis_mult"] == pytest.approx(0.25)
    assert got["cost_pct"] * (1 + got["hysteresis_mult"]) == pytest.approx(
        got["threshold_pct"], abs=1e-9)


def test_leg_band_fields_keep_the_upstream_names(eng):
    """`dynamic_band` 는 `half_width_pct`/`low_pct`/`high_pct` 를 낸다 —
    이름을 갈아 끼우면 상류가 바뀔 때 조용히 어긋난다."""
    dec_id = idec.save_decision(_decision(), _legs("005930"), engine=eng)
    leg = idec.get_decision(dec_id, engine=eng)["legs"][0]
    assert leg["half_width_pct"] == pytest.approx(1.1)
    assert leg["low_pct"] == pytest.approx(32.1)
    assert leg["high_pct"] == pytest.approx(34.3)


# ══════════════════════════════════════════════════════════════════════════
# T7 provenance — ★두 축은 다른 값이다★
# ══════════════════════════════════════════════════════════════════════════
def test_provenance_stamps_two_distinct_axes(eng):
    """`code_version` 은 **빌드** 식별자, `decision_version` 은 **결정 로직**의 판본.
    같은 값으로 두면 로직이 바뀌어도 기록이 그대로라 재현이 거짓말이 된다."""
    from src.engine.research_context import code_version

    dec_id = idec.save_decision(_decision(), _legs("005930"), engine=eng)
    got = idec.get_decision(dec_id, engine=eng)
    assert got["code_version"] == code_version()
    assert got["decision_version"] == idec.DECISION_LOGIC_VERSION
    assert got["decision_version"] != got["code_version"]


# ══════════════════════════════════════════════════════════════════════════
# T8 결정 **간** 질의
# ══════════════════════════════════════════════════════════════════════════
def test_decisions_can_be_filtered_across_time(eng):
    idec.save_decision(_decision("trade"), _legs("005930"), case_id="rc_1", engine=eng)
    idec.save_decision(_decision("hold", reason="밴드 안"), _legs("000660"),
                       case_id="rc_1", engine=eng)
    idec.save_decision(_decision("trade"), _legs("035720"), case_id="rc_2", engine=eng)

    assert len(idec.list_decisions(engine=eng)) == 3
    assert len(idec.list_decisions(case_id="rc_1", engine=eng)) == 2
    assert len(idec.list_decisions(status="trade", engine=eng)) == 2
    assert len(idec.list_decisions(case_id="rc_2", status="hold", engine=eng)) == 0


# ══════════════════════════════════════════════════════════════════════════
# T9 ★두 테이블의 존재 이유★
# ══════════════════════════════════════════════════════════════════════════
def test_legs_can_be_aggregated_across_decisions(eng):
    """★이 테스트가 사라지면 두 테이블일 이유도 사라진다★

    JSON 컬럼이었다면 SQL 로 답할 수 없는 질문이다:
    *"어느 종목이 가장 자주 무거래 밴드 밖이었나."*
    """
    idec.save_decision(_decision(), _legs("005930", "000660", outside=("005930",)),
                       case_id="rc_1", engine=eng)
    idec.save_decision(_decision(), _legs("005930", "035720", outside=("005930", "035720")),
                       case_id="rc_1", engine=eng)

    counts = idec.outside_band_counts(engine=eng)
    assert counts == {"005930": 2, "035720": 1}
    assert "000660" not in counts, "밴드 안이었던 종목이 세어졌다"


def test_the_aggregate_respects_the_case_filter(eng):
    """★짝★ 필터를 무시하면 다른 연구의 결정이 섞인다."""
    idec.save_decision(_decision(), _legs("005930"), case_id="rc_1", engine=eng)
    idec.save_decision(_decision(), _legs("005930"), case_id="rc_2", engine=eng)
    assert idec.outside_band_counts(case_id="rc_1", engine=eng) == {"005930": 1}


# ══════════════════════════════════════════════════════════════════════════
# T10 스펙이 빠뜨렸던 산출이 보존된다
# ══════════════════════════════════════════════════════════════════════════
def test_the_gradual_move_and_triggers_are_kept(eng):
    """`gradual` 은 "얼마나 움직일까" 이고 `triggers` 는 "왜 검토했나" 다 —
    둘 다 결정의 일부인데 설계 초안이 빠뜨렸다."""
    dec_id = idec.save_decision(_decision(), _legs("005930"), engine=eng)
    got = idec.get_decision(dec_id, engine=eng)
    assert got["gradual"]["step_pct"] == pytest.approx(50.0)
    assert got["triggers"] == ["calendar", "drift"]


def test_the_unmeasured_uncertainty_label_survives(eng):
    """★가정된 폭이라는 사실이 전파돼야 한다★ 기업 밸류에이션 폭은 측정된 것이
    하나도 없다(`repo_widths`). 그 라벨을 잃으면 confidence 날조가 된다."""
    dec_id = idec.save_decision(_decision(), _legs("005930"), engine=eng)
    belief = idec.get_decision(dec_id, engine=eng)["belief"]
    assert belief["measured"] is False
    assert belief["uncertainty_source"] == "assumed_widths"
