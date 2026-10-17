"use client";
// 젠포트 17그룹 → 88 세부업종 트리 (매매 대상 설정 미러) — 접이식 그룹 + 세부 체크박스.
// 선택된 세부업종은 'theme:세부' id로 universe.sectors 에 들어가 select_universe 가 해석.
// 구조는 백엔드 /theme-tree (젠포트 화면 전사), 종목 매핑은 best-effort 추론 시드.

import { useEffect, useState } from "react";
import { Check, ChevronDown, ChevronRight } from "lucide-react";

import { API_BASE } from "@/shared/api/apiBase";

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
  // BU3 — 실패를 삼키지 않는다: 예전 `.catch(() => {})` 는 업종 목록이 안 와도 빈 칸으로 보였다(실패 ≠ 업종 없음).
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/screener/theme-tree`).then((r) => {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    }).then((d) => {
      setGroups(d.groups ?? []);
      setNote(d.note ?? "");
      setSeeded({ subs: d.seeded_subsectors ?? 0, stocks: d.seeded_stocks ?? 0 });
      setFailed(false);
    }).catch(() => setFailed(true));
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
    <div className="bte-col">
      <div className="bte-row">
        <span className="bte-sub-h">{totalSubSelected > 0 ? `세부 업종 ${totalSubSelected}개 골랐어요` : "고르지 않으면 모든 업종이에요"}</span>
        {groups.length > 0 && (
          <button type="button" className="bte-link" onClick={() => emit(allOn ? new Set() : new Set(allIds))}>
            {allOn ? "모두 빼기" : "모두 고르기"}
          </button>
        )}
      </div>
      {failed && <p className="bte-note bte-note--bad" role="alert">업종 목록을 불러오지 못했어요. 지금은 업종으로 거를 수 없어요 — 새로고침해 다시 시도해 주세요.</p>}

      <div className="bte-tree">
        {groups.map((g) => {
          const ids = g.subsectors.map((s) => s.id);
          const grpAll = ids.every((i) => selSet.has(i));
          const grpSome = !grpAll && ids.some((i) => selSet.has(i));
          const isOpen = open.has(g.id);
          return (
            <div key={g.id} className="bte-tree-g">
              <div className="bte-tree-head">
                <button type="button" role="checkbox" aria-checked={grpAll ? true : grpSome ? "mixed" : false}
                  aria-label={`${g.label} 전체`} className="bte-check" onClick={() => toggleGroup(g)}>
                  {grpAll && <Check size={12} aria-hidden />}
                  {grpSome && <span className="bte-check-dash" aria-hidden />}
                </button>
                <button type="button" className="bte-tree-t" aria-expanded={isOpen} onClick={() => toggleOpen(g.id)}>
                  {g.label}
                  {isOpen ? <ChevronDown size={16} aria-hidden /> : <ChevronRight size={16} aria-hidden />}
                </button>
              </div>
              {isOpen && (
                <div className="bte-tree-subs">
                  {g.subsectors.map((s) => {
                    const on = selSet.has(s.id);
                    return (
                      <button key={s.id} type="button" className="bte-pill bte-pill--sm" aria-pressed={on} data-empty={s.size === 0 ? "1" : "0"}
                        onClick={() => toggleSub(s.id)}>
                        {on && <Check size={12} aria-hidden />}
                        {s.label}{s.size > 0 ? ` ${s.size}종목` : " · 아직 종목 없음"}
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
        <p className="bte-note">{note}{seeded ? ` (지금 세부 업종 ${seeded.subs}/88개 · ${seeded.stocks}종목을 담았어요)` : ""}</p>
      )}
    </div>
  );
}
