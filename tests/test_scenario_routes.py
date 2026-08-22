"""시나리오 API — 실행 · 3자 비교 · 카탈로그의 두 축 (스펙 §5, Phase 9b).

이 파일이 고정하는 것

1. **`model_type` 이 결과까지 따라간다.** 카탈로그에만 있으면 "이건 가정입니다" 가 선택
   화면에서만 보이고 결과 화면에서 사라진다 — §5 는 *결과가 나타나는 모든 곳*을 요구한다.
2. **`/stress-scenarios` 의 두 축이 분리돼 있다.** 12 패밀리는 분류, `model_type` 은 인식론.
   레거시 `mode` 는 한 글자도 바뀌지 않는다(프론트가 결과 렌더링을 그것으로 분기한다).
3. **3자 비교는 재구현이 아니라 합성이다.** 다리별 손실 = 충격 × 노출.
4. **사용자 정의 팩은 역사적 사실을 주장할 수 없다.**
"""
import pytest
from fastapi.testclient import TestClient

from src.app_factory import create_app

RUN = "/api/v1/allocation/scenario-run"
THREE = "/api/v1/allocation/scenario-three-way"
CAT = "/api/v1/allocation/stress-scenarios"
HOLDINGS = {"005930": 0.6, "000660": 0.4}
RULES = [{"factor_id": "avg_abs_momentum", "universe": ["SPY"]}]


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 카탈로그 — 두 축, 12 패밀리, 불변 `mode`
# ═══════════════════════════════════════════════════════════════════════════════
def test_catalogue_lists_all_twelve_families_even_the_empty_one(client):
    body = client.get(CAT).json()
    assert len(body["families"]) == 12
    empty = [f for f in body["families"] if not f["covered"]]
    assert empty and all(f.get("reason") for f in empty), (
        "빈 패밀리가 사유 없이 나열되거나 목록에서 사라졌습니다")


def test_every_catalogue_item_carries_both_axes(client):
    items = [i for g in client.get(CAT).json()["groups"] for i in g["items"]]
    assert items
    for i in items:
        assert i["model_type"] in ("historical_replay", "hypothetical"), i
        assert i["family"] and i["mode"], i
        assert i["pack_id"] and i["content_hash"], i


def test_the_legacy_mode_vocabulary_is_unchanged(client):
    """★프론트가 결과 렌더링을 `mode` 로 분기한다★ 패밀리를 12종으로 늘려도 이 축은 그대로다."""
    modes = {i["mode"] for g in client.get(CAT).json()["groups"] for i in g["items"]}
    assert modes == {"hypothetical", "historical", "kr_pack"}


def test_the_korean_packs_are_labelled_hypothetical_in_the_catalogue(client):
    items = {i["pack_id"]: i for g in client.get(CAT).json()["groups"] for i in g["items"]}
    assert items["semi_selloff"]["model_type"] == "hypothetical"
    assert items["semi_selloff"]["mode"] == "kr_pack"      # 분류 축은 그대로


def test_replays_do_not_take_a_severity_multiplier(client):
    items = {i["pack_id"]: i for g in client.get(CAT).json()["groups"] for i in g["items"]}
    assert items["hist_2020_covid"]["severity_applies"] is False
    assert items["semi_selloff"]["severity_applies"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 실행 — 라벨이 결과까지 따라간다
# ═══════════════════════════════════════════════════════════════════════════════
def test_a_run_carries_model_type_and_pack_identity(client):
    r = client.post(RUN, json={"holdings": HOLDINGS, "pack_id": "semi_selloff"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model_type"] == "hypothetical"
    assert body["identity"].startswith("semi_selloff@")
    assert body["shock_pct"] is not None and body["shock_basis"]


def test_an_m8_pack_runs_through_the_existing_path(client):
    r = client.post(RUN, json={"holdings": HOLDINGS, "pack_id": "rate_hike_200bp"})
    assert r.status_code == 200, r.text
    assert r.json()["model_type"] == "hypothetical"


def test_a_replay_reports_max_drawdown_and_says_so(client):
    """★두 종류의 손실을 같은 이름으로 부르지 않는다★

    가정 충격은 즉시 손실(%)을, 역사 리플레이는 구간 최대 낙폭을 낸다. 같은 `shock_pct` 에
    싣되 `shock_basis` 가 무엇을 잰 숫자인지 말해야 나란히 놓인 두 팩을 오해하지 않는다.
    """
    body = client.post(RUN, json={"holdings": HOLDINGS, "pack_id": "hist_2020_covid"}).json()
    assert body["model_type"] == "historical_replay"
    assert body["available"] is True, "이 환경에서 리플레이가 가용해야 이 테스트가 뜻을 갖는다"
    assert "낙폭" in body["shock_basis"], body["shock_basis"]
    assert body["shock_pct"] == body["max_dd_pct"]


def test_an_unavailable_replay_reports_no_shock_rather_than_zero(client, monkeypatch):
    """★미가용은 '충격 없음' 이 아니다★ 0 으로 채우면 그 시나리오가 안전해 보인다.

    이 환경에서는 mock 합성 리플레이가 가용하므로, 미가용 경로를 **강제로** 태운다 —
    환경에 따라 분기가 안 돌면 통과해도 아무것도 증명하지 못한다(7b 의 헛돈 게이트).
    """
    import src.api.allocation_routes as ar
    monkeypatch.setattr(ar, "allocation_stress", lambda req: {
        "error": False, "mode": "historical", "available": False,
        "scenario": req.scenario, "reason": "해당 기간 시세 데이터 미보유"})

    body = client.post(RUN, json={"holdings": HOLDINGS, "pack_id": "hist_2008_gfc"}).json()
    assert body["shock_pct"] is None, "미가용 구간을 0 으로 채웠습니다"
    assert "미가용" in body["shock_basis"]


def test_an_unknown_pack_is_422_not_500(client):
    r = client.post(RUN, json={"holdings": HOLDINGS, "pack_id": "nope"})
    assert r.status_code == 422 and "nope" in r.json()["detail"]


@pytest.mark.parametrize("payload,needle", [
    ({}, "둘 다 비어"),
    ({"pack_id": "semi_selloff",
      "pack": {"market": -5.0, "factors": {"size": -3.0}}}, "둘 다 주어"),
])
def test_exactly_one_of_pack_id_or_inline_pack(client, payload, needle):
    r = client.post(RUN, json={"holdings": HOLDINGS, **payload})
    assert r.status_code == 422, r.text
    assert needle in r.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 사용자 정의 팩 — 저장되지 않고, 역사적 사실을 주장할 수 없다
# ═══════════════════════════════════════════════════════════════════════════════
def test_an_inline_pack_runs_and_is_forced_hypothetical(client):
    r = client.post(RUN, json={
        "holdings": HOLDINGS,
        "pack": {"label": "내 충격", "market": -6.0,
                 "factors": {"size": -4.0, "leverage": -3.0},
                 "assumptions": {"corr_rise": 0.2, "vol_rise": 0.4,
                                 "liquidity_deteriorate": 0.5}}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model_type"] == "hypothetical"
    assert body["pack"]["family"] == "user_authored"
    assert body["shock_pct"] is not None


def test_an_inline_pack_cannot_smuggle_a_model_type(client):
    """★클라이언트가 정하면 §5 가 무의미해진다★

    방어가 두 겹이다 — `InlinePack` 에 `model_type` 필드가 **없어서** Pydantic 이 버리고,
    `inline_pack()` 이 값을 하드코딩한다. 이 테스트는 바깥 겹을 잡고, 안쪽 겹은
    `test_scenario_packs.py::test_an_inline_pack_cannot_claim_to_be_historical` 가 잡는다
    (스키마가 언젠가 extra 를 허용하게 돼도 엔진 쪽이 버틴다).
    """
    r = client.post(RUN, json={
        "holdings": HOLDINGS,
        "pack": {"label": "가짜 역사", "model_type": "historical_replay",
                 "market": -6.0, "factors": {"size": -4.0}, "assumptions": {}}})
    assert r.status_code == 200, r.text
    assert r.json()["model_type"] == "hypothetical"


def test_an_inline_pack_with_an_unknown_factor_is_refused(client):
    r = client.post(RUN, json={
        "holdings": HOLDINGS,
        "pack": {"market": -6.0, "factors": {"made_up_factor": -4.0}, "assumptions": {}}})
    assert r.status_code == 422
    assert "made_up_factor" in r.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 3자 비교 — 합성이지 재구현이 아니다
# ═══════════════════════════════════════════════════════════════════════════════
def test_three_way_scales_the_shock_by_each_leg_exposure(client, monkeypatch):
    """★노출 1.0 만으로는 아무것도 증명하지 못한다★

    곱셈이 항등이 되는 노출로만 채점하면 곱셈을 통째로 지워도 통과한다(7b 의 헛돈 게이트와
    같은 함정). 그래서 두 팩터 중 하나만 통과시켜 `continuous` 노출을 **0.5** 로 만든다 —
    기준선(1.0)과 타이밍(0.5)의 손실이 달라야만 통과한다.
    """
    from src.data.pit_macro import DataStatus, ResearchUsage
    from src.engine import timing_rules_v2 as v2

    # 같은 팩터(방향 above·임계 0)를 둘 — 값 부호만으로 하나는 온, 하나는 오프가 된다.
    # 방향이 다른 팩터를 섞으면 부호의 뜻이 갈려 의도한 0.5 가 나오지 않는다.
    vals = iter([1.0, -1.0])
    monkeypatch.setattr(v2, "read_factor", lambda fid, **kw: v2.FactorReading(
        fid, next(vals), ResearchUsage.BACKTEST_ELIGIBLE, DataStatus.REAL, None, "test"))

    r = client.post(THREE, json={
        "holdings": HOLDINGS, "pack_id": "semi_selloff", "market": "kr",
        "combination": "continuous",
        "rules": [{"factor_id": "avg_abs_momentum", "universe": ["SPY"]},
                  {"factor_id": "avg_abs_momentum", "universe": ["QQQ"]}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["composed"] is True
    shock = body["scenario"]["shock_pct"]

    judged = {n: leg for n, leg in body["legs"].items() if "shock_pct" in leg}
    exposures = {n: leg["exposure"] for n, leg in judged.items()}
    assert exposures["baseline"] == 1.0 and exposures["timing_only"] == 0.5, exposures
    assert len(set(leg["shock_pct"] for leg in judged.values())) > 1, (
        "다리별 손실이 전부 같습니다 — 노출을 곱하지 않아도 통과하는 상태입니다")

    for leg in judged.values():
        assert leg["shock_pct"] == pytest.approx(round(shock * leg["exposure"], 2), abs=0.011)
        assert leg["cash_pct"] == pytest.approx(round((1 - leg["exposure"]) * 100, 2), abs=0.011)


def test_three_way_carries_the_model_type_and_the_approximation_caveat(client):
    body = client.post(THREE, json={"holdings": HOLDINGS, "pack_id": "semi_selloff",
                                    "market": "kr", "combination": "all",
                                    "rules": RULES}).json()
    assert body["model_type"] == "hypothetical"
    assert "선형" in body["composition_note"], "선형 근사라는 사실이 응답에 없습니다"


def test_three_way_reuses_the_timing_derivation(client):
    """★두 번째 구현을 만들면 타이밍 탭과 스트레스 탭이 다른 신호를 비교한다★

    같은 규칙·같은 조합이면 `/timing/three-way` 와 다리별 노출이 일치해야 한다.
    """
    body = {"market": "kr", "combination": "continuous", "rules": RULES}
    a = client.post("/api/v1/allocation/timing/three-way", json=body).json()
    b = client.post(THREE, json={**body, "holdings": HOLDINGS,
                                 "pack_id": "semi_selloff"}).json()
    for name in a["legs"]:
        assert a["legs"][name]["exposure"] == b["legs"][name]["exposure"], name
        assert a["legs"][name]["state"] == b["legs"][name]["state"], name


def test_three_way_requires_at_least_one_rule(client):
    r = client.post(THREE, json={"holdings": HOLDINGS, "pack_id": "semi_selloff",
                                 "rules": []})
    assert r.status_code == 422 and "최소 1개" in r.json()["detail"]


def test_a_leg_that_could_not_be_judged_gets_no_loss_figure(client):
    """★판정하지 못한 다리에 0% 손실을 적으면, 그 다리가 셋 중 가장 안전해 보인다★

    스냅샷을 붙이지 않으면 `timing_macro` 는 노출 0.0 의 **unavailable** 이다. 노출 0 인
    현금 포지션과 "알 수 없음" 은 다른 사실인데, 곱셈만 하면 둘이 -0.0% 로 같아진다.
    """
    body = client.post(THREE, json={"holdings": HOLDINGS, "pack_id": "semi_selloff",
                                    "market": "kr", "combination": "continuous",
                                    "rules": RULES}).json()
    macro = body["legs"]["timing_macro"]
    assert macro["state"] == "unavailable", "이 테스트는 매크로 미연결 상태를 전제한다"
    assert "shock_pct" not in macro, "판정하지 못한 다리에 손실이 적혔습니다"
    # 판정된 다리에는 정상적으로 실린다 — 전부 비우는 것으로 통과하면 안 된다.
    assert body["legs"]["timing_only"]["shock_pct"] is not None


def test_an_unavailable_scenario_composes_no_leg_losses(client, monkeypatch):
    """충격 자체를 못 구했으면 다리별 손실도 없다."""
    import src.api.allocation_routes as ar
    monkeypatch.setattr(ar, "allocation_stress", lambda req: {
        "error": False, "mode": "historical", "available": False,
        "scenario": req.scenario, "reason": "해당 기간 시세 데이터 미보유"})

    body = client.post(THREE, json={"holdings": HOLDINGS, "pack_id": "hist_2008_gfc",
                                    "market": "kr", "combination": "all",
                                    "rules": RULES}).json()
    assert body["scenario"]["shock_pct"] is None
    assert body["composed"] is False
    assert all("shock_pct" not in leg for leg in body["legs"].values())


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 입력 경계 — 스키마가 극단값을 입구에서 막는다
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("factors", [
    {"size": 1e308},          # 곱하면 inf → JSON 이 깨진다
    {"size": -1e308},
    {"size": 1000.0},         # 노출(±3σ)에 곱해 말이 안 되는 충격
])
def test_an_inline_pack_with_an_extreme_coefficient_is_refused(client, factors):
    """★계산 중간이 아니라 입구에서 거절한다★ 사유가 분명하고, inf 가 응답에 실리지 않는다."""
    r = client.post(RUN, json={"holdings": HOLDINGS,
                               "pack": {"market": -6.0, "factors": factors,
                                        "assumptions": {}}})
    assert r.status_code == 422, r.text


def test_an_inline_pack_with_an_extreme_assumption_is_refused(client):
    r = client.post(RUN, json={"holdings": HOLDINGS,
                               "pack": {"market": -6.0, "factors": {"size": -3.0},
                                        "assumptions": {"vol_rise": 1e9}}})
    assert r.status_code == 422, r.text


def test_a_reasonable_inline_pack_still_passes(client):
    """경계를 좁히다 정상 입력까지 막으면 안 된다 — 통과 경로를 함께 고정한다."""
    r = client.post(RUN, json={"holdings": HOLDINGS,
                               "pack": {"market": -6.0,
                                        "factors": {"size": -4.0, "leverage": -3.0},
                                        "assumptions": {"vol_rise": 0.4}}})
    assert r.status_code == 200, r.text


def test_every_number_in_a_run_response_is_json_finite(client):
    """★NaN/inf 는 유효한 JSON 이 아니다★ 엄격한 파서를 쓰는 소비자가 통째로 실패한다."""
    import json
    r = client.post(RUN, json={"holdings": HOLDINGS, "pack_id": "semi_selloff"})
    # `parse_constant` 는 NaN·Infinity 리터럴을 만나면 호출된다 — 만나면 실패시킨다.
    json.loads(r.text, parse_constant=lambda c: pytest.fail(f"응답에 {c} 가 들어 있습니다"))
