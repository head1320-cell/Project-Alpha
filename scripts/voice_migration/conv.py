"""해요체 → 합니다체 변환기 (ADR 005). ★주석 밖 글자만★ · 같은 규칙을 소스와 E2E 에 함께 건다.

쓰임:
  python conv.py table <폴더…>         어절 → 바뀐 꼴 표(검토용)
  python conv.py ctx <낱말> <폴더…>    그 낱말이 든 줄(주석 제외)
  python conv.py apply <폴더…>         고쳐 쓴다
  python conv.py left <폴더…>          남은 해요체 줄
"""
from __future__ import annotations
import pathlib, re, sys, collections, importlib.util
ROOT = pathlib.Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
HERE = pathlib.Path(__file__).parent

# ── 한글 자모 ──
def dec(ch):
    c = ord(ch) - 0xAC00
    return c // 588, (c % 588) // 28, c % 28
def com(cho, jung, jong=0): return chr(0xAC00 + cho * 588 + jung * 28 + jong)
J_B, J_L, J_SS = 17, 8, 20          # 받침 ㅂ ㄹ ㅆ
V = dict(A=0, AE=1, EO=4, E=5, YEO=6, YE=7, WA=9, WAE=10, WO=14, WE=15, U=13, I=20, EU=18)
def with_b(ch):
    a, b, _ = dec(ch); return com(a, b, J_B)

OVERRIDE: dict[str, str] = {}
MANUAL: list[tuple[re.Pattern, str]] = []
MANUAL_TS: list[tuple[re.Pattern, str]] = []
PAIRS: list[tuple[str, str]] = []
KEEP_NA = ("끝나요", "어긋나요", "일어나요", "나타나요", "드러나요", "늘어나요", "벗어나요", "지나요", "만나요")
def load_rules():
    import os
    p = HERE / os.environ.get("RULES", "rules.py")
    if p.exists():
        spec = importlib.util.spec_from_file_location("rules", p); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        OVERRIDE.update(getattr(m, "OVERRIDE", {}))
        for a, b in getattr(m, "PHRASES", []):
            MANUAL.append((re.compile(a), b))
        for a, b in getattr(m, "PHRASES_TS", []):
            MANUAL_TS.append((re.compile(a), b))
        PAIRS.extend(sorted(getattr(m, "PAIRS", []), key=lambda ab: -len(ab[0])))

EU_DROP = {"써": "씁", "커": "큽", "꺼": "끕", "떠": "뜹", "터": "틉"}

def conv_word(w: str) -> str | None:
    """해요체 어절 하나(…요) → 합니다체. 모르면 None."""
    for k in sorted(OVERRIDE, key=len, reverse=True):
        if w.endswith(k): return w[: -len(k)] + OVERRIDE[k]
    if w.endswith(("죠", "군요", "까요", "네요", "게요", "인가요", "건가요", "때요", "래요", "대요")): return None
    if w.endswith("나요") and not w.endswith(KEEP_NA): return None
    body = w[:-1]
    if not body: return None
    p, q = body[-1], (body[-2] if len(body) > 1 else "")
    head, head2 = body[:-1], body[:-2]
    cho, jung, jong = dec(p)
    if p == "세": return head + "십시오"
    if p == "에":
        if body.endswith("아니에"): return body[:-3] + "아닙니다"
        if q == "이": return head2 + "입니다"
        return None
    if p == "예": return head + "입니다"
    if p in ("어", "아"):
        if not q: return None
        _, _, qj = dec(q)
        if qj == J_L:
            a, b, _ = dec(q); return head2 + com(a, b, J_B) + "니다"
        if qj: return head2 + q + "습니다"
        return head2 + with_b(q) + "니다"
    if p == "해": return head + "합니다"
    if p == "돼": return head + "됩니다"
    if p == "봐": return head + "봅니다"
    if p == "와": return head + "옵니다"
    if p == "놔": return head + "놓습니다"
    if jong: return None
    if jung == V["YEO"]: return head + com(cho, V["I"], J_B) + "니다"
    if jung == V["WO"]: return head + com(cho, V["U"], J_B) + "니다"
    if p in ("라", "러") and q:
        a, b, qj = dec(q)
        if qj == J_L: return head2 + com(a, b) + "릅니다"
    if p in EU_DROP: return head + EU_DROP[p] + "니다"
    if jung in (V["A"], V["AE"], V["E"], V["EO"]): return head + with_b(p) + "니다"
    return None

import tests.test_frontend_voice as tv
YO = re.compile(r"([가-힣]+)(요|죠)(?![가-힣])")
def is_haeyo(m) -> bool:
    w = m.group(0)
    if m.group(2) == "죠" or w.endswith("군요"): return True
    return (not w.endswith("개요")) and tv._is_haeyo_stem(m.group(1)[-1])

def chunks(src: str):
    """(주석인가, 글자) 조각 — tests.test_frontend_claim_words.strip_comments 와 같은 판정."""
    out, buf, i, n, quote = [], [], 0, len(src), None
    def flush():
        if buf: out.append((False, "".join(buf))); buf.clear()
    while i < n:
        c = src[i]
        if quote:
            buf.append(c)
            if c == "\\" and i + 1 < n: buf.append(src[i + 1]); i += 2; continue
            if c == quote: quote = None
            i += 1; continue
        if c in "\"'`": quote = c; buf.append(c); i += 1; continue
        if src.startswith("//", i):
            j = src.find("\n", i); j = n if j < 0 else j
            flush(); out.append((True, src[i:j])); i = j; continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2); j = n if j < 0 else j + 2
            flush(); out.append((True, src[i:j])); i = j; continue
        buf.append(c); i += 1
    flush(); return out

def chunks_py(src: str):
    """파이썬: # 주석만 뺀다(문자열·독스트링은 글자다). 세 겹 따옴표를 안다."""
    out, buf, i, n, quote = [], [], 0, len(src), None
    def flush():
        if buf: out.append((False, "".join(buf))); buf.clear()
    while i < n:
        c = src[i]
        if quote:
            if c == "\\" and i + 1 < n: buf.append(src[i:i + 2]); i += 2; continue
            if src.startswith(quote, i): buf.append(quote); i += len(quote); quote = None; continue
            if len(quote) == 1 and c == "\n": quote = None
            buf.append(c); i += 1; continue
        if c in "\"'":
            quote = c * 3 if src.startswith(c * 3, i) else c
            buf.append(quote); i += len(quote); continue
        if c == "#":
            j = src.find("\n", i); j = n if j < 0 else j
            flush(); out.append((True, src[i:j])); i = j; continue
        buf.append(c); i += 1
    flush(); return out

def chunks_of(path, src):
    if path.suffix == ".py": return chunks_py(src)
    if path.suffix in (".ts", ".tsx"): return chunks(src)
    return [(False, src)]

def conv_text(t: str, stats=None, miss=None, ts=False, skip=()) -> str:
    """skip — E2E 단언을 맞출 때 쓰는 변형: "ts"(글자 전체 규칙) · "head"(글자 머리 규칙) · "phrases"(상태 문구 전부)."""
    for a, b in PAIRS: t = t.replace(a, b)
    if ts and "ts" not in skip:
        for pat, rep in MANUAL_TS: t = pat.sub(rep, t)
    if "phrases" not in skip:
        for pat, rep in MANUAL:
            if "head" in skip and "(?<=— )" in pat.pattern: continue
            t = pat.sub(rep, t)
    def f(m):
        if not is_haeyo(m): return m.group(0)
        w = m.group(0); r = conv_word(w)
        if r is None:
            if miss is not None: miss[w] += 1
            return w
        if stats is not None: stats[(w, r)] += 1
        return r
    return YO.sub(f, t)

def conv_src(src: str, stats=None, miss=None, path=None) -> str:
    ch = chunks_of(path, src) if path is not None else chunks(src)
    ts = path is None or path.suffix in (".ts", ".tsx")
    return "".join(t if is_c else conv_text(t, stats, miss, ts) for is_c, t in ch)

def body_of(p):
    return "".join("\n" * t.count("\n") if c else t for c, t in chunks_of(p, p.read_text()))

def files(args):
    for a in args:
        base = ROOT / a
        ps = [base] if base.is_file() else sorted(q for q in base.rglob("*") if q.is_file() and q.suffix in EXTS)
        for p in ps:
            if p.name.endswith(".d.ts") or SKIP & set(p.parts) or p.name in NOFILE: continue
            yield p

EXTS = {".ts", ".tsx", ".py", ".json", ".yaml", ".yml", ".jsonl", ".txt", ".csv", ".html", ".sql", ".toml"}
NOFILE = {"test_frontend_voice.py", "voice-audit.spec.ts", "test_frontend_claim_words.py",
          "constrained_opt.py"}       # 최적화기 원문은 파일 해시 골든(별도 승인 사항 — CLAUDE.md §3)
SKIP = {"node_modules", ".next", "__pycache__", ".git", "test-results", ".venv", "venv"}

def main():
    load_rules()
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "table":
        stats, miss = collections.Counter(), collections.Counter()
        for p in files(args): conv_src(p.read_text(), stats, miss, p)
        tails = collections.defaultdict(lambda: [0, set()])
        for (w, r), k in stats.items():
            # 바뀐 꼬리만 — 공통 머리를 뗀다
            i = 0
            while i < min(len(w), len(r)) and w[i] == r[i]: i += 1
            i = max(0, i - 1)
            key = f"{w[i:]}→{r[i:]}"; tails[key][0] += k; tails[key][1].add(w)
        print(f"바뀜 {sum(stats.values())}곳 · 꼬리 {len(tails)}종")
        print(" | ".join(f"{k}×{v[0]}" + (f"[{sorted(v[1])[0]}]" if len(k) < 9 else "") for k, v in sorted(tails.items(), key=lambda kv: -kv[1][0])))
        print(f"\n못 바꿈 {sum(miss.values())}곳:", " ".join(f"{w}×{k}" for w, k in miss.most_common()))
    elif cmd == "ctx":
        word, n = args[0], 0
        for p in files(args[1:]):
            for no, line in enumerate(body_of(p).split("\n"), 1):
                if re.search(word, line):
                    n += 1; print(f"{p.relative_to(ROOT).as_posix().replace('frontend/', '')}:{no}: {line.strip()[:200]}")
        print("줄", n)
    elif cmd == "apply":
        n = 0
        for p in files(args):
            a = p.read_text(); b = conv_src(a, path=p)
            if a != b: p.write_text(b); n += 1
        print("고친 파일", n)
    elif cmd == "left":
        n = 0
        for p in files(args):
            body = body_of(p).split("\n")
            for no, line in enumerate(body, 1):
                if any(is_haeyo(m) for m in YO.finditer(line)):
                    n += 1; print(f"{p.relative_to(ROOT).as_posix().replace('frontend/', '')}:{no}: {line.strip()[:200]}")
        print("남은 줄", n)

if __name__ == "__main__": main()
