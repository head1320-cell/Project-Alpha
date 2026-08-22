"use client";
// EvidenceDrawer 의 Radix 구현부 — `next/dynamic` 으로 떼어내려고 파일을 나눴다.
// 이 모듈을 import 하는 순간 @radix-ui/react-popover 가 번들에 들어온다(실측 +13 kB).
// 진입점은 ./EvidenceDrawer — 왜 나눴는지는 그쪽 주석에 있다.
import * as React from "react";
import { Popover, PopoverTrigger, PopoverContent } from "@/shared/ui/shadcn/popover";
import type { EvidenceRow } from "./EvidenceDrawer";

export default function EvidenceDrawerPanel({
  label, title, rows, className = "", defaultOpen = false,
}: {
  label: string; title: string; rows: EvidenceRow[]; className?: string; defaultOpen?: boolean;
}) {
  return (
    <Popover defaultOpen={defaultOpen}>
      <PopoverTrigger asChild>
        <button type="button" className={`tev-drawer-t ${className}`.trim()}>
          {label}
        </button>
      </PopoverTrigger>
      {/* ★Phase A 의 포커스 복원 처치를 여기서는 쓰지 않는다 — 필요 없어서다★
          Phase A 의 모달 둘은 `onCloseAutoFocus` 를 막고 rAF 로 트리거를 다시 잡아야 했다.
          그래서 여기도 같은 코드를 넣었다가, **빼고 스펙을 다시 돌려 봤다 — 그대로 통과했다**.
          차이는 구조다: Phase A 는 dynamic 경계가 트리거 *바깥* 이라 Radix 가 진짜 트리거를
          본 적이 없었다. 여기서는 트리거가 Popover 루트 *안* 에 있어 Radix 가 정상 복원한다.
          근거 없이 남겨 두면 "이게 있어야 동작한다" 는 거짓 설명이 코드에 박힌다.
          (스펙은 여전히 toBeFocused() 로 **동작** 을 지킨다 — 누가 구현하든 상관없이.) */}
      <PopoverContent aria-label={title}>
        <div className="tev-drawer">
          <div className="tev-drawer-h">{title}</div>
          <dl className="tev-drawer-l">
            {rows.map((r, i) => (
              <div key={i} className="tev-drawer-r">
                <dt>{r.label}</dt>
                <dd className={r.mono ? "num" : undefined}>
                  {r.value}
                  {r.note && <span className="tev-drawer-n">{r.note}</span>}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </PopoverContent>
    </Popover>
  );
}
