"""말로 설계(AI4) — 말씀 한 문장 → 지금 캔버스를 고치는 초안(더하기 · 잇기 · 값 넣기). ★Claude 는 값을 쓰지 않는다★.
==============================================================================
스펙 §AI4 · 사용자 결정(2026-10-23): 지금 캔버스를 고치기 · 검사된 조작 목록 · 모자라면 비워 두고 말하기.
- 조작: `add{ref, kind}` · `connect{from, from_port, to, to_port}`(ref 또는 지금 노드 id) · `set{node, field, quote, how, choice, names}`.
  `set` 에 값 칸이 없다 — `quote` 는 말씀에서 그대로 옮긴 조각, `how` 는 읽는 법:
  프리셋 라벨(`choice`) · 옵션 값(`choice`) — 둘 다 그 칸의 닫힌 집합 · 숫자(서버가 `quote` 에서 하나를 읽는다) · 종목(`names` — 종목표 정확 일치).
- `speakable(schema)` — 칸마다 읽는 법. 근거(Claude 가 보는 표)와 검사가 같은 표를 쓴다. 불리언·글·고르기·필터·목록·칸별 값은 말로 넣지 않는다(설정 탭).
- `check` — 순서대로 붙이며 하나씩 검사하고, 탈락은 사유와 함께 돌려준다: 더하기(카탈로그·이름표) → 잇기(붙인 문서를 `/validate` 해
  ★새 오류 키★가 없어야 — AI1 과 같은 판정) → 값(읽기 규칙 · 칸 형식). 빠진 더하기에 매달린 잇기·값은 함께 탈락.
  남은 빈 입력·필수 칸은 `empty`(사람 말). 이해 못 함·투자 판단은 서버 고정 문장(`CANNOT`) — 초안 0.

한계(적어 둠): 숫자는 아라비아 숫자만 읽는다("세 종목"의 '세'는 아니다) · 만·억 같은 큰 단위와 음수는 읽지 않고 탈락시킨다 ·
종목은 종목표의 이름 정확 일치나 6자리 코드만(별칭·부분 일치 없음 — 여러 개 맞으면 후보를 말한다).
"""
from __future__ import annotations

import copy
import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from src.services.canvas_assist.check import BANNED, _key
from src.services.canvas_assist.ground import _NUM, numbers_of

MAX_SENTENCE = 300
MAX_ADD = 8
MAX_CONNECT = 12
MAX_SET = 12
MAX_SUMMARY = 80
MAX_QUOTE = 120
MAX_NAMES = 30
HOWS = ("preset", "option", "number", "tickers")
WHY_NOT = ("none", "off_topic", "judgement")
CANNOT = {"off_topic": "포트폴리오 설계에 대해 말해 주세요",
          "judgement": "어떤 종목이 좋을지는 말하지 않아요 — 말씀대로 설계만 지어요"}

TOP_KEYS = frozenset({"understood", "why_not", "summary", "add", "connect", "set"})
ADD_KEYS = frozenset({"ref", "kind"})
CONNECT_KEYS = frozenset({"from", "from_port", "to", "to_port"})
SET_KEYS = frozenset({"node", "field", "quote", "how", "choice", "names"})

#: 숫자 바로 뒤의 단위 낱말 → 칸 단위(`x-ui.unit`). 긴 낱말부터 맞춘다('개월' 이 '개' 보다 먼저, '달러' 가 '달' 보다 먼저).
_UNITS = {"%p": ("%p", "%포인트", "퍼센트포인트"), "%": ("%", "퍼센트", "프로"), "bp": ("bps", "bp", "베이시스포인트"),
          "거래일": ("거래일",), "영업일": ("영업일",), "일": ("일",), "개월": ("개월", "달"), "년": ("년",),
          "원": ("원",), "개": ("개",), "점": ("점",), "달러": ("달러",)}
UNIT_WORDS = sorted(((w.lower(), u) for u, ws in _UNITS.items() for w in ws), key=lambda x: -len(x[0]))
MAGNITUDE = ("백", "천", "만", "억", "조")
_NOT_SPOKEN = frozenset({"per_port", "per_port_number", "pick", "filter", "text", "string_list"})
_PLAIN = {"type_mismatch": "포트 타입이 달라요", "multiple_inputs": "받는 자리에 이미 선이 있어요",
          "unknown_port": "카탈로그에 없는 포트예요", "dangling_edge": "그래프에 없는 노드를 가리켜요",
          "cycle": "이으면 순환이 생겨요", "needs_unmet": "이대로 계산하면 실패할 선이에요"}


class _Reject(Exception):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code, self.reason = code, reason


def norm(text: str) -> str:
    """공백 정규화 — 말씀과 조각을 같은 잣대로 비교한다."""
    return re.sub(r"\s+", " ", text or "").strip()


def _types(p: dict) -> set[str]:
    return {q["type"] for q in [p, *(p.get("anyOf") or [])] if isinstance(q, dict) and isinstance(q.get("type"), str)}


def speakable(schema: dict | None) -> dict[str, dict]:
    """칸 이름 → `{label, read[], presets[], values{라벨: 값}, options{값: 라벨}, unit, integer}` — 말로 읽을 수 있는 칸만."""
    out: dict[str, dict] = {}
    for name, p in ((schema or {}).get("properties") or {}).items():
        if not isinstance(p, dict):
            continue
        ui = p.get("x-ui") or {}
        widget = ui.get("widget")
        if widget in _NOT_SPOKEN:
            continue
        ts = _types(p)
        scalar = not ts & {"array", "object"}
        presets = [x for x in ui.get("presets") or [] if isinstance(x, dict) and isinstance(x.get("label"), str)]
        enum = p.get("enum") or next((q.get("enum") for q in p.get("anyOf") or [] if isinstance(q, dict) and q.get("enum")), None)
        options = ({str(k): str(v) for k, v in ui["options"].items()} if isinstance(ui.get("options"), dict)
                   else {str(v): str(v) for v in enum} if enum else {})
        e: dict[str, Any] = {"label": ui.get("label") or name, "read": []}
        if presets:
            e["read"].append("preset")
            e["presets"] = [x["label"] for x in presets]
            e["values"] = {x["label"]: x.get("value") for x in presets}
        if options and scalar and widget != "tickers":
            e["read"].append("option")
            e["options"] = options
        if ts & {"number", "integer"} and scalar:
            e["read"].append("number")
            e["unit"] = ui.get("unit")
            e["integer"] = "integer" in ts and "number" not in ts
        if widget == "tickers":
            e["read"].append("tickers")
        if e["read"]:
            out[name] = e
    return out


def _public(sp: dict) -> dict:
    """Claude 에게 보이는 칸 설명 — 프리셋의 값(숫자)은 싣지 않는다(라벨만 고른다)."""
    return {k: sp[k] for k in ("label", "read", "presets", "options", "unit") if k in sp}


def ground(graph: dict, sentence: str, kinds: dict[str, dict], report: dict) -> dict:
    """말씀 · 지금 구조(노드 id·종류·이름 · 선) · 절차 · 종류별 포트와 말로 넣을 수 있는 칸. ★지금 설정값은 싣지 않는다★."""
    proc = report.get("procedure") or {}
    nodes = [n for n in graph.get("nodes") or [] if isinstance(n, dict)]
    return {
        "sentence": norm(sentence),
        "graph": {"nodes": [{"id": n.get("id"), "type": n.get("type"),
                             "label": (kinds.get(str(n.get("type"))) or {}).get("plain_label") or n.get("type")} for n in nodes],
                  "edges": [{k: e.get(k) for k in ("source", "source_port", "target", "target_port")}
                            for e in graph.get("edges") or [] if isinstance(e, dict)]},
        "procedure": {"steps": [{k: s.get(k) for k in ("key", "label", "need", "state", "node_ids", "text")}
                                for s in proc.get("steps") or []],
                      "next": proc.get("next")},
        "kinds": {t: {"label": k["plain_label"], "stage": k["stage"],
                      "inputs": [{"name": i["name"], "type": i["type"], "required": i["required"]} for i in k["inputs"]],
                      "outputs": [{"name": o["name"], "type": o["type"]} for o in k["outputs"]],
                      "fields": {f: _public(sp) for f, sp in speakable(k.get("params_schema")).items()}}
                  for t, k in kinds.items()},
    }


# ── 읽기 규칙 ─────────────────────────────────────────────────────────────────

def _read_choice(sp: dict, how: str, quote: str, choice: str) -> tuple[Any, str]:
    flabel = sp["label"]
    if how == "preset":
        if choice not in sp["presets"]:
            raise _Reject("preset", f"‘{flabel}’ 칸에 없는 프리셋이에요 — ‘{choice}’")
        value, shown = sp["values"][choice], choice
    else:
        if choice not in sp["options"]:
            raise _Reject("option", f"‘{flabel}’ 칸에 없는 선택지예요 — ‘{choice}’")
        value, shown = choice, sp["options"][choice]
    if not numbers_of(shown) <= numbers_of(quote):        # "2년"이라 했는데 "3년" — 말에 없는 숫자를 고르지 않는다
        raise _Reject("numbers", f"말씀 ‘{quote}’에 없는 숫자예요 — ‘{shown}’")
    return copy.deepcopy(value), shown


def _read_number(sp: dict, quote: str) -> tuple[Any, str]:
    found = list(_NUM.finditer(quote))
    if len(found) != 1:
        raise _Reject("number_count", f"말씀 ‘{quote}’에서 숫자 하나를 읽지 못했어요")
    m = found[0]
    if quote[:m.start()].rstrip().endswith(("-", "−", "마이너스")):
        raise _Reject("negative", "음수는 말로 넣지 않아요 — 설정 탭에서 넣어 주세요")
    rest = quote[m.end():].lstrip()
    if rest.startswith(MAGNITUDE):
        raise _Reject("unit", f"‘{quote}’ — 만·억 같은 큰 단위는 숫자로 적어 주세요")
    said = next((u for w, u in UNIT_WORDS if rest.lower().startswith(w)), None)
    if said is not None and said != sp.get("unit"):
        raise _Reject("unit", f"‘{quote}’의 단위가 ‘{sp['label']}’ 칸의 단위({sp.get('unit') or '단위 없음'})와 달라요")
    d = Decimal(m.group().replace(",", ""))
    whole = d == d.to_integral_value()
    if sp.get("integer") and not whole:
        raise _Reject("integer", f"‘{sp['label']}’ 칸은 정수만 받아요 — ‘{quote}’")
    return (int(d) if whole else float(d)), quote


def _read_tickers(names: list[str], quote: str, resolve: Callable[[str], dict]) -> tuple[list[str], str, list[tuple[str, str]]]:
    codes: list[str] = []
    shown: list[str] = []
    bad: list[tuple[str, str]] = []
    for raw in names:
        nm = raw.strip()
        if not nm:
            continue
        if nm.lower() not in quote.lower():
            bad.append(("ticker_quote", f"말씀 조각에 없는 종목 이름이에요 — ‘{nm}’"))
            continue
        r = resolve(nm) or {}
        if isinstance(r.get("code"), str) and r["code"]:
            if r["code"] not in codes:
                codes.append(r["code"])
                shown.append(str(r.get("name") or r["code"]))
        elif r.get("candidates"):
            bad.append(("ticker_ambiguous", f"여러 종목이 맞아요 — ‘{nm}’: "
                                            f"{' · '.join(str(c.get('name')) for c in r['candidates'][:3])}. 이름을 정확히 말해 주세요"))
        else:
            bad.append(("ticker_unknown", f"종목표에서 찾지 못했어요 — ‘{nm}’"))
    return codes, " · ".join(shown), bad


# ── 검사 ─────────────────────────────────────────────────────────────────────

def _rej(op: str, code: str, reason: str) -> dict:
    return {"op": op, "code": code, "reason": reason}


def _empty_draft() -> dict:
    return {"summary": None, "add": [], "connect": [], "set": [], "empty": []}


def _strs(it: Any, keys: frozenset, *, allow_blank: tuple[str, ...] = ()) -> bool:
    return (isinstance(it, dict) and set(it) == keys
            and all(isinstance(it[k], str) and (k in allow_blank or it[k].strip()) for k in keys if k != "names"))


def check(raw: Any, g: dict, graph: dict, kinds: dict[str, dict], validate: Callable[[Any], dict],
          field_errors: Callable[[str, dict], set], resolve_ticker: Callable[[str], dict]) -> dict:
    """`{understood, cannot, draft{summary, add, connect, set, empty}, rejected[{op, code, reason}]}`."""
    draft = _empty_draft()
    bad: list[dict] = []
    res = {"understood": True, "cannot": None, "draft": draft, "rejected": bad}
    if (not isinstance(raw, dict) or set(raw) != TOP_KEYS or not isinstance(raw.get("understood"), bool)
            or not all(isinstance(raw.get(k), list) for k in ("add", "connect", "set"))):
        bad.append(_rej("draft", "shape", "답의 형식이 맞지 않아요"))
        return res
    if not raw["understood"]:
        res["understood"] = False
        res["cannot"] = CANNOT["judgement" if raw.get("why_not") == "judgement" else "off_topic"]
        return res

    doc = {**graph, "nodes": copy.deepcopy([n for n in graph["nodes"] if isinstance(n, dict)]), "edges": list(graph["edges"])}
    existing = {str(n.get("id")): n for n in doc["nodes"]}
    ids = set(existing)
    refs: dict[str, dict] = {}
    failed: dict[str, str] = {}

    def label(n: dict) -> str:
        return (kinds.get(str(n.get("type"))) or {}).get("plain_label") or str(n.get("type"))

    def node_of(name: str) -> dict:
        if name in refs:
            return refs[name]
        if name in failed:
            raise _Reject("depends", f"앞의 더하기(‘{failed[name]}’)가 빠져서 함께 뺐어요")
        if name in existing:
            return existing[name]
        raise _Reject("no_node", f"그래프에 없는 노드예요 — ‘{name}’")

    # ① 더하기
    for it in raw["add"]:
        if not _strs(it, ADD_KEYS):
            bad.append(_rej("add", "shape", "더하기의 형식이 맞지 않아요"))
            continue
        ref, kind = it["ref"], it["kind"]
        kl = (kinds.get(kind) or {}).get("plain_label") or kind
        if len(draft["add"]) >= MAX_ADD:
            failed.setdefault(ref, kl)
            bad.append(_rej("add", "limit", f"더하기는 {MAX_ADD}개까지예요"))
        elif kind not in kinds:
            failed.setdefault(ref, kl)
            bad.append(_rej("add", "unknown_kind", f"카탈로그에 없는 종류예요 — ‘{kind}’"))
        elif ref in existing or ref in refs:
            failed.setdefault(ref, kl)
            bad.append(_rej("add", "ref", f"이름표가 겹쳐요 — ‘{ref}’"))
        else:
            nid, i = kind, 2
            while nid in ids:
                nid, i = f"{kind}_w{i}", i + 1
            ids.add(nid)
            node = {"id": nid, "type": kind, "params": {}}
            doc["nodes"].append(node)
            refs[ref] = node
            draft["add"].append({"ref": ref, "id": nid, "kind": kind, "label": kl})

    # ② 잇기 — 하나씩 붙여 ★새 오류 키★가 없을 때만
    keys = {_key(e) for e in validate(doc)["errors"]}
    for it in raw["connect"]:
        if not _strs(it, CONNECT_KEYS):
            bad.append(_rej("connect", "shape", "잇기의 형식이 맞지 않아요"))
            continue
        if len(draft["connect"]) >= MAX_CONNECT:
            bad.append(_rej("connect", "limit", f"잇기는 {MAX_CONNECT}개까지예요"))
            continue
        try:
            s, t = node_of(it["from"]), node_of(it["to"])
        except _Reject as r:
            bad.append(_rej("connect", r.code, r.reason))
            continue
        edge = {"id": f"{s['id']}.{it['from_port']}->{t['id']}.{it['to_port']}", "source": s["id"], "source_port": it["from_port"],
                "target": t["id"], "target_port": it["to_port"]}
        if any(isinstance(e, dict) and all(e.get(k) == edge[k] for k in ("source", "source_port", "target", "target_port"))
               for e in doc["edges"]):
            bad.append(_rej("connect", "duplicate", f"이미 있는 선이에요 — ‘{label(s)}’ → ‘{label(t)}’"))
            continue
        trial = {**doc, "edges": [*doc["edges"], edge]}
        errs = validate(trial)["errors"]
        new = [e for e in errs if _key(e) not in keys]
        if new:
            code = str(new[0].get("code") or "connection")
            bad.append(_rej("connect", code, f"‘{label(s)}’ → ‘{label(t)}’ 선: {_PLAIN.get(code, '잇는 선이 맞지 않아요')}"))
            continue
        doc, keys = trial, {_key(e) for e in errs}
        draft["connect"].append(edge)

    # ③ 값 — 서버가 말씀 조각에서 읽는다
    done: set[tuple[str, str]] = set()
    for it in raw["set"]:
        if not _strs(it, SET_KEYS, allow_blank=("choice",)) or not isinstance(it["names"], list) \
                or not all(isinstance(x, str) for x in it["names"]):
            extra = ", ".join(sorted(map(str, set(it) - SET_KEYS))) if isinstance(it, dict) else ""
            bad.append(_rej("set", "shape", "값 넣기의 형식이 맞지 않아요" + (f"(모르는 칸: {extra})" if extra else "")))
            continue
        how, choice, names = it["how"], it["choice"].strip(), it["names"]
        if how not in HOWS or (how in ("number", "tickers") and choice) or (how != "tickers" and names):
            bad.append(_rej("set", "shape", "읽는 법과 고른 것이 맞지 않아요"))
            continue
        if len(draft["set"]) >= MAX_SET:
            bad.append(_rej("set", "limit", f"값 넣기는 {MAX_SET}개까지예요"))
            continue
        try:
            node = node_of(it["node"])
            kind, field = str(node.get("type")), it["field"]
            schema = (kinds.get(kind) or {}).get("params_schema") or {}
            if field not in (schema.get("properties") or {}):
                raise _Reject("no_field", f"‘{label(node)}’ 노드에 없는 칸이에요 — ‘{field}’")
            sp = speakable(schema).get(field)
            if sp is None:
                flabel = ((schema["properties"][field].get("x-ui") or {}).get("label") or field)
                raise _Reject("not_speakable", f"‘{label(node)}’의 ‘{flabel}’ 칸은 말로 넣을 수 없어요 — 설정 탭에서 넣어 주세요")
            if (node["id"], field) in done:
                raise _Reject("duplicate", f"‘{sp['label']}’ 칸은 앞에서 이미 넣었어요")
            if how not in sp["read"]:
                raise _Reject("how", f"‘{sp['label']}’ 칸은 그렇게 읽을 수 없어요")
            quote = norm(it["quote"])
            if not quote or len(quote) > MAX_QUOTE or quote not in g["sentence"]:
                raise _Reject("quote", f"말씀에 없는 말이에요 — ‘{quote}’")
            extra_bad: list[tuple[str, str]] = []
            if how in ("preset", "option"):
                value, shown = _read_choice(sp, how, quote, choice)
            elif how == "number":
                value, shown = _read_number(sp, quote)
            else:
                if not names or len(names) > MAX_NAMES:
                    raise _Reject("tickers", f"종목 이름은 1~{MAX_NAMES}개예요")
                value, shown, extra_bad = _read_tickers(names, quote, resolve_ticker)
                bad.extend(_rej("set", c, r) for c, r in extra_bad)
                if not value:
                    continue
            after = {**(node.get("params") or {}), field: value}
            before_errs = {e for e in field_errors(kind, node.get("params") or {}) if e[0] == field}
            if {e for e in field_errors(kind, after) if e[0] == field} - before_errs:
                raise _Reject("bad_value", f"‘{sp['label']}’ 칸에 맞지 않는 값이에요(범위·형식) — ‘{shown}’")
        except _Reject as r:
            bad.append(_rej("set", r.code, r.reason))
            continue
        node["params"] = after
        done.add((node["id"], field))
        draft["set"].append({"node": node["id"], "field": field, "label": sp["label"], "value": value, "display": shown,
                             "quote": quote, "read": how})

    # ④ 요약 — 숫자는 말씀에 있는 것만 · 금지 표현 0
    summ = raw.get("summary")
    if isinstance(summ, str) and summ.strip():
        s = summ.strip()
        word = next((w for w in BANNED if w in s), None)
        extra = numbers_of(s) - numbers_of(g["sentence"])
        if len(s) > MAX_SUMMARY:
            bad.append(_rej("summary", "too_long", f"요약이 {MAX_SUMMARY}자를 넘어요"))
        elif word:
            bad.append(_rej("summary", "banned", f"요약에 쓰지 않는 표현이 있어요 — ‘{word}’"))
        elif extra:
            bad.append(_rej("summary", "numbers", f"요약에 말씀에 없는 숫자가 있어요 — {', '.join(sorted(extra))}"))
        else:
            draft["summary"] = s

    # ⑤ 비어 있는 것 — 새 노드에 남은 빈 입력·필수 칸(지어내지 않는다 — 사람이 채운다)
    new_ids = {a["id"] for a in draft["add"]}
    for e in validate(doc)["errors"]:
        if e.get("code") == "missing_input" and e.get("node_id") in new_ids:
            n = next(x for x in doc["nodes"] if x["id"] == e["node_id"])
            draft["empty"].append({"node": n["id"], "port": e.get("port"),
                                   "why": e.get("fix") or f"‘{label(n)}’의 입력 ‘{e.get('port')}’이 비어 있어요"})
    for n in doc["nodes"]:
        if n["id"] not in new_ids:
            continue
        props = ((kinds.get(n["type"]) or {}).get("params_schema") or {}).get("properties") or {}
        for f, kind_of_error in sorted(field_errors(n["type"], n.get("params") or {})):
            if kind_of_error == "missing":
                fl = ((props.get(f) or {}).get("x-ui") or {}).get("label") or f
                draft["empty"].append({"node": n["id"], "field": f, "why": f"‘{label(n)}’의 ‘{fl}’ 칸이 비어 있어요 — 말씀에 없어요"})
    return res
