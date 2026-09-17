"""성과의 ★종류★ — "이 수치가 무엇인가" (Z1)
==============================================================================
설계: `docs/specs/2026-09-12-addendum-scorecard.md` 합격기준 #3
소비자: `src/api/backtest_run_routes.py` · `screener_routes.py` ·
        `allocation_routes.py` · `stage11_routes.py` · `stage13_routes.py`
프런트: `frontend/src/shared/ui/PerfLabel.tsx`

## 왜 필요한가 — ★라벨을 프런트가 지어내면 장식이다★

배지 관용구가 넷 있었는데(`brun-badge` 시점정합 · `tbt-prov` 데이터출처 ·
`as-bt-badge` 데이터+OOS · 인라인 실행모드) ★어느 것도 성과의 종류를 말하지 않았다★.
그리고 "백테스트 페이지니까 BACKTEST" 는 사실이 아니라 **배치**다 — 같은 컴포넌트를
다른 데이터로 재사용하는 순간 거짓말이 된다. 그래서 **응답이 선언**하고 화면은 그린다.

## ★두 축을 섞지 않는다★

    kind        무슨 **성과**인가   백테스트 / 페이퍼 / 섀도 / 테스트베드 / 실계좌
    data_real   무슨 **데이터**인가  실데이터인가 합성인가

둘은 독립이다 — 실데이터 백테스트도, mock 데이터 페이퍼도 있다. 하나로 합치면
"mock 이니까 백테스트겠지" 같은 추론이 코드에 스며든다. Y2 에서 `evidence_level`
(근거의 종류)과 `confidence`(지지 정도)를 가른 것과 같은 규율이다.

## ★미상은 라벨이 아니다★

모르면 `KIND_UNKNOWN` 또는 `data_real=None` 이고, **왜 모르는지**를 함께 싣는다.
`False` 로 접으면 "합성이다" 라는 **없는 사실**이 생긴다(CLAUDE.md §4 `미상 ≠ 0`).
"""
from __future__ import annotations

from dataclasses import dataclass

#: 과거 데이터 위의 시뮬레이션.
KIND_BACKTEST = "backtest"
#: 모의투자 계좌의 실시간 집행.
KIND_PAPER = "paper"
#: 신호만 기록하고 주문은 내지 않는다.
KIND_SHADOW = "shadow"
#: 코스콤 RA 테스트베드의 표준 심사 환경.
#: ★어휘일 뿐 생산자가 없다★ — 이 저장소는 제출한 적이 없다.
KIND_RA_TESTBED = "ra_testbed"
#: 실계좌.
KIND_LIVE = "live"
#: ★판정 불가★ — 통과도 실패도 아니다.
KIND_UNKNOWN = "unknown"

PERF_KINDS = (KIND_BACKTEST, KIND_PAPER, KIND_SHADOW,
              KIND_RA_TESTBED, KIND_LIVE, KIND_UNKNOWN)

#: `ExecutionMode`(`src/execution/order_executor.py`) **하나만** 매핑한다.
#: ★저장소에 모드 어휘가 여섯이고 통합은 별도 승인 사항이다★ — 여기서 다른 어휘를
#: 끌어다 쓰면 일곱 번째 진실이 생긴다(채점표 §5-1).
_FROM_EXECUTION_MODE = {
    "SHADOW": KIND_SHADOW,
    "PAPER": KIND_PAPER,
    "LIVE": KIND_LIVE,
}

_NO_DATA_AXIS = ("실행 모드는 데이터가 실제인지 합성인지를 말하지 않습니다 — "
                 "다른 축입니다")
_UNKNOWN_MOCK = "이 실행이 실데이터였는지 기록돼 있지 않습니다"


@dataclass(frozen=True)
class PerfLabel:
    """성과 한 덩어리에 붙는 라벨. ★두 축을 한 객체에 담되 섞지 않는다.★"""
    kind: str
    kind_reason: str | None = None
    data_real: bool | None = None
    data_reason: str | None = None

    def to_dict(self) -> dict:
        return {"kind": self.kind, "kind_reason": self.kind_reason,
                "data_real": self.data_real, "data_reason": self.data_reason}


def backtest_label(*, is_mock_data: bool | None) -> PerfLabel:
    """백테스트 결과의 라벨. ★종류는 확실하고 데이터 축만 미상일 수 있다.★"""
    if is_mock_data is None:
        return PerfLabel(kind=KIND_BACKTEST, data_real=None,
                         data_reason=_UNKNOWN_MOCK)
    return PerfLabel(kind=KIND_BACKTEST, data_real=not bool(is_mock_data))


def execution_label(*, execution_mode: str | None) -> PerfLabel:
    """집행 성과의 라벨. ★알아보지 못한 모드는 `unknown` + 그 값★

    안전한 쪽(`paper`)으로도 기울지 않는다 — 기울면 다음 사람이 **확인되지 않은
    수치를 모의 성과로** 읽는다.
    """
    kind = _FROM_EXECUTION_MODE.get(execution_mode or "")
    if kind is None:
        seen = "없음" if execution_mode is None else repr(execution_mode)
        return PerfLabel(
            kind=KIND_UNKNOWN,
            kind_reason=f"실행 모드를 알아보지 못했습니다(본 값: {seen})",
            data_real=None, data_reason=_NO_DATA_AXIS)
    return PerfLabel(kind=kind, data_real=None, data_reason=_NO_DATA_AXIS)
