"""ResearchContext — 모든 연구 계산을 통제하는 단일 컨텍스트 (벤치마크 §4, Priority S)

문서가 이것으로 막으려는 것:

    hidden dates · inconsistent snapshots · accidental look-ahead ·
    inconsistent macro state · non-reproducible results

★실측이 이 모듈의 존재 이유다★ `code_version()` 이 **세 벌 바이트 동일하게**
복사돼 있었다(`regime_snapshots`·`company_snapshots`·`research_runs`). 그리고
네 번째(`backtest_runs.engine_version`)는 복사되는 동안 **갈라졌다** —
`APP_VERSION` 폴백이 빠져서, `APP_VERSION` 만 설정한 환경에서는 백테스트 기록만
`"dev"` 가 된다. 복사본이 넷이면 언젠가 하나는 갈라진다는 것의 실물이다.

`as_of` 정책도 라우트(`allocation_routes._check_as_of`) 안에만 있었다 — "미래
`as_of` 는 고정이 아니라 **고정한 척**" 이라는 좋은 규칙인데 엔진이 알지 못했다.

★선언하지 않은 절단일을 지어내지 않는다★ 이 모듈의 가장 중요한 규칙이다.
`market/fundamental/macro_data_as_of` 를 `as_of` 로 기본값 채우면 "그 날짜로
잘랐다" 는 **주장**이 되는데, 실제로 강제한 적이 없다. 그것이 §4 가 말하는
hidden date 다. 비어 있으면 `unspecified` 로 **말한다.**

★범위★ 문서 §34 Phase 1 — "minimum required foundation. **Do not rewrite every
data source.**" 컨텍스트는 **가산**이고 어떤 엔진도 강제로 통과시키지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import date

# 절단일 필드 — `as_of` 와 달리 **선언되지 않으면 비워 둔다**.
CUTOFF_FIELDS = ("market_data_as_of", "fundamental_data_as_of", "macro_data_as_of")

_DATE_LEN = 10
FINGERPRINT_LEN = 16


@dataclass(frozen=True)
class ResearchContext:
    """연구 계산의 정보집합. ★동결★ — 도중에 바뀌면 재현성이 무의미하다."""
    as_of: str | None = None
    information_cutoff: str | None = None
    universe_id: str | None = None
    market_data_as_of: str | None = None
    fundamental_data_as_of: str | None = None
    macro_data_as_of: str | None = None
    data_snapshot_id: str | None = None
    engine_version: str | None = None
    risk_model_version: str | None = None

    def with_(self, **kw) -> ResearchContext:
        """파생 컨텍스트 — 원본은 그대로 둔다."""
        return replace(self, **kw)


def code_version() -> str:
    """빌드 식별자 — ★단일 출처★

    폴백 순서 `GIT_SHA → APP_VERSION → "dev"`. 저장소마다 복사되던 것을 여기로
    모은다(`backtest_runs` 는 `BACKTEST_ENGINE_VERSION` 을 앞에 두고 나머지를
    여기에 위임한다).
    """
    return os.getenv("GIT_SHA") or os.getenv("APP_VERSION") or "dev"


def data_source() -> str:
    """가격·시세 출처 라벨 — `mock_gate` 가 유일한 판정 기준이다."""
    try:
        from src.data.mock_gate import mock_allowed
        return "mock" if mock_allowed() else "db"
    except Exception:  # noqa: BLE001
        return "unknown"


def validate_as_of(as_of: str | None) -> str | None:
    """`as_of` 검증 — 문제가 있으면 **사유 문자열**, 없으면 `None`.

    ★엔진은 HTTP 를 모른다★ `HTTPException` 을 던지지 않는다. 라우트가 이 사유를
    받아 422 로 바꾼다 — 정책은 하나이되 표현은 계층마다 다르다.

    ★미래 `as_of` 를 거부한다★ 허용하면 `2099-01-01` 이 그냥 오늘 데이터를 주면서
    기록에는 "2099 시점으로 고정했다" 고 적힌다 — 고정이 아니라 **고정한 척**이다.
    """
    if as_of is None:
        return None
    if not isinstance(as_of, str) or len(as_of) != _DATE_LEN:
        return f"as_of 형식이 올바르지 않습니다 (YYYY-MM-DD): {as_of}"
    try:
        d = date.fromisoformat(as_of)
    except ValueError:
        return f"as_of 형식이 올바르지 않습니다 (YYYY-MM-DD): {as_of}"
    if d > date.today():
        return (f"as_of 는 과거여야 합니다 — 미래 날짜는 고정이 아니라 고정한 "
                f"척입니다: {as_of}")
    return None


def now(**kw) -> ResearchContext:
    """오늘 기준 컨텍스트. ★절단일은 채우지 않는다★ 선언한 것만 들어간다."""
    kw.setdefault("as_of", date.today().isoformat())
    kw.setdefault("information_cutoff", kw["as_of"])
    kw.setdefault("engine_version", code_version())
    return ResearchContext(**kw)


def _canonical(ctx: ResearchContext) -> dict:
    """지문용 정규형 — 키 정렬 + 데이터 출처 포함.

    ★출처를 지문에 넣는다★ mock 결과와 실데이터 결과가 **같은 지문**을 갖는 것이
    가장 위험한 재현성 거짓말이다.
    """
    body = dict(sorted(asdict(ctx).items()))
    body["_data_source"] = data_source()
    body["_code_version"] = code_version()
    return body


def fingerprint(ctx: ResearchContext) -> str:
    """컨텍스트 지문 — §36 "같은 Context → 같은 결과" 의 Context 쪽 절반."""
    blob = json.dumps(_canonical(ctx), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:FINGERPRINT_LEN]


def describe(ctx: ResearchContext) -> dict:
    """응답에 싣는 정직 블록 — ★무엇을 선언했고 무엇을 안 했는지★"""
    declared = {f: getattr(ctx, f) for f in CUTOFF_FIELDS if getattr(ctx, f)}
    unspecified = [f for f in CUTOFF_FIELDS if not getattr(ctx, f)]
    return {
        "as_of": ctx.as_of,
        "information_cutoff": ctx.information_cutoff,
        "universe_id": ctx.universe_id,
        "data_snapshot_id": ctx.data_snapshot_id,
        "engine_version": ctx.engine_version,
        "risk_model_version": ctx.risk_model_version,
        "code_version": code_version(),
        "data_source": data_source(),
        "cutoffs_declared": declared,
        # ★비어 있는 절단일을 as_of 로 채우지 않는다★ 채우면 강제한 적 없는
        # 절단을 주장하는 것이고, 그것이 문서 §4 가 말하는 hidden date 다.
        "cutoffs_unspecified": unspecified,
        "fingerprint": fingerprint(ctx),
        "note": ("선언하지 않은 절단일은 채우지 않습니다 — 비어 있다는 것은 "
                 "'그 날짜로 잘랐다' 가 아니라 '자른 적이 없다' 는 뜻입니다"),
    }
