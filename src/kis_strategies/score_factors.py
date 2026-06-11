# 대상 경로: src/kis_strategies/score_factors.py
#
# 뉴지랭크 점수 근사 — 젠포트 가이드 "뉴지랭크(점수)의 이해" 시트가 공개한 구성 그대로:
#
#   종합점수   = (모멘텀점수 + 펀더멘탈점수) / 2
#   모멘텀점수 = 가격점수 + 수급점수            (0~100 스케일 유지 위해 평균)
#   펀더멘탈점수 = 성장점수 + 가치점수          (동일)
#   가격점수   : 상승강도(4주 상승률) · 5/20/60일 이동평균선 상승률(단/중/장기 이격도)
#   수급점수   : 20MA 거래대금 상승률 · 20MA 거래량 상승률 · VRAC(상승일 거래량 비중)
#                · 외국인/기관 순매수·20일 누적 (수급 적재 시에만)
#   성장점수   : 매출/영업이익/순이익(EPS) 전년동기 성장률 · 금기영업이익성장률(히스토리)
#   가치점수   : ROE(높을수록) · PER/PBR(낮을수록, 0이하 제외 — 가이드 명시)
#
# 각 구성요소를 매매대상 풀에서 날짜별 백분위(0~100)로 환산해 평균 — 가이드가
# "점수 = 비율과 같은 역할(0~100)"이라 설명하는 방식의 재현.
#
# 정직한 한계(근사 표기): 뉴지 원본은 가중치·세부 알고리즘 비공개 → 동률 아님.
# 성장·가치 레그는 현재 스냅샷(분기 갱신 미반영, look-ahead 근사)이라
# allow_snapshot_fundamentals 토글 시에만 합성되고, 없으면 펀더멘탈·종합은 NaN
# (정의를 조용히 바꾸지 않음 — 모멘텀·가격·수급 점수는 순수 가격·거래량이라 항상 인과적).

from __future__ import annotations

import numpy as np
import pandas as pd

SCORE_TOKENS: frozenset[str] = frozenset({
    "종합점수", "모멘텀점수", "펀더멘탈점수",
    "가격점수", "수급점수", "성장점수", "가치점수",
})

# 점수 워밍업: 60MA 이격도 + 변화율 + 백분위 안정화
SCORE_MIN_BARS = 85


def _ma_slope(close: pd.Series, n: int) -> pd.Series:
    """n일 이동평균선의 상승률 — 가이드 목적란 정의("n일 이동평균선의 상승률이 높은 종목")."""
    return close.rolling(n).mean().pct_change(1) * 100.0


def _price_ingredients(df: pd.DataFrame) -> dict[str, pd.Series]:
    c = df["close"].astype(float)
    return {
        "상승강도": c.pct_change(20) * 100.0,   # 지난 4주(20거래일) 상승률
        "단기이격도": _ma_slope(c, 5),
        "중기이격도": _ma_slope(c, 20),
        "장기이격도": _ma_slope(c, 60),
    }


def _flow_ingredients(df: pd.DataFrame) -> dict[str, pd.Series]:
    c = df["close"].astype(float)
    v = df["volume"].astype(float)
    tval = c * v
    up_v = v.where(c.diff() > 0, 0.0)
    out = {
        "거래대금상승률": (tval / tval.rolling(20).mean() - 1.0) * 100.0,
        "거래량비율": (v / v.rolling(20).mean() - 1.0) * 100.0,
        "VRAC": up_v.rolling(20).sum() / v.rolling(20).sum() * 100.0,
    }
    # 투자자별 수급 — 적재된 경우에만 (mock·미적재면 빠짐: 가용 요소 평균)
    try:
        from src.kis_strategies.factor_tokens import resolve_flow_token
        for label, token in (("외국인순매수", "외국인순매수량"), ("기관순매수", "기관순매수량")):
            s = resolve_flow_token(df, token)
            if s is not None and s.notna().any():
                out[label] = s.astype(float)
                out[label + "누적"] = s.astype(float).rolling(20).sum()
    except Exception:
        pass
    return out


# (구성요소 키, fund dict에서 찾을 후보 키들) — 첫 번째로 존재하는 값 사용
_GROWTH_KEYS = [
    ("매출성장률", ("revenue_growth_yoy",)),
    ("영업이익성장률", ("op_growth_yoy",)),
    ("단기이익성장률", ("eps_growth_yoy",)),
    ("금기영업이익성장률", ("영업이익성장률(금기)",)),
]


def _fund_value(fund: dict, keys: tuple[str, ...]) -> float | None:
    for k in keys:
        v = fund.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _pct_panel(cols: dict[str, pd.Series], higher_better: bool = True) -> pd.DataFrame | None:
    """{ticker: series(YYYY-MM-DD 인덱스)} → 날짜별 횡단면 백분위(0~100)."""
    cols = {k: s for k, s in cols.items() if s is not None}
    if not cols:
        return None
    wide = pd.DataFrame(cols)
    return wide.rank(axis=1, pct=True, ascending=higher_better) * 100.0


def _mean_frames(frames: list[pd.DataFrame | None]) -> pd.DataFrame | None:
    """프레임들의 셀별 평균 — NaN은 그 셀에서 제외(가용 구성요소 평균)."""
    frames = [f for f in frames if f is not None]
    if not frames:
        return None
    total, cnt = None, None
    for f in frames:
        m = f.notna().astype(float)
        fv = f.fillna(0.0)
        total = fv if total is None else total.add(fv, fill_value=0.0)
        cnt = m if cnt is None else cnt.add(m, fill_value=0.0)
    return total / cnt.replace(0.0, np.nan)


def _date_index(s: pd.Series, df: pd.DataFrame) -> pd.Series:
    idx = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in df.index]
    return pd.Series(s.values, index=idx)


def build_score_panels(ohlcv_map: dict, fundamentals_map: dict | None = None) -> dict[str, pd.DataFrame]:
    """점수 7종 패널 {점수명: DataFrame[YYYY-MM-DD × ticker]} — 봉 루프 전에 1회.

    fundamentals_map({ticker: fund dict})이 없으면 성장·가치(→펀더멘탈·종합)는 NaN."""
    price_cols: dict[str, dict] = {}
    flow_cols: dict[str, dict] = {}
    growth_cols: dict[str, dict] = {k: {} for k, _ in _GROWTH_KEYS}
    value_cols: dict[str, dict] = {"ROE": {}, "PER": {}, "PBR": {}}

    for tk, df in ohlcv_map.items():
        tk = str(tk)
        try:
            for name, s in _price_ingredients(df).items():
                price_cols.setdefault(name, {})[tk] = _date_index(s, df)
            for name, s in _flow_ingredients(df).items():
                flow_cols.setdefault(name, {})[tk] = _date_index(s, df)
        except Exception:
            continue
        fund = (fundamentals_map or {}).get(tk)
        if fund:
            n = len(df)
            for name, keys in _GROWTH_KEYS:
                v = _fund_value(fund, keys)
                if v is not None:
                    growth_cols[name][tk] = _date_index(pd.Series([v] * n, index=df.index), df)
            for name, key, positive_only in (("ROE", "roe", False),
                                             ("PER", "per", True), ("PBR", "pbr", True)):
                v = _fund_value(fund, (key,))
                if v is not None and (not positive_only or v > 0):  # 가이드: PER/PBR 0이하 제외
                    value_cols[name][tk] = _date_index(pd.Series([v] * n, index=df.index), df)

    price = _mean_frames([_pct_panel(c) for c in price_cols.values()])
    flow = _mean_frames([_pct_panel(c) for c in flow_cols.values()])
    growth = _mean_frames([_pct_panel(c) for c in growth_cols.values()])
    # 가치: ROE 높을수록 / PER·PBR 낮을수록 좋음 (방향 반전)
    value = _mean_frames([_pct_panel(value_cols["ROE"], higher_better=True),
                          _pct_panel(value_cols["PER"], higher_better=False),
                          _pct_panel(value_cols["PBR"], higher_better=False)])

    def _avg2(a: pd.DataFrame | None, b: pd.DataFrame | None) -> pd.DataFrame | None:
        # 정의 (a+b)/2 — 한쪽이 없으면 NaN (정의를 조용히 바꾸지 않음)
        if a is None or b is None:
            return None
        return (a + b) / 2.0

    momentum = _avg2(price, flow)
    fundamental = _avg2(growth, value)
    total = _avg2(momentum, fundamental)

    panels = {"가격점수": price, "수급점수": flow, "성장점수": growth, "가치점수": value,
              "모멘텀점수": momentum, "펀더멘탈점수": fundamental, "종합점수": total}
    return {k: v for k, v in panels.items() if v is not None}
