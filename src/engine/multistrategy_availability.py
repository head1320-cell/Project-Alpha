"""멀티전략 서브시스템 — ★무엇이 없는지 한 곳에서 말한다★ (BF)
==============================================================================
소비자: `src/api/stage11_routes.py`(multibacktest) · `src/api/stage12_routes.py`
(realism) · 트립와이어 `tests/test_no_dangling_imports.py`

## 실측 (2026-09-24)

`multi_strategy_backtest` · `realism_engine` · `counterfactual_analyzer` 는 모듈
**다섯**을 import 하는데 다섯 다 저장소에 없다. 2026-06-10 *"본체 코드베이스 이식
(0605_1019 스냅샷)"* 에 import 가 이미 끊긴 채 들어왔고, 그 경로의 커밋은 0건이다
(GitHub 이력). import 가 함수 안에 있어서 모듈 로드·테스트·린트 어느 것도 못 잡았고,
요청마다 `500 No module named 'src.engine.allocator'` 가 났다.

★모듈만이 아니다★ — 등록 전략의 일별 수익률을 담는 테이블이 스키마에 없다. 모듈을
복원해도 돌릴 재료가 없다.

## ★이 모듈이 하지 않는 것★

- **없는 것을 만들지 않는다.** 배분기·국면 분류기는 배분 정책이고(CLAUDE.md §3
  별도 승인), 빈 껍데기를 두면 "동작한다" 로 위장한다.
- **엔진을 고치지 않는다.** 문(라우트)이 먼저 묻고 503 + 사유를 낸다(§6).
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


MISSING: tuple[MissingModule, ...] = (
    MissingModule(
        module="src.engine.allocator", needed_by=(_ENGINE,),
        role="전략 배분기(MultiStrategyAllocator)",
        reason=("inverse_vol·hrp·hrp_macro 로 전략 비중을 정하는 자리입니다. "
                "hrp_macro 는 매크로 기울기를 얹는 배분 정책이라 새로 만들면 "
                "별도 승인 사항입니다.")),
    MissingModule(
        module="src.execution.order_netting", needed_by=(_ENGINE,),
        role="주문 네팅(OrderNettingEngine)",
        reason=("전략 간 상쇄 주문을 합치는 자리입니다. 엔진은 지금 네팅 절감을 "
                "회전율 × 1.5 로 추정하고 있어 이 모듈의 결과를 쓰지 않습니다.")),
    MissingModule(
        module="src.data.macro_feed", needed_by=(_ENGINE,),
        role="매크로 피드(MacroFeedCollector)",
        reason=("hrp_macro 용 매크로 행렬을 만드는 자리입니다. 저장소의 매크로 "
                "계층(pit_macro·macro_observation_store)과는 다른 이름의 모듈입니다.")),
    MissingModule(
        module="src.engine.regime_model",
        needed_by=(_ENGINE, "src/engine/realism_engine.py"),
        role="4국면 분류기(MultiRegimeModel)",
        reason=("GOLDILOCKS·REFLATION·STAGFLATION·DEFLATION 으로 날짜를 분류하는 "
                "자리입니다. 저장소 어디에도 이 분류기가 없고, 만들면 국면-배분 "
                "정책이라 별도 승인 사항입니다.")),
)

#: ★모듈을 복원해도 남는 공백★ — BG1 에서 `strategy_registry` 가 복원되며 수익률
#: 테이블(`strategy_daily`)이 생겼다. 이제 공백은 "등록된 전략이 있어야 한다" 이다.
DATA_GAP = ("전략 수익률은 등록된 백테스트 실행에서 옵니다(strategy_registry, BG1) — "
            "등록된 전략이 없으면 돌릴 재료가 없습니다.")

_REASON = ("멀티전략·리얼리즘 백테스트는 이 저장소에서 동작하지 않습니다 — 필요한 "
           "모듈 {n}개가 없고 돌릴 데이터도 없습니다. 고장이 아니라 부재이며, "
           "만들어 넣으면 배분 정책을 새로 정하는 일이라 별도 승인 사항입니다.")


def _spec_exists(name: str) -> bool:
    """모듈이 **있는가**. ★실행하지 않는다★ — `find_spec` 은 파일만 찾는다."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def missing_now() -> list[str]:
    """레지스트리 중 **지금** 없는 모듈. 복원되면 스스로 빠진다."""
    return [m.module for m in MISSING if not _spec_exists(m.module)]


def status() -> dict[str, Any]:
    """가용 여부 + ★무엇이 왜 없는지★. `{}`·사유 없는 `"unavailable"` 을 내지 않는다."""
    gone = set(missing_now())
    missing = [{"module": m.module, "role": m.role, "reason": m.reason}
               for m in MISSING if m.module in gone]
    return {
        "available": not missing,
        "missing": missing,
        "data_gap": DATA_GAP,
        "reason": _REASON.format(n=len(missing)) if missing else None,
        "since": SINCE,
    }


def http_unavailable():
    """없으면 `HTTPException(503, detail=status())`, 있으면 `None`.

    ★503 이지 500 이 아니다★ — 500 은 "서버가 고장 났다", 503 은 "이 기능이 지금
    없다" 다. 라우트는 이것을 **`try:` 앞에서** 부른다(뒤의 `except Exception → 500`
    이 HTTPException 까지 삼킨다).
    """
    s = status()
    if s["available"]:
        return None
    from fastapi import HTTPException
    return HTTPException(503, detail=s)
