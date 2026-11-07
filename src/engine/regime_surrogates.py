"""국면 경로 ★서로게이트★ — 순수 변환 (M1)
==============================================================================
설계·사전등록: `docs/superpowers/specs/2026-08-29-macro-regime-negative-control-design.md`

`walk_forward(regime={"points": …})` 는 국면 경로를 **주입 가능한 입력**으로 받는다.
그래서 엔진을 한 줄도 고치지 않고 "라벨을 무작위로 다시 붙이면 같은 결과가 나오는가"
를 물을 수 있다 — S6 이 기업 뷰에 `company_views=` 로 물었던 것과 같은 seam 이다.

## ★실측이 이 모듈의 설계를 정했다★

실제 경로는 82개월에 런 26개(평균 3.15개월)로 **지속성**이 있다:

| 널 | Sharpe | 평균 회전율 | 런 수 |
|---|---|---|---|
| 실제 경로 | 0.420 | 8.52% | 26 |
| 순환이동 k=7/19/41 | 0.18~0.28 | 6.6~8.3% | **26~27** |
| ★단순 셔플★ | 0.22~0.27 | **11.5~13.1%** | **61~71** |

단순 셔플은 런을 2.5배로 쪼개 회전율을 1.4~1.5배로 올린다 → 널 팔이 **비용 때문에**
불리해진다. 그 상태로 "진짜가 낫다" 고 결론내면 ★정보가 아니라 지속성 파괴를 잰
것★이다. 그래서 **주 널은 순환이동**이다.

★정정★ 사전등록 초안은 순환이동이 "런 길이 다중집합을 정확히 보존" 한다고 적었는데
그것은 **틀렸다**. 선형 수열에서는 감싸인 런이 양끝으로 쪼개지므로 런 **수**가 최대
1 달라진다(실측 26 → 26~27). 정확히 보존되는 것은 **주변분포**이고, 회전율을
지키는 데는 런 수가 거의 같은 것으로 충분하다. 주 통계·임계·판정 규칙은 그대로다.

## 계약

- ★`t`(달)는 건드리지 않고 `regime` 라벨만 옮긴다★ — 시간 격자가 그대로여야
  `allocation_backtest._truncated_points` 가 같은 방식으로 자른다.
- ★항등(`k=0`)은 거부★ — 널 표본에 진짜 팔을 섞으면 널이 오염된다.
- ★전부 순수★ — 입력 리스트도 그 안의 dict 도 변형하지 않는다. 제자리에서 고치면
  진짜 팔이 널 팔로 **조용히** 오염되고, 그 오염은 두 팔의 숫자가 같아진 뒤에야
  보인다(S6 에서 같은 자리를 변이로 지켰다).
- ★보존 성질은 선언하지 않고 **잰다**★ — 상수표에 적으면 구현이 바뀌어도 표는
  그대로다. `preserved_properties(before, after)` 가 비교해서 답한다.

★이 모듈은 `src/api/` 가 import 하지 않는다★ — 테스트가 정적으로 강제한다.
서로게이트 경로가 프로덕션 결정에 닿는 길을 구조로 없앤다(S6 의 통제 모듈과 같은
장치이고, `OrderExecutor` 우회 방지 가드의 계보다).
"""

from __future__ import annotations

import itertools
import logging
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

MONTH_KEY = "t"
REGIME_KEY = "regime"
#: 어느 서로게이트가 만든 점인지 — 소비자(`walk_forward`)는 읽지 않는다.
SURROGATE_KEY = "surrogate"
BLOCK_KEY = "surrogate_block"

ARM_OFF = "regime-off"
ARM_ON = "regime-on"
ARM_ON_PROB = "regime-on-prob"
ARM_CONST = "regime-const"
#: 리포트가 도는 순서 — 벤치마크를 먼저 세운다.
ARMS = (ARM_OFF, ARM_ON, ARM_ON_PROB, ARM_CONST)

NULL_SHIFT = "shift"
NULL_MARKOV = "markov"
NULL_BLOCK = "block"
NULLS = (NULL_SHIFT, NULL_MARKOV, NULL_BLOCK)


# ── 관측 ────────────────────────────────────────────────────────────────────
def labels_of(points: list[dict]) -> list[str]:
    return [str(p.get(REGIME_KEY)) for p in points or []]


def run_lengths(points: list[dict]) -> list[int]:
    """연속으로 같은 국면이 이어진 길이들 — ★지속성의 관측치★"""
    return [len(list(g)) for _, g in itertools.groupby(labels_of(points))]


def n_runs(points: list[dict]) -> int:
    return len(run_lengths(points))


def marginal(points: list[dict]) -> dict[str, int]:
    """국면별 개월 수. 순환이동은 이것을 **정확히** 보존한다."""
    return dict(Counter(labels_of(points)))


def transition_matrix(points: list[dict]) -> dict[str, dict[str, float]]:
    """관측된 전이확률. 나가는 전이가 없는 상태는 **주변분포로** 채우고 그 사실을
    로그로 남긴다 — 조용히 균등분포를 지어내지 않는다."""
    labs = labels_of(points)
    states = sorted(set(labs))
    counts = {s: Counter() for s in states}
    for a, b in zip(labs, labs[1:], strict=False):
        counts[a][b] += 1
    marg = marginal(points)
    total_marg = sum(marg.values()) or 1
    out: dict[str, dict[str, float]] = {}
    for s in states:
        tot = sum(counts[s].values())
        if tot == 0:
            logger.info("국면 %s 에 나가는 전이가 없어 주변분포로 채웁니다", s)
            out[s] = {t: marg.get(t, 0) / total_marg for t in states}
        else:
            out[s] = {t: counts[s].get(t, 0) / tot for t in states}
    return out


def default_block(points: list[dict]) -> int:
    """블록 부트스트랩의 블록 길이 — ★관측된 평균 런 길이★ 에서 나온다.

    지어낸 상수가 아니다. 런이 평균 3.15개월이면 블록 3 이 그 지속성을 담는다.
    """
    rl = run_lengths(points)
    if not rl:
        return 1
    return max(1, int(round(sum(rl) / len(rl))))


def preserved_properties(before: list[dict], after: list[dict]) -> dict[str, Any]:
    """★선언이 아니라 측정★ — 이 서로게이트가 무엇을 지켰는가."""
    nb, na = n_runs(before), n_runs(after)
    return {
        "marginal_preserved": marginal(before) == marginal(after),
        "run_length_multiset_preserved": (sorted(run_lengths(before))
                                          == sorted(run_lengths(after))),
        "n_runs_before": nb, "n_runs_after": na, "run_count_delta": na - nb,
        "month_grid_preserved": ([p.get(MONTH_KEY) for p in before]
                                 == [p.get(MONTH_KEY) for p in after]),
    }


# ── 변환 ────────────────────────────────────────────────────────────────────
def _relabel(points: list[dict], labels: list[str], method: str,
             **extra: Any) -> list[dict]:
    """얕은 복사 + 라벨 교체. ★원본 dict 를 건드리지 않는다★"""
    return [{**p, REGIME_KEY: lab, SURROGATE_KEY: method, **extra}
            for p, lab in zip(points, labels, strict=True)]


def circular_shift(points: list[dict], k: int) -> list[dict]:
    """★주 널★ 라벨 수열을 `k` 만큼 순환 이동한다.

    주변분포는 **정확히** 보존되고 런 수는 최대 1 달라진다(감싸는 지점 하나만
    갈라진다). 깨지는 것은 **수익과의 정렬**뿐이다 — 그것이 널이 물어야 할 것이다.

    Raises:
        ValueError: `k` 가 항등이거나(0 또는 n의 배수) 경로가 2개월 미만일 때.
    """
    n = len(points)
    if n < 2:
        raise ValueError("경로가 2개월 미만이라 순환이동할 수 없습니다")
    if int(k) % n == 0:
        raise ValueError("항등 이동은 널 표본이 아닙니다 — 진짜 팔과 같습니다")
    k = int(k) % n
    labs = labels_of(points)
    return _relabel(points, labs[k:] + labs[:k], NULL_SHIFT)


def markov_surrogate(points: list[dict], rng) -> list[dict]:
    """관측된 전이행렬에서 같은 길이의 경로를 뽑는다 — 지속성을 **분포적으로** 보존."""
    n = len(points)
    if n == 0:
        return []
    tm = transition_matrix(points)
    marg = marginal(points)
    states = sorted(marg)
    p0 = [marg[s] / sum(marg.values()) for s in states]
    cur = str(rng.choice(states, p=p0))
    out = [cur]
    for _ in range(n - 1):
        row = tm[cur]
        nxt = [row.get(s, 0.0) for s in states]
        tot = sum(nxt)
        nxt = [x / tot for x in nxt] if tot > 0 else p0
        cur = str(rng.choice(states, p=nxt))
        out.append(cur)
    return _relabel(points, out, NULL_MARKOV)


def block_surrogate(points: list[dict], rng, block: int | None = None) -> list[dict]:
    """순환 블록 재표집 — 국소 지속성을 보존한 채 런 경계를 다시 그린다.

    블록 길이는 관측된 평균 런 길이(`default_block`)가 기본이고, 쓴 값을 점마다
    `surrogate_block` 으로 **신고**한다.
    """
    n = len(points)
    if n == 0:
        return []
    b = int(block or default_block(points))
    b = max(1, min(b, n))
    labs = labels_of(points)
    out: list[str] = []
    while len(out) < n:
        start = int(rng.integers(0, n))
        out.extend(labs[(start + i) % n] for i in range(b))
    return _relabel(points, out[:n], NULL_BLOCK, **{BLOCK_KEY: b})


def constant_path(points: list[dict], label: str | None = None) -> list[dict]:
    """★타이밍을 전부 없애고 수준만 남긴다★ — `t3_transmission` 의 `-const` 와 같은 이유.

    이 대조군이 없으면 "국면이 기여했다" 를 잘못 말하게 된다: 이득이 사실은 그 규칙이
    고른 **수준**일 수 있고, 그것은 국면 타이밍과 무관하게 상수로도 얻어진다.
    기본 라벨은 **최빈 국면**이다(첫 라벨이 아니다 — 시작점 우연에 기대지 않는다).
    ★동률이면 라벨 사전순 첫 번째★ — 픽스처에서 실제로 3중 동률이 나왔고, 규칙을
    적어 두지 않으면 사전 순서·삽입 순서 같은 우연에 결과가 달라진다.
    """
    if not points:
        return []
    marg = marginal(points)
    lab = str(label) if label else sorted(marg.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return _relabel(points, [lab] * len(points), ARM_CONST)


def surrogate_path(points: list[dict], method: str, rng,
                   k: int | None = None, block: int | None = None) -> list[dict]:
    """방법 이름 → 서로게이트 경로. ★모르는 이름은 거부★

    조용히 원본으로 떨어지면 널이 진짜 팔이 되고, 리포트는 "구분되지 않는다" 를
    당연하게 만든다.
    """
    if method == NULL_SHIFT:
        if k is None:
            raise ValueError("순환이동에는 `k` 가 필요합니다 — 없으면 통제가 아닙니다")
        return circular_shift(points, k)
    if method == NULL_MARKOV:
        return markov_surrogate(points, rng)
    if method == NULL_BLOCK:
        return block_surrogate(points, rng, block)
    if method == ARM_CONST:
        return constant_path(points)
    raise ValueError(f"모르는 서로게이트입니다: {method!r} "
                     f"(가능: {', '.join((*NULLS, ARM_CONST))})")


def shifts_for(n: int, limit: int, rng) -> tuple[list[int], bool]:
    """널 표본으로 쓸 이동량들 — `(k 목록, 전수 여부)`.

    ★작은 경로에서 가짜 해상도를 만들지 않는다★ 길이 `n` 이면 비항등 이동은
    `n−1` 개뿐이다. 전부 들어가면 **전수**이고 그 사실을 함께 돌려준다.
    `n < 2` 면 이동할 수 없다 → 빈 목록(★없는 널을 지어내지 않는다★).
    """
    if n < 2:
        return [], True
    all_k = list(range(1, n))
    if len(all_k) <= max(int(limit), 0):
        return all_k, True
    picked = rng.choice(all_k, size=int(limit), replace=False)
    return sorted(int(x) for x in picked), False
