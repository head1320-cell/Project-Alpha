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

import { useEffect, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { LoadingState, UnavailableState } from "@/shared/ui/States";
import { chartModule, lazyChart } from "@/shared/ui/lazyChart";
import {
  studiosApi, type StudioDescriptor, type StudioResult, type StudioSpan,
} from "@/entities/macro/studios";
import { STUDIO_NAV } from "./StudioNav";
import { Spark as SparkLine } from "@/shared/ui/plot/Spark";
import { IND_KR, STUDIO_OUT_KO, signed } from "./macroKo";
import { ReasonWhy, RetryFail, ServerText } from "./studioBits";
import { CausalGraphView } from "./cockpitParts";

// 이 패널의 선 그림 셋 — recharts 는 차트 파일에서만 import 한다(ADR 004 · 2026-11-10). 화면이 뜬 뒤에 받는다(lazyChart) —
// 예전에는 이 파일이 직접 import 해 스튜디오 네 페이지의 초기 script 에 실려 있었다. 패널이 붙자마자 불러 계산 결과와 같이 오게 한다.
export const loadStudioCharts = chartModule(() => import("./StudioPanel.charts"));
const FactorLines = lazyChart(loadStudioCharts, (m) => m.FactorLines, { height: 200, label: "요인이 지나온 길" });
const CurveLines = lazyChart(loadStudioCharts, (m) => m.CurveLines, { height: 210, label: "곡선의 세 요인" });
const TpLine = lazyChart(loadStudioCharts, (m) => m.TpLine, { height: 170, label: "기간프리미엄 대용" });

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

/** 긴 수열은 값 대신 **모양**을 보여 준다 — 공용 스파크라인(선 1.5px · 끝 점 · 유한한 값이 둘 미만이면 그리지 않는다). */
function Spark({ values }: { values: number[] }) {
  return <SparkLine values={values} w={110} h={18} stroke="var(--tx-blue)" className="ms-spark" />;
}

function OutValue({ v }: { v: unknown }) {
  if (v === null || v === undefined) return <span className="ms-out-na">값 없음</span>;
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
        ? `관측 ${span.n}개 / 요청 ${span.requested}개${range}. 요청보다 짧은 구간으로 계산했습니다.`
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
    return `공통 요인 ${o.k_factors}개가 지표 변화의 ${(o.explained_var * 100).toFixed(1)}%를 설명합니다`;
  }
  if (id === "neural-sde") {
    const l = o.latest as Record<string, unknown> | undefined;
    if (!l || !isNum(l.level) || !isNum(l.slope)) return null;
    const inv = o.inverted === true ? ", 역전됐습니다" : o.inverted === false ? ", 역전되지 않았습니다" : "";
    return `현재 곡선은 수준 ${l.level.toFixed(2)}%, 기울기 ${signed(l.slope)}%p${inv}`;
  }
  if (id === "causal-deepm") {
    const e = Array.isArray(o.edges) ? o.edges.length : null;
    if (e == null || !isNum(o.n_series)) return null;
    return e > 0
      ? `계열 ${o.n_series}개 사이에서 선행 관계 ${e}개를 찾았습니다`
      : `계열 ${o.n_series}개 사이에서 선행 관계를 찾지 못했습니다`;
  }
  if (id === "agentic-mcp") {
    if (!isNum(o.n_views)) return null;
    return `뷰 ${o.n_views}개를 제약으로 변환했습니다${o.feasible === null ? "(모순 검사는 수행하지 않았습니다)" : ""}`;
  }
  return null;
}

function FactorViz({ o }: { o: Outs }) {
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
          <FactorLines rows={rows} k={k} />
          <p className="ms-viz-note">가로축은 관측 순서입니다(서버가 날짜를 제공하지 않았습니다).</p>
        </figure>
      )}
      {load.length > 0 && (
        <figure className="ms-viz-fig ms-viz-load">
          <figcaption>계열별 요인{k > 1 ? " 1" : ""} 적재(요인에 대한 민감도)</figcaption>
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
  const cols = CURVE_KEYS.filter(([k]) => nums(o[k]));
  const n = Math.max(0, ...cols.map(([k]) => nums(o[k])!.length));
  const rows = Array.from({ length: n }, (_, i) => {
    const r: Record<string, number> = { i: i + 1 };
    cols.forEach(([k]) => { const a = nums(o[k])!; if (isNum(a[i])) r[k] = a[i]; });
    return r;
  });
  const tp = nums(o.term_premium_proxy);
  const tpRows = tp ? tp.map((v, i) => ({ i: i + 1, tp: v })) : [];
  return (
    <div className="ms-viz">
      {rows.length > 1 && (
        <figure className="ms-viz-fig ms-viz-curve">
          <figcaption>곡선의 세 요인이 지나온 길(%)</figcaption>
          <CurveLines rows={rows} cols={cols} />
        </figure>
      )}
      {tpRows.length > 1 && (
        <figure className="ms-viz-fig ms-viz-tp">
          <figcaption>기간프리미엄 대용(bp)</figcaption>
          <TpLine rows={tpRows} />
          <p className="ms-viz-note">가로축은 관측 순서입니다. 무차익 조건 없이 추정한 대용치이므로 위험가격이 아닙니다.</p>
        </figure>
      )}
    </div>
  );
}

type Edge = { from: string; to: string; lag: number; p: number };
function CausalViz({ o }: { o: Outs }) {
  const edges = (Array.isArray(o.edges) ? o.edges : []) as Edge[];
  if (!edges.length) return <p className="ms-viz-empty">표시할 관계가 없습니다. 유의한 선행 관계가 확인되지 않았습니다.</p>;
  const given = (Array.isArray(o.nodes) ? o.nodes : []) as { id: string; label?: string }[];
  const ids = given.length ? given.map((n) => n.id) : Array.from(new Set(edges.flatMap((e) => [e.from, e.to])));
  const nodes = ids.map((id) => ({ id, label: IND_KR[id] ?? id }));
  return (
    <div className="ms-viz">
      <figure className="ms-viz-fig ms-viz-causal">
        <figcaption>선행 지표 → 후행 지표</figcaption>
        <CausalGraphView nodes={nodes} edges={edges} />
        <ul className="ms-edges">
          {edges.map((e, i) => (
            <li key={i}>{IND_KR[e.from] ?? e.from} → {IND_KR[e.to] ?? e.to}, {e.lag}개월 선행합니다, 유의확률 {e.p.toFixed(2)}</li>
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
        label={`${res.engine ?? "현재 사용 계산"}: 이번에는 계산할 수 없습니다`}
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
        <p className="ms-out-na">이 엔진은 이번 실행에서 산출값을 내지 않았습니다.</p>
      ) : (
        <div className="ms-out-wrap">
          <p className="ms-out-cap">서버 산출값 전체</p>
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
          {f.note ?? "요건은 충족됐지만 이 엔진의 구현은 아직 없습니다. 계약만 있습니다."}
        </p>
      ) : (
        <UnavailableState label="이 엔진은 현재 사용할 수 없습니다" reason={<ReasonWhy raw={f.reason} rawClass="ms-raw" />} />
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
          <span className="ms-inputs-l">사용 지표</span>
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

  useEffect(() => { loadStudioCharts().catch(() => {}); }, []);   // 차트 코드를 계산 결과와 같이 받는다(못 받으면 그림 자리가 그렇게 말한다)

  const d = listQ.data?.studios.find((s) => s.id === id) ?? null;
  const answer = runQ.data?.available ? studioAnswer(id, runQ.data.outputs) : null;

  return (
    <div className="ms-studio tx-page tx-page--wide tpage-fade">
      <StudioHead id={id} d={d} answer={answer} />

      {listQ.isLoading && <LoadingState label="스튜디오 정보 조회 중" />}
      {listQ.isError && <StudioFail title="스튜디오 정보 조회 실패" onRetry={() => void listQ.refetch()} />}
      {d && <FrontierCard d={d} />}

      <section className="ms-card ms-card-sub">
        <h2 className="ms-card-t">현재 사용 계산{d ? <>: <span data-server>{d.substitute.name}</span></> : ""}</h2>
        {d && <p className="ms-card-s" data-server><ServerText text={d.substitute.summary} /></p>}
        {runQ.isLoading && <LoadingState label="계산 중" />}
        {runQ.isError && <StudioFail title="계산 결과 수신 실패" onRetry={() => void runQ.refetch()} />}
        {runQ.data && <StudioOutcome res={runQ.data} id={id} />}
      </section>
    </div>
  );
}

export default StudioPanel;
