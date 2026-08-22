"""05 VIEWS — 뷰를 $Ak \\le b$ 로 컴파일하고 실현가능성을 검사한다 (M1-M)
==============================================================================
프론티어: Agentic MCP — DART 공시문 + 검색 트렌드를 CLQT 5단계로 읽어 **텍스트에서**
          선형 뷰 제약을 뽑는다.
대체:     결정론적 뷰 컴파일러 — 사용자가 명시한 뷰를 $Ak \\le b$ 로 바꾸고,
          Entropy Pooling(M1-T)으로 **실제로 만족 가능한지** 검사한다.

★경계를 특히 분명히 한다★
텍스트 → 뷰 변환에는 LLM 과 트렌드 API 가 둘 다 필요하고, 이 환경에는 **둘 다 없다**
(키 부재 + 프록시 403). 여기서 짓는 것은 **컴파일러와 검사기**뿐이다.
없는 근거로 만든 뷰가 포트폴리오를 움직이는 것이 이 화면에서 가장 위험한 일이므로,
"공시문을 읽어 뷰를 만들었다" 는 주장은 프론티어가 가용해지기 전까지 하지 않는다.

★뷰는 부등식이다★
"기대수익이 정확히 8%" 라고 말할 수 있는 사람은 없다. 등식 뷰는 그 주장을 강제해
사후분포를 과하게 비튼다. 방향과 하한/상한이 실제로 말할 수 있는 것이고,
Entropy Pooling 이 "뷰가 요구한 것 이상은 바꾸지 않는다" 를 보장한다.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from src.engine.macro_models.base import Engine, Studio, ok, unavailable

STUDIO = Studio(
    id="agentic-mcp",
    label="VIEWS",
    question="내 뷰는 서로 모순되지 않는가? 배분을 얼마나 움직이는가?",
    frontier=Engine(
        name="Agentic MCP (CLQT 5단계)",
        kind="frontier",
        summary="공시문·검색 트렌드 → 선형 뷰 제약 Ak ≤ b 자동 추출",
        requires=("llm", "trends_api"),
    ),
    substitute=Engine(
        name="뷰 컴파일러 + 실현가능성 검사",
        kind="substitute",
        summary="명시된 뷰를 Ak ≤ b 로 컴파일 → Entropy Pooling 으로 모순 검사",
        requires=("entropy_pooling",),
    ),
    inputs=(),
)

_MAX_VIEWS = 20


def compile_views(assets: list[str], views: list[dict[str, Any]]) -> dict[str, Any]:
    """뷰 목록 → `(A, b)` 와 사람이 읽는 설명.

    뷰 항목: `{"asset": str, "direction": +1|-1, "value": float, "label"?: str}`
      · `+1` → `E[r_asset] ≥ value` → 행 `-e_asset`, 우변 `-value`
      · `-1` → `E[r_asset] ≤ value` → 행 `+e_asset`, 우변 `+value`
    """
    if not assets:
        return {"ok": False, "reason": "자산 목록이 비어 있습니다."}
    if len(views) > _MAX_VIEWS:
        return {"ok": False, "reason": f"뷰가 너무 많습니다 ({len(views)} > {_MAX_VIEWS})."}

    idx = {a: i for i, a in enumerate(assets)}
    rows, rhs, human = [], [], []
    for v in views:
        a = str(v.get("asset", ""))
        if a not in idx:
            return {"ok": False, "reason": f"유니버스에 없는 자산에 대한 뷰입니다: {a}"}
        try:
            val = float(v["value"])
        except (KeyError, TypeError, ValueError):
            return {"ok": False, "reason": f"뷰의 값이 숫자가 아닙니다: {a}"}
        d = 1 if int(v.get("direction", 1)) >= 0 else -1
        row = np.zeros(len(assets))
        row[idx[a]] = -d
        rows.append(row)
        rhs.append(-d * val)
        human.append(f"E[{a}] {'≥' if d > 0 else '≤'} {val:.4g}"
                     + (f"  ({v['label']})" if v.get("label") else ""))

    if not rows:
        return {"ok": True, "A": [], "b": [], "human": [], "n": 0}
    return {"ok": True, "A": np.vstack(rows).tolist(), "b": rhs, "human": human,
            "n": len(rows)}


def run(assets: list[str] | None = None, views: list[dict[str, Any]] | None = None,
        scenarios: list[list[float]] | None = None, **_: Any) -> dict[str, Any]:
    """뷰를 컴파일하고, 시나리오가 있으면 실현가능성까지 검사한다."""
    assets = list(assets or [])
    views = list(views or [])
    if not assets:
        return unavailable(STUDIO.substitute.name,
                           "자산 목록이 없습니다 — 뷰를 어느 유니버스에 걸지 알 수 없습니다.")

    comp = compile_views(assets, views)
    if not comp["ok"]:
        return unavailable(STUDIO.substitute.name, comp["reason"])

    out: dict[str, Any] = {"assets": assets, "n_views": comp["n"],
                           "A": comp["A"], "b": comp["b"], "human": comp["human"]}

    if not views:
        return ok(STUDIO.substitute.name, {**out, "feasible": None},
                  note="뷰가 없습니다 — 컴파일할 제약이 없고 사후분포는 사전과 같습니다.")

    if scenarios is None:
        # ★검사하지 않았다는 것을 `feasible: null` 로 말한다★ `true` 로 두면 화면은
        # "모순 없음을 확인했다" 로 읽는다. 확인하지 않은 것과 확인해서 통과한 것은
        # 다른 사실이다.
        return ok(STUDIO.substitute.name, {**out, "feasible": None},
                  note=("제약은 컴파일했지만 시나리오가 없어 **실현가능성은 검사하지 "
                        "않았습니다** — 모순이 없다는 뜻이 아닙니다."))

    R = np.atleast_2d(np.asarray(scenarios, dtype=float))
    if R.shape[1] != len(assets):
        return unavailable(
            STUDIO.substitute.name,
            f"시나리오 열 수({R.shape[1]})가 자산 수({len(assets)})와 다릅니다.")

    from src.engine.entropy_pooling import pool_weights
    pooled = pool_weights(R, views=[
        {"asset": assets.index(str(v["asset"])), "direction": int(v.get("direction", 1)),
         "value": float(v["value"])} for v in views])
    if not pooled.get("available"):
        return unavailable(STUDIO.substitute.name,
                           pooled.get("reason") or "뷰 결합에 실패했습니다.")

    feasible = bool(pooled["feasible"])
    note = ("뷰가 서로 모순되지 않으며, 사후분포는 뷰가 요구한 것 이상을 바꾸지 않습니다."
            if feasible else
            "★이 뷰들을 동시에 만족시키는 분포가 없습니다★ 아래 위반 목록을 보고 "
            "뷰를 완화하거나 하나를 내리세요. 이 상태로 배분하지 마세요.")
    if pooled.get("note"):
        note = f"{note} {pooled['note']}"

    return ok(
        STUDIO.substitute.name,
        {**out,
         "feasible": feasible,
         "violations": pooled.get("violations", []),
         "kl": round(float(pooled["kl"]), 6),
         "ens": round(float(pooled["ens"]), 2),
         "ens_prior": round(float(pooled["ens_prior"]), 2),
         "prior_mean": [round(v, 6) for v in pooled["prior_mean"]],
         "posterior_mean": [round(v, 6) for v in pooled["posterior_mean"]]},
        note=note,
    )
