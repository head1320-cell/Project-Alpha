"use client";
/**
 * 저장된 것에서 고르기 (BK W5) — 등록된 전략 · 연구 기록
 * ==========================================================================
 * 서버 x-ui `widget: "pick"` 의 `source` 이름으로 **기존 문**을 부른다(주소를 여기 새로 적지 않는다 —
 * `multibacktestApi.strategies` · `researchApi.list`). ★세 상태를 섞지 않는다★ 불러오는 중 · 저장소를 못 읽음
 * (사유) · 정말 없음(무엇을 하면 생기는지)은 서로 다른 문장이다. 고른 값이 목록에 없으면 지우지 않고 그대로 보인다.
 */
import { useEffect, useState } from "react";
import { multibacktestApi } from "@/entities/multibacktest";
import { researchApi } from "@/entities/research";

type Item = { value: string | number; label: string; sub?: string; chips: { text: string; tone: "assumed" | "unknown" }[] };
type State = { kind: "loading" } | { kind: "error"; text: string } | { kind: "ready"; items: Item[] };

const EMPTY: Record<string, string> = {
  strategies: "등록된 전략이 없어요 — 백테스트 결과를 전략으로 등록하면 여기에 나와요.",
  research_runs: "연구 기록이 없어요 — 비중 계산 결과를 연구 기록으로 남기면 여기에 나와요.",
};

async function load(source: string): Promise<Item[]> {
  if (source === "strategies") {
    return (await multibacktestApi.strategies()).map((s) => ({
      value: s.id, label: s.name, sub: `전략 ${s.id}`,
      chips: [
        ...(s.is_mock_data === true ? [{ text: "연습용 데이터", tone: "unknown" as const }] : []),
        ...(s.is_mock_data === null ? [{ text: "데이터 출처 미상", tone: "unknown" as const }] : []),
        ...(s.is_pit_verified !== true ? [{ text: "시점 정합 미확인", tone: "assumed" as const }] : []),
      ],
    }));
  }
  if (source === "research_runs") {
    const res = await researchApi.list(undefined, 50);
    if (!res.available) throw new Error(res.reason ?? "연구 기록 저장소를 읽지 못했어요.");
    return res.runs.map((r) => ({
      value: r.run_id, label: r.name || r.kind,
      sub: `${new Date(r.created_at * 1000).toLocaleDateString("ko-KR")} · ${r.kind}`,
      chips: r.snapshot?.coverage?.source === "mock" ? [{ text: "연습용 데이터", tone: "unknown" as const }] : [],
    }));
  }
  throw new Error(`이 화면이 모르는 목록이에요(${source}) — 전문가 설정에서 직접 넣어 주세요.`);
}

export function PickField({ source, multi, value, onChange }: {
  source: string; multi: boolean; value: unknown; onChange: (v: unknown) => void;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    let live = true;
    setState({ kind: "loading" });
    load(source).then((items) => { if (live) setState({ kind: "ready", items }); })
      .catch((e: Error) => { if (live) setState({ kind: "error", text: e.message }); });
    return () => { live = false; };
  }, [source, nonce]);

  const picked: (string | number)[] = multi ? (Array.isArray(value) ? value : []) : value == null ? [] : [value as string];
  const toggle = (v: string | number) => {
    if (!multi) { onChange(v); return; }
    const next = picked.includes(v) ? picked.filter((x) => x !== v) : [...picked, v];
    onChange(next.length ? next : undefined);
  };

  if (state.kind === "loading") return <p className="pg-help" role="status">목록을 불러오는 중이에요.</p>;
  if (state.kind === "error") {
    return (
      <div className="pg-pick-err">
        <p className="pg-field-err">목록을 불러오지 못했어요 — {state.text}</p>
        <button type="button" className="pg-add" onClick={() => setNonce((n) => n + 1)}>다시 불러오기</button>
      </div>
    );
  }
  const known = new Set(state.items.map((i) => i.value));
  const orphans = picked.filter((v) => !known.has(v));
  return (
    <div className="pg-pick" role={multi ? "group" : "radiogroup"}>
      {state.items.length === 0 && <p className="pg-help">{EMPTY[source] ?? "고를 것이 없어요."}</p>}
      {state.items.map((it) => {
        const on = picked.includes(it.value);
        return (
          <button key={String(it.value)} type="button" role={multi ? "checkbox" : "radio"} aria-checked={on}
                  className={`pg-pick-row${on ? " on" : ""}`} onClick={() => toggle(it.value)}>
            <span className="pg-pick-box" aria-hidden="true" />
            <span className="pg-pick-main"><b>{it.label}</b>{it.sub && <span className="pg-pick-sub">{it.sub}</span>}</span>
            {it.chips.map((c) => <span key={c.text} className={`pg-tag pg-tag--${c.tone}`}>{c.text}</span>)}
          </button>
        );
      })}
      {orphans.length > 0 && (
        <p className="pg-warn">목록에 없는 값을 골라 두었어요: {orphans.join(", ")} — 지워졌거나 비활성일 수 있어요.</p>
      )}
    </div>
  );
}
