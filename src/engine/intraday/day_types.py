"""하루 유형 — 장 시작 N분의 가격 경로가 닮은 표본(종목 하나의 하루)끼리 e-means 로 묶는다 (설계 2026-11-16 §3 T1 · 구현 계획 §5).

★순수 함수다★ — 파일 · DB · mock 게이트를 모른다. 봉은 문 층(`src/api/intraday_day_type_routes.py`)이 실행 문과 같은
준비(`minute_feed.build_days`)로 지어 넘긴다. 이 모듈이 정하는 것:

- **특징**: 그날 그 종목의 첫 봉 시각부터 N분 — 첫 N개 봉이 1분마다 하나씩 있어야 하고, 벡터는 첫 봉 시가 대비 종가(bp).
  결정 시각은 창의 마지막 봉이 닫힌 때다. 그 뒤의 봉은 읽지 않는다(앞보기 0).
- **학습**: faiss 의 e-means(`NumpyEmeans` · 난수 시드 고정 · 5회차) → 중심을 끝값 오름차순으로 번호 매김(유형 1 … k).
- **배정**: 저장한 중심에서 float64 로 다시 센다(가장 가까운 중심 · 같으면 작은 번호). e-means 가 돌려주는 라벨은 ★마지막 회차
  도중의 라벨★이라(faiss 문서) 최종 중심의 배정과 다를 수 있다 — 모형의 유형 · 손실 · 표본 수는 전부 이 배정에서 나온다.
  T2 가 새 날의 유형을 셀 때도 같은 함수를 쓴다.
- **함께 싣는 사실**: 같은 자료에서 여러 번 시작한 Lloyd 의 손실(이 크기에서는 e-means 의 이점이 없다는 사실이 드러나게) ·
  난수 시드 다섯의 배정 일치도(조정 랜드 지수 — 유형이 시드에 기대는지).

★이 모듈이 말하지 않는 것★: 유형은 장 초반의 ★모양을 묶은 것★이다. 그 뒤의 움직임 · 수익을 예측한다는 뜻이 아니고(③ · ④),
묶음이 실제 시장에서 뜻이 있다는 증거도 아니다. 유형 수는 사용자가 정한다 — 이 모듈은 성과로 k 를 고르지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from src.engine.intraday.simulator import Day
from src.engine.intraday.types import Session

METHOD = "e-means"
VERSION = 1
#: 모형의 난수 시드(faiss 의 기본값과 같다) · 일치도를 재는 다른 시드 넷. ★사용자가 고르지 않는다★ — 시드를 바꿔 가며
#: 마음에 드는 유형을 고르는 일을 막는다(그것도 여러 번 해 본 것이다).
SEED = 1234
CHECK_SEEDS = (1235, 1236, 1237, 1238)
EPOCHS = 5
#: 같은 자료에 견줄 Lloyd(sklearn `KMeans`) — 시작 10번 · 시드 0.
LLOYD_STARTS = 10
LLOYD_SEED = 0
#: 유형 하나에 평균 표본 다섯 — 이보다 적으면 묶음이 표본 몇 개의 모양이 된다(설정값 · 근거는 계획 §5.1).
MIN_SAMPLES_PER_TYPE = 5
MIN_MINUTES, MAX_MINUTES = 5, 120
MIN_K, MAX_K = 4, 16
BP = 1e4
#: 거리를 한 번에 세는 행 수 — 2,000 × 16 × 120 을 한꺼번에 펼치면 30MB 다.
_CHUNK = 512

#: 표본을 뺀 사유(이 모듈이 정하는 것). 봉을 준비한 쪽이 이미 건너뛴 표본은 그쪽의 사유 코드를 그대로 싣는다.
EXCLUDE_REASONS = {
    "short_window": "첫 봉부터 정한 분 수 동안 1분마다 봉이 하나씩 있지 않습니다(빠진 분이 있거나 그날 봉이 모자랍니다).",
    "bad_price": "첫 봉 시가나 창 안의 종가가 0 이하이거나 숫자가 아닙니다.",
}
REFUSALS = {
    "bad_minutes": f"분 수는 {MIN_MINUTES} 이상 {MAX_MINUTES} 이하의 정수여야 합니다.",
    "bad_k": f"유형 수는 {MIN_K} 이상 {MAX_K} 이하의 정수여야 합니다.",
    "too_few_samples": f"쓸 수 있는 표본이 유형 수의 {MIN_SAMPLES_PER_TYPE}배보다 적어 학습하지 않았습니다.",
    "train_failed": "학습이 유한한 중심을 내지 못했습니다. 모형을 만들지 않았습니다.",
}


class DayTypeError(ValueError):
    """학습하지 않은 까닭 — 코드 · 문장 · 세부(문 층이 그대로 답에 싣는다)."""

    def __init__(self, code: str, **detail) -> None:
        super().__init__(REFUSALS[code])
        self.code = code
        self.detail = detail


def check_setting(minutes: int, k: int) -> None:
    if isinstance(minutes, bool) or not isinstance(minutes, (int, np.integer)) or not MIN_MINUTES <= minutes <= MAX_MINUTES:
        raise DayTypeError("bad_minutes", minutes=minutes)
    if isinstance(k, bool) or not isinstance(k, (int, np.integer)) or not MIN_K <= k <= MAX_K:
        raise DayTypeError("bad_k", k=k)


# ── 특징 ────────────────────────────────────────────────────────────────────────────────
def _minute(hhmmss) -> int | None:
    s = str(hhmmss)
    if len(s) < 4 or not s[:4].isdigit():
        return None
    return int(s[:2]) * 60 + int(s[2:4])


def window(session: Session, minutes: int) -> tuple[np.ndarray | None, str | None]:
    """그날의 장 초반 경로(bp) 또는 뺀 사유. 첫 N개 봉만 본다 — 그 뒤의 봉은 읽지 않는다."""
    if len(session.time) < minutes:
        return None, "short_window"
    clock = [_minute(t) for t in session.time[:minutes]]
    if clock[0] is None or clock != list(range(clock[0], clock[0] + minutes)):
        return None, "short_window"
    o0 = float(session.open[0])
    closes = np.asarray(session.close[:minutes], dtype=np.float64)
    if not (np.isfinite(o0) and o0 > 0.0) or not (np.isfinite(closes).all() and (closes > 0.0).all()):
        return None, "bad_price"                                 # 0 · 음수 · NaN 으로 나누지 않는다
    return (closes / o0 - 1.0) * BP, None


@dataclass(frozen=True)
class Collected:
    """학습에 쓸 표본 — 행은 (날, 종목) 순이다(들어온 순서와 무관 · 열쇠와 학습이 같은 순서를 본다)."""

    X: np.ndarray                                  # (n, N) bp
    samples: list[tuple[str, str]]                 # (날, 종목)
    starts: list[str]                              # 표본마다 첫 봉 시각("HHMMSS")
    excluded: list[tuple[str, str, str]]           # (날, 종목, 사유 코드) — 날 · 종목 순
    grade: str                                     # 쓴 봉의 출처 등급(가장 약한 출처가 정한다)
    sources: dict[str, int]                        # 쓴 표본의 출처별 수


def collect(days: Iterable[Day], minutes: int) -> Collected:
    from src.engine.intraday import session_grade  # 꾸러미가 다 읽힌 뒤에 부른다(같은 꾸러미의 공개 도우미)

    rows: list[np.ndarray] = []
    samples: list[tuple[str, str]] = []
    starts: list[str] = []
    used: list[Session] = []
    excluded: list[tuple[str, str, str]] = []
    for day in days:
        excluded.extend((day.date, ticker, reason) for ticker, reason in day.skipped)
        for ticker, s in day.sessions.items():
            vec, reason = window(s, minutes)
            if vec is None:
                excluded.append((day.date, ticker, str(reason)))
                continue
            rows.append(vec)
            samples.append((day.date, ticker))
            starts.append(str(s.time[0]))
            used.append(s)
    order = sorted(range(len(samples)), key=lambda i: samples[i])
    X = np.asarray([rows[i] for i in order], dtype=np.float64).reshape(len(order), minutes)
    picked = [used[i] for i in order]
    return Collected(X=X, samples=[samples[i] for i in order], starts=[starts[i] for i in order], excluded=sorted(excluded),
                     grade=session_grade(picked),
                     sources=dict(Counter(s.source if s.source in ("kis", "synthetic") else "unknown" for s in picked)))


# ── 학습 · 번호 · 배정 ────────────────────────────────────────────────────────────────────
def train_centroids(X: np.ndarray, k: int, seed: int) -> np.ndarray:
    """e-means 한 번 → 중심(번호 매기기 전). faiss 는 학습할 때만 들인다(서버 기동 · 다른 문에 짐을 지우지 않는다)."""
    from faiss.contrib.e_means import NumpyEmeans

    model = NumpyEmeans(X.shape[1], k, nepochs=EPOCHS, seed=seed)
    centroids, _last_pass_labels = model.train(np.ascontiguousarray(X, dtype=np.float32))   # 라벨은 쓰지 않는다(위 머리말)
    return np.asarray(centroids, dtype=np.float64)


def order_centroids(C: np.ndarray) -> np.ndarray:
    """끝값(N분째) 오름차순 · 같으면 경로의 사전순 — 유형 번호가 학습의 우연한 순서에 기대지 않게."""
    C = np.asarray(C, dtype=np.float64)
    rows = C.tolist()
    return C[sorted(range(len(rows)), key=lambda i: (rows[i][-1], rows[i]))]


def assign(C: np.ndarray, X: np.ndarray) -> np.ndarray:
    """가장 가까운 중심의 번호(0부터) — float64 제곱 거리 · 같으면 작은 번호(`argmin` 은 첫 최솟값을 고른다)."""
    C = np.asarray(C, dtype=np.float64)
    X = np.asarray(X, dtype=np.float64)
    out = np.empty(len(X), dtype=np.int64)
    for a in range(0, len(X), _CHUNK):
        part = X[a:a + _CHUNK]
        out[a:a + len(part)] = ((part[:, None, :] - C[None, :, :]) ** 2).sum(axis=2).argmin(axis=1)
    return out


def _trained(X: np.ndarray, k: int, seed: int) -> np.ndarray:
    C = np.asarray(train_centroids(X, k, seed), dtype=np.float64)
    if C.shape != (k, X.shape[1]) or not np.isfinite(C).all():
        raise DayTypeError("train_failed", seed=seed)
    return order_centroids(C)


def _loss(C: np.ndarray, X: np.ndarray, labels: np.ndarray) -> float:
    return float(((X - C[labels]) ** 2).sum(axis=1).mean())


def _same_partition(a: np.ndarray, b: np.ndarray) -> bool:
    """두 배정이 같은 묶음인가 — 번호만 바뀐 것은 같다(일대일 대응)."""
    pairs = set(zip(a.tolist(), b.tolist(), strict=True))
    return len(pairs) == len(set(a.tolist())) == len(set(b.tolist()))


def _loss_block(emeans: float, lloyd: float) -> dict:
    se, sl = f"{emeans:,.1f}", f"{lloyd:,.1f}"
    # 화면 문장에는 줄표를 쓰지 않는다(문체 검사 · ADR 005) — 두 문장으로 나눈다.
    head = f"같은 자료에서 Lloyd(시작 {LLOYD_STARTS}번)의 손실은 {sl}, e-means 는 {se}입니다(평균 제곱 거리 · bp²)."
    if se == sl:
        tail = " 표시 자리에서 같습니다."
    elif lloyd < 0.05:                                           # Lloyd 가 0 에 가까우면 비율이 뜻을 잃는다
        tail = " e-means 가 높습니다." if emeans > lloyd else " e-means 가 낮습니다."
    else:
        pct = abs(emeans - lloyd) / lloyd * 100.0
        shown = f"{pct:,.1f}%" if pct >= 0.05 else "0.1% 미만으로"
        tail = f" e-means 가 {shown} {'높습니다' if emeans > lloyd else '낮습니다'}."
    return {"emeans": emeans, "lloyd": lloyd, "lloyd_starts": LLOYD_STARTS, "shown": {"emeans": se, "lloyd": sl},
            "note": head + tail}


def _agreement_block(labels: np.ndarray, others: list[np.ndarray]) -> dict:
    from sklearn.metrics import adjusted_rand_score

    ari = [float(adjusted_rand_score(labels, o)) for o in others]
    same = all(_same_partition(labels, o) for o in others)
    low = min(ari)
    digits = 2
    while not same and f"{low:.{digits}f}" == f"{1.0:.{digits}f}" and digits < 6:   # 반올림이 차이를 숨기지 않게
        digits += 1
    shown = [f"{a:.{digits}f}" for a in ari]
    note = ("난수 시드 다섯이 같은 배정을 냈습니다." if same
            else f"난수 시드에 따라 배정이 달라집니다(조정 랜드 지수 최소 {low:.{digits}f}).")
    return {"seeds": [SEED, *CHECK_SEEDS], "ari": ari, "shown": shown, "min": low, "mean": float(np.mean(ari)),
            "same": same, "note": note}


def type_stats(C: np.ndarray, X: np.ndarray, labels: np.ndarray) -> list[dict]:
    """유형마다 표본 수 · 비중 · 중심 경로 · 끝값 · 최저 · 최고 · 흩어짐(그 유형 표본들이 중심에서 떨어진 RMS · bp).

    표본이 없는 유형도 0 으로 싣는다(센 값이다). 흩어짐은 표본이 없으면 미상(`None`)이다."""
    C = np.asarray(C, dtype=np.float64)
    X = np.asarray(X, dtype=np.float64)
    n = len(X)
    out = []
    for j, path in enumerate(C):
        members = X[labels == j]
        count = len(members)
        out.append({"type": j + 1, "samples": count, "share": count / n if n else 0.0, "path": path.tolist(),
                    "end": float(path[-1]), "low": float(path.min()), "high": float(path.max()),
                    "spread": float(np.sqrt(((members - path) ** 2).mean())) if count else None})
    return out


def fit(X: np.ndarray, k: int) -> dict:
    """모형 하나 → `{labels(유형 번호 · 표본 순), types, loss, agreement}`. 학습하지 못하면 `DayTypeError`."""
    from sklearn.cluster import KMeans

    X = np.asarray(X, dtype=np.float64)
    n, minutes = X.shape
    check_setting(minutes, k)
    needed = MIN_SAMPLES_PER_TYPE * k
    if n < needed:
        raise DayTypeError("too_few_samples", samples=n, needed=needed, k=k)
    C = _trained(X, k, SEED)
    labels = assign(C, X)
    lloyd = KMeans(n_clusters=k, n_init=LLOYD_STARTS, random_state=LLOYD_SEED).fit(X)
    centres = np.asarray(lloyd.cluster_centers_, dtype=np.float64)
    others = [assign(_trained(X, k, seed), X) for seed in CHECK_SEEDS]
    return {"labels": (labels + 1).tolist(), "types": type_stats(C, X, labels),
            "loss": _loss_block(_loss(C, X, labels), _loss(centres, X, assign(centres, X))),
            "agreement": _agreement_block(labels, others)}


# ── 열쇠 ────────────────────────────────────────────────────────────────────────────────
def model_key(collected: Collected, *, minutes: int, k: int) -> str:
    """같은 표본 · 같은 봉 · 같은 설정 = 같은 열쇠(요청한 기간이 달라도) · 봉이 하나라도 바뀌면 다른 열쇠."""
    features = hashlib.sha256(np.ascontiguousarray(collected.X, dtype=np.float64).tobytes()).hexdigest()
    payload = [VERSION, METHOD, SEED, EPOCHS, int(minutes), int(k), [list(s) for s in collected.samples], features]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
