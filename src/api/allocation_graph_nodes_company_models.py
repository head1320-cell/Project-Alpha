"""AAS 그래프 — 기업 분석 현업 모델 노드 (BL3 W3b) · ★`company_model_routes` 라우트 함수를 그대로 부른다★
==============================================================================
계획 `happy-percolating-falcon.md` §BL3 W3b. 엔진은 `src/engine/valuation/practice_models.py`(순수), 데이터는 라우트가 댄다.
같은 수인지는 `tests/test_allocation_graph_bl3w3b.py` 골든이 라우트와 대조한다.

C1(데이터형): EVA·가치 동인 · 가치의 층(Greenwald 3층) · 배수·PEG·정당 배수 · 영업 동인 몬테카를로.
공통: 종목은 이름으로 판정 · 가격은 출처와 함께(W3 `_priced`) · 결과의 `inputs` 가 관측/근사/가정/미상을 가른다 · 못 하면 사유.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from src.api import company_model_routes as cmr
from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _t
from src.api.allocation_graph_nodes import _ui
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
        "초과이익 소멸 기간", question="지금의 초과이익(EVA)이 몇 년에 걸쳐 사라진다고 볼까요?", unit="년",
        presets=[{"label": "3년", "value": 3}, {"label": "5년", "value": 5}, {"label": "10년", "value": 10}],
        help="경쟁이 초과이익을 깎아 먹는 속도예요 — 가정이에요.")})
    g: float | None = Field(None, ge=-0.05, le=0.15, json_schema_extra={"x-ui": _ui(
        "성장률", "advanced", help="가치 동인 공식의 성장률이에요. 비우면 영구성장률을 써요.")})
    ronic: float | None = Field(None, gt=-1, le=1, json_schema_extra={"x-ui": _ui(
        "새 투자 수익률", "advanced", help="새로 투자한 돈이 버는 수익률(RONIC)이에요. 비우면 최근 ROIC 를 써요.")})


def _eva(inputs: dict, p: EvaParams) -> pg.NodeOutput:
    head = _priced(p)
    return _call(cmr.company_model_eva, head,
                 cmr.EvaRequest(price=head["price"], fade_years=p.fade_years, g=p.g, ronic=p.ronic),
                 "EVA 를 계산하지 못했어요")


def _explain_eva(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    last, vd = r.get("latest") or {}, r.get("value_driver") or {}
    eva, roic, wacc = last.get("eva"), last.get("roic"), last.get("wacc")
    title = ((f"자본비용을 {eva / _EOK:,.0f}억 넘게 벌어요" if eva >= 0 else f"자본비용보다 {-eva / _EOK:,.0f}억 덜 벌어요")
             if isinstance(eva, (int, float)) else "EVA 를 계산했어요")
    facts = []
    if isinstance(roic, (int, float)) and isinstance(wacc, (int, float)):
        facts.append(f"투하자본수익률 {roic:.1%} · 자본비용 {wacc:.1%}")
    if vd.get("available"):
        facts.append("성장이 가치를 만들어요(새 투자 수익률 > 자본비용)" if vd.get("growth_creates_value")
                     else "성장이 가치를 깎아요(새 투자 수익률 < 자본비용) — 덜 자랄수록 나아요")
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
        help="세 가중의 합은 1 이어야 해요 — 맞지 않으면 계산하지 않아요.")})
    w_epv: float = Field(0.25, ge=0, le=1, json_schema_extra={"x-ui": _ui(
        "수익력가치 가중", question="지금 버는 만큼만 계속 벌 확률은?",
        presets=[{"label": "20%", "value": 0.2}, {"label": "25%", "value": 0.25}, {"label": "30%", "value": 0.3}])})
    w_full: float = Field(0.5, ge=0, le=1, json_schema_extra={"x-ui": _ui(
        "성장까지 가중", question="성장까지 이뤄질 확률은?",
        presets=[{"label": "20%", "value": 0.2}, {"label": "50%", "value": 0.5}, {"label": "70%", "value": 0.7}])})


def _layers(inputs: dict, p: LayersParams) -> pg.NodeOutput:
    head = _priced(p)
    return _call(cmr.company_model_value_layers, head,
                 cmr.LayersRequest(price=head["price"], w_asset=p.w_asset, w_epv=p.w_epv, w_full=p.w_full),
                 "가치의 층을 쌓지 못했어요")


def _explain_layers(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    L = {x["key"]: x for x in r.get("layers") or []}
    price = view.get("price")
    tops = [("asset", L.get("asset", {}).get("per_share")), ("epv", L.get("epv", {}).get("per_share")),
            ("full", r.get("full_per_share"))]
    names = {"asset": "자산가치", "epv": "수익력가치", "full": "성장까지 넣은 가치"}
    covered = [k for k, v in tops if isinstance(v, (int, float)) and isinstance(price, (int, float)) and v >= price]
    title = (f"지금 가격은 {names[covered[0]]} 안에 들어와요" if covered else
             "지금 가격은 성장까지 넣은 가치보다도 높아요" if isinstance(price, (int, float)) else "가치의 층을 쌓았어요")
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
            "unmeasured": ["자산을 다시 만드는 데 드는 돈(재생산원가) — 장부가로 대신했어요"]}


# ── 배수 · PEG · 정당 배수 ───────────────────────────────────────────────────

class MultiplesParams(_Priced):
    peers: bool = Field(True, json_schema_extra={"x-ui": _ui(
        "피어 PER 함께", "advanced", help="같은 업종 종목들의 PER 중앙값으로 본 가격도 함께 봐요(업종 표를 계산해 느려요).")})


def _multiples(inputs: dict, p: MultiplesParams) -> pg.NodeOutput:
    head = _priced(p)
    return _call(cmr.company_model_multiples, head, cmr.MultiplesRequest(price=head["price"], peers=p.peers),
                 "배수로 보지 못했어요")


def _explain_multiples(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    j = r.get("justified") or {}
    per, peg = r.get("per"), r.get("peg")
    title = (f"PER {per:.1f}배 · PEG {peg:.2f}" if isinstance(per, (int, float)) and isinstance(peg, (int, float))
             else f"PER {per:.1f}배 (PEG 는 못 냈어요)" if isinstance(per, (int, float)) else "배수를 봤어요")
    facts = []
    if isinstance(j.get("pbr"), (int, float)):
        facts.append(f"ROE 로 본 정당 PBR {j['pbr']:.2f}배 → {_won(j.get('pbr_price'))}")
    if isinstance(j.get("per"), (int, float)):
        facts.append(f"배당으로 본 정당 PER {j['per']:.1f}배 → {_won(j.get('per_price'))}")
    peer = r.get("peer") or {}
    if isinstance(peer.get("per_price"), (int, float)):
        facts.append(f"피어 PER 중앙값 {peer['per_median']:.1f}배 → {_won(peer['per_price'])}")
    trust = [*_base_trust(view, prov), *_history_trust(r), *_inputs_trust(r),
             _t(ASSUMED, "PEG 1 이 적정이라는 것은 관행이지 법칙이 아니에요 — 격자는 가정을 바꿔 보는 표예요.")]
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
        "매출 성장률 흔들림", question="매출 성장률이 해마다 얼마나 빗나갈 수 있을까요?",
        presets=[{"label": "±1%p", "value": 0.01}, {"label": "±3%p", "value": 0.03}, {"label": "±6%p", "value": 0.06}],
        help="표준편차예요. 중심은 지난 재무에서 읽어요.")})
    sigma_margin: float = Field(0.02, ge=0, le=0.5, json_schema_extra={"x-ui": _ui(
        "영업이익률 흔들림", question="영업이익률은 얼마나 빗나갈 수 있을까요?",
        presets=[{"label": "±1%p", "value": 0.01}, {"label": "±2%p", "value": 0.02}, {"label": "±4%p", "value": 0.04}])})
    sigma_reinvest: float = Field(0.01, ge=0, le=0.5, json_schema_extra={"x-ui": _ui("재투자율 흔들림", "advanced")})
    years: int = Field(5, ge=3, le=15, json_schema_extra={"x-ui": _ui("예측 기간", "advanced", unit="년")})
    n: int = Field(2000, ge=100, le=20000, json_schema_extra={"x-ui": _ui("경로 수", "advanced")})
    seed: int = Field(20260927, json_schema_extra={"x-ui": _ui("난수 씨앗", "advanced",
                                                               help="같은 씨앗이면 같은 결과가 나와요.")})


def _driver_mc(inputs: dict, p: DriverMcParams) -> pg.NodeOutput:
    head = _priced(p)
    req = cmr.DriverMcRequest(price=head["price"], sigma_growth=p.sigma_growth, sigma_margin=p.sigma_margin,
                              sigma_reinvest=p.sigma_reinvest, years=p.years, n=p.n, seed=p.seed)
    return _call(cmr.company_model_driver_mc, head, req, "영업 동인으로 가치 범위를 만들지 못했어요")


def _explain_driver_mc(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    q = r.get("quantiles") or {}
    pp = r.get("price_percentile")
    title = (f"지금 가격은 가치 범위의 {pp:.0f}번째 백분위예요" if isinstance(pp, (int, float))
             else "영업 동인으로 가치 범위를 만들었어요")
    facts = [f"10~90%: {_won(q.get('p10'))} ~ {_won(q.get('p90'))} · 중앙 {_won(q.get('p50'))}"] if q else []
    if isinstance(r.get("negative_share"), (int, float)) and r["negative_share"] > 0:
        facts.append(f"경로의 {r['negative_share']:.0%} 는 주당 가치가 0 아래예요(부채가 더 커요)")
    trust = [*_base_trust(view, prov), *_history_trust(r), *_inputs_trust(r)]
    if r.get("n_rejected"):
        trust.append(_t(UNKNOWN, f"매출이 사라지는 경로 {r['n_rejected']}개는 모형 밖이라 버렸어요"))
    if r.get("note"):
        trust.append(_t(ASSUMED, r["note"].replace("**", "")))
    return {"title": title, "facts": facts, "trust": trust,
            "unmeasured": ["동인끼리의 상관(함께 나빠지는 해) — 독립으로 뒀어요"]}


# ── 등록 ─────────────────────────────────────────────────────────────────────

def register(registry: pg.Registry) -> None:
    common = {"inputs": (), "outputs": (), "category": "기업", "stage": "signal"}
    for spec in (
        pg.NodeSpec("company_eva", "EVA·가치 동인", plain_label="자본비용을 넘게 버나",
                    plain_description="투하자본에 드는 비용을 빼고도 남는 이익(EVA)과, 성장이 가치를 만드는지 봐요.",
                    run=_eva, params_model=EvaParams, explain=_explain_eva,
                    description="company_model_eva 라우트 함수 그대로(practice_models.eva_analysis).", **common),
        pg.NodeSpec("company_value_layers", "가치의 층", plain_label="가치가 어디서 나오나",
                    plain_description="자산 → 지금의 이익력 → 성장으로 가치를 층층이 쌓고, 층마다 확률을 둬요.",
                    run=_layers, params_model=LayersParams, explain=_explain_layers,
                    description="company_model_value_layers 라우트 함수 그대로(Greenwald 3층 + 확률 가중).", **common),
        pg.NodeSpec("company_multiples", "배수·PEG", plain_label="성장 대비 몇 배가 맞나",
                    plain_description="성장률과 PEG 를 바꿔 가며 맞는 주가를 보고, ROE·배당으로 정당한 배수를 봐요.",
                    run=_multiples, params_model=MultiplesParams, explain=_explain_multiples,
                    description="company_model_multiples 라우트 함수 그대로.", **common),
        pg.NodeSpec("company_driver_mc", "영업 동인 몬테카를로", plain_label="매출·마진이 흔들리면",
                    plain_description="매출 성장·마진·재투자를 흔들어 주당 가치가 어디서 어디까지 나오는지 봐요.",
                    run=_driver_mc, params_model=DriverMcParams, explain=_explain_driver_mc,
                    description="company_model_driver_mc 라우트 함수 그대로(시드 고정 재현).", **common),
    ):
        registry.register(spec)
