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
      <CompsTable comps={data.comps} selfCode={code} />
    </div>
  );
}

function FootballField({ ff }: { ff: ValuationSandbox["football_field"] }) {
  const bands = ff.bands.filter((b) => b.available !== false && b.lo != null && b.hi != null);
  const unavailable = ff.bands.filter((b) => b.available === false);
  if (!bands.length) return <div className="ca-cp-note">밴드 산출 불가 — 재무 데이터 부족</div>;
  const values = [...bands.flatMap((b) => [b.lo as number, b.hi as number]), ff.current_price];
  const lo = Math.min(...values) * 0.95, hi = Math.max(...values) * 1.05 || 1;
  const X = (v: number) => ((v - lo) / (hi - lo)) * 100;
  const H = bands.length * 34 + 20;
  return (
    <section className="ca-cp-sec">
      <h4>Valuation Football Field <span className="ca-cp-sub">현재가 대비 가치 밴드</span></h4>
      <svg viewBox={`0 0 100 ${H}`} preserveAspectRatio="none" className="ca-ff-svg"
        style={{ width: "100%", height: H * 2.2 }}>
        {bands.map((b, i) => {
          const y = 12 + i * 34;
          const x1 = X(b.lo as number), x2 = Math.max(X(b.hi as number), x1 + 0.6);
          return (
            <g key={b.id}>
              <rect x={x1} y={y} width={x2 - x1} height={14} rx={1}
                className={`ca-ff-band ca-ff-${b.id}`} />
              {b.mid != null && (
                <line x1={X(b.mid)} x2={X(b.mid)} y1={y - 1} y2={y + 15} className="ca-ff-mid" />
              )}
            </g>
          );
        })}
        <line x1={X(ff.current_price)} x2={X(ff.current_price)} y1={2} y2={H - 2}
          className="ca-ff-price" />
      </svg>
      <div className="ca-ff-legend">
        {bands.map((b) => (
          <span key={b.id} className="ca-ff-leg">
            <i className={`ca-ff-dot ca-ff-${b.id}`} />
            {b.label} <b>{fmtW(b.lo)}~{fmtW(b.hi)}</b>{b.note ? ` · ${b.note}` : ""}
          </span>
        ))}
        <span className="ca-ff-leg"><i className="ca-ff-dot ca-ff-cur" />현재가 <b>{fmtW(ff.current_price)}</b></span>
        {unavailable.map((b) => (
          <span key={b.id} className="ca-ff-leg ca-ff-na">{b.label}: {b.note}</span>
        ))}
      </div>
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
  return (
    <section className="ca-cp-sec">
      <h4>민감도 매트릭스 <span className="ca-cp-sub">Ke(행) × g(열) — 초록=현재가 대비 업사이드</span></h4>
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
      <div className="ca-cp-sub" style={{ marginTop: 6 }}>
        — 칸은 영구성장률이 할인율에 근접해 잔존가치(TV)가 발산하는 조합(산출 불가).
      </div>
    </section>
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
