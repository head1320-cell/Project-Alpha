"""설계 절차 — ★그래프가 스스로 절차를 말한다★ (BT1, 순수)
==============================================================================
스펙 `docs/superpowers/specs/2026-09-30-bt-canvas-procedure-node-link-design.md` §1

캔버스의 "절차 탭"·"다음 한 걸음"·관문 알약의 `[붙이기]` 가 읽는 서버 판정이다. 절차는 따로 있는 마법사가
아니라 **지금 그래프에서 읽어 낸다**:

- `steps` — 여섯 단계(데이터 · 신호 · 생각 · 비중 · 확인 · 실행)가 채워졌는지. 필수·권장·선택을 가른다.
- `next` — 다음에 붙일 것 **하나**. 빠진 **단계**만 제안하고 설정값은 추천하지 않는다(BM 기각: 자동 스윕·
  "가장 좋은" 고르기). 문장은 "잴 수 있게 돼요"까지만 쓴다 — 붙인다고 관문을 통과하는 것이 아니다.
- `by_gate` — 관문마다 그것을 잴 수 있게 하는 한 걸음(없으면 `None` + 사유).
- `unmet_needs` — 타입은 맞지만 받는 쪽이 요구하는 값(`needs`)을 보내는 쪽이 **확실히** 주지 않는 선.
  계산할 때 실패할 것을 편집하는 순간 말한다. 확실하지 않으면(조건부) 말하지 않는다.

입력은 노드·선·카탈로그 모양의 종류 표·단계 목록·포트 쉬운 이름뿐이다. ★DB·설정·네트워크를 읽지 않는다★
(AST 테스트). 노드 종류 이름을 아는 것은 규칙 2~5 의 제안 대상(종목 고르기·수익률·비중 계산·과거로 돌려
보기·흔들림 나눠 보기)뿐이고, 카탈로그에 없으면 그 규칙은 건너뛴다.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

REQUIRED, RECOMMENDED, OPTIONAL = "required", "recommended", "optional"
FILLED, PARTIAL, EMPTY, BLOCKED = "filled", "partial", "empty", "blocked"

#: 단계 → 필요 정도. 확인하기는 권장 — 과거로 돌려 봐야 거래비용·처음 보는 기간을 잴 수 있다.
NEED = {"data": REQUIRED, "signal": OPTIONAL, "belief": OPTIONAL, "build": REQUIRED,
        "check": RECOMMENDED, "act": OPTIONAL}
#: 단계 → 그 단계의 노드가 재는 관문(`workflow_gates.GATES` 키). 생각 정하기·실행은 관문을 확인하지 않는다.
FEEDS = {"data": ["data", "pit"], "signal": ["signal"], "belief": [], "build": ["build"],
         "check": ["cost", "oos"], "act": []}
#: 포트 타입 → 먼저 제안할 생산 노드(카탈로그에 있을 때만). 없으면 단계 순서로 첫 생산자.
PREFERRED = {"Universe": "universe", "Returns": "returns", "Belief": "estimate", "Weights": "optimizer"}

NEW = "@new"
YES, MAYBE, NO = "yes", "maybe", "no"


# ── 한국어 조사 ──────────────────────────────────────────────────────────────

def _has_final(word: str) -> bool:
    for ch in reversed(word):
        if "가" <= ch <= "힣":
            return (ord(ch) - 0xAC00) % 28 != 0
        if ch.isalnum():
            return ch in "013678LMNlmn"
    return False


def _obj(word: str) -> str:
    return f"‘{word}’{'을' if _has_final(word) else '를'}"


def _subj(word: str) -> str:
    return f"‘{word}’{'이' if _has_final(word) else '가'}"


# ── 그래프 읽기 ──────────────────────────────────────────────────────────────

def _index(nodes: Sequence[Mapping], edges: Sequence[Mapping], kinds: Mapping[str, Mapping]):
    known = [n for n in nodes if isinstance(n, Mapping) and n.get("id") and n.get("type") in kinds]
    by_id = {str(n["id"]): n for n in known}
    incoming: dict[str, dict[str, tuple[str, str]]] = {nid: {} for nid in by_id}
    out_adj: dict[str, set[str]] = {nid: set() for nid in by_id}
    for e in edges:
        if not isinstance(e, Mapping):
            continue
        s, sp, t, tp = (str(e.get(k) or "") for k in ("source", "source_port", "target", "target_port"))
        if s in by_id and t in by_id:
            incoming[t].setdefault(tp, (s, sp))
            out_adj[s].add(t)
    return by_id, incoming, out_adj


def _descendants(start: str, out_adj: Mapping[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        for t in out_adj.get(stack.pop(), ()):
            if t not in seen:
                seen.add(t)
                stack.append(t)
    return seen


def _kind(kinds: Mapping[str, Mapping], node: Mapping) -> Mapping:
    return kinds[str(node["type"])]


def _label(kinds: Mapping[str, Mapping], kind: str) -> str:
    k = kinds.get(kind) or {}
    return str(k.get("plain_label") or k.get("label") or kind)


def _missing_inputs(node: Mapping, kind: Mapping, incoming: Mapping[str, Mapping]) -> list[Mapping]:
    got = incoming.get(str(node["id"]), {})
    return [p for p in kind.get("inputs") or [] if p.get("required", True) and p["name"] not in got]


# ── 값 공급 (needs · gives) ─────────────────────────────────────────────────

def supply(key: str, node_id: str, port: str, by_id: Mapping, incoming: Mapping, kinds: Mapping,
           _seen: frozenset = frozenset()) -> str:
    """노드 `node_id` 의 출력 `port` 가 값 `key` 를 주는가 — `yes` · `maybe` · `no`.

    출력 포트의 `gives` 는 세 모양이다: `{key}`(늘) · `{key, when}`(입력 `when` 이 이어졌을 때 **줄 수도**
    있다 — 데이터·설정에 따라) · `{key, from}`(입력 `from` 이 받은 값을 넘긴다).
    """
    if node_id in _seen or node_id not in by_id:
        return MAYBE          # 모르면 말하지 않는다(확실하지 않은 것을 실패로 부르지 않는다)
    out = next((o for o in _kind(kinds, by_id[node_id]).get("outputs") or [] if o["name"] == port), None)
    if out is None:
        return MAYBE
    best = NO
    for g in out.get("gives") or []:
        if g.get("key") != key:
            continue
        if g.get("from"):
            src = incoming.get(node_id, {}).get(g["from"])
            st = supply(key, src[0], src[1], by_id, incoming, kinds, _seen | {node_id}) if src else NO
        elif g.get("when"):
            st = MAYBE if g["when"] in incoming.get(node_id, {}) else NO
        else:
            st = YES
        if st == YES:
            return YES
        if st == MAYBE:
            best = MAYBE
    return best


def unmet_needs(nodes: Sequence[Mapping], edges: Sequence[Mapping], kinds: Mapping[str, Mapping]) -> list[dict]:
    """받는 쪽 `needs` 를 보내는 쪽이 **확실히** 주지 않는 선 — `[{source, source_port, target, target_port, key}]`."""
    by_id, incoming, _ = _index(nodes, edges, kinds)
    out = []
    for tid, ports in incoming.items():
        kind = _kind(kinds, by_id[tid])
        for p in kind.get("inputs") or []:
            src = ports.get(p["name"])
            if not src:
                continue
            for key in p.get("needs") or []:
                if supply(key, src[0], src[1], by_id, incoming, kinds) == NO:
                    out.append({"source": src[0], "source_port": src[1], "target": tid,
                                "target_port": p["name"], "key": key})
    return out


# ── 제안 ─────────────────────────────────────────────────────────────────────

def _suggest(action: str, kind: str | None, text: str, attach: list[dict], unlocks: list[str],
             kinds: Mapping) -> dict:
    return {"action": action, "kind": kind, "label": _label(kinds, kind) if kind else None,
            "text": text, "attach": attach, "unlocks": unlocks}


def _producer(kinds: Mapping[str, Mapping], port_type: str, stage_order: list[str]) -> str | None:
    pref = PREFERRED.get(port_type)
    if pref in kinds and any(o["type"] == port_type for o in kinds[pref].get("outputs") or []):
        return pref
    cands = [t for t, k in kinds.items() if any(o["type"] == port_type for o in k.get("outputs") or [])]
    rank = {s: i for i, s in enumerate(stage_order)}
    return min(cands, key=lambda t: (rank.get(kinds[t].get("stage"), 99), list(kinds).index(t)), default=None)


def _first(by_id: Mapping, kind: str) -> str | None:
    return next((nid for nid, n in by_id.items() if n["type"] == kind), None)


def _out_port(kinds: Mapping, kind: str, port_type: str) -> str | None:
    return next((o["name"] for o in kinds.get(kind, {}).get("outputs") or [] if o["type"] == port_type), None)


def _in_port(kinds: Mapping, kind: str, port_type: str) -> str | None:
    return next((i["name"] for i in kinds.get(kind, {}).get("inputs") or [] if i["type"] == port_type), None)


def _returns_feeding(nid: str, by_id: Mapping, incoming: Mapping, kinds: Mapping) -> str | None:
    port = _in_port(kinds, str(by_id[nid]["type"]), "Returns")
    src = incoming.get(nid, {}).get(port) if port else None
    return src[0] if src else _first(by_id, "returns")


def _rule_missing_input(by_id, incoming, out_adj, kinds, stage_order, port_plain) -> dict | None:
    for nid, node in by_id.items():
        kind = _kind(kinds, node)
        for p in _missing_inputs(node, kind, incoming):
            what = port_plain.get(p["type"], p["name"])
            me = _label(kinds, str(node["type"]))
            banned = _descendants(nid, out_adj) | {nid}
            existing = next(((sid, o["name"]) for sid, sn in by_id.items() if sid not in banned
                             for o in _kind(kinds, sn).get("outputs") or [] if o["type"] == p["type"]), None)
            if existing:
                src_label = _label(kinds, str(by_id[existing[0]]["type"]))
                return _suggest("connect", None,
                                f"{_subj(me)} 받을 {_obj(what)} 아직 잇지 않았어요 — {_subj(src_label)} 내는 "
                                f"{_obj(what)} 이을까요?",
                                [{"source": existing[0], "source_port": existing[1],
                                  "target": nid, "target_port": p["name"]}], [], kinds)
            prod = _producer(kinds, p["type"], stage_order)
            if prod is None:
                continue
            out = _out_port(kinds, prod, p["type"])
            return _suggest("add", prod,
                            f"{_subj(me)} 받을 {_obj(what)} 내는 노드가 없어요 — "
                            f"{_obj(_label(kinds, prod))} 붙여 이을까요?",
                            [{"source": NEW, "source_port": out, "target": nid, "target_port": p["name"]}],
                            [], kinds)
    return None


def _add_returns(by_id, kinds) -> dict | None:
    if "returns" not in kinds:
        return None
    uni = _first(by_id, "universe")
    if uni is None:
        if "universe" not in kinds:
            return None
        return _suggest("add", "universe",
                        f"먼저 {_obj(_label(kinds, 'universe'))} 붙여 무엇을 볼지 정해요. 그다음 수익률을 불러오면 "
                        "데이터·시점 관문을 잴 수 있게 돼요.", [], [], kinds)
    return _suggest("add", "returns",
                    f"{_obj(_label(kinds, 'returns'))} 붙이면 데이터·시점 관문을 잴 수 있게 돼요.",
                    [{"source": uni, "source_port": _out_port(kinds, "universe", "Universe"),
                      "target": NEW, "target_port": _in_port(kinds, "returns", "Universe")}],
                    ["data", "pit"], kinds)


def _add_optimizer(by_id, kinds) -> dict | None:
    if "optimizer" not in kinds:
        return None
    ret = _first(by_id, "returns")
    attach = ([{"source": ret, "source_port": _out_port(kinds, "returns", "Returns"),
                "target": NEW, "target_port": _in_port(kinds, "optimizer", "Returns")}] if ret else [])
    return _suggest("add", "optimizer",
                    f"비중을 정하는 단계가 없어요 — {_obj(_label(kinds, 'optimizer'))} 붙이면 비중 관문을 잴 수 "
                    "있게 돼요.", attach, ["build"], kinds)


def _add_backtest(by_id, incoming, kinds) -> dict | None:
    opt = _first(by_id, "optimizer")
    if opt is None or "backtest" not in kinds:
        return None
    ret = _returns_feeding(opt, by_id, incoming, kinds)
    attach = [{"source": opt, "source_port": _out_port(kinds, "optimizer", "Weights"),
               "target": NEW, "target_port": _in_port(kinds, "backtest", "Weights")}]
    if ret:
        attach.append({"source": ret, "source_port": _out_port(kinds, "returns", "Returns"),
                       "target": NEW, "target_port": _in_port(kinds, "backtest", "Returns")})
    return _suggest("add", "backtest",
                    f"거래비용과 처음 보는 기간을 아직 재지 않았어요 — ‘{_label(kinds, 'optimizer')}’ 뒤에 "
                    f"{_obj(_label(kinds, 'backtest'))} 붙이면 잴 수 있게 돼요.", attach, ["cost", "oos"], kinds)


def _add_risk(by_id, incoming, kinds) -> dict | None:
    if "risk" not in kinds:
        return None
    port = _in_port(kinds, "risk", "Weights")
    need = next((i.get("needs") or [] for i in kinds["risk"].get("inputs") or [] if i["name"] == port), [])
    for nid, node in by_id.items():
        out = _out_port(kinds, str(node["type"]), "Weights")
        if out and all(supply(k, nid, out, by_id, incoming, kinds) != NO for k in need):
            return _suggest("add", "risk",
                            f"확인하는 단계가 없어요 — {_subj(_label(kinds, str(node['type'])))} 낸 비중에 "
                            f"{_obj(_label(kinds, 'risk'))} 붙여 어느 종목이 흔들림을 만드는지 봐요.",
                            [{"source": nid, "source_port": out, "target": NEW, "target_port": port}], [], kinds)
    return None


# ── 단계 ─────────────────────────────────────────────────────────────────────

def _kind_stage(kinds: Mapping[str, Mapping], kind: str) -> str | None:
    return (kinds.get(kind) or {}).get("stage")


def _step_text(state: str, need: str, labels: list[str]) -> str:
    if state == FILLED:
        head = " · ".join(f"‘{x}’" for x in labels[:2])
        return head + (f" 외 {len(labels) - 2}개" if len(labels) > 2 else "")
    if state == BLOCKED:
        return f"{_subj(labels[0])} 받을 입력이 아직 이어지지 않았어요."
    if need == REQUIRED:
        return "아직 없어요 — 꼭 있어야 해요."
    if need == RECOMMENDED:
        return "아직 없어요 — 있으면 거래비용·처음 보는 기간을 잴 수 있어요."
    return "없어도 돼요."


def evaluate(nodes: Sequence[Mapping], edges: Sequence[Mapping], kinds: Mapping[str, Mapping],
             stages: Sequence[Mapping], port_plain: Mapping[str, str]) -> dict:
    """그래프 → `{steps[6], next, by_gate}`."""
    by_id, incoming, out_adj = _index(nodes, edges, kinds)
    stage_order = [str(s["key"]) for s in stages]
    types = {str(n["type"]) for n in by_id.values()}
    present = {str(_kind(kinds, n).get("stage")) for n in by_id.values()}

    by_gate: dict[str, dict | None] = {
        "data": _add_returns(by_id, kinds) if "returns" not in types else None,
        "pit": _add_returns(by_id, kinds) if "returns" not in types else None,
        "signal": None,
        "build": _add_optimizer(by_id, kinds) if "build" not in present else None,
        "cost": _add_backtest(by_id, incoming, kinds) if "backtest" not in types else None,
        "oos": _add_backtest(by_id, incoming, kinds) if "backtest" not in types else None,
        "economic": None,
        "live": None,
    }

    steps = []
    for s in stages:
        key = str(s["key"])
        mine = [nid for nid, n in by_id.items() if _kind(kinds, n).get("stage") == key]
        blocked = [nid for nid in mine if _missing_inputs(by_id[nid], _kind(kinds, by_id[nid]), incoming)]
        labels = [_label(kinds, str(by_id[nid]["type"])) for nid in (blocked or mine)]
        need = NEED.get(key, OPTIONAL)
        # ★일부★ 노드는 있는데 이 단계가 재는 관문을 아직 잴 수 없다(예: 종목만 있고 수익률이 없다) — 채움이라 부르지 않는다.
        gap = next((by_gate[g] for g in FEEDS.get(key, []) if by_gate.get(g)
                    and (not by_gate[g]["kind"] or _kind_stage(kinds, by_gate[g]["kind"]) == key)), None)
        state = BLOCKED if blocked else (PARTIAL if gap else FILLED) if mine else EMPTY
        text = _step_text(state, need, labels) if state != PARTIAL else \
            _step_text(FILLED, need, labels) + " — " + gap["text"]
        steps.append({"key": key, "label": s.get("label", key), "need": need, "state": state,
                      "node_ids": mine, "feeds_gates": FEEDS.get(key, []), "text": text})

    has_stage = {st["key"] for st in steps if st["state"] != EMPTY}
    # ★규칙 순서가 판정이다★ — 앞 규칙이 이긴다.
    nxt = (_rule_missing_input(by_id, incoming, out_adj, kinds, stage_order, port_plain)
           or (_add_returns(by_id, kinds) if "returns" not in types else None)
           or (_add_optimizer(by_id, kinds) if "build" not in has_stage else None)
           or (_add_backtest(by_id, incoming, kinds) if "backtest" not in types else None)
           or (_add_risk(by_id, incoming, kinds) if "check" not in has_stage else None))

    return {"steps": steps, "next": nxt, "by_gate": by_gate,
            "done_text": None if nxt else "절차를 다 채웠어요 — 계산해 보세요."}


#: 다른 모듈이 같은 조사 규칙을 쓰도록(‘수익률’을 · ‘비중’을).
quote_obj = _obj


def kinds_from_catalog(catalog: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """카탈로그 목록 → 종류 표(편의)."""
    return {str(c["type"]): c for c in catalog}
