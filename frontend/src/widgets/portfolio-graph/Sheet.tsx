"use client";
/**
 * 옆에서 여는 서랍 (BL2) — 캔버스를 떠나지 않고 기록을 다룬다
 * ==========================================================================
 * 네이티브 `<dialog>` 라 초점 가두기·Esc·배경 비활성은 브라우저가 한다. 여닫힘은 사용자 동작에 답하는
 * 모션 하나(오른쪽에서 밀려 들어옴)만 — 감속 모션이면 바로 나타난다.
 */
import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

export function Sheet({ open, onClose, title, sub, children, testId }: {
  open: boolean; onClose: () => void; title: string; sub?: string; children: ReactNode; testId?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className="pg-sheet" aria-label={title} data-sheet={testId} onClose={onClose}
            onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      <header className="pg-sheet-head">
        <div>
          <h2 className="pg-sheet-title">{title}</h2>
          {sub && <p className="pg-sheet-sub">{sub}</p>}
        </div>
        <button type="button" className="pg-sheet-x" aria-label="닫기" onClick={onClose}><X size={18} /></button>
      </header>
      <div className="pg-sheet-body">{open ? children : null}</div>
    </dialog>
  );
}
