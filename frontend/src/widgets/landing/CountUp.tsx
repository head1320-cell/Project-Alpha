"use client";
// 대상 경로: frontend/src/components/landing/CountUp.tsx
//
// 뷰포트 진입 시 숫자를 0→값으로 카운트업(rAF). 문자열 값의 prefix/suffix·소수 자릿수를
// 보존한다 — "+24.6%" → +0.0%…+24.6%, "142×" → 0×…142×, "290+" → 0+…290+.
// SSR/JS없음/reduced-motion 에선 최종값을 그대로 렌더(첫 페인트·접근성 안전).

import { useEffect, useRef, useState } from "react";

function parse(v: string) {
  const m = v.match(/^([^\d-]*)(-?[\d,]*\.?\d+)(.*)$/);
  if (!m) return null;
  const prefix = m[1] ?? "";
  const raw = m[2] ?? "";
  const suffix = m[3] ?? "";
  const num = parseFloat(raw.replace(/,/g, ""));
  if (!isFinite(num)) return null;
  const dot = raw.indexOf(".");
  const decimals = dot >= 0 ? raw.length - dot - 1 : 0;
  const grouped = raw.includes(",");
  return { prefix, num, suffix, decimals, grouped };
}

export default function CountUp({ value, className, duration = 1100 }: {
  value: string; className?: string; duration?: number;
}) {
  const ref = useRef<HTMLSpanElement | null>(null);
  const [display, setDisplay] = useState(value); // SSR·초기 = 최종값
  const done = useRef(false);

  useEffect(() => {
    const el = ref.current;
    const p = parse(value);
    const reduce = typeof window !== "undefined"
      && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (!el || !p || reduce || typeof IntersectionObserver === "undefined") { setDisplay(value); return; }

    const fmt = (n: number) => {
      const s = n.toFixed(p.decimals);
      const body = p.grouped
        ? Number(s).toLocaleString(undefined, { minimumFractionDigits: p.decimals, maximumFractionDigits: p.decimals })
        : s;
      return `${p.prefix}${body}${p.suffix}`;
    };

    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting || done.current) return;
        done.current = true;
        io.disconnect();
        setDisplay(fmt(0));
        const t0 = performance.now();
        const tick = (t: number) => {
          const prog = Math.min(1, (t - t0) / duration);
          const eased = 1 - Math.pow(1 - prog, 3); // easeOutCubic
          if (prog < 1) { setDisplay(fmt(p.num * eased)); requestAnimationFrame(tick); }
          else setDisplay(value); // 정확한 최종값
        };
        requestAnimationFrame(tick);
      });
    }, { threshold: 0.45 });
    io.observe(el);
    return () => io.disconnect();
  }, [value, duration]);

  return <span ref={ref} className={className}>{display}</span>;
}
