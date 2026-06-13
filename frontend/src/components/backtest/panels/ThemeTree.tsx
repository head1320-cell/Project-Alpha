"use client";
// 젠포트 17그룹 → 88 세부업종 트리 (매매 대상 설정 미러) — 접이식 그룹 + 세부 체크박스.
// 선택된 세부업종은 'theme:세부' id로 universe.sectors 에 들어가 select_universe 가 해석.
// 구조는 백엔드 /theme-tree (젠포트 화면 전사), 종목 매핑은 best-effort 추론 시드.

import { useEffect, useState } from "react";
import { Check, ChevronDown, ChevronRight } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
const R = "var(--bs-border-radius)";

interface Sub { id: string; label: string; size: number }
interface Group { id: string; label: string; subsectors: Sub[] }

export default function ThemeTree({ selected, onChange }: {
  selected: string[];                       // universe.sectors 중 theme: 항목 포함
  onChange: (next: string[]) => void;        // theme: 항목만 갱신 (plain sector는 보존)
}) {
  const [groups, setGroups] = useState<Group[]>([]);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [note, setNote] = useState<string>("");
  const [seeded, setSeeded] = useState<{ subs: number; stocks: number } | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/screener/theme-tree`).then((r) => r.json()).then((d) => {
      setGroups(d.groups ?? []);
      setNote(d.note ?? "");
      setSeeded({ subs: d.seeded_subsectors ?? 0, stocks: d.seeded_stocks ?? 0 });
    }).catch(() => {});
  }, []);

  const selSet = new Set(selected.filter((s) => s.startsWith("theme:")));
  const plain = selected.filter((s) => !s.startsWith("theme:"));
  const emit = (next: Set<string>) => onChange([...plain, ...Array.from(next)]);

  const toggleSub = (id: string) => {
    const n = new Set(selSet);
    if (n.has(id)) n.delete(id); else n.add(id);
    emit(n);
  };
  const toggleGroup = (g: Group) => {
    const ids = g.subsectors.map((s) => s.id);
    const allOn = ids.every((i) => selSet.has(i));
    const n = new Set(selSet);
    ids.forEach((i) => (allOn ? n.delete(i) : n.add(i)));
    emit(n);
  };
  const toggleOpen = (gid: string) =>
    setOpen((o) => { const n = new Set(o); n.has(gid) ? n.delete(gid) : n.add(gid); return n; });

  const totalSubSelected = selSet.size;
  const allIds = groups.flatMap((g) => g.subsectors.map((s) => s.id));
  const allOn = allIds.length > 0 && allIds.every((i) => selSet.has(i));

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 9 }}>
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
          업종 (88){totalSubSelected > 0 ? ` · ${totalSubSelected} 선택` : ""}
        </span>
        <button type="button" onClick={() => emit(allOn ? new Set() : new Set(allIds))}
          style={{ fontSize: 11, color: "var(--text-secondary)", background: "none", border: "none", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 2 }}>
          <Check size={12} /> {allOn ? "전체 해제" : "전체 선택"}
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 7 }}>
        {groups.map((g) => {
          const ids = g.subsectors.map((s) => s.id);
          const grpAll = ids.every((i) => selSet.has(i));
          const grpSome = !grpAll && ids.some((i) => selSet.has(i));
          const isOpen = open.has(g.id);
          return (
            <div key={g.id} style={{ border: "1px solid var(--border)", borderRadius: R, overflow: "hidden", alignSelf: "start" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 10px", background: "var(--bg-section)" }}>
                <button type="button" onClick={() => toggleGroup(g)} aria-label="그룹 전체"
                  style={{ width: 15, height: 15, borderRadius: 3, flexShrink: 0, display: "inline-flex", alignItems: "center", justifyContent: "center", border: "1px solid var(--border-strong)", cursor: "pointer", background: grpAll ? "var(--bs-primary, #1200ff)" : grpSome ? "var(--bg-card)" : "transparent" }}>
                  {grpAll && <Check size={11} style={{ color: "#fff" }} />}
                  {grpSome && <span style={{ width: 7, height: 2, background: "var(--bs-primary, #1200ff)" }} />}
                </button>
                <button type="button" onClick={() => toggleOpen(g.id)}
                  style={{ flex: 1, display: "flex", alignItems: "center", gap: 4, background: "none", border: "none", cursor: "pointer", textAlign: "left", fontSize: 13, fontWeight: 500, color: "var(--text-primary)" }}>
                  {g.label}
                  {isOpen ? <ChevronDown size={13} style={{ color: "var(--text-secondary)" }} /> : <ChevronRight size={13} style={{ color: "var(--text-secondary)" }} />}
                </button>
              </div>
              {isOpen && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 5, padding: "8px 10px" }}>
                  {g.subsectors.map((s) => {
                    const on = selSet.has(s.id);
                    return (
                      <button key={s.id} type="button" onClick={() => toggleSub(s.id)}
                        title={s.size === 0 ? "시드 종목 없음 — 미분류(확장 가능)" : `${s.size}종 시드`}
                        style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, cursor: "pointer", borderRadius: 12, padding: "4px 9px",
                          border: on ? "1px solid var(--bs-primary, #1200ff)" : "1px solid var(--border)",
                          background: on ? "var(--bg-card)" : "var(--bg-card)", color: on ? "var(--text-primary)" : s.size === 0 ? "var(--text-muted)" : "var(--text-secondary)" }}>
                        {on && <Check size={11} style={{ color: "var(--bs-primary, #1200ff)" }} />}
                        {s.label}{s.size > 0 ? ` (${s.size})` : ""}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {note && (
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 8, lineHeight: 1.6 }}>
          ⓘ {note}{seeded ? ` (현재 ${seeded.subs}/88 세부 · ${seeded.stocks}종 시드)` : ""}
        </div>
      )}
    </div>
  );
}
