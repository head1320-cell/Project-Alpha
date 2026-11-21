// ═══════════════════════════════════════════════════════════════════════════════
// 단 · 밀도 견본 (ADR 007 §3 · §7) — 카탈로그 `/dev/ui` 와 개발 견본 경로 `/dev/density` 가 함께 쓴다.
//
// ★제품 부품이 아니다★ — 토큰(`--tx-row-h` · `--tx-accent` …)이 뜻대로 도는지 눈과 시험(`e2e/density.spec.ts`)으로 보는 자리다.
// 공용 표는 U1 이 `shared/ui/table` 로 만든다. 여기의 클래스(`.devui-dn-*`)는 견본 전용이다.
//
//  · 상자에 `tier` · `density` 를 주면 그 상자에 속성을 달아 값을 다시 정한다(선택자가 속성만이라 `html` 이 아니어도 걸린다).
//    주지 않으면 조상(개발 견본 경로에서는 `html`)의 값이 내려온다.
//  · `dark` 를 주면 그 상자 안에서만 다크 토큰이 선다(`.dark { --tx-…}` 가 클래스 선택자다) — 개발 화면은 늘 라이트라서다.
//  · 숫자는 손으로 적은 견본 값이다 → 표 위에 `합성` 표시를 단다(어느 밀도에서도 보여야 한다).
// ═══════════════════════════════════════════════════════════════════════════════
import { DENSITIES, TIERS, type Density, type Tier } from "@/shared/ui/density";
import { direction, num, signedPct } from "@/shared/lib/krFormat";
import { Unknown } from "@/shared/ui/tx";

type Row = { code: string; name: string; price: number; chg: number | null; why?: string };

const ROWS: Row[] = [
  { code: "005930", name: "삼성전자", price: 71200, chg: 0.0213 },
  { code: "000660", name: "SK하이닉스", price: 182400, chg: -0.0142 },
  { code: "035420", name: "NAVER", price: 204500, chg: 0 },
  { code: "051910", name: "LG화학", price: 392000, chg: null, why: "거래정지" },
];

const MARK = { up: "▲ ", down: "▼ ", flat: "", unknown: "" } as const;

export function densityLabel(tier: Tier | null, density: Density | null): string {
  const t = TIERS.find(([id]) => id === tier)?.[1];
  const d = DENSITIES.find(([id]) => id === density)?.[1];
  return t && d ? `${t} · ${d}` : "속성 없음";
}

export function DensitySpecimen({ tier, density, dark, bare, caption }: {
  tier?: Tier; density?: Density; dark?: boolean; bare?: boolean; caption?: string;
}) {
  const cls = `devui-dn-box${dark ? " dark" : ""}${bare ? " devui-dn-bare" : ""}`;
  return (
    <div className={cls} data-tier={tier} data-density={density}>
      <div className="devui-dn-cap">
        <span className="devui-dn-cap-t">{caption ?? densityLabel(tier ?? null, density ?? null)}{dark ? " · 다크" : ""}</span>
        <span className="devui-dn-chip">합성</span>
      </div>
      <section className="devui-dn-sec" aria-label="조작 견본">
        <div className="devui-dn-bar">
          <button type="button" className="devui-dn-btn devui-dn-btn--primary">조회</button>
          <button type="button" className="devui-dn-btn">초기화</button>
          <input className="devui-dn-input" aria-label="종목 검색" placeholder="종목명 또는 코드" />
          <a className="devui-dn-link" href="#density">조건 상세</a>
        </div>
      </section>
      <section className="devui-dn-sec" aria-label="표 견본">
        <table className="devui-dn-table" aria-label="밀도 견본 표">
          <thead>
            <tr>
              <th scope="col">종목</th>
              <th scope="col" className="num">현재가(원)</th>
              <th scope="col" className="num">등락률</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map((r) => {
              const dir = direction(r.chg);
              return (
                <tr key={r.code}>
                  <td><span className="devui-dn-name">{r.name}</span> <code className="devui-dn-code">{r.code}</code></td>
                  <td className="num">{num(r.price)}</td>
                  <td className={`num${dir === "up" ? " devui-dn-up" : dir === "down" ? " devui-dn-down" : ""}`}>
                    {r.chg === null ? <Unknown reason={r.why} /> : `${MARK[dir]}${signedPct(r.chg)}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}
