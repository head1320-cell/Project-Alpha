"""기업 뷰 ★음성 통제★ 팔 — 순수 변환 (S6)
==============================================================================
설계: `docs/superpowers/specs/2026-08-28-investment-decision-layer-design.md` §2.3

S1~S5 가 만든 증거는 전부 **파이프라인이 돈다**는 것이었다. 이 모듈은 그 다음
질문을 여는 도구다 — ★뷰의 내용을 지우거나 뒤섞어도 같은 일이 일어나는가?★

| 팔 | 무엇을 뺐나 | 무엇을 가른다 |
|---|---|---|
| `company-on` | — | 기준 |
| `company-off` | 뷰 전체 | 뷰가 **뭐라도** 하는가 |
| ★`company-neutral`★ | **단면 변동만**(개수·자산은 유지) | 이득이 "뷰가 있다" 인가 "그 뷰의 내용" 인가 |
| ★`company-shuffled`★ | **자산↔내용 짝짓기만** | 어느 종목에 붙었는지가 중요한가 |
| `evidence-stripped` | 신뢰도(Ω 채널) | 불확실성이 **일을 하는가** |

★대조군이 넷인 이유는 하나로 부족하기 때문이다★ — `t3_transmission` 의
`-open`/`-const` 가 같은 이유로 둘이다. `off` 만 있으면 "뷰가 기여했다" 를 잘못
말하게 된다: 그 이득이 사실은 "무엇이든 뷰가 하나 있었다" 일 수 있고, 그것은
내용과 무관하게 얻어진다.

★이 모듈은 `company_views.py` 옆에 두지 않는다★ 그 파일은 프로덕션 배분 경로에
있다. 셔플러가 그 옆에 있으면 언젠가 한 줄 차이로 새어 들어간다. `src/api/` 가
이 모듈을 import 하지 않는다는 것을 **테스트가 정적으로 강제**한다 —
`OrderExecutor` 를 `trading_engine.py` 밖에서 못 만들게 하는 가드와 같은 장치다.

★전부 순수하다★ 입력 리스트도 그 안의 dict 도 변형하지 않는다. 제자리에서 고치면
`company-on` 팔이 통제 팔로 **조용히** 오염되고, 그 오염은 두 팔의 숫자가 같아진
뒤에야 보인다.
"""

from __future__ import annotations

import math
from itertools import permutations
from typing import Any

ARM_ON = "company-on"
ARM_OFF = "company-off"
ARM_NEUTRAL = "company-neutral"
ARM_SHUFFLED = "company-shuffled"
ARM_STRIPPED = "evidence-stripped"

#: 보고서가 도는 순서 — `off` 를 먼저 둬서 기준선이 먼저 서게 한다.
ARMS = (ARM_OFF, ARM_ON, ARM_NEUTRAL, ARM_SHUFFLED, ARM_STRIPPED)

#: 중립 팔의 방향. 부호까지 섞으면 "내용을 지웠다" 가 아니라 "다른 내용을 넣었다" 가 된다.
NEUTRAL_DIRECTION = 1

#: `build_user_views` 의 Idzorek 기본값 — 스케일 `(100−conf)/conf` 가 정확히 1.0 이
#: 되는 지점이다. ★새 상수를 고르지 않는다★ 신뢰도를 "지운다" 는 것은 저장소가
#: 이미 중립이라 부르는 값으로 되돌린다는 뜻이다.
DEFAULT_CONFIDENCE = 50.0

#: 팔 라벨이 들어가는 칸. 소비자(`build_view_rows`·`build_user_views`)는 읽지
#: 않으므로 계산을 바꾸지 않고, 보고서가 어느 팔의 뷰인지 되짚을 수 있게 한다.
ARM_KEY = "arm"


def _tag(views: list[dict], arm: str) -> list[dict]:
    """얕은 복사 + 팔 라벨. ★원본 dict 를 건드리지 않는다★"""
    return [{**v, ARM_KEY: arm} for v in views]


def neutralize(views: list[dict]) -> list[dict]:
    """내용을 상수로 — ★개수와 자산은 그대로 둔다★

    크기는 원래 크기들의 평균으로 통일한다(0 으로 만들면 `build_view_rows` 가
    "크기 0 인 뷰는 아무것도 주장하지 않는다" 며 **스킵**해 버려서 `off` 팔과
    구분되지 않는다 — 그러면 통제가 하나 사라진다).
    """
    if not views:
        return []
    mag = sum(abs(float(v.get("magnitude_pct") or 0.0)) for v in views) / len(views)
    return [{**v, "direction": NEUTRAL_DIRECTION, "magnitude_pct": mag,
             ARM_KEY: ARM_NEUTRAL} for v in views]


def shuffle_views(views: list[dict], perm: tuple[int, ...]) -> list[dict]:
    """(방향·크기·신뢰도) 삼중항을 자산 간 **치환**한다.

    ★재생성이 아니라 치환이다★ — 다중집합이 보존되어야 널이 "같은 내용, 다른
    배치" 를 뜻한다. 새로 뽑으면 크기 분포까지 달라져 두 가지가 한꺼번에 바뀐다.

    Raises:
        ValueError: 길이가 안 맞거나 **항등** 치환일 때. 항등을 널 표본으로 세면
            널이 진짜 팔로 오염된다.
    """
    n = len(views)
    if len(perm) != n:
        raise ValueError(f"치환 길이가 뷰 개수와 다릅니다: {len(perm)} != {n}")
    if sorted(perm) != list(range(n)):
        raise ValueError("치환이 아닙니다 — 인덱스가 한 번씩 나와야 합니다")
    if n and tuple(perm) == tuple(range(n)):
        raise ValueError("항등 치환은 널 표본이 아닙니다 — 진짜 팔과 같습니다")
    return [{**views[i],
             "direction": views[perm[i]]["direction"],
             "magnitude_pct": views[perm[i]]["magnitude_pct"],
             "confidence": views[perm[i]]["confidence"],
             ARM_KEY: ARM_SHUFFLED} for i in range(n)]


def strip_confidence(views: list[dict]) -> list[dict]:
    """신뢰도만 중립값으로 — 크기·방향·자산은 그대로.

    ★Ω 채널이 일을 하는지 묻는 팔이다.★ S4 가 예고했듯 mock 에서는 신뢰도가 전부
    포화해 같으므로 이 변환이 **아무것도 바꾸지 않는다** — 그 무등가가 결과이고,
    `is_inert()` 가 그것을 탐지한다.
    """
    return [{**v, "confidence": DEFAULT_CONFIDENCE, ARM_KEY: ARM_STRIPPED}
            for v in views]


def is_inert(before: list[dict], after: list[dict]) -> bool:
    """변환이 **아무것도 바꾸지 않았는가** — 계산에 쓰이는 칸만 본다.

    팔 라벨(`arm`)은 소비자가 읽지 않으므로 비교에서 뺀다. 이것이 참이면 두 팔의
    숫자가 같은 것이 **우연이 아니라 구조**라는 뜻이고, 보고서는 그 사실을
    `inert_channels` 로 신고해야 한다(같은 숫자를 조용히 두 번 싣지 않는다).
    """
    keys = ("assets", "weights", "direction", "magnitude_pct", "confidence")
    def shape(vs):
        return [tuple(str(v.get(k)) for k in keys) for v in vs]
    return shape(before) == shape(after)


def permutations_for(k: int, limit: int, rng) -> tuple[list[tuple[int, ...]], bool]:
    """널 표본으로 쓸 비항등 치환들 — `(치환 목록, 전수 여부)`.

    ★작은 유니버스에서 가짜 해상도를 만들지 않는다★ 뷰가 `k` 개면 비항등 치환은
    `k! − 1` 개뿐이다(k=3 → **5개**). 200번 뽑아 "분포" 라고 부르면 같은 값을 여러
    번 센 것이고, 분위가 실제보다 촘촘해 보인다. `k! − 1 ≤ limit` 이면 **전수
    열거**하고 그 사실을 함께 돌려준다.

    `k < 2` 면 셔플할 수 없다 → 빈 목록. ★널이 없다는 것을 빈 목록으로 말한다★ —
    없는 널을 지어내지 않는다.
    """
    if k < 2:
        return [], True
    total = math.factorial(k) - 1
    if total <= max(int(limit), 0):
        return [p for p in permutations(range(k)) if p != tuple(range(k))], True

    seen: list[tuple[int, ...]] = []
    uniq: set[tuple[int, ...]] = set()
    guard = 0
    while len(seen) < int(limit) and guard < int(limit) * 50 + 100:
        guard += 1
        p = tuple(int(i) for i in rng.permutation(k))
        if p == tuple(range(k)) or p in uniq:
            continue
        uniq.add(p)
        seen.append(p)
    return seen, False


def arm_views(views: list[dict], arm: str,
              perm: tuple[int, ...] | None = None) -> list[dict] | None:
    """팔 이름 → 그 팔이 `optimize(company_views=…)` 에 넘길 뷰 목록.

    `company-off` 는 `None` 이다 — 빈 목록이 아니라 **없음**이어야 상류가 뷰 경로를
    아예 타지 않는다.

    Raises:
        ValueError: 모르는 팔이거나, 셔플 팔인데 치환을 안 줬을 때. ★조용히
            `on` 으로 떨어지지 않는다★ — 그러면 통제 팔이 진짜 팔이 되고 보고서는
            "구분되지 않는다" 를 당연하게 만든다.
    """
    if arm == ARM_OFF:
        return None
    if arm == ARM_ON:
        return _tag(views, ARM_ON)
    if arm == ARM_NEUTRAL:
        return neutralize(views)
    if arm == ARM_STRIPPED:
        return strip_confidence(views)
    if arm == ARM_SHUFFLED:
        if perm is None:
            raise ValueError("셔플 팔에는 치환이 필요합니다 — 없으면 통제가 아닙니다")
        return shuffle_views(views, perm)
    raise ValueError(f"모르는 팔입니다: {arm!r} (가능: {', '.join(ARMS)})")


def signed_q(views: list[dict] | None) -> list[float]:
    """뷰의 부호 있는 크기 `direction × magnitude_pct` — 전달 상관의 x 축.

    ★`build_user_views` 와 같은 규약이다★(`q = direction × magnitude`). 실험이
    프로덕션과 다른 Q 를 쓰면 비교가 성립하지 않는다.
    """
    return [float(v.get("direction", 1)) * abs(float(v.get("magnitude_pct") or 0.0))
            for v in (views or [])]


def percentile_of(value: float, null: list[float] | Any) -> float | None:
    """진짜 팔이 널 분포의 **몇 분위**인가 (0~100). 널이 비면 `None`.

    ★"얼마나 큰가" 가 아니라 "널 안에서 어디인가" 를 묻는다★ — 그것이 음성 통제의
    질문이다.

    ★산수는 `null_stats` 가 단일 출처다★ 매크로 통제(M1~M5)가 같은 분위를 세 번째로
    구현하면 반드시 갈라지고, 갈라져도 타입 에러가 나지 않는다. 이 이름은 S6 의
    호출부(테스트 포함)를 위해 남는 얇은 위임이다.
    """
    from src.engine.null_stats import percentile_of as _impl
    return _impl(value, null)
