"use client";
// ValuationTab — 가치 자세히: 모형별 가치 범위(풋볼필드) + 가정 바꿔 보기 + 민감도(표/입체) + 업종 안 위치 + 상대가치 표.
// BU6: 기본 가정의 결과(`base`)는 부르는 쪽이 react-query 로 받아 넘긴다(겹친 그림과 같은 응답을 공유 — 요청 하나).
//      가정을 바꾸면 여기서 다시 묻는다(디바운스). 실패는 alert + 다시 시도.
//      글·색: 영어 제목 → 한국어 · 툴팁(`title`·SVG `<title>`) → 보이는 읽기 줄 · 현재가보다 높음/낮음 = 수준 색(판단 색 아님) ·
//      산점도는 비율을 지키는 정사각 SVG(예전엔 `preserveAspectRatio="none"` 으로 점이 타원, 글자가 늘어났다).
import { useEffect, useRef, useState } from "react";
import { X as XIcon } from "lucide-react";
import { companyApi } from "@/entities/company/api";
import { type ValuationSandbox } from "@/entities/company/model";
import { catColor } from "@/shared/ui/vizColor";
import { RetryFail } from "@/shared/ui/tx";

const fmtW = (v: number | null | undefined) =>
  v == null ? "몰라요" : `${Math.round(v).toLocaleString()}원`;
const fmtK = (v: number) => `${Math.round(v / 1000).toLocaleString()}천`;

const SLIDERS: { key: "rf" | "beta" | "erp" | "g" | "years"; label: string;
  min: number; max: number; step: number; pct?: boolean }[] = [
  { key: "rf", label: "무위험수익률(Rf)", min: 0.01, max: 0.08, step: 0.001, pct: true },
  { key: "beta", label: "베타(β, 시장 대비 흔들림)", min: 0.3, max: 2.5, step: 0.05 },
  { key: "erp", label: "시장 위험 프리미엄(ERP)", min: 0.03, max: 0.10, step: 0.001, pct: true },
  { key: "g", label: "영구성장률(g)", min: 0.0, max: 0.04, step: 0.001, pct: true },
  { key: "years", label: "예측 기간(년)", min: 5, max: 15, step: 1 },
];

export default function ValuationTab({ code, base }: { code: string; price: number; base: ValuationSandbox }) {
  const [data, setData] = useState<ValuationSandbox>(base);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [ov, setOv] = useState<Record<string, number>>({});
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const price = base.football_field.current_price;

  useEffect(() => { setData(base); setOv({}); setFailed(false); }, [base]);

  const load = (overrides: Record<string, number>) => {
    setBusy(true);
    companyApi.valuationSandbox(code, price, overrides)
      .then((d) => { setData(d); setFailed(false); })
      .catch(() => setFailed(true))
      .finally(() => setBusy(false));
  };
  const onSlide = (k: string, v: number) => {
    const next = { ...ov, [k]: v };
    setOv(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => load(next), 350);   // 디바운스 재평가
  };

  return (
    <div className="ca-vt" aria-busy={busy} style={{ opacity: busy ? 0.6 : 1, transition: "opacity .15s" }}>
      <FootballField ff={data.football_field} />
      {failed && <RetryFail title="바꾼 가정으로 다시 계산하지 못했어요" onRetry={() => load(ov)} />}
      <div className="ca-vt-grid">
        <AssumptionPanel data={data} ov={ov} onSlide={onSlide}
          onReset={() => { setOv({}); setData(base); setFailed(false); }} />
        <SensitivityHeatmap s={data.sensitivity} />
      </div>
      <RiskReturnScatter scatter={data.comps.scatter ?? []} sector={data.comps.sector} />
      <CompsTable comps={data.comps} selfCode={code} />
    </div>
  );
}

// 같은 업종 안 위치 — X=품질(Altman·Beneish·Sloan 업종 안 백분위 통합), Y=상승 여력(내재가/현재가−1). 점을 누르면 듀폰 3단 분해.
function RiskReturnScatter({ scatter, sector }: {
  scatter: NonNullable<ValuationSandbox["comps"]["scatter"]>; sector?: string;
}) {
  const [popup, setPopup] = useState<{ code: string; name: string; body: string } | null>(null);
  const [cur, setCur] = useState<string | null>(null);
  if (scatter.length < 3) return null;
  const ups = scatter.map((p) => p.upside);
  const yLo = Math.min(-20, ...ups), yHi = Math.max(20, ...ups);
  const X = (q: number) => 8 + (q / 100) * 84;
  const Y = (u: number) => 92 - ((u - yLo) / (yHi - yLo || 1)) * 84;
  const say = (p: { name: string; upside: number; quality: number }) => `${p.name}: 상승 여력 ${p.upside > 0 ? "+" : ""}${p.upside}%, 품질 백분위 ${p.quality}`;

  const onNode = async (p: { code: string; name: string }) => {
    try {
      const fd = await companyApi.financialDeep(p.code);
      const d = fd.dupont;
      const i = d.years.length - 1;
      const v = (x: number | null | undefined) => (x == null ? "몰라요" : String(x));
      const body = i >= 0
        ? `${d.years[i]}년 ROE ${v(d.roe[i])}% = 순이익률 ${v(d.net_margin[i])}% × 자산회전율 ${v(d.asset_turnover[i])} × 레버리지 ${v(d.leverage[i])}`
        : "듀폰 분해 자료가 없어요(재무 시계열이 적재되지 않았어요)";
      setPopup({ code: p.code, name: p.name, body });
    } catch {
      setPopup({ code: p.code, name: p.name, body: "듀폰 분해를 불러오지 못했어요. 점을 다시 눌러 보세요." });
    }
  };

  return (
    <section className="ca-cp-sec ca-rr" style={{ position: "relative" }}>
      <h4>같은 업종 안 위치</h4>
      <p className="ca-cp-sub"><span data-server>{sector ?? ""}</span> 업종. 가로 = 품질(업종 안 백분위), 세로 = 상승 여력. 점을 누르면 ROE 를 셋으로 나눠 보여요.</p>
      <svg viewBox="0 0 100 100" className="ca-rr-svg" role="img" aria-label={`업종 ${scatter.length}개 기업의 품질과 상승 여력`}>
        <line x1={50} x2={50} y1={8} y2={92} className="ca-rr-axis" />
        <line x1={8} x2={92} y1={Y(0)} y2={Y(0)} className="ca-rr-axis" />
        <text x={91} y={11} className="ca-rr-qlabel" textAnchor="end">품질 높음, 상승 여력 큼</text>
        <text x={9} y={11} className="ca-rr-qlabel">품질 낮음, 상승 여력 큼</text>
        <text x={91} y={97} className="ca-rr-qlabel" textAnchor="end">품질 높음, 상승 여력 작음</text>
        <text x={9} y={97} className="ca-rr-qlabel">품질 낮음, 상승 여력 작음</text>
        {scatter.map((p) => (
          <g key={p.code} onClick={() => onNode(p)} style={{ cursor: "pointer" }} tabIndex={0} role="button" aria-label={say(p)}
             onMouseEnter={() => setCur(say(p))} onFocus={() => setCur(say(p))}
             onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNode(p); } }}>
            <circle cx={X(p.quality)} cy={Y(p.upside)} r={p.self ? 2.6 : 1.8} className={p.self ? "ca-rr-node self" : "ca-rr-node"} />
            {p.self && <text x={X(p.quality) + 3.5} y={Y(p.upside) + 1.2} className="ca-rr-name">{p.name}</text>}
          </g>
        ))}
      </svg>
      <p className="ca-heat-read" aria-live="polite">{cur ?? "점에 마우스를 올리거나 Tab 으로 고르면 여기에 값이 나와요"}</p>
      {popup && (
        <div className="ca-rr-popup" role="dialog" aria-label={`${popup.name} 듀폰 분해`}>
          <b>{popup.name}</b>
          <button type="button" aria-label="닫기" onClick={() => setPopup(null)}><XIcon size={14} aria-hidden /></button>
          <div>{popup.body}</div>
        </div>
      )}
    </section>
  );
}

function FootballField({ ff }: { ff: ValuationSandbox["football_field"] }) {
  const P = ff.current_price;
  const all = ff.bands.filter((b) => b.available !== false && b.lo != null && b.hi != null);
  const unavailable = ff.bands.filter((b) => b.available === false);
  if (!all.length) return <p className="ca-cp-note">모형별 가치 범위를 낼 수 없어요(재무 자료가 부족해요).</p>;

  // 로버스트 축: 현재가와 극단 괴리(4배↑/0.15배↓) 밴드는 축 계산에서 제외하고 그림 밖 목록에 적는다
  // — 그레이엄 넘버 같은 아웃라이어 1개가 차트를 뭉개는 것 방지(겹친 그림과 같은 규칙).
  const inRange = all.filter((b) => (b.lo as number) <= P * 4 && (b.hi as number) >= P * 0.15);
  const outliers = all.filter((b) => !inRange.includes(b));
  const shown = inRange.length ? inRange : all;
  const values = [...shown.flatMap((b) => [b.lo as number, b.hi as number]), P];
  const lo = Math.min(...values) * 0.93;
  const hi = Math.max(...values) * 1.07 || 1;
  const X = (v: number) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
  const ticks = [lo, (lo + hi) / 2, hi];

  return (
    <section className="ca-cp-sec">
      <h4>모형별 가치 범위(풋볼필드)</h4>
      <p className="ca-cp-sub">세로 점선이 현재가예요. 막대 안의 금은 가운데 값이에요.</p>
      <div className="ca-ff2">
        {/* 현재가 기준선 (전 행 관통) */}
        <div className="ca-ff2-price" style={{ left: `calc(168px + (100% - 258px) * ${X(P) / 100})` }}>
          <span className="ca-ff2-price-tag">현재가 {fmtW(P)}</span>
        </div>
        {shown.map((b, i) => {
          const x1 = X(b.lo as number), x2 = Math.max(X(b.hi as number), x1 + 0.8);
          return (
            <div key={b.id} className="ca-ff2-row">
              <span className="ca-ff2-label" data-server>{b.label}</span>
              <div className="ca-ff2-track">
                <div className="ca-ff2-bar" style={{ left: `${x1}%`, width: `${x2 - x1}%`, background: catColor(i) }}>
                  {b.mid != null && (b.mid as number) >= (b.lo as number) && (
                    <i className="ca-ff2-mid" style={{
                      left: `${(((b.mid as number) - (b.lo as number)) /
                        Math.max(1e-9, (b.hi as number) - (b.lo as number))) * 100}%` }} />
                  )}
                </div>
              </div>
              <span className="ca-ff2-val">{fmtW(b.lo)}~{fmtW(b.hi)}</span>
            </div>
          );
        })}
        {/* 축 눈금 */}
        <div className="ca-ff2-row ca-ff2-axis">
          <span className="ca-ff2-label" />
          <div className="ca-ff2-track" style={{ border: "none", background: "none" }}>
            {ticks.map((t, i) => (
              <span key={i} className="ca-ff2-tick" style={{ left: `${X(t)}%` }}>{fmtK(t)}</span>
            ))}
          </div>
          <span className="ca-ff2-val" />
        </div>
      </div>
      {shown.some((b) => b.note) && (
        <ul className="ca-ff-notes">
          {shown.filter((b) => b.note).map((b) => <li key={b.id}><b data-server>{b.label}</b> <span data-server>{b.note}</span></li>)}
        </ul>
      )}
      {(outliers.length > 0 || unavailable.length > 0) && (
        <ul className="ca-ff-legend">
          {outliers.map((b) => (
            <li key={b.id} className="ca-ff-leg ca-ff-na">
              <span data-server>{b.label}</span> {fmtW(b.lo)}{b.lo !== b.hi ? `~${fmtW(b.hi)}` : ""}: 현재가와 너무 멀어 그림 밖에 적었어요(원천 자료를 확인해 보세요)
            </li>
          ))}
          {unavailable.map((b) => (
            <li key={b.id} className="ca-ff-leg ca-ff-na"><span data-server>{b.label}</span>: <span data-server>{b.note}</span></li>
          ))}
        </ul>
      )}
    </section>
  );
}

function AssumptionPanel({ data, ov, onSlide, onReset }: {
  data: ValuationSandbox; ov: Record<string, number>;
  onSlide: (k: string, v: number) => void; onReset: () => void;
}) {
  const byKey = Object.fromEntries(data.assumptions.map((a) => [a.key, a]));
  const ke = byKey["ke"]?.value as number | undefined;
  return (
    <section className="ca-cp-sec">
      <h4>가정 바꿔 보기 <button type="button" className="ca-vt-reset" onClick={onReset}>처음 값으로</button></h4>
      {SLIDERS.map((s) => {
        const a = byKey[s.key];
        const cur = ov[s.key] ?? (a?.value as number) ?? s.min;
        return (
          <div key={s.key} className="ca-vt-slider">
            <label className="ca-vt-slabel" htmlFor={`vt-${s.key}`}>
              <span>{s.label}</span>
              <b>{s.pct ? `${(cur * 100).toFixed(1)}%` : cur}</b>
              <em className="ca-vt-src" data-server>{a?.source ?? ""}</em>
            </label>
            <input id={`vt-${s.key}`} type="range" min={s.min} max={s.max} step={s.step} value={cur}
              onChange={(e) => onSlide(s.key, Number(e.target.value))} />
          </div>
        );
      })}
      <dl className="ca-vt-derived">
        <div><dt>자기자본비용(Ke, 도출)</dt><dd>{ke == null ? "몰라요" : `${(ke * 100).toFixed(2)}%`}</dd></div>
        <div><dt>적정가</dt><dd>{fmtW(data.unified.value)}</dd></div>
        <div><dt>현재가와 차이</dt><dd>{data.unified.gap_pct > 0 ? "+" : ""}{data.unified.gap_pct.toFixed(1)}%</dd></div>
        <div><dt>판정</dt><dd data-server>{data.unified.verdict}</dd></div>
      </dl>
    </section>
  );
}

function SensitivityHeatmap({ s }: { s: ValuationSandbox["sensitivity"] }) {
  const [mode, setMode] = useState<"2d" | "3d">("2d");
  const [cur, setCur] = useState<string | null>(null);
  const say = (i: number, j: number, v: number | null) =>
    `자기자본비용 ${(s.ke_axis[i] * 100).toFixed(1)}%, 영구성장률 ${(s.g_axis[j] * 100).toFixed(1)}%: ${v == null ? "잔존가치가 발산해 계산할 수 없어요" : `적정가 ${fmtW(v)}`}`;
  return (
    <section className="ca-cp-sec">
      <h4>가정이 바뀌면 적정가는(민감도)
        <span className="ca-heat-toggle" role="group" aria-label="보기 방식">
          <button type="button" aria-pressed={mode === "2d"} className={mode === "2d" ? "on" : ""} onClick={() => setMode("2d")}>표</button>
          <button type="button" aria-pressed={mode === "3d"} className={mode === "3d" ? "on" : ""} onClick={() => setMode("3d")}>입체</button>
        </span>
      </h4>
      <p className="ca-cp-sub">행 = 자기자본비용(Ke), 열 = 영구성장률(g). 칸 색은 현재가보다 높으면 주황 쪽, 낮으면 청록 쪽이에요.</p>
      {mode === "2d" ? (
        <>
          <div style={{ overflowX: "auto" }}>
            <table className="ca-heat">
              <thead><tr><th scope="col">Ke \ g</th>{s.g_axis.map((g) => <th key={g} scope="col">{(g * 100).toFixed(1)}%</th>)}</tr></thead>
              <tbody>
                {s.grid.map((row, i) => (
                  <tr key={i}>
                    <th scope="row">{(s.ke_axis[i] * 100).toFixed(1)}%</th>
                    {row.map((v, j) => {
                      const cls = v == null ? "na" : v >= s.current_price ? "up" : "dn";
                      return <td key={j} className={`ca-heat-c ${cls}`} tabIndex={0}
                        onMouseEnter={() => setCur(say(i, j, v))} onFocus={() => setCur(say(i, j, v))}>
                        {v == null ? "발산" : fmtK(v)}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="ca-heat-read" aria-live="polite">{cur ?? "칸에 마우스를 올리거나 Tab 으로 고르면 여기에 값이 나와요"}</p>
          <p className="ca-cp-sub">“발산” 칸은 영구성장률이 할인율에 너무 가까워 잔존가치(TV)를 계산할 수 없는 조합이에요.</p>
        </>
      ) : (
        <>
          <SurfaceIso s={s} />
          <p className="ca-cp-sub">높이 = 적정가. 두 가정이 함께 나빠질 때 가치가 절벽처럼 꺾이는 곳(잔존가치 발산 부근)이 보여요.</p>
        </>
      )}
    </section>
  );
}

// Ke×g 등축(isometric) 표면 — 외부 라이브러리 없이 SVG 폴리곤. 뒤→앞 렌더.
function SurfaceIso({ s }: { s: ValuationSandbox["sensitivity"] }) {
  const vals = s.grid.flat().filter((v): v is number => v != null);
  if (!vals.length) return <p className="ca-cp-note">표면을 그릴 수 없어요(모든 칸에서 잔존가치가 발산해요).</p>;
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const CX = 6.5, CY = 3.4, HMAX = 26;   // 등축 셀 폭/깊이, 최대 높이
  const px = (i: number, j: number) => 50 + (j - i) * CX;
  const py = (i: number, j: number, v: number | null) =>
    16 + (i + j) * CY - (v == null ? 0 : ((v - lo) / span) * HMAX) + HMAX;
  const cells: { i: number; j: number; quad: string; up: boolean }[] = [];
  for (let i = 0; i < 4; i++) {
    for (let j = 0; j < 4; j++) {
      const c = [s.grid[i][j], s.grid[i][j + 1], s.grid[i + 1][j + 1], s.grid[i + 1][j]];
      if (c.some((v) => v == null)) continue;   // TV 발산 구멍 — 절벽으로 보인다
      const quad = [
        `${px(i, j)},${py(i, j, c[0])}`, `${px(i, j + 1)},${py(i, j + 1, c[1])}`,
        `${px(i + 1, j + 1)},${py(i + 1, j + 1, c[2])}`, `${px(i + 1, j)},${py(i + 1, j, c[3])}`,
      ].join(" ");
      const avg = (c as number[]).reduce((a, b) => a + b, 0) / 4;
      cells.push({ i, j, quad, up: avg >= s.current_price });
    }
  }
  cells.sort((a, b) => (a.i + a.j) - (b.i + b.j));   // 뒤→앞
  return (
    <svg viewBox="0 0 100 78" className="ca-iso-svg" preserveAspectRatio="xMidYMid meet" role="img" aria-label="자기자본비용과 영구성장률에 따른 적정가 표면">
      {cells.map((c, k) => <polygon key={k} points={c.quad} className={`ca-iso-cell ${c.up ? "up" : "dn"}`} />)}
      <text x={50 - 4 * CX - 2} y={16 + 4 * CY + HMAX + 6} className="ca-rr-qlabel">Ke↑(할인율)</text>
      <text x={50 + 4 * CX - 12} y={16 + 4 * CY + HMAX + 6} className="ca-rr-qlabel">g↑(영구성장)</text>
    </svg>
  );
}

function CompsTable({ comps, selfCode }: { comps: ValuationSandbox["comps"]; selfCode: string }) {
  if (!comps.rows.length) return null;
  const cols: { k: keyof CompsRowLocal; label: string }[] = [
    { k: "mcap", label: "시총(억원)" }, { k: "per", label: "PER(배)" }, { k: "pbr", label: "PBR(배)" },
    { k: "ev_ebitda", label: "EV/EBITDA(배)" }, { k: "roe", label: "ROE(%)" },
    { k: "op_margin", label: "영업이익률(%)" }, { k: "rev_growth", label: "매출 성장(%)" },
  ];
  const num = (v: unknown) => (typeof v === "number" ? v.toLocaleString() : "몰라요");
  return (
    <section className="ca-cp-sec">
      <h4>업종 안 상대가치 비교</h4>
      <p className="ca-cp-sub"><span data-server>{comps.sector ?? ""}</span> 업종 {comps.rows.length - 1}개 기업과 같은 기준으로 놓았어요.</p>
      <div style={{ overflowX: "auto" }}>
        <table className="ca-comps">
          <thead><tr><th scope="col">기업</th>{cols.map((c) => <th key={c.k} scope="col">{c.label}</th>)}</tr></thead>
          <tbody>
            {comps.rows.map((r) => (
              <tr key={r.code} className={r.code === selfCode ? "self" : ""}>
                <td>{r.name}{r.code === selfCode && <span className="ca-cp-self">지금 보는 기업</span>}</td>{cols.map((c) => <td key={c.k}>{num(r[c.k])}</td>)}
              </tr>
            ))}
            <tr className="median"><td>업종 중간값</td>
              {cols.map((c) => <td key={c.k}>{num(comps.median_row[c.k])}</td>)}</tr>
          </tbody>
        </table>
      </div>
      <dl className="ca-comps-implied">
        <div><dt>업종 중간 PER 로 다시 보면</dt><dd>{fmtW(comps.implied.per_based)}</dd></div>
        <div><dt>업종 중간 PBR 로</dt><dd>{fmtW(comps.implied.pbr_based)}</dd></div>
        <div><dt>업종 중간 EV/EBITDA 로</dt><dd>{fmtW(comps.implied.ev_ebitda_based)}</dd></div>
      </dl>
    </section>
  );
}

type CompsRowLocal = ValuationSandbox["comps"]["rows"][number];
