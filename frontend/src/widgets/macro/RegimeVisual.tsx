"use client";
/**
 * BU5a+ · 국면 그림 — 도넛 2(한국·미국, 네 국면 전부) + 스트레스 반원 (계획 "BU5a+")
 * ==========================================================================
 * BU5a 가 머리의 도넛 카드를 답 문장으로 바꾸며 그림을 지웠다 — 사용자 규칙 "시각화 도구는 없애지 않는다" 위반이라 다시 짓되 더 낫게:
 *  · 옛 도넛은 1위 국면 한 조각뿐이었다 → 네 국면 확률을 모두 조각으로(나머지 셋이 얼마나 가까운지가 정보다).
 *  · 성장·물가 축은 등락색이 아니라 ★중립 단색 막대★(수준이지 오름/내림이 아니다 — BU5b 규칙).
 *  · 스트레스 반원에는 ★판정 색 띠가 없다★ — 임계값(몇 점부터 위험)은 서버가 주지 않으므로 화면이 만들지 않는다. 판정은 서버
 *    `recommended_mode` 를 글자로 옮길 뿐이다. 구성 항목 점수(0~100)는 서버 `stress_components` 그대로.
 * 그림은 답 문장과 ★같은 서버 값★을 모양으로 보일 뿐 새 판단이 없다(ADR-003 §2.6). 모르면 "몰라요" — 0 으로 그리지 않는다.
 * 색: 국면 4 색 = 범주색(`--mc-q-*`) — dataviz 검증기 all-pairs 라이트·다크 통과(빨강·파랑은 등락색이라 뺐다).
 * 라이트에서 노랑·분홍은 바탕 대비 3:1 미만이라 ★모든 조각에 이름 + % 글자가 붙는다★(색만으로 말하지 않는다).
 */
import type { RegimeState } from "@/entities/macro/api";
import { MODE_KO, regimeName } from "@/entities/macro/regimeKo";
import { pct } from "@/shared/lib/krFormat";
import { Unknown } from "@/shared/ui/tx";
import { IND_KR } from "./visualParts";

/** 사분면 순서(성장↑물가↓ → 성장↑물가↑ → 성장↓물가↑ → 성장↓물가↓) — 고리를 한 바퀴 돌면 국면이 이웃한 순서다. 색은 국면을 따른다(순위가 아니라). */
const QUADS = ["Goldilocks", "Reflation", "Stagflation", "Disinflation"] as const;
const Q_COLOR: Record<string, string> = {
  Goldilocks: "var(--mc-q-goldilocks)", Reflation: "var(--mc-q-reflation)",
  Stagflation: "var(--mc-q-stagflation)", Disinflation: "var(--mc-q-disinflation)",
};

/** 스트레스 구성 항목 이름 — 서버 `_compute_stress` 의 키. 모르는 키는 서버 이름 그대로(지어내지 않는다). */
const STRESS_KO: Record<string, string> = {
  vix: "변동성 지수(VIX)", credit_spread: "신용 스프레드", fx_volatility: "환율 변동성",
  rate_volatility: "금리 변동성", dxy_strength: "달러 강세", yield_curve: "수익률 곡선(10년−2년)", real_rate: "실질 금리",
};

const fin = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const signed = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}`;

// ── 도넛 ────────────────────────────────────────────────────────────────────
const R = 47, SW = 14, C = 2 * Math.PI * R, GAP = 2;   // 조각 사이 2px 바탕 틈

function Donut({ probs, now, label }: { probs: [string, number][] | null; now: string; label: string }) {
  const sum = probs?.reduce((a, [, p]) => a + p, 0) ?? 0;
  let at = 0;
  return (
    <div className="rv-donut" role="img" aria-label={label}>
      <svg viewBox="0 0 120 120" width="144" height="144" aria-hidden>
        <circle cx="60" cy="60" r={R} fill="none" strokeWidth={SW} className={probs && sum > 0 ? "rv-donut-track" : "rv-donut-empty"} />
        {probs && sum > 0 && probs.filter(([, p]) => p > 0).map(([k, p]) => {
          const len = (p / sum) * C;
          const seg = (
            <circle key={k} cx="60" cy="60" r={R} fill="none" strokeWidth={SW}
                    className="rv-donut-seg" data-regime={k} data-sweep={((p / sum) * 360).toFixed(2)}
                    style={{ stroke: Q_COLOR[k] ?? "var(--tx-mute)" }}
                    strokeDasharray={`${Math.max(len - GAP, 0.5)} ${C - Math.max(len - GAP, 0.5)}`}
                    strokeDashoffset={-at} transform="rotate(-90 60 60)" />
          );
          at += len;
          return seg;
        })}
      </svg>
      <div className="rv-donut-c">
        {now && <b>{regimeName(now)}</b>}
        {probs && sum > 0
          ? <span>{pct(probs.find(([k]) => k === now)?.[1] ?? NaN, 0)}</span>
          : <span className="rv-donut-unk">{now ? "확률 몰라요" : "몰라요"}</span>}
      </div>
    </div>
  );
}

function probsOf(st: RegimeState): [string, number][] | null {
  const raw = st.regime_probs;
  if (!raw) return null;
  const known = QUADS.filter((q) => fin(raw[q])).map((q) => [q, raw[q]] as [string, number]);
  const extra = Object.entries(raw).filter(([k, v]) => !(QUADS as readonly string[]).includes(k) && fin(v));
  const all = [...known, ...extra];
  return all.length ? all : null;
}

/** 축 분해에서 가장 크게 움직인 지표(기여 절댓값 1위). 축 분해가 없으면 null — 줄을 그리지 않는다. */
function topDriver(d?: { components?: { key: string; contribution: number }[] }): string | null {
  const c = d?.components?.filter((x) => fin(x.contribution));
  if (!c?.length) return null;
  const top = [...c].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))[0];
  return IND_KR[top.key] ?? top.key;
}

function Axis({ id, label, lo, hi, v }: { id: string; label: string; lo: string; hi: string; v: number }) {
  if (!fin(v)) return null;
  const w = Math.min(Math.abs(v), 1) * 50;   // ±1 을 반 폭으로(넘으면 끝에서 멈춘다 — 숫자는 그대로 보인다)
  return (
    <div className="rv-axis" data-axis={id}>
      <span className="rv-axis-l">{label}</span>
      <span className="rv-axis-track" aria-hidden>
        <i className="rv-axis-bar" style={v >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }} />
      </span>
      <span className="rv-axis-v">{signed(v)}</span>
      <span className="rv-axis-ends" aria-hidden><span>{lo}</span><span>{hi}</span></span>
    </div>
  );
}

function RegimeCard({ market, label, st }: { market: "kr" | "us"; label: string; st: RegimeState | undefined }) {
  if (!st) {
    return (
      <article className="rv-card" data-market={market}>
        <h3 className="rv-t">{label}</h3>
        <div className="rv-row">
          <Donut probs={null} now="" label={`${label} 국면을 받지 못했어요`} />
          <p className="rv-none"><Unknown reason="미국 국면을 받지 못했어요" /></p>
        </div>
      </article>
    );
  }
  const probs = probsOf(st);
  const ranked = probs ? [...probs].sort((a, b) => b[1] - a[1]) : null;
  const gDrv = topDriver(st.axis_detail?.growth), iDrv = topDriver(st.axis_detail?.inflation);
  const desc = `${label} 국면: ${ranked ? ranked.map(([k, p]) => `${regimeName(k)} ${pct(p, 0)}`).join(", ") : "확률 몰라요"}`;
  return (
    <article className="rv-card" data-market={market}>
      <h3 className="rv-t">{label}</h3>
      <div className="rv-row">
        <Donut probs={probs} now={st.regime} label={desc} />
        {ranked ? (
          <ul className="rv-leg">
            {ranked.map(([k, p]) => (
              <li key={k} data-regime={k} data-now={k === st.regime ? "" : undefined}>
                <i style={{ background: Q_COLOR[k] ?? "var(--tx-mute)" }} aria-hidden />
                <span>{regimeName(k)}</span><b>{pct(p, 0)}</b>
              </li>
            ))}
          </ul>
        ) : <p className="rv-none">국면별 확률을 받지 못했어요 — 판정 이름만 보여 드려요.</p>}
      </div>
      <div className="rv-axes">
        <Axis id="growth" label="성장" lo="약해요" hi="강해요" v={st.growth_axis} />
        <Axis id="inflation" label="물가" lo="낮아요" hi="높아요" v={st.inflation_axis} />
      </div>
      {(gDrv || iDrv) && (
        <p className="rv-note">
          가장 크게 움직인 지표{gDrv && <> · 성장 ‘{gDrv}’</>}{iDrv && <> · 물가 ‘{iDrv}’</>}
        </p>
      )}
    </article>
  );
}

// ── 스트레스 반원 ───────────────────────────────────────────────────────────
const GR = 70, GL = Math.PI * GR;   // 반원 길이

function StressCard({ st }: { st: RegimeState }) {
  const s = st.stress_score;
  const known = fin(s);
  const frac = known ? Math.max(0, Math.min(1, s / 100)) : 0;
  const comps = Object.entries(st.stress_components ?? {}).filter(([, v]) => fin(v)).sort((a, b) => b[1] - a[1]);
  const mode = MODE_KO[st.recommended_mode] ?? st.recommended_mode;
  return (
    <article className="rv-card rv-card--stress" data-kind="stress">
      <h3 className="rv-t">시장 스트레스</h3>
      <div className="rv-gauge">
        <svg viewBox="0 0 180 100" width="200" height="111" aria-hidden>
          <path d={`M 20 90 A ${GR} ${GR} 0 0 1 160 90`} className="rv-gauge-track" fill="none" strokeWidth="14" strokeLinecap="round" />
          {known && frac > 0 && (
            <path d={`M 20 90 A ${GR} ${GR} 0 0 1 160 90`} className="rv-gauge-fill" fill="none" strokeWidth="14" strokeLinecap="round"
                  data-frac={frac.toFixed(3)} strokeDasharray={`${frac * GL} ${GL}`} />
          )}
        </svg>
        <div className="rv-gauge-c">
          {known ? <><b className="rv-gauge-v">{Math.round(s)}</b><span>/100</span></> : <Unknown reason="스트레스 값을 받지 못했어요" />}
        </div>
        <div className="rv-gauge-ends" aria-hidden><span>0 · 잔잔해요</span><span>100 · 불안해요</span></div>
      </div>
      <dl className="rv-facts">
        <div><dt>권장 단계</dt><dd>{mode}</dd></div>
        {typeof st.yield_inversion === "boolean" && (
          <div><dt>수익률 곡선</dt><dd>{st.yield_inversion
            ? `역전${fin(st.inversion_severity) ? ` ${Math.round(st.inversion_severity)}bp` : ""}` : "역전 아님"}</dd></div>
        )}
      </dl>
      {comps.length ? (
        <>
          <p className="rv-sub">항목별 점수(0~100, 높을수록 불안) — 가중치를 매겨 합친 값이 위 숫자예요</p>
          <ul className="rv-sc">
            {comps.map(([k, v]) => (
              <li key={k} data-key={k}>
                <span className="rv-sc-n">{STRESS_KO[k] ?? k}</span>
                <span className="rv-sc-track" aria-hidden><i style={{ width: `${Math.max(0, Math.min(100, v))}%` }} /></span>
                <b className="rv-sc-v">{Math.round(v)}</b>
              </li>
            ))}
          </ul>
        </>
      ) : <p className="rv-none">구성 항목 점수를 받지 못했어요.</p>}
    </article>
  );
}

export function RegimeVisual({ regime }: { regime: RegimeState }) {
  const kr = regime.markets?.kr ?? regime;
  return (
    <section className="rv" aria-label="국면 그림">
      <RegimeCard market="kr" label="한국" st={kr} />
      <RegimeCard market="us" label="미국" st={regime.markets?.us} />
      <StressCard st={regime} />
    </section>
  );
}

export default RegimeVisual;
