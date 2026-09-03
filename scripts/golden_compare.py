"""골든 리포트 비교 — ★"달랐다" 로는 불변을 증명할 수 없다★
==============================================================================
사건: `docs/HISTORY.md` 2026-08-28 · 감사 `docs/specs/2026-08-26-data-extraction-audit.md`

## 왜 이 도구가 생겼나

`t3_geometry` 산출의 한 필드(`mdd_pct` −23.16 ↔ −23.17)가 **소스 변경 없이** 저장된
기준선과 달랐다. 원인 미상으로 감사 항목에 남아 있었고, 그동안 세 커밋이 "골든 3종
바이트 동일" 을 불변 증거로 썼다. 조사해서 원인을 찾았다:

    · 기준선 이후 계산 사슬을 건드린 커밋 **0건**(21커밋 전부 무편집)
    · 기준선 시점 커밋을 오늘 실행 → **오늘 HEAD 와 바이트 동일**
    · 같은 설정 4연속 실행 → md5 동일(완전 결정론)
    · ★`OPENBLAS_CORETYPE` 만 바꾸면 그 한 필드가 뒤집힌다★
      NEHALEM·SANDYBRIDGE·SKYLAKEX → 기준선과 차이 0 / HASWELL → 오늘 산출과 차이 0

numpy 가 싣는 OpenBLAS 는 `DYNAMIC_ARCH=1` 빌드라 **호스트 CPU 를 보고 런타임에
마이크로커널을 고른다**. 컨테이너가 다른 기계에 스케줄되면 합산 순서가 바뀌고,
그 차이가 넷째 유효숫자까지 올라온다.

★그러므로 "골든 바이트 동일" 은 코드의 성질이 아니다★ — 호스트의 성질이 섞여 있다.
같은 호스트에서 기준선과 대상을 **연달아** 뽑아 비교하면 유효하고, **저장해 둔**
기준선과 비교하는 순간 무효다. `diff` 는 그 둘을 구분해 주지 못한다.

## 세 판정 — ★"판정 불가" 를 "무해" 로 부르지 않는다★

    identical   구조·값 모두 동일                      → 종료 0
    last_place  인쇄된 마지막 자리 1단위 이내 차이뿐   → 종료 ★2★
    material    그보다 크거나 구조가 다름              → 종료 1

★`last_place` 는 "잡음이다" 가 아니다★ 리포트가 값을 반올림해 저장하므로 1e-12 의
진짜 변화도 반올림 경계에서는 마지막 자리를 뒤집는다. 이 리포트만으로는 **가를 수
없다**. 그래서 종료코드를 0 과 분리하고 출력이 **지문 대조를 요구**한다.

## 허용오차는 ★자릿수를 따라간다★

절대값 고정(예: 0.01)은 틀렸다 — `0.001` 규모의 값에서 10배 변화가 "잡음" 이 된다.
JSON 을 `Decimal` 로 파싱해 **인쇄된 자릿수**를 보존하고, 1단위를 거기서 유도한다.
★정수는 반올림이 없다★ — 정수 차이는 언제나 실질 차이다.

사용:
    python3 scripts/golden_compare.py BASE.json AFTER.json
    python3 scripts/golden_compare.py --fingerprint
"""

from __future__ import annotations

import argparse
import decimal
import json
import os
import sys

# ── 판정 ────────────────────────────────────────────────────────────────────
IDENTICAL = "identical"
LAST_PLACE = "last_place"
MATERIAL = "material"

#: ★`last_place` 가 0 이 되면 이 도구는 존재 이유가 없다★ 잡음일 **수도** 있는
#: 차이가 성공으로 새면, 그것을 걸러내려고 만든 판정이 스스로 무력해진다.
EXIT_IDENTICAL = 0
EXIT_MATERIAL = 1
EXIT_LAST_PLACE = 2

# ── 차이의 종류 ─────────────────────────────────────────────────────────────
KIND_ADDED = "added"
KIND_REMOVED = "removed"
KIND_TYPE = "type"
KIND_LENGTH = "length"
KIND_VALUE = "value"        # 비수치 값 차이
KIND_NUMERIC = "numeric"    # 수치 차이(자릿수 판정을 받는다)

_LAST_PLACE_NOTE = (
    "★이것은 '무해' 가 아니라 '이 리포트로는 가를 수 없다' 는 뜻입니다★ "
    "인쇄 자릿수 안에서만 다르므로 반올림 경계의 부동소수 차이일 수도, 실제 변화일 "
    "수도 있습니다. 아래 지문을 기준선의 지문과 대조하세요 — 기계가 다르면 "
    "OpenBLAS 가 다른 마이크로커널을 골랐을 수 있습니다(numpy 는 DYNAMIC_ARCH "
    "빌드를 싣습니다)."
)


def load(path: str):
    """JSON → 파이썬. ★float 를 `Decimal` 로 읽는다★

    `float` 로 읽으면 **인쇄된 자릿수가 사라진다**. `0.001` 과 `0.0010` 은 같은
    값이지만 **다른 정밀도로 보고된 값**이고, 허용오차는 그 정밀도에서 나온다.
    """
    with open(path, encoding="utf-8") as f:
        return json.load(f, parse_float=decimal.Decimal)


def _is_bool(v) -> bool:
    #: ★`bool` 은 `int` 의 하위형이다★ 먼저 걸러내지 않으면 `True` 와 `1` 이 같아진다.
    return isinstance(v, bool)


def _unit_of(*values: decimal.Decimal) -> decimal.Decimal:
    """인쇄된 **마지막 자리 1단위**. 정밀도가 다르면 ★더 엄격한 쪽★을 쓴다.

    정밀도가 다르다는 것 자체가 리포트가 달라졌다는 신호라, 느슨한 쪽을 고르면
    그 신호까지 잡음으로 흡수된다.
    """
    exps = [v.as_tuple().exponent for v in values]
    exps = [e for e in exps if isinstance(e, int)]      # 'n'/'N'/'F' 는 특수값
    if not exps:
        return decimal.Decimal(0)
    return decimal.Decimal(1).scaleb(min(exps))


def _diff(path, kind, base, after, severity, **extra) -> dict:
    d = {"path": path, "kind": kind, "severity": severity,
         "base": _plain(base), "after": _plain(after)}
    d.update(extra)
    return d


def _plain(v):
    """`Decimal` 을 JSON 으로 낼 수 있게 — ★문자열로 낸다★ float 로 바꾸면 자릿수가 또 사라진다."""
    return str(v) if isinstance(v, decimal.Decimal) else v


def _walk(base, after, path: str, out: list) -> None:
    """구조를 **끝까지** 내려간다. 얕게 훑으면 깊은 차이를 놓친다."""
    if _is_bool(base) != _is_bool(after) or type(base) is not type(after):
        # ★타입이 다르면 값 비교는 의미가 없다★ `1` 과 `"1"` 은 다른 사실이다.
        if not (isinstance(base, decimal.Decimal) and isinstance(after, decimal.Decimal)):
            out.append(_diff(path, KIND_TYPE, base, after, MATERIAL))
            return

    if isinstance(base, dict):
        for k in base:
            sub = f"{path}.{k}" if path else str(k)
            if k not in after:
                out.append(_diff(sub, KIND_REMOVED, base[k], None, MATERIAL))
            else:
                _walk(base[k], after[k], sub, out)
        for k in after:
            if k not in base:
                sub = f"{path}.{k}" if path else str(k)
                out.append(_diff(sub, KIND_ADDED, None, after[k], MATERIAL))
        return

    if isinstance(base, list):
        if len(base) != len(after):
            out.append(_diff(path, KIND_LENGTH, len(base), len(after), MATERIAL))
            return
        for i, (b, a) in enumerate(zip(base, after, strict=True)):
            _walk(b, a, f"{path}[{i}]", out)
        return

    if isinstance(base, decimal.Decimal) and isinstance(after, decimal.Decimal):
        if base == after:
            return
        unit = _unit_of(base, after)
        delta = abs(base - after)
        severity = LAST_PLACE if unit > 0 and delta <= unit else MATERIAL
        out.append(_diff(path, KIND_NUMERIC, base, after, severity,
                         delta=str(delta), unit=str(unit)))
        return

    # ★정수·문자열·불리언·None 은 반올림이 없다★ 다르면 실질 차이다.
    if base != after:
        out.append(_diff(path, KIND_VALUE, base, after, MATERIAL))


#: ★실험을 정의하는 필드★ 여기가 다르면 코드가 아니라 **다른 실험**을 비교한 것이다.
#:
#: 이 도구를 만들자마자 실제로 걸렸다 — 저장된 `t3_bl_ep` 기준선은 `--conf 25` 로
#: 뽑혔는데 재생성은 기본값(분해 Ω, conf≈1.111)이었고, 40개 필드가 전부 크게
#: 달랐다. `conf` 한 줄이 그 40줄에 묻히면 **회귀로 오독된다.**
#:
#: ★이 목록은 **강조**만 바꾼다★ 비우거나 틀려도 판정은 여전히 `material` 이고
#: 종료코드도 1 이다 — 가드의 이빨이 손 목록에 걸려 있지 않다.
RUN_DEFINING = frozenset({
    "conf", "months", "arch", "engine", "seed", "evidence_grade", "real_share",
})


def _leaf(path: str) -> str:
    return path.rsplit(".", 1)[-1].split("[", 1)[0]


def compare(base, after) -> dict:
    diffs: list[dict] = []
    _walk(base, after, "", diffs)
    if any(d["severity"] == MATERIAL for d in diffs):
        verdict = MATERIAL
    elif diffs:
        verdict = LAST_PLACE
    else:
        verdict = IDENTICAL
    setup = [d for d in diffs if _leaf(d["path"]) in RUN_DEFINING]
    return {"verdict": verdict, "diffs": diffs, "setup_diffs": setup}


def compare_files(base_path: str, after_path: str) -> dict:
    return compare(load(base_path), load(after_path))


# ── 지문 ────────────────────────────────────────────────────────────────────
#: ★기계에 관한 것이지 자격증명이 아니다★ 환경 전체를 실으면 API 키가 그대로 샌다
#: (CLAUDE.md §6). 그래서 **이름을 명시한 하나**만 읽는다.
_ENV_KEYS = ("OPENBLAS_CORETYPE",)


def _cpu() -> dict:
    model, flags = None, []
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if model is None and line.startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                elif not flags and line.startswith("flags"):
                    have = set(line.split(":", 1)[1].split())
                    flags = [x for x in ("fma", "avx", "avx2", "avx512f") if x in have]
                if model and flags:
                    break
    except OSError:
        pass
    return {"model": model, "flags": flags}


def fingerprint() -> dict:
    """이 기계가 무엇인가 — `last_place` 가 나왔을 때 대조할 것."""
    out: dict = {"python": sys.version.split()[0], "cpu": _cpu()}
    for name in ("numpy", "scipy", "pandas"):
        try:
            out[name] = __import__(name).__version__
        except Exception:  # noqa: BLE001 — 없으면 없다고 적는다
            out[name] = None
    out["openblas_coretype"] = os.getenv(_ENV_KEYS[0]) or None
    return out


# ── CLI ─────────────────────────────────────────────────────────────────────
def _render(res: dict) -> str:
    lines = [f"판정: {res['verdict']}"]
    if res["setup_diffs"]:
        # ★먼저, 따로 낸다★ 설정 차이가 값 차이 40줄 속에 묻히면 회귀로 오독된다.
        lines.append("★설정이 다릅니다 — 코드가 아니라 **다른 실험**을 비교하고 "
                     "있을 수 있습니다★")
        for d in res["setup_diffs"]:
            lines.append(f"  · {d['path']}: {d['base']} → {d['after']}")
        lines.append("")
    for d in res["diffs"][:40]:
        if d["kind"] == KIND_NUMERIC:
            lines.append(f"  [{d['severity']}] {d['path']}: {d['base']} → {d['after']} "
                         f"(차이 {d['delta']}, 마지막 자리 {d['unit']})")
        else:
            lines.append(f"  [{d['severity']}] {d['path']} ({d['kind']}): "
                         f"{d['base']} → {d['after']}")
    if len(res["diffs"]) > 40:
        lines.append(f"  … 외 {len(res['diffs']) - 40}건")
    if res["verdict"] == LAST_PLACE:
        lines.append("")
        lines.append(_LAST_PLACE_NOTE)
        # ★마지막 줄은 **순수 JSON 지문**이다★ 읽는 사람도 스크립트도 그대로 집어
        # 기준선의 지문과 대조할 수 있어야 한다 — 설명문 안에 묻으면 못 쓴다.
        lines.append("이 실행의 지문(마지막 줄):")
        lines.append(json.dumps(fingerprint(), ensure_ascii=False))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="골든 리포트 비교 — identical(0) / last_place(2) / material(1)")
    ap.add_argument("base", nargs="?", help="기준선 JSON")
    ap.add_argument("after", nargs="?", help="대상 JSON")
    ap.add_argument("--fingerprint", action="store_true",
                    help="이 기계의 지문만 출력하고 끝낸다")
    ap.add_argument("--json", action="store_true", help="결과를 JSON 으로")
    args = ap.parse_args()

    if args.fingerprint:
        print(json.dumps(fingerprint(), ensure_ascii=False, indent=2))
        return EXIT_IDENTICAL
    if not args.base or not args.after:
        ap.error("BASE 와 AFTER 를 둘 다 주거나 --fingerprint 를 쓰세요")

    try:
        res = compare_files(args.base, args.after)
    except (OSError, json.JSONDecodeError, decimal.InvalidOperation) as e:
        # ★조용히 성공하지 않는다★ 읽지 못한 것은 "같다" 가 아니다.
        print(f"판정: {MATERIAL} — 파일을 읽지 못했습니다: {e}", file=sys.stderr)
        print(f"읽지 못한 파일이 있습니다: {args.base} / {args.after}")
        return EXIT_MATERIAL

    print(json.dumps(res, ensure_ascii=False, indent=2) if args.json else _render(res))
    return {IDENTICAL: EXIT_IDENTICAL, LAST_PLACE: EXIT_LAST_PLACE,
            MATERIAL: EXIT_MATERIAL}[res["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
