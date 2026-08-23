"""현재 기업 상태 → CompanySnapshot 빌더 (P2-1)

Company 탭의 라이브 계산을 불변 스냅샷으로 굳혀, 언더라이팅이 ID 로 참조할 수 있게
한다. 지금까지 밸류에이션·이익의 질·리스크·피어는 화면을 그릴 때마다 다시 계산됐고,
**어떤 가정·어떤 시점의 재무로 그 판단이 나왔는지** 남는 곳이 없었다.

★계산을 옮기지 않고 호출해서 담는다★
──────────────────────────────────────────────────────────────────────────────
이 모듈은 새 산수를 하나도 짓지 않는다. 이미 있는 것을 부른다:

| 섹션 | 부르는 것 |
|---|---|
| `valuation` | `ValuationEngine.evaluate` + `resolve_default_params` 의 가정 전체 |
| `quality` | `company_analytics.financial_deep` — 발생액·QoE·red flag·듀폰·ROIC−WACC |
| `risk` | `company_analytics.risk_deep` — Altman·Beneish·커버리지·금리 스트레스 |
| `peers` | `company_analytics.comps_table` |
| `financials` | `dart_history.load_history` 연간 행 |
| `factors` | `FundamentalsStore.get_factors` |

같은 산수를 두 곳에 두면 반드시 갈라지고, 갈라져도 타입 에러가 나지 않는다 —
이 저장소가 A1(`currentSig`/`req`)과 R0(오버레이 컴파일)에서 두 번 값을 치른 실수다.

★정직성 규약 — 우리는 재무의 공표일을 모른다★
──────────────────────────────────────────────────────────────────────────────
설계 문서는 `publication_dates` 의 출처를 `pit_store` 로 적었다. 코드를 읽으면
**pit_store 는 공표일을 모른다**:

  · 가용성을 **정적 시차 규칙**으로 판정한다 — 분기 45일 · 연간 90일
    (`pit_store.DISCLOSURE_LAG_DAYS` / `ANNUAL_LAG_DAYS`)
  · `dart_history.load_history` 행에는 `year/reprt/month/seq` 뿐 — **접수일이 없다**
  · `rcept_dt` 는 **내부자 공시에만** 파싱된다(`dart_client.py:570`)
  · 정정공시(restatement) 이력은 어디에도 없다

그래서 여기서 만드는 `publication_dates` 는 **규칙에서 파생한 추정 가용일**이고,
값 옆에 그 사실을 적는다. 그리고 그 판정을 손으로 하지 않고 기존
`pit_macro.derive_usage(has_vintage=False, …)` 에 태워 스냅샷 전체가
**forward_only** 로 떨어지게 한다 — 전방 리서치 맥락으로는 쓸 수 있지만 과거
시뮬레이션에서는 구조적으로 차단된다. `regime_snapshot_builder` 가 매크로 관측치에
대해 하는 일과 **같은 규약**이다(빈티지 없음 → forward_only).

관측일을 공표일로 베끼면 스냅샷이 backtest_eligible 로 보이게 되는데, 그것이 정확히
이 프로젝트가 막으려는 조용한 날조다.

★한 섹션이 죽어도 스냅샷은 산다★
섹션마다 따로 감싼다. 실패한 섹션은 `{available:false, reason}` 이 되고 나머지는
그대로 굳는다 — "계산에 실패했다" 와 "값이 0 이다" 는 완전히 다른 사실이다.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from src.data.company_snapshots import create_snapshot
from src.data.pit_macro import DataStatus, ResearchUsage, derive_usage

logger = logging.getLogger(__name__)

# 스냅샷에 담는 연간 재무 최대 연수 — `financial_deep` 이 쓰는 창과 같다.
_MAX_YEARS = 10

# 가격을 해석할 때 거슬러 올라가는 창. 마지막 종가 하나만 필요하므로 넉넉히 1년이면
# 충분하다(휴장·미적재 구간을 넘기기 위한 여유).
_PRICE_LOOKBACK_DAYS = 365


def _section(name: str, fn: Callable[[], Any]) -> dict:
    """섹션 하나를 계산한다. 실패는 **사유**가 되고 스냅샷을 죽이지 않는다."""
    try:
        out = fn()
    except Exception as e:  # noqa: BLE001
        logger.warning("CompanySnapshot 섹션 실패 %s: %s", name, e)
        return {"available": False,
                "reason": f"산출 중 오류가 발생했습니다: {type(e).__name__}"}
    if out is None:
        return {"available": False, "reason": "산출값이 없습니다"}
    if isinstance(out, dict):
        # ★원본이 이미 `available` 을 말하면 덮지 않는다★ `financial_deep` 은 재무
        # 미적재를 `available:false` + note 로 이미 정직하게 답한다. 여기서 True 를
        # 씌우면 그 정직함이 지워진다.
        return out if "available" in out else {"available": True, **out}
    return {"available": True, "value": out}


def _resolve_price(code: str, price: float | None) -> tuple[float | None, str]:
    """(가격, 출처). 못 구하면 `(None, "unavailable")` — 지어내지 않는다.

    ★창의 끝은 **오늘**이어야 한다★ 처음에는 "넉넉하게" `2099-12-31` 로 두었는데,
    mock 로더는 요청한 범위를 **그대로 생성**하므로 74년치(19,829행)를 만들고 그
    마지막(2099-12-31) 종가가 잡혔다. 실측: 409원(2099) vs 40,263원(2026-08-21).
    가격을 명시하지 않고 만든 스냅샷은 밸류에이션·역DCF·확률분포가 **전부 그 숫자
    위에서** 돌았다. 내 테스트가 전부 가격을 명시해서 아무도 못 잡았다.

    실데이터 경로에서는 미래 구간이 비어 있어 차이가 없었지만, 미래를 요청하는 것
    자체가 잘못이다 — 없는 날의 가격을 묻고 있었다.
    """
    if price is not None and float(price) > 0:
        return float(price), "caller"
    try:
        from src.data.ohlcv_loader import load_ohlcv_unified
        today = datetime.now().date().isoformat()
        start = (datetime.now().date() - timedelta(days=_PRICE_LOOKBACK_DAYS)).isoformat()
        d = load_ohlcv_unified(code, start, today, prefer="auto")
        if d is not None and not d.empty:
            return float(d["close"].iloc[-1]), "ohlcv_loader"
    except Exception as e:  # noqa: BLE001
        logger.warning("가격 해석 실패 %s: %s", code, e)
    return None, "unavailable"


def _annual_rows(code: str) -> list[dict]:
    from src.data.dart_history import REPRT_ANNUAL, load_history
    return [r for r in load_history(str(code)) if r.get("reprt") == REPRT_ANNUAL]


def _period_end(year: int, month: int) -> date:
    """보고 기간의 마지막 날 — 분기·연간 모두 해당 월의 말일."""
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return nxt - timedelta(days=1)


def publication_dates(code: str) -> dict:
    """★공표일이 아니라 '규칙으로 추정한 가용일' 이다★ 이름값을 하지 않도록 못을 박는다.

    실제 DART 접수일과 정정공시 이력은 이 저장소에 없다. 그래서 이 블록은 숫자와
    **함께 그 한계를 싣고**, `research_usage` 가 그 한계를 강제한다.
    """
    from src.data.dart_history import _REPRT_MONTH, load_history
    from src.engine.pit_store import ANNUAL_LAG_DAYS, DISCLOSURE_LAG_DAYS, REPRT_ANNUAL

    rows = load_history(str(code))
    if not rows:
        return {"available": False,
                "reason": "재무 시계열이 적재되지 않아 가용일을 추정할 수 없습니다"}

    out = []
    for r in rows[-(_MAX_YEARS * 4):]:
        month = _REPRT_MONTH.get(str(r.get("reprt")))
        if month is None:
            continue
        end = _period_end(int(r["year"]), month)
        lag = ANNUAL_LAG_DAYS if str(r.get("reprt")) == REPRT_ANNUAL else DISCLOSURE_LAG_DAYS
        out.append({
            "year": int(r["year"]), "reprt": str(r["reprt"]),
            "period_end": end.isoformat(),
            "estimated_available_from": (end + timedelta(days=lag)).isoformat(),
            "lag_days": lag,
        })
    return {
        "available": bool(out),
        "reason": None if out else "보고서 코드를 해석할 수 있는 행이 없습니다",
        "method": "static_lag_rule",
        "lag_days": {"annual": ANNUAL_LAG_DAYS, "quarterly": DISCLOSURE_LAG_DAYS},
        "has_vintage": False,
        "rows": out,
        # ★이 문장이 이 블록의 존재 이유다★
        "warning": ("이 날짜는 **실제 공표일이 아니라 정적 시차 규칙(연간 90일 · "
                    "분기 45일)으로 추정한 가용일**입니다. DART 접수일과 정정공시"
                    "(restatement) 이력은 이 저장소에 없으므로 개정 편향이 존재하며, "
                    "그래서 이 스냅샷은 backtest_eligible 이 될 수 없습니다."),
    }


def _valuation_inputs(code: str, price: float) -> tuple:
    """(엔진, 가정, params, load_statement 결과) — ★재무를 한 번만 읽는다★

    P2-1 이 실측한 것이 "딥 탭 재무이력 3회 읽기" 였다. 스냅샷 하나를 만들면서
    밸류에이션과 역DCF 가 각자 재무를 불러오면 그 결함을 안에서 되풀이하는 것이다.
    준비된 `fs` 를 한 번 얻어 둘이 나눠 쓴다.
    """
    from src.data.dart_client import DARTClient
    from src.engine.company_analytics import resolve_default_params
    from src.engine.valuation.valuation_models import ValuationEngine, ValuationParams

    d = resolve_default_params(code)
    params = ValuationParams(risk_free_rate=d["rf"], market_premium=d["erp"],
                             beta=d["beta"], terminal_growth_rate=d["g"],
                             projection_years=int(d["years"]))
    engine = ValuationEngine(DARTClient())
    return engine, d, params, engine.load_statement(code, price)


def _valuation(code: str, price: float, prepared: tuple) -> dict:
    engine, d, params, loaded = prepared
    u = engine.evaluate(code, price, params=params, statement=loaded)
    return {
        "available": True,
        "ticker": u.ticker, "corp_name": u.corp_name,
        "current_price": u.current_price, "intrinsic_value": u.intrinsic_value,
        "gap_pct": u.gap_pct, "verdict": u.verdict, "is_mock": bool(u.is_mock),
        "models": [{"model": m.model,
                    "intrinsic_value": m.intrinsic_value_per_share,
                    "available": m.available, "error": m.error,
                    "components": m.components, "assumptions": m.assumptions}
                   for m in u.models],
        "financial_summary": u.financial_summary,
        "params": u.params,
        # ★가정을 값과 함께 굳힌다★ 나중에 이 스냅샷을 다시 열었을 때 "무엇을 믿고
        # 이 적정가가 나왔는가" 에 답할 수 있어야 한다 — 출처 라벨까지 그대로.
        "assumptions": d,
    }


def _implied(prepared: tuple, price: float) -> dict:
    """역DCF — ★값이 아니라 **가정**을 굳히는 것이 언더라이팅이다★ (P2-2)

    "적정가 83,000원" 은 우리 가정의 결과일 뿐이지만 "시장은 연 11.4% 성장을 믿고
    있다" 는 반증 가능한 명제다. 근이 없거나(적자·마이너스 FCF) 단조가 아니면
    `reverse_dcf` 가 사유를 돌려주고, `_section` 이 그것을 그대로 굳힌다.
    """
    from src.engine.valuation.reverse_dcf import reverse_dcf

    _engine_obj, _d, params, loaded = prepared
    if not loaded["available"]:
        return {"available": False,
                "reason": loaded["reason"] or "재무제표를 가져오지 못했습니다"}
    return reverse_dcf(loaded["fs"], params, price)


def _valuation_dist(prepared: tuple, price: float) -> dict:
    """확률적 밸류에이션 P10~P90 — ★점 하나를 확률 진술로★ (P2-3)

    준비된 `fs` 를 그대로 쓰므로 재무 읽기가 **늘지 않는다**. 표본이 얇거나 TV 발산
    기각이 많으면 `valuation_distribution` 이 사유를 돌려주고 `_section` 이 그대로
    굳힌다.
    """
    from src.engine.valuation.valuation_distribution import valuation_distribution

    _engine_obj, _d, params, loaded = prepared
    if not loaded["available"]:
        return {"available": False,
                "reason": loaded["reason"] or "재무제표를 가져오지 못했습니다"}
    return valuation_distribution(loaded["fs"], params, price)


def _macro_sensitivity(code: str, prepared: tuple) -> dict:
    """매크로 민감도 — ★구조적과 통계를 **절대 섞지 않는다**★ (P2-4)

    둘은 인식론적으로 다른 물건이다: 구조적 채널은 모델의 항등식(표본 0)이고
    통계 채널은 60개월짜리 표본의 추정이다. 한 표에 나란히 놓으면 읽는 사람이
    같은 종류의 숫자로 읽는다. 블록을 나누고 각자 `method` 를 달고 나간다.
    """
    from src.engine.valuation.macro_sensitivity import (
        macro_sensitivity,
        statistical_sensitivity,
    )

    _engine_obj, _d, params, loaded = prepared
    if not loaded["available"]:
        return {"available": False,
                "reason": loaded["reason"] or "재무제표를 가져오지 못했습니다"}

    structural = macro_sensitivity(loaded["fs"], params)
    statistical = statistical_sensitivity(code)
    return {
        "available": bool(structural.get("available") or statistical.get("available")),
        "structural": structural,
        "statistical": statistical,
        "note": ("두 블록은 다른 종류의 숫자입니다 — structural 은 모델의 항등식이라 "
                 "표본이 없고, statistical 은 월별 표본의 추정이라 표준오차가 있습니다."),
    }


def _provenance(code: str, price_source: str, sections: dict) -> dict:
    from src.data.mock_gate import mock_allowed
    unavailable = sorted(k for k, v in sections.items()
                         if isinstance(v, dict) and not v.get("available"))
    return {
        "available": True,
        "code": str(code),
        "price_source": price_source,
        "mock_allowed": bool(mock_allowed()),
        "unavailable_sections": unavailable,
        "reasons": {k: (sections[k].get("reason") or sections[k].get("note"))
                    for k in unavailable},
        "note": ("미가용 섹션은 값을 지어내지 않고 사유를 남깁니다 — "
                 "'계산에 실패했다' 와 '값이 0 이다' 는 다른 사실입니다."),
    }


def _data_status(valuation: dict, any_available: bool) -> DataStatus:
    """★real 을 주장하지 않는다★

    `regime_snapshot_builder` 와 같은 판정이다 — mock 출처는 mock, 그 외에는
    공표시각을 확정할 수 없으므로 **partial** 이다. 재무가 실제 DART 값이어도
    접수일과 정정 이력을 모르는 한 real 이라고 말할 근거가 없다.
    """
    if not any_available:
        return DataStatus.UNAVAILABLE
    if valuation.get("is_mock"):
        return DataStatus.MOCK
    return DataStatus.PARTIAL


def build_and_store(code: str, price: float | None = None,
                    as_of: str | None = None,
                    thesis: dict | None = None) -> str | None:
    """현재 기업 상태를 스냅샷으로 굳힌다. 성공 시 snapshot_id, DB 미가용 시 `None`.

    ★`thesis` 만은 계산되지 않고 **작성된다**★ 다른 섹션은 빌더가 엔진을 호출해
    산출하지만 논지는 사람이 쓴 입력이다. 여기서는 검증·분류만 해서 굳힌다.
    스냅샷이 불변이므로 **논지를 고치면 새 스냅샷**이 된다 — "그때 무엇을
    믿었는가" 가 그대로 남는다.
    """
    resolved_price, price_source = _resolve_price(code, price)
    as_of = as_of or datetime.now().date().isoformat()

    no_price = {"available": False,
                "reason": "현재가를 구할 수 없어 이 섹션을 산출하지 않았습니다"}

    sections: dict[str, dict] = {
        "financials": _section("financials", lambda: _financials(code)),
        "publication_dates": _section("publication_dates", lambda: publication_dates(code)),
        "quality": _section("quality", lambda: _quality(code)),
        "factors": _section("factors", lambda: _factors(code)),
        "peers": _section("peers", lambda: _peers(code)),
    }
    if resolved_price is None:
        sections["valuation"] = dict(no_price)
        sections["implied"] = dict(no_price)
        sections["valuation_dist"] = dict(no_price)
        sections["macro_sensitivity"] = dict(no_price)
        sections["risk"] = dict(no_price)
    else:
        # 재무는 여기서 **한 번만** 읽고 밸류에이션·역DCF 가 나눠 쓴다.
        prepared = _valuation_inputs(code, resolved_price)
        sections["valuation"] = _section(
            "valuation", lambda: _valuation(code, resolved_price, prepared))
        sections["implied"] = _section(
            "implied", lambda: _implied(prepared, resolved_price))
        sections["valuation_dist"] = _section(
            "valuation_dist", lambda: _valuation_dist(prepared, resolved_price))
        sections["macro_sensitivity"] = _section(
            "macro_sensitivity", lambda: _macro_sensitivity(code, prepared))
        sections["risk"] = _section("risk", lambda: _risk(code, resolved_price))

    any_available = any(v.get("available") for v in sections.values())
    status = _data_status(sections["valuation"], any_available)

    # ★손으로 지정하지 않는다★ 빈티지가 없으므로 forward_only 로 떨어진다.
    usage = derive_usage(
        has_vintage=False,
        depth_ok=bool(sections["financials"].get("available")),
        lag_known=True,
        has_source=any_available,
    )
    if usage is ResearchUsage.BACKTEST_ELIGIBLE:  # pragma: no cover - 도달 불가
        raise AssertionError("빈티지가 없는데 backtest_eligible 이 나왔다 — derive_usage 계약 위반")

    # 논지는 선택 — 없으면 섹션이 사유를 달고 비어 있는다(기본 동작 불변).
    sections["thesis"] = _section("thesis", lambda: _thesis(code, thesis))

    sections["provenance"] = _provenance(code, price_source, sections)

    return create_snapshot(
        code=str(code), as_of=as_of,
        price=resolved_price, price_source=price_source,
        data_status=status.value, research_usage=usage.value,
        **sections,
    )


# ── 섹션 산출 — 전부 **호출**이다 (여기에 산수를 짓지 않는다) ─────────────────
def _financials(code: str) -> dict:
    rows = _annual_rows(code)[-_MAX_YEARS:]
    if not rows:
        return {"available": False,
                "reason": "재무 시계열 미적재 — Data Infra 에서 '재무시계열' 적재 후 표시"}
    return {"available": True, "rows": rows, "n_years": len(rows),
            "years": [int(r["year"]) for r in rows]}


def _quality(code: str) -> dict:
    from src.engine.company_analytics import financial_deep
    return financial_deep(code)


def _risk(code: str, price: float) -> dict:
    from src.engine.company_analytics import risk_deep
    return risk_deep(code, price)


def _peers(code: str) -> dict:
    from src.engine.company_analytics import comps_table
    return comps_table(code)


def _factors(code: str) -> dict:
    from src.data.fundamentals_store import FundamentalsStore
    f = FundamentalsStore.get_default().get_factors(code)
    if not f:
        return {"available": False, "reason": "팩터 스토어에 이 종목의 값이 없습니다"}
    return {"available": True, "factors": f}


def _thesis(code: str, thesis: dict | None) -> dict:
    """논지 검증·분류 — ★여기서 논지를 짓지 않는다★ 받은 것을 검산할 뿐이다."""
    if thesis is None:
        return {"available": False,
                "reason": "논지가 작성되지 않았습니다 — 논지는 산출물이 아니라 입력입니다"}
    from src.engine.company_thesis import thesis_to_sell_conditions, validate_thesis
    out = validate_thesis(thesis, code=code)
    # 검증에 실패해도 원문과 사유를 함께 굳힌다 — "그때 이 논지가 왜 검증되지
    # 않았는가" 가 나중에 읽을 수 있는 기록이다.
    out["authored"] = thesis
    out["sell_conditions"] = thesis_to_sell_conditions(thesis, code=code)
    return out
