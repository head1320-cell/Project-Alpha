"""`DataLineage` — 값이 **어디서 어떤 시점 기준으로** 왔는지 (§3.4, Phase 12b).

11a 감사가 A3 로 적은 것: §3.4 가 요구하는 `DataLineage` 가 **코드에 아예 없었다**
(타입·필드·UI 0건). §8.1 우측 패널의 "lineage" 행도 Phase 6 배달로 적혀 있었으나 거짓이었다.

★계보는 "무엇을 계산했나" 가 아니라 "무엇을 읽었나" 다★
─────────────────────────────────────────────────────────────────────────────
변환 사슬을 팩터 33개에 손으로 적으면 대부분이 추측이 된다(12a 에서 같은 함정을 피했다).
그래서 여기서는 **읽기**만 기술한다 — 어떤 소스의 어떤 시리즈를, 어떤 빈티지 기준으로,
mock 폴백이 열린 상태에서 읽었는지. 이것들은 전부 코드에서 유도 가능한 사실이다.

★`mock_fallback_allowed` 는 "mock 을 썼다" 가 아니다★
`mock_gate.mock_allowed()` 는 **허용 여부**를 판정한다. 실제로 어느 계층(DB/KIS/mock)이
답했는지는 읽기마다 다르고, 그것을 추적하려면 데이터 계층 전체에 계측을 넣어야 한다.
지금 아는 사실만 적는다 — 모르는 것을 아는 척하는 것이 이 문서 전체가 막으려는 일이다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

#: 빈티지 기준 — 값이 "그 시점에 알 수 있었던 것" 인지를 결정하는 규칙.
VINTAGE_BASES = (
    "alfred_realtime",           # ALFRED realtime_start/end 로 그 시점 공표본을 읽는다
    "latest_revision",           # 최신 개정본 — 과거 채점에 쓰면 개정 편향
    "price_truncation",          # etf_prices.as_of(m) 로 시계열을 잘라 읽는다
    "not_applicable",            # 소스가 없다
)


@dataclass(frozen=True)
class DataLineage:
    """팩터 하나의 데이터 계보. **읽기 사실만** 담는다."""
    factor_id: str
    source: str                       # fred_alfred | ecos | price_series | none
    inputs: list[str] = field(default_factory=list)      # 시리즈 id 또는 입력 설명
    vintage_basis: str = "not_applicable"
    release_lag: str | None = None
    revision_policy: str | None = None
    mock_fallback_allowed: bool = False
    caveats: list[str] = field(default_factory=list)
    resolved_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _source_of(entry: dict) -> str:
    """카탈로그 항목에서 소스를 유도한다 — 인용문이 이미 그것을 말하고 있다."""
    if entry.get("availability") == "unavailable":
        return "none"
    prov = (entry.get("provenance") or "")
    if "ALFRED" in prov or "FRED" in prov:
        # FRED/ECOS 를 함께 적은 범용 팩터가 있다 — 둘 다 가능하다고 말한다.
        return "fred_or_ecos" if "ECOS" in prov else "fred_alfred"
    if "ECOS" in prov:
        return "ecos"
    return "price_series"


def _vintage_basis(entry: dict, source: str) -> str:
    if source == "none":
        return "not_applicable"
    if source in ("fred_alfred", "ecos", "fred_or_ecos"):
        # ★as_of 를 요구하는 팩터만 빈티지 경로로 읽힌다★ 그렇지 않으면 최신 개정본이다.
        return "alfred_realtime" if entry.get("requires_as_of") else "latest_revision"
    return "price_truncation"


def lineage_for(entry: dict) -> DataLineage:
    """카탈로그 항목 → 계보. 순수 함수이며 네트워크를 건드리지 않는다."""
    from src.data.mock_gate import mock_allowed

    source = _source_of(entry)
    basis = _vintage_basis(entry, source)

    inputs: list[str] = []
    sid = (entry.get("params") or {}).get("series_id")
    if sid:
        inputs.append(str(sid))
    elif source in ("fred_alfred", "ecos", "fred_or_ecos"):
        # 시리즈를 파라미터로 받지 않는 전용 팩터 — 인용문이 시리즈를 적고 있다.
        inputs.append(entry.get("provenance", ""))
    elif source == "price_series":
        inputs.append(f"종가 시계열 ({entry.get('evaluation_frequency', 'day')} 단위)")

    caveats: list[str] = []
    if basis == "latest_revision":
        caveats.append(
            "최신 개정본으로 읽습니다 — 과거 시점을 채점하는 데 쓰면 그때 알 수 없던 "
            "정보가 섞입니다(개정 편향).")
    if entry.get("revision_policy") == "revised":
        caveats.append("이 시리즈는 개정됩니다 — 빈티지를 지정하지 않으면 값이 나중에 달라집니다.")
    if entry.get("availability") == "unavailable":
        caveats.append(entry.get("unavailable_reason") or "데이터 소스를 보유하고 있지 않습니다.")
    if source == "price_series" and mock_allowed():
        caveats.append(
            "KIS_USE_MOCK=1 이라 실데이터가 없으면 결정론적 mock 으로 대체될 수 있습니다 — "
            "값의 크기를 실측으로 읽지 마세요.")

    return DataLineage(
        factor_id=entry.get("id", ""),
        source=source,
        inputs=inputs,
        vintage_basis=basis,
        release_lag=entry.get("release_lag"),
        revision_policy=entry.get("revision_policy"),
        mock_fallback_allowed=mock_allowed(),
        caveats=caveats,
        resolved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def lineage_for_factor(factor_id: str) -> DataLineage | None:
    """id 로 조회. 카탈로그에 없으면 **None** — 빈 계보를 지어내지 않는다."""
    from src.engine.timing_factors import CATALOG_BY_ID

    entry = CATALOG_BY_ID.get(factor_id)
    return None if entry is None else lineage_for(entry)
