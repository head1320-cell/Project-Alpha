"""M4 — 기본 배분 경로의 근거 관문(D1-b): 같은 경로 · k = 보유 기간의 워크포워드 브라이어로 GMM 시작 분포 × 전이 ↔ 전이 예측.

★받은 결정★(D1-b · CLAUDE.md §3 승인): GMM 시작 분포의 브라이어가 '오늘 국면 유지'와 '전이 예측'보다 ★엄격히 낮을 때만★ GMM,
아니면 전이 예측 + 사유. 오늘 국면 유지가 가장 낮아도 전이 예측이다(기본 경로의 두 후보는 GMM 과 전이 예측).
점수는 M2 의 `regime_skill` 그대로(같은 기억) — 관문은 점수를 다시 셈하지 않는다.
"""
from __future__ import annotations

import pytest

from src.engine import regime_gmm_start as gs
from src.engine import regime_skill as rs


def _skill(briers: dict[str, float | None], *, n_eval: int = 24, k: int = 1, fail: dict[str, str] | None = None) -> dict:
    """`regime_skill` 의 답 모양 — 후보 여섯 · 고정 순서 · 못 선 후보는 사유."""
    fail = fail or {}
    cands = []
    for key in rs.CANDIDATES:
        ok = key not in fail
        cands.append({"key": key, "name": rs.CANDIDATE_NAMES[key], "available": ok,
                      "brier": briers.get(key, 0.9) if ok else None, "reason": fail.get(key)})
    return {"available": True, "k": k, "n_eval": n_eval, "candidates": cands}


@pytest.fixture
def fake_skill(monkeypatch):
    seen: list = []

    def use(out: dict):
        def regime_skill(points, *, k=1, arms=None, **kw):
            seen.append((len(points), k, arms))
            return out
        monkeypatch.setattr(rs, "regime_skill", regime_skill)
        return seen
    return use


PTS = [{"t": f"2020-{m:02d}", "regime": "Goldilocks", "growth": 0.1, "inflation": -0.1} for m in range(1, 13)]


@pytest.mark.parametrize(("gmm", "persist", "trans", "chosen"), [
    (0.50, 0.60, 0.55, "gmm"),            # 둘보다 낮다 → GMM
    (0.55, 0.60, 0.55, "probabilistic"),  # 전이와 같다 → 낮지 않다(엄격)
    (0.58, 0.60, 0.55, "probabilistic"),  # 유지보다 낮고 전이보다 높다
    (0.65, 0.60, 0.70, "probabilistic"),  # 전이보다 낮고 유지보다 높다
    (0.60, 0.60, 0.70, "probabilistic"),  # 유지와 같다
])
def test_gmm_only_when_strictly_below_both(fake_skill, gmm, persist, trans, chosen):
    fake_skill(_skill({"gmm_start": gmm, "persistence": persist, "transition": trans}))
    out = gs.evidence_gate(PTS, 1)
    assert (out["available"], out["chosen"]) == (True, chosen)
    assert [c["key"] for c in out["compared"]] == ["gmm_start", "persistence", "transition"], "고정 순서"
    assert [c["brier"] for c in out["compared"]] == [gmm, persist, trans]
    assert out["n_compared"] == 3 and out["k"] == 1 and out["n_eval"] == 24
    assert out["reason"], "고른 쪽이 어느 것이든 까닭을 적는다"


def test_persistence_lowest_still_means_transition(fake_skill):
    """받은 결정 — 오늘 국면 유지가 가장 낮아도 기본 경로는 전이 예측이다. 해설이 그 사실을 숨기지 않는다."""
    fake_skill(_skill({"gmm_start": 0.50, "persistence": 0.40, "transition": 0.60}))
    out = gs.evidence_gate(PTS, 1)
    assert out["chosen"] == "probabilistic"
    assert "오늘 국면 유지" in out["reason"] and "전이 예측" in out["reason"]


def test_no_score_means_transition_with_the_skill_reason(fake_skill):
    fake_skill({"available": False, "k": 1, "reason": "평가 시점이 17개로 최소 20개에 못 미칩니다(경로 53개월 · 준비 구간 36개월 · 예측 1개월)."})
    out = gs.evidence_gate(PTS, 1)
    assert (out["available"], out["chosen"], out["compared"]) == (False, "probabilistic", [])
    assert "평가 시점이 17개" in out["reason"]


@pytest.mark.parametrize("missing", ["gmm_start", "persistence", "transition"])
def test_a_missing_candidate_means_transition_and_names_it(fake_skill, missing):
    fake_skill(_skill({"gmm_start": 0.4, "persistence": 0.6, "transition": 0.6},
                      fail={missing: "2021-03 시점에 세우지 못했습니다(시험)"}))
    out = gs.evidence_gate(PTS, 1)
    assert (out["available"], out["chosen"]) == (False, "probabilistic")
    assert rs.CANDIDATE_NAMES[missing] in out["reason"] and "시험" in out["reason"]


def test_the_gate_asks_m2_for_the_holding_period(fake_skill):
    seen = fake_skill(_skill({"gmm_start": 0.4, "persistence": 0.6, "transition": 0.6}, k=3))
    gs.evidence_gate(PTS, 3)
    assert seen == [(len(PTS), 3, None)], "k = 보유 기간 · 받은 경로 그대로(앞보기 0 은 부르는 쪽이 자른 경로를 넘겨 지킨다) · 팔은 M2 의 공유 기억"


def test_the_gate_passes_the_arms_through_and_asks_once(fake_skill):
    """가짜 팔을 넘기면 그대로 M2 에 간다(시험 · 백테스트가 같은 길을 쓴다) — 관문은 점수를 한 번만 묻는다."""
    seen = fake_skill(_skill({"gmm_start": 0.4, "persistence": 0.6, "transition": 0.6}))
    marker = object()
    gs.evidence_gate(PTS, 1, arms=marker)
    assert seen == [(len(PTS), 1, marker)]


N_GMM, N_PER, N_TR = (rs.CANDIDATE_NAMES[k] for k in ("gmm_start", "persistence", "transition"))
CHOSE_GMM = f"브라이어 점수에서 ‘{N_GMM}’가 ‘{N_PER}’와 ‘{N_TR}’보다 모두 낮아 ‘{N_GMM}’를 씁니다."
NOT_LOWEST = (f" 셋 가운데 가장 낮은 점수는 ‘{N_TR}’이 아닙니다 — 기본 경로는 ‘{N_GMM}’가 다른 둘보다 낮을 때만 그것을 쓰고 "
              f"그 밖에는 ‘{N_TR}’을 씁니다(‘{N_PER}’는 기본 경로의 후보가 아닙니다).")


def _not_below(*names: str) -> str:
    return f"브라이어 점수에서 ‘{N_GMM}’가 {'와 '.join(f'‘{n}’' for n in names)}보다 낮지 않아 ‘{N_TR}’을 씁니다."


@pytest.mark.parametrize(("briers", "expected"), [
    ((0.50, 0.60, 0.55), CHOSE_GMM),
    ((0.58, 0.60, 0.55), _not_below(N_TR)),                      # 전이 예측이 가장 낮다 — 덧붙일 말 없음
    ((0.55, 0.60, 0.55), _not_below(N_TR)),                      # 전이와 동률 — 쓴 쪽이 가장 낮은 쪽에 든다
    ((0.65, 0.60, 0.70), _not_below(N_PER) + NOT_LOWEST),        # 유지가 가장 낮다
    ((0.70, 0.60, 0.65), _not_below(N_PER, N_TR) + NOT_LOWEST),  # 둘 다 이기지 못했다
    ((0.40, 0.40, 0.60), _not_below(N_PER) + NOT_LOWEST),        # 유지와 동률로 가장 낮다 — 쓴 쪽(전이)은 가장 낮지 않다
])
def test_the_reason_names_what_was_not_beaten_and_says_when_the_used_one_is_not_lowest(fake_skill, briers, expected):
    fake_skill(_skill(dict(zip(("gmm_start", "persistence", "transition"), briers))))
    assert gs.evidence_gate(PTS, 1)["reason"] == expected


@pytest.mark.parametrize(("briers", "digits"), [
    ((0.5, 0.6, 0.55), 3),
    ((0.55, 0.6, 0.55), 3),                 # 같은 값은 같게 보이는 것이 맞다(동률)
    ((0.5121, 0.5124, 0.6), 4),             # 3자리에서 0.512 · 0.512 — 다른 값이 같게 보이면 늘린다
    ((0.512341, 0.512342, 0.6), 6),
])
def test_digits_grow_until_different_values_look_different(fake_skill, briers, digits):
    """보이는 글자(`shown`)는 서버가 그 자릿수로 한 번 짓는다 — 정확한 반(예 0.0625)을 파이썬(짝수 쪽)과 자바스크립트 toFixed(큰 쪽)가
    다르게 반올림하므로, 화면이 다시 서식을 입히면 해설과 표의 숫자가 갈릴 수 있다(화면은 이 글자를 그대로 보인다 — E2E 가 건다)."""
    fake_skill(_skill(dict(zip(("gmm_start", "persistence", "transition"), briers))))
    out = gs.evidence_gate(PTS, 1)
    assert out["digits"] == digits
    assert [c["shown"] for c in out["compared"]] == [f"{b:.{digits}f}" for b in briers], "보이는 글자는 그 자릿수로 한 번"


KEYS = {"available", "chosen", "chosen_name", "reason", "k", "n_eval", "n_compared", "compared", "digits", "note"}


def test_the_block_has_one_shape_and_the_caveat_only_when_it_compared(fake_skill):
    fake_skill(_skill({"gmm_start": 0.5, "persistence": 0.6, "transition": 0.55}))
    a = gs.evidence_gate(PTS, 1)
    fake_skill({"available": False, "k": 1, "reason": "평가 시점 부족(시험)"})
    b = gs.evidence_gate(PTS, 1)
    fake_skill(_skill({"gmm_start": 0.4, "persistence": 0.6, "transition": 0.6}, fail={"gmm_start": "적합 실패(시험)"}))
    c = gs.evidence_gate(PTS, 1)
    assert set(a) == set(b) == set(c) == KEYS
    assert (a["chosen_name"], b["chosen_name"], c["chosen_name"]) == (N_GMM, N_TR, N_TR)
    assert "낙관적" in a["note"] and "견준 후보 셋" in a["note"]
    assert (b["note"], c["note"], b["digits"], c["digits"]) == (None, None, None, None), "견주지 못했으면 낙관 줄도 자릿수도 없다"
    assert b["n_eval"] is None and c["n_eval"] == 24
    assert [x["available"] for x in c["compared"]] == [False, True, True] and c["compared"][0]["brier"] is None
    assert [x["shown"] for x in c["compared"]] == [None, None, None], "견주지 못했으면 보일 글자도 없다(표가 없다)"


def test_the_gate_reads_the_same_numbers_as_the_skill_table():
    """끝까지 한 번 — 실제 `regime_skill`(가짜 팔)의 점수표 값 = 관문이 견준 값 · 고른 쪽은 규칙대로."""
    from tests.test_regime_gmm_start import _fake_arms, _long_points
    pts = _long_points(60)
    arms = _fake_arms()
    skill = rs.regime_skill(pts, k=1, arms=arms)
    assert skill["available"], skill.get("reason")
    by = {c["key"]: c["brier"] for c in skill["candidates"]}
    out = gs.evidence_gate(pts, 1, arms=arms)
    assert out["available"] is True and out["n_eval"] == skill["n_eval"] == 24
    assert [c["brier"] for c in out["compared"]] == [by["gmm_start"], by["persistence"], by["transition"]]
    g, p, t = by["gmm_start"], by["persistence"], by["transition"]
    assert out["chosen"] == ("gmm" if g < p and g < t else "probabilistic")


def test_a_path_without_axes_is_a_reason_not_a_crash():
    """축 값 없이 굳혀진 경로(옛 스냅샷) — 점수를 낼 수 없다는 사유이지 예외가 아니다(M3 의 `gmm_start_path` 와 같은 검사)."""
    pts = [{"t": f"20{20 + m // 12}-{m % 12 + 1:02d}", "regime": "Goldilocks"} for m in range(60)]
    out = gs.evidence_gate(pts, 1)
    assert (out["available"], out["chosen"], out["compared"]) == (False, "probabilistic", [])
    assert "축 값이 없습니다" in out["reason"] and out["reason"].startswith(f"같은 경로의 워크포워드 점수를 낼 수 없어 ‘{N_TR}’을 씁니다.")


# ══ 2. 파이프라인 — 기본값 `evidence`(근거 관문) ═══════════════════════════════════════════

from types import SimpleNamespace  # noqa: E402

from tests.test_regime_gmm_start import (  # noqa: E402,F401
    _analyze,
    _fake_arms,
    _fresh_cache,
    client,
    stack,
    wired_route,
)
from tests.test_regime_weighting_golden import _jsonable  # noqa: E402
from tests.test_regime_weighting_golden import _path as _golden_path  # noqa: E402
from tests.test_regime_weighting_golden import _returns as _golden_returns  # noqa: E402

_GATE_KEYS = ("requested_weighting", "gate", "gmm_fallback")


def _without_gate(out: dict) -> dict:
    rest = {k: v for k, v in out.items() if k != "meta"}
    return _jsonable({**rest, "meta": {k: v for k, v in out["meta"].items() if k not in _GATE_KEYS}})


@pytest.mark.parametrize(("rebalance", "chosen"), [("M", "gmm"), ("Q", "probabilistic")])
def test_the_default_follows_the_gate_and_equals_the_chosen_stack(stack, rebalance, chosen):
    """골든 경로(가짜 팔)에서 관문은 한 달 보유면 GMM(0.795 < 1.5 · 0.830), 한 분기면 전이 예측(GMM 0.766 > 전이 0.764)을 고른다(잰 값).
    기본 요청의 스택 = 고른 방식을 명시한 스택 — 요청 표시 · 관문 블록만 다르다(관문은 새 셈을 하지 않는다)."""
    ev, path = stack("evidence", rebalance=rebalance)
    same, _ = stack(chosen, rebalance=rebalance)
    meta = ev["meta"]
    assert (meta["requested_weighting"], meta["regime_weighting"]) == ("evidence", chosen)
    assert meta["gate"]["available"] is True and meta["gate"]["chosen"] == chosen
    assert meta["gate"] == gs.evidence_gate(path, {"M": 1, "Q": 3}[rebalance]), "같은 경로 · k = 보유 기간"
    assert _without_gate(ev) == _without_gate(same)


def test_dev_data_length_means_transition_and_the_skill_reason(stack):
    """개발 자료와 같은 53개월 — 평가 시점 17개라 관문이 견주지 못한다 → 전이 예측 + 그 사유(하한을 낮춰 지어내지 않는다)."""
    ev, _ = stack("evidence", months=53)
    tr, _ = stack("probabilistic", months=53)
    gate = ev["meta"]["gate"]
    assert (gate["available"], gate["chosen"], gate["compared"]) == (False, "probabilistic", [])
    assert "평가 시점이 17개" in gate["reason"]
    assert ev["meta"]["regime_weighting"] == "probabilistic"
    assert "gmm_fallback" not in ev["meta"], "관문이 전이 예측을 골랐으면 GMM 을 세우려 하지 않았다 — 열화 칸이 없다"
    assert _without_gate(ev) == _without_gate(tr)


@pytest.mark.parametrize("weighting", ["hard", "probabilistic", "gmm"])
def test_explicit_weightings_carry_no_gate(stack, weighting):
    """짝 — 명시한 방식은 관문을 지나지 않는다(값은 M3 골든이 건다)."""
    out, _ = stack(weighting)
    assert "gate" not in out["meta"]
    assert out["meta"].get("requested_weighting") == ("gmm" if weighting == "gmm" else None)


def test_the_backtest_mode_stays_closed_and_computes_no_gate(monkeypatch):
    from src.api import allocation_pipeline as ap

    path = _golden_path()
    monkeypatch.setattr("src.data.regime_snapshots.get_snapshot", lambda sid: {"regime_path": [dict(p) for p in path]})
    called: list = []
    monkeypatch.setattr(gs, "evidence_gate", lambda *a, **k: called.append(a) or {})
    req = SimpleNamespace(mes_id="rgs_m4", regime_snapshot_id=None, regime_weighting="evidence", regime_mode="backtest",
                          rebalance="M", model="bl")
    out = ap._conditional_stack(req, _golden_returns(path))
    assert out["cond"]["available"] is False and called == [], "닫힌 모드에서는 관문을 계산하지 않는다"
    assert (out["meta"]["requested_weighting"], out["meta"]["gate"]) == ("evidence", None)


def test_the_default_is_the_gate_in_the_model_and_in_the_pipeline(monkeypatch, _fresh_cache):
    """모형의 기본값과 파이프라인의 기본값이 같다 — 한쪽만 바꾸면 부르는 길마다 달라진다."""
    from src.api import allocation_pipeline as ap
    from src.api.allocation_routes import AnalyzeRequest

    assert AnalyzeRequest.model_fields["regime_weighting"].default == "evidence"
    monkeypatch.setattr(rs, "default_arms", _fake_arms())
    path = _golden_path()
    monkeypatch.setattr("src.data.regime_snapshots.get_snapshot", lambda sid: {"regime_path": [dict(p) for p in path]})
    req = SimpleNamespace(mes_id="rgs_m4", regime_snapshot_id=None, regime_mode="live", rebalance="M", model="bl")
    out = ap._conditional_stack(req, _golden_returns(path))
    assert out["meta"]["requested_weighting"] == "evidence" and out["meta"]["gate"]["chosen"] == "gmm"


# ══ 3. 문 — `POST /api/v1/allocation/analyze` ══════════════════════════════════════════

def _analyze_default(client, tickers):
    return client.post("/api/v1/allocation/analyze", json={
        "tickers": tickers, "lookback_days": 500, "mc_paths": 100, "record_run": False,
        "conditional": True, "model": "bl", "mes_id": "rgs_m3"})


def test_the_route_default_is_the_gate_and_the_decision_moves_with_it(client, wired_route):
    """보내지 않으면 근거 관문(골든 경로 · 한 달 보유 → GMM) · 명시한 `evidence` 와 같다 · 짝: 명시한 `hard` 는 관문 없이 하드."""
    r = _analyze_default(client, wired_route)
    assert r.status_code == 200, r.text
    cond = r.json()["conditional"]
    assert (cond["requested_weighting"], cond["regime_weighting"], cond["gate"]["chosen"]) == ("evidence", "gmm", "gmm")
    assert cond["gmm_fallback"] is None, "관문이 GMM 을 고르면 그 길의 열화 칸이 있다(세웠으면 None)"
    explicit = _analyze(client, wired_route, "evidence").json()
    assert explicit["conditional"]["gate"] == cond["gate"]
    assert explicit["weights"]["optimized"] == r.json()["weights"]["optimized"]
    hard = _analyze(client, wired_route, "hard").json()
    assert "gate" not in hard["conditional"] and hard["conditional"]["regime_weighting"] == "hard"
    w, wh = r.json()["weights"]["optimized"], hard["weights"]["optimized"]
    assert sum(abs(w[t] - wh.get(t, 0.0)) for t in w) > 1e-6, "기본값이 바뀌면 결정이 움직인다(② 전달)"


@pytest.mark.parametrize("bad", ["Evidence", "gate", "auto", "evidence_gate"])
def test_the_route_rejects_near_names(client, wired_route, bad):
    assert _analyze(client, wired_route, bad).status_code == 422


# ══ 4. 캔버스 — 선택지 · 국면 가중 블록 · 해설 ══════════════════════════════════════════════

from src.api import allocation_graph_explain as gx  # noqa: E402
from src.api import allocation_graph_nodes as gn  # noqa: E402
from tests.test_regime_gmm_start import _canvas, _fake_boot, canvas_market  # noqa: E402,F401


def test_the_gate_is_the_first_option_and_the_default():
    """화면은 선택지 ★순서를 패턴에서★ 읽고(`schema.ts::optionsFromPattern`) 이름을 `x-ui.options` 에서 읽는다 — 근거 관문이 맨 앞 · 기본값."""
    prop = gn.EstimateParams.model_json_schema()["properties"]["regime_weighting"]
    assert prop["pattern"] == "^(evidence|hard|probabilistic|gmm)$"
    assert prop["x-ui"]["options"] == {"evidence": "근거 관문", "hard": N_PER, "probabilistic": N_TR, "gmm": N_GMM}
    assert prop["x-ui"]["options"]["evidence"] == gs.GATE_NAME == gx.WEIGHTING_PLAIN["evidence"]
    assert prop["default"] == "evidence"


def test_the_estimate_explain_states_the_gate_rule():
    ex = gx.explain_estimate({"settings": {"conditional": True, "regime_weighting": "evidence"}}, {}, None)
    said = " ".join(t["text"] for t in ex["trust"])
    assert "국면 가중 방식: 근거 관문" in ex["facts"]
    assert "지속된다고 가정" not in said
    assert "‘GMM 시작 분포 × 전이’가 ‘오늘 국면 유지’와 ‘전이 예측’보다 낮을 때만" in said and "아니면 ‘전이 예측’을" in said


@pytest.fixture
def gate_canvas(canvas_market, monkeypatch, _fresh_cache):
    """수익률 달과 맞춘 60개월 경로 + 가짜 군집 팔 · 가짜 다시 뽑기 — 관문이 점수를 낸다(한 달 보유 → GMM · 한 분기 → 전이 예측)."""
    monkeypatch.setattr(rs, "default_arms", _fake_arms())
    monkeypatch.setattr(gs, "bootstrap_agreement", _fake_boot())
    path = _golden_path(60, (2021, 8))
    monkeypatch.setattr("src.api.allocation_pipeline._regime_path_for", lambda req: {
        "points": [dict(p) for p in path], "path_source": "regime_snapshot", "path_note": None, "reason": None})
    return lambda **est: _canvas("evidence", **est)["nodes"]["o"]


def _gate_fact(gate: dict) -> str:
    nums = " · ".join(f"{c['name']} {c['shown']}" for c in gate["compared"])
    return f"근거 관문: 브라이어 점수 {nums}(평가 시점 {gate['n_eval']}개 · {gate['k']}개월 앞). {gate['reason']}"


@pytest.mark.parametrize(("rebalance", "used"), [("M", "gmm"), ("Q", "probabilistic")])
def test_the_canvas_block_carries_the_gate_and_the_explain_says_it(gate_canvas, rebalance, used):
    o = gate_canvas(rebalance=rebalance)
    reg = o["view"]["belief"]["regime"]
    gate = reg["gate"]
    assert (reg["requested"], reg["requested_name"], reg["used"], gate["chosen"]) == ("evidence", "근거 관문", used, used)
    assert [c["key"] for c in gate["compared"]] == list(gs.GATE_CANDIDATES) and gate["available"] is True
    facts = o["explain"]["facts"]
    assert _gate_fact(gate) in facts
    assert f"국면 가중 방식: {gx.WEIGHTING_PLAIN[used]}(요청: 근거 관문)" in facts
    trust = [t["text"] for t in o["explain"]["trust"]]
    assert gs.GATE_NOTE in trust, "고른 쪽의 점수는 낙관적이다(견준 후보 셋)"
    assert reg["fallbacks"] == [], "관문이 고른 것은 열화가 아니다 — 열화 걸음 없음"


def test_dev_data_default_canvas_says_the_gate_could_not_compare(canvas_market):
    o = _canvas("evidence")["nodes"]["o"]
    reg = o["view"]["belief"]["regime"]
    assert (reg["requested"], reg["used"], reg["gate"]["available"]) == ("evidence", "probabilistic", False)
    trust = [t["text"] for t in o["explain"]["trust"]]
    assert reg["gate"]["reason"] in trust and "평가 시점이 17개" in reg["gate"]["reason"]
    assert gs.GATE_NOTE not in trust, "짝 — 견주지 못했으면 낙관 줄이 없다"
    assert not any(f.startswith("근거 관문:") for f in o["explain"]["facts"]), "견주지 못했으면 점수 사실 줄이 없다"
    assert reg["fallbacks"] == []


@pytest.mark.parametrize("w", ["hard", "probabilistic", "gmm"])
def test_explicit_weightings_have_no_gate_in_the_block(canvas_market, w):
    reg = _canvas(w)["nodes"]["o"]["view"]["belief"]["regime"]
    assert reg["gate"] is None


@pytest.mark.parametrize("w", ["hard", "probabilistic", "evidence"])
def test_only_a_gmm_run_carries_stability_and_robustness(canvas_market, w):
    """M3 화면 변이 f15 의 동치 근거를 계약으로 — GMM 을 쓰지 않은 블록에는 시드 안정성 · 다시 뽑기가 없다(화면의 GMM 조건은 방어)."""
    reg = _canvas(w)["nodes"]["o"]["view"]["belief"]["regime"]
    assert reg["used"] != "gmm"
    assert (reg["stability"], reg["robustness"]) == (None, None)


# ══ 5. 백테스트 팔 E — 재조정 달마다 그 달까지 자른 경로의 관문 ═══════════════════════════════

from src.engine.allocation_backtest import walk_forward  # noqa: E402
from tests.test_regime_weighting_golden import arm_panel  # noqa: E402


@pytest.fixture
def arm_walk(monkeypatch, _fresh_cache):
    """84개월 패널 · 가짜 군집 팔 → 이름으로 부른 팔의 워크포워드(하네스의 팔은 늘 이름으로 부른다)."""
    monkeypatch.setattr(rs, "default_arms", _fake_arms())

    def run(weighting: str = "evidence", points=None, *, rebalance="M", **regime):
        path, df = arm_panel()
        pts = [dict(p) for p in (points if points is not None else path)]
        out = walk_forward(list(df.columns), df.to_numpy(), list(df.index), model="bl", rebalance=rebalance,
                           cost_bps=10.0, regime={"points": pts, "weighting": weighting, **regime})
        assert not out.get("error"), out.get("message")
        return out
    return run


def test_the_e_arm_runs_the_gate_every_month_on_the_truncated_path(arm_walk, monkeypatch):
    seen: list[tuple] = []
    real = gs.evidence_gate

    def spy(points, h_hold, **kw):
        out = real(points, h_hold, **kw)
        seen.append((len(points), str(points[-1]["t"])[:7], h_hold, out["chosen"]))
        return out
    monkeypatch.setattr(gs, "evidence_gate", spy)
    aud = arm_walk()["regime_audit"]
    assert aud["arm"] == "E"
    rows = [d for d in aud["detail"] if d["path_len"] >= 2]
    assert [d["path_len"] for d in rows] == [n for n, *_ in seen], "그 달까지 자른 경로로만(앞보기 0)"
    assert [d["last_path_month"] for d in rows] == [t for _, t, *_ in seen]
    assert all(h == 1 for *_, h, _ in seen), "k = 보유 기간(한 달)"
    assert [d["gate"]["chosen"] for d in rows] == [c for *_, c in seen]
    chose = {d["gate"]["chosen"] for d in rows}
    assert chose == {"gmm", "probabilistic"}, "앞쪽(점수 없음)은 전이 예측 · 뒤쪽은 GMM — 둘 다 있어야 공허하지 않다"
    assert (aud["gate_gmm_months"], aud["gate_transition_months"]) == (
        sum(d["gate"]["chosen"] == "gmm" for d in rows), sum(d["gate"]["chosen"] == "probabilistic" for d in rows))
    assert aud["gmm_months"] == sum(d["gmm"] is not None for d in rows) == aud["gate_gmm_months"], \
        "관문이 GMM 을 고른 달마다 세웠다(이 패널에서는 열화 없음) — G 팔과 같은 칸"


def test_the_e_arm_equals_the_chosen_arm_month_by_month(arm_walk):
    """관문이 GMM 을 고른 달 = 팔 G 의 그 달 · 전이 예측을 고른 달 = 팔 N 의 그 달(새 셈 0줄)."""
    e = arm_walk()
    g, n = arm_walk("gmm"), arm_walk("probabilistic")
    ew = {r["date"][:7]: r["weights"] for r in e["rebalances"]}
    gw = {r["date"][:7]: r["weights"] for r in g["rebalances"]}
    nw = {r["date"][:7]: r["weights"] for r in n["rebalances"]}
    for d in e["regime_audit"]["detail"]:
        if d["path_len"] < 2:
            continue
        want = gw if d["gate"]["chosen"] == "gmm" else nw
        assert ew[d["month"]] == want[d["month"]], d["month"]


def test_later_months_do_not_move_earlier_gate_choices(arm_walk):
    """★앞보기 0★ 마지막 12달의 축을 뒤집어도 그 전에 내린 관문의 선택 · 견준 점수는 그대로다."""
    path, _ = arm_panel()
    altered = [dict(p) for p in path]
    for p in altered[-12:]:
        p["growth"], p["inflation"] = -float(p["growth"]), -float(p["inflation"])
    cut = str(altered[-12]["t"])[:7]
    base = {d["month"]: d["gate"] for d in arm_walk()["regime_audit"]["detail"] if d["path_len"] >= 2}
    alt = {d["month"]: d["gate"] for d in arm_walk("evidence", altered)["regime_audit"]["detail"] if d["path_len"] >= 2}
    early = [m for m in base if m < cut]
    assert early and all(base[m] == alt[m] for m in early)
    assert any(base[m] != alt[m] for m in base if m >= cut), "짝 — 뒤집은 달 뒤의 선택은 실제로 달라진다(공허한 시험이 아니다)"


@pytest.mark.parametrize("weighting", ["hard", "probabilistic", "gmm"])
def test_other_arms_carry_no_gate(arm_walk, weighting):
    """짝 — B1 · N · G 의 감사 줄과 요약에는 관문이 없다(골든 그대로)."""
    aud = arm_walk(weighting)["regime_audit"]
    assert all("gate" not in d for d in aud["detail"])
    assert "gate_gmm_months" not in aud and "gate_transition_months" not in aud


# ══ 6. 화면 고정물 — E2E 의 '관문이 고른 최적화 결과' = 지금 서버의 출력 ══════════════════════

import json  # noqa: E402
import os  # noqa: E402
import pathlib  # noqa: E402

M4_FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "e2e" / "fixtures" / "regime-evidence-optimizer.json"


def test_the_screen_fixture_is_what_the_optimizer_produces(gate_canvas):
    """★손으로 지은 응답이 아니다★ 수익률 달과 맞춘 60개월 경로 · 가짜 군집 팔 · 가짜 다시 뽑기로 서버의 최적화 노드를 돌린 출력의
    국면 가중 블록과 해설 — 한 달 보유(관문 → GMM) · 한 분기 보유(관문 → 전이 예측). 다시 짓기: `REGEN_SCREEN_FIXTURES=1`."""
    from tests.test_regime_skill_routes import _close

    got = {}
    for key, rebalance in (("monthly", "M"), ("quarterly", "Q")):
        o = gate_canvas(rebalance=rebalance)
        ex = o["explain"]
        got[key] = json.loads(json.dumps({"belief": o["view"]["belief"],
                                          "explain": {k: ex[k] for k in ("title", "facts", "trust", "unmeasured")}},
                                         ensure_ascii=False))
    assert got["monthly"]["belief"]["regime"]["gate"]["chosen"] == "gmm"
    assert got["quarterly"]["belief"]["regime"]["gate"]["chosen"] == "probabilistic"
    if os.environ.get("REGEN_SCREEN_FIXTURES") == "1":
        M4_FIXTURE.write_text(json.dumps(got, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    assert M4_FIXTURE.exists(), f"고정물이 없습니다 — REGEN_SCREEN_FIXTURES=1 로 짓습니다: {M4_FIXTURE}"
    _close(got, json.loads(M4_FIXTURE.read_text(encoding="utf-8")))
