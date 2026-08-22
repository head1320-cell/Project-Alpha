"""AutoAlpha 후보 생성 샌드박스 (Full Expansion P6 — Experimental)
==============================================================================
지시서: 실험 기능(AutoAlpha·유전 탐색·대체데이터·텍스트·RL)은 "절대 자동 채택하지
않는다 — 항상 인간 검증이 필요한 후보 생성기로 취급한다. 어떤 실험도 승인·검증·운영
통제를 우회하지 못하게 하라."

이 모듈은 P2의 알파 DSL(FIELDS·FUNCS·lint·parse)을 재사용해 후보 알파 표현식을
생성·린트한다. 생성만 하며, 사용 가능(validated/approved) 상태로 만들지 않는다 —
스테이징은 반드시 experimental 상태로만(레지스트리 승급 사다리 draft→experimental→
validated→approved를 그대로 통과해야 실전 사용). 결정론적(seed 고정) — 재현 가능.

★거버넌스 상한★: STAGE_STATUS = "experimental" (그 이상으로 절대 스테이징 불가).
"""

from __future__ import annotations

import random
import re
from typing import Any

from src.engine.alpha_lab import FIELDS, FUNCS_2, lint_alpha

# 실험 후보는 experimental 이상으로 절대 승격 불가 (샌드박스가 만들 수 있는 최대 상태)
STAGE_STATUS = "experimental"

_ALL_FIELDS = [f[0] for f in FIELDS]
# 스케일 안전 변환(단일 필드에 씌워 rank/zscore 정규화 — scale_mix 경고 회피)
_NORM = ("rank", "zscore", "winsorize")
_DIR = ("", "neg")   # 방향(원방향 / 반전)
# price_level은 원값 경고 유발 → 후보 생성에서 제외(정직한 알파만)
_SAFE_FIELDS = [f for f in _ALL_FIELDS if f != "price_level"]


def _term(rng: random.Random) -> str:
    """단일 정규화 항: [neg](norm(field))."""
    field = rng.choice(_SAFE_FIELDS)
    norm = rng.choice(_NORM)
    base = f"{norm}({field})"
    return f"neg({base})" if rng.random() < 0.35 else base


def _random_expr(rng: random.Random) -> str:
    """랜덤 후보 — 단일항 / 이항결합 / 가중합 / 스프레드 중 하나."""
    kind = rng.random()
    if kind < 0.35:
        return _term(rng)
    if kind < 0.6:
        b = rng.choice(FUNCS_2)           # min2 / max2
        return f"{b}({_term(rng)}, {_term(rng)})"
    if kind < 0.85:
        w = rng.choice((0.3, 0.5, 0.7))   # 가중합
        return f"{w}*{_term(rng)} + {round(1 - w, 1)}*{_term(rng)}"
    return f"{_term(rng)} - {_term(rng)}"  # 스프레드


def _mutate(expr: str, rng: random.Random) -> str:
    """유전 변이 — 식 안의 필드 하나 또는 정규화 함수 하나를 교체."""
    fields_in = [f for f in _SAFE_FIELDS if re.search(rf"\b{re.escape(f)}\b", expr)]
    if fields_in and rng.random() < 0.6:
        old = rng.choice(fields_in)
        new = rng.choice(_SAFE_FIELDS)
        return re.sub(rf"\b{re.escape(old)}\b", new, expr, count=1)
    for nrm in _NORM:
        if f"{nrm}(" in expr:
            return expr.replace(f"{nrm}(", f"{rng.choice(_NORM)}(", 1)
    return expr


def _crossover(a: str, b: str, rng: random.Random) -> str:
    """유전 교배 — 두 부모를 이항 결합/가중합으로 합침."""
    if rng.random() < 0.5:
        return f"{rng.choice(FUNCS_2)}({a}, {b})"
    return f"0.5*({a}) + 0.5*({b})"


def generate_candidates(n: int = 12, seed: int = 0, mode: str = "random",
                        seeds: list[str] | None = None,
                        existing: list[str] | None = None) -> dict[str, Any]:
    """후보 알파 생성 + 린트. 유효(파싱 성공·error 없음)·비중복만 반환. 결정론적."""
    rng = random.Random(seed)
    existing_norm = {re.sub(r"\s+", "", e) for e in (existing or [])}
    seen: set[str] = set()
    out: list[dict] = []
    attempts = 0
    max_attempts = max(n * 12, 60)

    parents = [s for s in (seeds or []) if s and s.strip()]

    while len(out) < n and attempts < max_attempts:
        attempts += 1
        if mode == "genetic" and parents:
            if len(parents) >= 2 and rng.random() < 0.5:
                expr = _crossover(rng.choice(parents), rng.choice(parents), rng)
            else:
                expr = _mutate(rng.choice(parents), rng)
        else:
            expr = _random_expr(rng)

        norm = re.sub(r"\s+", "", expr)
        if norm in seen or norm in existing_norm:
            continue
        lint = lint_alpha(expr, existing_exprs=existing)
        if not lint["ok"]:            # error-level(파싱·0나누기 등)은 폐기
            continue
        seen.add(norm)
        out.append({
            "expr": expr,
            "fields": lint["fields"],
            "funcs": lint["funcs"],
            "warnings": [i for i in lint["issues"] if i["level"] == "warn"],
            "info": [i for i in lint["issues"] if i["level"] == "info"],
        })

    return {
        "candidates": out,
        "requested": n,
        "generated": len(out),
        "attempts": attempts,
        "mode": mode if not (mode == "genetic" and not parents) else "random",
        "governance": {
            "status_ceiling": STAGE_STATUS,
            "auto_adopt": False,
            "note": "실험 후보 — 자동 채택 금지. 스테이징은 experimental 상태로만 되며, 실전 "
                    "사용(validated→approved)에는 인간 검증(Alpha Lab)이 반드시 필요합니다.",
        },
        "selection_bias": selection_bias_note(n),
    }


def selection_bias_note(n_trials: int) -> dict[str, Any]:
    """다중검정/선택편향 경고(DSR-lite). N개 탐색 후 최고 IC를 고르면 최고값은 위로
    편향된다 — 검증 임계를 상향해야 함(정직한 과적합 경고). 근사: N개 표준정규 최댓값
    기대 ≈ sqrt(2 ln N)."""
    import math
    n = max(int(n_trials), 1)
    inflation = math.sqrt(2 * math.log(n)) if n > 1 else 0.0
    return {
        "n_trials": n,
        "expected_max_z": round(inflation, 2),
        "note": f"{n}개 후보를 탐색해 최고를 고르면 최고 IC의 t-stat은 약 +{round(inflation, 2)}σ "
                "위로 편향됩니다(다중검정). 단일 검증 임계를 그만큼 상향하고, walk-forward·"
                "out-of-sample·PBO 등으로 과적합을 별도 확인하세요 — 이 편향은 자동 보정되지 않습니다.",
    }


def stage_candidates(exprs: list[str], name_prefix: str = "AutoAlpha",
                     universe: str = "kospi200",
                     upsert=None, existing: list[str] | None = None) -> dict[str, Any]:
    """선택 후보를 레지스트리에 experimental로 스테이징. ★status를 절대 experimental
    이상으로 올리지 않음★(거버넌스). error-린트는 거부. upsert는 테스트 주입용."""
    if upsert is None:
        from src.data.alpha_registry import upsert_alpha as upsert
    staged: list[dict] = []
    rejected: list[dict] = []
    for i, expr in enumerate(exprs):
        lint = lint_alpha(expr, existing_exprs=existing)
        if not lint["ok"]:
            rejected.append({"expr": expr, "reason": "lint error", "issues": lint["issues"]})
            continue
        row = upsert(None, f"{name_prefix} #{i + 1}", expr, "AutoAlpha 실험 후보",
                     universe=universe, status=STAGE_STATUS,   # ★ 상한 강제 ★
                     tags=["experimental", "auto_alpha"])
        if row is None:
            rejected.append({"expr": expr, "reason": "DB 미가용"})
        else:
            staged.append({"alpha_id": row.get("alpha_id"), "expr": expr,
                           "status": row.get("status")})
    return {
        "staged": staged, "rejected": rejected,
        "n_staged": len(staged),
        "governance": {
            "status": STAGE_STATUS, "auto_adopt": False,
            "note": "experimental로만 스테이징됨 — 실전 사용 전 Alpha Lab 검증(Rank IC/ICIR/"
                    "walk-forward) → validated → approved 승급이 필요. 검증 없이는 사용 불가.",
        },
    }


# 실험 기능 카탈로그 — 연결/미연결 정직 표기 (지시서: 자동 채택 금지, 후보 생성기)
def experimental_catalog() -> list[dict[str, Any]]:
    return [
        {"id": "auto_alpha", "label": "AutoAlpha 후보 탐색", "connected": True,
         "kind": "candidate_generator",
         "desc": "알파 DSL(필드·함수)로 후보 표현식을 랜덤/유전 탐색·린트. experimental로만 스테이징.",
         "governance": "인간 검증 필수 — 자동 채택 없음."},
        {"id": "genetic_search", "label": "유전 알고리즘 탐색", "connected": True,
         "kind": "candidate_generator",
         "desc": "기존 알파를 씨앗으로 변이·교배해 후보 생성(같은 DSL·거버넌스).",
         "governance": "인간 검증 필수."},
        {"id": "alt_data_events", "label": "대체데이터 이벤트 신호", "connected": False,
         "kind": "not_connected",
         "desc": "대체데이터 피드 미연동 — 후보 생성기 자리표시자. 데이터 계약·PIT 랙 검증 선행 필요.",
         "governance": "미연동(정직). 연동 시에도 실험 후보로만."},
        {"id": "text_disclosure", "label": "텍스트 공시·뉴스 요약 신호", "connected": False,
         "kind": "not_connected",
         "desc": "뉴스·공시 NLP 파이프라인 미연동 — LLM 요약/센티먼트 인프라 선행 필요.",
         "governance": "미연동(정직)."},
        {"id": "rl_allocation", "label": "강화학습 동적 배분", "connected": False,
         "kind": "not_connected",
         "desc": "RL 연구 환경(에이전트·시뮬레이터) 미구축 — 연구/에이전트/응용 계층 분리 선행 필요(FinRL 관례).",
         "governance": "미연동(정직). 운영 통제 우회 불가."},
        {"id": "physics_regime", "label": "물리 은유 국면 분류", "connected": False,
         "kind": "not_connected",
         "desc": "실험적 국면 분류 — 기존 매크로 레짐과 중복 우려로 미구축(별도 연구 과제).",
         "governance": "미연동(정직)."},
    ]
