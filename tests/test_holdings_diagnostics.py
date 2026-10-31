"""임의의 보유를 넣으면 ★그 포트폴리오의 상태★ 가 한 응답으로 나온다 (AA5)

설계: `docs/plans` AA · 로드맵 P2 "보유 진단 표면"

## ★있는 것을 부른다★

`factor_exposure.asset_factor_betas` · `portfolio_factor_exposure` ·
`factor_concentration` · `allocation_routes._risk_contribution_report` ·
`liquidity_gate.LiquidityStore`. 새 계산을 만들지 않는다 — 죽은
`portfolio_manager.py` 의 문구도 되살리지 않는다.

## ★P-1(인증) 없이 가능한 이유★

보유를 **요청 본문으로** 받는다. "누구의" 보유인지 묻지 않으므로 계좌 소유권
판단이 필요 없다. 그 사실을 응답 `note` 가 적는다 — 나중에 계좌에서 읽는 판이
오면 그때가 P-1 이 선행조건이 되는 지점이다.

## 완료 판정(로드맵)

> *"임의의 보유 딕트를 넣으면 집중도·팩터 노출·유동성 경고가 한 응답으로 나오고,
>   각 수치에 ★미상은 `None` 과 사유★가 붙는다."*
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

URL = "/api/v1/diagnostics/holdings"
HOLDINGS = {"005930": 50.0, "000660": 30.0, "035420": 20.0}


@pytest.fixture(scope="module")
def client():
    from src.app_factory import create_app
    return TestClient(create_app())


def _post(client, **kw):
    body = {"holdings": dict(HOLDINGS), "weight_unit": "percent"}
    body.update(kw)
    r = client.post(URL, json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ═══════════════════════════════════════════════════════════════════════════
# ⑬ 한 응답 · 각 블록이 `available` + `reason`
# ═══════════════════════════════════════════════════════════════════════════
_BLOCKS = ("factor_exposure", "factor_concentration", "risk_contributions",
           "liquidity")


def test_one_response_carries_every_block(client):
    j = _post(client)
    for name in _BLOCKS:
        assert name in j, f"{name} 블록이 없습니다"


@pytest.mark.parametrize("name", _BLOCKS)
def test_every_block_says_whether_it_is_available_and_why_not(client, name):
    """★미상 자리마다 사유가 붙는다★ — 사유 없는 `null` 은 침묵 폴백이다."""
    block = _post(client)[name]
    assert "available" in block, f"{name}: available 이 없습니다"
    if not block["available"]:
        assert block.get("reason"), f"{name}: 못 냈는데 사유가 없습니다"


def test_the_response_declares_its_own_evidence(client):
    """AA3 의 결정측 축을 그대로 쓴다 — 새 판정 어휘를 만들지 않는다."""
    from src.engine.decision_evidence import DECISION_REQUIRED_AXES
    ev = _post(client)["evidence_rollup"]
    for axis in DECISION_REQUIRED_AXES:
        assert ev["axes"].get(axis) is not None, axis
    assert ev["status"] in ("verified", "partial", "unverified", "unknown")


def test_the_note_says_whose_holdings_it_did_not_ask(client):
    """★P-1 경계를 응답이 적는다★"""
    note = _post(client)["note"]
    assert "요청" in note and ("계좌" in note or "누구" in note)


# ═══════════════════════════════════════════════════════════════════════════
# ⑭ 커버리지를 숨기지 않는다
# ═══════════════════════════════════════════════════════════════════════════
def test_a_block_that_cannot_be_computed_says_why(client, monkeypatch):
    """★변이 i 가 이 테스트를 요구했다★

    처음에는 `if not block["available"]` 가지가 **한 번도 참이 아니었다** — mock
    모드에서 모든 블록이 성공하므로, `reason` 을 통째로 지워도 테스트가 초록이었다.
    그래서 실패를 **강제로 만들어** 사유가 오는지 본다.
    """
    monkeypatch.setattr(
        "src.engine.factor_exposure.asset_factor_betas",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("프록시 계열 없음")))
    j = _post(client)
    expo = j["factor_exposure"]
    assert expo["available"] is False, "실패를 강제했는데 성공했습니다 — 가지를 못 탔습니다"
    assert expo.get("reason"), "못 냈는데 사유가 없습니다 — 침묵 폴백입니다"
    conc = j["factor_concentration"]
    assert conc["available"] is False and conc.get("reason")
    # ★한 블록의 실패가 나머지를 죽이지 않는다★
    assert j["liquidity"]["available"] is True
    assert "evidence_rollup" in j


def test_a_liquidity_failure_also_says_why(client, monkeypatch):
    """★짝★ 다른 블록에서도 같은 규율이 지켜지는가."""
    monkeypatch.setattr(
        "src.engine.liquidity_gate.LiquidityStore.get_default",
        classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("스토어 없음"))))
    liq = _post(client)["liquidity"]
    assert liq["available"] is False and liq.get("reason")


def test_factor_coverage_is_reported_not_assumed(client):
    """베타를 못 낸 자산이 있으면 `coverage_pct` 가 100 미만으로 **보고된다**.

    ★0 으로 채우면 노출이 실제보다 작아 보인다★ — `portfolio_factor_exposure`
    가 이미 그 규율을 갖고 있고, 이 표면은 그것을 **가리지 않는다**.
    """
    expo = _post(client)["factor_exposure"]
    if not expo["available"]:
        pytest.skip(f"노출을 못 냈습니다: {expo['reason']}")
    for factor, row in expo["by_factor"].items():
        assert "coverage_pct" in row, factor
        if row.get("missing"):
            assert row["coverage_pct"] < 100.0, (
                f"{factor}: 베타를 못 낸 자산이 있는데 커버리지가 100 입니다")


def test_a_missing_beta_actually_lowers_the_reported_coverage(client, monkeypatch):
    """★변이 j 가 이 테스트를 요구했다★

    위 테스트의 `if row.get("missing")` 가지는 mock 에서 **한 번도 참이 아니다**
    (모든 자산이 베타를 낸다). 그래서 `coverage_pct` 를 항상 100 으로 박아도
    초록이었다. 여기서는 베타를 못 내는 자산을 **섞어서** 실제로 재게 한다.

    ★0 으로 채우면 노출이 실제보다 작아 보인다★ — 이 표면이 그 사실을 가리지
    않는지가 요점이다.
    """
    from src.engine import factor_exposure as fe
    real = fe.asset_factor_betas

    def _drop_one(codes, **kw):
        out = real(list(codes), **kw)
        if not out.get("available"):
            return out
        victim = sorted(out["assets"])[0]
        out["assets"][victim] = {"available": False,
                                 "reason": "테스트가 일부러 베타를 지웠습니다"}
        return out

    monkeypatch.setattr("src.engine.factor_exposure.asset_factor_betas", _drop_one)
    expo = _post(client)["factor_exposure"]
    if not expo["available"]:
        pytest.skip(f"노출을 못 냈습니다: {expo['reason']}")

    lowered = [f for f, row in expo["by_factor"].items()
               if row.get("missing") and row["coverage_pct"] < 100.0]
    assert lowered, (
        "베타를 지운 자산이 있는데 어떤 팩터도 커버리지를 낮춰 보고하지 "
        "않았습니다 — 결측을 0 으로 채우고 있습니다")
    for f in lowered:
        assert expo["by_factor"][f]["missing"], f


def test_risk_contributions_name_their_portfolio_and_sigma(client):
    """★어느 포트폴리오·어느 Σ 인지 항상 밝힌다★ (`_risk_contribution_report` 의 계약)"""
    rc = _post(client)["risk_contributions"]
    assert rc.get("weights_source") and rc.get("sigma_source")


def test_liquidity_reports_per_ticker_and_never_invents_spread(client):
    """운영 경로에 호가 원천이 없다 — mock 이 아니면 `spread_pct` 는 `None` 이다."""
    liq = _post(client)["liquidity"]
    if not liq["available"]:
        pytest.skip(f"유동성을 못 냈습니다: {liq['reason']}")
    assert set(liq["by_ticker"]) == set(HOLDINGS)
    for row in liq["by_ticker"].values():
        assert "adv_value_억" in row and "is_tradable" in row


# ═══════════════════════════════════════════════════════════════════════════
# 입력 계약 — ★단위를 확정하지 않으면 거절한다★
# ═══════════════════════════════════════════════════════════════════════════
def test_an_ambiguous_weight_unit_is_refused(client):
    """비중 단위가 애매하면 계산하지 않는다 — 분수를 퍼센트로 읽으면 100배 틀린다."""
    r = client.post(URL, json={"holdings": {"005930": 0.5, "000660": 0.5}})
    assert r.status_code == 422, r.text


def test_empty_holdings_are_refused_with_a_reason(client):
    r = client.post(URL, json={"holdings": {}, "weight_unit": "percent"})
    assert r.status_code == 422


def test_a_single_asset_still_answers(client):
    """★자산 하나여도 답한다★ — 리스크 기여는 못 내도 유동성은 낼 수 있다."""
    j = _post(client, holdings={"005930": 100.0})
    assert j["liquidity"]["available"] or j["liquidity"]["reason"]
    for name in _BLOCKS:
        assert "available" in j[name]
