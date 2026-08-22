"use client";
/**
 * 매크로 서브스튜디오 내비 (M1-U)
 * ==========================================================================
 * ★`.mc-tab` 과 겹치는 클래스를 만들지 않는다★ `radix-dialogs.spec.ts:66` 은
 * `.mc-tab` 을 `.first()` 없이 선택한다 — 같은 이름의 노드를 하나라도 더 만들면
 * strict mode 위반으로 죽는다. 이 저장소가 "클래스명이 E2E 계약" 이라고 적어 둔
 * 규칙의 정확한 사례라, 새 접두사 `.ms-nav*` 를 쓴다.
 *
 * ★가용성 점을 달지 않는다★ 어느 스튜디오가 도는지는 **실행해 봐야** 안다
 * (`pinn-tail` 은 이 환경에서 초과 관측 6 < 최소 8 로 거부된다). 목록만 보고 초록
 * 점을 찍으면 그것은 재 보지 않은 주장이다. 가용성과 사유는 각 스튜디오 안에 있다.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

/** 라우트 슬러그는 서버의 `Studio.id` 와 **같다**(M1-M 이 그렇게 정했다). */
export const STUDIO_NAV: { href: string; n: string; label: string }[] = [
  { href: "/macro",              n: "00", label: "COCKPIT" },
  { href: "/macro/tsfm-latent",  n: "01", label: "LATENT" },
  { href: "/macro/neural-sde",   n: "02", label: "TERM" },
  { href: "/macro/causal-deepm", n: "03", label: "CAUSAL" },
  { href: "/macro/pinn-tail",    n: "04", label: "TAIL" },
  { href: "/macro/agentic-mcp",  n: "05", label: "VIEWS" },
];

export function StudioNav() {
  const pathname = usePathname();
  return (
    <nav className="ms-nav" aria-label="매크로 스튜디오">
      {STUDIO_NAV.map((s) => {
        const on = pathname === s.href;
        return (
          <Link key={s.href} href={s.href}
                className={`ms-nav-item${on ? " on" : ""}`}
                aria-current={on ? "page" : undefined}>
            <b className="ms-nav-n num">{s.n}</b>
            <span className="ms-nav-l">{s.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

export default StudioNav;
