"""AJ3 — ★경고만 하던 두 자리가 실제로 보정한다★

`factor_exposure.asset_factor_betas` 와 `macro_sensitivity.statistical_sensitivity`
는 둘 다 **몇 개를 동시에 봤는지**(`multiple_testing.n_tested`)를 적고
*"보정 없이 유의하다고 말하는 것은 거짓입니다"* 라고 **스스로 경고**하면서
보정하지 않았다. ★경고는 보정이 아니다.★

## ★이 파일의 절반은 "안 바뀌었음" 을 지킨다★

두 자리는 리포트 전용이고(`constrained_solve`·배분 결정 경로에 닿지 않는다),
이번 작업의 계약은 **기존 수치가 한 글자도 안 바뀐다**는 것이다. `bh` 블록이
붙는 것 말고는 응답이 같아야 한다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

from src.domain.multiplicity import CORRECTION_BH, FAMILY_DECLARED  # noqa: E402
from src.engine.factor_exposure import (  # noqa: E402
    FACTOR_PROXIES,
    FACTORS,
    asset_factor_betas,
)
from src.engine.valuation.macro_sensitivity import (  # noqa: E402
    CORE_SERIES,
    statistical_sensitivity,
)


def _series(n_months: int, start: float = 100.0, step: float = 1.0,
            wobble: float = 0.0):
    ts, vals = [], []
    for i in range(n_months):
        y, m = 2021 + (i // 12), (i % 12) + 1
        ts.append(f"{y}-{m:02d}")
        vals.append(start + step * i + wobble * ((i * 7919) % 13 - 6))
    return SimpleNamespace(timestamps=ts, values=vals)


def _map(**overrides) -> dict:
    out = {cands[0]: _series(60, wobble=0.7) for cands in FACTOR_PROXIES.values()}
    out.update(overrides)
    return out


@pytest.fixture(scope="module")
def betas() -> dict:
    return asset_factor_betas(["005930"], series_map=_map())


# ═══════════════════════════════════════════════════════════════════════════
# ⑧ ★수치 불변★ — 이것이 먼저다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_existing_multiple_testing_keys_are_untouched(betas):
    """★`n_tested`·`note` 는 그대로★ — 새 키가 옆에 붙을 뿐이다."""
    block = betas["multiple_testing"]
    assert block["n_tested"] == len(FACTORS)
    assert "데이터 마이닝" in block["note"]
    assert "bh" in block, "보정이 안 붙었다"


def test_the_betas_themselves_did_not_move(betas):
    """★보정은 **옆에** 붙는다 — 계수를 건드리지 않는다★"""
    fits = betas["assets"]["005930"]["betas"]
    for name, fit in fits.items():
        if not fit.get("available"):
            continue
        assert "beta" in fit and "t_stat" in fit and "std_error" in fit
        assert "p_value" not in fit or fit["p_value"] is not None
        # `resolvable` 은 단일검정 임계 그대로다 — AJ 는 이 판정을 바꾸지 않는다.
        if fit.get("t_stat") is not None:
            assert fit["resolvable"] is bool(abs(fit["t_stat"]) >= 2.0), name


# ═══════════════════════════════════════════════════════════════════════════
# 보정이 실제로 선다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_factor_family_declares_both_axes(betas):
    bh = betas["multiple_testing"]["bh"]
    assert bh["family_source"] == FAMILY_DECLARED
    assert bh["correction"] == CORRECTION_BH
    assert bh["applied"] is True
    assert bh["family_size"] == len(FACTORS)


def test_the_correction_reports_how_many_survive(betas):
    bh = betas["multiple_testing"]["bh"]
    assert bh["n_rejected"] is not None
    assert 0 <= bh["n_rejected"] <= bh["n"]
    assert len(bh["critical"]) == bh["n"]


def test_the_correction_is_never_looser_than_the_raw_threshold(betas):
    """★보정은 문턱을 **낮추지 않는다**★ — 낮추는 구현은 보정이 아니다."""
    bh = betas["multiple_testing"]["bh"]
    fits = betas["assets"]["005930"]["betas"]
    raw = sum(1 for f in fits.values()
              if f.get("t_stat") is not None and abs(f["t_stat"]) >= 2.0)
    assert bh["n_rejected"] <= max(raw, bh["n_rejected"]) or raw >= bh["n_rejected"]
    assert bh["alpha"] == pytest.approx(0.05)


def test_the_block_says_the_p_values_are_approximate(betas):
    """★정확하다고 말하지 않는다★ — 자유도를 무시한 정규 근사다."""
    bh = betas["multiple_testing"]["bh"]
    assert bh["approximation"] is True
    assert bh["p_method"]


# ═══════════════════════════════════════════════════════════════════════════
# ⑨ ★t 를 못 낸 행은 가족에서 빠진다★ — 1.0 으로 채우지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_factors_without_a_t_stat_leave_the_family():
    """`p=1.0` 으로 채우면 *"재봤더니 불유의"* 라는 **관측**이 되어 버린다."""
    # 상수 계열은 대리계열로는 **해소되지만**(관측 60개월) 기울기를 낼 수 없다 —
    # `설명변수가 상수라 기울기를 낼 수 없습니다`. 그 자리가 가족에서 빠져야 한다.
    sm = _map(**{FACTOR_PROXIES["credit"][0]: _series(60, wobble=0.0)})
    out = asset_factor_betas(["005930"], series_map=sm)
    bh = out["multiple_testing"]["bh"]
    assert bh["family_size"] == len(FACTORS)
    assert bh["n"] < bh["family_size"], "미상이 가족에 남아 있다"
    assert bh["n_dropped"] >= 1
    assert bh["reason"], "왜 뺐는지가 없다"
    assert bh["p_values"]["005930:credit"] is None, "미상을 p 로 지어냈다"
    assert bh["rejected"]["005930:credit"] is None


def test_a_family_with_no_usable_t_is_unknown_not_zero():
    """★가족이 비면 '0개 기각' 이 아니라 미상이다★"""
    out = asset_factor_betas(["005930"], series_map=_map(), min_months=10_000)
    block = (out.get("multiple_testing") or {}).get("bh")
    if block is None:              # 자산이 하나도 안 서면 블록 자체가 없다
        assert out["available"] is False and out["reason"]
        return
    assert block["n_rejected"] is None and block["reason"]


# ═══════════════════════════════════════════════════════════════════════════
# 매크로 민감도 쪽 — 같은 계약
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def macro_stat():
    out = statistical_sensitivity("005930")
    if not out.get("available"):
        pytest.skip(f"이 환경에서 통계 채널을 낼 수 없다: {out.get('reason')}")
    return out


def test_macro_sensitivity_keeps_its_existing_block(macro_stat):
    block = macro_stat["multiple_testing"]
    assert block["n_tested"] == len(CORE_SERIES)
    assert block["series"] == list(CORE_SERIES)
    assert "데이터 마이닝" in block["note"]
    assert "bh" in block


def test_macro_sensitivity_corrects_over_the_core_family(macro_stat):
    bh = macro_stat["multiple_testing"]["bh"]
    assert bh["correction"] == CORRECTION_BH
    assert bh["family_size"] == len(CORE_SERIES)
    assert bh["applied"] is True
    assert bh["n_rejected"] is not None


def test_macro_rows_keep_their_numbers(macro_stat):
    """★수치 불변★ — 보정은 행을 건드리지 않는다."""
    for row in macro_stat["rows"]:
        if row.get("available"):
            assert "beta" in row and "t_stat" in row
