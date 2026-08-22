"""국내 변동성 시나리오팩 — 팩터 기반 충격 모델 (Full Expansion P3-b)
==============================================================================
지시서 요구: 한국 시장 변동성에 맞춘 기본 시나리오팩 7종. 각 시나리오는
  · 충격 정의와 출처/가정
  · 시장·섹터·팩터·개별종목 충격
  · 상관 상승·변동성 상승·유동성 악화 가정
  · 충격 후 P&L vs 기준
  · VaR·CVaR·MDD 프록시, 리스크 기여 변화
  · 가장 취약한 슬리브·종목·팩터·유동성 버킷
  · 충격 강도 사용자 조절
  · 시나리오별 실행 가능성(차입·거래대금·체결실패 위험)
을 제공한다.

설계 (기존 M8 stress_test_analyzer는 리스크탭·스크리너가 쓰므로 무변경):
  · 팩터 노출 = 각 종목의 {시장β·규모·모멘텀·가치·레버리지·유동성·반도체·수급민감}
    (fundamentals/price 스토어·master 재사용, factor-xray 관례와 동일).
  · 시나리오 충격 = 팩터별 계수 × 종목 노출의 합 + 시장 기본 충격. severity 배율.
  · 개별종목 충격을 팩터별로 분해 → "무엇이 이 종목을 때렸나" 귀속.
  · 실데이터 없으면 노출은 정직 결측(0 기여) — 합성 항 만들지 않음.
"""

from __future__ import annotations

import logging
import math

import numpy as np

logger = logging.getLogger(__name__)

# ── 팩터 정의 (표준화 후 사용) ────────────────────────────────────────────────
# id → 라벨. 노출은 크로스섹션 z-score(반도체는 0/1 더미).
FACTORS = {
    "mkt_beta": "시장 베타",
    "size": "규모(소형=+)",
    "momentum": "모멘텀",
    "value": "저평가(가치)",
    "leverage": "레버리지",
    "illiquidity": "저유동성",
    "semi": "반도체 밸류체인",
}

# ── 7종 시나리오: factor→계수(%), market=시장 기본충격(%), + 정성 메타 ──────────
# 계수 부호: 음수=악재. size 노출은 소형일수록 큼(소형 취약 시나리오는 음계수).
SCENARIOS: dict[str, dict] = {
    "shortsell_regulation": {
        "label": "공매도 규제·차입 급감",
        "description": "공매도 금지/재개 또는 대차 공급 급감 — 헤지 청산·숏스퀴즈로 고차입·고공매도잔고주 급변동.",
        # ★스펙 §5 는 이 패밀리에 "데이터가 신뢰할 수 있는 경우에만" 이라는 단서를 단다★
        # 이 저장소에는 대차잔고·차입가능수량 피드가 없다. 그래서 이 팩은 실측이 아니라
        # **가정 기반 계수 모델**이고, 그 사실을 침묵으로 두지 않고 출처에 적는다.
        "source": "규제 발표 / 대차잔고·차입가능수량 급감 가정 "
                  "(대차 데이터 피드 없음 — 실측이 아닌 가정 모델)",
        "market": -2.0,
        "factors": {"leverage": -4.0, "illiquidity": -5.0, "momentum": 3.0, "size": -3.0},
        "assumptions": {"corr_rise": 0.15, "vol_rise": 0.40, "liquidity_deteriorate": 0.6},
        "execution": "숏 커버 급증·차입 불가로 롱숏·헤지 전략 실행 위험 최고. 대차 데이터 신선도 필수.",
        "hedge_note": "지수 풋/인버스로 시장 충격 일부 상쇄 가능하나 개별 숏 청산비용은 헤지 불가.",
    },
    "leverage_unwind": {
        "label": "레버리지·테마 과열 급청산",
        "description": "신용융자·CFD 청산과 테마 과열 붕괴 — 고모멘텀·고레버리지·소형주 연쇄 하락(반대매매).",
        "source": "신용잔고 급증 후 반대매매 / 테마 집중 붕괴 가정",
        "market": -4.0,
        "factors": {"momentum": -8.0, "leverage": -5.0, "size": -6.0, "illiquidity": -4.0},
        "assumptions": {"corr_rise": 0.25, "vol_rise": 0.60, "liquidity_deteriorate": 0.7},
        "execution": "반대매매 물량으로 소형주 체결 실패·슬리피지 급증. 하한가 직행 위험.",
        "hedge_note": "테마 집중 노출을 사전 축소하는 것이 유일한 실효 헤지. 사후 헤지 곤란.",
    },
    "krw_sharp_move": {
        "label": "원화 급변동",
        "description": "원/달러 급등(약세) — 외국인 순매도·수입원가 상승. 수출 대형주는 상대적 방어.",
        "source": "USD/KRW +10~15% 급등 / 외국인 자금 이탈 가정",
        "market": -3.0,
        "factors": {"mkt_beta": -3.0, "value": 2.0, "semi": 2.0, "size": -2.0},
        "assumptions": {"corr_rise": 0.20, "vol_rise": 0.35, "liquidity_deteriorate": 0.4},
        "execution": "외국인 순매도로 대형주 거래대금은 유지되나 스프레드 확대. 실행 가능성 중간.",
        "hedge_note": "USD 자산·수출주 비중으로 부분 헤지. FX 선물은 v1 범위 밖.",
    },
    "semi_selloff": {
        "label": "반도체 밸류체인 급락",
        "description": "메모리 업황·미국 반도체 규제 충격 — 반도체·소부장 집중 하락, 지수 견인.",
        "source": "HBM/메모리 수요 둔화 or 수출규제 / 반도체 지수 -20% 가정",
        "market": -3.0,
        "factors": {"semi": -18.0, "mkt_beta": -2.0, "momentum": -3.0},
        "assumptions": {"corr_rise": 0.30, "vol_rise": 0.45, "liquidity_deteriorate": 0.3},
        "execution": "대형 반도체는 유동성 충분해 실행 가능. 소부장은 체결 위험 상승.",
        "hedge_note": "반도체 ETF 인버스·지수 헤지 유효. 소부장 개별 리스크는 잔존.",
    },
    "valueup_collapse": {
        "label": "밸류업 기대 붕괴",
        "description": "정책 후퇴·주주환원 기대 되돌림 — 저PBR·고배당 '밸류업 수혜주' 되돌림.",
        "source": "밸류업 정책 후퇴 / 저PBR 리레이팅 되돌림 가정",
        "market": -1.5,
        "factors": {"value": -9.0, "size": 2.0, "mkt_beta": -1.0},
        "assumptions": {"corr_rise": 0.10, "vol_rise": 0.25, "liquidity_deteriorate": 0.3},
        "execution": "금융·지주 대형주 중심이라 유동성 양호. 실행 가능성 높음.",
        "hedge_note": "성장주 상대 비중 확대로 스타일 헤지 가능. 지수 헤지 효과는 제한적.",
    },
    "earnings_dispersion": {
        "label": "어닝시즌 분산 확대",
        "description": "실적 서프라이즈/쇼크 양극화 — 어닝 시즌 종목별 분산 급증, 팩터 상관 붕괴.",
        "source": "실적 발표 집중기 / 종목별 특이변동성 급증 가정",
        "market": -1.0,
        "factors": {"momentum": -4.0, "value": 2.0},
        "assumptions": {"corr_rise": -0.15, "vol_rise": 0.30, "liquidity_deteriorate": 0.2},
        "execution": "지수 충격은 작으나 개별 종목 갭 위험 — 실적일 전후 체결 위험.",
        "hedge_note": "지수 헤지 효과 낮음(특이위험 지배). 종목 분산이 최선의 방어.",
    },
    "retail_flow_reversal": {
        "label": "개인 수급 반전·유동성 위축",
        "description": "개인 자금 이탈과 거래대금 급감 — 개인 수급 의존 소형·저유동주 급락.",
        "source": "거래대금 급감·개인 순매도 전환 / 유동성 위축 가정",
        "market": -2.5,
        "factors": {"illiquidity": -8.0, "size": -6.0, "momentum": -3.0},
        "assumptions": {"corr_rise": 0.20, "vol_rise": 0.40, "liquidity_deteriorate": 0.8},
        "execution": "저유동주 체결 실패·슬리피지 최고. 참여율 제약으로 청산 수일 소요 가능.",
        "hedge_note": "유동성 버킷을 대형주로 이동하는 것이 유일한 실효 방어.",
    },
    # ── Phase 9 추가 4종 — 스펙 §5 의 빈 패밀리를 메운다 ────────────────────────
    # 기존 7종과 **같은 7팩터 노출 행렬**을 쓴다. 새 노출 로더를 만들지 않는다 —
    # 새 팩터를 도입하면 `_load_exposures` 가 두 갈래가 되고, 그때부터 시나리오마다
    # 노출이 다른 뜻을 갖게 된다.
    "vol_shock_liquidity_vacuum": {
        "label": "변동성 급등·유동성 진공",
        "description": "변동성 급등으로 마켓메이커가 호가를 거두고 호가창이 얇아짐 — "
                       "고베타·저유동주가 같은 물량에 훨씬 크게 밀린다.",
        "source": "VIX/VKOSPI 급등 + 호가 스프레드 확대 / 시장조성 축소 가정",
        "market": -5.0,
        "factors": {"mkt_beta": -5.0, "illiquidity": -7.0, "size": -4.0, "momentum": -2.0},
        "assumptions": {"corr_rise": 0.35, "vol_rise": 0.90, "liquidity_deteriorate": 0.85},
        "execution": "체결 자체가 어려워지는 구간 — 시장가 주문은 스프레드를 그대로 지불한다. "
                     "분할 체결·참여율 제약으로 청산이 하루 안에 끝나지 않을 수 있다.",
        "hedge_note": "변동성 급등 **뒤에** 사는 헤지는 이미 비싸다. 사전 보유한 지수 풋/"
                      "현금 비중만 실효가 있다는 것이 이 시나리오의 요지다.",
    },
    "credit_conditions_tightening": {
        "label": "신용·금융환경 긴축",
        "description": "금융환경지수 악화와 크레딧 스프레드 확대 — 차환에 의존하는 "
                       "고레버리지 기업이 먼저 무너진다.",
        "source": "NFCI 상승·회사채 스프레드 확대 / 차환 리스크 가정",
        "market": -3.5,
        "factors": {"leverage": -7.0, "size": -4.0, "illiquidity": -3.0, "value": 1.5},
        "assumptions": {"corr_rise": 0.25, "vol_rise": 0.50, "liquidity_deteriorate": 0.6},
        "execution": "대형주 유동성은 유지되나 신용도 낮은 종목은 매도 압력이 집중된다.",
        "hedge_note": "레버리지 노출 축소가 직접적인 방어. 지수 헤지는 종목별 신용 차이를 "
                      "구분하지 못한다.",
        # ★같은 이름의 팩터가 있지만 다른 물건이다★ 타이밍 카탈로그의 `financial_conditions`
        # 는 NFCI 빈티지를 **읽는** 팩터이고(이 환경에는 FRED 키가 없어 unavailable),
        # 이쪽은 그 긴축이 일어났다고 **가정한** 계수 모델이다. 하나가 되면 안 된다.
        "data_note": "긴축을 실측하지 않고 가정한다 — NFCI 실측이 필요한 판단은 타이밍 팩터 "
                     "`financial_conditions` 쪽이며 그건 FRED 키가 있어야 값이 나온다.",
    },
    "corr_convergence_hedge_failure": {
        "label": "상관 수렴·주식채권 헤지 실패",
        "description": "위기에 상관이 1로 수렴해 분산효과가 사라지고, 채권이 주식을 방어하지 "
                       "못하는 국면 — 2022년형 동반 하락.",
        "source": "위기 상관 수렴 / 주식·채권 동반 하락 가정",
        "market": -4.0,
        "factors": {"mkt_beta": -4.0, "size": -2.0, "value": -1.0},
        "assumptions": {"corr_rise": 0.45, "vol_rise": 0.55, "liquidity_deteriorate": 0.4},
        "execution": "지수 대형주 중심이라 체결 자체는 가능. 문제는 분산이 작동하지 않는 것.",
        "hedge_note": "★이 팩에서 상관 수렴은 가정값이다★ 실제 보유 포트폴리오의 상관이 "
                      "수렴하면 변동성·VaR 이 얼마나 변하는지는 `/stress-correlation` 이 "
                      "공분산을 다시 구성해 **계산**한다 — 그쪽을 함께 보라. 여기서 그 계산을 "
                      "다시 구현하지 않는다.",
    },
    "stagflation_regime": {
        "label": "스태그플레이션 국면",
        "description": "성장 둔화와 인플레 고착이 겹치는 국면 — 원가는 오르는데 수요는 "
                       "줄어 마진이 양쪽에서 눌린다.",
        "source": "성장률 하향 + 물가 상방 고착 / 실질금리 상승 가정",
        "market": -3.0,
        "factors": {"momentum": -3.0, "leverage": -4.0, "size": -3.0, "semi": -3.0,
                    "value": 2.5},
        "assumptions": {"corr_rise": 0.20, "vol_rise": 0.40, "liquidity_deteriorate": 0.45},
        "execution": "충격이 서서히 반영되는 국면이라 체결 위험 자체는 낮다.",
        "hedge_note": "가치·배당 쪽 상대 비중과 원자재 노출이 부분 방어. 지수 헤지는 국면 "
                      "지속 기간이 길어 비용이 누적된다.",
    },
}


def _z(vals: list[float | None]) -> np.ndarray:
    """크로스섹션 z-score. 결측(None)은 0(중립 노출 — 합성 항 아님, 정직 결측)."""
    arr = np.array([v if isinstance(v, (int, float)) and math.isfinite(v) else np.nan for v in vals],
                   dtype=float)
    m = np.isfinite(arr)
    out = np.zeros(len(vals))
    if m.sum() >= 2:
        mu, sd = arr[m].mean(), arr[m].std(ddof=0)
        if sd > 1e-9:
            out[m] = np.clip((arr[m] - mu) / sd, -3, 3)
    return out


def _load_exposures(codes: list[str]) -> tuple[dict[str, np.ndarray], list[str], list[str]]:
    """종목별 팩터 노출 행렬 (표준화). (exposures{factor:vec}, names, coverage_notes)."""
    from src.data.fundamentals_store import FundamentalsStore
    from src.data.price_factors_store import PriceFactorsStore
    from src.data.stock_master import get_market_cap, get_stock_name, get_stock_sector

    fs, ps = FundamentalsStore.get_default(), PriceFactorsStore.get_default()
    beta, mcap, mom, ey, debt, amount, semi, names = [], [], [], [], [], [], [], []
    n_semi = 0
    for c in codes:
        f = fs.get_factors(c, None) or {}
        p = ps.get_factors(c, None) or {}
        beta.append(p.get("beta_1y"))
        mc = get_market_cap(c)
        mcap.append(math.log10(mc) if isinstance(mc, (int, float)) and mc > 0 else None)
        mom.append(p.get("momentum_12_1") if p.get("momentum_12_1") is not None else p.get("return_6m"))
        ey.append(f.get("earnings_yield") if f.get("earnings_yield") is not None
                  else (1.0 / f["per"] if isinstance(f.get("per"), (int, float)) and f["per"] > 0 else None))
        d2e = f.get("debt_to_equity")
        debt.append(float(d2e) if d2e is not None else None)
        amount.append(p.get("amount_20d_avg") if p.get("amount_20d_avg") is not None else p.get("turnover_rate"))
        sec = (get_stock_sector(c) or "")
        is_semi = 1.0 if ("반도체" in sec or "전자" in sec) else 0.0
        n_semi += int(is_semi)
        semi.append(is_semi)
        names.append(get_stock_name(c) or c)

    exp = {
        "mkt_beta": _z(beta),
        "size": -_z(mcap),          # 소형일수록 +
        "momentum": _z(mom),
        "value": _z(ey),
        "leverage": _z(debt),
        "illiquidity": -_z(amount),  # 저유동일수록 +
        "semi": np.array(semi),      # 0/1 더미
    }
    notes = []
    cov = {k: int(np.count_nonzero(v)) for k, v in exp.items()}
    weak = [FACTORS[k] for k, v in cov.items() if v == 0]
    if weak:
        notes.append(f"노출 결측 팩터(0 기여): {', '.join(weak)} — 실데이터 적재 시 채워짐(정직 결측).")
    if n_semi:
        notes.append(f"반도체 밸류체인 분류 {n_semi}종목 (KRX 섹터 기준).")
    return exp, names, notes


#: 인라인 정의에 반드시 있어야 하는 키 — 없으면 지어내지 않고 거절한다.
_REQUIRED_DEFINITION_KEYS = ("market", "factors", "assumptions")


def run_scenario(codes: list[str], weights: dict[str, float], scenario: str,
                 severity: float = 1.0, sleeves: dict[str, str] | None = None,
                 definition: dict | None = None) -> dict:
    """시나리오 충격 → 종목별·팩터별·포트폴리오 P&L + 취약 귀속.

    `definition` 을 주면 카탈로그를 찾지 않고 그 정의로 계산한다(사용자 정의 팩, Phase 9).
    ★계산은 한 벌뿐이다★ 인라인 팩을 위해 별도 실행 경로를 만들면 등록된 팩과 사용자 팩이
    서로 다른 수식으로 채점되고, 두 결과를 나란히 놓는 것 자체가 거짓이 된다.
    """
    if definition is not None:
        missing = [k for k in _REQUIRED_DEFINITION_KEYS if k not in definition]
        if missing:
            return {"error": True,
                    "message": f"시나리오 정의에 필수 항목이 없습니다: {', '.join(missing)}"}
        unknown = set(definition["factors"]) - set(FACTORS)
        if unknown:
            return {"error": True,
                    "message": f"알 수 없는 팩터: {', '.join(sorted(unknown))}. "
                               f"가능한 값: {', '.join(FACTORS)}"}
    elif scenario not in SCENARIOS:
        return {"error": True, "message": f"미지원 시나리오: {scenario}"}
    codes = [c for c in codes if weights.get(c, 0) > 0]
    if len(codes) < 1:
        return {"error": True, "message": "보유 종목이 없습니다."}
    w = np.array([max(weights.get(c, 0.0), 0.0) for c in codes])
    w = w / w.sum() if w.sum() > 0 else np.full(len(codes), 1.0 / len(codes))

    sc = definition if definition is not None else SCENARIOS[scenario]
    exp, names, notes = _load_exposures(codes)
    coeffs = sc["factors"]
    sev = float(severity)

    # 종목별 충격 = 시장 기본 + Σ 팩터계수 × 노출.  팩터별 기여도 분해.
    market_shock = sc["market"] * sev
    factor_contrib_stock: dict[str, np.ndarray] = {}
    total = np.full(len(codes), market_shock)
    for fid, coef in coeffs.items():
        contrib = coef * sev * exp[fid]
        factor_contrib_stock[fid] = contrib
        total += contrib

    port_shock = float(w @ total)

    # 팩터별 포트폴리오 기여 (귀속)
    factor_attr = [{"factor": fid, "label": FACTORS[fid],
                    "contribution_pct": round(float(w @ factor_contrib_stock[fid]), 2)}
                   for fid in coeffs]
    factor_attr.append({"factor": "market", "label": "시장 기본충격",
                        "contribution_pct": round(market_shock, 2)})
    factor_attr.sort(key=lambda x: x["contribution_pct"])

    rows = [{"stock_code": codes[i], "corp_name": names[i],
             "weight_pct": round(float(w[i]) * 100, 2),
             "shock_pct": round(float(total[i]), 2),
             "contribution_pct": round(float(w[i] * total[i]), 2)}
            for i in range(len(codes))]
    rows.sort(key=lambda x: x["shock_pct"])

    # 취약 슬리브 (있으면)
    sleeve_attr = None
    if sleeves:
        agg: dict[str, float] = {}
        for i, c in enumerate(codes):
            s = sleeves.get(c, "미분류")
            agg[s] = agg.get(s, 0.0) + float(w[i] * total[i])
        sleeve_attr = sorted(({"sleeve": k, "contribution_pct": round(v, 2)} for k, v in agg.items()),
                             key=lambda x: x["contribution_pct"])

    # VaR/CVaR/MDD 프록시 — 충격을 변동성 상승과 결합한 파라메트릭 근사(정직 라벨)
    # ★없는 가정은 0 이다 — 지어내지 않는다★ 등록된 7+4종은 세 항목을 모두 갖지만 인라인
    # 정의는 일부만 줄 수 있다. 없는 항목에 기본 상승률을 넣으면 사용자가 요청하지 않은
    # 스트레스가 결과에 섞인다.
    a = {"corr_rise": 0.0, "vol_rise": 0.0, "liquidity_deteriorate": 0.0,
         **(sc.get("assumptions") or {})}
    base_vol = 0.20
    stressed_vol = base_vol * (1.0 + a["vol_rise"] * sev)
    z95 = 1.645
    var95 = round((abs(port_shock) / 100 + z95 * stressed_vol / math.sqrt(252)) * 100, 2)
    cvar95 = round(var95 * 1.25, 2)
    mdd_proxy = round(min(port_shock * 1.4, port_shock), 2)

    return {
        # 인라인 정의는 정성 메타가 없을 수 있다 — 없으면 빈 문자열이지 지어낸 문장이 아니다.
        "error": False, "scenario": scenario, "label": sc.get("label") or scenario,
        "description": sc.get("description") or "", "source": sc.get("source") or "",
        "severity": sev,
        "portfolio_shock_pct": round(port_shock, 2),
        "market_shock_pct": round(market_shock, 2),
        "factor_attribution": factor_attr,
        "rows": rows,
        "most_vulnerable": rows[:5],
        "sleeve_attribution": sleeve_attr,
        "assumptions": {
            "correlation_rise": a["corr_rise"], "volatility_rise": round(a["vol_rise"] * sev, 3),
            "liquidity_deterioration": a["liquidity_deteriorate"],
            "stressed_vol_pct": round(stressed_vol * 100, 1),
        },
        "risk_proxy": {"var95_pct": var95, "cvar95_pct": cvar95, "mdd_proxy_pct": mdd_proxy},
        "execution_feasibility": sc.get("execution") or "",
        "hedge_note": sc.get("hedge_note") or "",
        "notes": notes + ["팩터 노출 × 시나리오 계수의 선형 근사 — 실제 충격은 비선형일 수 있음(정직 한계).",
                          f"VaR/CVaR는 충격+변동성 상승 파라메트릭 프록시(배율 {sev:g}×)."],
    }


def catalog() -> list[dict]:
    return [{"id": k, "label": v["label"], "description": v["description"], "source": v["source"]}
            for k, v in SCENARIOS.items()]
