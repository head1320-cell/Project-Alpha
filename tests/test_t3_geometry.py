"""Phase 3 기하 실험 계약 — ★Ω 매칭이 **Ω 만** 바꿨는지★
==============================================================================
계획: 매크로 → 포트폴리오 정보 계약 패스 Phase 3.

## 이 파일이 막는 것

`R-omega-matched` 팔은 "기하는 R, 신뢰도는 A" 를 주장한다. 그 주장이 거짓이면
분해(`전체 = 기하 + Ω축소`)가 **아무 의미도 없는 두 숫자의 합**이 된다.
그런데 그 거짓은 결과 표를 봐서는 보이지 않는다 — 세 팔 모두 그럴듯한 수치를 낸다.

그래서 세 가지를 못 박는다:

1. `R` 과 `R-omega-matched` 의 **P·Q 가 원소별 동일**하고 **Ω 만 다르다**.
2. `R-omega-matched` 의 Ω 가 **A 의 Ω 와 정확히 같다**.
3. 분해가 **항등식**이다 — `전체 = 기하 + Ω축소` 가 부동소수점 오차 내에서 성립.

★그리고 짝★ Ω 매칭이 결과를 **실제로 바꾸는지**도 본다. 안 바뀌면 개입이 없었던
것이고, 그러면 "기하 몫" 이 언제나 100% 로 나와 결론이 뒤집힌다.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import sys

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.allocation_studio import TAU_DEFAULT  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # ★dataclass 가 sys.modules 를 본다★
    spec.loader.exec_module(mod)
    return mod


t3 = _load("t3_transmission", "scripts/t3_transmission.py")
geo = _load("t3_geometry", "scripts/t3_geometry.py")


@pytest.fixture(scope="module")
def panel():
    names, R, dates, points, beta = t3.build_panel(months=36)
    win = R[:504]
    return {"names": names, "R": R, "dates": dates, "points": points, "beta": beta,
            "sigma": np.cov(win.T) * 252.0, "mu": win.mean(axis=0) * 252.0}


def _pq(arm, panel, conf=25.0):
    v = geo.geometry_views(arm, panel["mu"], panel["names"], panel["beta"])
    return t3.pq_from_views(v, panel["names"], panel["sigma"], conf, TAU_DEFAULT)


# ══════════════════════════════════════════════════════════════════════════
# 1) 정보 표현 — 기하가 실제로 다르다
# ══════════════════════════════════════════════════════════════════════════
def test_level_arm_row_sums_to_one_and_relative_arm_to_zero(panel):
    Pa, _Qa, _Oa, _ = _pq("A-level", panel)
    Pr, _Qr, _Or, _ = _pq("R-relative", panel)
    assert Pa[0].sum() == pytest.approx(1.0, abs=1e-9)
    assert Pr[0].sum() == pytest.approx(0.0, abs=1e-9)
    # ★같은 L1 노름★ — 노름까지 다르면 "기하만 다르다" 가 아니다
    assert np.abs(Pa[0]).sum() == pytest.approx(np.abs(Pr[0]).sum(), abs=1e-9)


def test_matched_arm_uses_the_relative_geometry(panel):
    """`R-omega-matched` 의 **행**은 R 의 것이어야 한다(A 의 것이 아니라)."""
    Pr, Qr, _Or, _ = _pq("R-relative", panel)
    Pm, Qm, _Om, _ = _pq("R-omega-matched", panel)
    np.testing.assert_allclose(Pm, Pr, atol=0, rtol=0)
    np.testing.assert_allclose(Qm, Qr, atol=0, rtol=0)


# ══════════════════════════════════════════════════════════════════════════
# 2) ★Ω 매칭이 Ω 만 바꾼다★ — 그리고 실제로 바꾼다
# ══════════════════════════════════════════════════════════════════════════
def test_omega_matching_replaces_omega_with_the_level_arms_omega(panel):
    """walk-forward 안에서 실제로 A 의 Ω 가 들어갔는지 — 기록으로 확인한다."""
    rec_a, _ = geo.run_arm("A-level", panel["names"], panel["R"], panel["dates"],
                           panel["points"], panel["beta"], conf=25.0)
    rec_m, _ = geo.run_arm("R-omega-matched", panel["names"], panel["R"],
                           panel["dates"], panel["points"], panel["beta"], conf=25.0)
    assert rec_a["omega"] and len(rec_a["omega"]) == len(rec_m["omega"])
    np.testing.assert_allclose(rec_m["omega"], rec_a["omega"], rtol=1e-12)


def test_omega_matching_actually_changes_something(panel):
    """★짝★ 개입이 없으면 '기하 몫' 이 언제나 100% 로 나와 결론이 뒤집힌다.

    R 의 자기 Ω 와 A 의 Ω 가 **다르다**는 것이 이 실험의 전제다 — 같다면 분해할
    것이 없다.
    """
    rec_r, _ = geo.run_arm("R-relative", panel["names"], panel["R"], panel["dates"],
                           panel["points"], panel["beta"], conf=25.0)
    rec_m, _ = geo.run_arm("R-omega-matched", panel["names"], panel["R"],
                           panel["dates"], panel["points"], panel["beta"], conf=25.0)
    ratio = float(np.mean(rec_m["omega"]) / np.mean(rec_r["omega"]))
    assert ratio > 1.5, (
        f"스프레드 행의 Ω 가 수준 행과 거의 같다 (비 {ratio:.3f}) — 분해가 공허하다")
    # 그리고 비중 경로가 실제로 갈라져야 한다
    l1 = float(np.mean([np.abs(a - b).sum() for a, b in
                        zip(rec_r["w"], rec_m["w"], strict=True)
                        if a is not None and b is not None]))
    assert l1 > 1e-6, "Ω 를 바꿨는데 비중이 그대로다"


def test_relative_row_has_lower_variance_than_the_level_row(panel):
    """★구조적 사실★ Ω 축소의 **원인**을 직접 확인한다 — `Ω = diag(P τΣ Pᵀ)·scale`.

    스프레드 포트폴리오는 공통인자가 상쇄되어 분산이 작다. 그래서 같은 규약 아래
    상대 뷰는 **자동으로 더 확신하는 뷰**가 된다 — 형태를 고른 결과이지 그 형태가
    경제적으로 옳다는 증거가 아니다.
    """
    S = panel["sigma"]
    ra = t3._factor_row_level(panel["beta"])
    rr = t3._factor_row_relative(panel["beta"])
    va, vr = float(ra @ S @ ra), float(rr @ S @ rr)
    assert vr < va, f"스프레드 행의 분산이 더 크다: {vr:.3e} vs {va:.3e}"


# ══════════════════════════════════════════════════════════════════════════
# 3) 분해가 항등식인가
# ══════════════════════════════════════════════════════════════════════════
def test_decomposition_is_an_identity(panel):
    """`전체 = 기하 + Ω축소` — 세 팔의 CE 로 정의된 항등식이 성립해야 한다."""
    ce = {}
    for arm in geo.ARMS:
        rec, rb = geo.run_arm(arm, panel["names"], panel["R"], panel["dates"],
                              panel["points"], panel["beta"], conf=25.0)
        d, curve, tos, rbm = t3.simulate(rec, rb, panel["R"], panel["dates"], 0.0)
        by_month = {p["t"]: p["regime"] for p in panel["points"]}
        ce[arm] = t3.metrics(d, curve, tos, rbm, by_month)["ce"]
    total = ce["R-relative"] - ce["A-level"]
    geom = ce["R-omega-matched"] - ce["A-level"]
    omega = ce["R-relative"] - ce["R-omega-matched"]
    assert total == pytest.approx(geom + omega, abs=1e-9)


# ══════════════════════════════════════════════════════════════════════════
# 4) 통제 — 기하 말고는 아무것도 다르지 않다
# ══════════════════════════════════════════════════════════════════════════
def test_all_arms_apply_the_same_number_of_rebalances(panel):
    counts = set()
    for arm in geo.ARMS:
        rec, rb = geo.run_arm(arm, panel["names"], panel["R"], panel["dates"],
                              panel["points"], panel["beta"], conf=25.0)
        counts.add((rec["applied"], len(rb)))
        assert len(rec["w"]) == len(rb)
        assert rec["evidence_grade"] == t3.EVIDENCE_SYNTHETIC
    assert len(counts) == 1, f"팔마다 리밸런싱 수가 다르다: {counts}"


def test_every_arm_uses_exactly_one_view(panel):
    """★뷰 개수를 1로 고정★ 직전 연구의 A 는 뷰가 6개라 기하와 개수가 뭉쳐 있었다."""
    for arm in geo.ARMS:
        P, Q, _Om, _sk = _pq(arm, panel)
        assert P.shape[0] == 1 and len(Q) == 1
