"""국면 축 단일 진실 공급원 — 변환(YoY)·z·모멘텀 블렌드·축 분해·사분면·확률.

지수형 시리즈(CPI/산업생산/GDP/고용/KOSPI)는 레벨이 항상 우상향이라 레벨 z-score가
구조적으로 +로 고정된다(과거 'Stagflation 고정' 버그의 원인). 여기서 YoY %로 변환 후
z-score한다. collector/차트는 원시값을 유지 — 변환은 이 모듈에서만 수행한다.

★ CIO 리팩토링 반영 ★
· 축 = (1-w)·z(레벨/YoY) + w·z(3개월 모멘텀) — 레벨이 높아도 급감속이면 축이 낮아짐.
  ("CPI 레벨 z +2.17σ vs 물가 축 -0.28 모순"의 해소: 축 입력은 YoY z이며, 지표별 분해를
  compute_axis_detail로 투명 공개 — UI가 레벨 z를 축 입력인 것처럼 보여주던 표시 불일치 제거)
· 사분면 명명 통일(전 모듈 공용): Goldilocks(성장↑물가↓) / Reflation(성장↑물가↑) /
  Stagflation(성장↓물가↑) / Disinflation(성장↓물가↓).
  'Deflation' 제거 — 물가 z<0은 '상승 둔화(디스인플레이션)'이지 물가 하락이 아님.
· quadrant_probs: 축 불확실성(se) 기반 사분면 확률(합=1) — 정적 신뢰도% 대체.

축 구성은 성장×물가 2×2 (Bridgewater 4국면 / 경기사이클 분석의 표준 관행):
  성장 = 실물 활동(산업생산·고용·GDP·경기선행) YoY의 역사 대비 z
  물가 = CPI YoY z + 기대인플레이션 레벨 z
regime_analyzer(헤더)와 macro_analytics(국면 궤적)가 이 정의를 공유해 서로 일치한다.
"""
from __future__ import annotations

import math

# (series_key, transform, sign, weight) — transform: "yoy"(지수→전년比%) | "level"
US_GROWTH = [("INDPRO", "yoy", 1, 0.35), ("PAYEMS", "yoy", 1, 0.25),
             ("UNRATE", "level", -1, 0.20), ("GDPC1", "yoy", 1, 0.20)]
US_INFLATION = [("CPIAUCSL", "yoy", 1, 0.60), ("T10YIE", "level", 1, 0.40)]
KR_GROWTH = [("KR_LEADING_CYCLE", "level", 1, 0.40), ("KR_IP", "yoy", 1, 0.30),
             ("KOSPI", "yoy", 1, 0.30)]
KR_INFLATION = [("KR_CPI", "yoy", 1, 0.70), ("T10YIE", "level", 1, 0.30)]

AXES = {"kr": (KR_GROWTH, KR_INFLATION), "us": (US_GROWTH, US_INFLATION)}

# 레벨 vs 모멘텀 블렌드 — 표준 관행: 레벨이 주, 3개월 변화(방향)가 보조
MOMENTUM_WEIGHT = 0.25
MOMENTUM_LAG = 3            # 개월
SE_FLOOR = 0.25             # 축 불확실성 하한 (지표 1~2개일 때 과신 방지)

QUADRANTS = ("Goldilocks", "Reflation", "Stagflation", "Disinflation")


# ── 개정 상태 — ★"빈티지가 있다" 와 "빈티지를 쓴다" 는 다르다★ ────────────────
# 예전에는 `allocation_routes._pit_block()` 이 전역 상수 `_REVISION_BIAS =
# "unmanaged"` 를 박았다. 값 자체는 맞았지만 **어느 계열 때문에 그런지**를 말하지
# 못했고, 그래서 두 가지가 보이지 않았다:
#
#   · `kr` 축은 5계열 중 4개가 ECOS 라 **영구히** 막혀 있다(빈티지 엔드포인트가 없다).
#   · `us` 축은 6계열 전부 FRED 라 **소스는 빈티지를 준다** — 막고 있는 것은
#     수집 경로뿐이고, 그것은 **고칠 수 있는 것**이다.
#
# 전역 상수는 그 차이를 지웠다. 하나는 데이터 제공자의 한계이고 다른 하나는
# 우리 코드의 선택인데, 같은 라벨을 달고 있었다.
#
# ★그리고 레지스트리만 보고 판정하면 반대로 과대주장한다★ `has_vintage=True` 는
# **API 가 줄 수 있다**는 뜻이지 **우리가 가져온다**는 뜻이 아니다.
# `pit_macro` 자신이 같은 계열의 오류를 이미 한 번 겪었다 — 빈 `realtime_start` 를
# `as_of` 로 채워 `has_vintage` 를 참으로 만들었던 버그.
#
# ★2026-08-28 갱신 (Track B4, 별도 승인)★ 이제 `collect_all()` 이 관측 스토어를
# as-of 로 조회한다(`macro_collector._from_vintage_store`). 그래서 ⑵ 는 참이다.
# ★그래도 여기 논리곱은 그대로다★ — 막는 것이 ⑵ 에서 ⑶(그 계열에 **실제** 빈티지
# 행이 있는가)으로 옮겨졌을 뿐이고, ⑶ 은 선언이 아니라 관측이다.

#: 국면 축이 읽는 경로가 실제로 빈티지를 가져오는가.
#: ★선언이지 추론이 아니다★ — `tests/test_axis_revision_status.py` 가 이 선언과
#: 실제 코드(수집기가 `pit_macro` 를 부르는가)를 대조한다. 빈티지를 배선하면 그
#: 테스트가 red 가 되어 이 상수를 함께 고치도록 강제한다.
def _collector_reads_vintage() -> bool:
    """⑵ 수집 경로가 빈티지를 가져오는가. ★사실이 있는 곳에서 읽는다★

    예전에는 이 모듈에 `AXIS_PATH_USES_VINTAGE` 라는 손 선언이 있었다. 사실은
    수집기 쪽에 있으므로 거기 하나만 둔다 — 두 곳에 두면 갈라지고, 갈라진 선언은
    틀린 선언이다.
    """
    try:
        from src.services.macro_collector import COLLECTOR_READS_VINTAGE
        return bool(COLLECTOR_READS_VINTAGE)
    except Exception:
        return False


def _series_has_vintage(key: str) -> bool:
    """⑶ 그 계열에 **실제로** 빈티지가 있는가 — ★선언이 아니라 관측★

    `macro_observation_store` 에 물어본다. 없으면(스토어 미생성·조회 실패) 거짓 —
    ★모르면 막는 쪽이 안전하다★. 여기서 관대해지면 없는 빈티지를 있다고 말한다.
    """
    try:
        from src.data.macro_observation_store import coverage
        cov = coverage([key]) or {}
        row = (cov.get("by_series") or {}).get(key) or {}
        return int(row.get("with_vintage") or 0) > 0
    except Exception:
        return False


def _path_uses_vintage(key: str) -> bool:
    """★두 사실이 모두 참일 때만 참★

    ⑵만 보면 데이터 없이 "PIT 통과" 가 되고, ⑶만 보면 **현재 개정본으로 과거를
    채점하면서** "PIT 통과" 가 된다. 후자가 정확히 `ac938c4` 가 막은 상태다 —
    스토어에 빈티지가 쌓여도 수집기가 안 읽으면 축은 현재값을 본다.
    """
    return _collector_reads_vintage() and _series_has_vintage(key)

#: 왜 막혔는가 — 하나는 제공자의 한계, 다른 하나는 우리 코드의 선택이다.
BLOCKED_BY_SOURCE = "source"      # 제공자가 빈티지를 주지 않는다 (영구)
BLOCKED_BY_PATH = "path"          # 제공자는 주는데 수집 경로가 안 쓴다 (고칠 수 있다)

REVISION_MANAGED = "managed"
REVISION_UNMANAGED = "unmanaged"


def axis_revision_status(market: str = "kr") -> dict:
    """국면 축을 이루는 **계열별** 개정 상태.

    ★두 사실이 모두 참일 때만 `managed` 다★
      1. `source_has_vintage` — 제공자가 개정 이력을 주는가 (`source_registry`)
      2. `AXIS_PATH_USES_VINTAGE` — 지금 코드가 그것을 **가져오는가**

    Returns:
        `{market, revision_bias, path_uses_vintage, series[],
          blocked_permanently[], blocked_by_path[], note}`
    """
    from src.data.source_registry import _BY_KEY

    g_def, i_def = AXES.get(market, AXES["kr"])
    rows: list[dict] = []
    for axis_name, group in (("growth", g_def), ("inflation", i_def)):
        for key, _transform, _sign, weight in group:
            spec = _BY_KEY.get(key)
            has_v = bool(spec.has_vintage) if spec is not None else False
            # ★미등록 계열은 '빈티지 없음' 으로 떨어뜨리되 그 사실을 남긴다★
            # 조용히 True 로 두면 등록을 빠뜨린 계열이 백테스트 적격이 된다.
            blocked = (BLOCKED_BY_SOURCE if not has_v
                       else None if _path_uses_vintage(key) else BLOCKED_BY_PATH)
            rows.append({
                "key": key, "axis": axis_name, "weight": weight,
                "provider": spec.provider if spec is not None else None,
                "registered": spec is not None,
                "source_has_vintage": has_v,
                "blocked_by": blocked,
            })

    perm = [r["key"] for r in rows if r["blocked_by"] == BLOCKED_BY_SOURCE]
    path = [r["key"] for r in rows if r["blocked_by"] == BLOCKED_BY_PATH]
    managed = not perm and not path
    if managed:
        note = "모든 축 계열이 빈티지 기반으로 조회된다."
    elif perm:
        note = (f"{len(perm)}개 계열({', '.join(sorted(set(perm)))})은 제공자가 개정 "
                f"이력을 주지 않아 **영구히** 개정 편향이 남습니다"
                + (f"; 나머지 {len(path)}개는 소스에 빈티지가 있으나 수집 경로가 "
                   f"현재값을 가져옵니다(고칠 수 있음)." if path else "."))
    else:
        note = (f"{len(path)}개 계열 전부 소스에 빈티지가 있습니다 — 막고 있는 것은 "
                f"수집 경로뿐이며 **고칠 수 있는 차단**입니다.")
    return {
        "market": market,
        "revision_bias": REVISION_MANAGED if managed else REVISION_UNMANAGED,
        # ★축 전체가 빈티지로 조회될 때만 참★ 하나라도 아니면 그 축은 PIT 가 아니다.
        "path_uses_vintage": bool(rows) and all(
            _path_uses_vintage(r["key"]) for r in rows if r["source_has_vintage"]
        ) and _collector_reads_vintage(),
        "series": rows,
        "blocked_permanently": sorted(set(perm)),
        "blocked_by_path": sorted(set(path)),
        "note": note,
    }


def yoy_pct(values, lag: int = 12) -> list:
    """지수 레벨 시계열 → 전년동기比 % 시계열 (선두 lag개는 None)."""
    out = []
    for i, v in enumerate(values):
        prev = values[i - lag] if i >= lag else None
        ok = v is not None and prev is not None and prev > 0
        out.append((v / prev - 1) * 100 if ok else None)
    return out


def zscore_at(vals, back: int = 0, window: int = 60) -> float | None:
    """시계열의 -1-back 시점 값의 z (직전 window 표본 기준). 표본<8이면 None."""
    idx = len(vals) - 1 - back
    if idx < 0:
        return None
    x = vals[idx]
    if x is None:
        return None
    seg = [v for v in vals[max(0, idx - window + 1):idx + 1] if v is not None]
    if len(seg) < 8:
        return None
    mean = sum(seg) / len(seg)
    var = sum((v - mean) ** 2 for v in seg) / len(seg)
    std = math.sqrt(var)
    return (x - mean) / std if std > 1e-12 else 0.0


def _momentum_series(vals, lag: int = MOMENTUM_LAG) -> list:
    """변환 시계열의 lag개월 차분 — 모멘텀(가속/감속) 원천."""
    out = []
    for i, v in enumerate(vals):
        prev = vals[i - lag] if i >= lag else None
        out.append((v - prev) if (v is not None and prev is not None) else None)
    return out


def compute_axis_detail(series_map: dict, axis_def: list, back: int = 0,
                        momentum_weight: float = MOMENTUM_WEIGHT) -> dict:
    """축 스코어 + 지표별 분해 + 불확실성(se).

    지표 기여 = sign·weight·[(1-mw)·z(변환 레벨) + mw·z(3개월 모멘텀)] / Σweight.
    미가용/표본 부족 지표는 제외하고 가중 재정규화(허위값 금지).
    se = 지표 기여 스코어의 가중 표준편차/√n (지표 간 불일치가 클수록 불확실) — 하한 SE_FLOOR.
    """
    comps: list[dict] = []
    for key, transform, sign, weight in axis_def:
        s = series_map.get(key)
        vals = list(getattr(s, "values", None) or [])
        if not vals:
            continue
        series = yoy_pct(vals) if transform == "yoy" else vals
        z = zscore_at(series, back=back)
        if z is None:
            continue
        z_mom = zscore_at(_momentum_series(series), back=back)
        blend = (1 - momentum_weight) * z + momentum_weight * (z_mom if z_mom is not None else z)
        comps.append({"key": key, "transform": transform, "sign": sign, "weight": weight,
                      "z": round(z, 3), "z_mom": round(z_mom, 3) if z_mom is not None else None,
                      "blend": sign * blend})
    wsum = sum(c["weight"] for c in comps)
    if wsum <= 0:
        return {"score": 0.0, "se": SE_FLOOR, "components": []}
    score = sum(c["blend"] * c["weight"] for c in comps) / wsum
    for c in comps:
        c["contribution"] = round(c["blend"] * c["weight"] / wsum, 4)
        c["blend"] = round(c["blend"], 3)
    # 지표 간 분산 → 불확실성 (n=1이면 하한)
    if len(comps) >= 2:
        var = sum(c["weight"] * (c["blend"] - score) ** 2 for c in comps) / wsum
        se = math.sqrt(var) / math.sqrt(len(comps))
    else:
        se = SE_FLOOR
    return {"score": round(score, 4), "se": round(max(SE_FLOOR, se), 4), "components": comps}


def compute_axis(series_map: dict, axis_def: list, back: int = 0) -> float:
    """가중 z 평균 (하위호환 래퍼 — compute_axis_detail의 score)."""
    return compute_axis_detail(series_map, axis_def, back=back)["score"]


def quadrant(growth: float, inflation: float) -> str:
    """성장×물가 사분면 — 전 모듈 공용 명칭 (Deflation 아님 — Disinflation)."""
    if growth >= 0:
        return "Reflation" if inflation >= 0 else "Goldilocks"
    return "Stagflation" if inflation >= 0 else "Disinflation"


def _phi(x: float) -> float:
    """표준정규 CDF."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def quadrant_probs(growth: float, inflation: float,
                   se_g: float = SE_FLOOR, se_i: float = SE_FLOOR) -> dict:
    """축 불확실성 기반 사분면 확률 (독립 가우시안 가정, 합=1).

    P(성장>0)=Φ(g/se_g), P(물가>0)=Φ(i/se_i) → 4사분면 곱.
    정적 '신뢰도 80%' 텍스트를 확률 분포로 대체(CIO 확률적 비중 제시)."""
    pg = _phi(growth / max(1e-9, se_g))
    pi = _phi(inflation / max(1e-9, se_i))
    return {"Reflation": round(pg * pi, 4), "Goldilocks": round(pg * (1 - pi), 4),
            "Stagflation": round((1 - pg) * pi, 4), "Disinflation": round((1 - pg) * (1 - pi), 4)}
