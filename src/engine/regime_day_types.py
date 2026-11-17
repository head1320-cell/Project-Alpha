"""하루 유형 비율 × 국면 — 시행의 (날, 종목) 표본을 그날의 시장 국면(가장 큰 확률)별로 나눠 하루 유형마다 센다 (구현 계획 §7.3 · K2b).

순수 함수다(읽기 · 쓰기 · 난수 없음). ★관측이며 결정에 쓰지 않는다★ — 같은 날의 두 이름표(시가 전에 아는 국면 · 첫 N분이 닫힌 뒤에
정해지는 유형)를 겹쳐 셀 뿐이다. 어느 쪽이 다른 쪽을 예측한다는 뜻이 아니고 비율의 차이가 국면의 성질이라는 뜻도 아니다.

- 표본: `(날, 종목, 유형 1 ~ K | None, 뺀 사유 | None)` — 유형은 모형의 중심으로 배정한 값이다(문 층이 `day_types.window` · `assign` 으로 센다).
  유형이 없는 표본(창이 덜 찬 날 등)은 뺀 표본이며 사유 코드가 있어야 한다.
- 국면 규칙은 국면별 성과 나눔(`regime_split`)과 같다 — 그날 국면이 없거나 지수에 그날이 없으면 '국면 미상'(같은 사유 문장 · 날 수와 표본 수).
- 비율 = 그 유형의 수 ÷ 그 묶음에서 ★분류된★ 표본(뺀 표본은 분모에 넣지 않는다) — 분류된 표본이 0 이면 없음이다(0% 가 아니다).
- 표본 안: 표본의 날이 모형의 학습 날이면 따로 센다(모형이 그날을 보고 중심을 정했다 — 표본 밖과 같은 무게로 읽지 않게).
- ★국면들 + 미상 = 전체★(표본 · 분류 · 표본 안 · 유형별 수 · 뺀 사유). 표본의 순서와 무관하다.
- 유형 번호가 1 ~ K 밖이거나 · 국면 번호가 1 ~ k 밖이거나 · 뺀 표본에 사유가 없으면 지어내지 않고 `ValueError` 다.
"""
from __future__ import annotations

from numbers import Integral
from typing import Any

from src.engine.regime_split import REASONS


def _group(types_k: int) -> dict[str, Any]:
    return {"samples": 0, "classified": 0, "in_sample": 0, "counts": [0] * types_k, "inside": [0] * types_k, "excluded": {}}


def _view(g: dict[str, Any], types_k: int) -> dict[str, Any]:
    n = g["classified"]
    types = [{"type": j + 1, "n": g["counts"][j], "in_sample": g["inside"][j], "share": (g["counts"][j] / n) if n else None}
             for j in range(types_k)]
    return {"samples": g["samples"], "classified": n, "in_sample": g["in_sample"], "types": types,
            "excluded": dict(sorted(g["excluded"].items()))}


def day_types_by_regime(samples: list[tuple], regime_days: list[dict], k: int, types_k: int,
                        train_days: list[str] | set[str]) -> dict[str, Any]:
    train = set(train_days)
    by_date = {r["date"]: r for r in regime_days}
    states = [_group(types_k) for _ in range(k)]
    unknown, total = _group(types_k), _group(types_k)
    reasons: dict[str, dict[str, Any]] = {}
    for date, _ticker, kind, why in sorted(samples, key=lambda s: (s[0], s[1])):
        if kind is not None and (isinstance(kind, bool) or not isinstance(kind, Integral) or not 1 <= kind <= types_k):
            raise ValueError("type_out_of_range")
        if kind is None and not why:
            raise ValueError("excluded_without_reason")
        row = by_date.get(date)
        top = row.get("top") if row is not None else None
        if top is not None:
            if not 1 <= top <= k:
                raise ValueError("state_out_of_range")
            into = states[top - 1]
        else:
            into = unknown
            reason = REASONS["no_index_day"] if row is None else (row.get("reason") or REASONS["no_regime"])
            seen = reasons.setdefault(reason, {"days": set(), "samples": 0})
            seen["days"].add(date)
            seen["samples"] += 1
        for g in (into, total):
            g["samples"] += 1
            if kind is None:
                g["excluded"][why] = g["excluded"].get(why, 0) + 1
                continue
            j = int(kind) - 1
            g["classified"] += 1
            g["counts"][j] += 1
            if date in train:
                g["in_sample"] += 1
                g["inside"][j] += 1
    return {"k": k, "types_k": types_k,
            "states": [{"state": s + 1, **_view(g, types_k)} for s, g in enumerate(states)],
            "unknown": {**_view(unknown, types_k),
                        "reasons": [{"reason": why, "days": len(v["days"]), "samples": v["samples"]} for why, v in reasons.items()]},
            "total": _view(total, types_k)}
