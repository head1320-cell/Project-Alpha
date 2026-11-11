"""AAS 그래프 — 기업 분석 현업 모델 노드 (BL3 W3b) · ★`company_model_routes` 라우트 함수를 그대로 부른다★
==============================================================================
계획 `happy-percolating-falcon.md` §BL3 W3b. 엔진은 `src/engine/valuation/practice_models.py`(순수), 데이터는 라우트가 댄다.
같은 수인지는 `tests/test_allocation_graph_bl3w3b.py` 골든이 라우트와 대조한다.

C1(데이터형): EVA·가치 동인 · 가치의 층(Greenwald 3층) · 배수·PEG·정당 배수 · 영업 동인 몬테카를로.
C2(가정형): 시나리오 가중 · 의사결정 나무 · 합산가치(SOTP)·지주사 NAV · 실물옵션 — 확률·값·배수·지분율은 사람이 정한다(행 목록 편집기).
공통: 종목은 이름으로 판정 · 가격은 출처와 함께(W3 `_priced`) · 결과의 `inputs` 가 관측/근사/가정/미상을 가른다 · 못 하면 사유.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.api import company_model_routes as cmr
from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _t
from src.api.allocation_graph_nodes import _FORBID, _ui
from src.api.allocation_graph_nodes_company import _base_trust, _out, _Priced, _priced
from src.engine import portfolio_graph as pg

_EOK = 1e8


def _call(route, head: dict, req, what: str) -> pg.NodeOutput:
    out = route(head["code"], req)
    if isinstance(out, dict) and out.get("available") is False:
        raise pg.NodeFailure(f"{what} — {out.get('reason') or '사유 미상'}")
    return _out(head, out)


def _inputs_trust(r: dict) -> list[dict]:
    """결과의 `inputs` 중 가정·근사·미상을 신뢰 줄로 — 관측은 적지 않는다(숫자가 이미 말한다)."""
    tone = {"가정": ASSUMED, "근사": ASSUMED, "미상": UNKNOWN}
    out = []
    for i in r.get("inputs") or []:
        if i.get("basis") in tone:
            src = f" — {i['source']}" if i.get("source") else ""
            out.append(_t(tone[i["basis"]], f"{i['label']}: {i['basis']}{src}"))
    return out


def _history_trust(r: dict) -> list[dict]:
    return [_t(UNKNOWN, r["history_note"])] if r.get("history_note") else []


def _won(x: Any) -> str:
    return f"{x:,.0f}원" if isinstance(x, (int, float)) else "—"


# ── EVA · 가치 동인 ──────────────────────────────────────────────────────────

class EvaParams(_Priced):
    fade_years: int = Field(5, ge=1, le=30, json_schema_extra={"x-ui": _ui(
        "초과이익 소멸 기간", question="초과이익(EVA) 소멸 기간 가정", unit="년",
        presets=[{"label": "3년", "value": 3}, {"label": "5년", "value": 5}, {"label": "10년", "value": 10}],
        help="경쟁으로 초과이익이 소멸하는 기간입니다 — 가정입니다.")})
    g: float | None = Field(None, ge=-0.05, le=0.15, json_schema_extra={"x-ui": _ui(
        "성장률", "advanced", help="가치 동인 공식의 성장률입니다. 비우면 영구성장률을 씁니다.")})
    ronic: float | None = Field(None, gt=-1, le=1, json_schema_extra={"x-ui": _ui(
        "신규 투자 수익률", "advanced", help="신규 투자자본의 수익률(RONIC)입니다. 비우면 최근 ROIC 를 씁니다.")})


def _eva(inputs: dict, p: EvaParams) -> pg.NodeOutput:
    head = _priced(p)
    return _call(cmr.company_model_eva, head,
                 cmr.EvaRequest(price=head["price"], fade_years=p.fade_years, g=p.g, ronic=p.ronic),
                 "EVA 를 계산하지 못했습니다")


def _explain_eva(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    last, vd = r.get("latest") or {}, r.get("value_driver") or {}
    eva, roic, wacc = last.get("eva"), last.get("roic"), last.get("wacc")
    title = ((f"자본비용을 {eva / _EOK:,.0f}억 넘게 법니다" if eva >= 0 else f"자본비용보다 {-eva / _EOK:,.0f}억 덜 법니다")
             if isinstance(eva, (int, float)) else "EVA 를 계산했습니다")
    facts = []
    if isinstance(roic, (int, float)) and isinstance(wacc, (int, float)):
        facts.append(f"투하자본수익률 {roic:.1%} · 자본비용 {wacc:.1%}")
    if vd.get("available"):
        facts.append("성장이 가치를 만듭니다(신규 투자 수익률 > 자본비용)" if vd.get("growth_creates_value")
                     else "성장이 가치를 깎습니다(신규 투자 수익률 < 자본비용) — 덜 자랄수록 낫습니다")
    trust = [*_base_trust(view, prov), *_history_trust(r), *_inputs_trust(r)]
    if not vd.get("available") and vd.get("reason"):
        trust.append(_t(UNKNOWN, f"가치 동인 공식: {vd['reason']}"))
    if r.get("note"):
        trust.append(_t(ASSUMED, r["note"]))
    return {"title": title, "facts": facts, "trust": trust,
            "unmeasured": ["초과이익이 실제로 몇 년 버티는지(경쟁 우위의 지속성)"]}


# ── 가치의 층 ────────────────────────────────────────────────────────────────

class LayersParams(_Priced):
    w_asset: float = Field(0.25, ge=0, le=1, json_schema_extra={"x-ui": _ui(
        "자산가치 가중", question="회사가 지금 가진 것만큼만 가치가 있을 확률은?",
        presets=[{"label": "10%", "value": 0.1}, {"label": "25%", "value": 0.25}, {"label": "50%", "value": 0.5}],
        help="세 가중의 합은 1 이어야 합니다 — 맞지 않으면 계산하지 않습니다.")})
    w_epv: float = Field(0.25, ge=0, le=1, json_schema_extra={"x-ui": _ui(
        "수익력가치 가중", question="지금 버는 만큼만 계속 벌 확률은?",
        presets=[{"label": "20%", "value": 0.2}, {"label": "25%", "value": 0.25}, {"label": "30%", "value": 0.3}])})
    w_full: float = Field(0.5, ge=0, le=1, json_schema_extra={"x-ui": _ui(
        "성장가치 가중", question="성장까지 이뤄질 확률은?",
        presets=[{"label": "20%", "value": 0.2}, {"label": "50%", "value": 0.5}, {"label": "70%", "value": 0.7}])})


def _layers(inputs: dict, p: LayersParams) -> pg.NodeOutput:
    head = _priced(p)
    return _call(cmr.company_model_value_layers, head,
                 cmr.LayersRequest(price=head["price"], w_asset=p.w_asset, w_epv=p.w_epv, w_full=p.w_full),
                 "가치의 층을 쌓지 못했습니다")


def _explain_layers(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    L = {x["key"]: x for x in r.get("layers") or []}
    price = view.get("price")
    tops = [("asset", L.get("asset", {}).get("per_share")), ("epv", L.get("epv", {}).get("per_share")),
            ("full", r.get("full_per_share"))]
    names = {"asset": "자산가치", "epv": "수익력가치", "full": "성장까지 넣은 가치"}
    covered = [k for k, v in tops if isinstance(v, (int, float)) and isinstance(price, (int, float)) and v >= price]
    title = (f"지금 가격은 {names[covered[0]]} 안에 들어옵니다" if covered else
             "지금 가격은 성장까지 넣은 가치보다도 높습니다" if isinstance(price, (int, float)) else "가치의 층을 쌓았습니다")
    facts = [f"{names[k]}: {_won(v)}" for k, v in tops]
    if isinstance(r.get("weighted_per_share"), (int, float)):
        facts.append(f"확률로 묶은 값: {_won(r['weighted_per_share'])}")
    trust = [*_base_trust(view, prov), *_history_trust(r), *_inputs_trust(r)]
    if r.get("franchise"):
        trust.append(_t(CONFIRMED, r["franchise"]))
    if r.get("weighted_reason"):
        trust.append(_t(UNKNOWN, r["weighted_reason"]))
    ep = L.get("epv", {})
    if ep.get("reason"):
        trust.append(_t(UNKNOWN, f"수익력가치: {ep['reason']}"))
    return {"title": title, "facts": facts, "trust": trust,
            "unmeasured": ["자산을 다시 만드는 데 드는 돈(재생산원가) — 장부가로 대신했습니다"]}


# ── 배수 · PEG · 정당 배수 ───────────────────────────────────────────────────

class MultiplesParams(_Priced):
    peers: bool = Field(True, json_schema_extra={"x-ui": _ui(
        "피어 PER 비교", "advanced", help="동종업계 PER 중앙값 기준 가격을 함께 산출합니다(업종 표 계산으로 느립니다).")})


def _multiples(inputs: dict, p: MultiplesParams) -> pg.NodeOutput:
    head = _priced(p)
    return _call(cmr.company_model_multiples, head, cmr.MultiplesRequest(price=head["price"], peers=p.peers),
                 "배수로 보지 못했습니다")


def _explain_multiples(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    j = r.get("justified") or {}
    per, peg = r.get("per"), r.get("peg")
    title = (f"PER {per:.1f}배 · PEG {peg:.2f}" if isinstance(per, (int, float)) and isinstance(peg, (int, float))
             else f"PER {per:.1f}배 (PEG 는 못 냈습니다)" if isinstance(per, (int, float)) else "배수를 봤습니다")
    facts = []
    if isinstance(j.get("pbr"), (int, float)):
        facts.append(f"ROE 로 본 정당 PBR {j['pbr']:.2f}배 → {_won(j.get('pbr_price'))}")
    if isinstance(j.get("per"), (int, float)):
        facts.append(f"배당으로 본 정당 PER {j['per']:.1f}배 → {_won(j.get('per_price'))}")
    peer = r.get("peer") or {}
    if isinstance(peer.get("per_price"), (int, float)):
        facts.append(f"피어 PER 중앙값 {peer['per_median']:.1f}배 → {_won(peer['per_price'])}")
    trust = [*_base_trust(view, prov), *_history_trust(r), *_inputs_trust(r),
             _t(ASSUMED, "PEG 1 이 적정이라는 것은 관행이지 법칙이 아닙니다 — 격자는 가정을 바꿔 보는 표입니다.")]
    for k in ("peg_reason",):
        if r.get(k):
            trust.append(_t(UNKNOWN, r[k]))
    if j.get("reason"):
        trust.append(_t(UNKNOWN, j["reason"]))
    if j.get("pbr_note"):
        trust.append(_t(CONFIRMED, j["pbr_note"]))
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["성장률이 실제로 이어질지"]}


# ── 영업 동인 몬테카를로 ─────────────────────────────────────────────────────

class DriverMcParams(_Priced):
    sigma_growth: float = Field(0.03, ge=0, le=0.5, json_schema_extra={"x-ui": _ui(
        "매출 성장률 표준편차", question="매출 성장률 연간 변동성 가정",
        presets=[{"label": "±1%p", "value": 0.01}, {"label": "±3%p", "value": 0.03}, {"label": "±6%p", "value": 0.06}],
        help="표준편차입니다. 중심은 지난 재무에서 읽습니다.")})
    sigma_margin: float = Field(0.02, ge=0, le=0.5, json_schema_extra={"x-ui": _ui(
        "영업이익률 표준편차", question="영업이익률 변동성 가정",
        presets=[{"label": "±1%p", "value": 0.01}, {"label": "±2%p", "value": 0.02}, {"label": "±4%p", "value": 0.04}])})
    sigma_reinvest: float = Field(0.01, ge=0, le=0.5, json_schema_extra={"x-ui": _ui("재투자율 표준편차", "advanced")})
    years: int = Field(5, ge=3, le=15, json_schema_extra={"x-ui": _ui("예측 기간", "advanced", unit="년")})
    n: int = Field(2000, ge=100, le=20000, json_schema_extra={"x-ui": _ui("경로 수", "advanced")})
    seed: int = Field(20260927, json_schema_extra={"x-ui": _ui("난수 시드", "advanced",
                                                               help="같은 시드면 같은 결과가 나옵니다.")})


def _driver_mc(inputs: dict, p: DriverMcParams) -> pg.NodeOutput:
    head = _priced(p)
    req = cmr.DriverMcRequest(price=head["price"], sigma_growth=p.sigma_growth, sigma_margin=p.sigma_margin,
                              sigma_reinvest=p.sigma_reinvest, years=p.years, n=p.n, seed=p.seed)
    return _call(cmr.company_model_driver_mc, head, req, "영업 동인으로 밸류에이션 밴드 생성 실패")


def _explain_driver_mc(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    q = r.get("quantiles") or {}
    pp = r.get("price_percentile")
    title = (f"지금 가격은 밸류에이션 밴드의 {pp:.0f}번째 백분위입니다" if isinstance(pp, (int, float))
             else "영업 동인으로 밸류에이션 밴드를 만들었습니다")
    facts = [f"10~90%: {_won(q.get('p10'))} ~ {_won(q.get('p90'))} · 중앙 {_won(q.get('p50'))}"] if q else []
    if isinstance(r.get("negative_share"), (int, float)) and r["negative_share"] > 0:
        facts.append(f"경로의 {r['negative_share']:.0%} 는 주당 가치가 0 아래입니다(부채가 더 큽니다)")
    trust = [*_base_trust(view, prov), *_history_trust(r), *_inputs_trust(r)]
    if r.get("n_rejected"):
        trust.append(_t(UNKNOWN, f"매출이 사라지는 경로 {r['n_rejected']}개는 모형 밖이라 버렸습니다"))
    if r.get("note"):
        trust.append(_t(ASSUMED, r["note"].replace("**", "")))
    return {"title": title, "facts": facts, "trust": trust,
            "unmeasured": ["동인끼리의 상관(함께 나빠지는 해) — 독립으로 뒀습니다"]}


# ══ C2 — 가정형 ══════════════════════════════════════════════════════════════

def _rows(items: list, model) -> list:
    return [model(**x.model_dump()) for x in items]


# ── 시나리오 가중 ────────────────────────────────────────────────────────────

class ScenarioItem(BaseModel):
    model_config = _FORBID
    name: str = Field("시나리오", max_length=20, json_schema_extra={"x-ui": _ui("이름")})
    prob: float = Field(0.5, ge=0, le=1, json_schema_extra={"x-ui": _ui("확률")})
    g: float | None = Field(None, ge=0, le=0.05, json_schema_extra={"x-ui": _ui("영구성장률")})
    beta: float | None = Field(None, ge=0.1, le=3.0, json_schema_extra={"x-ui": _ui("베타")})
    rf: float | None = Field(None, ge=0, le=0.15, json_schema_extra={"x-ui": _ui("무위험수익률", "advanced")})
    erp: float | None = Field(None, ge=0, le=0.15, json_schema_extra={"x-ui": _ui("시장위험프리미엄", "advanced")})


class ScenariosParams(_Priced):
    # ★기본값은 default(리터럴)로★ — default_factory 는 JSON 스키마에 기본값을 싣지 않아, 설정 화면이 "아직 없어요" 라고
    # 보이면서 서버는 세 시나리오로 계산하는 어긋남이 생긴다(스크린샷 비평에서 잡음).
    scenarios: list[ScenarioItem] = Field(
        default=[ScenarioItem(name="약세", prob=0.25, g=0.01, beta=1.3), ScenarioItem(name="기본", prob=0.5),
                 ScenarioItem(name="강세", prob=0.25, g=0.03, beta=0.9)],
        max_length=8, json_schema_extra={"x-ui": _ui(
            "시나리오", question="시나리오별 확률 가정",
            help="2~5개 · 확률의 합은 1 · 비운 가정은 기본값(가치평가 샌드박스와 같다).")})


def _scenarios(inputs: dict, p: ScenariosParams) -> pg.NodeOutput:
    head = _priced(p)
    return _call(cmr.company_model_scenarios, head,
                 cmr.ScenariosRequest(price=head["price"], scenarios=_rows(p.scenarios, cmr.ScenarioRow)),
                 "시나리오로 묶지 못했습니다")


def _explain_scenarios(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    pa = r.get("prob_above_price")
    title = f"확률로 묶은 적정가 {_won(r.get('weighted'))}"
    facts = [f"{x['name']} ({x['prob']:.0%}): {_won(x['value'])}" for x in r.get("rows") or []]
    if isinstance(pa, (int, float)):
        facts.append(f"지금 가격 이상일 확률 {pa:.0%}")
    trust = [*_base_trust(view, prov), *_inputs_trust(r),
             _t(ASSUMED, "확률은 사람이 정한 값입니다 — 측정한 빈도가 아닙니다.")]
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["정한 확률이 맞는지"]}


# ── 의사결정 나무 ────────────────────────────────────────────────────────────

class BranchItem(BaseModel):
    model_config = _FORBID
    id: str = Field("A", max_length=20, json_schema_extra={"x-ui": _ui("가지 id")})
    parent: str = Field("", max_length=20, json_schema_extra={"x-ui": _ui("부모 id", help="비우면 맨 처음 갈림길입니다.")})
    label: str = Field("", max_length=40, json_schema_extra={"x-ui": _ui("사건")})
    prob: float = Field(0.5, ge=0, le=1, json_schema_extra={"x-ui": _ui("확률")})
    value: float | None = Field(None, json_schema_extra={"x-ui": _ui("주당 가치(끝 가지)")})


class TreeParams(_Priced):
    branches: list[BranchItem] = Field(
        default=[
            BranchItem(id="A", label="규제 승인", prob=0.6), BranchItem(id="B", label="승인 실패", prob=0.4, value=38000),
            BranchItem(id="A1", parent="A", label="시장 안착", prob=0.7, value=80000),
            BranchItem(id="A2", parent="A", label="경쟁 심화", prob=0.3, value=55000)],
        max_length=30, json_schema_extra={"x-ui": _ui(
            "가지", question="사건별 분기 구조",
            help="같은 부모 아래 확률의 합은 1 · 끝 가지에는 주당 가치 · 깊이 4단계까지.")})


def _tree(inputs: dict, p: TreeParams) -> pg.NodeOutput:
    head = _priced(p)
    return _call(cmr.company_model_decision_tree, head,
                 cmr.DecisionTreeRequest(price=head["price"], branches=_rows(p.branches, cmr.TreeBranch)),
                 "의사결정 나무 산출 실패")


def _explain_tree(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    paths = r.get("paths") or []
    facts = [f"{' → '.join(str(x) for x in pth['labels'])}: {pth['prob']:.0%} · {_won(pth['value'])}" for pth in paths[:4]]
    trust = [*_base_trust(view, prov), *_inputs_trust(r),
             _t(ASSUMED, "가지·확률·값은 모두 사람이 정했습니다 — 나무는 그 가정을 정직하게 접을 뿐입니다.")]
    if r.get("ignored_values"):
        trust.append(_t(UNKNOWN, f"중간 가지의 값은 쓰지 않았습니다(아래 가지로 계산): {', '.join(r['ignored_values'])}"))
    return {"title": f"기대 가치 {_won(r.get('expected_value'))}", "facts": facts, "trust": trust,
            "unmeasured": ["사건의 확률 자체"]}


# ── 합산가치(SOTP)·지주사 NAV ─────────────────────────────────────────────────

class SegmentItem(BaseModel):
    model_config = _FORBID
    name: str = Field("부문", max_length=30, json_schema_extra={"x-ui": _ui("부문")})
    metric: float = Field(0.0, json_schema_extra={"x-ui": _ui("지표(억원)", help="EBITDA·순이익 등")})
    multiple: float = Field(5.0, ge=0, le=100, json_schema_extra={"x-ui": _ui("배수")})


class SubsidiaryItem(BaseModel):
    model_config = _FORBID
    code: str = Field("000660", pattern=r"^\d{6}$", json_schema_extra={"x-ui": _ui("자회사 종목코드")})
    stake_pct: float = Field(20.0, ge=0, le=100, json_schema_extra={"x-ui": _ui("지분율(%)")})


class SotpParams(_Priced):
    segments: list[SegmentItem] = Field(default_factory=list, max_length=12, json_schema_extra={"x-ui": _ui(
        "사업 부문", question="직접 하는 사업을 부문별로 나누면?", help="부문 실적은 저장소에 없습니다 — 직접 넣습니다.")})
    subsidiaries: list[SubsidiaryItem] = Field(default_factory=list, max_length=12, json_schema_extra={"x-ui": _ui(
        "상장 자회사", question="가진 상장 자회사와 지분율은?", help="시가총액은 조회하고, 지분율은 직접 넣습니다.")})
    holding_discount_pct: float = Field(0.0, ge=0, lt=100, json_schema_extra={"x-ui": _ui(
        "지주사 할인", question="합산 가치 할인율", unit="%",
        presets=[{"label": "없음", "value": 0}, {"label": "30%", "value": 30}, {"label": "50%", "value": 50}],
        help="한국 지주사는 흔히 NAV 에서 할인돼 거래됩니다 — 할인율은 가정입니다.")})
    net_debt_eok: float | None = Field(None, json_schema_extra={"x-ui": _ui(
        "순차입금(억원)", "advanced", help="비우면 총부채로 근사합니다(DCF 와 같은 다리 — 보수적).")})


def _sotp(inputs: dict, p: SotpParams) -> pg.NodeOutput:
    head = _priced(p)
    req = cmr.SotpRequest(price=head["price"], segments=_rows(p.segments, cmr.SotpSegment),
                          subsidiaries=_rows(p.subsidiaries, cmr.SotpSubsidiary),
                          holding_discount_pct=p.holding_discount_pct, net_debt_eok=p.net_debt_eok)
    return _call(cmr.company_model_sotp, head, req, "합산가치 산출 실패")


def _explain_sotp(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    title = f"부문·자회사를 합치면 주당 {_won(r.get('per_share'))}"
    facts = [f"{x['name']}: {x['value']:,.0f}억" for x in r.get("segments") or []]
    facts += [f"{x.get('name') or x['code']} 지분 {x['stake_pct']:.0f}%: {x['value']:,.0f}억" for x in r.get("subsidiaries") or []]
    trust = [*_base_trust(view, prov), *_history_trust(r), *_inputs_trust(r)]
    for x in r.get("excluded") or []:
        trust.append(_t(UNKNOWN, f"{x.get('code')}: 합계에서 뺐습니다 — {x.get('reason')}"))
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["부문별 적정 배수(피어 부문 자료 없음)"]}


# ── 실물옵션 ─────────────────────────────────────────────────────────────────

class RealOptionParams(_Priced):
    kind: str = Field("call", pattern="^(call|put)$", json_schema_extra={"x-ui": _ui(
        "옵션 종류", question="평가 대상 실물옵션", widget="cards",
        options={"call": "확장·연기(들어갈 권리)", "put": "포기(빠져나올 권리)"})})
    S: float = Field(1000.0, gt=0, json_schema_extra={"x-ui": _ui(
        "사업 가치(억원)", question="그 사업의 지금 가치는?", help="현금흐름의 현재가치 — 가정입니다.")})
    K: float = Field(1200.0, gt=0, json_schema_extra={"x-ui": _ui(
        "투자비·처분가(억원)", question="들어가려면(또는 빠져나오면) 얼마?")})
    T: float = Field(3.0, gt=0, le=30, json_schema_extra={"x-ui": _ui(
        "결정 만기", unit="년", presets=[{"label": "1년", "value": 1}, {"label": "3년", "value": 3}, {"label": "5년", "value": 5}])})
    sigma: float = Field(0.35, gt=0, le=2, json_schema_extra={"x-ui": _ui(
        "사업 가치 변동성", presets=[{"label": "20%", "value": 0.2}, {"label": "35%", "value": 0.35}, {"label": "60%", "value": 0.6}],
        help="옵션 가치에 가장 민감한 가정입니다.")})
    q: float = Field(0.0, ge=0, le=0.5, json_schema_extra={"x-ui": _ui(
        "가치 누수율", "advanced", help="결정 대기 중 유실되는 현금흐름 비율(배당수익률처럼 처리합니다).")})
    n_steps: int = Field(500, ge=50, le=2000, json_schema_extra={"x-ui": _ui("이항 단계 수", "advanced")})


def _real_option(inputs: dict, p: RealOptionParams) -> pg.NodeOutput:
    head = _priced(p)
    req = cmr.RealOptionRequest(price=head["price"], S=p.S, K=p.K, T=p.T, sigma=p.sigma, q=p.q, kind=p.kind,
                                n_steps=p.n_steps)
    return _call(cmr.company_model_real_option, head, req, "실물옵션 산출 실패")


def _explain_real_option(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    bs, bi = (r.get("black_scholes") or {}).get("value"), (r.get("binomial") or {}).get("value")
    title = (f"실물옵션 {bs:,.0f}억(유럽형) · {bi:,.0f}억(미국형)" if isinstance(bs, (int, float)) and isinstance(bi, (int, float))
             else "실물옵션을 계산했습니다")
    npv = r.get("static_npv")
    facts = []
    if isinstance(npv, (int, float)):
        facts.append(f"지금 바로 하면 {npv:,.0f}억 — 선택권이 더하는 값 {r.get('option_premium', 0):,.0f}억")
    ps = r.get("per_share") or {}
    if isinstance(ps.get("black_scholes"), (int, float)):
        facts.append(f"주당 {_won(ps['black_scholes'])} (현재가의 {ps.get('vs_price_pct', 0):.1f}%)")
    trust = [*_base_trust(view, prov), *_inputs_trust(r), _t(CONFIRMED, (r.get("early_exercise") or {}).get("note", ""))]
    if r.get("note"):
        trust.append(_t(ASSUMED, r["note"]))
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["사업 가치의 변동성(측정하지 않은 가정)"]}


# ── 등록 ─────────────────────────────────────────────────────────────────────

def register(registry: pg.Registry) -> None:
    common = {"inputs": (), "outputs": (), "category": "기업", "stage": "signal"}
    for spec in (
        pg.NodeSpec("company_eva", "EVA·가치 동인", plain_label="EVA 분석",
                    plain_description="투하자본 비용 차감 후 경제적 이익(EVA)과 성장의 가치 창출 여부를 분석합니다.",
                    run=_eva, params_model=EvaParams, explain=_explain_eva,
                    description="company_model_eva 라우트 함수 그대로(practice_models.eva_analysis).", **common),
        pg.NodeSpec("company_value_layers", "가치의 층", plain_label="가치 구성 분해",
                    plain_description="자산가치 → 현재 수익력 → 성장 가치 순으로 가치를 분해하고 층별 확률을 부여합니다.",
                    run=_layers, params_model=LayersParams, explain=_explain_layers,
                    description="company_model_value_layers 라우트 함수 그대로(Greenwald 3층 + 확률 가중).", **common),
        pg.NodeSpec("company_multiples", "배수·PEG", plain_label="PEG·멀티플",
                    plain_description="성장률·PEG 별 적정 주가와 ROE·배당 기반 정당 배수를 산출합니다.",
                    run=_multiples, params_model=MultiplesParams, explain=_explain_multiples,
                    description="company_model_multiples 라우트 함수 그대로.", **common),
        pg.NodeSpec("company_driver_mc", "영업 동인 몬테카를로", plain_label="영업 동인 몬테카를로",
                    plain_description="매출 성장·마진·재투자율을 확률적으로 변동시켜 주당 가치 분포를 산출합니다.",
                    run=_driver_mc, params_model=DriverMcParams, explain=_explain_driver_mc,
                    description="company_model_driver_mc 라우트 함수 그대로(시드 고정 재현).", **common),
        pg.NodeSpec("company_scenarios", "시나리오 가중", plain_label="확률가중 시나리오",
                    plain_description="약세·기본·강세 시나리오별 가정과 확률로 확률가중 적정가를 산출합니다.",
                    run=_scenarios, params_model=ScenariosParams, explain=_explain_scenarios,
                    description="company_model_scenarios 라우트 함수 그대로(행마다 샌드박스와 같은 엔진).", **common),
        pg.NodeSpec("company_decision_tree", "의사결정 나무", plain_label="의사결정 나무",
                    plain_description="승인·실패 등 분기 사건을 의사결정 나무로 구성해 기대 가치를 산출합니다.",
                    run=_tree, params_model=TreeParams, explain=_explain_tree,
                    description="company_model_decision_tree 라우트 함수 그대로.", **common),
        pg.NodeSpec("company_sotp", "합산가치(SOTP)", plain_label="SOTP 가치평가",
                    plain_description="사업 부문 가치와 상장 자회사 지분가치를 합산하고 지주사 할인을 반영합니다.",
                    run=_sotp, params_model=SotpParams, explain=_explain_sotp,
                    description="company_model_sotp 라우트 함수 그대로(자회사 시총 조회).", **common),
        pg.NodeSpec("company_real_option", "실물옵션", plain_label="실물옵션",
                    plain_description="확장·연기·포기 실물옵션의 가치를 블랙-숄즈·이항 모형으로 산출합니다.",
                    run=_real_option, params_model=RealOptionParams, explain=_explain_real_option,
                    description="company_model_real_option 라우트 함수 그대로(BS + CRR 이항).", **common),
    ):
        registry.register(spec)
