"""AAS 그래프 — '매매 몫 결합'(K4): 정책 백테스트(핵심) + 분봉 결과 조회(위성) + 시장 국면 + 국면별 매매 몫 → 합친 곡선 두 판
==============================================================================
설계 `docs/superpowers/specs/2026-11-17-emeans-gmm-combination-design.md` §5 · 구현 계획 `2026-11-16-emeans-gmm-strategy.md` §7.5.

- **입력.** 핵심 = '정책 백테스트'의 비용 후 곡선(`BacktestResult` · 다시 계산하지 않는다) · 위성 = '분봉 결과 조회'가 가리키는 시행의
  비용 후 일별 손익(실행자 본인의 시행 기록을 ★읽기만★ — 국면별 성과 나눔(K2a)과 같은 길 · 남의 것 = 없는 것 · 못 읽음 ≠ 없음).
  국면은 시장 국면 문 · 국면 나눔 · 국면 조건과 ★같은 함수★(`regime_answer`)로 계산한다.
- **몫.** 겹친 구간의 첫날과 달마다 첫 거래일에 Σ 그날 국면 확률(그날 시가 전에 아는 값) × 국면별 매매 몫 · 그 사이에는 표류 ·
  옮긴 몫 × 정책 백테스트의 비용 가정. 계산은 순수 함수 `src.engine.core_satellite`. 몫 고정 판은 같은 날 · 같은 비용에 목표만
  날 가중 평균 몫으로 고정한 판이다 — 두 판을 나란히 낸다(이긴 쪽 · 순위가 없다).
- **지어내지 않는다.** 칸은 비어서 시작하고 빈 칸은 실패한다 · 비용 후 손익이 없는 시행 · 겹친 구간의 날 어긋남 · 몫을 정하는 날의 확률을
  모르는 경우는 사유와 함께 실패한다(0 이나 앞 달 몫으로 채우지 않는다) · 운영에서는 합성 분봉의 시행을 합치지 않는다.
- **끝 노드.** 출력이 없다(합친 곡선이 비교 · 순위 · 비중 · 주문으로 가는 길이 구조에 없다) · 단추가 없다(계산은 쓰기 0 · 시행이 아니다) ·
  도구는 표와 자본을 고르지 않는다(AI 후보가 아니다 — `NOT_OFFERED`). 주문 경로 · 가동기 · 증권사 클라이언트를 들이지 않는다(정적 시험).
"""
from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api import graph_actor
from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _practice, _t
from src.api.intraday_context import NO_INDEX_DAY
from src.api.intraday_market_regime_routes import INDEXES, regime_answer
from src.data import intraday_trials as trials
from src.data.mock_gate import mock_allowed
from src.domain.perf_kind import backtest_label
from src.engine import core_satellite as cs
from src.engine import market_regime as mr
from src.engine import portfolio_graph as pg
from src.engine.perf_compare import align_curves
from src.engine.quant_metrics import drawdown_episodes

P = pg.Port

KIND = "core_satellite_mix"
#: AI 추천 · 말로 설계가 후보로 삼지 않는 종류 — 도구는 국면별 몫과 자본을 고르지 않는다(`canvas_assist_routes.offered_kinds`).
NOT_OFFERED = (KIND,)
WHO = "매매 몫 결합은 로그인한 사용자만 사용합니다"
LABELS = {"regime": "국면 몫", "fixed": "몫 고정"}
GRADE_SYNTHETIC, GRADE_REAL = "E0", "E3"
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_MAX_STATES = mr.K_RANGE[1]

REASONS = {
    "no_index": "지수를 고르십시오. 국면을 계산할 지수가 필요합니다.",
    "no_k": "국면 수를 고르십시오(2 ~ 4).",
    "no_shares": "국면별 매매 몫을 모두 채우십시오. 비어 있는 칸: {states}.",
    "no_capital": "매매 몫 자본을 입력하십시오. 분봉 손익을 수익률로 바꾸는 분모입니다.",
    "core_unreadable": "정책 백테스트의 곡선을 읽을 수 없어 합치지 않았습니다.",
    "cost_unknown": "정책 백테스트의 비용 가정을 읽을 수 없어 합치지 않았습니다. 옮긴 몫의 비용을 정할 수 없습니다.",
    "store_unreadable": "시행 기록을 읽지 못했습니다. 시행이 없다는 뜻이 아닙니다.",
    "not_found": "이 분봉 백테스트 결과를 찾지 못했습니다. 본인이 실행한 결과만 합칠 수 있습니다.",
    "synthetic_in_production": "모의 모드에서 합성 분봉으로 만든 결과입니다. 운영에서는 합치지 않습니다.",
    "no_flow": "이 분봉 백테스트의 기록에 일별 손익이 없어 합치지 않았습니다.",
    "gross_only": ("이 분봉 백테스트는 비용 후 손익을 모릅니다(수수료율을 정하지 않았거나 매도세를 산출하지 못했습니다). "
                   "비용 전 손익으로 합치면 위성이 유리하게 보여 합치지 않았습니다."),
    "bad_flow": "이 분봉 백테스트의 일별 기록을 읽을 수 없어 합치지 않았습니다.",
    "bad_setting": "이 분봉 백테스트의 설정(진입 금액 · 동시 보유 상한 · 수수료율 · 종목)을 읽을 수 없어 자본 하한을 정하지 못했습니다.",
    "capital_short": ("매매 몫 자본이 모자랍니다. 자본 {capital}원 · 필요 {needed}원(진입 금액 × 동시에 보유할 수 있는 종목 수 {positions} × "
                      "(1 + 수수료율)). 그 자본으로 살 수 없는 진입이 있어 합치지 않았습니다."),
    "no_overlap": "정책 백테스트와 분봉 백테스트의 기간이 겹치지 않습니다.",
    "days_mismatch": ("겹친 기간 안에서 거래일이 맞지 않습니다(정책 백테스트에만 있는 날 {core_only}일 · 분봉 백테스트에만 있는 날 {trial_only}일). "
                      "없는 날의 손익을 0 으로 채우지 않아 합치지 않았습니다."),
    "regime_store": "지수 일봉 저장소를 읽지 못해 시장 국면을 계산하지 않았습니다. 적재가 없다는 뜻이 아닙니다.",
    "regime_unavailable": "시장 국면을 계산하지 못해 합치지 않았습니다.",
    "regime_unknown": "몫을 정하는 날의 시장 국면 확률을 몰라 합치지 않았습니다. 몫을 지어내거나 앞 달 몫으로 미루지 않습니다.",
    "regime_shape": "국면 계산이 국면 수와 맞지 않는 확률을 내어 합치지 않았습니다. 국면 계산의 문제입니다.",
}
#: 엔진의 거절 코드 → 사유(원인과 같은 사유). 노드가 먼저 거르는 것(길이 · 표 · 확률 빠짐)은 여기까지 오지 않는다.
ENGINE_REFUSALS = {
    "return_at_or_below_minus_one": "하루 손실이 그 몫의 자본 전체 이상인 날이 있어 합치지 않았습니다.",
    "not_finite": "읽을 수 없는 값(NaN 포함)이 있어 합치지 않았습니다.",
    "probs_not_one": "국면 확률의 합이 1 이 아니어서 합치지 않았습니다. 국면 계산의 문제입니다.",
    "probs_shape": REASONS["regime_shape"],
    "_other": "합치는 계산의 입력이 맞지 않아 합치지 않았습니다.",
}
#: 답에 늘 싣는 한계 문장 — 화면은 서버 글자 그대로 보인다.
NOTES = (
    "두 판은 같은 날 · 같은 재조정 날 · 같은 비용으로 계산했고 다른 것은 목표 몫뿐입니다. 어느 판이 낫다는 뜻이 아닙니다.",
    "몫은 첫날과 달마다 첫 거래일에 그날 시가 전에 알던 국면 확률로 정하고, 그 사이에는 되돌리지 않습니다.",
    "위성 수익률은 그날 분봉 손익(비용 후) ÷ 매매 몫 자본입니다. 몫이 바뀌면 진입 금액도 같은 비율로 바뀐다고 봅니다.",
    "놀리는 자본의 이자 · 세금은 넣지 않았습니다. 옮긴 몫에는 정책 백테스트의 비용 가정을 적용했습니다.",
    "비율 표를 바꿔 가며 다시 보면 그만큼 고르는 것이 됩니다. 이 노드는 다시 본 횟수를 세지 않습니다.",
)
_SHARE_HELP = "그 국면일 때 전체 자본 가운데 분봉 매매(위성)에 두는 몫입니다. 도구는 몫을 정하지 않습니다."
#: 등록부 모듈(`allocation_graph_nodes`)의 `_FORBID` · `_ui` 와 같은 꼴 — 그 모듈이 끝에서 이 모듈을 등록하므로 들이면 순환 import 가 된다
#: (이 모듈을 먼저 들이는 쪽에서 깨진다). 같은 꼴인지는 시험이 건다.
_FORBID = ConfigDict(extra="forbid")


def _ui(label: str, tier: str = "basic", **kw: Any) -> dict:
    return {"label": label, "tier": tier, **kw}


# ── 매개변수 — ★전부 비어서 시작한다★ ─────────────────────────────────────────────────────────
def _share(n: int) -> Any:
    shown = {} if n <= 2 else {"show_if": {"k": list(range(n, _MAX_STATES + 1))}}
    return Field(None, ge=0, le=100, json_schema_extra={"x-ui": _ui(
        f"국면 {n} 일 때 매매 몫", question=f"국면 {n} 일 때 위성의 몫", widget="input", unit="%", help=_SHARE_HELP, **shown)})


class MixParams(BaseModel):
    model_config = _FORBID
    index: Literal["KOSPI", "KOSDAQ"] | None = Field(None, json_schema_extra={"x-ui": _ui(
        "지수", question="국면을 계산할 지수", widget="cards", options=dict(INDEXES), order=list(INDEXES),
        help="몫을 정하는 날의 시장 국면 확률을 이 지수로 계산합니다(시장 국면 절과 같은 계산).")})
    k: int | None = Field(None, ge=mr.K_RANGE[0], le=mr.K_RANGE[1], json_schema_extra={"x-ui": _ui(
        "국면 수", question="시장 국면의 수", widget="input", unit="개",
        help="2 ~ 4. 도구는 국면 수를 고르지 않습니다. 번호는 변동성이 낮은 국면부터입니다.")})
    share_1: float | None = _share(1)
    share_2: float | None = _share(2)
    share_3: float | None = _share(3)
    share_4: float | None = _share(4)
    capital: float | None = Field(None, gt=0, le=1e13, json_schema_extra={"x-ui": _ui(
        "매매 몫 자본", question="분봉 매매에 두는 자본", widget="input", unit="원",
        help="분봉 손익을 수익률로 바꾸는 분모입니다. 진입 금액 × 동시에 보유할 수 있는 종목 수 × (1 + 수수료율) 이상이어야 합니다.")})


def _fields(p: MixParams) -> tuple[str, int, list[float], float]:
    """칸 → 값. 빈 칸은 그 이름과 함께 실패한다 — ★시행 기록을 읽기 전에★ 본다. 국면 수보다 큰 번호의 칸은 쓰지 않는다."""
    if p.index is None:
        raise pg.NodeFailure(REASONS["no_index"])
    if p.k is None:
        raise pg.NodeFailure(REASONS["no_k"])
    shares = [p.share_1, p.share_2, p.share_3, p.share_4][: p.k]
    blank = [f"국면 {i}" for i, s in enumerate(shares, start=1) if s is None]
    if blank:
        raise pg.NodeFailure(REASONS["no_shares"].format(states=", ".join(blank)))
    if p.capital is None:
        raise pg.NodeFailure(REASONS["no_capital"])
    return p.index, int(p.k), [float(s) / 100.0 for s in shares if s is not None], float(p.capital)


# ── 입력 읽기 ─────────────────────────────────────────────────────────────────────────────
def _number(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _core_mock(value: dict) -> bool | None:
    """정책 백테스트의 성과 라벨(`perf_kind.backtest_label` 의 `data_real`) — 모의 시세 위의 곡선인가.
    라벨이 없거나 데이터 축이 미상이면 미상(실제라고 하지 않는다)."""
    label = value.get("perf_label")
    real = label.get("data_real") if isinstance(label, dict) else None
    return (not real) if isinstance(real, bool) else None


def _data_mock(synthetic: bool, mock: bool, trial_grade: Any, regime_grade: Any, core_mock: bool | None) -> bool | None:
    """성과 라벨(`perf_kind.backtest_label`)의 데이터 축 — 하나라도 합성이거나 모의 모드면 합성(True) · 시행 · 국면 · 핵심이
    모두 실제로 적혀 있으면 실제(False) · 그 밖(핵심의 라벨 없음 · 등급 미상)은 미상(None — 실제라고 하지 않는다)."""
    if synthetic or mock:
        return True
    return False if (trial_grade == GRADE_REAL and regime_grade == GRADE_REAL and core_mock is False) else None


def _core(value: Any) -> dict[str, Any]:
    """정책 백테스트의 답 → 날짜 · 그날의 비용 후 수익(곡선의 이웃 비 · 첫날은 시작 자본 1 대비) · 비용 가정(bp) · 모의 시세 여부."""
    if not isinstance(value, dict) or value.get("error"):
        raise pg.NodeFailure(REASONS["core_unreadable"])
    dates, curve = value.get("dates"), value.get("equity_curve")
    if not isinstance(dates, list) or not isinstance(curve, list) or not dates or len(dates) != len(curve):
        raise pg.NodeFailure(REASONS["core_unreadable"])
    ds = [str(d)[:10] for d in dates]
    eq = [_number(x) for x in curve]
    if (any(e is None or e <= 0 for e in eq) or not all(_DATE.fullmatch(d) for d in ds)
            or len(set(ds)) != len(ds) or ds != sorted(ds)):
        raise pg.NodeFailure(REASONS["core_unreadable"])
    cost = _number((value.get("config") or {}).get("cost_bps"))
    if cost is None or cost < 0:
        raise pg.NodeFailure(REASONS["cost_unknown"])
    values = [float(e) for e in eq if e is not None]
    prev = [1.0] + values[:-1]
    return {"dates": ds, "returns": {d: e / q - 1.0 for d, e, q in zip(ds, values, prev, strict=True)}, "cost_bps": cost,
            "mock": _core_mock(value)}


def _flow(daily: Any) -> tuple[list[str], dict[str, float]]:
    """시행의 일별 흐름 → 날짜 · 그날의 비용 후 손익(원). 비용 전 흐름은 쓰지 않는다."""
    if not isinstance(daily, dict) or daily.get("values") is None or not daily.get("dates"):
        raise pg.NodeFailure(REASONS["no_flow"])
    if daily.get("basis") != "net":
        raise pg.NodeFailure(REASONS["gross_only"])
    try:
        ds = [str(d) for d in daily["dates"]]
        vs = [_number(v) for v in daily["values"]]
    except TypeError:
        raise pg.NodeFailure(REASONS["bad_flow"]) from None
    if (len(ds) != len(vs) or any(v is None for v in vs) or len(set(ds)) != len(ds)
            or not all(_DATE.fullmatch(d) for d in ds)):
        raise pg.NodeFailure(REASONS["bad_flow"])
    return sorted(ds), {d: float(v) for d, v in zip(ds, vs, strict=True) if v is not None}


def _floor(got: dict) -> tuple[float, int]:
    """자본 하한 = 진입 금액 × min(동시 보유 상한, 종목 수) × (1 + 수수료율) — 한 시각에 묶일 수 있는 돈의 최대(시뮬레이터: 종목 하나에 포지션 하나)."""
    setting = got.get("setting") if isinstance(got.get("setting"), dict) else {}
    position = setting.get("position") if isinstance(setting.get("position"), dict) else {}
    costs = setting.get("costs") if isinstance(setting.get("costs"), dict) else {}
    amount, fee = _number(position.get("amount")), _number(costs.get("commission_bp"))
    limit, tickers = position.get("max_open_positions"), got.get("tickers")
    if (amount is None or amount <= 0 or fee is None or fee < 0 or not isinstance(tickers, list) or not tickers
            or (limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1))):
        raise pg.NodeFailure(REASONS["bad_setting"])
    positions = len(tickers) if limit is None else min(int(limit), len(tickers))
    return round(amount * positions * (1.0 + fee / 1e4), 2), positions


def _window(core_dates: list[str], trial_dates: list[str]) -> list[str]:
    """겹친 구간의 거래일 — 그 안에서 날이 하나라도 어긋나면 쪽마다 날 수를 적고 실패한다(없는 날을 0 으로 채우지 않는다)."""
    lo, hi = max(core_dates[0], trial_dates[0]), min(core_dates[-1], trial_dates[-1])
    if lo > hi:
        raise pg.NodeFailure(REASONS["no_overlap"])
    c = [d for d in core_dates if lo <= d <= hi]
    t = [d for d in trial_dates if lo <= d <= hi]
    if c != t:
        raise pg.NodeFailure(REASONS["days_mismatch"].format(core_only=len(set(c) - set(t)), trial_only=len(set(t) - set(c))))
    return c


def _regime(index: str, k: int, days: list[str]) -> dict[str, Any]:
    """몫을 정하는 날의 국면 확률 — 시장 국면 문과 같은 함수 · 같은 거절(저장소 장애 ≠ 적재 없음)."""
    try:
        answer = regime_answer(index, k, date.fromisoformat(days[0]), date.fromisoformat(days[-1]))
    except HTTPException as err:                                  # 기간 규칙 — 분봉 시행의 상한과 같아 닿지 않지만 닿으면 그 문장
        why = err.detail.get("reason") if isinstance(err.detail, dict) else str(err.detail)
        raise pg.NodeFailure(f"{REASONS['regime_unavailable']} {why}".strip()) from None
    empty = answer.get("empty")
    if empty:
        if empty.get("reason") == "store_error":
            raise pg.NodeFailure(REASONS["regime_store"])
        raise pg.NodeFailure(f"{REASONS['regime_unavailable']} {empty.get('message') or ''}".strip())
    rows = {str(row.get("date")): row for row in answer.get("days") or []}
    probs_at: dict[int, tuple[float, ...]] = {}
    missing: list[str] = []
    for i in cs.month_starts(days):
        row = rows.get(days[i])
        probs = None if row is None else row.get("probs")
        if probs is None:
            missing.append(f"{days[i]}: {(row or {}).get('reason') or NO_INDEX_DAY}")
            continue
        if len(probs) != k:
            raise pg.NodeFailure(REASONS["regime_shape"])
        probs_at[i] = tuple(float(x) for x in probs)
    if missing:
        raise pg.NodeFailure(f"{REASONS['regime_unknown']} {' · '.join(missing)}")
    return {"probs_at": probs_at, "grade": answer.get("grade"), "grade_reason": answer.get("grade_reason")}


# ── 계산 ─────────────────────────────────────────────────────────────────────────────────
def _pct(x: float, digits: int = 4) -> float:
    return round(x * 100.0, digits)


def _panel(key: str, run: dict, avg_target: float) -> dict[str, Any]:
    return {"key": key, "label": LABELS[key], "total_return_pct": _pct(run["total_return"]),
            "max_drawdown_pct": _pct(run["max_drawdown"]), "avg_share_pct": _pct(run["avg_share"]),
            "avg_target_pct": _pct(avg_target), "cost_pct": round(run["cost_total"] * 100.0, 6), "rebalances": len(run["moves"])}


def _mix(inputs: dict, p: MixParams, actor: Any) -> pg.NodeOutput:
    user = graph_actor.require(actor, WHO)
    index, k, table, capital = _fields(p)
    core = _core(inputs.get("core"))
    key = str((inputs.get("run") or {}).get("trial_key") or "")
    got = trials.daily_of(user, key)                              # 읽기만 — 실행 횟수가 늘지 않는다
    if got is None:
        raise pg.NodeFailure(REASONS["store_unreadable"])
    if not got.get("found"):                                      # 남의 것과 없는 것은 같은 문장이다
        raise pg.NodeFailure(REASONS["not_found"])
    mock = mock_allowed()
    trial_grade = got.get("grade")
    if trial_grade == GRADE_SYNTHETIC and not mock:               # 운영에서는 합성 위의 숫자를 합치지 않는다
        raise pg.NodeFailure(REASONS["synthetic_in_production"])
    trial_dates, pnl = _flow(got.get("daily"))
    needed, positions = _floor(got)
    if capital < needed:
        raise pg.NodeFailure(REASONS["capital_short"].format(capital=f"{capital:,.0f}", needed=f"{needed:,.0f}", positions=positions))
    days = _window(core["dates"], trial_dates)
    regime = _regime(index, k, days)
    try:
        out = cs.mix(days, [core["returns"][d] for d in days], [pnl[d] / capital for d in days], regime["probs_at"], table,
                     core["cost_bps"] / 1e4)
    except ValueError as err:
        raise pg.NodeFailure(ENGINE_REFUSALS.get(str(err), ENGINE_REFUSALS["_other"])) from None

    synthetic = GRADE_SYNTHETIC in (trial_grade, regime["grade"]) or core["mock"] is True     # 핵심이 모의 시세여도 합성이다
    practice = mock or synthetic
    # 성과 숫자는 무슨 성과인지 말한다(Z4) — 두 판은 과거 위의 시뮬레이션(backtest)이다. 보기와 출처에 같은 값.
    perf_label = backtest_label(is_mock_data=_data_mock(synthetic, mock, trial_grade, regime["grade"], core["mock"])).to_dict()
    eq_regime = [round(e, 8) for e in out["regime"]["equity"]]
    eq_fixed = [round(e, 8) for e in out["fixed"]["equity"]]
    view = {
        "trial_key": key,
        "request": {"index": index, "name": INDEXES[index], "k": k, "table_pct": [_pct(t) for t in table], "capital": capital,
                    "cost_bps": core["cost_bps"]},
        "window": {"from": days[0], "to": days[-1], "days": len(days), "core_days": len(core["dates"]), "trial_days": len(trial_dates)},
        "needed_capital": needed, "positions": positions,
        "months": [{"date": m["date"], "probs_pct": [_pct(x) for x in m["probs"]], "target_pct": _pct(m["target"]),
                    "moved_pct": _pct(m["moved"]), "cost_pct": round(m["cost"] * 100.0, 6)} for m in out["months"]],
        "panels": [_panel("regime", out["regime"], out["fixed_share"]), _panel("fixed", out["fixed"], out["fixed_share"])],
        "fixed_share_pct": _pct(out["fixed_share"]),
        "compare": {"curves": align_curves(days, eq_regime, days, eq_fixed, base=1.0), "labels": {"a": LABELS["regime"], "b": LABELS["fixed"]},
                    "drawdowns": {"a": drawdown_episodes(days, eq_regime, top=3), "b": drawdown_episodes(days, eq_fixed, top=3)},
                    "practice": practice},
        "grades": {"trial": trial_grade if trial_grade in (GRADE_SYNTHETIC, GRADE_REAL) else None,
                   "regime": regime["grade"] if regime["grade"] in (GRADE_SYNTHETIC, GRADE_REAL) else None,
                   "core_mock": core["mock"]},
        "regime_grade_reason": regime["grade_reason"],
        "synthetic": synthetic, "mock": mock, "perf_label": perf_label,
        "notes": list(NOTES),
    }
    return pg.NodeOutput(values={}, view=view, provenance={"perf_label": perf_label},
                         tags={"pit": "unknown", "practice": practice, "sources": [f"intraday_trial:{key[:12]}"]})


# ── 해설 ─────────────────────────────────────────────────────────────────────────────────
def _signed(v: float) -> str:
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v):.2f}%"


def _explain(view: dict, prov: dict, params: Any) -> dict:
    w, req = view.get("window") or {}, view.get("request") or {}
    regime, fixed = (view.get("panels") or [{}, {}])[:2]
    facts = [
        f"기간 {w.get('from')} ~ {w.get('to')} · {w.get('days')}거래일 · 몫을 정한 날 {len(view.get('months') or [])}번",
        f"국면 몫 판: 기간 수익률 {_signed(regime.get('total_return_pct', 0.0))} · 최대 낙폭 {_signed(regime.get('max_drawdown_pct', 0.0))} · "
        f"평균 몫 {regime.get('avg_share_pct', 0.0):.2f}%",
        f"몫 고정 판(목표 몫 {view.get('fixed_share_pct', 0.0):.2f}% · 국면 몫 판의 날 가중 평균): 기간 수익률 "
        f"{_signed(fixed.get('total_return_pct', 0.0))} · 최대 낙폭 {_signed(fixed.get('max_drawdown_pct', 0.0))}",
        f"옮긴 몫의 비용: 국면 몫 판 {regime.get('cost_pct', 0.0):.4f}% · 몫 고정 판 {fixed.get('cost_pct', 0.0):.4f}%"
        f"(정책 백테스트의 비용 가정 {req.get('cost_bps', 0.0):g}bp)",
        "참고: 정책 백테스트 요약의 샤프 · 변동성은 비용 전 값입니다. 이 노드는 요약을 쓰지 않고 비용 후 곡선만 씁니다.",
    ]
    if w.get("trial_days") != w.get("days") or w.get("core_days") != w.get("days"):
        facts.append(f"겹친 {w.get('days')}거래일만 합쳤습니다(정책 백테스트 {w.get('core_days')}일 · 분봉 백테스트 {w.get('trial_days')}일).")
    trust = [
        _t(CONFIRMED, "정책 백테스트의 비용 후 곡선과 분봉 백테스트가 남긴 비용 후 일별 손익을 그대로 읽어 합쳤습니다. 두 백테스트를 다시 계산하지 않았습니다."),
        _t(CONFIRMED, "몫은 몫을 정한 날의 시가 전에 알던 국면 확률(전 거래일 종가까지)로 정했습니다."),
        _t(ASSUMED, "위성 수익률은 그날 분봉 손익(비용 후) ÷ 매매 몫 자본입니다. 몫이 바뀌면 진입 금액도 같은 비율로 바뀐다고 보고, "
                    "놀리는 자본의 이자는 0 으로 봅니다."),
        _t(ASSUMED, f"옮긴 몫에는 정책 백테스트의 비용 가정({req.get('cost_bps', 0.0):g}bp)을 적용했습니다. 시작 자본은 핵심에 투자된 상태로 보고 "
                    "첫날 위성으로 옮기는 몫도 비용을 냅니다."),
        _t(UNKNOWN, "분봉의 시점 정합은 미상입니다. 봉 시각의 뜻(그 1분의 시작인지 끝인지)을 확인하지 못했습니다."),
    ]
    if view.get("synthetic"):
        trust.append(_practice("합성 자료(모의 시세 · 모의 지수 · 합성 분봉 가운데 하나 이상) 위의 숫자입니다. "
                               "계산 장치를 확인하는 용도이며 예측력이나 수익의 증거가 아닙니다."))
    return {"title": "핵심과 위성을 국면별 매매 몫으로 합쳤습니다", "facts": facts, "trust": trust,
            "unmeasured": ["합친 것이 더 낫다는 증거(경제적 가치)", "실제 계좌의 체결 · 세금 · 이자",
                           "비율 표를 바꿔 다시 본 횟수(이 노드는 세지 않습니다)"]}


# ── 등록 ─────────────────────────────────────────────────────────────────────────────────
def register(registry: pg.Registry) -> None:
    registry.register(pg.NodeSpec(
        KIND, "매매 몫 결합", stage="check", plain_label="매매 몫 결합",
        plain_description="배분 결과(핵심)와 분봉 매매(위성)를 국면별 매매 몫으로 합친 곡선과, 같은 평균 몫으로 고정한 곡선을 나란히 산출합니다.",
        inputs=(P("core", "BacktestResult"), P("run", "IntradayRun")), outputs=(), run=_mix, params_model=MixParams,
        explain=_explain, category="백테스트", wants_actor=True,
        description="정책 백테스트의 비용 후 곡선 + 분봉 시행의 비용 후 일별 손익(읽기만) · 시장 국면(같은 함수) · 쓰기 0 · 출력 없음 · 단추 없음."))


__all__ = ["ENGINE_REFUSALS", "KIND", "NOT_OFFERED", "NOTES", "REASONS", "WHO", "register"]
