"""ResearchRun 의 검정력 일급 필드 — ★질의 가능해야 한다★ (A5)
==============================================================================
감사(`7313371`) §4 의 포트폴리오 부채: `mde`·`power`·`seed`·비용가정이 **일급
필드가 아니라** JSON 안에 묻혀 있었다. 그러면 "검정력 0.8 을 넘긴 런만 보여줘"
같은 질문에 **테이블이 답할 수 없다** — 모든 행을 읽어 JSON 을 파싱해야 한다.

★가산 마이그레이션의 규율★ `add_columns` 는 붙였다고 믿지 않고 **SELECT 로
확인**한다. 못 붙으면 그 열 없이 동작해야 한다 — `case_id` 가 세운 패턴이다.
붙은 척하면 조회가 통째로 깨져서 수정 전보다 나빠진다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.research_runs as rr  # noqa: E402
from src.engine.research_power import power_report  # noqa: E402


@pytest.fixture
def mem_rr(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(rr, "_engine", lambda: eng)
    monkeypatch.setattr(rr, "_inited", False)
    yield eng
    eng.dispose()


def _block(power=0.4, mde=3.0):
    return power_report(
        curve=[{"scale": 1.0, "rate": power, "n": 5, "n_resolved": 5,
                "n_unknown": 0, "n_detected": 2, "ci": (0.1, 0.7), "reason": None},
               {"scale": mde, "rate": 1.0, "n": 5, "n_resolved": 5,
                "n_unknown": 0, "n_detected": 5, "ci": (0.5, 1.0), "reason": None}],
        observed_scale=1.0, n_obs=84, n_assets=6, rho_bar=0.58)


# ══════════════════════════════════════════════════════════════════════════
# ★열로 승격된다 — JSON 안에만 있지 않다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_power_fields_are_queryable_as_columns(mem_rr):
    rid = rr.record_run("gate", {"i": 1}, {"o": 1}, power_block=_block(),
                        seed=20260825, cost_bps=10.0)
    with mem_rr.connect() as c:
        row = c.execute(text(
            "SELECT run_id, mde, power, n_eff, target_power, seed, cost_bps "
            f"FROM {rr._TABLE} WHERE power >= 0.3")).fetchone()
    assert row is not None, "검정력으로 질의할 수 없다 — 일급 필드가 아니다"
    assert row[0] == rid
    assert row[1] == pytest.approx(3.0)          # mde
    assert row[2] == pytest.approx(0.4)          # power
    assert row[3] == pytest.approx(129.23, abs=0.01)
    assert row[4] == pytest.approx(0.80)
    assert row[5] == 20260825
    assert row[6] == pytest.approx(10.0)


def test_the_fields_come_back_from_get_run(mem_rr):
    # ★1× 의 검출률이 목표(0.80) 아래여야 MDE 가 두 번째 척도로 간다★
    # 0.9 를 주면 첫 척도에서 이미 목표에 도달해 MDE=1.0(at_search_floor)이 된다.
    rid = rr.record_run("gate", {}, {}, power_block=_block(power=0.6, mde=2.0),
                        seed=7, cost_bps=25.0)
    d = rr.get_run(rid)
    assert d["power"] == pytest.approx(0.6) and d["mde"] == pytest.approx(2.0)
    assert d["n_eff"] == pytest.approx(129.23, abs=0.01)
    assert d["seed"] == 7 and d["cost_bps"] == pytest.approx(25.0)


def test_the_whole_block_is_still_kept_in_outputs(mem_rr):
    """★열은 요약이고 원본은 남는다★ 곡선·bracket·사유는 열로 못 만든다."""
    rid = rr.record_run("gate", {}, {"verdict": "underpowered"},
                        power_block=_block())
    d = rr.get_run(rid)
    assert d["outputs"]["power_block"]["mde_detail"]["bracket"] == [1.0, 3.0]
    assert d["outputs"]["power_block"]["curve"]
    assert d["outputs"]["verdict"] == "underpowered"    # 기존 내용을 덮지 않는다


# ══════════════════════════════════════════════════════════════════════════
# ★미상은 미상으로 저장된다 — 0 이 아니다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_run_without_a_power_block_stores_nulls_not_zeros(mem_rr):
    """★없는 검정력을 0 으로 적으면 "검정력이 0 이었다" 는 거짓 진술이 된다.★"""
    rid = rr.record_run("plain", {}, {})
    d = rr.get_run(rid)
    for f in ("mde", "power", "n_eff", "target_power", "seed", "cost_bps"):
        assert d[f] is None, f
    with mem_rr.connect() as c:
        n = c.execute(text(f"SELECT COUNT(*) FROM {rr._TABLE} "
                           "WHERE power IS NULL")).scalar()
    assert n == 1


def test_an_unknown_mde_inside_a_block_stays_null(mem_rr):
    """MDE 미도달(사유 있음)은 `None` 으로 저장된다 — 탐색 최대값이 아니다."""
    blk = power_report(curve=[{"scale": 1.0, "rate": 0.1, "n": 5, "n_resolved": 5,
                               "n_unknown": 0, "n_detected": 0, "ci": (0.0, 0.5),
                               "reason": None}],
                       observed_scale=1.0, n_obs=84, n_assets=6, rho_bar=0.58)
    rid = rr.record_run("gate", {}, {}, power_block=blk)
    d = rr.get_run(rid)
    assert d["mde"] is None
    assert d["power"] == pytest.approx(0.1)
    assert d["outputs"]["power_block"]["reasons"]["mde"]


# ══════════════════════════════════════════════════════════════════════════
# ★열이 못 붙어도 동작한다 — 붙은 척하지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_recording_still_works_when_the_columns_cannot_be_added(mem_rr, monkeypatch):
    """`case_id` 가 세운 패턴 — 못 붙으면 그 열 없이 간다(조회를 깨지 않는다)."""
    import src.data.schema_add_columns as sac
    real = sac.add_columns
    monkeypatch.setattr(
        sac, "add_columns",
        lambda e, t, cols, **kw: (False if any(c == "power" for c, _ in cols)
                                  else real(e, t, cols, **kw)))
    rid = rr.record_run("gate", {}, {}, power_block=_block(), seed=1)
    assert rid, "열이 없다고 기록 자체가 실패하면 안 된다"
    d = rr.get_run(rid)
    assert d["power"] is None                   # ★있는 척하지 않는다★
    assert d["outputs"]["power_block"]["power"] == pytest.approx(0.4)  # JSON 엔 있다


def test_the_column_list_is_derived_not_hand_counted(mem_rr):
    """★위치 인덱스를 손으로 세지 않는다 (M1-S)★ 열이 늘면 인덱스가 밀린다."""
    rr.record_run("gate", {}, {}, power_block=_block())
    cols = rr._col_list()
    assert cols[:len(rr._BASE_COL_LIST)] == rr._BASE_COL_LIST
    assert "power" in cols and "mde" in cols and "n_eff" in cols
    assert len(cols) == len(set(cols)), "열 이름이 중복된다"


def test_listing_runs_still_works_and_carries_power(mem_rr):
    rr.record_run("gate", {}, {}, power_block=_block(power=0.2))
    rr.record_run("gate", {}, {}, power_block=_block(power=0.95))
    got = sorted(x["power"] for x in rr.list_runs(kind="gate"))
    assert got == [pytest.approx(0.2), pytest.approx(0.95)]
