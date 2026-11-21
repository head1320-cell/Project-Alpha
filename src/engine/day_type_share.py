"""하루 유형 비중 — 고른 하루 유형(하나 이상 · 전부 아님)이 바구니 표본 가운데 차지한 20거래일 합친 비중 (설계 2026-11-17 §6 · 구현 계획 §7.6 · K5)
==============================================================================
★순수 함수★ — 파일 · DB 를 읽지 않는다. 날마다의 셈(바구니 종목마다 그날 장 시작 구간의 유형)은 문 층이 저장소에서 읽어 넘긴다.

- 거래일 t 의 값 = Σ_{d ∈ [t−19, t]} 고른 유형의 표본 수 ÷ Σ_{d ∈ [t−19, t]} 유형을 정한 표본 수 — ★풀링★(날마다 비율의 평균이 아니다 —
  표본이 적은 날이 같은 무게를 갖지 않게). 시장 국면은 거래일 d 에 X[d−1] 을 쓰므로 d 의 국면은 d−20 ~ d−1 의 표본만 본다
  (그날 표본은 장 초반 창이 끝나야 안다).
- 창 안에 세지 않은 날 · 분봉이 없는 날 · 유형을 정한 표본이 0 인 날이 하나라도 있으면 그 창은 미상 + 사유 — 0 이나 앞 값으로 채우지 않는다
  (시장 국면의 '종가 21개가 모두'와 같은 엄격함). 사유가 여럿이면 이어 세면 풀리는 '세지 않은 날'을 먼저 말한다.
- 고른 유형: 1 ~ k 의 정수 · 하나 이상 · 중복 없이 · 전부는 거절(비중이 늘 1 이라 나눌 것이 없다).
- 날마다의 셈 `counts[d]`: `None`(세지 않음) · `{"missing": "no_bars"}`(그날 바구니의 분봉이 없거나 쓰지 않는 합성) ·
  `{"missing": "unreadable"}`(그날 분봉 파일을 읽지 못함 — 없다는 뜻이 아니다) ·
  `{"by_type": {유형: 수}, "classified": 유형을 정한 표본 수}`. 어긋난 셈(음수 · 고른 것보다 적은 분류 수 · 모르는 사유)은 쓰지 않고 `ValueError`.
- 바구니의 하루(`basket_day`): 종목마다의 (유형, 사유)를 그날의 셈으로 — 한 종목이라도 세지 않았으면 세지 않은 날 ·
  일부 종목만 유형을 정했으면 ★정한 표본만★ 센다(풀링의 분모 · 뺀 표본은 사유별로 남긴다) · 봉이 하나도 없으면 분봉 없는 날 ·
  봉은 있었으나 장 시작 구간을 못 쓴 종목이 있으면 표본 없는 날.

★이 모듈이 말하지 않는 것★: 비중은 이름표(하루 유형)의 집계다. 그 비중이 시장의 무엇을 뜻한다거나 다음 날을 예측한다는 말이 아니다.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np

WINDOW = 20

#: 창이 미상인 까닭(코드 → 문장). 화면은 서버 문장을 그대로 보인다.
REASONS = {
    "short": "하루 유형 비중의 창이 차지 않았습니다(앞선 거래일이 모자랍니다).",
    "not_counted": "창 안에 아직 세지 않은 날이 있습니다. 비중 세기로 이어서 셉니다.",
    "unreadable": "창 안에 분봉 파일을 읽지 못한 날이 있습니다(분봉이 없다는 뜻이 아닙니다).",
    "no_bars": "창 안에 바구니 종목의 분봉이 없는 날이 있습니다(적재되지 않았거나 운영에서 쓰지 않는 합성 분봉입니다).",
    "no_samples": "창 안에 하루 유형을 정한 표본이 없는 날이 있습니다(분봉은 있으나 장 시작 구간의 봉이 모자라거나 결함이 있었습니다).",
}
#: 사유가 여럿일 때 말하는 순서 — 이어 세면 풀리는 것부터 · 읽지 못한 것(없음과 다르다)을 없음보다 먼저.
_ORDER = ("not_counted", "unreadable", "no_bars", "no_samples")
_MISSING = ("no_bars", "unreadable")
#: 종목 하나의 그날 사유 가운데 '그 종목의 봉이 없다'는 것 — 적재되지 않음 · 운영에서 막은 합성 · 그 종목만 없음(`minute_bars` · `minute_feed` 의 코드).
NO_BAR_CODES = ("not_loaded", "synthetic_rows_blocked", "no_bars")
#: 그날 파일을 읽지 못함 — 바구니 전체에 같다(파일 하나).
UNREADABLE_CODE = "unreadable"

REFUSALS = {
    "no_types": "하루 유형을 하나 이상 고르십시오.",
    "type_out_of_range": "하루 유형 번호는 1 이상 그 모형의 유형 수 이하의 정수여야 합니다.",
    "duplicate_types": "같은 하루 유형을 두 번 골랐습니다.",
    "all_types": "모든 하루 유형을 고르면 비중이 늘 1 이라 국면을 나누지 못합니다. 일부만 고르십시오.",
}


class ShareError(ValueError):
    """고르기의 잘못 — 문 층이 400 으로 올린다(`code` · 문장)."""

    def __init__(self, code: str):
        super().__init__(REFUSALS[code])
        self.code = code


def check_types(types: Iterable[Any], k: int) -> tuple[int, ...]:
    """고른 유형 → 정렬된 튜플. 비어 있음 · 범위 밖(정수가 아닌 것 · 참거짓 포함) · 중복 · 전부는 `ShareError`."""
    picked = list(types)
    if not picked:
        raise ShareError("no_types")
    for t in picked:
        if isinstance(t, bool) or not isinstance(t, (int, np.integer)) or not 1 <= int(t) <= int(k):
            raise ShareError("type_out_of_range")
    if len(set(int(t) for t in picked)) != len(picked):
        raise ShareError("duplicate_types")
    if len(picked) >= int(k):
        raise ShareError("all_types")
    return tuple(sorted(int(t) for t in picked))


def _day(c: Any) -> tuple[str | None, int, Mapping[int, int]]:
    """하루의 셈 → (미상 코드, 분류된 표본 수, 유형별 수). 어긋나면 `ValueError`."""
    if c is None:
        return "not_counted", 0, {}
    if "missing" in c:
        if c["missing"] not in _MISSING:
            raise ValueError(f"모르는 분봉 없음 사유: {c['missing']!r}")
        return str(c["missing"]), 0, {}
    by = {int(t): int(v) for t, v in c["by_type"].items()}
    classified = int(c["classified"])
    if classified < 0 or any(v < 0 for v in by.values()) or sum(by.values()) > classified:
        raise ValueError("하루의 셈이 어긋났습니다(음수이거나 유형별 수의 합이 분류된 표본 수보다 큽니다)")
    if classified == 0:
        return "no_samples", 0, by
    return None, classified, by


def basket_day(rows: Sequence[tuple[Any, Any] | None]) -> dict[str, Any] | None:
    """바구니 종목마다의 (유형 번호 또는 None, 사유 코드 또는 None) → 그날의 셈(`window_share` 가 읽는 모양). 세지 않은 종목은 `None`.

    한 줄은 유형(1 이상의 정수)과 사유 가운데 꼭 하나만 갖는다 — 어긋나면 `ValueError`(지어내지 않고 멈춘다)."""
    if not rows:
        raise ValueError("바구니가 비었습니다")
    if any(r is None for r in rows):
        return None
    labels: list[int] = []
    excluded: dict[str, int] = {}
    for label, reason in rows:                                   # type: ignore[misc]
        if label is not None:
            if reason is not None or isinstance(label, bool) or not isinstance(label, (int, np.integer)) or int(label) < 1:
                raise ValueError(f"한 줄은 유형(1 이상의 정수)과 사유 가운데 하나만 가집니다: {(label, reason)!r}")
            labels.append(int(label))
        else:
            if not isinstance(reason, str) or not reason:
                raise ValueError(f"유형이 없는 줄에는 사유가 있어야 합니다: {(label, reason)!r}")
            excluded[reason] = excluded.get(reason, 0) + 1
    if UNREADABLE_CODE in excluded:
        return {"missing": UNREADABLE_CODE}
    if not labels and all(r in NO_BAR_CODES for r in excluded):
        return {"missing": "no_bars"}
    by_type: dict[int, int] = {}
    for t in labels:
        by_type[t] = by_type.get(t, 0) + 1
    return {"by_type": by_type, "classified": len(labels), "excluded": excluded}


def window_share(dates: Sequence[str], counts: Mapping[str, Any], types: Iterable[int],
                 window: int = WINDOW) -> tuple[np.ndarray, list[str | None], np.ndarray]:
    """날짜(지수 거래일 · 오름차순)마다 그날까지 `window` 거래일의 합친 비중 → (값 · 미상 코드 · 창의 분류된 표본 수).

    미상인 날의 값은 NaN · 표본 수는 0 이다. 창의 첫 `window − 1` 날은 `short`."""
    chosen = {int(t) for t in types}
    n = len(dates)
    picked = np.zeros(n)
    classified = np.zeros(n)
    code: list[str | None] = [None] * n
    for i, d in enumerate(dates):
        bad, cls, by = _day(counts.get(d))
        code[i] = bad
        if bad is None:
            picked[i] = sum(v for t, v in by.items() if t in chosen)
            classified[i] = cls
    values = np.full(n, np.nan)
    reasons: list[str | None] = [None] * n
    samples = np.zeros(n, dtype=int)
    for t in range(n):
        if t < window - 1:
            reasons[t] = "short"
            continue
        inside = code[t - window + 1: t + 1]
        bad = next((c for c in _ORDER if c in inside), None)
        if bad is not None:
            reasons[t] = bad
            continue
        total = float(classified[t - window + 1: t + 1].sum())
        values[t] = float(picked[t - window + 1: t + 1].sum()) / total
        samples[t] = int(total)
    return values, reasons, samples
