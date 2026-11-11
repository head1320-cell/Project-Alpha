"""요한센 판정은 ★프로세스의 경고 필터 상태에 기대지 않는다★ (2026-11-11)

## 무엇이 있었나 (재현)
캔버스 `long_run` 노드가 오래 돈 E2E 서버에서만 "요한센 검정이 실패했습니다: Casting complex values to real discards the imaginary part"
로 실패했다. 새로 띄운 서버에서는 같은 요청이 `ok` 였다.

- statsmodels `coint_johansen` 은 고유값을 복소 dtype 으로 받아(이 입력에서는 허수부가 정확히 0) trace 통계량에 넣으며 `ComplexWarning` 을 낸다
  (`vecm.py` 717–718행). 기본 경고 설정에서는 경고만 나고 계산은 끝난다.
- scikit-learn 의 입력 검사 등은 `warnings.catch_warnings()` 안에서 `ComplexWarning` 을 잠깐 'error' 로 바꾼다. `catch_warnings` 는 스레드 안전하지
  않아(Python 3.14 · `sys.flags.context_aware_warnings == 0`) 두 스레드가 엇갈려 드나들면 'error' 필터가 ★프로세스 전역에 남는다★ — 그 뒤로는
  같은 입력이 예외로 끝났다. 두 스레드의 엇갈림으로 필터가 남는 것과, 그 상태에서 이 입력이 실패하는 것을 각각 재현했다.

그래서 판정은 경고 필터와 무관해야 하고, 대신 ★버린 허수부를 직접 잰다★ — 0 이 아니면 실수부만 취해 판정하지 않는다(짝).
"""
from __future__ import annotations

import json
import pathlib
import warnings
from types import SimpleNamespace

import numpy as np
import pytest

from src.engine import cointegration as ci

CASE = json.loads((pathlib.Path(__file__).parent / "golden" / "johansen_complex_dtype_case.json").read_text())["series"]


def _default_state() -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("default")
        return ci.analyze_long_run(CASE)


def test_the_case_really_emits_the_complex_warning():
    """★공허하지 않게★ 이 입력이 정말 ComplexWarning 을 내는지(안 내면 아래 시험은 아무것도 재지 않는다)."""
    from statsmodels.tsa.vector_ar.vecm import coint_johansen
    names = sorted(CASE)
    y = np.column_stack([np.asarray(CASE[k], float) for k in names])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        jo = coint_johansen(y, 0, 1)
    assert any(issubclass(w.category, np.exceptions.ComplexWarning) for w in caught)
    assert np.iscomplexobj(jo.eig) and float(np.max(np.abs(np.imag(jo.eig)))) == 0.0


def test_a_leaked_error_filter_does_not_change_the_verdict():
    """전역에 'error/ComplexWarning' 이 남아 있어도(다른 스레드가 남긴 상태) 같은 판정."""
    base = _default_state()
    assert base["available"] is True, base.get("reason")
    with warnings.catch_warnings():
        warnings.simplefilter("error", np.exceptions.ComplexWarning)
        leaked = ci.analyze_long_run(CASE)
    assert leaked["available"] is True, leaked.get("reason")
    assert leaked["coint_rank"] == base["coint_rank"]
    assert leaked["evidence"]["trace_stat"] == base["evidence"]["trace_stat"]


def test_the_local_guard_does_not_leak_into_the_process():
    """판정이 끝난 뒤 프로세스 경고 필터는 들어오기 전 그대로다(이 자리가 새 누수를 만들지 않는다)."""
    before = list(warnings.filters)
    ci.analyze_long_run(CASE)
    assert list(warnings.filters) == before


def test_a_real_imaginary_part_is_refused_with_a_reason(monkeypatch):
    """★짝★ 허수부가 실제로 있으면 실수부만 취해 판정하지 않는다 — 사유와 함께 거절(숫자를 지어내지 않는다)."""
    import statsmodels.tsa.vector_ar.vecm as vecm
    real = vecm.coint_johansen

    def fake(y, det_order, k_ar_diff):
        jo = real(y, det_order, k_ar_diff)          # 결과의 eig 는 읽기 전용 — 같은 모양의 값으로 바꿔 끼운다
        return SimpleNamespace(lr1=jo.lr1, cvt=jo.cvt,
                               eig=np.asarray(jo.eig, dtype=complex) + np.array([1e-3j] + [0j] * (len(jo.eig) - 1)))
    monkeypatch.setattr(vecm, "coint_johansen", fake)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = ci.analyze_long_run(CASE)
    assert out["available"] is False and out["coint_rank"] is None
    assert "허수부" in out["reason"]


@pytest.mark.parametrize("imag", [1e-14, 0.0])
def test_numerical_noise_in_the_imaginary_part_is_not_refused(monkeypatch, imag):
    """짝의 짝 — 부동소수 잡음 수준의 허수부는 거절 사유가 아니다(항상 거절하는 구현을 막는다)."""
    import statsmodels.tsa.vector_ar.vecm as vecm
    real = vecm.coint_johansen

    def fake(y, det_order, k_ar_diff):
        jo = real(y, det_order, k_ar_diff)
        return SimpleNamespace(lr1=jo.lr1, cvt=jo.cvt, eig=np.asarray(jo.eig, dtype=complex) + imag * 1j)
    monkeypatch.setattr(vecm, "coint_johansen", fake)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = ci.analyze_long_run(CASE)
    assert out["available"] is True, out.get("reason")
