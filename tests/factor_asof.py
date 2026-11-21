"""팩터 시험이 쓰는 날짜 — ★한 곳에서 정한다★ (2026-11-11)

## 왜 따로 두나

합성 매크로 계열은 "오늘 기준 최근 60개월"이다(`macro_collector._collect_one` 의 `length=60` —
240으로 늘렸다가 되돌린 까닭이 그 자리 주석에 있다). 창이 날마다 미끄러진다.

시험은 `as_of="2024-06-30"` 과 귀인 창 2021-01~2023-12 를 ★고정 날짜★로 썼다. 자른 뒤 남는 달이
2026-11 에 딱 24개(`MIN_MONTHS`)였고 2026-12-01 부터 23개가 되어 일곱 건이 빨개진다
(`faketime -f "+20d"` 로 쟀다 · 고치기 전 코드에서도 같았다).

그래서 매크로 창에 닿는 날짜는 오늘에서 센다. 시세만 보는 시험은 고정 날짜 그대로다
(시세 mock 은 2000-01-03 부터 날짜 주소 가능하다).

`tests/test_factor_tests_do_not_expire.py` 가 이 도우미를 여러 "오늘"로 훑어, 어느 날에 돌려도
남는 달이 모자라지 않는지 본다.
"""
from __future__ import annotations

import calendar
from datetime import date


def _shift(year: int, month: int, months: int) -> tuple[int, int]:
    """(해, 달)에 `months` 를 더한다(음수면 앞으로)."""
    k = year * 12 + (month - 1) + months
    return k // 12, k % 12 + 1


def month_end(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


#: as_of 를 오늘에서 몇 달 앞에 둘지. 60개월 창에서 자른 뒤 `MIN_MONTHS`(24) 이상이 남아야 한다.
#: ★18 인 까닭★ `truncate_series` 가 `YYYYMM` 계열을 as_of 가 든 해의 앞 해 12월에서 자르던 때에는
#: 남는 관측이 60 − k − (as_of 의 달) 개였다 — 가장 나쁜 달(12월)에도 60 − 18 − 12 = 30 개가 남는다.
#: 그 결함을 고친 뒤에는 60 − 18 = 42 개가 남는다. 어느 쪽에서도 넉넉하다.
STACK_MONTHS_BACK = 18


def stack_as_of(today: date | None = None) -> str:
    """팩터 스택 시험의 as_of — 오늘에서 `STACK_MONTHS_BACK` 달 앞 달의 말일."""
    t = today or date.today()
    return month_end(*_shift(t.year, t.month, -STACK_MONTHS_BACK))


def attribution_months(today: date | None = None, n: int = 36) -> list[dict]:
    """팩터 귀인 시험의 월별 수익률 창 — ★지난달까지 `n` 달★(매크로 창 60개월 안에 통째로 든다)."""
    t = today or date.today()
    out = []
    for i in range(n):
        y, m = _shift(t.year, t.month, i - n)
        out.append({"year": y, "month": m, "return_pct": 1.0 + 0.4 * ((i * 7919) % 11 - 5)})
    return out
