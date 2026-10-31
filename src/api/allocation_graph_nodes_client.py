"""AAS 그래프 — 고객·계좌·목표·보유 진단 노드 (CF 3부 PB1) · ★관측만 — 비중을 바꾸지 않는다★
==============================================================================
스펙 `docs/superpowers/specs/2026-10-16-cf-comfy-canvas-claude-design.md` §8.2 · 사용자 결정(2026-10-23): 증권사 PB 의 자산관리 기능.
테스트 `tests/test_pb1_client_nodes.py`.

- `client_profile` 고객 — 별칭(개인정보 모양이면 거절 · `domain/pii_guard`) · 위험 성향 · 출처 · 평가일 · 투자 기간.
  ★비면 미상 + 사유★ — 기본값으로 채우지 않는다(`investor_profile` 의 규율).
- `account` 계좌 점검 — 비중(+고객) → 기존 `/accounts/diagnose`(AD4)를 ★그대로★ 부른다. 선언하지 않은 한도는 '판정 못 함'(통과가 아니다).
  공매도(음수) 비중은 사유와 함께 실패 — 계좌 한도는 롱온리 보유를 잰다.
- `goal` 목표까지 — 계좌 → 기존 `/accounts/glidepath`(AO4)를 ★그대로★. 실적 ⟂ 계획 규율은 그 함수가 지킨다.
- `holdings_check` 보유 진단 — 비중 → 기존 `/diagnostics/holdings`(AA5)를 ★그대로★.

★어느 것도 비중을 바꾸지 않고 주문하지 않는다★ — 최적화기·주문 경로를 import 하지 않는다(테스트가 AST 로 확인한다).
최적화기가 고객·계좌·목표를 모른다는 사실을 설명에 적는다. 고객 성향을 배분에 반영하는 것은 별도 승인 사항이다(CLAUDE.md §3).
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal

import numpy as np
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, FAILED, UNKNOWN, _practice, _t
from src.api.allocation_graph_nodes import _labels, _ui
from src.api.json_safe import finite_payload
from src.data.exposure_taxonomy import AssetClass
from src.data.mock_gate import mock_allowed
from src.domain.account_policy import ACCOUNT_TYPES, LIMIT_KINDS
from src.domain.investor_profile import PROFILE_SOURCES, RISK_TOLERANCE_LEVELS, SOURCE_UNKNOWN
from src.domain.pii_guard import ALIAS_MAX, pii_reason
from src.engine import portfolio_graph as pg

P = pg.Port
_FORBID = ConfigDict(extra="forbid")
_DATE = r"^\d{4}-\d{2}-\d{2}$"

RISK_PLAIN = {"conservative": "안정형", "moderate_conservative": "안정추구형", "moderate": "위험중립형",
              "moderate_aggressive": "적극투자형", "aggressive": "공격투자형"}
SOURCE_PLAIN = {"survey": "설문", "user_declared": "고객이 말함", "default": "기본값", "unknown": "모름"}
ACCOUNT_PLAIN = {"general": "일반(위탁)", "pension_savings": "연금저축", "irp": "IRP", "isa": "ISA"}
LIMIT_PLAIN = {"risky_asset_max_pct": "위험자산 비중 상한(%)", "annual_contribution_krw": "연간 납입 한도(원)",
               "total_contribution_krw": "총 납입 한도(원)", "min_holding_days": "의무 보유 기간(일)"}
VERDICT_PLAIN = {"pass": "넘지 않음", "breach": "넘음", "undetermined": "판정 못 함"}
CLASS_PLAIN = {"EQUITY": "주식", "RATES": "금리(채권)", "CREDIT": "신용", "FX": "외환", "COMMODITY": "원자재",
               "REAL_ASSET": "실물", "CASH": "현금"}
_CLASSES = tuple(c.value for c in AssetClass)

_OPTIMIZER_UNAWARE = "최적화기는 이 고객·계좌를 모른 채 비중을 냈어요 — 이 점검은 사후 관측이고 비중을 바꾸지 않아요."
#: 기존 경로 사유 문장의 필드 이름 → 사람 말 (PB2 화면 점검에서 찾음). 강조 기호·백틱은 걷는다 — 뜻은 그대로.
_FIELD_PLAIN = {"horizon_days": "투자 기간(일)", "target_retirement_year": "목표 연도", "risky/safe": "위험자산/안전자산"}


def _plain(v: Any) -> str:
    """경로가 준 사유를 이야기 탭에 그대로 싣기 전에 — `**`·`★`·백틱을 걷고 필드 이름을 사람 말로."""
    s = str(v).replace("**", "").replace("★", "").replace("`", "")
    for k, w in _FIELD_PLAIN.items():
        s = s.replace(k, w)
    return s


def _holdings(inputs: dict, what: str) -> dict[str, float]:
    """Weights → 종목별 % (양수만). ★공매도 비중은 받지 않는다★ — 계좌 한도·보유 진단은 롱온리 보유를 잰다."""
    w = inputs["weights"]
    ws = np.asarray(w["weights"], dtype=float)
    if (ws < -1e-9).any():
        raise pg.NodeFailure(f"공매도(음수) 비중이 있어 {what}를 하지 않아요 — 이 점검은 롱온리 보유를 재요.")
    out = {str(n): float(x) * 100.0 for n, x in zip(w["names"], ws) if x > 1e-9}
    if not out:
        raise pg.NodeFailure(f"비중이 모두 0이라 {what}할 보유가 없어요.")
    return out


def _route(fn, req, what: str) -> dict:
    try:
        return finite_payload(fn(req))
    except HTTPException as e:
        raise pg.NodeFailure(f"{what} — {e.detail}") from e


# ── 고객 ────────────────────────────────────────────────────────────────

class ClientParams(BaseModel):
    model_config = _FORBID
    alias: str | None = Field(None, max_length=ALIAS_MAX, json_schema_extra={"x-ui": _ui(
        "별칭", question="이 고객을 무엇이라고 부를까요?", widget="text",
        help="PB 가 정한 별칭만 적어요 — 실명·연락처·주민번호·계좌번호를 적지 마세요(그런 모양이면 받지 않아요).")})
    risk_tolerance: Literal[RISK_TOLERANCE_LEVELS] | None = Field(None, json_schema_extra={"x-ui": _ui(
        "위험 성향", question="고객의 투자 성향은요?", options=RISK_PLAIN, order=list(RISK_TOLERANCE_LEVELS),
        help="비워 두면 '모름' 이에요 — 기본값으로 채우지 않아요.")})
    profile_source: Literal[PROFILE_SOURCES] = Field(SOURCE_UNKNOWN, json_schema_extra={"x-ui": _ui(
        "성향 출처", question="그 성향은 어떻게 정했나요?", options=SOURCE_PLAIN, order=list(PROFILE_SOURCES))})
    assessed_at: str | None = Field(None, pattern=_DATE, json_schema_extra={"x-ui": _ui(
        "평가일", help="성향을 정한 날(YYYY-MM-DD). 성향은 낡아요 — 며칠 지났는지 함께 보여 줘요.")})
    horizon_years: int | None = Field(None, ge=1, le=60, json_schema_extra={"x-ui": _ui(
        "투자 기간", unit="년", help="비워 두면 '모름' 이에요.")})

    @field_validator("alias")
    @classmethod
    def _alias(cls, v: str | None) -> str | None:
        reason = pii_reason(v)
        if reason:
            raise ValueError(reason)
        return v.strip() if v else None


def _client(inputs: dict, p: ClientParams) -> pg.NodeOutput:
    age = None
    if p.assessed_at:
        try:
            age = (dt.date.today() - dt.date.fromisoformat(p.assessed_at)).days
        except ValueError:
            raise pg.NodeFailure(f"평가일 {p.assessed_at} 을(를) 날짜로 읽지 못했어요.") from None
        if age < 0:
            raise pg.NodeFailure(f"평가일 {p.assessed_at} 이(가) 오늘보다 뒤예요 — 미래의 평가는 받지 않아요.")
    profile = {"alias": p.alias, "risk_tolerance": p.risk_tolerance, "profile_source": p.profile_source,
               "assessed_at": p.assessed_at, "assessed_age_days": age, "horizon_years": p.horizon_years}
    return pg.NodeOutput(values={"client": profile}, view=dict(profile))


def _explain_client(view: dict, prov: dict, params: Any) -> dict:
    risk, src = view.get("risk_tolerance"), view.get("profile_source") or SOURCE_UNKNOWN
    facts, trust = [], []
    if risk:
        when = (f" · 평가일 {view['assessed_at']}({view['assessed_age_days']}일 지났어요)" if view.get("assessed_at")
                else " · 평가일 모름")
        facts.append(f"위험 성향: {RISK_PLAIN.get(risk, risk)}(출처: {SOURCE_PLAIN.get(src, src)}){when}")
        trust.append({"survey": _t(ASSUMED, "설문으로 정했다고 적은 성향이에요 — 이 계산은 설문을 확인하지 않았어요."),
                      "user_declared": _t(ASSUMED, "고객이 말한 성향이에요 — 설문으로 잰 값이 아니에요."),
                      "default": _t(ASSUMED, "기본값으로 둔 성향이에요 — 고객에게 물은 값이 아니에요."),
                      }.get(src, _t(UNKNOWN, "성향을 어떻게 정했는지 모르는 채예요.")))
    else:
        facts.append("위험 성향을 정하지 않았어요.")
        trust.append(_t(UNKNOWN, "위험 성향을 모르는 채예요 — 기본값으로 채우지 않아요."))
    hz = view.get("horizon_years")
    facts.append(f"투자 기간: {hz}년" if hz else "투자 기간을 정하지 않았어요.")
    if not hz:
        trust.append(_t(UNKNOWN, "투자 기간을 모르는 채예요."))
    trust.append(_t(UNKNOWN, "성향·기간은 비중을 바꾸지 않아요 — 최적화기는 이 고객을 모른 채 계산해요."))
    alias = view.get("alias")
    return {"title": f"고객 {alias}" if alias else "고객(별칭 없음)", "facts": facts, "trust": trust,
            "unmeasured": ["성향이 지금도 맞는지 — 다시 물어야 알 수 있어요", "고객의 실제 계좌·자산 전체"]}


# ── 계좌 점검 ────────────────────────────────────────────────────────────

class LimitRow(BaseModel):
    """선언하는 한도 하나 — ★값만 받지 않는다★ 출처와 기준일을 함께(AD4 `DeclaredLimit` 와 같은 모양)."""
    model_config = _FORBID
    kind: Literal[LIMIT_KINDS] = Field(..., json_schema_extra={"x-ui": _ui("한도 종류", options=LIMIT_PLAIN)})
    value: float | None = Field(None, json_schema_extra={"x-ui": _ui("값", help="비우면 '선언하지 않음' — 판정 못 함이에요.")})
    source: str | None = Field(None, max_length=200, json_schema_extra={"x-ui": _ui("출처", help="예: 약관 조항·내부 지침 이름")})
    as_of: str | None = Field(None, pattern=_DATE, json_schema_extra={"x-ui": _ui("기준일")})


class AccountParams(BaseModel):
    model_config = _FORBID
    account_type: Literal[ACCOUNT_TYPES] | None = Field(None, json_schema_extra={"x-ui": _ui(
        "계좌 유형", question="어떤 계좌인가요?", options=ACCOUNT_PLAIN, order=list(ACCOUNT_TYPES),
        help="골라야 점검해요 — 기본값으로 정하지 않아요.")})
    risky_asset_classes: list[Literal[_CLASSES]] | None = Field(None, json_schema_extra={"x-ui": _ui(
        "위험자산으로 볼 자산군", question="어느 자산군을 위험자산으로 볼까요?",
        presets=[{"label": "정하지 않음", "value": None}, {"label": "주식", "value": ["EQUITY"]},
                 {"label": "주식·신용", "value": ["EQUITY", "CREDIT"]}],
        help="어느 자산군이 위험자산인지는 규제 판단이라 이 저장소가 정하지 않아요 — 정하지 않으면 위험자산 비중을 재지 않아요.")})
    limits: list[LimitRow] = Field([], max_length=8, json_schema_extra={"x-ui": _ui(
        "선언한 한도", question="이 계좌의 한도를 출처와 함께 적어 주세요",
        help="이 저장소는 법규 수치(예: IRP 위험자산 70%)를 들고 있지 않아요 — 선언하지 않은 한도는 '판정 못 함' 이에요.")})


def _account(inputs: dict, p: AccountParams) -> pg.NodeOutput:
    if p.account_type is None:
        raise pg.NodeFailure("계좌 유형을 골라 주세요 — 기본값으로 정하지 않아요.")
    from src.api.account_policy_routes import AccountDiagnoseRequest, DeclaredLimit, diagnose_account
    holdings = _holdings(inputs, "계좌 점검")
    limits = [lim.model_dump() for lim in p.limits]
    res = _route(diagnose_account, AccountDiagnoseRequest(
        account_type=p.account_type, holdings=holdings, risky_asset_classes=p.risky_asset_classes,
        limits=[DeclaredLimit(**lim) for lim in limits]), "계좌 점검을 하지 못했어요")
    client = inputs.get("client")
    account = {"account_type": p.account_type, "holdings": holdings, "risky_asset_classes": p.risky_asset_classes,
               "limits": limits, "client": client}
    view = {"result": res, "account_type": p.account_type, "labels": _labels(list(holdings)),
            "client_alias": (client or {}).get("alias")}
    return pg.NodeOutput(values={"account": account}, view=view)


def _explain_account(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    verdicts = r.get("verdicts") or []
    acct = ACCOUNT_PLAIN.get(view.get("account_type"), view.get("account_type"))
    facts = [f"{LIMIT_PLAIN.get(v['kind'], v['kind'])}: {VERDICT_PLAIN.get(v['verdict'], v['verdict'])}"
             + (f" — {_plain(v['reason'])}" if v.get("reason") else "") for v in verdicts]
    if not verdicts:
        facts.append(_plain(r.get("note") or "이 계좌 유형에는 이 저장소가 아는 한도가 없어요."))
    rs = r.get("risky_share") or {}
    iv = rs.get("interval") or {}
    if rs.get("available") and iv.get("lo") is not None:
        un = rs.get("unassigned_pct") or 0
        facts.append(f"위험자산 비중: {iv['lo']:g}~{iv['hi']:g}%"
                     + (f" — 자산군을 모르는 보유 {un:g}% 만큼 구간이 넓어요(모름을 0으로 접지 않아요)" if un else ""))
    elif rs.get("reason"):
        facts.append(f"위험자산 비중을 재지 않았어요 — {_plain(rs['reason'])}")
    if r.get("ignored_limits"):
        facts.append(f"이 계좌에 없는 한도라 보지 않은 것: {', '.join(LIMIT_PLAIN.get(k, k) for k in r['ignored_limits'])}")
    trust = []
    if any(v["verdict"] == "undetermined" for v in verdicts):
        trust.append(_t(UNKNOWN, "선언하지 않았거나 잴 수 없는 한도는 판정하지 못했어요 — 통과가 아니에요."))
    if any(v["verdict"] in ("pass", "breach") for v in verdicts):
        trust.append(_t(ASSUMED, "판정에 쓴 한도 값은 선언한 것이에요(출처·기준일과 함께) — 이 저장소는 법규 수치를 들고 있지 않아요."))
    trust.append(_t(UNKNOWN, _OPTIMIZER_UNAWARE))
    breach = sum(1 for v in verdicts if v["verdict"] == "breach")
    headline = ({"label": "넘은 한도", "value": breach, "unit": "개", "text": f"{breach}개"} if verdicts else None)
    return {"title": f"{acct} 계좌 한도를 점검했어요", "headline": headline, "facts": facts, "trust": trust,
            "unmeasured": ["계좌 잔고·실제 보유 — 계좌를 읽지 않고 이어진 비중만 봐요", "법규 수치가 지금도 같은지"]}


# ── 목표까지 ─────────────────────────────────────────────────────────────

class CurveRow(BaseModel):
    model_config = _FORBID
    years_to_target: float = Field(..., ge=0, le=80, json_schema_extra={"x-ui": _ui("목표까지 남은 해")})
    risky_target_pct: float = Field(..., ge=0, le=100, json_schema_extra={"x-ui": _ui("그때 위험자산 목표(%)")})


class GoalParams(BaseModel):
    model_config = _FORBID
    target_retirement_year: int | None = Field(None, ge=2000, le=2100, json_schema_extra={"x-ui": _ui(
        "목표 연도", question="목표(은퇴 등)는 몇 년인가요?", help="비워 두면 남은 기간을 몰라 목표 비중을 내지 않아요.")})
    curve: list[CurveRow] = Field([], max_length=12, json_schema_extra={"x-ui": _ui(
        "글라이드패스 곡선", question="남은 기간에 따라 위험자산을 얼마나 둘까요?",
        help="두 점 이상이어야 목표 비중을 내요 — 곡선은 투자 판단이라 이 저장소가 정하지 않아요.")})
    monthly_krw: float | None = Field(None, ge=0, json_schema_extra={"x-ui": _ui("월 적립 계획", "advanced", unit="원")})
    bucket: Literal["risky", "safe"] | None = Field(None, json_schema_extra={"x-ui": _ui(
        "적립 대상", "advanced", options={"risky": "위험자산", "safe": "안전자산"})})
    portfolio_value_krw: float | None = Field(None, gt=0, json_schema_extra={"x-ui": _ui("평가 금액", "advanced", unit="원")})
    contributed_ytd_krw: float | None = Field(None, ge=0, json_schema_extra={"x-ui": _ui(
        "올해 이미 낸 금액", "advanced", unit="원", help="★실적★ — 계획이 아니에요. 연간 납입 한도 판정에 써요.")})
    total_contributed_krw: float | None = Field(None, ge=0, json_schema_extra={"x-ui": _ui(
        "지금까지 낸 금액", "advanced", unit="원", help="★실적★ — 총 납입 한도 판정에 써요.")})


def _goal(inputs: dict, p: GoalParams) -> pg.NodeOutput:
    from src.api.account_policy_routes import DeclaredLimit
    from src.api.glidepath_routes import ContributionPlan, CurvePoint, GlidePathRequest, glidepath_account
    acc = inputs["account"]
    res = _route(glidepath_account, GlidePathRequest(
        account_type=acc["account_type"], holdings=acc["holdings"], risky_asset_classes=acc["risky_asset_classes"],
        target_retirement_year=p.target_retirement_year,
        curve=[CurvePoint(**c.model_dump()) for c in p.curve] or None,
        contribution=ContributionPlan(monthly_krw=p.monthly_krw, bucket=p.bucket, portfolio_value_krw=p.portfolio_value_krw),
        limits=[DeclaredLimit(**lim) for lim in acc["limits"]],
        contributed_ytd_krw=p.contributed_ytd_krw, total_contributed_krw=p.total_contributed_krw), "목표까지를 재지 못했어요")
    client = inputs.get("client") or acc.get("client")
    return pg.NodeOutput(values={}, view={"result": res, "account_type": acc["account_type"],
                                          "client_alias": (client or {}).get("alias")})


def _explain_goal(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    g = r.get("glide") or {}
    facts, trust = [], []
    target = g.get("target_pct")
    if target is None:
        why = list(dict.fromkeys(_plain(x) for x in (g.get("years_reason"), g.get("curve_reason"), g.get("reason")) if x))
        facts.append("목표 위험자산 비중을 내지 않았어요" + (f" — {' / '.join(why)}" if why else "."))
        trust.append(_t(UNKNOWN, "곡선(두 점 이상)·남은 기간이 있어야 목표를 내요 — 지어내지 않아요."))
    else:
        facts.append(f"이 시점의 목표 위험자산 비중: {target:g}%")
        trust.append(_t(ASSUMED, "목표는 선언한 곡선에서 읽은 값이에요 — 곡선이 옳은지는 이 계산이 판정하지 않아요."))
    gap = g.get("gap") or {}
    if target is not None and gap.get("state") == "above":
        facts.append(f"지금 위험자산 비중이 목표보다 {gap['lo']:.1f}~{gap['hi']:.1f}%p 많아요")
    elif target is not None and gap.get("state") == "below":
        facts.append(f"지금 위험자산 비중이 목표보다 {-gap['hi']:.1f}~{-gap['lo']:.1f}%p 적어요")
    elif target is not None:
        facts.append("지금 비중과 목표의 차이는 몰라요" + (f" — {_plain(gap['reason'])}" if gap.get("reason") else ""))
        trust.append(_t(UNKNOWN, "격차의 부호를 모르면 0으로 보지 않아요 — 미배정 자산군 때문이에요."))
    months = (r.get("contribution") or {}).get("months")
    if months is not None:
        facts.append(f"적립 계획대로라면 격차를 좁히는 데 {months}개월")
    trust.append(_t(UNKNOWN, "최적화기는 이 목표를 모른 채 비중을 냈어요 — 격차를 배분에 반영하지 않아요."))
    return {"title": "목표까지 얼마나 남았는지 봤어요", "facts": facts, "trust": trust,
            "unmeasured": ["목표 곡선이 이 고객에게 맞는지", "앞으로의 수익률(적립만으로 좁히는 데 걸리는 개월만 봐요)"]}


# ── 보유 진단 ────────────────────────────────────────────────────────────

class HoldingsCheckParams(BaseModel):
    model_config = _FORBID
    lookback_days: int = Field(500, ge=60, le=2000, json_schema_extra={"x-ui": _ui(
        "볼 기간", unit="영업일", presets=[{"label": "1년", "value": 252}, {"label": "2년", "value": 500}])})
    as_of: str | None = Field(None, pattern=_DATE, json_schema_extra={"x-ui": _ui("기준일", "advanced")})
    benchmark: str | None = Field(None, max_length=20, json_schema_extra={"x-ui": _ui("벤치마크", "advanced")})


def _holdings_check(inputs: dict, p: HoldingsCheckParams) -> pg.NodeOutput:
    from src.api.diagnostics_routes import HoldingsDiagnosticsRequest, holdings_diagnostics
    holdings = _holdings(inputs, "보유 진단")
    res = _route(holdings_diagnostics, HoldingsDiagnosticsRequest(
        holdings=holdings, weight_unit="percent", lookback_days=p.lookback_days, as_of=p.as_of, benchmark=p.benchmark),
        "보유 진단을 하지 못했어요")
    return pg.NodeOutput(values={}, view={"result": res, "labels": _labels(list(holdings))},
                         provenance={"source": "mock"} if mock_allowed() else {})


def _explain_holdings(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    n = len(r.get("holdings") or {})
    facts = [f"{n}종목 보유를 팩터 노출 · 집중도 · 위험 기여 · 유동성으로 나눠 봤어요."]
    trust = [_t(CONFIRMED, "진단 계산은 끝났어요.")]
    for name, blk in (("위험 기여", r.get("risk_contributions")), ("유동성", r.get("liquidity"))):
        if isinstance(blk, dict) and blk.get("available") is False:
            trust.append(_t(FAILED, f"{name}를 재지 못했어요 — {_plain(blk.get('reason'))}"))
    if prov.get("source") == "mock":
        trust.append(_practice())
    if r.get("note"):
        facts.append(_plain(r["note"]))
    return {"title": "지금 보유를 진단했어요", "facts": facts, "trust": trust,
            "unmeasured": ["이 진단이 앞으로의 위험을 맞히는지 — 과거 기준이에요"]}


def register(registry: pg.Registry) -> None:
    for spec in (
        pg.NodeSpec("client_profile", "고객", plain_label="고객", category="고객", stage="data",
                    plain_description="별칭·위험 성향·투자 기간을 적어요. 비중은 바꾸지 않아요.",
                    inputs=(), outputs=(P("client", "Client"),), run=_client, params_model=ClientParams,
                    explain=_explain_client, description="PB 가 정한 별칭과 성향(출처·평가일). 개인정보 모양은 받지 않는다."),
        pg.NodeSpec("account", "계좌 점검", plain_label="계좌 점검", category="고객", stage="check",
                    plain_description="고객 계좌의 유형과 선언한 한도로 이 비중을 점검해요. 선언하지 않은 한도는 판정하지 않아요.",
                    inputs=(P("weights", "Weights"), P("client", "Client", required=False)),
                    outputs=(P("account", "Account"),), run=_account, params_model=AccountParams,
                    explain=_explain_account, description="`/accounts/diagnose` 그대로 — 관측만. 공매도 비중은 받지 않는다."),
        pg.NodeSpec("goal", "목표까지", plain_label="목표까지", category="고객", stage="check",
                    plain_description="고객의 목표 연도·곡선으로 지금 위험자산 비중이 목표와 얼마나 다른지 봐요.",
                    inputs=(P("account", "Account"), P("client", "Client", required=False)), outputs=(),
                    run=_goal, params_model=GoalParams, explain=_explain_goal,
                    description="`/accounts/glidepath` 그대로 — 관측만. 곡선이 없으면 목표를 내지 않는다."),
        pg.NodeSpec("holdings_check", "보유 진단", plain_label="보유 진단", category="고객", stage="check",
                    plain_description="고객이 들고 있는 비중의 팩터 노출·집중도·위험 기여·유동성을 봐요.",
                    inputs=(P("weights", "Weights"),), outputs=(), run=_holdings_check,
                    params_model=HoldingsCheckParams, explain=_explain_holdings,
                    description="`/diagnostics/holdings` 그대로 — 관측만."),
    ):
        registry.register(spec)
