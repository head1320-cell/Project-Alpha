"use client";
/**
 * 서브스튜디오 패널 — 두 엔진을 나란히 (M1-U → BU5c 토스식)
 * ==========================================================================
 * 다섯 라우트가 이 한 컴포넌트를 공유한다. 계약을 다섯 벌 복사하면 반드시 갈라지고,
 * 갈라진 계약은 화면이 "어느 엔진이 낸 값인지" 를 잘못 말하게 한다 — M1-M 이
 * `base.py` 를 둔 것과 같은 이유다.
 *
 * 이 패널이 지키는 것:
 *
 *   1. ★미가용이면 숫자를 하나도 내지 않는다★ 사유만 낸다. 고급 엔진은 이 환경에서 전부
 *      미가용이고(딥러닝 도구 없음 · 표본 60 < 240), 꼬리 위험은 대체 엔진까지 미가용이다.
 *      그 상태를 0 이나 빈 표로 그리면 "계산했더니 0" 과 구분되지 않는다.
 *   2. ★`span` 을 항상 적는다★ 요청보다 짧으면 응답이 그 사실을 말하도록 서버가
 *      `truncated` 를 낸다(A8 규칙). 화면이 마저 말한다.
 *   3. ★`note` 를 접지 않는다★ "그레인저 인과는 개입 인과가 아니다" 같은 문장은 설명이 아니라 **한계**다.
 *   4. (BU5c) ★원래 사유는 지우지 않는다★ 예외 글("ModuleNotFoundError")은 사람 말 한 줄 아래 "원래 사유 보기" 안에
 *      그대로 둔다. 서버가 답한 "미가용"(사유)과 서버에 닿지 못한 "실패"(alert + 다시 시도)를 가른다.
 *   5. (BU5c) 그림은 더할 뿐 지우지 않는다 — 아래 산출 표(긴 수열 스파크라인 포함)는 그대로 있고, 위에 그림을 얹는다.
 *      답 줄은 서버 값을 틀에 끼운 것이다(새 판단 없음 — ADR-003 §2.6).
 */

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine,
} from "recharts";
import { LoadingState, UnavailableState } from "@/shared/ui/States";
import { useChartAnimation } from "@/shared/ui/chartStyle";
import {
  studiosApi, type StudioDescriptor, type StudioResult, type StudioSpan,
} from "@/entities/macro/studios";
import { STUDIO_NAV } from "./StudioNav";
import { IND_KR, STUDIO_OUT_KO, catColor, signed } from "./macroKo";
import { ReasonWhy, RetryFail, ServerText } from "./studioBits";
import { CausalGraphView, TIP_STYLE } from "./cockpitParts";

/** 스튜디오 id → 한국어 이름(스튜디오 줄·경로 머리와 같은 말). 서버 `label`(LATENT…)은 쓰지 않는다. */
export const studioName = (id: string): string =>
  STUDIO_NAV.find((s) => s.href === `/macro/${id}`)?.label ?? id;

export { ServerText } from "./studioBits";
/** 서버에 닿지 못한 실패 — 미가용(서버가 답한 한계)과 다르다. */
export const StudioFail = RetryFail;

/** 지표 키 → 한국어(모르면 서버 키 그대로, 식별자라 고정폭). */
const keyName = (k: string): ReactNode => (IND_KR[k] ? IND_KR[k] : <span data-mono>{k}</span>);
const outName = (k: string): ReactNode => (STUDIO_OUT_KO[k] ? STUDIO_OUT_KO[k] : <span data-mono>{k}</span>);

// ─── 산출 표 ─────────────────────────────────────────────────────────────────
// 스튜디오마다 outputs 의 키가 다르다. 전용 그림(아래 StudioViz)과 별개로 **값의 모양**으로 모든 키를 그린다 —
// 모르는 모양은 지어내지 않고 접힌 JSON 으로 그대로 보여 준다(못생겼지만 정직하다).

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const fmt = (n: number) => (Math.abs(n) >= 1000 || Number.isInteger(n)
  ? n.toLocaleString("ko-KR", { maximumFractionDigits: 3 })
  : n.toFixed(3));

/** 긴 수열은 값 대신 **모양**을 보여 준다. */
function Spark({ values }: { values: number[] }) {
  const n = values.length;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (n - 1)) * 100},${20 - ((v - min) / span) * 20}`);
  return (
    <svg className="ms-spark" viewBox="0 0 100 20" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={pts.join(" ")} fill="none" stroke="var(--tx-blue)" strokeWidth="1" />
    </svg>
  );
}

function OutValue({ v }: { v: unknown }) {
  if (v === null || v === undefined) return <span className="ms-out-na">값이 없어요</span>;
  if (typeof v === "boolean") return <span className="ms-out-b">{v ? "예" : "아니오"}</span>;
  if (isNum(v)) return <span className="num">{fmt(v)}</span>;
  if (typeof v === "string") return <span data-server>{v}</span>;

  if (Array.isArray(v)) {
    if (v.length === 0) return <span className="ms-out-na">0개</span>;
    if (v.every(isNum)) {
      const a = v as number[];
      if (a.length <= 8) return <span className="num">{a.map(fmt).join(", ")}</span>;
      return (
        <span className="ms-out-seq">
          <span className="num">{a.length}개, 마지막 {fmt(a[a.length - 1])}</span>
          <Spark values={a} />
        </span>
      );
    }
    if (v.every((x) => typeof x === "string")) {
      return (
        <span className="ms-out-list">
          {(v as string[]).map((k, i) => <span key={i} className="ms-out-li">{keyName(k)}</span>)}
        </span>
      );
    }
    return (
      <details className="ms-out-more">
        <summary>{v.length}개 항목</summary>
        <pre className="ms-out-pre" data-mono>{JSON.stringify(v, null, 1)}</pre>
      </details>
    );
  }

  if (typeof v === "object") {
    const e = Object.entries(v as Record<string, unknown>);
    if (e.length && e.every(([, x]) => isNum(x))) {
      return (
        <span className="ms-out-kv">
          {e.map(([k, x]) => (
            <span key={k} className="ms-out-kvi"><em>{outName(k)}</em> <b className="num">{fmt(x as number)}</b></span>
          ))}
        </span>
      );
    }
    return (
      <details className="ms-out-more">
        <summary>{e.length}개 필드</summary>
        <pre className="ms-out-pre" data-mono>{JSON.stringify(v, null, 1)}</pre>
      </details>
    );
  }
  return <span className="ms-out-na">표시할 수 없는 값</span>;
}

function SpanLine({ span }: { span: StudioSpan | null }) {
  if (!span) return null;
  const range = span.first && span.last ? ` (${span.first} ~ ${span.last})` : "";
  return (
    <p className={`ms-span${span.truncated ? " ms-span-trunc" : ""}`}>
      {span.truncated
        ? `관측 ${span.n}개 / 요청 ${span.requested}개${range}. 요청보다 짧은 구간으로 계산했어요.`
        : `관측 ${span.n}개 / 요청 ${span.requested}개${range}.`}
    </p>
  );
}

// ─── 답 줄 · 그림 (스튜디오별) ────────────────────────────────────────────────

type Outs = Record<string, unknown>;
const nums = (v: unknown): number[] | null => (Array.isArray(v) && v.every(isNum) ? (v as number[]) : null);

/** 답 줄 — 서버 값을 정해진 틀에 끼운다. 필요한 값이 없으면 null(지어내지 않는다). */
export function studioAnswer(id: string, o: Outs): string | null {
  if (id === "tsfm-latent") {
    if (!isNum(o.k_factors) || !isNum(o.explained_var)) return null;
    return `공통 요인 ${o.k_factors}개가 지표 변화의 ${(o.explained_var * 100).toFixed(1)}%를 설명해요`;
  }
  if (id === "neural-sde") {
    const l = o.latest as Record<string, unknown> | undefined;
    if (!l || !isNum(l.level) || !isNum(l.slope)) return null;
    const inv = o.inverted === true ? ", 역전됐어요" : o.inverted === false ? ", 역전되지 않았어요" : "";
    return `지금 곡선은 수준 ${l.level.toFixed(2)}%, 기울기 ${signed(l.slope)}%p${inv}`;
  }
  if (id === "causal-deepm") {
    const e = Array.isArray(o.edges) ? o.edges.length : null;
    if (e == null || !isNum(o.n_series)) return null;
    return e > 0
      ? `계열 ${o.n_series}개 사이에서 앞서 움직이는 관계 ${e}개를 찾았어요`
      : `계열 ${o.n_series}개 사이에서 앞서 움직이는 관계를 찾지 못했어요`;
  }
  if (id === "agentic-mcp") {
    if (!isNum(o.n_views)) return null;
    return `뷰 ${o.n_views}개를 제약으로 바꿨어요${o.feasible === null ? "(모순 검사는 하지 않았어요)" : ""}`;
  }
  return null;
}

function FactorViz({ o }: { o: Outs }) {
  const anim = useChartAnimation();
  const f = Array.isArray(o.factors) ? (o.factors as unknown[]) : [];
  const k = isNum(o.k_factors) ? o.k_factors : 1;
  const rows = f.map((r, i) => {
    const row: Record<string, number> = { i: i + 1 };
    (Array.isArray(r) ? r : [r]).forEach((x, j) => { if (isNum(x)) row[`f${j + 1}`] = x; });
    return row;
  });
  const load = Object.entries((o.loadings ?? {}) as Record<string, unknown>)
    .map(([key, v]) => [key, Array.isArray(v) ? v[0] : v] as const)
    .filter((x): x is readonly [string, number] => isNum(x[1]));
  const maxAbs = Math.max(1e-9, ...load.map(([, v]) => Math.abs(v)));
  return (
    <div className="ms-viz">
      {rows.length > 1 && (
        <figure className="ms-viz-fig ms-viz-factor">
          <figcaption>요인이 지나온 길</figcaption>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={rows} margin={{ top: 6, right: 10, bottom: 2, left: 0 }}>
              <XAxis dataKey="i" tick={{ fontSize: 11, fill: "var(--tx-sub)" }} stroke="var(--tx-line)" interval={Math.max(0, Math.floor(rows.length / 6))} />
              <YAxis width={36} tick={{ fontSize: 11, fill: "var(--tx-sub)" }} stroke="var(--tx-line)" />
              <ReferenceLine y={0} stroke="var(--tx-mute)" />
              <Tooltip contentStyle={TIP_STYLE} formatter={(v: number, n: string) => [signed(Number(v), 3), `요인 ${n.slice(1)}`]} labelFormatter={(l) => `관측 ${l}번째`} />
              {Array.from({ length: k }, (_, j) => (
                <Line key={j} dataKey={`f${j + 1}`} stroke={k === 1 ? "var(--tx-blue)" : catColor(j)} strokeWidth={2} dot={false} isAnimationActive={anim} />
              ))}
            </LineChart>
          </ResponsiveContainer>
          <p className="ms-viz-note">가로축은 관측 순서예요(서버가 날짜를 주지 않았어요).</p>
        </figure>
      )}
      {load.length > 0 && (
        <figure className="ms-viz-fig ms-viz-load">
          <figcaption>계열마다 요인{k > 1 ? " 1" : ""}과 함께 움직이는 정도(적재)</figcaption>
          <ul className="ms-load">
            {load.map(([key, v]) => (
              <li key={key} className="ms-load-row">
                <span className="ms-load-n">{keyName(key)}</span>
                <span className="ms-load-track" aria-hidden>
                  <i className={v >= 0 ? "pos" : "neg"} style={{ width: `${(Math.abs(v) / maxAbs) * 50}%` }} />
                </span>
                <b className="ms-load-v">{signed(v, 3)}</b>
              </li>
            ))}
          </ul>
        </figure>
      )}
    </div>
  );
}

const CURVE_KEYS: [string, string][] = [["level", "수준"], ["slope", "기울기"], ["curvature", "곡률"]];
function CurveViz({ o }: { o: Outs }) {
  const anim = useChartAnimation();
  const cols = CURVE_KEYS.filter(([k]) => nums(o[k]));
  const n = Math.max(0, ...cols.map(([k]) => nums(o[k])!.length));
  const rows = Array.from({ length: n }, (_, i) => {
    const r: Record<string, number> = { i: i + 1 };
    cols.forEach(([k]) => { const a = nums(o[k])!; if (isNum(a[i])) r[k] = a[i]; });
    return r;
  });
  const tp = nums(o.term_premium_proxy);
  const tpRows = tp ? tp.map((v, i) => ({ i: i + 1, tp: v })) : [];
  const axis = { tick: { fontSize: 11, fill: "var(--tx-sub)" }, stroke: "var(--tx-line)" };
  return (
    <div className="ms-viz">
      {rows.length > 1 && (
        <figure className="ms-viz-fig ms-viz-curve">
          <figcaption>곡선의 세 요인이 지나온 길(%)</figcaption>
          <ResponsiveContainer width="100%" height={210}>
            <LineChart data={rows} margin={{ top: 6, right: 10, bottom: 2, left: 0 }}>
              <XAxis dataKey="i" {...axis} interval={Math.max(0, Math.floor(rows.length / 6))} />
              <YAxis width={36} {...axis} />
              <ReferenceLine y={0} stroke="var(--tx-mute)" />
              <Tooltip contentStyle={TIP_STYLE} formatter={(v: number, k: string) => [Number(v).toFixed(2), CURVE_KEYS.find(([x]) => x === k)?.[1] ?? k]} labelFormatter={(l) => `관측 ${l}번째`} />
              {cols.map(([k], j) => <Line key={k} dataKey={k} stroke={catColor(j)} strokeWidth={2} dot={false} isAnimationActive={anim} />)}
            </LineChart>
          </ResponsiveContainer>
          <ul className="mc-legend">
            {cols.map(([k, ko], j) => <li key={k}><i style={{ background: catColor(j) }} aria-hidden />{ko}</li>)}
          </ul>
        </figure>
      )}
      {tpRows.length > 1 && (
        <figure className="ms-viz-fig ms-viz-tp">
          <figcaption>기간프리미엄 대용(bp)</figcaption>
          <ResponsiveContainer width="100%" height={170}>
            <LineChart data={tpRows} margin={{ top: 6, right: 10, bottom: 2, left: 0 }}>
              <XAxis dataKey="i" {...axis} interval={Math.max(0, Math.floor(tpRows.length / 6))} />
              <YAxis width={40} {...axis} />
              <ReferenceLine y={0} stroke="var(--tx-mute)" />
              <Tooltip contentStyle={TIP_STYLE} formatter={(v: number) => [Number(v).toFixed(1), "기간프리미엄 대용"]} labelFormatter={(l) => `관측 ${l}번째`} />
              <Line dataKey="tp" stroke="var(--tx-blue)" strokeWidth={2} dot={false} isAnimationActive={anim} />
            </LineChart>
          </ResponsiveContainer>
          <p className="ms-viz-note">가로축은 관측 순서예요. 무차익 조건 없이 잰 대용값이라 위험가격이 아니에요.</p>
        </figure>
      )}
    </div>
  );
}

type Edge = { from: string; to: string; lag: number; p: number };
function CausalViz({ o }: { o: Outs }) {
  const edges = (Array.isArray(o.edges) ? o.edges : []) as Edge[];
  if (!edges.length) return <p className="ms-viz-empty">그릴 관계가 없어요. 유의한 앞섬 관계가 하나도 나오지 않았어요.</p>;
  const given = (Array.isArray(o.nodes) ? o.nodes : []) as { id: string; label?: string }[];
  const ids = given.length ? given.map((n) => n.id) : Array.from(new Set(edges.flatMap((e) => [e.from, e.to])));
  const nodes = ids.map((id) => ({ id, label: IND_KR[id] ?? id }));
  return (
    <div className="ms-viz">
      <figure className="ms-viz-fig ms-viz-causal">
        <figcaption>먼저 움직이는 지표 → 따라 움직이는 지표</figcaption>
        <CausalGraphView nodes={nodes} edges={edges} />
        <ul className="ms-edges">
          {edges.map((e, i) => (
            <li key={i}>{IND_KR[e.from] ?? e.from} → {IND_KR[e.to] ?? e.to}, {e.lag}개월 앞서요, 유의확률 {e.p.toFixed(2)}</li>
          ))}
        </ul>
      </figure>
    </div>
  );
}

function ViewsViz({ o }: { o: Outs }) {
  const human = Array.isArray(o.human) ? (o.human as string[]) : [];
  if (!human.length) return null;
  return (
    <div className="ms-viz">
      <figure className="ms-viz-fig">
        <figcaption>컴파일한 제약</figcaption>
        <ul className="ms-view-rules">
          {human.map((h, i) => <li key={i} className="ms-view-rule" data-mono>{h}</li>)}
        </ul>
      </figure>
    </div>
  );
}

function StudioViz({ id, o }: { id: string; o: Outs }) {
  if (id === "tsfm-latent") return <FactorViz o={o} />;
  if (id === "neural-sde") return <CurveViz o={o} />;
  if (id === "causal-deepm") return <CausalViz o={o} />;
  if (id === "agentic-mcp") return <ViewsViz o={o} />;
  return null;
}

/** 대체 엔진 결과. ★`available` 로 좁히기 전에는 outputs 를 읽을 수 없다★ */
export function StudioOutcome({ res, id }: { res: StudioResult; id: string }) {
  if (!res.available) {
    return (
      <UnavailableState
        label={`${res.engine ?? "지금 쓰는 계산"}: 이번에는 계산할 수 없어요`}
        reason={<span data-server><ServerText text={res.reason} /></span>}
      />
    );
  }
  const rows = Object.entries(res.outputs);
  return (
    <div className="ms-outcome">
      <SpanLine span={res.span} />
      {/* ★한계는 접지 않는다★ */}
      {res.note && <p className="ms-note" data-server><ServerText text={res.note} /></p>}
      <StudioViz id={id} o={res.outputs} />
      {rows.length === 0 ? (
        <p className="ms-out-na">이 엔진은 이번 실행에서 산출값을 내지 않았어요.</p>
      ) : (
        <div className="ms-out-wrap">
          <p className="ms-out-cap">서버가 낸 값 모두</p>
          <table className="ms-out">
            <tbody>
              {rows.map(([k, v]) => (
                <tr key={k} className="ms-out-row">
                  <th scope="row" className="ms-out-k">{outName(k)}</th>
                  <td className="ms-out-v"><OutValue v={v} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** 고급(프론티어) 엔진 — 이 저장소에는 **계약만** 있다. 왜 비어 있는지를 항상 말한다. */
export function FrontierCard({ d }: { d: StudioDescriptor }) {
  const f = d.frontier;
  return (
    <section className="ms-card ms-card-frontier">
      <h2 className="ms-card-t">고급 엔진: <span data-server>{f.name}</span></h2>
      <p className="ms-card-s" data-server><ServerText text={f.summary} /></p>
      {f.available ? (
        <p className="ms-note" data-server>
          {f.note ?? "요건은 충족됐지만 이 엔진의 구현은 아직 없어요. 계약만 있어요."}
        </p>
      ) : (
        <UnavailableState label="이 엔진은 지금 쓸 수 없어요" reason={<ReasonWhy raw={f.reason} rawClass="ms-raw" />} />
      )}
    </section>
  );
}

/** 머리 — 한국어 이름 · 서버 질문 · 입력 계열 칩 · 답 줄. */
export function StudioHead({ id, d, answer }: { id: string; d: StudioDescriptor | null; answer: string | null }) {
  return (
    <header className="ms-head">
      <h1 className="ms-h1">{studioName(id)}</h1>
      {d && <p className="ms-q" data-server>{d.question}</p>}
      {d && d.inputs.length > 0 && (
        <div className="ms-inputs">
          <span className="ms-inputs-l">쓰는 지표</span>
          <ul className="ms-in-list">
            {d.inputs.map((k) => <li key={k} className="ms-in-chip">{keyName(k)}</li>)}
          </ul>
        </div>
      )}
      {answer && <p className="ms-answer">{answer}</p>}
    </header>
  );
}

export function StudioPanel({ id, months = 60 }: { id: string; months?: number }) {
  const listQ = useQuery({
    queryKey: ["macro", "studios"],
    queryFn: () => studiosApi.list(),
    staleTime: 60_000,
  });
  const runQ = useQuery({
    queryKey: ["macro", "studio", id, months],
    queryFn: () => studiosApi.run(id, months),
  });

  const d = listQ.data?.studios.find((s) => s.id === id) ?? null;
  const answer = runQ.data?.available ? studioAnswer(id, runQ.data.outputs) : null;

  return (
    <div className="ms-studio tx-page tx-page--wide tpage-fade">
      <StudioHead id={id} d={d} answer={answer} />

      {listQ.isLoading && <LoadingState label="스튜디오 정보를 불러오는 중이에요" />}
      {listQ.isError && <StudioFail title="스튜디오 정보를 불러오지 못했어요" onRetry={() => void listQ.refetch()} />}
      {d && <FrontierCard d={d} />}

      <section className="ms-card ms-card-sub">
        <h2 className="ms-card-t">지금 쓰는 계산{d ? <>: <span data-server>{d.substitute.name}</span></> : ""}</h2>
        {d && <p className="ms-card-s" data-server><ServerText text={d.substitute.summary} /></p>}
        {runQ.isLoading && <LoadingState label="계산하는 중이에요" />}
        {runQ.isError && <StudioFail title="계산 결과를 받지 못했어요" onRetry={() => void runQ.refetch()} />}
        {runQ.data && <StudioOutcome res={runQ.data} id={id} />}
      </section>
    </div>
  );
}

export default StudioPanel;
