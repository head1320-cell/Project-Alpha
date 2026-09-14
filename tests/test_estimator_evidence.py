"""AH2 — 여섯 방언을 한 어휘로 (레지스트리 + 롤업).

★실측이 채점표를 뒤집었다★ — 채점표 §4 가 이름을 댄 일곱 계열(GARCH·DCC·
MarkovRegression·GaussianMixture·DynamicFactor·genpareto·LedoitWolf)중 **어느 것도
백테스트·배분 결정에 닿지 않는다**. 결정에 닿는 누출은 따로 있고, 여섯 중 넷이 이미
자기 누출을 **산문으로** 적어 뒀다:

  · `allocation_pipeline` → `path_source:"recomputed"` + `path_note`
  · `regime_axes`         → `revision_bias: REVISION_UNMANAGED` · `path_uses_vintage`
  · `backtest_run_routes` → `as_of_honored` + 긴 `reason`
  · `reverse_stress`      → ★선언 없음★

없는 것은 누출이 아니라 **어휘·판정·롤업**이었다. 여섯 방언이라 기계가 셀 수 없다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from src.domain.estimator_fit import (
    VINTAGE_AS_OF,
    VINTAGE_CURRENT,
    VINTAGE_UNMEASURED,
    WINDOW_BOUNDED,
    WINDOW_FULL_SAMPLE,
    WINDOW_TRAILING,
    WINDOW_UNMEASURED,
    EstimatorFit,
)
from src.engine.estimator_evidence import (
    ESTIMATOR_AXIS_LABELS,
    ESTIMATOR_REQUIRED_AXES,
    EXCLUDED_SITES,
    LEAKAGE_SITES,
    estimator_evidence,
)
from src.engine.run_evidence import (
    STATUS_PARTIAL,
    STATUS_UNKNOWN,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _fit(window, vintage, site="t", consumer="allocation") -> EstimatorFit:
    return EstimatorFit(site=site, window=window, vintage=vintage, consumer=consumer)


# ═══════════════════════════════════════════════════════════════════════════
# ① 롤업 — 잘린 창 + 그때 값이면 통과
# ═══════════════════════════════════════════════════════════════════════════

def test_a_fully_bounded_run_is_verified():
    out = estimator_evidence(
        covariance=_fit(WINDOW_BOUNDED, VINTAGE_AS_OF),
        regime_path=_fit(WINDOW_BOUNDED, VINTAGE_AS_OF))
    assert out["status"] == STATUS_VERIFIED
    assert out["broken_axes"] == [] and out["unknown_axes"] == []


def test_a_recomputed_regime_path_is_not_verified():
    """★짝★ L1 — `/analyze` 의 재계산 경로는 통과가 아니다(항상-통과 배제)."""
    out = estimator_evidence(
        covariance=_fit(WINDOW_BOUNDED, VINTAGE_AS_OF),
        regime_path=_fit(WINDOW_TRAILING, VINTAGE_CURRENT))
    assert out["status"] != STATUS_VERIFIED
    assert "regime_path" in out["broken_axes"]
    assert out["axes"]["regime_path"]["reason"]


def test_all_degraded_is_unverified():
    out = estimator_evidence(
        covariance=_fit(WINDOW_FULL_SAMPLE, VINTAGE_AS_OF),
        regime_path=_fit(WINDOW_TRAILING, VINTAGE_CURRENT))
    assert out["status"] == STATUS_UNVERIFIED


def test_nothing_measured_is_unknown_not_ok():
    out = estimator_evidence(
        covariance=_fit(WINDOW_UNMEASURED, VINTAGE_UNMEASURED),
        regime_path=None)
    assert out["status"] == STATUS_UNKNOWN
    assert "covariance" in out["unknown_axes"]


def test_unknown_and_broken_are_never_merged():
    out = estimator_evidence(
        covariance=_fit(WINDOW_BOUNDED, VINTAGE_AS_OF),
        regime_path=_fit(WINDOW_UNMEASURED, VINTAGE_UNMEASURED))
    assert out["status"] == STATUS_PARTIAL
    assert out["unknown_axes"] == ["regime_path"]
    assert out["broken_axes"] == []


# ═══════════════════════════════════════════════════════════════════════════
# ② 해당 없음 ≠ 미상 — `decision_evidence` 와 같은 규율
# ═══════════════════════════════════════════════════════════════════════════

def test_an_omitted_optional_axis_is_not_counted():
    """대리계열을 안 쓴 표면에 '대리계열 미상' 을 달면 **묻지 않은 것**을 적는 것이다."""
    out = estimator_evidence(covariance=_fit(WINDOW_BOUNDED, VINTAGE_AS_OF))
    assert "proxies" not in out["applicable"]
    assert out["status"] == STATUS_VERIFIED


def test_a_required_axis_never_vanishes():
    """★필수 축은 빠지면 '문제없음' 이 된다★ — 빠져도 `unknown` 으로 남는다."""
    out = estimator_evidence()
    for name in ESTIMATOR_REQUIRED_AXES:
        assert name in out["axes"]
        assert out["axes"][name]["reason"], f"{name} 에 사유가 없다"
    assert out["status"] == STATUS_UNKNOWN


def test_every_axis_has_a_label():
    """★`rollup` 이 `labels[n]` 을 하드 인덱싱한다 — 라벨이 없으면 KeyError★"""
    out = estimator_evidence(
        covariance=_fit(WINDOW_BOUNDED, VINTAGE_AS_OF),
        regime_path=_fit(WINDOW_BOUNDED, VINTAGE_AS_OF),
        proxies=_fit(WINDOW_BOUNDED, VINTAGE_AS_OF))
    for name in out["applicable"]:
        assert name in ESTIMATOR_AXIS_LABELS, f"{name} 에 사람이 읽는 이름이 없다"


# ═══════════════════════════════════════════════════════════════════════════
# ③ ★규칙을 복사하지 않는다★ — `run_evidence.rollup` 재사용
# ═══════════════════════════════════════════════════════════════════════════

def test_the_module_reuses_the_shared_rollup():
    """롤업 규칙이 두 곳에 있으면 화면에 따라 다른 판정이 나온다(그 사건이 있었다)."""
    src = (_ROOT / "src" / "engine" / "estimator_evidence.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = {n.module: {a.name for a in n.names}
                for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "rollup" in imported.get("src.engine.run_evidence", set()), (
        "공유 롤업을 쓰지 않는다 — 규칙을 복사하면 한쪽만 고쳐도 타입 에러가 안 난다")


def test_the_rollup_output_shape_matches_the_other_callers():
    out = estimator_evidence(covariance=_fit(WINDOW_BOUNDED, VINTAGE_AS_OF))
    for key in ("status", "axes", "applicable", "ok_axes",
                "broken_axes", "unknown_axes", "summary", "note"):
        assert key in out, f"`{key}` 가 없다 — 다른 호출자와 모양이 다르다"


# ═══════════════════════════════════════════════════════════════════════════
# ④ 레지스트리 — ★안 잰 것을 적는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_registry_is_not_empty():
    """★공허한 레지스트리는 증거가 아니다★ (AG 변이 `i` 의 교훈)"""
    assert LEAKAGE_SITES, "결정에 닿는 자리가 하나도 없다 — 전수 검사가 공허해진다"
    assert EXCLUDED_SITES, "제외 목록이 비었다 — 안 잰 것을 안 적었다"


@pytest.mark.parametrize("rec", LEAKAGE_SITES, ids=lambda r: r.site)
def test_every_registered_site_is_fully_declared(rec):
    assert rec.site and rec.window and rec.vintage and rec.consumer
    assert rec.window in ("bounded", "trailing", "full_sample", "unmeasured")
    assert rec.vintage in ("as_of", "current", "unmeasured")
    assert rec.consumer in ("allocation", "backtest")
    assert rec.note, f"{rec.site} 에 설명이 없다"


@pytest.mark.parametrize("rec", LEAKAGE_SITES, ids=lambda r: r.site)
def test_every_registered_site_really_exists(rec):
    """★목록이 낡아 없는 파일을 가리키면 전수 검사는 통과하지만 아무것도 안 지킨다★"""
    rel = rec.site.split(":")[0]
    assert (_ROOT / rel).exists(), f"{rel} 이 없다 — 레지스트리가 낡았다"


@pytest.mark.parametrize("rec", EXCLUDED_SITES, ids=lambda r: r["site"])
def test_every_excluded_site_carries_a_reason(rec):
    """★사유 없는 제외는 금지★ — 안 잰 것을 안 잤다고 적어야 축이 거짓말을 안 한다."""
    assert rec["reason"], f"{rec['site']} 를 사유 없이 제외했다"
    assert (_ROOT / rec["site"].split(":")[0]).exists(), f"{rec['site']} 가 없다"


def test_excluded_sites_are_not_also_registered():
    """★한 자리가 두 목록에 있으면 둘 중 하나가 거짓말이다★"""
    leaked = {r.site.split(":")[0] for r in LEAKAGE_SITES}
    excluded = {r["site"].split(":")[0] for r in EXCLUDED_SITES}
    assert not (leaked & excluded), f"두 목록에 겹치는 파일: {leaked & excluded}"


# ═══════════════════════════════════════════════════════════════════════════
# ⑤ ★백테스트 쪽 — 실측이 계획을 뒤집었다★
#
# 계획은 "엔진이 이 추정기들에 도달하지 않으니 백테스트 결과에는 안 붙인다" 였다.
# 그런데 재보니 엔진에는 **옵트인 누출 플래그**가 따로 있다:
# `allow_snapshot_fundamentals=True` 면 `score_factors.py:151,156` 이 **오늘의
# ROE/PER/PBR 를 과거 전 구간에 방송**한다. 그리고 ★그 실행의 결과는 깨끗한 실행과
# 완전히 구별되지 않았다★ — 최상위 키가 두 경우에 완전히 같았다(직접 돌려 확인).
#
# `thesis_backtest` 는 이 사실을 진단으로 이미 적고 있었다: *"스냅샷 상수 조건은
# 창 전체에서 값이 변하지 않아 항상 참이거나 항상 거짓이 됩니다 — 그것이
# look-ahead 의 관측 가능한 형태입니다"*. 엔진 결과만 그것을 몰랐다.
# ═══════════════════════════════════════════════════════════════════════════

def test_a_snapshot_fundamentals_run_is_not_verified():
    from src.engine.estimator_evidence import backtest_estimator_evidence
    out = backtest_estimator_evidence(snapshot_fundamentals=True)
    assert out["status"] != STATUS_VERIFIED
    assert "snapshot_fundamentals" in out["broken_axes"]
    axis = out["axes"]["snapshot_fundamentals"]
    assert axis["vintage"] == VINTAGE_CURRENT
    assert axis["window"] == WINDOW_FULL_SAMPLE
    assert "방송" in axis["reason"] or "전체표본" in axis["reason"]


def test_a_run_without_the_opt_in_is_measured_as_clean():
    """★짝★ 끄고 돈 실행은 **재봤더니 안 켰다**이지 미상이 아니다.

    처음에는 이 경우 축을 아예 빼려 했다(안 쓴 것을 `ok` 로 적으면 안 된다는
    생각). ★눈으로 돌려 보니 그 설계가 공허했다★ — 축이 하나도 없으니 깨끗한
    실행이 `unknown` 으로 굴러서 *"못 쟀다"* 로 읽혔다.

    이 축이 묻는 것은 *"이 실행이 오늘의 재무를 과거에 방송했나"* 이고, **아니오**
    는 관측된 답이다. 안 켰다는 것은 가정이 아니라 측정이다.
    """
    from src.engine.estimator_evidence import backtest_estimator_evidence
    out = backtest_estimator_evidence(snapshot_fundamentals=False)
    assert out["status"] == STATUS_VERIFIED
    assert "snapshot_fundamentals" in out["applicable"]
    assert out["broken_axes"] == [] and out["unknown_axes"] == []
    assert out["axes"]["snapshot_fundamentals"]["reason"] is None


def test_the_three_opt_in_answers_are_all_different():
    """★짝★ 켜짐/꺼짐/미상이 셋 다 구별된다 — 하나로 뭉개는 구현 배제."""
    from src.engine.estimator_evidence import backtest_estimator_evidence
    seen = {backtest_estimator_evidence(snapshot_fundamentals=v)["status"]
            for v in (True, False, None)}
    assert len(seen) == 3, f"세 답이 구별되지 않는다: {seen}"


def test_an_unmeasured_opt_in_is_unknown_not_clean():
    """★미상 ≠ 안 켰음★ — 플래그를 못 읽었으면 그렇게 말한다."""
    from src.engine.estimator_evidence import backtest_estimator_evidence
    out = backtest_estimator_evidence(snapshot_fundamentals=None)
    assert out["status"] == STATUS_UNKNOWN
    assert "snapshot_fundamentals" in out["unknown_axes"]


def test_the_two_surfaces_do_not_share_an_axis_set():
    """배분과 백테스트는 **다른 것을 추정한다** — 축이 같을 이유가 없다."""
    from src.engine.estimator_evidence import backtest_estimator_evidence
    alloc = estimator_evidence(covariance=_fit(WINDOW_BOUNDED, VINTAGE_AS_OF))
    bt = backtest_estimator_evidence(snapshot_fundamentals=True)
    assert set(alloc["applicable"]).isdisjoint(set(bt["applicable"]))
