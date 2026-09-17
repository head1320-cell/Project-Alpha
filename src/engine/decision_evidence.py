"""결정 하나의 ★증거 롤업★ — *"이 판단이 무엇 위에 섰는가"* (AA3)
==============================================================================
설계: `docs/plans` AA · 애드덤 합격기준 #10
소비자: `src/api/allocation_routes.py::rebalance_decision_route` ·
        `src/api/diagnostics_routes.py`

## ★로드맵 문장이 그대로는 실행 불가였다★

로드맵은 *"`run_evidence.pit_evidence` 를 `RebalanceProposal` 에 실어 나른다"* 고
적었다. 그런데 `pit_evidence` 가 요구하는 네 축(`price_basis`·`universe`·
`macro_lookahead`·`fundamentals_pit`)은 **백테스트 엔진 산출물**이고 결정 경로에는
생산자가 **하나도 없다**. 없는 것을 나를 수는 없고, 없는 축을 지어내면 그것이야말로
이 저장소가 금지한 "타당성 제조" 다.

그래서 **어휘와 롤업 규칙은 `run_evidence` 것을 그대로 쓰고**(같은 함수를 부른다)
축만 결정 경로가 실제로 아는 것으로 세운다.

## 축 넷 — 전부 **필수**다

    price    가격 데이터 출처          coverage.source: db → ok · mock → degraded
    as_of    요청 절단일을 지켰는가     지킴 → ok · 어긋남 → degraded · ★미요청 → unknown★
    target   목표 비중의 출처가 선언됐나  optimize:* → ok
    macro    국면 경로가 굳혀진 것인가   ★선택 축★ 스냅샷 → ok · recomputed → degraded

★`as_of` 미요청을 `ok` 로 매기지 않는다★ — 결함은 아니지만 "시점 정합됐다" 는
**하지 않은 진술**이다. `미상 ≠ 통과`(CLAUDE.md §4).

★`macro` 만 선택 축인 이유 — 실측이 정했다★
`build_belief` 는 `conditional` 을 요청하지 않으면 `_NO_BELIEF` 를 돌려주고
국면 경로를 **아예 만들지 않는다**. 그 모듈의 주석이 그 구분을 이미 적었다 —
*"막힌 것이 아니라 **묻지 않은** 것이다."* 안 쓴 축에 `unknown` 을 매기면
"국면을 재려다 실패했다" 가 되는데, 그것은 일어나지 않은 일이다
(`run_evidence` 가 `macro`·`fundamentals` 를 다루는 규율과 같다).

★`macro` 축이 진짜 look-ahead 를 잡는다★ — `allocation_pipeline._regime_path_for`
는 스냅샷이 없으면 **현재 데이터로** 국면 경로를 다시 계산하고, 그 사실을
`path_source: "recomputed"` + *"결정 시점에 알 수 있었던 분류가 아닙니다"* 로 이미
적고 있었다. 아무도 그것을 판정으로 접어 올리지 않았을 뿐이다.

## ★신선도는 축이 아니다★

`allocation_pipeline._freshness` 의 note 가 이미 못 박았다 — *"이 값 하나로
'낡았다' 를 판정하지 마십시오."* 그래서 문턱을 지어내지 않고 **첨부**만 한다.
"""
from __future__ import annotations

from typing import Any

#: "이 표면에 해당하지 않는다" 를 뜻하는 표식. ★`None` 과 다르다★ —
#: `None` 은 "물었는데 없었다"(미상)이고 이것은 "묻지 않았다"(해당 없음)이다.
ABSENT = object()

from src.engine.run_evidence import (
    AXIS_DEGRADED,
    AXIS_OK,
    AXIS_UNKNOWN,
    rollup,
)

#: 축 이름 → 사람이 읽는 이름.
DECISION_AXIS_LABELS = {
    "price": "가격 출처",
    "as_of": "절단일 준수",
    "target": "목표 출처",
    "macro": "국면 경로",
}

#: ★둘은 언제나 필수다★ — 어떤 표면이든 가격을 읽고, 절단일을 쓰거나 안 쓴다.
#: 값이 없으면 `unknown` 으로 **남는다** — 빠지면 "못 쟀다" 가 "문제없다" 가 된다.
DECISION_REQUIRED_AXES = ("price", "as_of")

#: ★`target` 과 `macro` 는 **그 표면에 해당할 때만** 축이 된다★
#: 리밸런스 결정은 언제나 목표를 받으므로 `target` 이 필수처럼 동작하지만,
#: 보유 진단 표면(`/diagnostics/holdings`)은 목표를 다루지 않는다. 거기에
#: "목표 출처 미상" 을 달면 **묻지 않은 것을 못 쟀다고 적는 것**이다.
#: 축을 **생략**(`ABSENT`)하면 해당 없음이고, `None` 을 명시하면 "물었는데
#: 선언되지 않았다" 는 미상이다 — 둘은 다른 사실이다.
OPTIONAL_AXES = ("target", "macro")

_NO_MEASUREMENT = "측정값이 없습니다 — 이 결정에서 재지 못했습니다."


def _axis(state: str, reason: str | None, **detail: Any) -> dict[str, Any]:
    return {"state": state, "reason": reason, **detail}


def _price_axis(coverage: dict | None) -> dict[str, Any]:
    source = (coverage or {}).get("source")
    if source == "db":
        return _axis(AXIS_OK, None, source=source)
    if source == "mock":
        return _axis(AXIS_DEGRADED,
                     "가격이 합성값(mock)입니다 — 이 판단의 수치는 시장에서 온 "
                     "것이 아닙니다.", source=source)
    return _axis(AXIS_UNKNOWN,
                 "가격 출처가 선언되지 않았습니다 — 실데이터인지 합성인지 "
                 "알 수 없습니다.", source=source)


def _as_of_axis(requested: str | None, effective: str | None) -> dict[str, Any]:
    if not requested:
        # ★결함은 아니지만 통과도 아니다★ 절단일을 요청하지 않은 판단은
        # **재현 시점이 고정돼 있지 않다** — 나중에 같은 답을 낼 보장이 없다.
        return _axis(AXIS_UNKNOWN,
                     "절단일을 요청하지 않았습니다 — 이 판단은 재현 시점이 "
                     "고정돼 있지 않습니다.",
                     requested=None, effective=effective)
    if not effective:
        return _axis(AXIS_UNKNOWN,
                     "서버가 실제로 쓴 절단일을 알 수 없어 준수 여부를 잴 수 "
                     "없습니다.", requested=requested, effective=None)
    if str(effective) == str(requested):
        return _axis(AXIS_OK, None, requested=requested, effective=effective)
    # ★휴장일이면 자연히 어긋난다★ — 그래서 "위반" 이라 부르지 않고 두 값을 적는다.
    return _axis(AXIS_DEGRADED,
                 f"요청한 절단일({requested})과 실제로 쓴 절단일({effective})이 "
                 "다릅니다 — 휴장일이면 자연스러운 차이이지만, 그 차이만큼은 "
                 "요청한 시점의 정보집합이 아닙니다.",
                 requested=requested, effective=effective)


def _target_axis(target_source: Any) -> dict[str, Any] | None:
    """★`ABSENT` 는 "목표를 다루지 않는 표면" 이다★ — 축이 되지 않는다."""
    if target_source is ABSENT:
        return None
    if target_source:
        return _axis(AXIS_OK, None, source=target_source)
    return _axis(AXIS_UNKNOWN,
                 "목표 비중의 출처가 선언되지 않았습니다 — 어느 최적화기가 낸 "
                 "목표인지 알 수 없습니다.", source=None)


def _macro_axis(regime_path: Any) -> dict[str, Any] | None:
    """★`None` 은 "해당 없음" 이지 "못 쟀다" 가 아니다★

    조건부를 요청하지 않은 결정은 국면 경로를 만들지 않는다. 그 결정에 "국면
    미상" 을 매기면 하지 않은 시도를 실패로 적는 것이다.
    """
    if regime_path is None or regime_path is ABSENT:
        return None
    path = regime_path
    source = path.get("path_source")
    if source in ("mes", "regime_snapshot"):
        return _axis(AXIS_OK, None, path_source=source)
    if source == "recomputed":
        # ★관측된 look-ahead 다★ 상류가 이미 그렇게 적었다.
        return _axis(AXIS_DEGRADED,
                     path.get("path_note")
                     or ("국면 경로를 **현재 데이터로** 다시 계산했습니다 — "
                         "결정 시점에 알 수 있었던 분류가 아닙니다."),
                     path_source=source)
    return _axis(AXIS_UNKNOWN, path.get("reason") or _NO_MEASUREMENT,
                 path_source=source)


def decision_evidence(*, coverage: dict | None, as_of_requested: str | None,
                      target_source: Any = ABSENT, regime_path: Any = ABSENT,
                      freshness: dict | None = None) -> dict[str, Any]:
    """결정 하나의 증거 판정.

    Args:
        coverage: `_load_clean_returns` 가 낸 것(`source`·`as_of_effective`).
        as_of_requested: 호출자가 **요청한** 절단일. 없으면 `None`.
        target_source: `evidence.target_source`(예: `"optimize:mvo"`). 생략하면
            ★목표를 다루지 않는 표면★이라 이 축이 판정에서 빠진다. `None` 을
            **명시**하면 "물었는데 선언되지 않았다" 는 미상이다.
        regime_path: `allocation_pipeline._regime_path_for` 의 반환. ★`None` 이면
            조건부를 **묻지 않은** 결정이고, 이 축은 판정에서 빠진다★ — 물었는데
            경로를 못 만든 경우(`path_source=None` 인 딕트)와 다르다.
        freshness: `allocation_pipeline._freshness` 의 반환. ★판정하지 않고
            그대로 싣는다★ — 그 함수 자신이 "이 값 하나로 판정하지 말라" 고 적었다.

    Returns:
        `run_evidence.rollup()` 의 모양 + `freshness` + `note`.
    """
    axes: dict[str, dict | None] = {
        "price": _price_axis(coverage),
        "as_of": _as_of_axis(as_of_requested, (coverage or {}).get("as_of_effective")),
        "target": _target_axis(target_source),
        # ★`None` 이면 롤업에서 빠진다★ — 안 쓴 축은 판정에 들어가지 않는다.
        "macro": _macro_axis(regime_path),
    }
    # ★필수 축은 값이 없어도 사라지지 않는다★ (위 네 함수가 그것을 보장하지만,
    # 누가 축을 선택으로 바꿔도 여기서 다시 채워진다)
    for name in DECISION_REQUIRED_AXES:
        if axes.get(name) is None:
            axes[name] = _axis(AXIS_UNKNOWN, _NO_MEASUREMENT)

    return {
        **rollup(axes, DECISION_AXIS_LABELS),
        # ★축이 아니라 첨부다★ — 문턱을 지어내지 않는다.
        "freshness": freshness,
        "note": ("이 판정은 **이 결정이 선 근거의 시점·출처**에 대한 것입니다. "
                 "`verified` 라도 목표 비중이 옳다거나 수치가 정확하다는 뜻이 "
                 "아니고, 추정기 수준의 데이터 누출(전체표본 스케일링·윈저화)은 "
                 "어느 축도 보지 않습니다."),
    }
