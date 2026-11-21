"use client";
/**
 * '배치' 메뉴 — 기본 배치 ↔ 판 배치 · 처음 배치 · 이름 붙인 배치 · 닫은 판 다시 열기 · 배치 관리 (G6 2a-1 · 계획 §9.1 · 용어집 §3.30)
 * ==========================================================================
 * 판 배치를 끈 넓은 창에서는 결과 칸 막대에, 켠 화면에서는 판 위 막대에 하나 선다. 단추 id 는 화면마다 하나(`ws-open-<화면>`) —
 * 끄고 켜며 단추가 다른 자리로 옮겨 그려져도 초점이 그 단추로 돌아온다.
 * 처음 배치 · 이름 붙인 배치는 ★지금 폭에 들어갈 때만★ 고른다 — 들어가지 않으면 aria-disabled + 까닭(필요한 폭 · 지금 폭). 고르자마자
 * 합쳐 보이는 일을 막는다. 한 열로 쌓은 좁은 창에서는 열을 그리지 않으므로 폭으로 막지 않는다(넓히면 그 배치로 돌아간다).
 * 도구는 배치를 고르거나 권하지 않는다 — 처음 배치의 이름은 쓰임의 묘사다.
 */
import { LayoutGrid } from "lucide-react";
import { needWidth, type Layout } from "./layout";
import { MenuButton, type MenuItem } from "./MenuButton";
import type { WorkspaceState } from "./useWorkspace";

/** 화면마다 하나인 '배치' 단추의 id. */
export const openId = (screen: string): string => `ws-open-${screen}`;

/** 단추로 초점을 돌린다 — 다음 그림 뒤(판 배치를 켜고 끄면 단추가 다른 자리에 새로 선다). */
export const refocusOpen = (screen: string): void => {
  requestAnimationFrame(() => document.getElementById(openId(screen))?.focus());
};

const px = (n: number): string => `${Math.round(n).toLocaleString("ko-KR")} px`;

export function LayoutMenu({ ws, work, stacked = false, onReopen, onManage }: {
  ws: WorkspaceState;
  /** 판이 들어설 폭(px · 아직 재지 못했으면 0 — 그때는 막지 않는다). */
  work: number;
  /** 한 열로 쌓은 좁은 창 — 폭으로 막지 않는다. */
  stacked?: boolean;
  /** 닫은 판 다시 열기 — 판 배치를 켠 화면에서만 준다. */
  onReopen?: (id: string) => void;
  onManage: () => void;
}) {
  const { spec } = ws;
  const back = () => refocusOpen(spec.screen);
  /** 지금 폭에 들어가지 않으면 그 까닭. 들어가거나 막지 않을 때는 undefined. */
  const tooWide = (l: Layout): string | undefined => {
    if (stacked || !(work > 0)) return undefined;
    const need = needWidth(l, spec);
    return need > work ? `창이 좁아 고를 수 없습니다(필요한 폭 ${px(need)} · 지금 ${px(work)}).` : undefined;
  };
  const nameOf = (id: string) => spec.panels.find((p) => p.id === id)?.name ?? id;

  const items: MenuItem[] = [
    { kind: "group", key: "mode", label: "배치 방식", items: [
      { kind: "item", key: "off", role: "menuitemradio", checked: !ws.on, label: "기본 배치", onSelect: () => { ws.setOn(false); back(); } },
      { kind: "item", key: "on", role: "menuitemradio", checked: ws.on, label: "판 배치", onSelect: () => { ws.setOn(true); back(); } },
    ] },
    { kind: "group", key: "presets", label: "처음 배치", items: spec.presets.map((p): MenuItem => {
      const why = tooWide(p.layout);
      return { kind: "item", key: `p-${p.id}`, label: p.name, disabled: !!why, why, onSelect: () => { ws.applyPreset(p.id); back(); } };
    }) },
  ];
  if (ws.saved.length) {
    items.push({ kind: "group", key: "saved", label: "이름 붙인 배치", items: ws.saved.map((n): MenuItem => {
      const why = tooWide(n.layout);
      return { kind: "item", key: `s-${n.name}`, label: n.name, disabled: !!why, why, onSelect: () => { ws.applySaved(n.name); back(); } };
    }) });
  }
  if (ws.on && onReopen && ws.layout.closed.length) {
    items.push({ kind: "group", key: "closed", label: "닫은 판", items: ws.layout.closed.map((id): MenuItem => (
      { kind: "item", key: `c-${id}`, label: `‘${nameOf(id)}’ 다시 열기`, onSelect: () => onReopen(id) }
    )) });
  }
  items.push({ kind: "sep", key: "sep" }, { kind: "item", key: "manage", label: "배치 관리", onSelect: onManage });

  return (
    <MenuButton className="tx-btn tx-btn--sub ws-open" id={openId(spec.screen)} items={items}>
      <LayoutGrid size={16} aria-hidden />
      배치
    </MenuButton>
  );
}
