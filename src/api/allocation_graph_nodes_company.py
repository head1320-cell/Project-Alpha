"""AAS 그래프 — 기업 웨이브 (BL3 W3) · ★`company_routes` 라우트 함수를 그대로 부른다★
==============================================================================
계획 `happy-percolating-falcon.md` §BL3 W3. 같은 수인지는 `tests/test_allocation_graph_bl3w3.py` 골든이 라우트와 대조한다.

| 노드 | 부르는 것 |
|---|---|
| 가치평가 샌드박스 | `company_valuation_sandbox` (샌드박스 + 민감도 격자 + 풋볼필드 + Comps) |
| 역DCF · 가치 분포 | `company_reverse_dcf` · `company_valuation_distribution` |
| 재무 심층 · 위험 심층 | `company_financial_deep` · `company_risk_deep` |
| 매크로 민감도 | `macro_sensitivity_for` + `statistical_sensitivity(series_map=macro_series_map())` — 라우트와 같은 두 블록 |
| 테제 점검 | `company_thesis_check` (저장하지 않는다) — kill 조건은 `filter_ast` 조건(스크리너와 같은 편집기) |

## 정직성
- **종목은 이름으로 판정한다** — `stock_master.get_stock_name`. mock 가격 경로는 없는 코드에도 값을 주므로 가격으로 판정하지 않는다.
- **가격은 지어내지 않는다** — 비우면 `company_views.prices_for` 의 값과 출처, 못 구하면 사유 실패. 직접 넣으면 '직접 입력'.
- 엔진이 `available: false` 로 답하면(적자 기업의 역DCF · 재무 미적재 · 검증 못 한 테제) 숫자 대신 그 사유로 실패한다.
- 재무는 DART(파일 캐시)를 읽는다 — `/company` 화면·BK W5 `valuation_scores` 와 같은 경로다. 매크로 통계 블록만 저장소 경로.

## 하지 않는 것
- 테제 백테스트 — 동기 실행 + 기록 기본 True. W1 처럼 시작/읽기를 나눠야 하는데 테제 전용 실행 행이 없다(별도 설계).
- 기업 스냅샷 저장 — 마법사 THESIS 의 기록(BL4 대응표에서 다룬다).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.api import company_routes as cr
from src.api import screener_routes as _sr
from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _t
from src.api.allocation_graph_nodes import _FORBID, _ui
from src.api.allocation_graph_nodes_bl2 import macro_series_map
from src.data.mock_gate import mock_allowed
from src.engine import portfolio_graph as pg

_CODES = [{"label": "삼성전자", "value": "005930"}, {"label": "SK하이닉스", "value": "000660"},
          {"label": "NAVER", "value": "035420"}]
_TODAY = "오늘의 재무·가격으로 낸 값이에요 — 과거 시점의 판단이 아니라서 과거 검증에는 쓰지 않아요."


class _Company(BaseModel):
    model_config = _FORBID
    code: str = Field("005930", pattern=r"^\d{6}$", json_schema_extra={"x-ui": _ui(
        "종목", question="어느 기업을 볼까요?", presets=_CODES, help="6자리 종목코드예요. 모르는 코드는 계산하지 않아요.")})


class _Priced(_Company):
    price: float | None = Field(None, gt=0, json_schema_extra={"x-ui": _ui(
        "현재가", "advanced", unit="원", help="비우면 적재된 시세의 마지막 종가를 써요(출처를 함께 적어요).")})


def _company(p: _Company) -> dict:
    from src.data.stock_master import get_stock_name
    name = get_stock_name(p.code)
    if not name:
        raise pg.NodeFailure(f"모르는 종목코드예요({p.code}) — 종목 마스터에 없는 코드는 가치를 매기지 않아요.")
    return {"code": p.code, "name": name}


def _priced(p: _Priced) -> dict:
    c = _company(p)
    if p.price:
        return {**c, "price": float(p.price), "price_source": "직접 입력"}
    from src.engine import company_views as cv
    prices, source = cv.prices_for([p.code])
    if p.code not in prices:
        raise pg.NodeFailure(f"{c['name']}의 가격을 구하지 못했어요(출처: {source.get(p.code) or '없음'}) — "
                             "설정의 ‘현재가’에 직접 넣으면 계산해요.")
    return {**c, "price": prices[p.code], "price_source": source.get(p.code) or "미상"}


def _out(head: dict, result: dict, extra: dict | None = None) -> pg.NodeOutput:
    is_mock = bool(result.get("is_mock")) if isinstance(result, dict) else False
    practice = is_mock or mock_allowed()
    return pg.NodeOutput(values={}, view={**head, "result": result, **(extra or {})},
                         tags={"pit": "forward_only", "practice": practice, "sources": ["company_routes", "dart"]},
                         provenance={"practice": practice})


def _unavailable(result: dict, what: str) -> None:
    if isinstance(result, dict) and result.get("available") is False:
        raise pg.NodeFailure(f"{what} — {result.get('reason') or result.get('note') or '사유 미상'}")


def _base_trust(view: dict, prov: dict) -> list[dict]:
    out = [_t(ASSUMED, _TODAY)]
    src = view.get("price_source")
    if src:
        out.append(_t(CONFIRMED if src == "직접 입력" else UNKNOWN,
                      f"현재가 {view.get('price'):,.0f}원 — 출처: {src}."))
    if prov.get("practice"):
        out.append(_t(UNKNOWN, "개발 모드라 재무·가격이 합성(연습용)이에요 — 실제 기업 가치를 말해 주지 않아요."))
    return out


# ── 가치평가 샌드박스 ─────────────────────────────────────────────────────────

class SandboxParams(_Priced):
    rf: float | None = Field(None, ge=0, le=0.15, json_schema_extra={"x-ui": _ui(
        "무위험수익률", "advanced", help="비우면 국고채 10년(출처는 결과의 가정 표에 적어요).")})
    beta: float | None = Field(None, ge=0.1, le=3.0, json_schema_extra={"x-ui": _ui("베타", "advanced")})
    erp: float | None = Field(None, ge=0, le=0.15, json_schema_extra={"x-ui": _ui("시장위험프리미엄", "advanced")})
    g: float | None = Field(None, ge=0, le=0.05, json_schema_extra={"x-ui": _ui("영구성장률", "advanced")})
    years: int | None = Field(None, ge=3, le=20, json_schema_extra={"x-ui": _ui("예측기간", "advanced", unit="년")})


def _sandbox(inputs: dict, p: SandboxParams) -> pg.NodeOutput:
    head = _priced(p)
    out = cr.company_valuation_sandbox(p.code, price=head["price"], rf=p.rf, beta=p.beta, erp=p.erp, g=p.g, years=p.years)
    return _out(head, out)


def _explain_sandbox(view: dict, prov: dict, params: Any) -> dict:
    u = ((view.get("result") or {}).get("unified") or {})
    v, gap = u.get("value"), u.get("gap_pct")
    models = [m for m in u.get("models") or [] if m.get("available")]
    title = (f"{view.get('name')} 적정가 {v:,.0f}원 — 지금 가격이 그보다 {abs(gap):.0f}% {'높아요' if gap > 0 else '낮아요'}"
             if isinstance(v, (int, float)) and v > 0 and isinstance(gap, (int, float))
             # 적정가가 없으면(0) 괴리율도 0 으로 온다 — '차이 없음' 이 아니라 '정의 불가' 라서 차이를 말하지 않는다
             else f"{view.get('name')}의 적정가를 정하지 못했어요" if isinstance(v, (int, float)) and v <= 0
             else f"{view.get('name')} 가치를 매겼어요")
    facts = [f"{m['model']}: {m['value']:,.0f}원" for m in models if isinstance(m.get("value"), (int, float))]
    trust = [*_base_trust(view, prov),
             _t(ASSUMED, "적정가는 할인율·성장률 가정의 결과예요 — 가정 표와 민감도 격자를 함께 보세요.")]
    if len({round(m["value"], -3) for m in models if isinstance(m.get("value"), (int, float))}) > 1:
        trust.append(_t(ASSUMED, "모델마다 값이 달라요 — 하나로 합친 값은 평균이지 합의가 아니에요."))
    return {"title": title, "facts": facts, "trust": trust,
            "unmeasured": ["적정가로 수렴할지·언제 수렴할지(예측력)"]}


# ── 역DCF ────────────────────────────────────────────────────────────────────

def _reverse(inputs: dict, p: _Priced) -> pg.NodeOutput:
    head = _priced(p)
    out = cr.company_reverse_dcf(p.code, price=head["price"], market_cap=None, bracket_lo=-0.5, bracket_hi=0.5)
    _unavailable(out, "시장가를 정당화하는 성장률을 풀지 못했어요")
    return _out(head, out)


def _explain_reverse(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    ig, cg = r.get("implied_growth_pct"), r.get("current_growth_pct")
    title = (f"지금 가격은 앞으로 10년 현금흐름이 해마다 {ig:.1f}% 자란다고 믿는 가격이에요"
             if isinstance(ig, (int, float)) else "시장이 믿는 성장률을 풀었어요")
    facts = []
    if isinstance(cg, (int, float)):
        facts.append(f"지금까지의 성장률은 {cg:.1f}% — 차이 {r.get('gap_pp', 0):+.1f}%p")
    trust = [*_base_trust(view, prov),
             _t(ASSUMED, "성장률을 하나의 상수로 푼 값이에요 — 실제 성장 경로는 들쭉날쭉해요.")]
    if r.get("current_growth_reason"):
        trust.append(_t(UNKNOWN, f"지금까지의 성장률을 재지 못했어요 — {r['current_growth_reason']}"))
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["그 성장률이 실제로 나올지"]}


# ── 가치 분포 ────────────────────────────────────────────────────────────────

class DistributionParams(_Priced):
    n: int = Field(2000, ge=100, le=20000, json_schema_extra={"x-ui": _ui(
        "표본 수", "advanced", presets=[{"label": "500", "value": 500}, {"label": "2000", "value": 2000}])})


def _distribution(inputs: dict, p: DistributionParams) -> pg.NodeOutput:
    head = _priced(p)
    out = cr.company_valuation_distribution(p.code, price=head["price"], n=p.n)
    _unavailable(out, "적정가 분포를 만들지 못했어요")
    return _out(head, out)


def _explain_distribution(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    u = r.get("unified") or {}
    pp = u.get("price_percentile")
    title = (f"현재가는 적정가 분포의 {pp:.0f}번째 백분위예요" if isinstance(pp, (int, float)) else "적정가 분포를 그렸어요")
    facts = [f"P10 {u.get('p10', 0):,.0f} · P50 {u.get('p50', 0):,.0f} · P90 {u.get('p90', 0):,.0f}원"] if u.get("p50") else []
    sr = (r.get("model_disagreement") or {}).get("spread_ratio")
    if isinstance(sr, (int, float)):
        facts.append(f"모델끼리 {sr:.2f}배 갈려요 — 분포 폭보다 크면 불확실성의 주인은 모델 선택이에요.")
    widths = r.get("widths") or {}
    trust = [*_base_trust(view, prov)]
    if widths and not any(w.get("measured") for w in widths.values()):
        trust.append(_t(ASSUMED, "가정마다 흔들 폭은 잰 값이 아니라 정한 값이에요 — 분포의 폭도 가정이에요."))
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["폭 자체의 근거(측정된 불확실성)"]}


# ── 재무 심층 · 위험 심층 ─────────────────────────────────────────────────────

def _financial(inputs: dict, p: _Company) -> pg.NodeOutput:
    head = _company(p)
    out = cr.company_financial_deep(p.code)
    _unavailable(out, "재무 심층을 볼 수 없어요")
    return _out(head, out)


def _explain_financial(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    flags = (r.get("qoe") or {}).get("red_flags") or []
    title = f"{view.get('name')} 이익의 질에 경고 {len(flags)}개" if flags else f"{view.get('name')} 이익의 질·운전자본을 봤어요"
    return {"title": title, "facts": [str(f) for f in flags[:4]], "trust": _base_trust(view, prov),
            "unmeasured": ["공시 정정 전의 값(빈티지) — 지금 표는 정정이 덮은 값이에요"]}


def _risk(inputs: dict, p: _Priced) -> pg.NodeOutput:
    head = _priced(p)
    return _out(head, cr.company_risk_deep(p.code, price=head["price"]))


def _explain_risk(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    a = r.get("altman") or {}
    title = (f"Altman Z {a['z']:.2f} — {a.get('zone')}" if isinstance(a.get("z"), (int, float)) else "재무 위험을 봤어요")
    trust = [*_base_trust(view, prov)]
    b = r.get("beneish") or {}
    if b.get("available") is False:
        trust.append(_t(UNKNOWN, f"이익 조작 지표(Beneish)는 계산하지 못했어요 — {b.get('note') or '사유 미상'}"))
    note = (r.get("coverage") or {}).get("note")
    if note:
        trust.append(_t(ASSUMED, f"이자보상은 근사식이에요 — {note}"))
    return {"title": title, "facts": [], "trust": trust, "unmeasured": ["실제 부도 확률(이 점수는 판별 규칙이에요)"]}


# ── 매크로 민감도 ────────────────────────────────────────────────────────────

class MacroSensParams(_Priced):
    statistical: bool = Field(True, json_schema_extra={"x-ui": _ui(
        "통계 블록", "advanced", help="매크로 계열과의 월별 회귀도 함께 볼지예요(상관이지 인과가 아니에요).")})


def _macro_sens(inputs: dict, p: MacroSensParams) -> pg.NodeOutput:
    from src.engine.valuation import macro_sensitivity as ms
    head = _priced(p)
    out = ms.macro_sensitivity_for(p.code, head["price"])
    tags = None
    if p.statistical:
        series, tags = macro_series_map()
        out["statistical"] = ms.statistical_sensitivity(p.code, series_map=series)
    node = _out(head, out)
    if tags and tags.get("practice") is False:
        node.tags["sources"] = [*node.tags["sources"], *tags.get("sources", [])]
    return node


def _explain_macro_sens(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    rows = [x for x in r.get("rows") or [] if x.get("available")]
    up = next((x for x in rows if str(x.get("shock", "")).startswith("+")), None)
    title = (f"10년 금리가 1%p 오르면 적정가가 {up['value_pct']:+.1f}% 움직여요"
             if up and isinstance(up.get("value_pct"), (int, float)) else "매크로 충격에 대한 민감도를 봤어요")
    facts = [f"{x['shock']}: {x['value_pct']:+.1f}%" for x in rows if isinstance(x.get("value_pct"), (int, float))]
    trust = [*_base_trust(view, prov),
             _t(CONFIRMED, "금리 블록은 할인율 공식을 그대로 따라간 값이에요(표본이 아니라 항등식)."),
             *[_t(UNKNOWN, f"{x.get('shock')} → {x.get('target')}: {x.get('reason')}") for x in r.get("unavailable") or []][:3]]
    if "statistical" in r:
        trust.append(_t(ASSUMED, "통계 블록은 과거에 같이 움직인 정도예요 — 원인이라는 뜻은 아니에요."))
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["실제 이익(EPS)에 미치는 영향 — 채널이 없어요"]}


# ── 테제 점검 ────────────────────────────────────────────────────────────────

class ThesisParams(_Company):
    claim: str = Field("", max_length=4000, json_schema_extra={"x-ui": _ui(
        "논지", question="이 기업에 대해 무엇을 믿나요?", help="한두 문장이면 충분해요.")})
    kill_conditions: _sr.FilterGroupModel = Field(
        default_factory=lambda: _sr.FilterGroupModel(logic="AND", conditions=[], groups=[]),
        json_schema_extra={"x-ui": _ui("버릴 조건", question="어떻게 되면 이 논지를 버릴까요?", widget="filter",
                                       help="조건 하나하나가 ‘이렇게 되면 틀렸다’ 예요. 묶음(그룹)은 쓰지 않아요.")})


def _thesis(inputs: dict, p: ThesisParams) -> pg.NodeOutput:
    head = _company(p)
    if p.kill_conditions.groups:
        raise pg.NodeFailure("버릴 조건은 한 줄씩 나열해 주세요 — 묶음(그룹)은 논지 점검에서 쓰지 않아요.")
    kills = [c.model_dump(exclude_none=True) for c in p.kill_conditions.conditions]
    out = cr.company_thesis_check(p.code, cr.ThesisCheckRequest(claim=p.claim, kill_conditions=kills))
    if out.get("available") is False:
        raise pg.NodeFailure(f"논지를 점검할 수 없어요 — {'; '.join(out.get('errors') or []) or out.get('reason') or '사유 미상'}")
    return _out(head, out)


_TIER_KO = {"backtestable": "과거 검증 가능", "screen_only_backtest_lookahead": "근사 검증(미래 정보 섞임)",
            "screen_only": "지금 점검만"}


def _explain_thesis(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    counts = ((r.get("kill_conditions") or {}).get("counts")) or {}
    facts = [f"{_TIER_KO.get(k, k)}: {v}개" for k, v in counts.items() if v]
    trust = [*_base_trust(view, prov)]
    if counts.get("screen_only_backtest_lookahead"):
        trust.append(_t(ASSUMED, "일부 조건은 스냅샷 값이라 과거 검증에 쓰면 미래 정보가 섞여요."))
    return {"title": f"버릴 조건 {sum(counts.values())}개를 점검했어요", "facts": facts, "trust": trust,
            "unmeasured": ["논지가 맞는지 — 이 점검은 반증할 수 있는지만 봐요"]}


# ── 등록 ─────────────────────────────────────────────────────────────────────

def register(registry: pg.Registry) -> None:
    common = {"inputs": (), "outputs": (), "category": "기업", "stage": "signal"}
    for spec in (
        pg.NodeSpec("company_valuation", "가치평가 샌드박스", plain_label="적정가 매기기",
                    plain_description="가정을 바꿔 가며 기업의 적정가와 그 민감도를 봐요.",
                    run=_sandbox, params_model=SandboxParams, explain=_explain_sandbox,
                    description="company_valuation_sandbox 라우트 함수 그대로.", **common),
        pg.NodeSpec("reverse_dcf", "역DCF", plain_label="시장이 믿는 성장률",
                    plain_description="지금 가격을 정당화하려면 얼마나 자라야 하는지 거꾸로 풀어요.",
                    run=_reverse, params_model=_Priced, explain=_explain_reverse,
                    description="company_reverse_dcf 라우트 함수 그대로.", **common),
        pg.NodeSpec("valuation_distribution", "가치 분포", plain_label="적정가의 범위",
                    plain_description="가정을 흔들어 적정가가 어디서 어디까지 나오는지 봐요.",
                    run=_distribution, params_model=DistributionParams, explain=_explain_distribution,
                    description="company_valuation_distribution 라우트 함수 그대로.", **common),
        pg.NodeSpec("financial_deep", "재무 심층", plain_label="이익의 질 보기",
                    plain_description="이익이 현금으로 들어오는지, 운전자본·자본배치는 어떤지 봐요.",
                    run=_financial, params_model=_Company, explain=_explain_financial,
                    description="company_financial_deep 라우트 함수 그대로.", **common),
        pg.NodeSpec("risk_deep", "위험 심층", plain_label="재무 위험 보기",
                    plain_description="부도 판별 점수와 금리가 오를 때의 버팀을 봐요.",
                    run=_risk, params_model=_Priced, explain=_explain_risk,
                    description="company_risk_deep 라우트 함수 그대로.", **common),
        pg.NodeSpec("company_macro_sensitivity", "매크로 민감도", plain_label="금리에 얼마나 흔들리나",
                    plain_description="금리 같은 거시 충격에 적정가가 얼마나 움직이는지 봐요.",
                    run=_macro_sens, params_model=MacroSensParams, explain=_explain_macro_sens,
                    description="macro_sensitivity_for + statistical_sensitivity(저장된 매크로 관측).", **common),
        pg.NodeSpec("thesis_check", "테제 점검", plain_label="논지 점검하기",
                    plain_description="내 논지와 버릴 조건을 적으면 검증할 수 있는 조건인지 가려 줘요.",
                    run=_thesis, params_model=ThesisParams, explain=_explain_thesis,
                    description="company_thesis_check 라우트 함수(저장하지 않는다).", **common),
    ):
        registry.register(spec)
