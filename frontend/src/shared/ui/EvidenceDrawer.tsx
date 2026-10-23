"use client";

// ═══════════════════════════════════════════════════════════════════════════════
// EvidenceDrawer — 정상 상태의 부연을 담는 서랍 (UI/UX 현대화 P2b)
// ─────────────────────────────────────────────────────────────────────────────
// ★무엇을 넣고 무엇을 넣지 않는가★ — 이 구분이 이 컴포넌트의 전부다.
//
//   넣는다   재현 식별자, 버전, 기준시점 설명 같은 **정상 상태의 부연**.
//            평소에는 화면을 어지럽히고, 필요할 때는 정확히 필요하다.
//   넣지 않는다  경고·비정상 상태. 서랍은 닫혀 있으면 존재하지 않는 것과 같다.
//            title= 을 걷어내려고 만든 물건으로 title= 과 같은 일을 하면 아무것도 고치지 못한다.
//
// 설계 원칙 3 과 6 이 그대로 코드가 된 자리다: "경고는 항상 보이고, 부연은 한 키 거리에".
//
// ★왜 두 파일인가 — 무게를 소비자마다 재지 않으려고★
// Radix Popover 는 실측 +13 kB 다(/dev/ui 126→139). ADR 001 은 4 kB 를 넘는 증가를
// 설명 없이 통과시키지 않는다. 소비자마다 `next/dynamic` 을 쓰게 하면 언젠가 한 곳이
// 빠뜨리고, 그때 무게는 조용히 돌아온다. 그래서 **경계를 이 안에 둔다** — 닫혀 있는 동안은
// 평범한 <button> 이고, 처음 열릴 때 구현부를 가져온다. 소비자는 그냥 import 하면 된다.
// (Phase A 의 모달들은 소비자 쪽에서 dynamic 했다. 그건 창이 하나뿐이라 그래도 됐다.)
// ═══════════════════════════════════════════════════════════════════════════════

import * as React from "react";
import dynamic from "next/dynamic";

const EvidenceDrawerPanel = dynamic(() => import("./EvidenceDrawerPanel"), { ssr: false });

export interface EvidenceRow {
  /** 항목 이름. 짧게 — 표의 왼쪽 열이다. */
  label: string;
  /** 값. 식별자·버전 같은 것은 num 클래스로 등폭 정렬된다. */
  value: React.ReactNode;
  /** 왜 이 값이 여기 있는지. 없으면 줄만 나온다. */
  note?: React.ReactNode;
  /** 식별자류(해시·run_id)면 true — 등폭 + 줄바꿈 허용. */
  mono?: boolean;
}

export function EvidenceDrawer({
  label = "근거", title, rows, className = "",
}: {
  /** 트리거 버튼 텍스트. */
  label?: string;
  /** 서랍 제목 — 스크린리더가 읽는 이름이기도 하다. */
  title: string;
  rows: EvidenceRow[];
  className?: string;
}) {
  const [armed, setArmed] = React.useState(false);

  // 아직 한 번도 열지 않았다 — Radix 는 로드되지 않았고, 이건 그냥 버튼이다.
  // 클래스·글자가 아래 실제 트리거와 같아서 바뀌는 순간 레이아웃이 흔들리지 않는다.
  if (!armed) {
    return (
      <button type="button" className={`tev-drawer-t ${className}`.trim()}
        onClick={() => setArmed(true)}>
        {label}
      </button>
    );
  }
  // 처음 열린 뒤로는 구현부가 트리거까지 소유한다(Popover 는 앵커를 제 안에 둬야 한다).
  return <EvidenceDrawerPanel label={label} title={title} rows={rows} className={className} defaultOpen />;
}
