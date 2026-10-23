"use client";
// 모형 한눈에(BU6a+) — 여러 가치 모형의 추정값(점)과 범위(선)를 한 로그 축에 줄지어 놓고 현재가 세로선을 긋는다.
// ★못 낸 모형은 줄을 지우지 않는다★(그 줄에 서버 사유) · 불러오는 중은 "계산하는 중이에요" · 판단 색 없음(점은 한 색, 이름이 말한다).
// 값은 서버 응답 그대로 — 화면은 위치만 계산한다. 축 밖·0 이하 값은 끝에 붙이고 "그림 밖"이라고 적는다(지우지 않음).
import React from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import type { ValuationSandbox } from "@/entities/company/model";
import { priceWon } from "@/shared/lib/krFormat";
import type { CompanyModels } from "./useModels";

export interface LadRow {
  key: string;
  label: string;
  /** 대표 추정값(점). 없으면 범위만이거나 사유. */
  v?: number | null;
  lo?: number | null;
  hi?: number | null;
  /** 같은 줄의 다른 점(가치의 층: 자산·수익력). 세기에는 넣지 않는다. */
  extra?: { label: string; v: number }[];
  reason?: string | null;
  wait?: boolean;
  /** 이 줄의 가정 출처 — "실측 기본값" / "사람이 정한 확률" 등(보이는 글자). */
  basis?: string;
}

/** 레일(좁은 칸)에서 쓰는 짧은 이름 — 긴 이름이 잘리지 않게. */
const SHORT: Record<string, string> = {
  rim: "RIM", dcf: "DCF", ddm: "DDM", graham: "그레이엄", dist: "가치 분포", driver: "영업 동인", layers: "가치의 층",
  eva: "EVA", jper: "정당 PER", jpbr: "정당 PBR", peer: "업종 PER", scen: "시나리오",
};

const fin = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);

/** 질의 하나 → 줄 하나(또는 여럿). 불러오는 중·실패·못 함·값을 가른다. */
function fromQuery<T>(q: UseQueryResult<T>, key: string, label: string, pick: (d: T) => Omit<LadRow, "key" | "label">): LadRow {
  if (q.isPending) return { key, label, wait: true };
  if (q.isError || !q.data) return { key, label, reason: "서버에 닿지 못해 이 모형을 그리지 못했어요" };
  const d = q.data as T & { available?: boolean; reason?: string | null };
  if (d.available === false) return { key, label, reason: d.reason ?? "서버가 사유 없이 못 했다고 답했어요" };
  return { key, label, ...pick(d) };
}

/** 샌드박스(풋볼필드) + 모형 여덟 → 줄. 순서 = 위에서 아래로 읽는 차례(가정형 → 분포 → 영업 → 자산·이익 → 배수 → 시나리오). */
export function buildLadderRows(sb: UseQueryResult<ValuationSandbox>, m: CompanyModels): LadRow[] {
  const band = (id: string, label: string): LadRow => {
    if (sb.isPending) return { key: id, label, wait: true };
    if (sb.isError || !sb.data) return { key: id, label, reason: "가치 샌드박스를 받지 못했어요" };
    const b = sb.data.football_field?.bands.find((x) => x.id === id);
    if (!b || b.available === false || !fin(b.lo) || !fin(b.hi)) return { key: id, label, reason: b?.note ?? "이 모형은 값을 내지 못했어요" };
    return { key: id, label, v: fin(b.mid) ? b.mid : null, lo: b.lo, hi: b.hi, basis: "실측 기본값" };
  };
  const rows: LadRow[] = [
    band("rim", "RIM(잔여이익)"),
    band("dcf", "DCF(현금흐름할인)"),
    band("ddm", "DDM(배당할인)"),
    band("graham", "그레이엄 넘버"),
    fromQuery(m.dist, "dist", "가치 분포(가정 흔들기)", (d) => ({
      v: d.unified?.p50 ?? null, lo: d.unified?.p10 ?? null, hi: d.unified?.p90 ?? null, basis: "흔든 폭은 정한 값" })),
    fromQuery(m.driver, "driver", "영업 동인 흔들기", (d) => ({
      v: d.quantiles?.p50 ?? null, lo: d.quantiles?.p10 ?? null, hi: d.quantiles?.p90 ?? null, basis: "흔든 폭은 정한 값" })),
    fromQuery(m.layers, "layers", "가치의 층(성장까지)", (d) => {
      const L = Object.fromEntries((d.layers ?? []).map((x) => [x.key, x]));
      const extra = [
        fin(L.asset?.per_share) ? { label: "자산", v: L.asset.per_share as number } : null,
        fin(L.epv?.per_share) ? { label: "수익력", v: L.epv.per_share as number } : null,
      ].filter((x): x is { label: string; v: number } => x !== null);
      return fin(d.full_per_share) ? { v: d.full_per_share, extra } : { reason: d.weighted_reason ?? "성장까지 잰 값을 내지 못했어요", extra };
    }),
    fromQuery(m.eva, "eva", "EVA(경제적 부가가치)", (d) => (fin(d.valuation?.per_share)
      ? { v: d.valuation!.per_share } : { reason: d.valuation?.per_share_reason ?? "주당 가치를 내지 못했어요" })),
    fromQuery(m.multiples, "jper", "정당 PER", (d) => (fin(d.justified?.per_price)
      ? { v: d.justified!.per_price } : { reason: d.justified?.reason ?? "정당 PER 을 내지 못했어요" })),
    fromQuery(m.multiples, "jpbr", "정당 PBR", (d) => (fin(d.justified?.pbr_price)
      ? { v: d.justified!.pbr_price } : { reason: d.justified?.reason ?? "정당 PBR 을 내지 못했어요" })),
    fromQuery(m.multiples, "peer", "같은 업종 PER 중앙값", (d) => (fin(d.peer?.per_price)
      ? { v: d.peer!.per_price } : { reason: "같은 업종 PER 을 받지 못했어요" })),
    fromQuery(m.scenarios, "scen", "시나리오 가중", (d) => {
      const vs = (d.rows ?? []).map((r) => r.value).filter(fin);
      return fin(d.weighted) ? { v: d.weighted, lo: vs.length ? Math.min(...vs) : null, hi: vs.length ? Math.max(...vs) : null, basis: "사람이 정한 확률" }
        : { reason: "확률로 묶은 값을 내지 못했어요" };
    }),
  ];
  return rows;
}

/** 로그 축 위치(0~1). 0 이하는 왼쪽 끝. */
function scaler(vals: number[]) {
  const pos = vals.filter((v) => v > 0);
  const lo = Math.log(Math.min(...pos) * 0.85), hi = Math.log(Math.max(...pos) * 1.15);
  return (v: number) => (v <= 0 ? 0 : Math.min(1, Math.max(0, (Math.log(v) - lo) / (hi - lo || 1))));
}

export function ModelLadder({ rows, price, intrinsic, compact }: { rows: LadRow[]; price: number; intrinsic?: number | null; compact?: boolean }) {
  const vals = [price, ...(intrinsic && intrinsic > 0 ? [intrinsic] : []),
    ...rows.flatMap((r) => [r.v, r.lo, r.hi, ...(r.extra ?? []).map((e) => e.v)]).filter(fin)];
  const x = scaler(vals);
  const at = (v: number) => `${(x(v) * 100).toFixed(2)}%`;
  const mains = rows.filter((r) => fin(r.v));
  const below = mains.filter((r) => (r.v as number) < price).length;
  // 축 위치를 CSS 변수로 — 현재가 선이 모든 줄을 꿰뚫는다(이름 칸·값 칸 폭을 뺀 길이 위에서).
  const posVar = (v: number) => ({ "--x": x(v) } as React.CSSProperties);
  return (
    <figure className={`ci-ladder${compact ? " ci-ladder--compact" : ""}`} data-price={price}
            aria-label={`가치 모형 ${mains.length}개의 추정값과 현재가 ${priceWon(price)}`}>
      <div className="ci-lad-body">
        {rows.map((r) => (
          <div key={r.key} className="ci-lad-row" data-key={r.key}>
            <span className="ci-lad-name">{compact ? SHORT[r.key] ?? r.label : r.label}</span>
            <span className="ci-lad-track">
              {r.wait ? <span className="ci-lad-wait">계산하는 중이에요</span>
                : r.reason && !fin(r.v) ? <span className="ci-lad-reason" data-server>{r.reason}</span>
                : (
                  <>
                    {fin(r.lo) && fin(r.hi) && (
                      <i className="ci-lad-range" style={{ left: at(r.lo), width: `calc(${at(r.hi)} - ${at(r.lo)})` }} aria-hidden />
                    )}
                    {(r.extra ?? []).map((e) => (
                      <i key={e.label} className="ci-lad-dot ci-lad-dot--sub" data-v={e.v} style={{ left: at(e.v) }} aria-hidden>
                        {!compact && <em>{e.label}</em>}
                      </i>
                    ))}
                    {fin(r.v) && <i className={`ci-lad-dot${r.v <= 0 ? " out" : ""}`} data-main data-v={r.v} style={{ left: at(r.v) }} aria-hidden />}
                  </>
                )}
            </span>
            {!compact && <span className="ci-lad-val">{fin(r.v) ? priceWon(r.v) : r.wait ? "" : "값 없음"}</span>}
          </div>
        ))}
        <i className="ci-lad-price" style={posVar(price)} aria-hidden />
        {intrinsic && intrinsic > 0 ? <i className="ci-lad-intr" style={posVar(intrinsic)} aria-hidden /> : null}
      </div>
      <figcaption className="ci-lad-cap">
        <span className="ci-lad-key"><i className="ci-lad-sw price" aria-hidden />현재가 {priceWon(price)}</span>
        {intrinsic && intrinsic > 0 ? <span className="ci-lad-key"><i className="ci-lad-sw intr" aria-hidden />머리 문장 내재가치 {priceWon(intrinsic)}</span> : null}
        {!compact && <span className="ci-lad-key"><i className="ci-lad-sw range" aria-hidden />범위(분포는 10~90%, 모형은 약세~강세 가정)</span>}
      </figcaption>
      <p className="ci-lad-sum">
        {mains.length ? `값을 낸 모형 ${mains.length}개 중 ${below}개가 현재가보다 낮게 봤어요` : "아직 값을 낸 모형이 없어요"}
        {!compact && " · 축은 로그 눈금이에요"}
      </p>
    </figure>
  );
}
