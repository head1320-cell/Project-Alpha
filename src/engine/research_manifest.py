"""판정 메니페스트 — ★증거와 어긋난 판정은 런타임이 거부한다★ (P5)
==============================================================================
검토서: `docs/specs/2026-09-02-deepseek-concept-review.md` §4 P5

Alpha 는 검증기를 이미 갖고 있다(`research_verdict`·`research_power`·
`research_panel`·`null_stats`·`regime_surrogates`). 빠진 것은 검증기가 아니라
★판정이 생산 소비자에게 돌아오는 간선★ 이었다 — `conditional=true` 는 A4 가
`underpowered`, A3 이 `inconclusive` 로 판정한 신호를 **그 판정을 한 번도 읽지
않고** 최적화기에 태웠다.

그리고 판정은 어디에도 영속화되지 않았다(`regime_control` 은 JSON 리포트 파일로만
냈다). 이 모듈이 그 자리를 채운다.

★메니페스트는 생성물이지 손으로 쓰는 것이 아니다★ M9 의 Q14 가 가르친 것이다:
합성 픽스처는 **하드코딩된 주장과 파생된 값을 구분하지 못한다**. 그래서
`load_manifest` 는 기록된 **증거로 `classify` 를 다시 돌려** 기록된 판정과
대조하고 어긋나면 거부한다 — 테스트가 잡는 것이 아니라 런타임이 막는다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.domain.build_identity import (
    METHOD_UNKNOWN,
    METHODS,
    TREE_UNKNOWN,
    TREES,
    BuildIdentity,
    as_identity,
    versions_comparable,
)
from src.engine.research_panel import evidence_grade
from src.engine.research_verdict import VERDICT_NO_EVIDENCE, VERDICT_POSITIVE, classify

logger = logging.getLogger(__name__)

#: 저장소 산물 — 관문이 생성하고 커밋한다. DB 없이도 읽힌다.
MANIFEST_PATH = Path("docs/specs/macro_gate_verdict.json")

#: ★schema 2 부터 사전등록 출처를 요구한다 (P6)★ 등록이 없는 판정은 "어느 규칙
#: 아래 나왔는지" 를 말할 수 없어 재현이 불가능하다 — 증거로 치지 않는다.
SCHEMA = 2

#: 판정을 재계산하는 데 필요한 증거. 하나라도 없으면 메니페스트를 받지 않는다.
EVIDENCE_FIELDS = ("null_outside", "spa_ok", "power", "target_power")


def load_manifest(path: str | Path | None = None) -> tuple[dict | None, str | None]:
    """메니페스트를 읽고 **판정을 재계산해 대조**한다. `(manifest, reason)`.

    ★어긋나면 `None` + 사유다★ — 손으로 `positive` 로 고쳐도 증거가 따라오지
    않으면 통하지 않는다. 재계산 대조가 없으면 이 파일은 그냥 **주장을 적어 둔
    파일**이고, 그것을 생산 경로가 읽는 것은 지금보다 나을 것이 없다.

    ★없으면 미상이지 통과가 아니다.★
    """
    p = Path(path) if path is not None else MANIFEST_PATH
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        return None, (f"판정 메니페스트를 읽지 못했습니다({p}) — {type(e).__name__}. "
                      "관문을 돌린 적이 없다는 뜻이며, ★미상은 통과가 아닙니다★.")
    try:
        m = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"판정 메니페스트가 JSON 이 아닙니다({p}) — {e}"
    if not isinstance(m, dict):
        return None, f"판정 메니페스트가 객체가 아닙니다({p})"

    if int(m.get("schema") or 0) < SCHEMA:
        return None, (
            f"판정 메니페스트 schema {m.get('schema')} 는 더 이상 증거가 아닙니다 "
            f"(현재 {SCHEMA}) — ★사전등록 출처가 없는 판정★ 이라 어느 결정규칙 "
            "아래 나왔는지 말할 수 없습니다(P6). 관문을 다시 돌려 재생성하십시오.")

    pre = m.get("preregistration")
    if not isinstance(pre, dict) or pre.get("matches") is not True:
        return None, (
            "판정이 사전등록과 일치한 실행에서 나왔다는 기록이 없습니다 — "
            f"preregistration={pre!r}. 등록과 어긋난 실행의 판정은 증거가 "
            "아닙니다(P6).")

    ev = m.get("evidence")
    if not isinstance(ev, dict) or any(f not in ev for f in EVIDENCE_FIELDS):
        missing = [f for f in EVIDENCE_FIELDS
                   if not isinstance(ev, dict) or f not in ev]
        return None, (f"판정을 재계산할 증거가 없습니다 — {', '.join(missing)} 누락. "
                      "증거 없는 판정은 주장이지 판정이 아닙니다.")

    # ★단일 출처로 다시 돌린다★ 파일에 적힌 판정을 믿지 않는다.
    recomputed = classify(null_outside=ev.get("null_outside"),
                          spa_ok=ev.get("spa_ok"), power=ev.get("power"),
                          target_power=ev.get("target_power", 0.8))
    if m.get("verdict") != recomputed["verdict"] or \
            bool(m.get("passed")) != bool(recomputed["passed"]):
        return None, (
            f"기록된 판정({m.get('verdict')}/passed={m.get('passed')})이 그 증거로 "
            f"재계산한 판정({recomputed['verdict']}/passed={recomputed['passed']})과 "
            "★어긋납니다★ — 위조되었거나 증거가 갱신되지 않았습니다.")

    # 재계산 결과를 싣는다 — 파일의 문자열이 아니라 **규칙의 산출**이 진실이다.
    return {**m, "verdict": recomputed["verdict"],
            "passed": bool(recomputed["passed"]),
            "why": recomputed.get("why") or []}, None


def _mismatches(adj: dict, *, universe, months, model, panel) -> list[str]:
    """이 요청이 **판정된 패널과 어떻게 다른가**. 순수 함수."""
    out: list[str] = []
    n_req = (None if universe is None else len(universe))
    n_adj = adj.get("n_assets")
    if n_req is not None and n_adj is not None and int(n_req) != int(n_adj):
        out.append(f"자산 수 {n_req} ≠ 판정 패널 {n_adj}")
    if months is not None and adj.get("months") is not None \
            and int(months) != int(adj["months"]):
        out.append(f"기간 {months}개월 ≠ 판정 패널 {adj['months']}개월")
    if model is not None and adj.get("model") is not None and model != adj["model"]:
        out.append(f"모델 {model!r} ≠ 판정 모델 {adj['model']!r}")
    if panel is not None and adj.get("panel") is not None and panel != adj["panel"]:
        out.append(f"패널 {panel!r} ≠ 판정 패널 {adj['panel']!r}")
    elif panel is None and adj.get("panel") is not None:
        out.append(f"이 요청의 패널을 선언하지 않았습니다 — 판정은 "
                   f"{adj['panel']!r} 을 상대로 내려졌습니다")
    return out


def _manifest_identity(m: dict) -> BuildIdentity:
    """메니페스트가 **기록한** 빌드 식별자. ★JSON 은 무엇이든 담을 수 있다★

    그래서 값을 검증해서 넣는다 — 모르는 `tree`/`method` 는 지어내지 않고
    미상으로 접는다. 커밋된 메니페스트에는 `code_tree` 가 아예 없고, 그것은
    **깨끗했다는 뜻이 아니라 잰 적이 없다는 뜻**이다.
    """
    value = m.get("code_version")
    tree = m.get("code_tree")
    method = m.get("code_version_method")
    return BuildIdentity(
        value=value if isinstance(value, str) else None,
        method=method if method in METHODS else METHOD_UNKNOWN,
        tree=tree if tree in TREES else TREE_UNKNOWN,
        reason=(None if tree in TREES else
                "이 메니페스트는 작업 트리 상태를 기록하지 않았습니다 — "
                "깨끗했다는 뜻이 아니라 잰 적이 없다는 뜻입니다."))


def verification_label(manifest: dict | None, *, universe=None, months=None,
                       model: str | None = None, panel: str | None = None,
                       code_version: BuildIdentity | str | None = None
                       ) -> dict[str, Any]:
    """조건부 μ/Σ 에 붙일 검증 라벨. ★순수 함수다.★

    ★메커니즘 판정을 요청 판정으로 옮기지 않는다★ 이것이 이 함수의 존재 이유다.
    A3 은 **E0 합성 6자산 84개월 패널**을 판정했다. 사용자의 KOSPI 포트폴리오는
    그 패널이 아니므로, 메커니즘 판정을 요청에 그대로 붙이면 **하지 않은
    이전(transfer)** 을 주장하게 된다 — 이 저장소가 금지하는 형태다.

    그래서 라벨은 "당신 포트폴리오가 검증됐다" 가 아니라 "당신이 방금 쓴
    메커니즘의 검증 상태는 이렇고, 당신 경우와는 이렇게 다르다" 라고 말한다.
    """
    req = as_identity(code_version)
    if manifest is None:
        return {
            "mechanism_verdict": VERDICT_NO_EVIDENCE, "passed": False,
            "why": [], "evidence_grade": None,
            "evidence_grade_reason": "판정 메니페스트가 없어 출처를 모릅니다",
            "adjudicated": None, "scope": {"mismatches": None},
            "this_request_verified": False,
            "code_version_matches": None,
            "code_version_method": req.method, "code_tree": req.tree,
            "reason": ("이 매크로 조건부 경로는 ★판정된 적이 없습니다★ — "
                       "미상은 통과가 아닙니다. 조건부 μ/Σ 가 적용됐다면 그것은 "
                       "예측력이 확인되어서가 아니라 계산이 가능해서입니다."),
        }

    adj = dict(manifest.get("adjudicated") or {})
    grade, grade_why = evidence_grade(adj.get("provenance"))
    mism = _mismatches(adj, universe=universe, months=months, model=model,
                       panel=panel)
    passed = bool(manifest.get("passed"))
    verified = bool(passed and manifest.get("verdict") == VERDICT_POSITIVE
                    and not mism)

    if verified:
        reason = None
    elif not passed:
        reason = (f"메커니즘 판정이 {manifest.get('verdict')!r} 입니다 — "
                  "이 경로는 관문을 통과한 적이 없습니다.")
    else:
        reason = ("판정은 통과했으나 ★이 요청은 판정된 대상이 아닙니다★: "
                  + " · ".join(mism))

    adj_ident = _manifest_identity(manifest)
    mv = manifest.get("code_version")
    return {
        "mechanism_verdict": manifest.get("verdict"), "passed": passed,
        "why": list(manifest.get("why") or []),
        "evidence_grade": grade, "evidence_grade_reason": grade_why,
        "adjudicated": {**adj, "code_version": mv,
                        "code_tree": adj_ident.tree,
                        "code_version_method": adj_ident.method,
                        "generated_at": manifest.get("generated_at")},
        "evidence": dict(manifest.get("evidence") or {}),
        "scope": {"mismatches": mism},
        "this_request_verified": verified,
        # ★노후화는 적되 막지 않는다★ 막는 것은 플래그의 몫이다.
        #
        # ★이 한 줄이 AM3 의 전부다★ 옛 구현은 `code_version == mv` 였는데,
        # 실측 결과 양쪽이 언제나 `"dev"`(701행) 여서 **항상 참**이었다 — 가드는
        # 있는데 도달할 수 없었다. AL 의 하드코딩 `0` 이 `coverage_complete` 를
        # 이긴 것과 같은 모양이다. 이제 판정은 세 상태다:
        #   True  — 양쪽이 진짜 버전이고 양쪽 트리가 깨끗하며 값이 같다
        #   False — 같은 조건에서 값이 다르다 (★진짜 노후화★)
        #   None  — 대답할 수 없다 (미상·더러운 트리·`"dev"`)
        "code_version_matches": versions_comparable(req, adj_ident),
        "code_version_method": req.method, "code_tree": req.tree,
        "reason": reason,
    }
