"use client";
/**
 * 화면에 들어오면 한 번 `data-in` 을 붙인다 (BU8a 첫 화면 · 등장 모습은 CSS 가 정한다).
 * ★스크롤 이벤트를 듣지 않는다★ IntersectionObserver 하나 · 들어오면 바로 끊는다.
 * ★숨는 내용이 없게★ 서버 렌더·JS 없음에서는 `data-arm` 이 없어 처음부터 보인다. 붙은 뒤에야(`data-arm`) CSS 가 등장 전 모습을 건다.
 * 감속 모션이면 CSS 가 등장 전 모습을 걸지 않는다(globals BU8a 절).
 */
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

type Tag = "div" | "ol" | "section";

export function InView({ as = "div", className, style, threshold = 0.2, children }: {
  as?: Tag; className?: string; style?: CSSProperties; threshold?: number; children: ReactNode;
}) {
  const ref = useRef<HTMLElement | null>(null);
  const [armed, setArmed] = useState(false);
  const [seen, setSeen] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") { setSeen(true); return; }
    setArmed(true);
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { setSeen(true); io.disconnect(); }
    }, { threshold, rootMargin: "0px 0px -10% 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, [threshold]);

  const Comp = as as "div";
  return (
    <Comp ref={(n: HTMLElement | null) => { ref.current = n; }} className={className} style={style}
          data-arm={armed || undefined} data-in={seen || undefined}>
      {children}
    </Comp>
  );
}
