"""CF 3부 P1 — ★제약 보고의 빈틈과 설명의 빈틈★ (보고만 · 엔진 무변경)

`constrained_solve` 는 `groups_of` 에 없는 업종의 상한을 ★아무 말 없이★ 건너뛴다(`_build_slsqp` 가
`groups.items()` 만 돈다). 업종을 읽지 못하면(`sector_groups_for` → `{}`) 업종 상한이 모두 빠진다 — 개발 DB 에는
`instrument_master` 가 없어 실제로 그렇다. 엔진(`constrained_opt.py`)은 SHA 가드라 손대지 않고, 같은 사실을
라우트(`_apply_constraints`)가 보고 `unapplied` 로 적는다.

설명(`explain_optimizer`)은 근사해(`approx`)나 계산 뒤 깎아 맞춘 해(`projected`)에도 "정한 제약 안에서 계산했어요"(확인)라고
말했다 — 확인이 아니라 가정이다. 기대 수익 추정 노드는 수익률 입력을 받기만 하고 쓰지 않는다 — 그 사실을 설명에 적는다.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.api import allocation_graph_explain as ex  # noqa: E402
from src.api.allocation_routes import ConstraintsInput, _apply_constraints  # noqa: E402

NAMES = ["000001", "000002", "000003", "000004"]
RNG = np.random.default_rng(11)


def _opt():
    R = RNG.normal(0.0004, 0.012, (300, len(NAMES)))
    return R, {"mu_used": (R.mean(axis=0) * 252).tolist(), "sigma_annual": (np.cov(R.T) * 252).tolist(),
               "weights": np.full(len(NAMES), 1 / len(NAMES)), "flow": {"optimized": None}, "fallbacks": []}


def _run(monkeypatch, groups: dict[str, str], model: str = "mvo", **c):
    import src.engine.constrained_opt as co
    monkeypatch.setattr(co, "sector_groups_for", lambda names: {t: g for t, g in groups.items() if t in names})
    R, opt = _opt()
    req = SimpleNamespace(constraints=ConstraintsInput(**c), model=model, weights=None, risk_aversion=None)
    return _apply_constraints(req, NAMES, R, opt, None)


SEMI = {"000001": "반도체", "000002": "반도체", "000003": "자동차"}   # 000004 는 업종을 모른다


# ── ① 업종 상한이 빠진 것을 보고한다 ─────────────────────────────────────────

def test_cap_for_a_sector_with_no_member_is_reported_unapplied(monkeypatch):
    rep = _run(monkeypatch, SEMI, group_caps_pct={"바이오": 20})
    gone = [u for u in rep["unapplied"] if u["kind"] == "group_cap"]
    assert [u["group"] for u in gone] == ["바이오"]
    assert "바이오" in gone[0]["text"] and "없" in gone[0]["text"]


def test_cap_for_a_present_sector_is_not_reported(monkeypatch):
    """짝 — 그 업종 종목이 있으면 상한은 적용됐다(빠졌다고 말하지 않는다)."""
    rep = _run(monkeypatch, {**SEMI, "000004": "자동차"}, group_caps_pct={"반도체": 50})
    assert rep["unapplied"] == []


def test_a_cap_not_reported_is_actually_enforced(monkeypatch):
    """★'빠지지 않았다' 는 말이 참인지★ — 보고가 본 업종 표와 엔진이 쓴 표가 같아야 한다. 상한이 비중에 걸린다."""
    import src.engine.constrained_opt as co
    groups = {**SEMI, "000004": "자동차"}
    monkeypatch.setattr(co, "sector_groups_for", lambda names: {t: g for t, g in groups.items() if t in names})
    R, opt = _opt()
    R[:, 0] += 0.002                       # 반도체 두 종목을 뚜렷이 좋게 — 상한이 없으면 그쪽으로 몰린다
    R[:, 1] += 0.002
    opt["mu_used"] = (R.mean(axis=0) * 252).tolist()
    opt["sigma_annual"] = (np.cov(R.T) * 252).tolist()
    req = SimpleNamespace(constraints=ConstraintsInput(group_caps_pct={"반도체": 20}), model="mvo", weights=None,
                          risk_aversion=None)
    rep = _apply_constraints(req, NAMES, R, opt, None)
    assert rep["unapplied"] == [] and rep["status"] == "ok"
    w = np.asarray(opt["weights"], dtype=float)
    assert w[0] + w[1] <= 0.20 + 0.01


def test_names_without_a_sector_are_named(monkeypatch):
    rep = _run(monkeypatch, SEMI, group_caps_pct={"반도체": 50})
    unk = [u for u in rep["unapplied"] if u["kind"] == "unknown_sector"]
    assert len(unk) == 1 and unk[0]["names"] == ["000004"]
    # 반도체 상한 자체는 적용됐다 — 그 상한이 빠졌다고 말하지 않는다
    assert not [u for u in rep["unapplied"] if u["kind"] == "group_cap"]


def test_unreadable_sectors_report_every_cap(monkeypatch):
    """업종을 하나도 못 읽으면(`{}`) 업종 상한은 ★전부★ 빠졌다 — 상한마다 적는다."""
    rep = _run(monkeypatch, {}, group_caps_pct={"반도체": 50, "자동차": 30})
    gone = sorted(u["group"] for u in rep["unapplied"] if u["kind"] == "group_cap")
    assert gone == ["반도체", "자동차"]
    assert all("읽지 못" in u["text"] for u in rep["unapplied"] if u["kind"] == "group_cap")
    # 모든 종목이 업종 미상이라는 줄을 따로 늘어놓지 않는다(같은 사실을 두 번 말하지 않는다)
    assert not [u for u in rep["unapplied"] if u["kind"] == "unknown_sector"]


def test_without_group_caps_nothing_is_unapplied(monkeypatch):
    """짝 — 업종 상한을 주지 않았으면 업종을 몰라도 빠진 것이 없다(공허한 경고 금지)."""
    rep = _run(monkeypatch, {}, max_weight_pct=40)
    assert rep["unapplied"] == []


def test_engine_still_skips_silently_so_the_route_is_the_one_speaking(monkeypatch):
    """★전제 확인★ — 엔진은 지금도 말하지 않는다. 이 보고가 없으면 아무도 말하지 않는다."""
    from src.engine.constrained_opt import Constraints, constrained_solve
    R, opt = _opt()
    sol = constrained_solve("mvo", NAMES, R, np.asarray(opt["mu_used"]), np.asarray(opt["sigma_annual"]),
                            Constraints(group_caps_pct={"바이오": 20}), groups_of=SEMI)
    text = " ".join(sol.get("notes") or []) + " ".join(sol.get("binding") or [])
    assert "바이오" not in text and sol.get("relaxed") == []


def test_analyze_route_carries_the_same_report(monkeypatch):
    """`/analyze` 와 캔버스가 같은 함수를 부른다 — 라우트 응답에도 `unapplied` 가 있다."""
    import src.engine.constrained_opt as co
    monkeypatch.setattr(co, "sector_groups_for", lambda names: {})
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    r = TestClient(create_app()).post("/api/v1/allocation/analyze", json={
        "tickers": ["005930", "000660", "035420"], "model": "mvo",
        "constraints": {"group_caps_pct": {"반도체": 40}}})
    assert r.status_code == 200, r.text
    cr = r.json()["constraints_report"]
    assert [u["group"] for u in cr["unapplied"] if u["kind"] == "group_cap"] == ["반도체"]


# ── ② 설명이 제약 상태를 바르게 말한다 ────────────────────────────────────

def _trust(cr: dict) -> list[dict]:
    return ex.explain_optimizer({"weights": {"A": 50.0, "B": 50.0}, "model": "mvo", "constraints_report": cr},
                                {}, None)["trust"]


def _texts(trust, state=None):
    return [t["text"] for t in trust if state is None or t["state"] == state]


def test_clean_constraint_report_is_confirmed():
    """짝 — 상태 ok · 빠진 것 없음 · 투영 아님 이면 지금처럼 확인."""
    t = _trust({"status": "ok", "violations": [], "binding": [], "relaxed": [], "notes": [], "projected": False,
                "unapplied": []})
    assert "정한 제약 안에서 계산했어요." in _texts(t, ex.CONFIRMED)


def test_approx_is_not_called_confirmed():
    t = _trust({"status": "approx", "violations": [{"kind": "turnover", "detail": "회전율 32% > 상한 20%"}],
                "binding": [], "relaxed": ["turnover"], "notes": [], "projected": False, "unapplied": []})
    assert not any("제약 안에서" in x for x in _texts(t, ex.CONFIRMED))
    assumed = " ".join(_texts(t, ex.ASSUMED))
    assert "회전율" in assumed and "느슨" in assumed and "어긋난 제약 1개" in assumed


def test_projected_is_not_called_confirmed():
    """공분산 전용 방식은 제약을 풀지 않고 계산 뒤에 깎아 맞춘다 — 회전율·시장 민감도는 적용되지 않는다."""
    t = _trust({"status": "ok", "violations": [], "binding": [], "relaxed": [], "notes": [], "projected": True,
                "unapplied": []})
    assert not any("제약 안에서" in x for x in _texts(t, ex.CONFIRMED))
    assert any("깎아 맞췄" in x and "회전율" in x for x in _texts(t, ex.ASSUMED))


def test_unapplied_caps_become_unknown_lines():
    t = _trust({"status": "ok", "violations": [], "binding": [], "relaxed": [], "notes": [], "projected": False,
                "unapplied": [{"kind": "group_cap", "group": "바이오", "cap_pct": 20.0,
                               "text": "업종 상한 ‘바이오’ 20%는 적용되지 않았어요 — 이 종목들 중 그 업종이 없어요."}]})
    assert "적용된 제약 안에서 계산했어요." in _texts(t, ex.CONFIRMED)
    assert any("바이오" in x for x in _texts(t, ex.UNKNOWN))


def test_infeasible_stays_failed():
    t = _trust({"status": "infeasible", "reason": "상한 합이 100% 보다 작아요", "violations": [], "binding": [],
                "relaxed": [], "notes": [], "unapplied": []})
    assert any("상한 합" in x for x in _texts(t, ex.FAILED))


# ── ③ 기대 수익 추정 노드는 수익률 입력을 쓰지 않는다고 말한다 ────────────────

@pytest.mark.parametrize("conditional", [False, True])
def test_estimate_says_it_does_not_use_its_returns_input(conditional):
    out = ex.explain_estimate({"settings": {"conditional": conditional}}, {}, None)
    assert any("이어진 수익률" in f and "쓰지 않아요" in f for f in out["facts"])


def test_optimizer_explain_does_not_carry_the_estimate_line():
    """짝 — 그 문장은 추정 노드의 것이다(옵티마이저는 수익률을 실제로 쓴다)."""
    out = ex.explain_optimizer({"weights": {"A": 100.0}, "model": "mvo"}, {}, None)
    assert not any("이어진 수익률" in f for f in out["facts"])
