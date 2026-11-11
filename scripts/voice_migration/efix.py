"""E2E 단언 맞추기 — Playwright 줄 보고서의 "Expected substring / Received string" 을 읽어, 변환기의 다른 변형 가운데
★실제 화면 글(Received)에 든 것★으로 단언을 고친다.  사용: python efix.py <e2e 로그> [--apply]

왜: 글자 전체가 그 꼴일 때만 명사형으로 바꾸는 규칙("X가 없어요" → "X 없음")은, 단언이 문장의 조각만 적어 둔 자리에서 화면과 어긋난다
(화면은 "…X가 없습니다 — …"). 어느 쪽이 맞는지는 화면이 말한다.
"""
from __future__ import annotations
import importlib.util, os, pathlib, re, subprocess, sys

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parents[1]

def load(rules: str):
    os.environ["RULES"] = rules
    spec = importlib.util.spec_from_file_location(f"conv_{rules}", HERE / "conv.py"); m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m); m.load_rules(); return m

A, B = load("rules.py"), load("vocab.py")
BASE = os.environ.get("BASE", "HEAD")      # 옮기기 전 커밋
MODES = ((), ("ts",), ("ts", "head"), ("ts", "phrases"), ("head",), ("phrases",))

def variants(quoted: str) -> list[str]:
    out = []
    for skip in MODES:
        t = A.conv_text(A.conv_text(quoted, ts=True, skip=skip), ts=True, skip=skip)
        t = B.conv_text(B.conv_text(t, ts=True), ts=True)
        if t not in out: out.append(t)
    return out

LIT = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|`((?:[^`\\]|\\.)*)`')
norm = lambda s: re.sub(r"\s+", " ", s)

def main():
    log = pathlib.Path(sys.argv[1]).read_text(errors="replace"); apply = "--apply" in sys.argv
    blocks = re.split(r"\n(?=  \d+\) \[chromium\])", log)
    fixed = skipped = 0; edits: dict[pathlib.Path, list[tuple[int, str, str]]] = {}
    for b in blocks[1:]:
        if "Retry #" in b.split("\n", 1)[0]: continue
        exp = re.search(r'Expected (?:sub)?string:\s+"(.*)"', b); rec = re.search(r'Received string:\s+"(.*)"', b)
        at = re.search(r"at (/[^\s:]+/e2e/[^\s:]+):(\d+):\d+\s*$", b, re.M)
        head = b.split("\n", 1)[0][:110]
        if not (exp and rec and at): skipped += 1; print("손으로:", head); continue
        x, y = exp.group(1), norm(rec.group(1)); path, line = pathlib.Path(at.group(1)), int(at.group(2))
        rel = path.relative_to(ROOT).as_posix()
        old = subprocess.run(["git", "show", f"{BASE}:{rel}"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
        cur = path.read_text().split("\n")
        if line > len(old) or line > len(cur): skipped += 1; print("줄 없음:", head); continue
        hit = None
        for ln in range(max(0, line - 4), min(len(old), line + 3)):        # 여러 줄에 걸친 단언
            for m in LIT.finditer(old[ln]):
                q = m.group(0); vs = variants(q)
                if not vs or vs[0][1:-1] != x and x not in vs[0]: continue
                extra = [q[0] + "미상" + q[-1]] if vs[0][1:-1] == "N/A" else []      # 값 자리가 아니라 문장 속 "…는 미상입니다"
                for v in vs[1:] + extra:
                    if norm(v[1:-1]) in y and vs[0] in cur[ln]: hit = (ln, vs[0], v); break
                if hit: break
            if hit: break
        if not hit: skipped += 1; print("못 맞춤:", head, "| 기대:", x[:60]); continue
        edits.setdefault(path, []).append(hit); fixed += 1
        print(f"맞춤: {rel}:{hit[0] + 1}  {hit[1][:60]}  →  {hit[2][:60]}")
    if apply:
        for path, es in edits.items():
            cur = path.read_text().split("\n")
            for ln, a, v in es: cur[ln] = cur[ln].replace(a, v)
            path.write_text("\n".join(cur))
    print(f"맞춤 {fixed} · 손으로 {skipped}" + (" · 적용함" if apply else " · (미적용 — --apply)"))

if __name__ == "__main__": main()
