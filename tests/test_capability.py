"""능력 사다리 — 위조할 수 없고, 사유 없이 강등하지 않는다 (M1-C)
==============================================================================
요청받은 아키텍처는 Neural SDE·PINN·RL-GNN·Diffusion DRO·cvxpylayers SPO 를 상위
티어에 놓는데, 이 환경에는 torch·cvxpy·cvxpylayers 가 없고 표본은 60개월 mock 이다.
사다리가 다이어그램이면 아무나 "L0" 이라고 적을 수 있다. 그래서 코드가 판정한다.

★이 파일이 잠그는 것 넷★
  1. 레벨을 **위조할 수 없다** — 가짜 모듈을 `sys.modules` 에 꽂아도 심볼이 없으면 안 열린다.
  2. 요건이 채워지면 레벨이 **실제로 오른다** — 1번만 있으면 "항상 L3" 도 통과한다(짝).
  3. 강등에는 **항상 사유가 있다**.
  4. **아래 사다리가 성한지도 답한다** — 위가 죽었을 때 한 칸 내려가는지 여러 칸
     추락하는지는 다른 사실이다.
"""

from __future__ import annotations

import sys
import types

import pytest

from src.engine.capability import (
    LEVEL_ORDER,
    LEVEL_REQUIREMENTS,
    probe_all,
    resolve,
)


# ── 1. ★위조 불가★ ─────────────────────────────────────────────────────────
def test_a_fake_module_does_not_open_a_level(monkeypatch):
    """`sys.modules` 에 빈 껍데기를 꽂아도 심볼이 없으면 열리지 않는다.

    `find_spec` 만 보는 프로브였다면 여기서 통과했을 것이고, 그건 곧 "쓸 수 없는
    모델을 쓸 수 있다고 말하는 것" 이다.
    """
    for name in ("torch", "torch.nn"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    p = probe_all()
    assert p["torch"]["ok"] is False, "빈 껍데기 모듈로 torch 요건이 열렸다"
    assert "심볼" in p["torch"]["reason"]


def test_the_current_environment_cannot_reach_the_frontier(monkeypatch):
    """실측 그대로 — torch 도 트렌드 API 도 없고 표본은 60개월이다."""
    r = resolve()
    assert r["level"] != "L0"
    assert r["blocked_level"] == LEVEL_ORDER[LEVEL_ORDER.index(r["level"]) - 1]
    assert r["blocked_reason"], "강등했는데 사유가 없다"
    # 사유는 **어느 요건이 왜** 인지 말해야 한다 — "L0 불가" 만으로는 올릴 방법이 없다.
    assert any(k in r["blocked_reason"] for k in ("torch", "cvxpylayers", "표본", "키"))


# ── 2. ★요건이 채워지면 레벨이 오른다★ (1번의 짝) ──────────────────────────
def test_satisfying_the_requirements_actually_raises_the_level(monkeypatch):
    """1번만 있으면 **무조건 L3 을 답하는** 구현도 통과한다 — 여기서 잠근다."""
    import src.engine.capability as cap

    base = probe_all()
    reached = resolve(base)["level"]
    idx = LEVEL_ORDER.index(reached)
    assert idx > 0, "이미 최상위라 이 테스트가 잴 것이 없다 (환경이 바뀌었다)"

    higher = LEVEL_ORDER[idx - 1]
    forced = {k: dict(v) for k, v in base.items()}
    for req in cap.LEVEL_REQUIREMENTS[higher]:
        forced[req] = {**forced[req], "ok": True, "reason": ""}

    assert resolve(forced)["level"] == higher, "요건을 다 채웠는데 레벨이 오르지 않았다"


def test_removing_a_requirement_from_a_level_lowers_the_bar(monkeypatch):
    """레벨은 요건 집합에서 파생된다 — 상수로 박혀 있지 않다."""
    import src.engine.capability as cap

    monkeypatch.setitem(cap.LEVEL_REQUIREMENTS, "L0", ())
    assert resolve()["level"] == "L0", "요건이 빈 레벨이 열리지 않았다"


# ── 3. ★아래 사다리가 성한지도 답한다★ ─────────────────────────────────────
def test_a_broken_rung_below_is_reported_not_hidden():
    """사다리의 요점은 "위가 죽으면 아래로" 다. 아래 칸이 비어 있으면 한 칸 강등이
    아니라 여러 칸 추락이고, 그건 도달 레벨만 봐서는 보이지 않는다.

    ★조건문으로 감싸지 않는다 (프로브로 배웠다)★ 처음에는
    `if not r["fallback_intact"]: assert ...` 로 썼는데, 폴백 파손을 숨기도록 코드를
    변이시키니 `fallback_intact` 가 True 가 되면서 **else 가지로 빠져 초록**이었다.
    답을 보고 분기하는 단언은 그 답이 틀렸을 때 아무것도 잡지 못한다.
    그래서 여기서는 `levels` 에서 **기대값을 파생시켜 대조**한다 — 환경이 바뀌어도
    참이고, 보고가 실제와 어긋나면 반드시 빨개진다.
    """
    r = resolve()
    below = LEVEL_ORDER[LEVEL_ORDER.index(r["level"]) + 1:]
    expected_broken = [lv for lv in below if not r["levels"][lv]["ok"]]

    assert r["fallback_broken_levels"] == expected_broken, \
        "아래 칸의 실제 상태와 보고가 어긋난다 — 추락 위험이 화면에서 사라진다"
    assert r["fallback_intact"] is (not expected_broken)
    assert r["fallback_next"] == next((lv for lv in below if r["levels"][lv]["ok"]), None)
    if expected_broken:
        assert r["fallback_reason"], "추락 경로에 사유가 없다"
        for lv in expected_broken:
            assert lv in r["fallback_reason"], f"{lv} 이 파손인데 사유에 없다"


def test_the_last_rung_always_holds():
    """L3 은 요건이 없다 — numpy 만으로 성립하는 마지막 바닥이라 절대 비지 않는다.
    이게 깨지면 시스템이 내려갈 곳이 없다."""
    assert LEVEL_REQUIREMENTS["L3"] == ()
    assert resolve()["levels"]["L3"]["ok"] is True


# ── 4. 모든 요건이 자기 사유를 갖는다 ───────────────────────────────────────
def test_every_failing_requirement_explains_itself():
    """사유 없는 미가용은 "왜" 를 사용자에게서 빼앗고, 고칠 방법도 함께 빼앗는다."""
    p = probe_all()
    assert len(p) >= 8, "요건이 이렇게 적을 리 없다 — 레지스트리가 비었는지 확인"
    for name, v in p.items():
        assert v["description"], f"{name}: 설명이 없다"
        if not v["ok"]:
            assert v["reason"], f"{name}: 미가용인데 사유가 없다"


def test_a_probe_that_crashes_does_not_crash_the_ladder(monkeypatch):
    """프로브 하나가 죽어도 사다리는 답해야 한다 — 답을 못 하면 화면이 빈다."""
    import src.engine.capability as cap

    def boom():
        raise RuntimeError("probe exploded (test)")

    monkeypatch.setitem(cap.REQUIREMENTS, "statsmodels", ("깨지는 프로브", boom))
    p = probe_all()
    assert p["statsmodels"]["ok"] is False
    assert "프로브 실행 실패" in p["statsmodels"]["reason"]
    assert resolve(p)["level"] in LEVEL_ORDER


# ── 5. 라우트 ───────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


def test_the_capability_route_exposes_level_and_reason(client):
    r = client.get("/api/v1/macro/capability")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["level"] in LEVEL_ORDER
    assert body["label"]
    assert "requirements" in body and body["requirements"]
    assert "fallback_intact" in body
