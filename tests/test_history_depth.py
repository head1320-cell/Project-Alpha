"""과거 데이터 적재 깊이 — 매크로(BOK/FRED) 깊이 env화(5년 하드코딩 제거).

★기본값이 5 → 15 → 20 으로 두 번 올라갔다 (P4-D3)★
15년(180개월)은 `capability.py` 의 `frontier_sample` 요건(240개월)을 **채우지 못한다**.
키를 정상적으로 넣어도 사다리가 안 올라간다는 뜻이고, 설정을 따로 만져야만 열리는
천장은 사실상 닫힌 천장이다. 그래서 기본값을 요건에 맞췄다.

아래 테스트는 숫자 20 자체가 아니라 **그 숫자가 요건을 만족한다는 사실**을 지킨다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.services.macro_collector as mc  # noqa: E402

# capability.py:214 의 `_min_observations(240, require_real_source=True)` 와 같은 값.
# 여기서 import 할 수 없는 이유: 그 숫자는 프로브 클로저 안에 있어 밖에서 못 읽는다.
# 값이 갈라지면 아래 두 번째 단언이 아니라 tests/test_macro_depth.py 가 잡는다.
_FRONTIER_MIN_MONTHS = 240


def test_macro_history_years_default(monkeypatch):
    monkeypatch.delenv("MACRO_HISTORY_YEARS", raising=False)
    assert mc._history_years() == 20   # 기본 20년 (BOK/FRED는 수십 년 제공)


def test_default_depth_reaches_the_frontier_requirement(monkeypatch):
    """★설정을 안 만져도 프론티어 표본 요건에 닿는다★

    이것이 기본값을 15 에서 올린 이유 전부다. 기본값을 되돌리면 여기가 빨개진다 —
    첫 테스트의 숫자만 고쳐 놓고 넘어갈 수 없게 하는 짝이다.
    """
    monkeypatch.delenv("MACRO_HISTORY_YEARS", raising=False)
    assert mc._history_years() * 12 >= _FRONTIER_MIN_MONTHS
    # 그리고 옛 기본값으로는 닿지 못했다는 사실 — 변경이 불필요했던 게 아니라는 기록.
    assert 15 * 12 < _FRONTIER_MIN_MONTHS


def test_macro_history_years_override(monkeypatch):
    monkeypatch.setenv("MACRO_HISTORY_YEARS", "25")
    assert mc._history_years() == 25


def test_macro_history_years_bad_value_fallback(monkeypatch):
    monkeypatch.setenv("MACRO_HISTORY_YEARS", "oops")
    assert mc._history_years() == 20   # 잘못된 값 → 기본 폴백
