"""T3 — 매크로 전달 아키텍처 비교 (설계 + 합성 실험 전용)
==============================================================================
전달계층 감사(`docs/specs/2026-08-25-transmission-layer-audit.md`)가 찾은 것:
★국면 신호는 **타이밍**(공통인자의 평균/분산을 바꾼다)인데, 전달은 **자산별 절대
뷰**(단면 장치)다.★ 그 형태 불일치가 존재하지 않는 종목 간 차이를 매달 쫓게 만들고
회전율 32%를 만든다.

## 팔

| 팔 | 국면이 말하는 것 | μ 사용 | 최적화기 계열 |
|---|---|---|---|
| **T3-A** | 자산별 **절대** μ 뷰 ← ★현행 baseline★ | 예 | 뷰 → BL/EP → MVO |
| **T3-B** | 자산군 **상대** 뷰 | 예 | 〃 |
| **T3-C** | **팩터 수준** 뷰 (`β` 정규화, 행합 ≈ 1) | 예 | 〃 |
| **T3-C-rel** | **팩터 상대** 뷰 (`β−β̄` 정규화, 행합 ≈ 0) | 예 | 〃 |
| **T3-D1** | 자산군 **리스크 예산** | ★아니오★ | 공분산 전용 |
| **T3-D2** | 자산군 **노출 한도** | ★아니오★ | 공분산 전용 |

D 계열에는 대조군이 **둘** 있다 — 하나로는 부족하기 때문이다:

| 대조군 | 무엇을 뺐나 | 무엇을 가른다 |
|---|---|---|
| `-open` | 규칙 전체 | 이 규칙이 **뭐라도** 하는가 |
| ★`-const`★ | **국면 변동만** (첫 리밸런싱 값으로 고정) | 이득이 **국면 타이밍**인가 아니면 그 규칙이 고른 **수준**인가 |

★`-const` 가 없으면 "국면이 기여했다" 를 잘못 말하게 된다★ 예컨대 노출 한도의
이득이 사실은 "EQ 를 조금이라도 들고 있게 만든 하한" 일 수 있고, 그것은 국면과
무관하게 상수로도 얻어진다. D 는 A/B/C 와 최적화기 계열이 달라 직접 비교가
성립하지 않으므로, 판단은 **자기 대조군 대비**로만 한다.

## 두 엔진

- **BL** `bl_posterior` — 사전분포는 균형 `Π = δΣw_mkt`. 신뢰도(Ω)가 있다.
- **EP** `ep_posterior_mu` — 사전분포는 시나리오 균등가중(=트레일링 평균).
  ★신뢰도 축이 없다★(`confidence_used: False`) — 결측이 아니라 아키텍처 사실이다.
  그리고 EP 는 **부등식**이라 뷰가 이미 만족되면 아무것도 하지 않는다.

★그래서 BL 과 EP 의 **레벨을 비교하지 않는다**★ 사전분포가 다르다. 비교는 언제나
*한 엔진 안에서* 팔끼리다.

## 뷰 행은 프로덕션 빌더가 만든다

`build_view_rows`(`src/engine/view_rows.py`)를 **두 엔진 모두** 통과시킨다 — 실험이
프로덕션과 다른 P 행을 쓰는 일이 없게. `_omega` 는 `build_user_views` 와 같은
`scale = (100−conf)/conf` 규약을 그대로 쓴다(규약을 바꿔 이기는 실험 금지).

사용:
    python3 scripts/t3_transmission.py                       # BL · A/B/C
    python3 scripts/t3_transmission.py --engine both --conf 25
    python3 scripts/t3_transmission.py --arch T3-C,T3-C-rel --conf 25
    python3 scripts/t3_transmission.py --arch D                # D 계열 + 대조군
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from typing import Any

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engine.allocation_backtest import (  # noqa: E402
    _month_of,
    _rebalance_indices,
    _truncated_points,
)
from src.engine.allocation_studio import (  # noqa: E402
    DELTA_DEFAULT,
    TAU_DEFAULT,
    bl_posterior,
)
from src.engine.conditional_market import (  # noqa: E402
    conditional_moments,
    implied_confidence,
    regime_by_month_from_path,
    regime_mixture_moments,
    resolve_shrinkage_lambda,
    view_omega_terms,
)
from src.engine.constrained_opt import Constraints, constrained_solve  # noqa: E402
from src.engine.entropy_views import ep_posterior_mu  # noqa: E402
from src.engine.regime_probability import from_posterior_mean_path  # noqa: E402
from src.engine.regime_transitions import (  # noqa: E402
    REGIMES,
    count_transitions,
    transition_posterior,
)
from src.engine.sleeve_combine import _risk_budget_weights  # noqa: E402
from src.engine.view_rows import build_view_rows  # noqa: E402

#: μ 뷰를 만드는 팔 — BL·EP 두 엔진 모두에서 돌릴 수 있다.
ARCH_VIEW = ("T3-A", "T3-B", "T3-C", "T3-C-rel")
#: ★뷰가 없는 팔★ — EP 의 **사전분포만**으로 배분한다. 뷰를 주지 않으면 사후=사전
#: 이므로, 이 팔의 회전율은 곧 "트레일링 평균이 움직여서 생긴 거래" 다.
#: BL 의 `Π` 같은 정적 앵커가 EP 에 없다는 것을 **수치로** 분해한다
#: (0e655c7 의 미해결 관찰: 뷰가 37% 침묵인데 회전율은 26%).
ARCH_PRIOR_ONLY = "EP-prior-only"
#: ★μ 를 아예 읽지 않는 팔★ — 국면 → 리스크 예산 / 노출 한도. 엔진 개념이 없다.
ARCH_BUDGET = ("T3-D1", "T3-D1-open", "T3-D1-const",
               "T3-D2", "T3-D2-open", "T3-D2-const")
ARCH_ALL = ARCH_VIEW + (ARCH_PRIOR_ONLY,) + ARCH_BUDGET
DEFAULT_ARCH = ("T3-A", "T3-B", "T3-C")
ENGINES = ("bl", "ep")
COSTS = (0.0, 10.0, 30.0)
RF = 0.035

#: `kl` 이 이보다 작으면 EP 사후 = 사전, 즉 **뷰가 아무 일도 하지 않았다**.
EP_INACTIVE_KL = 1e-9
#: 노출 한도의 하한 — 국면이 아무리 나빠도 한 자산군을 0 으로 만들지 않는다.
CAP_FLOOR = 0.15

# ── 증거 등급 ────────────────────────────────────────────────────────────────
# ★등급을 올려 적지 않는다★ 이 스크립트가 내는 모든 수치는 합성 패널에서 나온다.
# 구조적 사실(행합·계약 형태)만 `structural` 이고, Sharpe·CE·CVaR 는 전부
# `synthetic_mechanism` 이다 — 경제적 가치의 증거가 아니다.
EVIDENCE_STRUCTURAL = "structural"
EVIDENCE_SYNTHETIC = "synthetic_mechanism"
EVIDENCE_REAL_FORECAST = "real_forecast"
EVIDENCE_REAL_ECONOMIC = "real_economic"

#: 제약 종류 — 감사행이 "무엇을 건 것인지" 를 값으로 말한다.
CONSTRAINT_RISK_BUDGET = "risk_budget"
CONSTRAINT_GROUP_BOUNDS = "group_bounds"

#: 국면 의존성 — `dynamic` 불리언 하나로는 `-open`(규칙 없음)과
#: `-const`(규칙 있고 얼림)를 구분할 수 없다. 셋을 값으로 가른다.
REGIME_PER_REBALANCE = "per_rebalance"
REGIME_FROZEN = "frozen_at_first_rebalance"
REGIME_NONE = "none"

# ── 합성 패널 ────────────────────────────────────────────────────────────────
# ★국면이 자산군을 가르도록 만든다★ 앞선 패널은 국면이 **공통인자 하나**만 바꿔서
# 자산군 간 차이가 없었고, 그러면 어떤 전달 형태를 써도 같은 결론이 나온다. 여기서는
# 국면이 (i) 공통인자 드리프트·변동성 **그리고** (ii) 두 자산군의 상대 성과를 함께
# 바꾼다 — 실제 매크로 국면이 하는 일에 가깝고, 세 아키텍처를 구분할 수 있다.
CLASSES = {"EQ": [0, 1, 2], "FI": [3, 4, 5]}
_PROF = {  # 국면: (공통 드리프트, 공통 변동성, EQ 틸트, FI 틸트, 특이 변동성)
    "Goldilocks":   (0.00075, 0.010, +0.00040, -0.00020, 0.0035),
    "Reflation":    (0.00035, 0.013, +0.00025, -0.00035, 0.0045),
    "Stagflation":  (-0.00070, 0.017, -0.00055, +0.00030, 0.0060),
    "Disinflation": (0.00020, 0.010, -0.00015, +0.00045, 0.0040),
}
_P_TRUE = np.array([[0.75, 0.10, 0.05, 0.10],
                    [0.15, 0.65, 0.15, 0.05],
                    [0.10, 0.15, 0.65, 0.10],
                    [0.15, 0.05, 0.10, 0.70]])


def build_panel(months: int = 84, seed: int = 20260825):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-02", periods=months * 21, freq="C")
    names = [f"EQ{i}" for i in range(3)] + [f"FI{i}" for i in range(3)]
    beta = np.array([1.25, 1.00, 0.80, 0.35, 0.25, 0.15])   # 자산군별 공통인자 노출
    seen: list[str] = []
    for ts in idx:
        mo = ts.strftime("%Y-%m")
        if mo not in seen:
            seen.append(mo)
    labels, cur = [], 0
    for _ in seen:
        labels.append(REGIMES[cur])
        cur = int(rng.choice(4, p=_P_TRUE[cur]))
    by_month = dict(zip(seen, labels, strict=True))

    rows = []
    for ts in idx:
        mu_f, sd_f, eq_t, fi_t, iv = _PROF[by_month[ts.strftime("%Y-%m")]]
        f = rng.normal(mu_f, sd_f)
        tilt = np.array([eq_t] * 3 + [fi_t] * 3)
        rows.append(f * beta + tilt + rng.normal(0.0, iv, 6))
    points = [{"t": m, "growth": 0.0, "inflation": 0.0, "regime": by_month[m]}
              for m in seen]
    return names, np.array(rows), list(idx), points, beta


def class_of(names: list[str]) -> dict[str, str]:
    """★합성 패널 전용 자산군 맵★

    실제 유니버스에는 이런 맵이 **없다** — `constrained_opt.sector_groups_for` 는
    genport **섹터**를 주고 실패하면 조용히 `{}` 를 돌린다. 정준 자산군 분류는
    별개의 데이터 계약이다(결정 메모 §5). 여기서는 티커 접두사가 진실이다.
    """
    return {nm: ("EQ" if nm.startswith("EQ") else "FI") for nm in names}


# ── 전달 아키텍처: 조건부 μ → **뷰 딕셔너리** ────────────────────────────────
# ★행을 손으로 만들지 않는다★ 뷰를 프로덕션 스키마(`assets` | `weights` +
# `direction` + `magnitude_pct`)로 표현하고, `build_view_rows` 가 P 행을 만든다.
# 그래야 BL 과 EP 가 **같은 행**을 본다.
def _signed_view(weights: dict[str, float], mu_row: float) -> dict:
    """부호 있는 가중치 + 그 행이 주장하는 값 → 뷰 딕셔너리.

    ★부호를 한 곳에만 넣는다★ 크기는 `|row·μ|`, 방향은 그 부호다. 가중치와
    `direction` 양쪽에 부호를 넣으면 상쇄된다(`view_rows` 계약).
    """
    return {"weights": weights, "direction": 1 if mu_row >= 0 else -1,
            "magnitude_pct": abs(mu_row) * 100.0}


def views_absolute(mu, names, beta) -> list[dict]:
    """★T3-A (현행 baseline)★ 자산마다 절대 뷰 — P 행이 `e_i`, 뷰 N개."""
    return [{"assets": [nm], "direction": 1 if m >= 0 else -1,
             "magnitude_pct": abs(float(m)) * 100.0}
            for nm, m in zip(names, np.asarray(mu, float), strict=True)]


def views_relative_class(mu, names, beta) -> list[dict]:
    """★T3-B★ 자산군 **상대** 뷰 — `(+1/n_EQ … −1/n_FI)`, 뷰 1개.

    공통 수준(타이밍 성분)은 상대 뷰에서 **상쇄**되므로, 이 아키텍처는 국면이
    말하는 **자산군 간 차이만** 전달하고 수준 추정잡음은 흘려보내지 않는다.
    """
    cls = class_of(names)
    eq = [nm for nm in names if cls[nm] == "EQ"]
    fi = [nm for nm in names if cls[nm] == "FI"]
    w = {nm: 1.0 / len(eq) for nm in eq}
    w.update({nm: -1.0 / len(fi) for nm in fi})
    row = np.array([w.get(nm, 0.0) for nm in names])
    return [_signed_view(w, float(row @ np.asarray(mu, float)))]


def _factor_row_level(beta: np.ndarray) -> np.ndarray:
    """★T3-C★ **팩터 수준** 행 — `β/Σ|β|`. β 가 전부 양수라 **행합 ≈ 1**.

    행합이 1 이면 이 뷰는 "예산 전체가 z% 낸다" 는 **수준 주장**이다. 롱온리·
    완전투자(Σw=1)에서 예산은 이미 고정이라 최적화기에 **레버가 없다**.
    """
    b = np.asarray(beta, float)
    return b / max(float(np.abs(b).sum()), 1e-12)


def _factor_row_relative(beta: np.ndarray) -> np.ndarray:
    """★T3-C-rel★ **팩터 상대** 행 — `(β−β̄)/Σ|β−β̄|`. **행합 ≈ 0**.

    ★항목 6 의 핵심★ 같은 팩터 신호를 **수준이 아니라 틸트**로 말한다. 고β 대 저β
    스프레드는 예산을 늘리지 않고 **예산 안에서** 표현되므로, 그로스 레버 없이도
    롱온리 완전투자 포트폴리오가 반응할 수 있다 — 그것이 사실인지가 이 팔의 질문이다.
    """
    b = np.asarray(beta, float)
    d = b - b.mean()
    return d / max(float(np.abs(d).sum()), 1e-12)


def _factor_views(row: np.ndarray, mu, names) -> list[dict]:
    w = {nm: float(v) for nm, v in zip(names, row, strict=True) if abs(v) > 0.0}
    return [_signed_view(w, float(row @ np.asarray(mu, float)))]


def views_factor_level(mu, names, beta) -> list[dict]:
    return _factor_views(_factor_row_level(beta), mu, names)


def views_factor_relative(mu, names, beta) -> list[dict]:
    return _factor_views(_factor_row_relative(beta), mu, names)


def views_none(mu, names, beta) -> list[dict]:
    """★뷰 없음★ — EP 사전분포만. `ep_posterior_mu` 는 이때 사후=사전을 낸다."""
    return []


_VIEWS = {"T3-A": views_absolute, "T3-B": views_relative_class,
          "T3-C": views_factor_level, "T3-C-rel": views_factor_relative,
          ARCH_PRIOR_ONLY: views_none}


# ── 국면 → 리스크 예산 / 노출 한도 (T3-D, μ 를 읽지 않는다) ──────────────────
def _class_vol(sigma: np.ndarray, names: list[str], cls: dict[str, str],
               g: str) -> float:
    """그 자산군의 **등가중 포트폴리오** 조건부 변동성 — 자산 하나가 아니라 군."""
    ix = [i for i, nm in enumerate(names) if cls[nm] == g]
    w = np.zeros(len(names))
    w[ix] = 1.0 / max(len(ix), 1)
    return math.sqrt(max(float(w @ sigma @ w), 1e-16))


def regime_risk_budget(sigma: np.ndarray, names: list[str], *,
                       flat: bool = False) -> np.ndarray:
    """★T3-D1★ 국면 조건부 Σ → 자산군 리스크 예산 `b ∝ 1/σ_class`.

    ★μ 를 읽지 않는다★ 국면은 "무엇이 오를까" 가 아니라 "어디에 리스크를 둘까" 를
    말한다. 국면에서 변동성이 튀는 자산군의 예산이 줄어든다.

    `flat=True` 는 **대조군** — 등예산(=리스크 패리티). 국면 정보가 0 이다.
    """
    cls = class_of(names)
    groups: dict[str, list[int]] = {}
    for i, nm in enumerate(names):
        groups.setdefault(cls[nm], []).append(i)
    b = np.zeros(len(names))
    if flat:
        for ix in groups.values():
            for i in ix:
                b[i] = 1.0
    else:
        inv = {g: 1.0 / _class_vol(sigma, names, cls, g) for g in groups}
        tot = sum(inv.values()) or 1.0
        for g, ix in groups.items():
            for i in ix:
                b[i] = (inv[g] / tot) / len(ix)
    return b / max(b.sum(), 1e-12)


def regime_group_caps(sigma: np.ndarray, sigma_uncond: np.ndarray,
                      names: list[str], *, open_: bool = False
                      ) -> dict[str, float]:
    """★T3-D2★ 국면 조건부 Σ vs 무조건부 Σ → 자산군 **상한%**.

    `cap_g = 100 · clip(σ_uncond,g / σ_cond,g, CAP_FLOOR, 1)` — 그 자산군의
    변동성이 국면에서 평소보다 높으면 상한이 내려간다. ★μ 를 읽지 않는다★

    ★계약 공백을 여기서 만난다★ `Constraints` 에는 그룹 **상한만 있고 하한이 없다.**
    "Stagflation 이면 FI 최소 40%" 는 자산군이 **둘이고 완전투자일 때만** 상대편
    상한으로 우회 가능하다(EQ ≤ 60%). 셋 이상이면 표현할 수 없다.

    상한 합이 100 미만이면 완전투자가 불가능해지므로 비례 확대한다 — 그 확대 자체가
    "하한이 없어서 생긴 우회" 라는 증거다.

    `open_=True` 는 **대조군** — 한도 없음.
    """
    if open_:
        return {}
    cls = class_of(names)
    caps: dict[str, float] = {}
    for g in sorted(set(cls.values())):
        sc = _class_vol(sigma, names, cls, g)
        su = _class_vol(sigma_uncond, names, cls, g)
        caps[g] = 100.0 * min(1.0, max(CAP_FLOOR, su / max(sc, 1e-12)))
    tot = sum(caps.values())
    if tot < 100.0:                       # ★완전투자를 지킬 만큼 비례 확대★
        caps = {g: c * (100.0 / tot) for g, c in caps.items()}
    return caps


# ── ★제약 구성의 단일 출처★ — `-const` 는 제2 구현이 아니다 ──────────────────
# 요구: "`-const` 는 동적 팔과 **정확히 같은 제약 구성**을 쓰되 국면 의존 상태만
# 얼린다." 그러려면 제약을 만드는 곳이 **하나**여야 하고, 두 팔의 차이는 그 함수를
# **언제 부르는가**뿐이어야 한다. 감사행의 `source` 가 그 사실을 값으로 증언한다.
#
# ★`-const` 가 얼리는 것의 정의★ 두 요구가 긴장한다 — "국면 의존 상태만 얼린다" 와
# "모든 리밸런싱에서 진짜 상수". 상한 규칙이 `σ_uncond/σ_cond` 라 σ_cond 만 얼리면
# 상한이 σ_uncond 를 따라 계속 움직여 두 번째를 깬다. 그래서:
#
#   **`-const` 는 제약 구성 입력 전체를 첫 적용 리밸런싱 시점에 얼린다.**
#   **제약 *객체*가 상수다. 비중은 여전히 움직일 수 있다** — Σ 추정은 모든 팔의
#   공통 입력이지 제약이 아니다(측정: D1-const EQ범위 0.047 · D2-const 0.000).
#
# 이것을 감사 필드에 적는 이유는 "상수 팔인데 비중이 움직인다" 를 결함으로 오독하지
# 않게 하기 위해서다.
@dataclass(frozen=True)
class ConstraintSpec:
    """한 리밸런싱에서 최적화기에 거는 제약 — frozen 이라 소비자가 못 고친다."""

    kind: str                                   # risk_budget | group_bounds
    source: str                                 # ★생성 함수 이름 — 두 팔이 같아야 한다★
    regime_informed: bool                       # `-open` 이면 False
    #: 자산 순 리스크 예산 (D1 전용). D2 는 None.
    budget: tuple[float, ...] | None = None
    #: ★그룹 → (하한%, 상한%)★ 하한은 지금 언제나 0 이고, 그 0 이 화면에 계속
    #: 보이는 것이 `Constraints` 에 그룹 하한이 없다는 계약 공백의 상시 증거다.
    bounds: tuple[tuple[str, float, float], ...] = ()

    def key(self) -> tuple:
        """distinct 를 셀 수 있는 해시 가능한 표현 — `-const` 상수성 판정용."""
        b = tuple(round(x, 12) for x in (self.budget or ()))
        return (self.kind, self.source, self.regime_informed, b,
                tuple((g, round(lo, 12), round(hi, 12)) for g, lo, hi in self.bounds))

    def bounds_dict(self) -> dict[str, tuple[float, float]]:
        return {g: (lo, hi) for g, lo, hi in self.bounds}

    def budget_by_group(self, names: list[str]) -> dict[str, float] | None:
        """자산 순 예산 → 그룹 합. D2 는 None.

        ★D1 의 감사행에 이것이 없으면 감사가 공허하다★ D1 은 그룹 경계가 언제나
        `(0, 100)` 이라 `effective_bounds` 만으로는 세 팔이 구분되지 않는다 —
        실제로 건 것은 **예산**이다.
        """
        if self.budget is None:
            return None
        cls = class_of(names)
        out: dict[str, float] = {}
        for w, nm in zip(self.budget, names, strict=True):
            out[cls[nm]] = out.get(cls[nm], 0.0) + float(w)
        return out

    def caps_pct(self) -> dict[str, float]:
        """`Constraints.group_caps_pct` 로 넘길 상한만 — 100% 는 걸지 않는다."""
        return {g: hi for g, _lo, hi in self.bounds if hi < 100.0}


def build_constraint(family: str, sigma: np.ndarray, sigma_uncond: np.ndarray,
                     names: list[str], *, regime_informed: bool) -> ConstraintSpec:
    """★D 계열 제약의 유일한 생성기★ 세 팔(-open/-const/-regime)이 전부 여기를 탄다.

    Args:
        family: `"D1"`(리스크 예산) 또는 `"D2"`(노출 한도).
        regime_informed: `False` 면 국면 정보를 **빼고** 같은 계열의 규칙을 쓴다
            (D1 → 등예산 = 리스크 패리티 · D2 → 한도 없음). 이것이 `-open` 이다.
    """
    groups = sorted(set(class_of(names).values()))
    if family == "D1":
        b = regime_risk_budget(sigma, names, flat=not regime_informed)
        return ConstraintSpec(
            kind=CONSTRAINT_RISK_BUDGET, source="regime_risk_budget",
            regime_informed=regime_informed, budget=tuple(float(x) for x in b),
            bounds=tuple((g, 0.0, 100.0) for g in groups))
    caps = regime_group_caps(sigma, sigma_uncond, names,
                             open_=not regime_informed)
    return ConstraintSpec(
        kind=CONSTRAINT_GROUP_BOUNDS, source="regime_group_caps",
        regime_informed=regime_informed, budget=None,
        bounds=tuple((g, 0.0, float(caps.get(g, 100.0))) for g in groups))


def constraint_audit_row(spec: ConstraintSpec, *, month: str, const: bool,
                         frozen_at: str | None, weights: np.ndarray | None,
                         names: list[str]) -> dict[str, Any]:
    """감사행 — ★제약의 출처·정적여부·국면의존성·유효경계를 값으로 낸다★

    `dynamic` 불리언 **하나로는 부족하다** — `-open`(규칙 없음)과 `-const`(규칙
    있고 얼림)가 둘 다 "정적" 이라 구분되지 않는다. `regime_dependency` 가 셋을 가른다.
    """
    cls = class_of(names)
    binding: list[str] = []
    if weights is not None:
        for g, _lo, hi in spec.bounds:
            share = 100.0 * float(sum(w for w, nm in zip(weights, names, strict=True)
                                      if cls[nm] == g))
            if hi < 100.0 and share >= hi - 0.5:
                binding.append(g)
    return {
        "t": month,
        "source": spec.source,
        "kind": spec.kind,
        "dynamic": not const,
        "regime_dependency": (REGIME_FROZEN if const
                              else REGIME_PER_REBALANCE if spec.regime_informed
                              else REGIME_NONE),
        "frozen_at": frozen_at,
        "effective_bounds": spec.bounds_dict(),
        "risk_budget_by_group": spec.budget_by_group(names),
        # ★서명★ 제약 하나를 해시 가능한 한 값으로 — `-const` 의 상수성과
        # `-open` 과의 차이를 **한 필드로** 셀 수 있게 한다(테스트가 두 종류의
        # 비교 코드를 갖지 않도록).
        "signature": repr(spec.key()),
        "binding": binding,
        # ★이 줄이 등급 승격을 막는다★ 감사행 하나하나가 자기 등급을 들고 다닌다.
        "evidence_grade": EVIDENCE_SYNTHETIC,
    }


def _equilibrium(sigma: np.ndarray, w_mkt: np.ndarray, delta: float) -> np.ndarray:
    """역최적화 균형 기대수익 `Π = δ Σ w_mkt` — BL 의 사전분포."""
    return delta * sigma @ w_mkt


def _omega(P: np.ndarray, tau_sigma: np.ndarray, conf: float) -> np.ndarray:
    """`build_user_views` 와 **같은 규약** — 규약을 바꿔 이기는 실험이 되지 않게."""
    scale = (100.0 - conf) / max(conf, 1.0)
    base = np.maximum(np.diag(P @ tau_sigma @ P.T), 1e-10)
    return np.diag(base * max(scale, 1e-4)) + np.eye(P.shape[0]) * 1e-10


def _min_var_long_only(S: np.ndarray, mu: np.ndarray, delta: float) -> np.ndarray:
    """평균-분산 롱온리 (합=1). `allocation_studio` 와 같은 SLSQP 규약."""
    from scipy.optimize import minimize
    n = len(mu)
    r = minimize(lambda w: -(w @ mu - 0.5 * delta * w @ S @ w),
                 np.ones(n) / n, method="SLSQP", bounds=[(0.0, 1.0)] * n,
                 constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}])
    w = np.asarray(r.x, float)
    return w / max(w.sum(), 1e-12)


def pq_from_views(views: list[dict], names: list[str], sigma: np.ndarray,
                  conf: float, tau: float):
    """뷰 딕셔너리 → `(P, Q, Ω)`. ★행은 프로덕션 빌더가 만든다★"""
    rows, skipped = build_view_rows(views, names)
    if not rows:
        return None, None, None, skipped
    P = np.vstack([r.row for r in rows])
    Q = np.array([r.direction * r.magnitude for r in rows], dtype=float)
    return P, Q, _omega(P, tau * sigma, conf), skipped


# ── 실행 ────────────────────────────────────────────────────────────────────
def run_arch(arch: str, names, R, dates, points, beta, *, min_train=252,
             delta=DELTA_DEFAULT, tau=TAU_DEFAULT, conf_override=None,
             engine: str = "bl"):
    """한 아키텍처의 walk-forward — 매 리밸런싱에서 절단 경로만 본다."""
    is_budget = arch in ARCH_BUDGET
    rb = _rebalance_indices(list(dates), "M", min_train)
    n = len(names)
    w_mkt = np.ones(n) / n
    rec = {"w": [], "view_disp": [], "post_disp": [], "conf": [],
           "months": [], "applied": 0, "timing_view": [], "fwd_factor": [],
           "ep_inactive": 0, "ep_infeasible": 0, "ep_kl": [],
           "caps": [], "budget_eq": [], "engine": engine, "arch": arch,
           # ★리밸런싱마다 한 줄 — 제약이 어디서 왔고 얼려졌는지가 기록에 남는다★
           "constraint_audit": [],
           "evidence_grade": EVIDENCE_SYNTHETIC,
           "uses_mu": not is_budget}
    #: `-const` 팔이 첫 리밸런싱 값을 얼려 두는 곳.
    frozen: dict[str, object] = {}

    def _blank(t):
        rec["w"].append(None)
        rec["months"].append(_month_of(dates[t]))

    for t in rb:
        R_win = R[:t]
        df = pd.DataFrame(R_win, index=pd.DatetimeIndex(dates[:t]), columns=names)
        pts = _truncated_points(points, _month_of(dates[t]))
        if len(pts) < 2:
            _blank(t); continue
        by_month, _ = regime_by_month_from_path(pts)
        cur = pts[-1]["regime"]
        rows = transition_posterior(count_transitions(pts))
        probs, Pm = from_posterior_mean_path(rows, cur, 1, list(REGIMES),
                                             mode="backtest")
        cond = regime_mixture_moments(df, by_month, [p.probs for p in probs], Pm,
                                      list(REGIMES), h_hold=1)
        if not cond.get("available"):
            cond = conditional_moments(df, by_month, cur)
        if not cond.get("available"):
            _blank(t); continue

        mu = np.asarray(cond["mu"], float)
        sigma = np.asarray(cond["sigma"], float)

        # ── T3-D: μ 를 아예 만지지 않는 경로 ────────────────────────────────
        if is_budget:
            # ★세 팔이 **같은 생성기**를 탄다★ 차이는 그것을 *언제 부르는가* 뿐이다.
            #   -open   : 국면 정보를 뺀 같은 계열 규칙 (regime_informed=False)
            #   -const  : 같은 규칙, 첫 적용 리밸런싱에서 **입력 전체를 얼림**
            #   (기본)  : 매 리밸런싱 재구성
            const = arch.endswith("-const")
            family = "D1" if arch.startswith("T3-D1") else "D2"
            month = _month_of(dates[t])
            if const and frozen.get("spec") is not None:
                spec = frozen["spec"]
            else:
                spec = build_constraint(
                    family, sigma, np.cov(R_win.T) * 252.0, names,
                    regime_informed=not arch.endswith("-open"))
                if const:
                    frozen["spec"], frozen["at"] = spec, month
            frozen_at = frozen.get("at") if const else None

            if spec.kind == CONSTRAINT_RISK_BUDGET:
                b = np.asarray(spec.budget, float)
                w = _risk_budget_weights(sigma, b)
                rec["budget_eq"].append(float(sum(
                    b[i] for i, nm in enumerate(names) if nm.startswith("EQ"))))
            else:
                res = constrained_solve(
                    "min_var", names, R_win, np.zeros(n), sigma,
                    Constraints(group_caps_pct=spec.caps_pct()),
                    groups_of=class_of(names))
                wl = res.get("weights")
                if wl is None:
                    _blank(t); continue
                w = np.array([float(wl.get(nm, 0.0)) for nm in names]) \
                    if isinstance(wl, dict) else np.asarray(wl, float)
                w = np.maximum(w, 0.0)
                w = w / max(w.sum(), 1e-12)
                rec["caps"].append(spec.bounds_dict().get("EQ", (0.0, 100.0))[1])
            rec["constraint_audit"].append(constraint_audit_row(
                spec, month=month, const=const, frozen_at=frozen_at,
                weights=w, names=names))
            rec["w"].append(w)
            rec["months"].append(month)
            rec["applied"] += 1
            continue

        # ── T3-A/B/C: 국면 → μ 뷰 → BL 또는 EP ─────────────────────────────
        # ★신뢰도는 분해 Ω 로 — 모든 팔에 **같은 규칙**을 적용한다★
        A, W, h = cond.get("A_h"), cond.get("W_h"), int(cond.get("h_hold") or 1)
        if A is not None and W is not None:
            ann = 12.0 / h
            rg = np.maximum(np.diag(np.asarray(A, float) * ann), 0.0)
            wi = np.maximum(np.diag(np.asarray(W, float) * ann), 0.0)
        else:
            rg, wi = np.zeros(n), np.maximum(np.diag(sigma), 0.0)
        months = cond.get("n_months_by_regime") or {}
        nm_ = max(1, min(months.values(), default=int(cond.get("n_months") or 1)))
        terms = view_omega_terms(regime_diag=rg, sigma_within_diag=wi, n_months=nm_)
        conf = float(np.min(implied_confidence(terms["omega_diag"],
                                               np.maximum(np.diag(sigma), 1e-12))))
        if conf_override is not None:
            conf = float(conf_override)
        resolve_shrinkage_lambda(cond)              # 계약 확인(스칼라여야 한다)

        views = _VIEWS[arch](mu, names, beta)
        P, Q, Om, skipped = pq_from_views(views, names, sigma, conf, tau)
        if P is None and arch != ARCH_PRIOR_ONLY:
            _blank(t); continue

        if arch == ARCH_PRIOR_ONLY:
            # ★뷰가 0개인 것은 실패가 아니라 이 팔의 정의다★ EP 의 사전분포
            # (시나리오 균등가중 = 트레일링 평균)를 그대로 μ 로 쓴다.
            rep = ep_posterior_mu([], names, R_win)
            if not rep.get("available"):
                _blank(t); continue
            rec["ep_kl"].append(0.0)
            rec["ep_inactive"] += 1
            mu_post = np.asarray(rep["prior_mu_annual"], float)
        elif engine == "bl":
            mu_post = bl_posterior(_equilibrium(sigma, w_mkt, delta), sigma,
                                   P, Q, Om, tau=tau)
        else:
            rep = ep_posterior_mu(views, names, R_win)
            if not rep.get("available"):
                _blank(t); continue
            kl = float(rep.get("kl") or 0.0)
            rec["ep_kl"].append(kl)
            if kl <= EP_INACTIVE_KL:
                rec["ep_inactive"] += 1
            if not rep.get("feasible"):
                # ★실현 불가는 **무거래**다 — 그날을 건너뛰지 않는다★
                # `continue` 로 스킵하면 그날 수익이 사라지는데, 포트폴리오는
                # 거래를 안 했을 뿐 포지션을 그대로 들고 있다(walk_forward 규약).
                rec["ep_infeasible"] += 1
                rec["w"].append(rec["w"][-1] if rec["w"] else None)
                rec["months"].append(_month_of(dates[t]))
                continue
            mu_post = np.asarray(rep["mu_annual"], float)

        w = _min_var_long_only(sigma, mu_post, delta)
        rec["w"].append(w)
        rec["months"].append(_month_of(dates[t]))
        if Q is not None and len(Q):
            rec["view_disp"].append(float(np.max(Q) - np.min(Q)) if len(Q) > 1
                                    else float(abs(Q[0])))
        rec["post_disp"].append(float(mu_post.max() - mu_post.min()))
        rec["conf"].append(conf if engine == "bl" else float("nan"))
        rec["applied"] += 1
        # 타이밍 지표: β 포트폴리오에 대한 뷰(사후 기준) vs 실현 β 수익
        rec["timing_view"].append(float((beta / np.abs(beta).sum()) @ mu_post))
        nxt = [i for i in rb if i > t]
        e = nxt[0] if nxt else len(R)
        rec["fwd_factor"].append(float((beta / np.abs(beta).sum())
                                       @ R[t:e].sum(axis=0)) if e > t else np.nan)
    return rec, rb


def simulate(rec, rb, R, dates, cost_bps: float):
    """비중 경로 → 자산곡선·회전율 (walk_forward 와 같은 규약: 편도 회전율·표류)."""
    cost = cost_bps / 1e4
    n = R.shape[1]
    w = np.zeros(n)
    eq, daily, tos, rb_month = 1.0, [], [], []
    at = {t: i for i, t in enumerate(rb)}
    equity_curve = []
    for t in range(rb[0], R.shape[0]):
        if t in at:
            w_new = rec["w"][at[t]]
            if w_new is not None:
                to = 0.5 * float(np.abs(w_new - w).sum())
                eq *= (1.0 - to * cost)
                w = w_new
                tos.append(to)
                rb_month.append(_month_of(dates[t]))
        pr = float(w @ R[t])
        eq *= (1.0 + pr)
        daily.append(pr)
        equity_curve.append(eq)
    return np.array(daily), np.array(equity_curve), np.array(tos), rb_month


def metrics(daily, curve, tos, rb_month, by_month, delta=DELTA_DEFAULT):
    if daily.size < 3:
        return {}
    ann = daily.mean() * 252
    vol = daily.std(ddof=1) * math.sqrt(252)
    dn = daily[daily < 0]
    dvol = dn.std(ddof=1) * math.sqrt(252) if dn.size > 2 else float("nan")
    peak = np.maximum.accumulate(curve)
    mdd = float(((curve - peak) / peak).min())
    q = float(np.percentile(daily, 5))
    cvar = float(daily[daily <= q].mean()) if (daily <= q).any() else float("nan")
    ce = float(ann - (delta / 2.0) * daily.var(ddof=1) * 252)
    # 거짓 트리거: 회전율이 중앙값 초과인데 실현 국면이 직전과 같은 비율
    thr = float(np.median(tos)) if tos.size else 0.0
    ntr = nf = 0
    prev = None
    for to, m in zip(tos, rb_month, strict=True):
        reg = by_month.get(m)
        if to > thr:
            ntr += 1
            if prev is not None and reg == prev:
                nf += 1
        prev = reg
    return {"return_pct": round(ann * 100, 2), "vol_pct": round(vol * 100, 2),
            "sharpe": round((ann - RF) / vol, 3) if vol > 0 else None,
            "sortino": round((ann - RF) / dvol, 3) if dvol == dvol and dvol > 0 else None,
            "mdd_pct": round(mdd * 100, 2), "cvar_pct": round(cvar * 100, 3),
            "turnover_pct": round(float(tos.mean()) * 100, 2) if tos.size else 0.0,
            "n_rebalances": int(tos.size), "ce": round(ce, 6),
            "false_trigger": round(nf / ntr, 4) if ntr else None}


def w_l1(rec):
    ws = [w for w in rec["w"] if w is not None]
    d = [float(np.abs(b - a).sum()) for a, b in zip(ws, ws[1:], strict=False)]
    return (round(float(np.mean(d)), 4), round(float(np.median(d)), 4)) if d else (None, None)


def w_dispersion(rec):
    """비중 산포 — 리밸런싱마다 `max(w) − min(w)` 의 평균, 그리고 EQ 비중의 범위."""
    ws = [w for w in rec["w"] if w is not None]
    if not ws:
        return {"spread": None, "eq_mean": None, "eq_sd": None, "eq_range": None}
    eq = np.array([float(w[:3].sum()) for w in ws])
    return {"spread": round(float(np.mean([w.max() - w.min() for w in ws])), 4),
            "eq_mean": round(float(eq.mean()), 4), "eq_sd": round(float(eq.std()), 4),
            "eq_range": round(float(eq.max() - eq.min()), 4)}


def timing_ic(rec):
    """★타이밍 IC★ — 단면 IC 가 아니라 **β 포트폴리오 뷰 vs 실현 β 수익**.

    ★T3-D 에는 정의되지 않는다★ μ 뷰가 없으므로 예측을 한 적이 없다. 0 을 적으면
    "예측했는데 못 맞췄다" 로 읽히므로 `undefined` 를 낸다.
    """
    if not rec.get("uses_mu", True):
        return {"ic": None, "t": None, "hit": None, "n": 0, "undefined": True,
                "reason": "이 아키텍처는 기대수익 뷰를 만들지 않는다"}
    v = np.array(rec["timing_view"], float)
    f = np.array(rec["fwd_factor"], float)
    ok = np.isfinite(v) & np.isfinite(f)
    if ok.sum() < 10 or np.std(v[ok]) < 1e-15:
        return {"ic": None, "t": None, "hit": None, "n": int(ok.sum())}
    ic = float(np.corrcoef(v[ok], f[ok])[0, 1])
    n = int(ok.sum())
    t = ic * math.sqrt(max(n - 2, 1) / max(1 - ic * ic, 1e-12))
    return {"ic": round(ic, 4), "t": round(t, 2),
            "hit": round(float(np.mean(np.sign(v[ok]) == np.sign(f[ok]))), 4), "n": n}


def _resolve_arch(spec: str | None) -> list[str]:
    if not spec:
        return list(DEFAULT_ARCH)
    if spec.strip().upper() == "ALL":
        return list(ARCH_ALL)
    if spec.strip().upper() == "D":
        return list(ARCH_BUDGET)
    out = []
    for a in spec.split(","):
        a = a.strip()
        if a not in ARCH_ALL:
            raise SystemExit(f"알 수 없는 아키텍처 '{a}' — 가능: {', '.join(ARCH_ALL)}")
        out.append(a)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=None)
    ap.add_argument("--months", type=int, default=84)
    ap.add_argument("--arch", default=None,
                    help=f"쉼표 구분 · ALL · D. 기본 {','.join(DEFAULT_ARCH)}")
    ap.add_argument("--engine", default="bl", choices=("bl", "ep", "both"))
    # ★신뢰도를 고정해 아키텍처만 비교할 수 있게 한다★ 분해 Ω 는 이 패널에서
    # conf≈1 까지 내려가 뷰가 거의 무시되는데, 그러면 "전달 형태가 중요한가" 를
    # 묻는 실험이 **뷰가 안 먹는 구간에서** 돌게 된다. 신뢰도를 올려가며 세 형태가
    # 어떻게 갈라지는지 보는 것이 이 연구의 핵심이다.
    ap.add_argument("--conf", type=float, default=None)
    args = ap.parse_args()

    arches = _resolve_arch(args.arch)
    engines = ENGINES if args.engine == "both" else (args.engine,)
    names, R, dates, points, beta = build_panel(months=args.months)
    by_month = {p["t"]: p["regime"] for p in points}

    out: dict[str, dict] = {}
    order: list[tuple[str, str]] = []
    for arch in arches:
        # ★D 계열에는 엔진 개념이 없다★ 뷰를 만들지 않으므로 BL/EP 를 통과하지 않는다.
        # ★prior-only 는 EP 전용★ BL 은 균형 Π 라 "사전이 움직인다" 가 성립하지 않는다.
        for eng in (("bl",) if arch in ARCH_BUDGET
                    else ("ep",) if arch == ARCH_PRIOR_ONLY else engines):
            rec, rb = run_arch(arch, names, R, dates, points, beta,
                               conf_override=args.conf, engine=eng)
            mean_l1, med_l1 = w_l1(rec)
            cells = {}
            for c in COSTS:
                d, curve, tos, rbm = simulate(rec, rb, R, dates, c)
                cells[c] = metrics(d, curve, tos, rbm, by_month)
            key = arch if arch in ARCH_BUDGET else f"{arch}/{eng}"
            order.append((key, arch))
            out[key] = {
                "arch": arch, "engine": None if arch in ARCH_BUDGET else eng,
                "uses_mu": rec["uses_mu"],
                "view_disp": round(float(np.mean(rec["view_disp"])), 4)
                if rec["view_disp"] else None,
                "post_disp": round(float(np.mean(rec["post_disp"])), 4)
                if rec["post_disp"] else None,
                "conf": round(float(np.mean(rec["conf"])), 3)
                if (rec["conf"] and eng == "bl") else None,
                "w_l1_mean": mean_l1, "w_l1_median": med_l1,
                "dispersion": w_dispersion(rec),
                "applied": rec["applied"],
                "n_views": (len(_VIEWS[arch](np.zeros(len(names)) + 0.01,
                                             names, beta))
                            if arch in _VIEWS else 0),
                "ep_inactive": rec["ep_inactive"], "ep_infeasible": rec["ep_infeasible"],
                "ep_inactive_pct": (round(100.0 * rec["ep_inactive"] / len(rec["ep_kl"]), 1)
                                    if rec["ep_kl"] else None),
                "eq_cap_mean": (round(float(np.mean([c for c in rec["caps"]
                                                     if c is not None])), 1)
                                if any(c is not None for c in rec["caps"]) else None),
                "eq_budget_mean": (round(float(np.mean(rec["budget_eq"])), 4)
                                   if rec["budget_eq"] else None),
                "timing": timing_ic(rec), "cells": cells,
            }

    hdr = (f"{'arch/engine':>16} {'뷰수':>4} {'뷰산포':>7} {'사후산포':>8} {'conf':>6} "
           f"{'Δw L1':>7} {'중앙':>7} {'EQ범위':>7} | {'bp':>3} {'ret%':>7} {'vol%':>6} "
           f"{'sharpe':>6} {'mdd%':>7} {'cvar%':>6} {'turn%':>6} "
           f"{'nrb':>4} {'CE':>8} {'FT':>6}")
    print(hdr)
    print("-" * len(hdr))

    def _f(v, w, p=4):
        return f"{v:>{w}.{p}f}" if isinstance(v, (int, float)) else f"{'—':>{w}}"

    for key, _arch in order:
        o = out[key]
        for c in COSTS:
            m = o["cells"][c]
            print(f"{key:>16} {o['n_views']:>4} {_f(o['view_disp'], 7)} "
                  f"{_f(o['post_disp'], 8)} {_f(o['conf'], 6, 2)} "
                  f"{_f(o['w_l1_mean'], 7)} {_f(o['w_l1_median'], 7)} "
                  f"{_f(o['dispersion']['eq_range'], 7)} | {c:>3.0f} "
                  f"{m['return_pct']:>7} {m['vol_pct']:>6} {str(m['sharpe']):>6} "
                  f"{m['mdd_pct']:>7} {m['cvar_pct']:>6} {m['turnover_pct']:>6} "
                  f"{m['n_rebalances']:>4} {m['ce']:>8.4f} {str(m['false_trigger']):>6}")

    if any(out[k]["engine"] == "ep" for k, _ in order):
        print()
        print("EP 전달 안정성 (★부등식이라 이미 만족되면 아무 일도 하지 않는다★)")
        for key, _a in order:
            o = out[key]
            if o["engine"] != "ep":
                continue
            print(f"  {key}: 사후=사전 {o['ep_inactive']}회 "
                  f"({o['ep_inactive_pct']}%) · 실현불가(무거래) {o['ep_infeasible']}회")

    if any(out[k]["arch"] in ARCH_BUDGET for k, _ in order):
        print()
        print("T3-D 국면 반응 (★μ 를 읽지 않는다 — 예산·한도만★)")
        for key, _a in order:
            o = out[key]
            if o["arch"] not in ARCH_BUDGET:
                continue
            print(f"  {key}: EQ 리스크예산 평균 {o['eq_budget_mean']} · "
                  f"EQ 상한 평균 {o['eq_cap_mean']}")

    print()
    print("타이밍 평가 (★단면 IC 가 아니다★ — β 포트폴리오 뷰 vs 실현 β 수익)")
    for key, _a in order:
        t = out[key]["timing"]
        if t.get("undefined"):
            print(f"  {key}: ★정의되지 않음★ — {t['reason']}")
        else:
            print(f"  {key}: IC {t['ic']}  t={t['t']}  방향적중 {t['hit']}  n={t['n']}")

    print()
    print("ΔCE (★같은 엔진 안에서만★ 첫 팔 대비)")
    for eng in engines:
        base = next((k for k, _a in order if out[k]["engine"] == eng), None)
        if base is None:
            continue
        for key, _a in order:
            if out[key]["engine"] != eng or key == base:
                continue
            for c in COSTS:
                d = out[key]["cells"][c]["ce"] - out[base]["cells"][c]["ce"]
                print(f"  {key} vs {base} @{c:>4.0f}bp : {d:+.6f}")
    # ── ★T3-D 귀속 — 뺄셈을 **둘**로 가른다★ ────────────────────────────────
    # `D-regime − D-open` 은 셋을 뭉친다: 제약이 있다는 것의 값 · 그 수준의 값 ·
    # 국면에 따라 변한다는 것의 값. 앞의 둘은 매크로가 아니라 **포트폴리오 정책**이다.
    fams = [(f, f, f"{f}-const", f"{f}-open") for f in ("T3-D1", "T3-D2")]
    if any(out.get(f[1]) for f in fams):
        print()
        print("★T3-D 귀속★ 정책 가치 = const − open · **동적 매크로 가치 = regime − const**")
        for _f, dyn, const, open_ in fams:
            if not all(k in out for k in (dyn, const, open_)):
                continue
            for c in COSTS:
                ce = {k: out[k]["cells"][c]["ce"] for k in (dyn, const, open_)}
                policy = ce[const] - ce[open_]
                dynamic = ce[dyn] - ce[const]
                verdict = ("★동적 국면 제약에 대한 반증(이 합성 기제 한정)★"
                           if dynamic < 0 else "동적 항이 양수")
                print(f"  {dyn} @{c:>4.0f}bp : 정책 {policy:+.6f} · "
                      f"동적매크로 {dynamic:+.6f}  {verdict if c == 0 else ''}")
        print("  ★`D-const > D-regime` 은 **동적 국면 의존 제약**에 대한 반증이지")
        print("    **제약 일반**에 대한 반증이 아니다. 정책 항은 별도로 읽는다.★")
        print("  (D 계열은 A/B/C 와 최적화기 계열이 달라 그쪽과는 비교하지 않는다)")

    from src.engine.capability import probe_all
    fs = probe_all().get("frontier_sample", {})
    print()
    print(f"★증거 등급★ {EVIDENCE_SYNTHETIC} — 합성 패널이다. Sharpe·CE·CVaR 는 "
          f"기제 확인 수치이지 **경제적 가치의 증거가 아니다**.")
    print("  표본:", json.dumps(fs.get("detail") or fs.get("reason") or {},
                               ensure_ascii=False))
    if args.report:
        # ★등급이 보고서 최상단에 박힌다★ 나중에 이 JSON 만 보는 사람이 합성임을
        # 모른 채 인용하는 것을 막는다.
        payload = {"evidence_grade": EVIDENCE_SYNTHETIC, "real_share": 0.0,
                   "frontier_sample": fs.get("detail") or fs.get("reason"),
                   "arms": out}
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        print(f"\nJSON → {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
