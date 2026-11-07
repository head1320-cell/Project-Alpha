"""AK2 — 비용을 정하는 자리들의 레지스트리와 롤업.

AJ2(`multiplicity_evidence`)·AH2(`estimator_evidence`)의 관용구 그대로이고
★판정은 `run_evidence.rollup` 한 곳에만 있다★ — `pit_evidence`·
`decision_evidence`·`estimator_evidence`·`multiplicity_evidence` 와 **같은 함수**다.

## 이 파일이 거는 계약

  · ★레지스트리가 비지 않는다★ — 비면 아래 검사 전부가 공허해진다(AG 의 사고)
  · 각 자리가 **실재**한다 — 파일도 심볼도 있어야 증거다
  · ★라우트별 10배 불일치가 표에 적혀 있다★
  · `market_rules` 가 주는데 아무도 안 쓰는 규칙이 사유와 함께 적혀 있다
"""
from __future__ import annotations

import pathlib

import pytest

from src.domain.cost_model import COMPONENTS, STATES
from src.engine.cost_model_registry import (
    COST_SITES,
    DISAGREEMENTS,
    UNAPPLIED_RULES,
    CostSite,
    registry_evidence,
    site_axis,
)
from src.engine.run_evidence import AXIS_DEGRADED, AXIS_OK, AXIS_UNKNOWN

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _site(**kw) -> CostSite:
    base = dict(key="x", site="src/engine/x.py:f", label="시험",
                commission_bps=15.0, slippage_bps=5.0,
                components={c: "off" for c in COMPONENTS}, note="…")
    base["components"]["commission"] = "charged"
    base["components"]["slippage"] = "charged"
    base.update(kw)
    return CostSite(**base)


# ═══════════════════════════════════════════════════════════════════════════
# ⑭ 축 상태 — 세 갈래가 **실제로** 나온다
# ═══════════════════════════════════════════════════════════════════════════

def test_a_site_charging_every_component_is_ok():
    site = _site(components={c: "charged" for c in COMPONENTS})
    assert site_axis(site)["state"] == AXIS_OK


def test_a_site_with_components_switched_off_is_degraded():
    """★안 켠 것은 관측된 결함이다★ — 백테스트 넷이 정확히 이 상태였다."""
    axis = site_axis(_site())
    assert axis["state"] == AXIS_DEGRADED
    assert axis["reason"] and axis["missing"]


def test_a_site_that_cannot_measure_is_unknown_not_degraded():
    comps = {c: "charged" for c in COMPONENTS}
    comps["impact"] = "unmeasurable"
    assert site_axis(_site(components=comps))["state"] == AXIS_UNKNOWN


def test_the_three_states_all_occur():
    """★짝★ 언제나 한 상태인 구현을 배제한다."""
    comps_fog = {c: "charged" for c in COMPONENTS}; comps_fog["impact"] = "unmeasurable"
    states = {
        site_axis(_site(components={c: "charged" for c in COMPONENTS}))["state"],
        site_axis(_site())["state"],
        site_axis(_site(components=comps_fog))["state"],
    }
    assert states == {AXIS_OK, AXIS_DEGRADED, AXIS_UNKNOWN}


# ═══════════════════════════════════════════════════════════════════════════
# ⑫ 레지스트리 자체 — ★실측을 못 박는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_registry_is_not_empty_and_counts_more_than_four():
    """★채점표는 "넷" 이라고 적었다 — 재보니 열넷이었다★"""
    assert len(COST_SITES) >= 12, f"자리가 {len(COST_SITES)}개뿐이다"


def test_site_keys_are_unique():
    keys = [s.key for s in COST_SITES]
    assert len(set(keys)) == len(keys)


def test_every_site_uses_the_shared_vocabulary():
    for s in COST_SITES:
        assert set(s.components) == set(COMPONENTS), s.site
        for name, state in s.components.items():
            assert state in STATES, f"{s.site}:{name} = {state}"
        assert s.note, f"{s.site} 에 설명이 없다"


@pytest.mark.parametrize("s", COST_SITES, ids=lambda s: getattr(s, "key", "?"))
def test_every_registered_site_really_exists(s):
    """★레지스트리가 유령을 가리키면 그 항목은 증거가 아니다★"""
    path = _ROOT / s.site.split(":")[0]
    assert path.exists(), f"{s.site} 파일이 없다"
    symbol = s.site.split(":")[-1]
    assert symbol in path.read_text(encoding="utf-8"), f"{s.site} 심볼이 없다"


@pytest.mark.parametrize("s", COST_SITES, ids=lambda s: getattr(s, "key", "?"))
def test_every_site_declares_the_rate_it_actually_uses(s):
    """★적어 둔 요율이 코드에 실제로 있어야 한다★ — 낡은 표는 증거가 아니다."""
    if s.commission_bps is None or s.rate_source != "literal":
        return   # 설정 계층을 읽는 자리엔 숫자가 박혀 있지 않다 — 그것이 요점이다
    text = (_ROOT / s.site.split(":")[0]).read_text(encoding="utf-8")
    as_rate = f"{s.commission_bps / 1e4:g}"
    assert as_rate in text or f"{s.commission_bps:g}" in text, (
        f"{s.site} 에 {s.commission_bps}bp({as_rate}) 가 없다 — 표가 낡았다")


# ═══════════════════════════════════════════════════════════════════════════
# ⑬ ★같은 요청이 라우트에 따라 10배★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_route_disagreement_is_recorded():
    assert DISAGREEMENTS
    for d in DISAGREEMENTS:
        assert d["sites"] and d["reason"] and d["ratio"]


def test_the_commission_disagreement_is_tenfold():
    d = next(d for d in DISAGREEMENTS if d["component"] == "commission")
    assert d["ratio"] == pytest.approx(10.0)
    assert {15.0, 1.5} == set(d["values_bps"])


def test_the_registry_actually_contains_both_commission_values():
    """★표가 코드와 어긋나면 그 표는 증거가 아니다★"""
    values = {s.commission_bps for s in COST_SITES if s.commission_bps is not None}
    assert {15.0, 1.5} <= values


def test_slippage_is_not_reported_as_a_disagreement():
    """★실측: 슬리피지는 전 자리가 5bp 로 **일치**한다★ — 없는 갈등을 만들지 않는다."""
    assert not [d for d in DISAGREEMENTS if d["component"] == "slippage"]
    vals = {s.slippage_bps for s in COST_SITES if s.slippage_bps is not None}
    assert vals == {5.0}, vals


# ═══════════════════════════════════════════════════════════════════════════
# ★`market_rules` 가 주는데 아무도 안 쓰는 것★
# ═══════════════════════════════════════════════════════════════════════════

def test_unapplied_rules_are_listed_with_reasons():
    assert UNAPPLIED_RULES
    for r in UNAPPLIED_RULES:
        assert r["rule"] and r["reason"] and "status" in r


def test_the_three_opt_in_costs_are_no_longer_simply_absent():
    """★AK 이후 세금·스프레드·충격은 '없음' 이 아니라 '옵트인' 이다★"""
    by = {r["rule"]: r for r in UNAPPLIED_RULES}
    for rule in ("sell_tax_bp", "spread_bp_default", "impact_coeff"):
        assert by[rule]["status"] == "opt_in", rule
        assert "charge_" in by[rule]["reason"]


def test_the_rules_still_absent_say_so():
    """★옵트인으로 바뀌지 **않은** 것이 남아 있어야 이 구분이 뜻을 가진다★"""
    absent = [r for r in UNAPPLIED_RULES if r["status"] == "absent"]
    assert absent, "전부 옵트인이면 이 축이 공허하다"
    assert all(r["reason"] for r in absent)


# ═══════════════════════════════════════════════════════════════════════════
# 롤업 표면
# ═══════════════════════════════════════════════════════════════════════════

def test_the_registry_rollup_reports_broken_axes():
    got = registry_evidence()
    assert got["broken_axes"], "비용을 다 안 보는 자리가 결함으로 안 잡힌다"
    assert got["summary"] and got["note"]
    assert got["disagreements"] and got["unapplied_rules"]


def test_the_rollup_does_not_claim_the_models_were_unified():
    note = registry_evidence()["note"]
    assert "통일" in note or "단일" in note


def test_the_engine_default_and_the_desk_round_trip_are_both_reported():
    """★같은 왕복을 세 모델로 재면 몇 bp인가★ — 비교가 한 자에서 나와야 한다."""
    got = registry_evidence()
    rts = {r["key"]: r["round_trip_bps"] for r in got["round_trips"]}
    assert rts["kis_backtest_engine"] == pytest.approx(40.0)
    assert rts["realism_engine"] == pytest.approx(13.0)
    assert rts["execution_plan"] == pytest.approx(26.0)


# ═══════════════════════════════════════════════════════════════════════════
# ★요율이 어디서 오나★ — 숫자가 박힌 자리와 설정을 읽는 자리
# ═══════════════════════════════════════════════════════════════════════════

def test_most_sites_hardcode_their_rate():
    """★그것이 열넷이 갈라진 이유다★"""
    literal = [s for s in COST_SITES if s.rate_source == "literal"]
    assert len(literal) > len(COST_SITES) / 2


def test_at_least_one_site_reads_the_settings_layer():
    """★짝★ 전부 리터럴이면 위 검사가 공허하다."""
    assert [s for s in COST_SITES if s.rate_source == "market_rules"]


def test_the_execution_desk_reads_the_settings_layer():
    desk = next(s for s in COST_SITES if s.key == "execution_plan")
    assert desk.rate_source == "market_rules"
    assert desk.decision_touching is True
