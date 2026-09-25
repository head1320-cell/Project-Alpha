"""멀티전략 서브시스템 — ★무엇이 없는지 한 곳에서 말한다★ (BF)
==============================================================================
소비자: `src/api/stage11_routes.py`(multibacktest) · `src/api/stage12_routes.py`
(realism) · 트립와이어 `tests/test_no_dangling_imports.py`

## 실측 (2026-09-24, BF)

`multi_strategy_backtest` · `realism_engine` · `counterfactual_analyzer` 는 모듈
**다섯**을 import 하는데 다섯 다 저장소에 없었다. 2026-06-10 *"본체 코드베이스 이식
(0605_1019 스냅샷)"* 에 import 가 이미 끊긴 채 들어왔고, 요청마다
`500 No module named 'src.engine.allocator'` 가 났다.

## 복원 (2026-09-25, BG)

코어 셋 — `strategy_registry`(BG1) · `allocator`(BG2) · `order_netting`(BG3) — 이
복원돼 레지스트리에서 빠졌다(트립와이어가 요구한다). 남은 둘(`macro_feed` ·
`regime_model`)은 R4 이고 ★기능 단위로만★ 막는다: `hrp_macro` · `regime_change` 를
고른 요청만 422 + 사유, 나머지는 돈다(BG4).

## ★이 모듈이 하지 않는 것★

- **없는 것을 만들지 않는다.** 국면 분류기·매크로 피드는 배분 정책이고(CLAUDE.md §3
  별도 승인), 빈 껍데기를 두면 "동작한다" 로 위장한다.
- **엔진을 고치지 않는다.** 문(라우트)이 먼저 묻고 503(코어 부재) · 422(없는 기능)
  + 사유를 낸다.
- **선언을 믿지 않는다.** `missing_now()` 는 `find_spec` 으로 **지금** 잰다 — 누가
  모듈을 복원하면 스스로 빠지고, 트립와이어가 레지스트리 정리를 요구한다.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

#: 끊긴 채 들어온 시점 — 사용자가 "언제부터" 를 물을 때의 답.
SINCE = "2026-06-10 본체 코드베이스 이식(0605_1019 스냅샷) — 그 뒤로 한 번도 존재한 적이 없다"

_ENGINE = "src/engine/multi_strategy_backtest.py"


@dataclass(frozen=True)
class MissingModule:
    """없는 모듈 하나. ★무엇을 하려던 것인지 사람 말로★"""

    module: str
    needed_by: tuple[str, ...]
    role: str
    reason: str
    #: ★이 모듈이 없으면 막히는 기능★ (BG4) — `FEATURES` 의 키. 비어 있으면 **코어**라
    #: 없을 때 서브시스템 전체가 503 이다. 있으면 그 기능을 고른 요청만 422 다.
    features: tuple[str, ...] = ()


#: 기능 → (요청 칸, 값, 사유). ★R4 전까지 막는 두 가지★ — 나머지 요청은 돈다.
FEATURES: dict[str, tuple[str, str, str]] = {
    "hrp_macro": (
        "allocation_method", "hrp_macro",
        "hrp_macro 는 HRP 위에 매크로 국면 기울기를 얹는 배분 정책인데 매크로 피드"
        "(macro_feed)·국면 분류기(regime_model)가 이 저장소에 없습니다 — R4 에서 별도 "
        "승인 후 다룹니다. hrp 또는 inverse_vol 을 고르세요."),
    "regime_change": (
        "rebalance_policy", "regime_change",
        "국면 변경 리밸런싱은 국면 분류기(regime_model)가 있어야 합니다. 없으면 국면이 "
        "늘 미상이라 엔진이 매일 리밸런싱합니다 — 조용히 daily 가 되므로 R4 전까지 "
        "막습니다. daily·weekly·monthly·quarterly 중에서 고르세요."),
}


MISSING: tuple[MissingModule, ...] = (
    MissingModule(
        module="src.data.macro_feed", needed_by=(_ENGINE,),
        role="매크로 피드(MacroFeedCollector)",
        reason=("hrp_macro 용 매크로 행렬을 만드는 자리입니다. 저장소의 매크로 "
                "계층(pit_macro·macro_observation_store)과는 다른 이름의 모듈입니다."),
        features=("hrp_macro",)),
    MissingModule(
        module="src.engine.regime_model",
        needed_by=(_ENGINE, "src/engine/realism_engine.py"),
        role="4국면 분류기(MultiRegimeModel)",
        reason=("GOLDILOCKS·REFLATION·STAGFLATION·DEFLATION 으로 날짜를 분류하는 "
                "자리입니다. 저장소 어디에도 이 분류기가 없고, 만들면 국면-배분 "
                "정책이라 별도 승인 사항입니다."),
        features=("hrp_macro", "regime_change")),
)

#: ★모듈을 복원해도 남는 공백★ — BG1 에서 `strategy_registry` 가 복원되며 수익률
#: 테이블(`strategy_daily`)이 생겼다. 이제 공백은 "등록된 전략이 있어야 한다" 이다.
DATA_GAP = ("전략 수익률은 등록된 백테스트 실행에서 옵니다(strategy_registry, BG1) — "
            "등록된 전략이 없으면 돌릴 재료가 없습니다.")

_REASON = ("멀티전략·리얼리즘 백테스트는 이 저장소에서 동작하지 않습니다 — 필요한 "
           "코어 모듈 {n}개가 없습니다. 고장이 아니라 부재이며, 만들어 넣으면 배분 "
           "정책을 새로 정하는 일이라 별도 승인 사항입니다.")

_UNSUPPORTED_REASON = ("요청이 이 저장소에 아직 없는 기능을 골랐습니다({names}) — "
                       "고장이 아니라 부재입니다. 각 항목의 사유를 보세요.")


def _spec_exists(name: str) -> bool:
    """모듈이 **있는가**. ★실행하지 않는다★ — `find_spec` 은 파일만 찾는다."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def missing_now() -> list[str]:
    """레지스트리 중 **지금** 없는 모듈. 복원되면 스스로 빠진다."""
    return [m.module for m in MISSING if not _spec_exists(m.module)]


def _unsupported(gone: set[str]) -> list[dict[str, Any]]:
    out = []
    for feat, (field, value, reason) in FEATURES.items():
        need = [m.module for m in MISSING if feat in m.features and m.module in gone]
        if need:
            out.append({"feature": feat, "field": field, "value": value,
                        "reason": reason, "missing": need})
    return out


def status() -> dict[str, Any]:
    """가용 여부 + ★무엇이 왜 없는지★. `{}`·사유 없는 `"unavailable"` 을 내지 않는다.

    ★가용은 코어로 판정한다★ (BG4) — 기능 모듈이 없어도 그 기능을 안 고른 요청은
    돈다. 없는 것은 가용일 때도 `missing`·`unsupported_features` 로 계속 말한다.
    """
    gone = set(missing_now())
    missing = [{"module": m.module, "role": m.role, "reason": m.reason,
                "features": list(m.features)}
               for m in MISSING if m.module in gone]
    core = [m for m in missing if not m["features"]]
    return {
        "available": not core,
        "missing": missing,
        "unsupported_features": _unsupported(gone),
        "data_gap": DATA_GAP,
        "reason": _REASON.format(n=len(core)) if core else None,
        "since": SINCE,
    }


def http_unavailable():
    """코어가 없으면 `HTTPException(503, detail=status())`, 있으면 `None`.

    ★503 이지 500 이 아니다★ — 500 은 "서버가 고장 났다", 503 은 "이 기능이 지금
    없다" 다. 라우트는 이것을 **`try:` 앞에서** 부른다(뒤의 `except Exception → 500`
    이 HTTPException 까지 삼킨다).
    """
    s = status()
    if s["available"]:
        return None
    from fastapi import HTTPException
    return HTTPException(503, detail=s)


def http_unsupported(**requested: Any):
    """요청이 없는 기능을 골랐으면 `HTTPException(422, ...)`, 아니면 `None` (BG4).

    `requested` 는 요청 칸 → 값(`allocation_method="hrp"` 등). ★422 이지 503 이
    아니다★ — 서브시스템은 있고, **이 요청이** 없는 기능을 골랐다. 문은 이것도
    `try:` 앞에서 부른다.
    """
    hits = [u for u in status()["unsupported_features"]
            if requested.get(u["field"]) == u["value"]]
    if not hits:
        return None
    from fastapi import HTTPException
    return HTTPException(422, detail={
        "available": True,
        "unsupported": hits,
        "reason": _UNSUPPORTED_REASON.format(
            names=", ".join(f"{u['field']}={u['value']}" for u in hits)),
        "since": SINCE,
    })
