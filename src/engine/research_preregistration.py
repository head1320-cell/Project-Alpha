"""사전등록 지문 — ★결정규칙과 널 **행동**을 해시로 묶는다★ (P6)
==============================================================================
검토서: `docs/specs/2026-09-02-deepseek-concept-review.md` §4 P6 (격차 G2)

`regime_control.run()` 은 `cost_levels`·`threshold_pct` 를 **파라미터**로 받고,
리포트의 `preregistered` 블록은 그때 쓴 값을 그대로 적었다. 즉 ★자기 서술이지
자기 구속이 아니었다★ — `cost_levels=(5.0,)` 로 돌리면 리포트가 `[5.0]` 을
"사전등록됨" 이라고 충실히 적는다. 사전등록의 요점은 "무엇을 썼는지" 가 아니라
★"결과를 보고 바꾸지 않았음"★ 이고, 그 증명이 없었다.

★그리고 널을 **어떻게 만드는가** 는 상수가 아니라 코드다.★ `surrogate_path` ·
`shifts_for` 가 바뀌면 "널 밖" 의 뜻이 통째로 달라지는데 어떤 상수 해시도 그것을
보지 못한다. 그래서 **소스가 아니라 행동**을 해시한다 — 고정 경로·고정 시드로
생성기를 돌려 그 산출을 해시하므로, 주석·이름·리팩터에는 반응하지 않고 생성
규칙이 바뀔 때만 바뀐다.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 커밋되는 등록. 규칙을 바꾸려면 다시 만들어 커밋해야 하고 그것은 diff 로 검토된다.
REGISTRATION_PATH = Path("docs/specs/macro_gate_preregistration.json")

SCHEMA = 1

#: ★프로브는 상수다★ 결과에 따라 달라지면 지문이 지문이 아니다.
NULL_PROBE: dict[str, Any] = {
    "methods": ["shift", "markov", "block"],
    "seeds": [20260101, 20260102, 20260103],
    "shift_k": [1, 2, 3],
    "shifts_for_limit": 5,
    "shifts_for_seed": 7,
    "n_points": 24,
    "regimes": ["GOLDILOCKS", "REFLATION", "STAGFLATION", "DEFLATION"],
    "note": ("소스가 아니라 **행동**을 해시한다 — 고정 경로·고정 시드의 산출이라 "
             "주석·리팩터에는 반응하지 않고 생성 규칙이 바뀔 때만 바뀐다."),
}

_RULE_FIELDS = ("primary", "secondary", "cost_levels", "threshold_pct",
                "spa_alpha", "decision_rule_text", "candidate_arms",
                "primary_null")


def _canon(v):
    """정준화 — ★튜플/리스트·정수/실수·키 순서가 지문을 바꾸면 안 된다★

    등록 파일은 JSON 왕복을 거치므로 `(5.0, 10.0)` 이 `[5.0, 10.0]` 으로 돌아온다.
    거기서 지문이 깨지면 **읽는 순간 드리프트로 오인**된다.
    """
    if isinstance(v, dict):
        # ★정렬은 여기서 하지 않는다★ `rule_fingerprint` 의
        # `json.dumps(sort_keys=True)` 가 중첩까지 정렬하므로 여기서 또 하면
        # 같은 일을 두 곳이 하게 된다(변이가 그 중복을 드러냈다 — 한쪽을 지워도
        # 아무 테스트가 깨지지 않았다). 키 정렬의 단일 출처는 직렬화다.
        return {str(k): _canon(v[k]) for k in v}
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    return v


def decision_rule(*, primary, secondary, cost_levels, threshold_pct, spa_alpha,
                  decision_rule_text, candidate_arms, primary_null) -> dict:
    """사전등록되는 **결정규칙**. 격자·시드 같은 실행 파라미터는 여기 없다 —
    그것들은 실행마다 다를 수 있고, 바뀌면 안 되는 것은 판정 규칙이다."""
    return {
        "primary": primary, "secondary": list(secondary),
        "cost_levels": [float(c) for c in cost_levels],
        "threshold_pct": [float(t) for t in threshold_pct],
        "spa_alpha": float(spa_alpha),
        "decision_rule_text": decision_rule_text,
        "candidate_arms": list(candidate_arms),
        "primary_null": primary_null,
    }


def rule_fingerprint(rule: dict) -> str:
    """결정규칙 → sha256. 정준화 후 정렬된 JSON 을 해시한다."""
    payload = {k: _canon(rule.get(k)) for k in _RULE_FIELDS}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")).hexdigest()


def null_behaviour_fingerprint(probe: dict | None = None) -> dict:
    """널 생성기의 ★행동★ 지문 — 고정 입력의 산출을 해시한다.

    BLAS 가 개입하지 않고 numpy `default_rng`(PCG64)는 결정론적이라 프로세스·
    호스트를 넘어 안정하다(실측 확인).
    """
    import numpy as np

    import src.engine.regime_surrogates as rs

    p = probe or NULL_PROBE
    regs = p["regimes"]
    pts = [{"t": f"2020-{i % 12 + 1:02d}", "regime": regs[i % len(regs)]}
           for i in range(int(p["n_points"]))]

    h = hashlib.sha256()
    for method in p["methods"]:
        for i, seed in enumerate(p["seeds"]):
            rng = np.random.default_rng(int(seed))
            k = (p["shift_k"][i % len(p["shift_k"])]
                 if method == rs.NULL_SHIFT else None)
            sur = rs.surrogate_path(pts, method, rng, k=k)
            h.update(json.dumps([q.get("regime") for q in sur],
                                ensure_ascii=False).encode("utf-8"))
    ks, enumerated = rs.shifts_for(len(pts), int(p["shifts_for_limit"]),
                                   np.random.default_rng(int(p["shifts_for_seed"])))
    h.update(json.dumps([[int(x) for x in ks], bool(enumerated)]).encode("utf-8"))
    h.update(json.dumps([q.get("regime") for q in rs.constant_path(pts)],
                        ensure_ascii=False).encode("utf-8"))
    return {"fingerprint": h.hexdigest(), "probe": dict(p)}


def load_registration(path: str | Path | None = None) -> tuple[dict | None, str | None]:
    """등록을 읽고 ★기록된 지문이 기록된 규칙에서 나오는지 대조★ 한다 (P5 규율).

    ★없으면 미상이지 일치가 아니다.★
    """
    p = Path(path) if path is not None else REGISTRATION_PATH
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        return None, (f"사전등록 파일을 읽지 못했습니다({p}) — {type(e).__name__}. "
                      "등록된 적이 없다는 뜻이며 ★미상은 일치가 아닙니다★.")
    try:
        reg = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"사전등록 파일이 JSON 이 아닙니다({p}) — {e}"
    if not isinstance(reg, dict) or "rule" not in reg:
        return None, f"사전등록 파일에 `rule` 이 없습니다({p})"

    recomputed = rule_fingerprint(reg["rule"])
    if reg.get("rule_fingerprint") != recomputed:
        return None, (f"기록된 규칙 지문({reg.get('rule_fingerprint')})이 그 규칙에서 "
                      f"재계산한 값({recomputed})과 ★어긋납니다★ — 위조되었거나 "
                      "규칙만 고치고 지문을 갱신하지 않았습니다.")
    return reg, None


def compare(registration: dict | None, *, rule: dict, null_fp: str) -> dict:
    """등록 vs 이번 실행. `matches` 는 ★미상이면 `None`★ 이다."""
    effective_rule_fp = rule_fingerprint(rule)
    base = {"registered": (None if registration is None else {
                "rule_fingerprint": registration.get("rule_fingerprint"),
                "null_fingerprint": registration.get("null_fingerprint")}),
            "effective": {"rule_fingerprint": effective_rule_fp,
                          "null_fingerprint": null_fp}}
    if registration is None:
        return {**base, "matches": None, "drift": None,
                "reason": ("사전등록을 읽지 못했습니다 — 이 실행이 등록된 규칙을 "
                           "따랐는지 알 수 없습니다. ★미상은 일치가 아닙니다★.")}

    drift: list[str] = []
    if registration.get("rule_fingerprint") != effective_rule_fp:
        drift.append(
            f"결정규칙이 등록과 다릅니다 — 등록 {registration.get('rule_fingerprint')} "
            f"vs 이번 실행 {effective_rule_fp}")
    if registration.get("null_fingerprint") != null_fp:
        drift.append(
            f"널 생성 행동이 등록과 다릅니다 — 등록 "
            f"{registration.get('null_fingerprint')} vs 이번 실행 {null_fp}. "
            "생성 규칙이 바뀌었거나 난수 생성기 같은 외부 요인이 바뀌었습니다.")
    return {**base, "matches": not drift, "drift": drift,
            "reason": (None if not drift else " · ".join(drift))}
