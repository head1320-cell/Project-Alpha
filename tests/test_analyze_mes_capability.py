"""MES 가 최적화 경로에 들어오고, 능력 요건이 실제로 막는다 (M2-B)
==============================================================================
M1 이 능력 사다리를 지었지만 그것을 **읽고 무언가를 막는 코드**는 없었다. 배지는
화면에 있고 판정은 어디에도 쓰이지 않는 상태 — 이 저장소가 R0·M1-V·P2 에서 세 번
닫은 "지었는데 안 배선됨" 계열이다.

★게이트가 레벨 서수가 아니라 요건 프로브인 이유 (계획서가 틀렸던 지점)★
------------------------------------------------------------------------------
처음 계획은 "`capability_level` 이 L2 미만이면 EP 거부" 였다. 라이브로 재 보니 사다리는
**L0 이 최상단, L3 이 안전 기저**이고 `resolve()` 는 요건이 모두 통과하는 **가장 높은**
레벨을 돌려준다. 이 환경은 L1 — 즉 L1 은 L2 보다 **위**다. 원안대로면 정상 환경에서
EP 가 막힌다.

그리고 `capability.py:243` 이 직접 적어 두었듯 **레벨 간 요건은 포함관계가 아니다**
(L1 이 L2 의 요건을 필요로 하지 않는다). L1 도달이 `entropy_pooling` 이 있다는 뜻이
아니므로, 서수가 아니라 **그 엔진이 필요로 하는 요건 하나**를 봐야 한다.
"""

from __future__ import annotations

import pytest

from src.engine.capability import LEVEL_ORDER, LEVEL_REQUIREMENTS, probe_all, resolve


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


TICKERS = ["005930", "000660", "035420", "051910"]


def _body(**kw):
    b = {"tickers": list(TICKERS), "lookback_days": 500, "mc_paths": 100,
         "record_run": False}
    b.update(kw)
    return b


# ── 1. ★사다리의 방향을 먼저 고정한다★ ─────────────────────────────────────

def test_the_ladder_runs_from_l0_best_to_l3_floor():
    """이 순서를 잘못 읽으면 게이트 부등호가 통째로 뒤집힌다 (실제로 그랬다)."""
    assert LEVEL_ORDER[0] == "L0" and LEVEL_ORDER[-1] == "L3"
    assert LEVEL_REQUIREMENTS["L3"] == (), "안전 기저에 요건이 있으면 바닥이 아니다"


def test_level_requirements_are_not_nested():
    """★L1 에 도달했다고 L2 의 요건이 있는 것이 아니다★

    `capability.py` 가 주석으로 적어 둔 사실을 테스트로 고정한다. 이것이 참이기 때문에
    게이트는 레벨 서수가 아니라 요건 이름을 봐야 한다.
    """
    assert not set(LEVEL_REQUIREMENTS["L2"]) & set(LEVEL_REQUIREMENTS["L1"])


def test_entropy_pooling_is_an_l2_requirement_not_an_l1_one():
    assert "entropy_pooling" in LEVEL_REQUIREMENTS["L2"]
    assert "entropy_pooling" not in LEVEL_REQUIREMENTS["L1"]


# ── 2. ★게이트는 요건 프로브를 본다★ (짝 단언) ────────────────────────────

def test_ep_is_allowed_when_the_entropy_pooling_probe_passes(client):
    """이 환경은 실측 L1 인데 EP 는 **허용된다** — 서수로 막았다면 여기서 red 다."""
    if not probe_all().get("entropy_pooling", {}).get("ok"):
        pytest.skip("이 환경에서는 entropy_pooling 요건이 없다")
    assert resolve()["level"] == "L1", "환경 전제가 바뀌었다 — 짝 단언을 다시 읽어야 한다"
    r = client.post("/api/v1/allocation/analyze", json=_body(model="ep"))
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["error"] is False
    assert b["mu_engine"] == "ep"


def test_ep_is_refused_with_that_probes_own_reason_when_it_fails(client, monkeypatch):
    """요건을 깨면 **그 프로브의 사유로** 막힌다."""
    import src.api.allocation_routes as ar

    def broken():
        p = probe_all()
        p["entropy_pooling"] = {"ok": False, "reason": "테스트가 요건을 제거했습니다",
                                "description": "", "detail": None}
        return p

    monkeypatch.setattr(ar, "probe_all", broken, raising=False)
    monkeypatch.setattr("src.engine.capability.probe_all", broken)
    r = client.post("/api/v1/allocation/analyze", json=_body(model="ep"))
    assert r.status_code == 422, r.text
    assert "테스트가 요건을 제거했습니다" in r.json()["detail"]


def test_other_models_are_untouched_by_the_capability_gate(client, monkeypatch):
    """★게이트가 EP 에만 걸린다★ 요건이 없어도 mvo 는 계속 돈다."""
    def broken():
        p = probe_all()
        p["entropy_pooling"] = {"ok": False, "reason": "없음", "description": "", "detail": None}
        return p

    monkeypatch.setattr("src.engine.capability.probe_all", broken)
    r = client.post("/api/v1/allocation/analyze", json=_body(model="mvo"))
    assert r.status_code == 200, r.text
    assert r.json()["mu_engine"] == "mvo"


# ── 3. 실현 불가 뷰는 500 이 아니라 **사유가 있는 422** ────────────────────

def test_contradictory_views_return_422_with_the_reason_not_500(client):
    r = client.post("/api/v1/allocation/analyze", json=_body(
        model="ep",
        views=[{"assets": ["005930"], "direction": 1, "magnitude_pct": 25, "confidence": 50},
               {"assets": ["005930"], "direction": -1, "magnitude_pct": 25, "confidence": 50}]))
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert "동시에 만족" in d
    assert "005930" in d, "어느 뷰가 문제인지 없으면 고칠 방법이 없다"


# ── 4. MES 조인 — 복제가 아니라 참조 ───────────────────────────────────────

def _make_mes() -> str | None:
    """실제 스냅샷을 만들어 MES 로 승격시킨다 (M1-V 의 생산 경로 그대로).

    ★`build_and_store` 는 dict 가 아니라 **snapshot_id 문자열**을 돌려준다★ (실측)
    P2 에서 `upsert_alpha` 를 dict 로 착각했던 것과 같은 계열이다 — 반환 계약을 읽고
    쓰는 것이 먼저다.
    """
    from src.engine.regime_snapshot_builder import build_and_store
    try:
        return build_and_store(market="kr")
    except Exception:
        return None


def test_an_unknown_mes_id_is_refused_before_any_computation(client):
    r = client.post("/api/v1/allocation/analyze", json=_body(mes_id="rgs_does_not_exist"))
    assert r.status_code == 422
    assert "찾을 수 없" in r.json()["detail"]


def _stamp_level(sid: str, level: str) -> None:
    """MES 행의 능력 레벨을 **라이브와 다른 값**으로 직접 바꾼다.

    ★왜 이렇게까지 하는가★ 처음 이 테스트는 저장값과 응답값이 같은지만 봤다. 그런데
    이 환경에서는 고정 시점 레벨과 라이브 레벨이 **둘 다 L1** 이라, 라우트가 조인을
    버리고 새로 판정해도 같은 값이 나와 **프로브가 red 가 되지 않았다**. 실패할 수 없는
    가드는 가드가 아니므로, 두 값을 강제로 갈라놓고 어느 쪽을 읽는지 본다.
    """
    from sqlalchemy import text

    from src.data.regime_snapshots import _engine
    with _engine().begin() as c:
        c.execute(text("UPDATE regime_snapshots SET capability_level = :l "
                       "WHERE snapshot_id = :s"), {"l": level, "s": sid})


def test_the_capability_level_is_joined_from_the_mes_row_not_recomputed(client):
    """★단일 출처는 MES 행이다★ 라우트가 새로 판정하면 고정 시점의 사실이 사라진다."""
    sid = _make_mes()
    if not sid:
        pytest.skip("이 환경에서 스냅샷을 만들 수 없다")
    live = resolve()["level"]
    pinned = "L3" if live != "L3" else "L2"      # 라이브와 반드시 다른 값
    _stamp_level(sid, pinned)

    r = client.post("/api/v1/allocation/analyze", json=_body(mes_id=sid))
    assert r.status_code == 200, r.text
    mes = r.json()["mes"]
    assert mes["mes_id"] == sid
    assert mes["capability_level"] == pinned, (
        f"MES 행의 값({pinned}) 대신 라이브 판정({live})이 나왔다 — 조인이 아니라 재계산이다")


def test_a_divergence_between_the_pinned_and_live_level_is_reported(client):
    """★불일치는 숨기지 않는다★ 다만 막지도 않는다 — 고정 시점의 해석일 뿐이다."""
    if not probe_all().get("entropy_pooling", {}).get("ok"):
        pytest.skip("이 환경에서는 entropy_pooling 요건이 없다")
    sid = _make_mes()
    if not sid:
        pytest.skip("이 환경에서 스냅샷을 만들 수 없다")
    live = resolve()["level"]
    _stamp_level(sid, "L3" if live != "L3" else "L2")

    r = client.post("/api/v1/allocation/analyze", json=_body(model="ep", mes_id=sid))
    assert r.status_code == 200, r.text
    mes = r.json()["mes"]
    assert mes["live_capability_level"] == live
    assert mes.get("capability_diverged"), "레벨이 갈라졌는데 화면이 알 방법이 없다"


def test_without_a_mes_the_response_says_so_rather_than_inventing_one(client):
    """★증거 없이 돌았다는 것도 사실이다★ 빈 값을 지어내지 않는다."""
    r = client.post("/api/v1/allocation/analyze", json=_body())
    assert r.status_code == 200, r.text
    assert r.json()["mes"] is None


def test_mes_id_is_not_defaulted_from_regime_snapshot_id(client):
    """★세션이 붙인 스냅샷 ≠ 케이스가 고정한 증거★ 하나로 다른 하나를 채우면
    "케이스가 고정했다" 는 없는 사실이 만들어진다 (M1-S 가 두 열을 나눈 이유)."""
    sid = _make_mes()
    if not sid:
        pytest.skip("이 환경에서 스냅샷을 만들 수 없다")
    r = client.post("/api/v1/allocation/analyze", json=_body(regime_snapshot_id=sid))
    assert r.status_code == 200, r.text
    assert r.json()["mes"] is None, "regime_snapshot_id 가 mes 로 승격됐다"


# ── 5. 엔진 라벨은 서버가 찍는다 ────────────────────────────────────────────

@pytest.mark.parametrize("model,expected", [("mvo", "mvo"), ("min_var", "mvo"),
                                            ("risk_parity", "mvo")])
def test_non_view_engines_are_never_labelled_bl_or_ep(client, model, expected):
    r = client.post("/api/v1/allocation/analyze", json=_body(model=model))
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["mu_engine"] == expected
    assert b["ep"] is None


def test_the_ep_diagnostics_ride_along_when_ep_runs(client):
    if not probe_all().get("entropy_pooling", {}).get("ok"):
        pytest.skip("이 환경에서는 entropy_pooling 요건이 없다")
    r = client.post("/api/v1/allocation/analyze", json=_body(
        model="ep",
        views=[{"assets": ["005930"], "direction": 1, "magnitude_pct": 8, "confidence": 50}]))
    assert r.status_code == 200, r.text
    ep = r.json()["ep"]
    assert ep is not None and ep["feasible"] is True
    # ★신뢰도가 반영됐다고 오해하지 않도록 화면이 읽을 플래그가 있어야 한다★
    assert ep["confidence_used"] is False
    assert ep["ens"] is not None and ep["ens_prior"] is not None
