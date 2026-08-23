"use client";
// 매크로 전략 라이브러리 — 매크로 탭(05 Strategies)의 22 자산배분 전략을 AAS로 불러오기.
// 각 전략의 '현재 시점 보유자산·비중'(compute_strategies, KR ETF 실데이터 매핑)을 그대로
// AAS 포트폴리오로 로드 → Optimize/Stress/Explain 파이프라인으로 재최적화·검증 가능.
// 백엔드 무변경 — 기존 GET /macro/strategies (analysisApi.macroStrategies) 재사용.
import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { analysisApi } from "@/entities/macro/analysisApi";
import { type TacticalStrategy } from "@/entities/macro/analysisModel";
import { useAllocation } from "./AllocationProvider";

// 매크로 콕핏과 동일한 family 라벨·순서 (일관성)
const FAMILY_LABELS: Record<string, string> = {
  risk: "리스크 기반 · 공분산 구동", optim: "최적화 기반", trend: "추세추종 (CTA)",
  sizing: "성장최적 사이징", momentum: "모멘텀 · 추세 타이밍", benchmark: "벤치마크",
};
const FAMILY_ORDER = ["momentum", "risk", "optim", "trend", "sizing", "benchmark"];

function signalTone(sig: string): string {
  if (sig.includes("공격")) return "var(--color-bull)";
  if (sig.includes("방어")) return "var(--color-bear)";
  return "var(--t-muted)";
}

export function StrategyLibrary() {
  const { loadStrategy, loadedStrategy } = useAllocation();
  const [market, setMarket] = useState<"kr" | "us">(loadedStrategy?.market ?? "kr");
  const [q, setQ] = useState("");

  const stratQ = useQuery({
    queryKey: ["macro", "strategies", market],
    queryFn: () => analysisApi.macroStrategies(market).catch(() => null),
  });

  const groups = useMemo(() => {
    const all = stratQ.data?.strategies ?? [];
    const needle = q.trim().toLowerCase();
    const filtered = needle
      ? all.filter((s) => s.name.toLowerCase().includes(needle) || s.description.toLowerCase().includes(needle) || s.id.includes(needle))
      : all;
    const by: Record<string, TacticalStrategy[]> = {};
    filtered.forEach((s) => { const f = s.family ?? "momentum"; (by[f] ??= []).push(s); });
    return FAMILY_ORDER.filter((f) => by[f]?.length).map((f) => ({ family: f, label: FAMILY_LABELS[f] ?? f, items: by[f] }));
  }, [stratQ.data, q]);

  const total = stratQ.data?.strategies?.length ?? 0;

  return (
    <div className="as-sl">
      <div className="as-seg as-fb-mode">
        <button className={market === "kr" ? "on" : ""} onClick={() => setMarket("kr")}>국내 ETF (실데이터)</button>
        <button className={market === "us" ? "on" : ""} onClick={() => setMarket("us")}>미국 원본</button>
      </div>
      <input className="as-sl-search" value={q} placeholder="전략 검색 — 예: 듀얼모멘텀, HRP, 영구"
        onChange={(e) => setQ(e.target.value)} />
      <div className="as-note">
        매크로 탭의 {total || "22"}개 자산배분 전략을 불러와 시작 포트폴리오로 사용합니다. 불러온 뒤
        <b> 03 Timing</b>·<b> 04 Optimize</b>에서 마켓타이밍·재최적화를 적용할 수 있습니다.
      </div>

      {stratQ.isLoading && <div className="as-empty">전략 시그널 계산 중…</div>}
      {!stratQ.isLoading && !total && <div className="as-empty">전략을 불러오지 못했습니다 (백엔드 미기동 시 mock).</div>}

      <div className="as-sl-list">
        {groups.map((g) => (
          <div key={g.family} className="as-sl-group">
            <div className="as-sl-fam">{g.label} <b className="num">{g.items.length}</b></div>
            {g.items.map((s) => {
              const loaded = loadedStrategy?.id === s.id && loadedStrategy?.market === market;
              const top = [...s.holdings].sort((a, b) => b.weight - a.weight).slice(0, 4);
              return (
                <div key={s.id} className={`as-sl-card${loaded ? " on" : ""}`}>
                  <div className="as-sl-head">
                    <span className="as-sl-name">{s.name}</span>
                    <span className="as-sl-sig num" style={{ color: signalTone(s.signal) }}>{s.signal}</span>
                  </div>
                  <div className="as-sl-desc">{s.description}</div>
                  <div className="as-sl-holds">
                    {top.map((h) => (
                      <span key={h.ticker} className="as-sl-hold" title={`${h.label} ${h.weight}%`}>
                        {h.label}<b className="num"> {Math.round(h.weight)}%</b>
                      </span>
                    ))}
                    {s.holdings.length > top.length && <span className="as-sl-more num">+{s.holdings.length - top.length}</span>}
                  </div>
                  <button className="as-fb-apply as-sl-load" onClick={() => loadStrategy(s, market)}>
                    {loaded ? "✓ 불러옴 — 다시 적용" : "이 전략으로 구성 →"}
                  </button>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
