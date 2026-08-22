"""능력 사다리 — L0~L3 을 다이어그램이 아니라 **측정 가능한 아티팩트**로 (M1-C)
==============================================================================
왜 이 파일이 M1 에서 가장 중요한가
------------------------------------------------------------------------------
요청받은 아키텍처는 Neural SDE · PINN · RL-GNN · Gen-DFL Diffusion · cvxpylayers SPO 를
Tier 2~4 에 놓는다. 그런데 이 환경의 실측은 이렇다:

  · torch · cvxpy · cvxpylayers · jax · hmmlearn  — **전부 미설치**, GPU 없음
  · 매크로 시계열                                  — 29계열 × **60개월**, 전부 mock
  · 다섯 데이터 호스트                              — 전부 프록시 403 CONNECT

A8 은 4상태 HMM 을 관측 48 / 모수 32 라는 이유로 기각했다. 위 모델들은 모수가 그보다
몇 자릿수 크다. **60개 목 데이터 위에 올리면 그럴듯한 숫자를 만드는 기계가 된다.**

그래서 이 파일은 모델을 짓지 않는다. 대신 **"지금 무엇이 가능한가"를 코드가 판정하게**
한다. 프론티어 모델이 들어올 자리를 남기되, 그 자리가 왜 비어 있는지를 API 와 화면이
항상 말하게 만드는 것이 목적이다.

★위조할 수 없어야 한다★
------------------------------------------------------------------------------
레벨을 문자열 상수로 두면 아무나 "L0" 이라고 적을 수 있고, 그러면 이 사다리는 다이어그램
으로 되돌아간다. 그래서 요건은 전부 **실제로 확인하는 프로브**다:

  · 모듈 요건은 `importlib.util.find_spec` 이 아니라 **실제 import 후 심볼 확인**.
    `sys.modules` 에 가짜를 꽂아도 심볼이 없으면 열리지 않는다.
  · 표본 요건은 관측 수를 **실제로 센다**.
  · 데이터 요건은 지표 가용성을 **실제로 읽는다**.

그리고 `resolve()` 는 도달 레벨만 주지 않고 **바로 위 레벨이 왜 안 됐는지**를 함께 준다.
사유 없는 강등은 "왜 이 답이 나왔는지" 를 사용자에게서 빼앗는다.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# 사다리는 위에서 아래로 — 앞선 것이 더 강한 주장이다.
LEVEL_ORDER = ("L0", "L1", "L2", "L3")

LEVEL_LABEL = {
    "L0": "Full Frontier",
    "L1": "Quantitative Causal",
    "L2": "Robust Statistical",
    "L3": "Safe Baseline",
}


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    reason: str = ""
    detail: dict[str, Any] | None = None


def _module_probe(module: str, *symbols: str) -> Callable[[], ProbeResult]:
    """모듈을 **실제로 import 하고 심볼까지 확인**하는 프로브를 만든다.

    `find_spec` 만 보면 빈 껍데기 모듈로 통과한다 — 이 사다리에서 그것은 곧
    "쓸 수 없는 모델을 쓸 수 있다고 말하는 것" 이고, 가장 위험한 거짓이다.

    ★반드시 **쓸 모듈의 전체 경로**를 준다 (실측으로 배웠다)★
    첫 작성에서 `_module_probe("statsmodels", "api")` 라고 썼더니 statsmodels 0.14.6 이
    설치돼 있는데도 L1 이 막혔다. `import statsmodels` 는 `statsmodels.api` 를 끌어오지
    않으므로 `hasattr(mod, "api")` 가 False 다 — 파이썬 서브모듈의 기본 동작이고,
    `scipy`/`optimize` · `cvxpylayers`/`torch` 도 똑같이 틀렸다. 즉 **프로브가 틀렸지
    환경이 아니었다.** 이제 점 경로를 그대로 import 하고, 심볼은 그 모듈에서 찾는다.
    """
    def probe() -> ProbeResult:
        try:
            mod = importlib.import_module(module)
        except Exception as e:  # noqa: BLE001 — ImportError 외에도 초기화 실패가 온다
            return ProbeResult(False, f"`{module}` 을 가져올 수 없습니다: {type(e).__name__}")
        missing = [s for s in symbols if not hasattr(mod, s)]
        if missing:
            return ProbeResult(
                False,
                f"`{module}` 은 있지만 필요한 심볼이 없습니다: {', '.join(missing)}")
        root = importlib.import_module(module.split(".")[0])
        return ProbeResult(True, detail={"module": module,
                                         "version": getattr(root, "__version__", None)})
    return probe


#: 합성이 아닌 것으로 인정하는 출처. `MacroSeries.source` 가 쓰는 값과 같아야 한다.
_REAL_SOURCES = ("BOK", "FRED", "KRX", "DART", "KIS")

#: 프론티어를 열려면 실측 계열이 이만큼은 돼야 한다. 절반 — 근거는 아래 주석.
_MIN_REAL_SHARE = 0.5


def _min_observations(n_required: int, *,
                      require_real_source: bool = False) -> Callable[[], ProbeResult]:
    """표본이 실제로 충분한지 **센다**.

    모듈이 있어도 표본이 없으면 모델은 노이즈를 낸다. A8 이 4상태 HMM 을 기각한 것이
    정확히 이 판정이었고, 그때는 사람이 손으로 셌다 — 여기서는 코드가 센다.

    ★`require_real_source` 는 P4 가 만든 안전장치다★
    ------------------------------------------------------------------------------
    P4 는 적재 깊이를 20년(240개월)으로 올리고 **mock 길이도 그 깊이에서 유도**하게
    바꾼다. 파이프라인이 깊이를 감당하는지 mock 으로 검증하기 위해서다. 그런데 그
    변경만 하면 위험이 하나 생긴다 — **관측 240개가 전부 합성인데 `frontier_sample`
    이 통과해, 지어낸 데이터 위에서 L0(Full Frontier)이 열린다.** 그러면 이 사다리는
    M1 이 막으려던 바로 그것("그럴듯한 숫자를 만드는 기계")이 된다.

    그래서 관측 수와 **출처를 함께** 본다. 표본이 240개여도 실측 비중이 낮으면 열지
    않고, 사유에 두 수치를 나란히 적는다 — 무엇이 모자란지 사람이 바로 알아야 한다.

    ★L1 의 `causal_sample` 에는 이 조건을 걸지 않는다★ L1 대체 엔진들은 이미 자기
    출처를 라벨로 밝히고(`span`·`note` 계약), mock 환경에서 도는 것이 이 저장소의
    확립된 개발 동작이다. 여기까지 막으면 개발 환경에서 매크로가 통째로 죽는다.
    막아야 하는 것은 **프론티어를 여는 주장**이지 개발용 계산이 아니다.
    """
    def probe() -> ProbeResult:
        try:
            from src.services.macro_collector import MacroCollector
            snap = MacroCollector().collect_all()
            series = getattr(snap, "series", None) or {}
            n = max((len(s.values) for s in series.values()), default=0)
        except Exception as e:  # noqa: BLE001
            return ProbeResult(False, f"매크로 시계열을 읽지 못해 표본을 셀 수 없습니다: {e}")

        real = sum(1 for s in series.values()
                   if str(getattr(s, "source", "") or "").upper() in _REAL_SOURCES)
        total = len(series)
        share = (real / total) if total else 0.0
        detail = {"observed": n, "required": n_required,
                  "real_series": real, "total_series": total,
                  "real_share": round(share, 3)}

        if n < n_required:
            return ProbeResult(
                False,
                f"표본이 부족합니다 — 관측 {n}개, 최소 {n_required}개 필요",
                detail)
        if require_real_source and share < _MIN_REAL_SHARE:
            return ProbeResult(
                False,
                (f"관측 {n}개는 충족했지만 실측 데이터가 아닙니다 — "
                 f"실측 계열 {real}/{total}({round(share * 100)}%), "
                 f"최소 {round(_MIN_REAL_SHARE * 100)}% 필요. "
                 f"합성 데이터로는 프론티어 모델을 열지 않습니다 "
                 f"(BOK/FRED/KRX/DART/KIS 키를 넣으면 열립니다)."),
                detail)
        return ProbeResult(True, detail=detail)
    return probe


def _repo_module(module: str, *symbols: str) -> Callable[[], ProbeResult]:
    """저장소 안의 엔진이 실제로 import 되는지 — 외부 의존성 때문에 죽는 경우가 있다."""
    return _module_probe(module, *symbols)


def _either_trends_source() -> Callable[[], ProbeResult]:
    """검색 트렌드 — **둘 중 하나만 있어도 열린다** (M1-I).

    Naver DataLab 과 Google Trends 는 서로 대체 가능한 근거다(둘 다 구간 정규화된
    상대 지수). 그래서 `and` 가 아니라 `or` 다. 다만 **어느 쪽이 열렸는지**를
    detail 에 남긴다 — "트렌드가 있다" 와 "한국 트렌드가 있다" 는 다른 사실이고,
    05 VIEWS 가 국내 공시를 다룰 때 그 구분이 필요해진다.
    """
    import os

    def probe() -> ProbeResult:
        naver = bool(os.getenv("NAVER_CLIENT_ID")) and bool(os.getenv("NAVER_CLIENT_SECRET"))
        google = bool(os.getenv("GOOGLE_TRENDS_API_KEY"))
        if naver or google:
            return ProbeResult(True, detail={"naver": naver, "google": google})
        return ProbeResult(
            False,
            "Naver DataLab(NAVER_CLIENT_ID/SECRET) 도 Google Trends"
            "(GOOGLE_TRENDS_API_KEY) 도 설정되지 않았습니다 — 둘 중 하나면 됩니다.")
    return probe


def _external_service(env_keys: tuple[str, ...], label: str) -> Callable[[], ProbeResult]:
    """외부 서비스 — 키가 있는지만 본다. **호출해 보지 않는다.**

    키가 있어도 이 환경은 프록시가 403 CONNECT 로 막는다. 그 사실을 여기서 네트워크
    호출로 확인하려 들면 프로브가 느려지고 불안정해진다. 키 부재는 확실한 미가용이고,
    키가 있는데 막히는 것은 **호출 지점이 사유와 함께 보고**한다 — 층을 나눈다.
    """
    import os

    def probe() -> ProbeResult:
        missing = [k for k in env_keys if not os.getenv(k)]
        if missing:
            return ProbeResult(False, f"{label} 키가 없습니다: {', '.join(missing)}")
        return ProbeResult(True, detail={"keys": list(env_keys)})
    return probe


# ── 요건 레지스트리 ──────────────────────────────────────────────────────────
# 각 요건은 이름 → (설명, 프로브). 레벨은 요건 **이름**만 참조한다.
REQUIREMENTS: dict[str, tuple[str, Callable[[], ProbeResult]]] = {
    # L0 — 프론티어
    "torch": ("Neural SDE · PINN · RL-GNN 학습/추론 (torch)",
              _module_probe("torch.nn", "Module")),
    "cvxpylayers": ("SPO 종단 미분 최적화 레이어 (cvxpylayers + cvxpy)",
                    _module_probe("cvxpylayers.torch", "CvxpyLayer")),
    "trends_api": ("검색 트렌드 (Naver DataLab · Google Trends)",
                   _either_trends_source()),
    "llm": ("공시문 → 뷰 변환 (Agentic MCP)",
            _external_service(("ANTHROPIC_API_KEY",), "LLM")),
    "frontier_sample": ("프론티어 모델 학습에 필요한 최소 표본",
                        # 20년 월간. ★출처 조건이 함께 걸린다 (P4-D4)★ — 깊이를 올려
                        # mock 이 240개를 만들어도 합성으로는 열리지 않는다.
                        _min_observations(240, require_real_source=True)),

    # L1 — 정량 인과
    "statsmodels": ("동적 요인모형 · Granger · Markov 전환",
                    _module_probe("statsmodels.tsa.statespace.dynamic_factor", "DynamicFactor")),
    "causal_graph": ("방향성 매크로 그래프",
                     _repo_module("src.engine.causal_graph")),
    "term_structure": ("수익률 곡선 적합 (scipy 최적화)",
                       _module_probe("scipy.optimize", "least_squares")),
    "causal_sample": ("인과 추정에 필요한 최소 표본", _min_observations(36)),

    # L2 — 견고 통계
    "conformal": ("분포 무가정 예측 구간", _repo_module("src.engine.conformal")),
    "entropy_pooling": ("KL 최소화 뷰 결합", _repo_module("src.engine.entropy_pooling")),

    # L3 — 안전 기저: 요건 없음. numpy 만으로 성립하는 마지막 바닥.
}

LEVEL_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "L0": ("torch", "cvxpylayers", "trends_api", "llm", "frontier_sample"),
    "L1": ("statsmodels", "causal_graph", "term_structure", "causal_sample"),
    "L2": ("conformal", "entropy_pooling"),
    "L3": (),
}

LEVEL_NOTE = {
    "L0": "Gen-DFL + RL-GNN + Agentic MCP + SPO — 전 기능",
    "L1": "DeePM + 수익률곡선 + 고전 뷰 결합 (텍스트 뷰 제외)",
    "L2": "예측 구간 + 엔트로피 풀링 / 최소분산",
    "L3": "HRP 또는 균등가중 + 현금 — 마지막 바닥",
}


def probe_all() -> dict[str, dict[str, Any]]:
    """요건별 판정. **프로브를 실제로 돌린다** — 캐시하지 않는 이유는 의존성이
    설치되면 그 즉시 사다리가 열려야 하기 때문이다."""
    out: dict[str, dict[str, Any]] = {}
    for name, (desc, probe) in REQUIREMENTS.items():
        try:
            r = probe()
        except Exception as e:  # noqa: BLE001 — 프로브가 죽어도 사다리는 답해야 한다
            r = ProbeResult(False, f"프로브 실행 실패: {type(e).__name__}: {e}")
        out[name] = {"ok": r.ok, "description": desc, "reason": r.reason,
                     "detail": r.detail}
    return out


def resolve(probes: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """도달 레벨 + **바로 위 레벨이 실패한 이유**.

    ★사유 없는 강등은 하지 않는다★ "L2 입니다" 만 말하면 사용자는 왜 L1 이 아닌지
    알 수 없고, 그러면 의존성을 설치해 올릴 방법도 알 수 없다.
    """
    p = probes if probes is not None else probe_all()

    per_level: dict[str, dict[str, Any]] = {}
    reached: str | None = None
    for lvl in LEVEL_ORDER:
        reqs = LEVEL_REQUIREMENTS[lvl]
        failed = [r for r in reqs if not p.get(r, {}).get("ok")]
        per_level[lvl] = {
            "label": LEVEL_LABEL[lvl], "note": LEVEL_NOTE[lvl],
            "requirements": list(reqs), "failed": failed, "ok": not failed,
        }
        if not failed and reached is None:
            reached = lvl

    # 요건이 없는 L3 는 항상 성립하므로 reached 는 None 이 될 수 없다.
    level = reached or "L3"

    # 바로 위 레벨(더 강한 주장)이 왜 안 됐는지.
    idx = LEVEL_ORDER.index(level)
    blocked_reason = None
    blocked_level = None
    if idx > 0:
        blocked_level = LEVEL_ORDER[idx - 1]
        why = [f"{r}: {p.get(r, {}).get('reason') or '미가용'}"
               for r in per_level[blocked_level]["failed"]]
        blocked_reason = " / ".join(why)

    # ── ★아래 사다리가 성한지도 답한다 (실측이 드러낸 구멍)★ ──────────────
    # 처음에는 "도달 레벨"만 냈다. 그런데 실측에서 **L1 은 통과인데 L2 가 실패**로
    # 나왔다 — conformal·entropy_pooling 이 아직 없기 때문이다. 사다리의 요점은
    # "위가 죽으면 아래로 내려간다" 인데, 아래 칸이 비어 있으면 L1 이 죽는 순간
    # **L3 까지 곧장 추락한다.** 도달 레벨만 보고하면 그 위험이 화면에서 사라진다.
    #
    # 레벨 간 요건은 포함관계가 아니다(L1 이 L2 의 요건을 필요로 하지 않는다).
    # 그래서 이것은 "버그"가 아니라 **따로 보고해야 하는 사실**이다.
    below = LEVEL_ORDER[idx + 1:]
    broken = [lv for lv in below if not per_level[lv]["ok"]]
    next_working = next((lv for lv in below if per_level[lv]["ok"]), None)

    return {
        "level": level,
        "label": LEVEL_LABEL[level],
        "note": LEVEL_NOTE[level],
        "blocked_level": blocked_level,
        "blocked_reason": blocked_reason,
        # 폴백 경로 상태 — `fallback_intact` 가 False 면 한 단계 강등이 아니라
        # 여러 단계 추락이 일어난다.
        "fallback_intact": not broken,
        "fallback_broken_levels": broken,
        "fallback_next": next_working,
        "fallback_reason": (
            None if not broken else
            f"{level} 이 실패하면 {'·'.join(broken)} 을 건너뛰고 "
            f"{next_working or '없음'} 으로 내려갑니다 — "
            + " / ".join(
                f"{lv}: " + ", ".join(per_level[lv]["failed"]) for lv in broken)
        ),
        "levels": per_level,
        "requirements": p,
    }
