"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// 공용 표 견본 (U1-a · ADR 007 §5) — 카탈로그 `/dev/ui` 의 '공용 표' 절.
//
// 제품이 쓰는 부품(`shared/ui/table`)을 밀도 셋 · 두 테마에서 눈과 시험(`e2e/data-table.spec.ts`)으로 보는 자리다.
//  · 줄은 손으로 적은 일곱 줄이다 → 상자마다 `합성` 표시를 단다. 스펙의 기대값은 이 일곱 줄에서 손으로 계산했다(줄을 고치면 스펙도 함께).
//  · 정렬 · 쪽 · 고른 줄의 상태는 부르는 쪽이 든다(부품은 받은 줄을 그린다) — 스크리너가 쓰는 꼴과 같다.
//  · 상자에 `tier` · `density` 를 주면 그 상자에 속성을 단다(토큰 블록의 선택자가 속성만이라 `html` 이 아니어도 걸린다).
// ═══════════════════════════════════════════════════════════════════════════════
import { useMemo, useState } from "react";
import { num } from "@/shared/lib/krFormat";
import { type Density, type Tier } from "@/shared/ui/density";
import { BarValue, DataTable, Na, Pager, clampPage, nextSort, pageCount, pageSlice, sortRows, type Column, type SortState } from "@/shared/ui/table";
import { densityLabel } from "./DensitySpecimen";

type Row = { code: string; name: string; price: number; per: number | null; score: number; verdict: string };

const ROWS: Row[] = [
  { code: "005930", name: "삼성전자", price: 71200, per: 12.4, score: 88.1, verdict: "저평가" },
  { code: "000660", name: "SK하이닉스", price: 182400, per: null, score: 91.5, verdict: "저평가" },
  { code: "035420", name: "NAVER", price: 204500, per: 31.0, score: 62.3, verdict: "적정" },
  { code: "051910", name: "LG화학", price: 392000, per: 18.7, score: 55.0, verdict: "적정" },
  { code: "005380", name: "현대차", price: 243000, per: 5.6, score: 79.9, verdict: "저평가" },
  { code: "035720", name: "카카오", price: 44350, per: null, score: 40.2, verdict: "고평가" },
  { code: "068270", name: "셀트리온", price: 178900, per: 44.2, score: 47.7, verdict: "고평가" },
];
const SIZE = 5;
const LABEL = "공용 표 견본";

export function TableSpecimen({ tier, density, dark }: { tier?: Tier; density?: Density; dark?: boolean }) {
  const [sort, setSort] = useState<SortState>({ col: "score", dir: "desc" });
  const [page, setPage] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  const [favs, setFavs] = useState<string[]>([]);
  const sorted = useMemo(() => sortRows(ROWS, (r) => r[sort.col as "price" | "per" | "score"], sort.dir), [sort]);
  const cur = clampPage(page, sorted.length, SIZE);
  const base = cur * SIZE;
  const columns: Column<Row>[] = [
    { id: "rank", header: "순위", num: true, width: 48, cell: (_r, i) => base + i + 1 },
    { id: "fav", header: "관심", headerHidden: true, width: 40, cell: (r) => {
      const on = favs.includes(r.code);
      return (
        <button type="button" className="tx-td-btn" aria-pressed={on} aria-label={on ? `${r.name} 관심 종목에서 빼기` : `${r.name} 관심 종목에 넣기`}
                onClick={() => setFavs((f) => (on ? f.filter((c) => c !== r.code) : [...f, r.code]))}>{on ? "★" : "☆"}</button>
      );
    } },
    { id: "name", header: "종목", cell: (r) => <>{r.name}<code className="devui-tb-code">{r.code}</code></> },
    { id: "price", header: "현재가(원)", num: true, sortable: true, cell: (r) => num(r.price) },
    { id: "per", header: "PER(배)", num: true, sortable: true, cell: (r) => (r.per === null ? <Na /> : num(r.per, 1)) },
    { id: "score", header: "종합점수", num: true, sortable: true, cell: (r) => <BarValue ratio={r.score / 100}>{num(r.score, 1)}</BarValue> },
    { id: "verdict", header: "판정", fill: true, cell: (r) => <span className="tx-chip" data-tone="plain">{r.verdict}</span> },
  ];
  return (
    <div className={`devui-tb-box${dark ? " dark" : ""}`} data-tier={tier} data-density={density}>
      <div className="devui-tb-cap">
        <span className="devui-tb-cap-t">{densityLabel(tier ?? null, density ?? null)}{dark ? " · 다크" : ""}</span>
        <span className="devui-tb-chip">합성</span>
      </div>
      <DataTable label={LABEL} columns={columns} rows={pageSlice(sorted, cur, SIZE)} rowKey={(r) => r.code}
                 sort={sort} onSort={(col) => { setSort((s) => nextSort(s, col)); setPage(0); }}
                 selectedKey={picked} onSelect={(key) => setPicked(key)}
                 note="N/A 는 값이 없는 칸입니다(0 이 아닙니다)." />
      <Pager label={`${LABEL} 쪽`} page={cur} count={pageCount(sorted.length, SIZE)} total={sorted.length} size={SIZE} onPage={setPage} />
      <p className="devui-tb-picked">고른 줄: {picked ?? "없음"}</p>
    </div>
  );
}
