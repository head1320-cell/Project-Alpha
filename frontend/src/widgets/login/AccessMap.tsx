"use client";
/**
 * 로그인 화면 · 로그인이 여는 것 (BU8b · 사용자 결정 "폼 + '로그인이 여는 것' 지도")
 * ==========================================================================
 * 문 앞에서 플랫폼 원칙('무엇을 재지 않았는지 말한다')을 그대로 한다 — 이 문이 무엇을 열고 무엇을 열지 않는지.
 * ★지어낸 목록이 아니다★ 세 층(열린 화면 → 로그인 → 거래 권한)은 `entities/session/accessMap.json` 에서 읽고, 그 파일이
 * 서버 보호 목록(`src/api/protected_routes.py::PROTECTED`)과 같은지는 `tests/test_login_access_map.py` 가 양방향으로 대조한다.
 *
 * 위에는 '지금 이 서버' 칩 둘 — 서버 값만:
 *  · 데이터 출처 = `GET /macro/connection-status` → 첫 화면·홈과 같은 `sourceChip`(연습용 여부는 mock 게이트가 정한다)
 *  · 실행 모드 = `GET /live/mode`(보호 목록 `OPEN_WITH_REASON` 에 공개로 등록된 것) → 뜻 번역(`order_executor.py` 머리 주석).
 *    모르는 값이면 서버 값 그대로 · 실패면 "확인하지 못했어요"(침묵 0).
 */
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { KeyRound, Lock, LockOpen, type LucideIcon } from "lucide-react";

import { macroApi } from "@/entities/macro/api";
import { sourceChip } from "@/entities/macro/regimeKo";
import ACCESS from "@/entities/session/accessMap.json";
import { API_BASE } from "@/shared/api/apiBase";
import { Chips, type Chip } from "@/shared/ui/tx";

type Item = { label: string; href?: string };
type TierKey = "open" | "login" | "admin";
const TIERS: { key: TierKey; Icon: LucideIcon }[] = [
  { key: "open", Icon: LockOpen }, { key: "login", Icon: Lock }, { key: "admin", Icon: KeyRound },
];

/** 실행 모드 뜻 — 서버 `ExecutionMode`(SHADOW·PAPER·LIVE). 어휘 밖이면 서버 값 그대로 보인다. */
const MODE_SAY: Record<string, string> = {
  SHADOW: "주문 없이 신호만 기록해요",
  PAPER: "가상으로 체결해요",
  LIVE: "실제 돈으로 주문해요",
};

async function liveMode(): Promise<string | null> {
  const r = await fetch(`${API_BASE}/api/v1/live/mode`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const b = (await r.json()) as { mode?: unknown };
  return typeof b?.mode === "string" && b.mode ? b.mode : null;
}

function modeChip(q: { data?: string | null; isError: boolean; isLoading: boolean }): Chip[] {
  if (q.isLoading) return [];
  if (q.isError || !q.data) return [{ label: "실행 모드를 확인하지 못했어요", tone: "unknown", ev: "mode" }];
  return [{ label: `실행 모드: ${MODE_SAY[q.data] ?? q.data}`, tone: "plain", ev: "mode" }];
}

export function AccessMap() {
  const cs = useQuery({ queryKey: ["macro", "connection-status"], queryFn: () => macroApi.connectionStatus() });
  const mode = useQuery({ queryKey: ["login", "live-mode"], queryFn: liveMode, retry: false });
  const chips: Chip[] = [
    ...sourceChip({ data: cs.data, isError: cs.isError, isLoading: cs.isLoading }).map((c) => ({ ...c, ev: "data" })),
    ...modeChip(mode),
  ];

  return (
    <section className="lg-map" aria-labelledby="lg-map-h">
      <h2 id="lg-map-h" className="lg-map-h">로그인이 여는 것</h2>
      <div className="lg-srv">
        <span className="lg-srv-k">지금 이 서버</span>
        <Chips items={chips} label="지금 이 서버의 상태" />
      </div>
      <ol className="lg-tiers">
        {TIERS.map(({ key, Icon }, i) => {
          const tier = ACCESS[key] as { title: string; why?: string; items: Item[] };
          return (
            <li key={key} className="lg-tier" data-tier={key} style={{ ["--i" as string]: i }}>
              <span className="lg-tier-n" aria-hidden><Icon size={16} strokeWidth={2} /></span>
              <div className="lg-tier-b">
                <h3 className="lg-tier-t">{tier.title}</h3>
                <ul className="lg-chips">
                  {tier.items.map((it) => (
                    <li key={it.label}>
                      {it.href ? <Link href={it.href} className="lg-chip">{it.label}</Link> : <span className="lg-chip">{it.label}</span>}
                    </li>
                  ))}
                </ul>
                {tier.why ? <p className="lg-why">{tier.why}</p> : null}
              </div>
            </li>
          );
        })}
      </ol>
      <p className="lg-map-cap">서버의 보호 목록과 같은 내용이에요.</p>
    </section>
  );
}
