"""판정 어휘 — ★"유의하지 않다" 는 "효과가 없다" 가 아니다★ (A2)
==============================================================================
M1~M5 가 정확히 이 구멍에 빠졌다. 판정이 `passed` 불리언 하나뿐이라 "SPA
p=0.094 로 관문을 못 넘었다" 와 "효과가 없다" 가 리포트에서 **구별되지 않았다**.
양성 통제에서 심은 효과 1× 의 검출률이 40% 였다는 사실 — 관문이 애초에 찾을 힘이
없었다는 사실 — 을 담을 자리가 없었다.

★다섯 분류★

| 판정 | 뜻 |
|---|---|
| `positive` | 널 밖이고 탐색 보정 후에도 유의하다 |
| `inconclusive` | 두 관문이 엇갈린다 — 결론이 아니다 |
| `underpowered` | 못 넘었는데 **검정력이 모자랐다** — 없다는 뜻이 아니다 |
| `evidence_of_no_effect` | 못 넘었고 **찾을 힘은 충분했다** |
| `no_evidence` | 관문을 못 돌렸거나 검정력을 모른다 — ★미상은 판정이 아니다★ |

★만다트 §4 의 계약★ `p > 0.05` 만으로는 결코 `evidence_of_no_effect` 가 되지
않는다. 반드시 **입증된 검정력**이 있어야 한다.

★판정은 규칙이지 데이터가 아니다★ 그래서 순수 함수다 — `null_stats` ·
`regime_control.decide_verdict` 와 같은 규율이다.
"""

from __future__ import annotations

from typing import Any

VERDICT_NO_EVIDENCE = "no_evidence"
VERDICT_UNDERPOWERED = "underpowered"
VERDICT_INCONCLUSIVE = "inconclusive"
VERDICT_EVIDENCE_OF_NO_EFFECT = "evidence_of_no_effect"
VERDICT_POSITIVE = "positive"

ALL_VERDICTS = (VERDICT_NO_EVIDENCE, VERDICT_UNDERPOWERED, VERDICT_INCONCLUSIVE,
                VERDICT_EVIDENCE_OF_NO_EFFECT, VERDICT_POSITIVE)

#: ★관례이지 측정치가 아니다★ — 바꾸면 판정이 바뀐다. 리포트에 함께 싣는다.
DEFAULT_TARGET_POWER = 0.80

#: 모든 관문 리포트가 실어야 하는 필드.
REQUIRED_FIELDS = ("mde", "power", "n_eff")


def classify(*, null_outside: bool | None, spa_ok: bool | None,
             power: float | None,
             target_power: float = DEFAULT_TARGET_POWER) -> dict[str, Any]:
    """두 관문 결과 + 검정력 → 다섯 분류 중 하나.

    ★순서가 계약이다★ 검정력은 **못 찾은 것**을 읽을 때만 필요하다. 찾았으면
    찾은 것이므로 `positive` 는 검정력 없이도 선다. 반대로 못 찾았을 때 검정력을
    모르면 `underpowered` 도 `evidence_of_no_effect` 도 주장할 수 없다 —
    ★모르는 검정력은 '낮은 검정력' 이 아니다.★
    """
    tp = float(target_power)
    common = {"target_power": tp, "power": (None if power is None else float(power)),
              "convention": True}

    if null_outside is True and spa_ok is True:
        return {**common, "verdict": VERDICT_POSITIVE, "passed": True,
                "why": ["널 밖이고 탐색 보정 후에도 유의합니다"]}

    if null_outside is None or spa_ok is None:
        unrun = [n for n, v in (("널 통제", null_outside), ("SPA", spa_ok))
                 if v is None]
        return {**common, "verdict": VERDICT_NO_EVIDENCE, "passed": False,
                "why": [f"{' · '.join(unrun)} 를 돌리지 못했습니다 — "
                        f"미상은 판정이 아닙니다"]}

    if bool(null_outside) != bool(spa_ok):
        passed_gate = "널 통제" if null_outside else "SPA"
        failed_gate = "SPA" if null_outside else "널 통제"
        return {**common, "verdict": VERDICT_INCONCLUSIVE, "passed": False,
                "why": [f"{passed_gate} 는 넘고 {failed_gate} 는 못 넘었습니다 — "
                        f"엇갈리면 결론이 아닙니다"]}

    # 둘 다 못 넘었다 — ★여기서 검정력이 뜻을 가른다★
    if power is None:
        return {**common, "verdict": VERDICT_NO_EVIDENCE, "passed": False,
                "why": ["검정력을 모릅니다 — 불유의를 '효과 없음' 으로 읽을 수 "
                        "없고 '검정력 부족' 이라고도 할 수 없습니다"]}
    if float(power) >= tp:
        return {**common, "verdict": VERDICT_EVIDENCE_OF_NO_EFFECT, "passed": False,
                "why": [f"관문을 못 넘었고 검정력 {float(power):.2f} ≥ 목표 "
                        f"{tp:.2f} 라 찾을 힘은 있었습니다"]}
    return {**common, "verdict": VERDICT_UNDERPOWERED, "passed": False,
            "why": [f"관문을 못 넘었지만 검정력 {float(power):.2f} < 목표 "
                    f"{tp:.2f} 입니다 — 없다는 뜻이 아니라 찾을 힘이 없었습니다"]}


def _reason_for(report: dict[str, Any], field: str) -> str | None:
    """`{field}_reason` 또는 `reasons[field]` — ★빈 문자열은 사유가 아니다★."""
    for cand in (report.get(f"{field}_reason"),
                 (report.get("reasons") or {}).get(field)):
        if isinstance(cand, str) and cand.strip():
            return cand
    return None


def require_power_fields(report: dict[str, Any], *,
                         fields: tuple[str, ...] = REQUIRED_FIELDS) -> list[str]:
    """리포트에 `mde`·`power`·`n_eff` 가 실렸는지. 빠진 것들의 **사유 목록**.

    ★리포트에 검정력이 없으면 그 리포트는 불완전하다★ 값이 `None` 인 것은
    괜찮다 — 다만 **사유와 함께** 적어야 한다. 사유 없는 `None` 은 침묵 폴백이다.
    """
    missing: list[str] = []
    for f in fields:
        if f not in report:
            missing.append(f"`{f}` 가 리포트에 없습니다")
        elif report[f] is None and not _reason_for(report, f):
            missing.append(f"`{f}` 가 미상인데 사유가 없습니다 — "
                           f"미상은 사유와 함께 적습니다")
    return missing
