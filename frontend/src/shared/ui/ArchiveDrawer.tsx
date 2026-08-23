"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// ArchiveDrawer — 목록의 과거 항목을 본문 밖으로 빼는 측면 서랍 (A7)
// ─────────────────────────────────────────────────────────────────────────────
// ★왜 필요한가 (측정)★
// 02 ALPHALAB 의 레지스트리는 15개(초안 1 · 실험 14), 09 JOURNAL 은 런 10개 +
// STRATEGY HEALTH 15줄이 **전부 본문에 펼쳐져** 있었다. 300~340px 레일에서 이 길이는
// 화면 세 배가 되고, 지금 작업 중인 항목이 과거 기록에 묻힌다.
//
// ★왜 vaul 이 아니라 Radix Dialog 인가★
// shadcn 의 Sheet 는 vaul 을 쓰지만 그건 **새 dependency** 다. 측면 슬라이드는
// Dialog + CSS 로 똑같이 나오고, 포커스 트랩·Escape·스크롤 잠금·`aria-modal` 은 이미
// 들어와 있는 `@radix-ui/react-dialog` 가 준다(`shadcn/dialog.tsx` 가 쓰는 것).
//
// ★그런데 그대로 쓰면 예산을 넘는다 — 재서 알았다★
// 한 파일로 만들었을 때 alphalab 141 → 152 kB, journal 229 → 250 kB. Radix Dialog 가
// 그 청크들에 처음 들어가기 때문이다. 서랍은 닫힌 채 시작하므로 첫 페인트에 필요한 것은
// 트리거 버튼뿐이다 → 패널을 `next/dynamic` 으로 떼어낸다(ADR 001 개정판이 허용하는 경우).
//
// ★포털된다★ Radix 는 Overlay/Content 를 document.body 로 포털한다 — 컨테이너로 스코프한
// Playwright 단언은 이 안을 못 본다(`shadcn/dialog.tsx` 헤더가 같은 함정을 기록해 뒀다).
// 드로어를 검사하는 스펙은 `.as-arch-*` 를 **페이지 루트에서** 잡아야 한다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useRef, useState } from "react";
import dynamic from "next/dynamic";

const ArchiveDrawerPanel = dynamic(() => import("./ArchiveDrawerPanel"), { ssr: false });

export interface ArchiveDrawerProps {
  /** 트리거 버튼에 보이는 글자 — 개수를 포함해 "무엇이 몇 개 숨어 있는지" 를 말한다. */
  label: React.ReactNode;
  /** 서랍 제목. 스크린리더의 접근 가능한 이름이 되므로 비우지 않는다. */
  title: string;
  /** 제목 옆 보조 설명 (선택). */
  hint?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

/**
 * 측면 서랍.
 *
 * 본문에는 **지금 쓰는 것**만 남기고 나머지를 여기로 넣는다. 트리거는 개수를 드러내야
 * 한다 — "전체 보기" 만 있으면 무엇이 얼마나 접혔는지 알 수 없다.
 *
 * `mounted` 는 한 번 열린 뒤 계속 true 다. 닫을 때마다 청크를 버리면 다시 열 때 또
 * 기다려야 하고, 이미 받은 것을 버릴 이유가 없다.
 */
export function ArchiveDrawer({ label, title, hint, children, className = "" }: ArchiveDrawerProps) {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  return (
    <>
      <button ref={triggerRef} type="button" className={`as-arch-t ${className}`.trim()}
        onClick={() => { setMounted(true); setOpen(true); }}>
        {label}
      </button>
      {mounted && (
        <ArchiveDrawerPanel open={open} onOpenChange={setOpen} title={title} hint={hint}
          // ★포커스를 손으로 되돌린다 — E2E 가 잡은 결함이다★
          // 패널이 `next/dynamic` 이라 클릭 시점에 Dialog 가 없었고, 그래서 Radix 가
          // 기억한 복귀 대상이 트리거가 아니었다. Escape 로 닫으면 포커스가 body 로
          // 떨어져서, 키보드 사용자는 방금 있던 자리를 잃고 처음부터 Tab 해야 했다.
          // 눈으로는 전혀 보이지 않는 종류의 결함이다.
          // `requestAnimationFrame` 은 Radix 가 포커스를 정리한 **뒤에** 우리가 넣기
          // 위한 것이다 — 같은 틱에 부르면 Radix 의 정리에 다시 덮인다.
          onCloseAutoFocus={(e) => {
            e.preventDefault();
            requestAnimationFrame(() => triggerRef.current?.focus());
          }}>
          {children}
        </ArchiveDrawerPanel>
      )}
    </>
  );
}
