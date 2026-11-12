"""화면 문자열 목록 — 남은 쉬운 표현을 찾고, 치환 뒤 어긋난 곳을 긴 실행 전에 싸게 찾는다 (읽기 전용 · 파일을 고치지 않는다).

  python scripts/voice_migration/inventory.py list <영역> [표지…]     표지 낱말이 든 화면 문자열(파일:줄 · 문자열)
  python scripts/voice_migration/inventory.py count                    영역별 개수 · 표지별 개수
  python scripts/voice_migration/inventory.py remnants <규칙 파일>     따옴표 쌍의 키가 따옴표 없이(JSX 글자·정규식·문장 속) 남은 곳
  python scripts/voice_migration/inventory.py asserts <규칙 파일>      pytest·E2E 가 옛 조각을 아직 단언하는 곳

영역: canvas-server · canvas-front · front-other · server-other · all
"화면 문자열" = `.py` 는 docstring 이 아닌 문자열 상수(ast) · `.ts/.tsx` 는 주석을 걷은 줄. 주석·docstring 은 문체 대상이 아니다(용어집 머리말).
★⑤의 교훈 셋★ ① 칸 이름을 따옴표째로만 바꾸면 `<summary>이름</summary>` · `/^이름$/` 에 옛 이름이 남는다 → `remnants`.
② 시험은 문장 전체가 아니라 조각("몫" · "끝을 맞춰")을 단언한다 → `asserts`. ③ 둘 다 20분·60분짜리 실행 전에 본다.
"""
from __future__ import annotations

import ast
import collections
import importlib.util
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).parent
HANGUL = re.compile("[가-힣]")

#: 쉬운 풀이의 표지 — 낱말 자체가 틀린 것은 아니다. 이 낱말이 든 문자열을 사람이 읽고 가른다(중립 합니다체 문장은 남긴다).
MARKERS = [
    "알려 주", "봤습니다", "봅니다", "매겼", "매깁니다", "골랐", "고릅니다", "잡았", "잡기로", "나눴", "나눕니다", "합쳤", "합칩니다", "넣어 봤", "넣었", "넣습니다",
    "돌려 봤", "돌렸", "돌려 볼", "돌립니다", "같이 무너", "같이 움직", "같이 떨어", "같이 잃", "되짚", "치우침", "쏠림", "평소", "똑같이", "나란히",
    "이으면", "이어야", "잇습니다", "이은 ", "이어 ", "적었", "적습니다", "적지 않", "적으면", "쟀", "잽니다", "잰 ", "재지 ", "잴 ", "재려", "얼마나", "틀려", "틀렸",
    "이랬", "버틴", "버팀", "겨우", "크게 잃", "모았", "기울", "묶어", "묶은", "넘깁니다", "들고 ", "맡길", "몰릴", "어땠", "어떤지", "먼지 ", "싼지", "비싼",
    "오르면", "내리면", "오를", "내릴", "버는", "벌", "불러왔", "불러옵니다", "살 ", "팔 ", "팝니다", "삽니다", "사고팔", "사기", "팔기", "밀리면", "무리", "고르기",
    "얼마로", "언제부터", "어디서", "무엇을", "왜 ", "그대로 두", "따로 ", "함께 ", "덜 ", "더 ", "많이 ", "조금 ", "아주 ", "쓸 수", "볼 수", "줍니다", "드립니다",
]


def py_strings(path: pathlib.Path) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    docs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docs.add(id(first.value))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and HANGUL.search(n.value)]


def ts_strings(path: pathlib.Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    out = []
    for i, line in enumerate(text.split("\n"), 1):
        line = re.sub(r"(^|[^:\"'`])//.*$", r"\1", line)
        if HANGUL.search(line):
            out.append((i, line.strip()))
    return out


def strings(path: pathlib.Path) -> list[tuple[int, str]]:
    if path.suffix == ".py":
        return py_strings(path)
    if path.suffix in (".ts", ".tsx"):
        return ts_strings(path)
    return []


def files(*dirs: str) -> list[pathlib.Path]:
    out = []
    for d in dirs:
        base = ROOT / d
        ps = [base] if base.is_file() else sorted(base.rglob("*"))
        out += [p for p in ps if p.is_file() and p.suffix in (".py", ".ts", ".tsx") and "__pycache__" not in p.parts and "node_modules" not in p.parts]
    return out


def area_files(area: str) -> list[pathlib.Path]:
    canvas_srv = [p for p in files("src/api") if p.name.startswith("allocation_graph")]
    canvas_ui = files("frontend/src/widgets/portfolio-graph", "frontend/src/entities/portfolio-graph")
    if area == "canvas-server":
        return canvas_srv
    if area == "canvas-front":
        return canvas_ui
    if area == "front-other":
        return [p for p in files("frontend/src") if p not in set(canvas_ui)]
    if area == "server-other":
        return [p for p in files("src") if p not in set(canvas_srv) and p.name != "constrained_opt.py"]
    if area == "all":
        return area_files("canvas-server") + area_files("canvas-front") + area_files("front-other") + area_files("server-other")
    raise SystemExit(f"모르는 영역: {area}")


def hits(area: str, markers: list[str]) -> list[tuple[pathlib.Path, int, str, list[str]]]:
    out = []
    for p in area_files(area):
        for ln, s in strings(p):
            h = [m for m in markers if m in s]
            if h:
                out.append((p, ln, s, h))
    return out


def load(rules: str):
    spec = importlib.util.spec_from_file_location(f"rules_{rules}", HERE / rules)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def quoted_keys(m) -> dict[str, str]:
    """따옴표 한 쌍으로 감싼 쌍(`'"이름"'` → `'"새 이름"'`)의 속 글자."""
    return {a[1:-1]: b[1:-1] for a, b in m.PAIRS if len(a) > 2 and a[0] == a[-1] == '"' and a.count('"') == 2 and b[:1] == '"' and b[-1:] == '"'}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "list":
        area = args[0] if args else "all"
        markers = args[1:] or MARKERS
        last = None
        for p, ln, s, _h in hits(area, markers):
            rel = p.relative_to(ROOT).as_posix()
            if rel != last:
                print(f"\n## {rel}")
                last = rel
            print(f"{ln}: {' '.join(s.split())}")
    elif cmd == "count":
        tally = collections.Counter()
        for area in ("canvas-server", "canvas-front", "front-other", "server-other"):
            rows = hits(area, MARKERS)
            print(f"{area}: {len(rows)} 문자열 · {len({r[0] for r in rows})} 파일")
            tally.update(m for r in rows for m in r[3])
        print(" ".join(f"{k.strip()}×{v}" for k, v in tally.most_common()))
    elif cmd == "remnants":
        keys = quoted_keys(load(args[0]))
        n = 0
        for p in files("frontend/src", "src", "frontend/e2e"):
            for ln, s in strings(p):
                for k, v in keys.items():
                    if k in s and f'"{k}"' not in s:
                        n += 1
                        print(f"{p.relative_to(ROOT).as_posix()}:{ln}: [{k} → {v}] {' '.join(s.split())[:150]}")
        print(f"잔여 {n}곳")
    elif cmd == "asserts":
        m = load(args[0])
        olds = sorted({a for a, _b in m.PAIRS if HANGUL.search(a)}, key=len, reverse=True)
        # 옛 문장에서 조사·구두점으로 끊은 조각(네 글자 이상) — 시험은 대개 이런 조각을 단언한다
        frags = collections.defaultdict(set)
        for a, b in m.PAIRS:
            for f in re.findall(r"[가-힣][가-힣 ]{3,}[가-힣]", a):
                if f not in b:
                    frags[f].add(a)
        n = 0
        for p in files("tests", "frontend/e2e"):
            if p.name in ("test_frontend_voice.py", "voice-audit.spec.ts", "test_frontend_claim_words.py"):
                continue
            for ln, s in strings(p):
                if not re.search(r"assert|expect|toHave|toContain|hasText|includes|startswith| in ", s) and p.suffix != ".py":
                    continue
                for f in frags:
                    if f in s:
                        n += 1
                        print(f"{p.relative_to(ROOT).as_posix()}:{ln}: [{f}] {' '.join(s.split())[:150]}")
                        break
        print(f"옛 조각 단언 {n}곳 · 규칙의 옛 문장 {len(olds)}개")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
