"""스튜디오 앙상블 — **불일치를 일급으로** (P4-M3)
==============================================================================
왜 필요한가
------------------------------------------------------------------------------
다섯 스튜디오(TSFM 잠재 · Neural SDE · 인과 · 꼬리 · Agentic 뷰)는 각자 답하고
끝난다. 이들을 하나의 매크로 상태로 묶되, ★합의도가 아니라 불일치를 일급으로★ 낸다.

모델이 서로 다르게 말할 때가 **가장 정보가 많은 순간**이다. 평균으로 뭉개면 그
정보가 사라지고, 화면은 "확신에 찬 하나의 답" 을 보여 준다 — 실제로는 도구들이
갈렸는데도. A8 이 세 국면 도구를 하나로 평균 내지 않은 이유가 그것이고, 그때 적은
문장이 여기 그대로 적용된다: "하나로 평균 내면 어느 모형이 무슨 말을 했는지 사라진다."

★미가용 도구를 합의에 세지 않는다★
5개 중 4개가 미가용이고 1개만 답했을 때 "만장일치" 라고 하면 거짓이다. 답한 개수를
함께 내고, 1개면 합의가 아니라고 적는다. 미가용 도구는 **사유와 함께** 이름을 남긴다 —
어느 도구가 왜 빠졌는지 모르면 남은 답을 어떻게 읽을지 알 수 없다.

★동수는 결론이 아니다★
2:2 에서 임의로 하나를 고르면 그건 지어낸 결론이다. `tie: true` 로 그 사실을 낸다.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)


def disagreement(verdicts: list[str]) -> dict[str, Any]:
    """판정 목록 → 불일치 지표.

    정규화 엔트로피를 쓴다 — 0 은 만장일치, 1 은 완전 분산이다. 최빈값 비율
    (1 − max share) 도 후보였지만 그건 **몇 갈래로 갈렸는지**를 구분하지 못한다:
    2갈래 균등과 4갈래 균등이 둘 다 0.5·0.75 로 뭉뚱그려지는 대신, 엔트로피는
    갈래가 늘수록 단조증가한다. "얼마나 갈렸나" 를 재는 것이 목적이므로 그쪽이 맞다.

    `counts` 를 함께 내는 이유는 점수만으로는 **무엇과 무엇이** 갈렸는지 화면이
    말할 수 없기 때문이다.
    """
    vals = [v for v in verdicts if v]
    if not vals:
        return {"score": 0.0, "unique": 0, "counts": {}, "n": 0}

    counts = Counter(vals)
    n = len(vals)
    unique = len(counts)
    if unique <= 1:
        return {"score": 0.0, "unique": unique, "counts": dict(counts), "n": n}

    import math
    entropy = -sum((c / n) * math.log(c / n) for c in counts.values())
    # 표본 수가 상한을 정한다 — n개 답이 전부 다를 때가 최대다.
    max_entropy = math.log(min(n, unique)) if min(n, unique) > 1 else 1.0
    # 갈래가 늘수록 단조증가하도록 관측 가능한 최대(log n)로 정규화한다.
    norm = math.log(n) if n > 1 else 1.0
    return {
        "score": round(entropy / norm, 6),
        "unique": unique,
        "counts": dict(counts),
        "n": n,
        "max_entropy": round(max_entropy, 6),
    }


def combine_studio_views(views: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """도구별 결과 → 결합 판정 + **불일치와 미가용을 함께**.

    `views` 는 `{도구이름: {available, verdict?, reason?}}`. 스튜디오의 공통 계약
    (`base.ok` / `base.unavailable`)과 같은 모양이라 그대로 넣을 수 있다.

    ★결합해도 개별 판정을 숨기지 않는다★ `per_tool` 에 원본이 남는다. 남지 않으면
    결론을 되짚을 수 없고, 되짚을 수 없는 결론은 연구 결과가 아니다.
    """
    available: dict[str, str] = {}
    unavailable: list[str] = []
    reasons: dict[str, str] = {}

    for name, res in views.items():
        if not isinstance(res, dict) or not res.get("available"):
            unavailable.append(name)
            reasons[name] = (res or {}).get("reason") or "사유가 기록되지 않았습니다."
            continue
        verdict = res.get("verdict")
        if verdict is None:
            unavailable.append(name)
            reasons[name] = "가용하다고 했지만 판정이 없습니다."
            continue
        available[name] = str(verdict)

    n_available = len(available)
    dis = disagreement(list(available.values()))

    if n_available == 0:
        return {
            "verdict": None, "consensus": False, "tie": False,
            "n_available": 0, "per_tool": {}, "unavailable": unavailable,
            "reasons": reasons, "disagreement": dis,
            "note": ("가용한 도구가 하나도 없습니다 — 결론을 내지 않습니다. "
                     "미가용 사유는 `reasons` 를 보세요."),
        }

    counts = Counter(available.values())
    top = counts.most_common()
    tie = len(top) > 1 and top[0][1] == top[1][1]
    verdict = top[0][0] if not tie else None

    # ★합의의 정의를 좁게 잡는다★ 도구 2개 이상이 **전부** 같아야 합의다.
    # 1개만 답한 것은 합의가 아니라 표본 1이고, 2:1 은 갈린 것이다.
    consensus = n_available >= 2 and dis["unique"] == 1

    if n_available == 1:
        note = (f"가용한 도구가 {next(iter(available))} 하나뿐입니다 — 합의가 아니라 "
                "단일 관측입니다. 다른 도구의 미가용 사유를 함께 읽으세요.")
    elif tie:
        note = (f"판정이 {top[0][1]}:{top[1][1]} 로 동수입니다 — 임의로 한쪽을 고르지 "
                "않습니다. 동수는 결론이 아니라 그 자체가 정보입니다.")
    elif not consensus:
        note = (f"도구 {n_available}개 중 {top[0][1]}개가 '{top[0][0]}' 로 다수이지만 "
                "만장일치가 아닙니다 — 갈린 사실을 다수결과 함께 읽어야 합니다.")
    else:
        note = f"가용한 도구 {n_available}개가 모두 '{verdict}' 로 일치합니다."

    return {
        "verdict": verdict,
        "consensus": consensus,
        "tie": tie,
        "n_available": n_available,
        "per_tool": available,
        "unavailable": unavailable,
        "reasons": reasons,
        "disagreement": dis,
        "note": note,
    }
