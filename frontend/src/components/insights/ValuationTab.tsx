"use client";
// ValuationTab — 실무 밸류에이션: Football Field + 가정 샌드박스 + Ke×g 민감도 + Comps.
// 마운트 시 1콜(valuationSandbox), 슬라이더 변경 시 디바운스 재호출.
import { useCallback, useEffect, useRef, useState } from "react";
import { companyApi, type ValuationSandbox } from "@/lib/screenerApi";

const fmtW = (v: number | null | undefined) =>
  v == null ? "—" : `₩${Math.round(v).toLocaleString()}`;

const SLIDERS: { key: "rf" | "beta" | "erp" | "g" | "years"; label: string;
  min: number; max: number; step: number; pct?: boolean }[] = [
  { key: "rf", label: "무위험수익률 Rf", min: 0.01, max: 0.08, step: 0.001, pct: true },
  { key: "beta", label: "베타 β", min: 0.3, max: 2.5, step: 0.05 },
  { key: "erp", label: "시장프리미엄 ERP", min: 0.03, max: 0.10, step: 0.001, pct: true },
  { key: "g", label: "영구성장률 g", min: 0.0, max: 0.04, step: 0.001, pct: true },
  { key: "years", label: "예측기간(년)", min: 5, max: 15, step: 1 },
];

export default function ValuationTab({ code, price }: { code: string; price: number }) {
  const [data, setData] = useState<ValuationSandbox | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ov, setOv] = useState<Record<string, number>>({});
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback((overrides: Record<string, number>) => {
    setBusy(true);
    companyApi.valuationSandbox(code, price, overrides)
      .then((d) => { setData(d); setErr(null); })
      .catch((e) => setErr(String(e?.message ?? e)))
      .finally(() => setBusy(false));
  }, [code, price]);

  useEffect(() => { load({}); }, [load]);
  const onSlide = (k: string, v: number) => {
    const next = { ...ov, [k]: v };
    setOv(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => load(next), 350);   // 디바운스 재평가
  };

  if (err) return <div className="ca-cp-note">밸류에이션 심화 로드 실패 — {err}</div>;
  if (!data) return <div className="ca-cp-note">밸류에이션 심화 불러오는 중…</div>;

  return (
    <div className="ca-vt" style={{ opacity: busy ? 0.6 : 1, transition: "opacity .15s" }}>
      <FootballField ff={data.football_field} />
      <div className="ca-vt-grid">
        <AssumptionPanel data={data} ov={ov} onSlide={onSlide}
          onReset={() => { setOv({}); load({}); }} />
        <SensitivityHeatmap s={data.sensitivity} />
      </div>
      <RiskReturnScatter scatter={data.comps.scatter ?? []} sector={data.comps.sector} />
      <CompsTable comps={data.comps} selfCode={code} />
    </div>
  );
}

// 리스크-리턴-퀄리티 사분면 (CIO: 딜 성격 1초 정의) — X=퀄리티(Altman·Beneish·Sloan
// 피어 내 백분위 통합), Y=업사이드(내재가/현재가−1). 노드 클릭 → 듀폰 3단 분해 팝업.
function RiskReturnScatter({ scatter, sector }: {
  scatter: NonNullable<ValuationSandbox["comps"]["scatter"]>; sector?: string;
}) {
  const [popup, setPopup] = useState<{ code: string; name: string; body: string } | null>(null);
  if (scatter.length < 3) return null;
  const ups = scatter.map((p) => p.upside);
  const yLo = Math.min(-20, ...ups), yHi = Math.max(20, ...ups);
  const X = (q: number) => (q / 100) * 100;
  const Y = (u: number) => 64 - ((u - yLo) / (yHi - yLo || 1)) * 60;

  const onNode = async (p: { code: string; name: string }) => {
    try {
      const fd = await companyApi.financialDeep(p.code);
      const d = fd.dupont;
      const i = d.years.length - 1;
      const body = i >= 0
        ? `${d.years[i]}년 ROE ${d.roe[i] ?? "—"}% = 순이익률 ${d.net_margin[i] ?? "—"}% × 회전율 ${d.asset_turnover[i] ?? "—"} × 레버리지 ${d.leverage[i] ?? "—"}`
        : "듀폰 분해 데이터 없음 (재무 시계열 미적재)";
      setPopup({ code: p.code, name: p.name, body });
    } catch {
      setPopup({ code: p.code, name: p.name, body: "듀폰 분해 로드 실패" });
    }
  };

  return (
    <section className="ca-cp-sec" style={{ position: "relative" }}>
      <h4>리스크-리턴-퀄리티 매트릭스
        <span className="ca-cp-sub">{sector ?? ""} 피어 · X=퀄리티(백분위) · Y=업사이드% · 노드 클릭=듀폰</span></h4>
      <svg viewBox="0 0 100 68" className="ca-rr-svg" preserveAspectRatio="none">
        <line x1={50} x2={50} y1={2} y2={64} className="ca-rr-axis" />
        <line x1={0} x2={100} y1={Y(0)} y2={Y(0)} className="ca-rr-axis" />
        <text x={97} y={Y(0) - 2} className="ca-rr-qlabel" textAnchor="end">우량·고수익</text>
        <text x={3} y={Y(0) - 2} className="ca-rr-qlabel">저퀄리티·고수익 (투기적)</text>
        <text x={97} y={62} className="ca-rr-qlabel" textAnchor="end">우량·저수익 (안정)</text>
        <text x={3} y={62} className="ca-rr-qlabel">저퀄리티·저수익 (회피)</text>
        {scatter.map((p) => (
          <g key={p.code} onClick={() => onNode(p)} style={{ cursor: "pointer" }}>
            <circle cx={X(p.quality)} cy={Y(p.upside)} r={p.self ? 2.2 : 1.4}
              className={p.self ? "ca-rr-node self" : "ca-rr-node"}>
              <title>{p.name} · 업사이드 {p.upside}% · 퀄리티 {p.quality}</title>
            </circle>
            {p.self && (
              <text x={X(p.quality) + 3} y={Y(p.upside) + 1} className="ca-rr-name">{p.name}</text>
            )}
          </g>
        ))}
      </svg>
      {popup && (
        <div className="ca-rr-popup">
          <b>{popup.name}</b> <button onClick={() => setPopup(null)}>✕</button>
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
  if (!all.length) return <div className="ca-cp-note">밴드 산출 불가 — 재무 데이터 부족</div>;

  // 로버스트 축: 현재가와 극단 괴리(4배↑/0.15배↓) 밴드는 축 계산에서 제외하고
  // '축 범위 밖'으로 정직 표기 — 그레이엄 넘버 같은 아웃라이어 1개가 차트를 뭉개는 것 방지.
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
      <h4>Valuation Football Field <span className="ca-cp-sub">현재가 기준선 대비 가치 밴드 (수평 박스플롯)</span></h4>
      <div className="ca-ff2">
        {/* 현재가 기준선 (전 행 관통) */}
        <div className="ca-ff2-price" style={{ left: `calc(168px + (100% - 258px) * ${X(P) / 100})` }}>
          <span className="ca-ff2-price-tag">현재가 {fmtW(P)}</span>
        </div>
        {shown.map((b) => {
          const x1 = X(b.lo as number), x2 = Math.max(X(b.hi as number), x1 + 0.8);
          const below = (b.hi as number) < P;   // 밴드 전체가 현재가 아래 = 고평가 신호
          return (
            <div key={b.id} className="ca-ff2-row">
              <span className="ca-ff2-label" title={b.note ?? ""}>{b.label}</span>
              <div className="ca-ff2-track">
                <div className={`ca-ff2-bar ca-ff-${b.id}`}
                  style={{ left: `${x1}%`, width: `${x2 - x1}%` }}>
                  {b.mid != null && (b.mid as number) >= (b.lo as number) && (
                    <i className="ca-ff2-mid" style={{
                      left: `${(((b.mid as number) - (b.lo as number)) /
                        Math.max(1e-9, (b.hi as number) - (b.lo as number))) * 100}%` }} />
                  )}
                </div>
              </div>
              <span className={`ca-ff2-val ${below ? "dn" : ""}`}>
                {fmtW(b.lo)} ~ {fmtW(b.hi)}
              </span>
            </div>
          );
        })}
        {/* 축 눈금 */}
        <div className="ca-ff2-row ca-ff2-axis">
          <span className="ca-ff2-label" />
          <div className="ca-ff2-track" style={{ border: "none", background: "none" }}>
            {ticks.map((t, i) => (
              <span key={i} className="ca-ff2-tick" style={{ left: `${X(t)}%` }}>
                {Math.round(t / 1000).toLocaleString()}k
              </span>
            ))}
          </div>
          <span className="ca-ff2-val" />
        </div>
      </div>
      {(outliers.length > 0 || unavailable.length > 0) && (
        <div className="ca-ff-legend" style={{ marginTop: 8 }}>
          {outliers.map((b) => (
            <span key={b.id} className="ca-ff-leg ca-ff-na">
              ⚠ {b.label} {fmtW(b.lo)}{b.lo !== b.hi ? `~${fmtW(b.hi)}` : ""} — 축 범위 밖
              (현재가 대비 극단 괴리 · 원천 데이터 검증 필요)
            </span>
          ))}
          {unavailable.map((b) => (
            <span key={b.id} className="ca-ff-leg ca-ff-na">{b.label}: {b.note}</span>
          ))}
        </div>
      )}
    </section>
  );
}

function AssumptionPanel({ data, ov, onSlide, onReset }: {
  data: ValuationSandbox; ov: Record<string, number>;
  onSlide: (k: string, v: number) => void; onReset: () => void;
}) {
  const byKey = Object.fromEntries(data.assumptions.map((a) => [a.key, a]));
  return (
    <section className="ca-cp-sec">
      <h4>가정 샌드박스 <button className="ca-vt-reset" onClick={onReset}>실측 기본값 복원</button></h4>
      {SLIDERS.map((s) => {
        const a = byKey[s.key];
        const cur = ov[s.key] ?? (a?.value as number) ?? s.min;
        return (
          <div key={s.key} className="ca-vt-slider">
            <div className="ca-vt-slabel">
              <span>{s.label}</span>
              <b>{s.pct ? `${(cur * 100).toFixed(1)}%` : cur}</b>
              <em className="ca-vt-src">{a?.source ?? ""}</em>
            </div>
            <input type="range" min={s.min} max={s.max} step={s.step} value={cur}
              onChange={(e) => onSlide(s.key, Number(e.target.value))} />
          </div>
        );
      })}
      <div className="ca-vt-derived">
        Ke(도출) <b>{(((byKey["ke"]?.value as number) ?? 0) * 100).toFixed(2)}%</b> · 적정가{" "}
        <b>{fmtW(data.unified.value)}</b> · 괴리 <b>{data.unified.gap_pct.toFixed(1)}%</b> ·{" "}
        {data.unified.verdict}
      </div>
    </section>
  );
}

function SensitivityHeatmap({ s }: { s: ValuationSandbox["sensitivity"] }) {
  const [mode, setMode] = useState<"2d" | "3d">("2d");
  return (
    <section className="ca-cp-sec">
      <h4>민감도 매트릭스
        <span className="ca-cp-sub">Ke(행) × g(열) — 초록=현재가 대비 업사이드</span>
        <span className="ca-heat-toggle">
          <button className={mode === "2d" ? "on" : ""} onClick={() => setMode("2d")}>2D</button>
          <button className={mode === "3d" ? "on" : ""} onClick={() => setMode("3d")}>3D 표면</button>
        </span>
      </h4>
      {mode === "2d" ? (
        <div style={{ overflowX: "auto" }}>
          <table className="ca-heat">
            <thead><tr><th>Ke \ g</th>{s.g_axis.map((g) => <th key={g}>{(g * 100).toFixed(1)}%</th>)}</tr></thead>
            <tbody>
              {s.grid.map((row, i) => (
                <tr key={i}>
                  <th>{(s.ke_axis[i] * 100).toFixed(1)}%</th>
                  {row.map((v, j) => {
                    const cls = v == null ? "na" : v >= s.current_price ? "up" : "dn";
                    return <td key={j} className={`ca-heat-c ${cls}`}
                      title={v == null ? "TV 발산 (g≈Ke)" : fmtW(v)}>
                      {v == null ? "—" : `${Math.round(v / 1000).toLocaleString()}k`}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <SurfaceIso s={s} />
      )}
      <div className="ca-cp-sub" style={{ marginTop: 6 }}>
        {mode === "2d"
          ? "— 칸은 영구성장률이 할인율에 근접해 잔존가치(TV)가 발산하는 조합(산출 불가)."
          : "높이=내재가치. Ke·g가 동시에 악화될 때 가치가 절벽처럼 꺾이는 위험 임계점(TV 발산 부근)이 드러남."}
      </div>
    </section>
  );
}

// Ke×g 3D 등축(isometric) 표면 — 외부 라이브러리 없이 SVG 폴리곤. 뒤→앞 렌더.
function SurfaceIso({ s }: { s: ValuationSandbox["sensitivity"] }) {
  const vals = s.grid.flat().filter((v): v is number => v != null);
  if (!vals.length) return <div className="ca-cp-note">표면 산출 불가 (전 칸 TV 발산)</div>;
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const CX = 6.5, CY = 3.4, HMAX = 26;   // 등축 셀 폭/깊이, 최대 높이
  const px = (i: number, j: number) => 50 + (j - i) * CX;
  const py = (i: number, j: number, v: number | null) =>
    16 + (i + j) * CY - (v == null ? 0 : ((v - lo) / span) * HMAX) + HMAX;
  const cells: { i: number; j: number; quad: string; up: boolean }[] = [];
  for (let i = 0; i < 4; i++) {
    for (let j = 0; j < 4; j++) {
      const c = [s.grid[i][j], s.grid[i][j + 1], s.grid[i + 1][j + 1], s.grid[i + 1][j]];
      if (c.some((v) => v == null)) continue;   // TV 발산 구멍 — 절벽으로 시각화됨
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
    <svg viewBox="0 0 100 78" className="ca-iso-svg" preserveAspectRatio="xMidYMid meet">
      {cells.map((c, k) => (
        <polygon key={k} points={c.quad} className={`ca-iso-cell ${c.up ? "up" : "dn"}`}>
          <title>Ke {(s.ke_axis[c.i] * 100).toFixed(1)}~{(s.ke_axis[c.i + 1] * 100).toFixed(1)}% · g {(s.g_axis[c.j] * 100).toFixed(1)}~{(s.g_axis[c.j + 1] * 100).toFixed(1)}%</title>
        </polygon>
      ))}
      <text x={50 - 4 * CX - 2} y={16 + 4 * CY + HMAX + 6} className="ca-rr-qlabel">Ke↑ (할인율)</text>
      <text x={50 + 4 * CX - 12} y={16 + 4 * CY + HMAX + 6} className="ca-rr-qlabel">g↑ (영구성장)</text>
    </svg>
  );
}

function CompsTable({ comps, selfCode }: { comps: ValuationSandbox["comps"]; selfCode: string }) {
  if (!comps.rows.length) return null;
  const cols: { k: keyof CompsRowLocal; label: string }[] = [
    { k: "mcap", label: "시총(억)" }, { k: "per", label: "PER" }, { k: "pbr", label: "PBR" },
    { k: "ev_ebitda", label: "EV/EBITDA" }, { k: "roe", label: "ROE%" },
    { k: "op_margin", label: "영업이익률%" }, { k: "rev_growth", label: "매출성장%" },
  ];
  const num = (v: unknown) => (typeof v === "number" ? v.toLocaleString() : "—");
  return (
    <section className="ca-cp-sec">
      <h4>Comps — 상대가치 매트릭스 <span className="ca-cp-sub">{comps.sector ?? ""} 피어 {comps.rows.length - 1}개</span></h4>
      <div style={{ overflowX: "auto" }}>
        <table className="ca-comps">
          <thead><tr><th>기업</th>{cols.map((c) => <th key={c.k}>{c.label}</th>)}</tr></thead>
          <tbody>
            {comps.rows.map((r) => (
              <tr key={r.code} className={r.code === selfCode ? "self" : ""}>
                <td>{r.name}</td>{cols.map((c) => <td key={c.k}>{num(r[c.k])}</td>)}
              </tr>
            ))}
            <tr className="median"><td>피어 중간값</td>
              {cols.map((c) => <td key={c.k}>{num(comps.median_row[c.k])}</td>)}</tr>
          </tbody>
        </table>
      </div>
      <div className="ca-comps-implied">
        중간값 재평가 암시가: PER 기준 <b>{fmtW(comps.implied.per_based)}</b> · PBR 기준{" "}
        <b>{fmtW(comps.implied.pbr_based)}</b> · EV/EBITDA 기준 <b>{fmtW(comps.implied.ev_ebitda_based)}</b>
      </div>
    </section>
  );
}

type CompsRowLocal = ValuationSandbox["comps"]["rows"][number];
