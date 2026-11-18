"""시장 국면(일) — 지수 종가의 20거래일 수익 · 실현 변동성을 GMM 으로 나눈 국면의 소속 확률 (구현 계획 §7.1 · K1)
==============================================================================
★순수 함수★ — 파일 · DB 를 읽지 않는다. 지수 일봉을 읽는 일은 문 층(`intraday_market_regime_routes`)이 한다.

- 특징: 거래일 t 의 r20 = ln(C_t / C_{t−20}) · σ20 = 일 로그 수익 20개의 표본 표준편차(ddof 1) × √252.
  종가 21개 창에 0 이하 · 비유한 종가가 하나라도 있으면 그날 특징은 미상이다(나눗셈 · 로그 가드).
- 거래일 d 의 입력 = ★직전 거래일(d−1) 의 특징★ — d 의 종가를 보지 않는다.
- 적합: 달마다 — 그달 첫 거래일 ★전★ 의 특징 가운데 마지막 `FIT_DAYS` 개(고정 길이 후행 창 — 같은 날은 읽기 시작점과 무관하게 같은 값).
  창의 평균 · 표준편차로 표준화 → `GaussianMixture(k, full, random_state=s)` 를 시드 `0 … SEEDS−1` 로 → 성분을 σ20 평균 오름차순으로 번호
  (1 = 변동성 가장 낮음) → 소속 확률을 시드 평균. 수렴하지 못한 시드는 빼고 그 수를 센다. BLAS 는 한 스레드로 묶는다(작은 행렬에서 25배 — 잰 값).
- ★창이 다 차야 적합한다★: 그달 첫 거래일 전의 특징이 `FIT_DAYS` 개보다 적으면 그달의 날은 미상 + 사유(필요 · 있는 날 수).
  짧은 창으로 적합하면 나중에 앞쪽 이력이 적재될 때 같은 날의 값이 바뀐다(이 값을 규칙 조건으로 쓰면(K3 · 아직 없음) 같은 설정에서 다른 체결이 나온다). 미상을 0 이나 균등 확률로 채우지 않는다.
  `FIT_DAYS`(750) ÷ 최대 국면 수(4) = 국면당 평균 187일 — full 공분산 2차원 성분의 매개변수 6개에 견줘 충분하다.

- ★특징이 변하지 않는 창은 나누지 않는다★: 창 안의 두 특징 가운데 하나라도 표준편차가 `MIN_FEATURE_SD` 보다 작으면(평평한 가격 · 일정한 성장)
  그달은 미상 + 사유. 그런 창을 표준화하면 분산 0 열이 상수가 되거나 반올림 잡음이 커져, 한쪽 100% · 반반 같은 확률을 지어낸다(잰 값 · 시험이 건다).
- 적합 줄 `fit`: `window_days`(창 길이) · `refits`(다시 적합한 달 수) · `seeds`(적합마다 쓰려 한 시드 수) · `failed`(수렴하지 못해 뺀 시드 — 모든 적합의 합).
  확률은 수렴한 시드만으로 평균한다. 한 달의 시드가 모두 실패하면 그달은 미상 + 사유.

- ★셋째 특징(K5 · 선택)★: `extra`(날짜마다 하루 유형 비중 — `src.engine.day_type_share`)를 주면 특징 = [r20, σ20, extra] 이고
  거래일 d 는 역시 d−1 의 값을 쓴다. `extra` 가 없으면 이 모듈의 답은 K5 전과 같다(K1 · K2 · K3 · K4 가 쓰는 길).
  셋째 특징이 있으면 성분이 비중 축으로 갈릴 수 있어 σ20 평균이 거의 같은 두 성분의 번호가 시드마다 뒤바뀐다 — 그대로 평균하면 확률이 뭉개진다.
  그래서 ★시드끼리 성분을 평균의 거리로 맞춘 뒤★(헝가리안 배정 · 첫 시드가 기준) 첫 시드의 σ20 평균 순으로 번호를 붙인다(번호 규칙은 K1 과 같다).
  달 사이에도 같은 일이 생길 수 있어(띠의 색이 달 경계에서 바뀌어 보인다) 앞 달 성분과 번호가 이어지지 않은 달을 세어 싣고, 마지막 적합의 성분 평균을 싣는다.

★이 모듈이 말하지 않는 것★: 국면은 이름표다(번호와 통계뿐 · 뜻을 붙인 이름 없음). 다음 날 국면을 맞힌다는 말이 아니다(P).
BIC 는 같은 자료의 k = 2 · 3 · 4 를 나란히 적을 뿐 고르지 않는다 — 국면 수는 사용자가 정한다.
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np

WINDOW = 20
FIT_DAYS = 750
SEEDS = 10
K_RANGE = (2, 4)
BIC_KS = (2, 3, 4)
#: 적합 창의 특징 표준편차가 이보다 작으면 '변하지 않는 창'이다. 특징은 단위 없는 값(로그 수익 · 연율 변동성 — 실제 지수에서 1e-3 단위로 변한다)이라
#: 절대 문턱이다. 일정한 성장의 σ20 은 반올림 잡음(1e-17 단위)만 남는다 — 그 잡음을 표준화가 키우지 않게 그보다 넉넉히 위에 둔다.
MIN_FEATURE_SD = 1e-9
_ANNUAL = math.sqrt(252.0)

REASONS = {
    "first_day": "자료의 첫 거래일이라 직전 거래일의 특징이 없습니다.",
    "no_feature": "직전 거래일의 특징이 없습니다. 그날까지 종가 21개(20거래일)가 모두 0보다 커야 셉니다.",
    "too_little_history": "적합에 쓸 날이 모자랍니다. 필요 {need}일 · 있는 날 {have}일.",
    "fit_failed": "모든 난수 시드에서 적합이 수렴하지 않았습니다.",
    "flat_window": "적합 창의 특징(20거래일 수익 · 실현 변동성)이 변하지 않아 국면을 나누지 않았습니다.",
    "no_share": "직전 거래일의 하루 유형 비중이 없습니다.",
    "flat_share": "적합 창의 하루 유형 비중이 변하지 않아 국면을 나누지 않았습니다.",
}


class RegimeError(ValueError):
    """부르는 쪽의 잘못(국면 수 범위 · 날짜 순서 · 길이) — 문 층이 422 로 올린다."""


def features(closes: Any) -> tuple[np.ndarray, np.ndarray]:
    """종가(날짜 오름차순) → (r20, σ20). 미상은 NaN."""
    c = np.asarray(closes, dtype=float)
    n = len(c)
    r20, s20 = np.full(n, np.nan), np.full(n, np.nan)
    good = np.isfinite(c) & (c > 0)
    lc = np.full(n, np.nan)
    lc[good] = np.log(c[good])
    for t in range(WINDOW, n):
        win = lc[t - WINDOW: t + 1]
        if not np.isfinite(win).all():
            continue
        r20[t] = win[-1] - win[0]
        s20[t] = float(np.std(np.diff(win), ddof=1)) * _ANNUAL
    return r20, s20


@dataclass
class _Fit:
    mu: np.ndarray
    sd: np.ndarray
    models: list = field(default_factory=list)     # (GaussianMixture, order) — 수렴한 시드만
    failed: int = 0
    rows: int = 0
    Z: np.ndarray | None = None

    def probs(self, x: np.ndarray) -> list[float]:
        z = ((x - self.mu) / self.sd)[None, :]
        acc = np.zeros(len(self.models[0][1]))
        for g, order in self.models:
            acc += g.predict_proba(z)[0][order]
        p = acc / len(self.models)
        return [float(v) for v in p]


    def centers(self) -> np.ndarray:
        """번호 순 성분 평균(원래 단위) — 맨 앞 시드의 것(셋째 특징이 있으면 맞춤의 기준 시드). 행 = 국면 1 … k."""
        g, order = self.models[0]
        return g.means_[order] * self.sd + self.mu


def _fit(Xh: np.ndarray, k: int, seeds: int, *, match: bool = False) -> _Fit:
    from sklearn.mixture import GaussianMixture
    from threadpoolctl import threadpool_limits

    mu = Xh.mean(axis=0)
    sd = Xh.std(axis=0)                                # 부르는 쪽이 변하지 않는 창을 미리 거른다(`flat_window`) — 여기서 0 을 1 로 바꿔 덮지 않는다
    Z = (Xh - mu) / sd
    out = _Fit(mu=mu, sd=sd, rows=len(Xh), Z=Z)
    with threadpool_limits(1), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for s in range(seeds):
            try:
                g = GaussianMixture(n_components=k, covariance_type="full", random_state=s).fit(Z)
            except Exception:                         # noqa: BLE001 — 시드 하나의 실패는 세어 둔다(전부면 사유)
                out.failed += 1
                continue
            if not g.converged_:
                out.failed += 1
                continue
            out.models.append((g, np.argsort(g.means_[:, 1], kind="stable")))
    if match and out.models:
        out.models = _matched(out.models)
    return out


def _assignment(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a 의 성분 r 에 맞는 b 의 성분 번호(평균 사이 제곱 거리의 합이 가장 작은 짝 — 헝가리안 배정)."""
    from scipy.optimize import linear_sum_assignment

    cost = ((a[:, None, :] - b[None, :, :]) ** 2).sum(axis=2)
    rows, cols = linear_sum_assignment(cost)
    return cols[np.argsort(rows)]


def _matched(models: list) -> list:
    """셋째 특징이 있을 때의 시드 맞춤 — 기준 시드의 성분에 다른 시드의 성분을 평균의 거리(표준화된 공간)로 맞추고,
    기준의 σ20 평균 순으로 번호를 붙인다. 비중으로 갈린 성분은 σ20 평균이 거의 같아(잰 값: 표준화 단위 ±0.01), 시드마다 조금 다른 해에
    수렴하면 시드마다 따로 붙인 σ20 순이 뒤바뀔 수 있다 — 같은 해로 수렴한 시드끼리는 평균이 같아 뒤바뀌지 않는다.
    ★기준 = 가능도(하한)가 가장 큰 시드★ — 첫 시드로 두면 그 시드가 다른 국소해에 수렴했을 때 나머지가 엉뚱한 성분에 맞춰진다
    (잰 값: 비중 계단 자료에서 시드 열 가운데 셋이 비중이 아닌 해에 수렴했다 — 시드 0 이 그중 하나). 같으면 앞 시드.
    다른 해에 수렴한 시드도 평균에 든다(K1 과 같다 — 그 몫만큼 확률이 덜 날카롭다)."""
    best = max(range(len(models)), key=lambda i: (float(models[i][0].lower_bound_), -i))
    ref = models[best][0].means_
    ref_order = np.argsort(ref[:, 1], kind="stable")
    matched = [(g, _assignment(ref, g.means_)[ref_order]) for g, _ in models]
    return [matched[best]] + matched[:best] + matched[best + 1:]   # 기준을 맨 앞에(성분 평균 · 달 사이 비교가 기준의 것을 읽는다)


def numbering_follows(prev: np.ndarray, cur: np.ndarray, scale: np.ndarray) -> bool:
    """앞 적합과 이번 적합의 번호가 이어지는가 — 번호 순 성분 평균(원래 단위)을 이번 창의 표준편차로 나눠 맞춘 짝이 같은 번호끼리면 참."""
    a, b = np.asarray(prev, dtype=float) / scale, np.asarray(cur, dtype=float) / scale
    return bool(np.array_equal(_assignment(a, b), np.arange(len(a))))


def _bic(Z: np.ndarray, seeds: int) -> dict[str, float | None]:
    from sklearn.mixture import GaussianMixture
    from threadpoolctl import threadpool_limits

    out: dict[str, float | None] = {}
    with threadpool_limits(1), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for kk in BIC_KS:
            vals = []
            for s in range(seeds):
                try:
                    g = GaussianMixture(n_components=kk, covariance_type="full", random_state=s).fit(Z)
                except Exception:                     # noqa: BLE001
                    continue
                if g.converged_:
                    vals.append(float(g.bic(Z)))
            out[str(kk)] = min(vals) if vals else None
    return out


def _agreement(fit: _Fit) -> dict[str, float | int] | None:
    from sklearn.metrics import adjusted_rand_score

    if fit.Z is None or len(fit.models) < 2:
        return None
    labels = [order.argsort()[g.predict(fit.Z)] for g, order in fit.models]   # 성분 번호 → 국면 번호(변동성 순)
    ari = [float(adjusted_rand_score(labels[0], other)) for other in labels[1:]]
    return {"min": min(ari), "mean": sum(ari) / len(ari), "seeds": len(fit.models)}


def regime_days(dates: list[str], closes: Any, *, k: int, start: str, end: str,
                fit_days: int = FIT_DAYS, seeds: int = SEEDS,
                extra: Any = None, extra_reasons: list[str | None] | None = None) -> dict[str, Any]:
    """판정 기간 [start, end] 의 거래일마다 국면 확률. `dates` 는 오름차순 ISO 날짜(자료 전체 — 판정 기간 앞의 이력 포함).

    `extra`(선택 · K5) = 날짜마다 셋째 특징(하루 유형 비중 · 모르면 NaN) · `extra_reasons` = 모르는 날의 사유 문장(없으면 일반 문장)."""
    if not (K_RANGE[0] <= k <= K_RANGE[1]):
        raise RegimeError(f"국면 수는 {K_RANGE[0]} ~ {K_RANGE[1]} 입니다")
    dates = list(dates)
    c = np.asarray(closes, dtype=float)
    if len(dates) != len(c) or any(a >= b for a, b in zip(dates, dates[1:])):
        raise RegimeError("날짜는 겹치지 않는 오름차순이고 종가와 길이가 같아야 합니다")
    r20, s20 = features(c)
    if extra is None:
        if extra_reasons is not None:
            raise RegimeError("셋째 특징 없이 그 사유만 줄 수 없습니다")
        X = np.column_stack([r20, s20])
    else:
        e = np.asarray(extra, dtype=float)
        if len(e) != len(c) or (extra_reasons is not None and len(extra_reasons) != len(c)):
            raise RegimeError("셋째 특징과 그 사유는 날짜와 길이가 같아야 합니다")
        X = np.column_stack([r20, s20, e])
    known = np.isfinite(X).all(axis=1)
    index_known = np.isfinite(r20) & np.isfinite(s20)
    lc = np.where(np.isfinite(c) & (c > 0), np.log(np.where(c > 0, c, 1.0)), np.nan)
    first_of: dict[str, int] = {}
    for i, d in enumerate(dates):
        first_of.setdefault(d[:7], i)

    fits: dict[str, _Fit | tuple[str, int]] = {}
    failed = 0
    days: list[dict[str, Any]] = []
    for i, d in enumerate(dates):
        if not (start <= d <= end):
            continue
        month = d[:7]
        if month not in fits:
            hist = np.flatnonzero(known[:first_of[month]])[-fit_days:]
            if len(hist) < fit_days:
                fits[month] = ("too_little_history", len(hist))
            elif bool((flat := X[hist].std(axis=0) < MIN_FEATURE_SD).any()):
                fits[month] = ("flat_window" if bool(flat[:2].any()) else "flat_share", len(hist))
            else:
                f = _fit(X[hist], k, seeds, match=extra is not None)
                failed += f.failed
                fits[month] = f if f.models else ("fit_failed", len(hist))
        row: dict[str, Any] = {"date": d, "probs": None, "top": None, "top_prob": None, "reason": None}
        f = fits[month]
        if isinstance(f, tuple):
            code, have = f
            row["reason"] = REASONS[code].format(need=fit_days, have=have)
        elif i == 0:
            row["reason"] = REASONS["first_day"]
        elif not index_known[i - 1]:
            row["reason"] = REASONS["no_feature"]
        elif not known[i - 1]:                               # 지수 특징은 있고 셋째 특징(비중)을 모른다
            row["reason"] = (extra_reasons[i - 1] if extra_reasons is not None and extra_reasons[i - 1] else REASONS["no_share"])
        else:
            p = f.probs(X[i - 1])
            top = int(np.argmax(p))
            row.update(probs=p, top=top + 1, top_prob=p[top])
        row["ret"] = float(lc[i] - lc[i - 1]) if i > 0 and np.isfinite(lc[i]) and np.isfinite(lc[i - 1]) else None
        days.append(row)

    states = []
    valued = [r for r in days if r["top"] is not None]
    for s in range(1, k + 1):
        rets = [r["ret"] for r in valued if r["top"] == s and r["ret"] is not None]
        states.append({"state": s, "days": sum(1 for r in valued if r["top"] == s),
                       "share": (sum(1 for r in valued if r["top"] == s) / len(valued)) if valued else None,
                       "mean_return": (sum(rets) / len(rets)) if rets else None,
                       "realized_vol": (float(np.std(rets, ddof=1)) * _ANNUAL) if len(rets) >= 2 else None})
    transitions = sum(1 for a, b in zip(valued, valued[1:]) if a["top"] != b["top"])
    last = next((f for f in reversed(list(fits.values())) if isinstance(f, _Fit)), None)
    for r in days:
        r.pop("ret")
    out = {"days": days, "states": states, "transitions": transitions,
           "bic": _bic(last.Z, seeds) if last is not None else None,
           "agreement": _agreement(last) if last is not None else None,
           "fit": {"window_days": fit_days, "refits": sum(isinstance(f, _Fit) for f in fits.values()),
                   "seeds": seeds, "failed": failed}}
    if extra is None:
        return out                                          # K1 의 답 모양 그대로
    fitted = [(m, f) for m, f in fits.items() if isinstance(f, _Fit)]
    renumbered = [m for (_, a), (m, b) in zip(fitted, fitted[1:]) if not numbering_follows(a.centers(), b.centers(), b.sd)]
    out["fit"].update(renumbered=len(renumbered), renumbered_months=renumbered)
    out["centers"] = ([{"state": s + 1, "r20": float(row[0]), "sigma20": float(row[1]), "share": float(row[2])}
                       for s, row in enumerate(last.centers())] if last is not None else None)
    return out
