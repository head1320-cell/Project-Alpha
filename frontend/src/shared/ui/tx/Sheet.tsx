"use client";
/**
 * 시트 — 화면을 떠나지 않고 자세히 보기 (BL2 캔버스 서랍을 BU2 에서 공용으로 올렸다)
 * ==========================================================================
 * 네이티브 `<dialog>` 라 초점 가두기·Esc·배경 비활성은 브라우저가 한다. 1440 에서는 오른쪽에서, 560 이하에서는 아래에서 올라온다.
 * 여닫힘은 사용자 동작에 답하는 모션 하나 — 감속 모션이면 바로 나타난다. 색은 `--tx-*`(캔버스 `--pg-*` 와 같은 값).
 * `className` 은 화면 계약 클래스를 더할 때 쓴다(캔버스는 `pg-sheet` — portfolio-graph.spec).
 */
import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

export function Sheet({ open, onClose, title, sub, children, testId, className }: {
  open: boolean; onClose: () => void; title: string; sub?: ReactNode; children: ReactNode; testId?: string; className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className={`tx-sheet${className ? ` ${className}` : ""}`} aria-label={title} data-sheet={testId} onClose={onClose}
            onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      <header className="tx-sheet-head">
        <div>
          <h2 className="tx-sheet-title">{title}</h2>
          {sub ? <p className="tx-sheet-sub">{sub}</p> : null}
        </div>
        <button type="button" className="tx-sheet-x" aria-label="닫기" onClick={onClose}><X size={18} /></button>
      </header>
      <div className="tx-sheet-body">{open ? children : null}</div>
    </dialog>
  );
}
