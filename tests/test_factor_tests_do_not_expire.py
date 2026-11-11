"""팩터 시험은 ★달력 때문에 죽지 않는다★ (2026-11-11)

## 무엇이 문제였나 (실측)

`tests/test_factor_stack_respects_as_of.py` 6건과 `tests/test_factor_attribution_vintage.py` 1건이
2026-12-01 부터 빨개진다. 코드가 바뀌어서가 아니라 달력이 넘어가서다 — 연습용 매크로 계열은 오늘 기준
최근 60개월인데 시험은 고정 날짜(`2024-06-30` · 2021-01~2023-12)를 썼다. 남는 달이 24 → 23 이 된다.

이 파일은 그 시험들이 쓰는 날짜(`tests/factor_asof.py`)를 ★여러 "오늘"로 훑어★, 어느 날에 돌려도
대리계열이 최소 관측 수(`MIN_MONTHS`)를 채우는지 본다. 고정 날짜로 되돌리면 여기서 빨개진다.

수집기를 날마다 통째로 돌리면 한 번에 2초가 넘는다. 그래서 ★연습용 계열의 길이와 "어느 계열이 비는가"는
실제 수집 경로에서 한 번 읽고★(60 을 여기 박지 않는다) 날짜별 계열은 같은 생성기로 바로 만든다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import calendar  # noqa: E402
from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402

import src.services.macro_collector as mc  # noqa: E402
from src.engine.factor_exposure import FACTOR_PROXIES, MIN_MONTHS, resolve_proxies  # noqa: E402
from tests.factor_asof import attribution_months, stack_as_of  # noqa: E402

#: 오늘부터 이만큼의 달을 훑는다 — 달마다 첫날·15일·말일(생성기가 30일씩 거슬러 가므로 날에 따라 달 라벨이 달라질 수 있다).
_SWEEP_MONTHS = 48


class _Series:
    def __init__(self, timestamps, values):
        self.timestamps, self.values = list(timestamps), list(values)


@pytest.fixture(scope="module")
def mock_shape() -> dict[str, int]:
    """실제 수집 경로가 내는 연습용 계열의 모양 — {계열 이름: 관측 수}. 빈 계열은 빠진다."""
    snap = mc.MacroCollector().collect_all(use_cache=False)
    shape = {k: len(s.timestamps) for k, s in snap.series.items()
             if s.timestamps and getattr(s, "source", "") == "MOCK"}
    used = {n for cands in FACTOR_PROXIES.values() for n in cands}
    assert used & set(shape), "팩터 대리계열이 연습용 자료에 하나도 없다 — 이 훑기는 공허하다"
    return shape


def _days():
    today = date.today()
    y, m = today.year, today.month
    out = [today]
    for i in range(_SWEEP_MONTHS):
        k = y * 12 + (m - 1) + i
        yy, mm = k // 12, k % 12 + 1
        for d in (1, 15, calendar.monthrange(yy, mm)[1]):
            day = date(yy, mm, d)
            if day >= today:
                out.append(day)
    return out


def _series_map_on(monkeypatch, day: date, shape: dict[str, int]) -> dict:
    """수집기의 "오늘"이 `day` 일 때의 연습용 계열 묶음."""
    pinned = datetime(day.year, day.month, day.day, 9, 0, 0)

    class _Pinned(datetime):
        @classmethod
        def now(cls, tz=None):
            return pinned

    monkeypatch.setattr(mc, "datetime", _Pinned)
    out = {}
    for name, length in shape.items():
        ts, vals = mc._generate_mock_series(name, length=length, **mc.MOCK_PROFILES.get(name, {"base": 100, "vol": 5, "trend": 0}))
        out[name] = _Series(ts, vals)
    return out


def test_the_stack_as_of_leaves_enough_months_on_any_day(monkeypatch, mock_shape):
    """`stack_as_of(오늘)` 로 잘라도 팩터 아홉이 모두 대리계열을 얻는다 — 앞으로 4년의 어느 날에도."""
    bad = []
    for day in _days():
        sm = _series_map_on(monkeypatch, day, mock_shape)
        as_of = stack_as_of(day)
        assert as_of < day.isoformat(), f"as_of {as_of} 가 오늘({day}) 이후다 — 자를 것이 없다"
        p = resolve_proxies(sm, as_of=as_of)
        n = {f: d["n_months"] for f, d in p["resolved"].items()}
        if len(n) != len(FACTOR_PROXIES) or min(n.values()) < MIN_MONTHS:
            bad.append(f"{day} as_of={as_of} 얻은 팩터 {len(n)}/{len(FACTOR_PROXIES)} 최소 {min(n.values(), default=0)}개월")
    assert bad == [], f"{len(bad)}일에서 달이 모자란다 — 처음 다섯: {bad[:5]}"


def test_the_stack_as_of_actually_cuts(monkeypatch, mock_shape):
    """★짝★ 늘 통과하는 as_of(예: 오늘)를 배제한다 — 자른 창은 안 자른 창보다 짧아야 한다."""
    for day in _days()[::12]:
        sm = _series_map_on(monkeypatch, day, mock_shape)
        cut = resolve_proxies(sm, as_of=stack_as_of(day))
        full = resolve_proxies(sm)
        for f in cut["resolved"]:
            assert cut["resolved"][f]["n_months"] < full["resolved"][f]["n_months"], (day, f)


def test_the_attribution_window_overlaps_the_factors_on_any_day(monkeypatch, mock_shape):
    """귀인 시험의 수익률 창이 팩터 변화와 `MIN_MONTHS` 이상 겹친다 — 어느 날에도."""
    bad = []
    for day in _days():
        sm = _series_map_on(monkeypatch, day, mock_shape)
        resolved = resolve_proxies(sm)["resolved"]
        months = {f"{r['year']:04d}-{r['month']:02d}" for r in attribution_months(day)}
        shared = months.intersection(*[set(d["changes"]) for d in resolved.values()])
        if len(shared) < MIN_MONTHS:
            bad.append(f"{day} 겹치는 달 {len(shared)}개")
    assert bad == [], f"{len(bad)}일에서 겹침이 모자란다 — 처음 다섯: {bad[:5]}"
