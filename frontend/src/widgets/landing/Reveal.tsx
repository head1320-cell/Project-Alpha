"use client";
// 대상 경로: frontend/src/components/landing/Reveal.tsx
//
// 스크롤 진입 시 .lp-in 을 1회 부여하는 경량 래퍼(IntersectionObserver).
// 자식 등장(스태거)은 globals.css 의 .lp-stagger / .lp-reveal 규칙이 담당한다.
// 모션 OFF/JS 없음/reduced-motion 폴백은 CSS(@media)+<noscript>로 처리 — 여기선 클래스 토글만.

import { useEffect, useRef, useState, type ReactNode } from "react";

export default function Reveal({ as = "div", className = "", stagger = false, id, children }: {
  as?: "div" | "footer";
  className?: string;
  stagger?: boolean;
  id?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLElement | null>(null);
  const [vis, setVis] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") { setVis(true); return; }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) { setVis(true); io.disconnect(); } });
    }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const cls = ["lp-reveal", stagger ? "lp-stagger" : "", vis ? "lp-in" : "", className].filter(Boolean).join(" ");
  const setRef = (n: HTMLElement | null) => { ref.current = n; };

  return as === "footer"
    ? <footer ref={setRef} className={cls} id={id}>{children}</footer>
    : <div ref={setRef} className={cls} id={id}>{children}</div>;
}
