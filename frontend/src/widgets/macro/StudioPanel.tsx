"use client";
/**
 * 서브스튜디오 패널 — 두 엔진을 나란히 (M1-U)
 * ==========================================================================
 * 다섯 라우트가 이 한 컴포넌트를 공유한다. 계약을 다섯 벌 복사하면 반드시 갈라지고,
 * 갈라진 계약은 화면이 "어느 엔진이 낸 값인지" 를 잘못 말하게 한다 — M1-M 이
 * `base.py` 를 둔 것과 같은 이유다.
 *
 * 이 패널이 지키는 것 셋:
 *
 *   1. ★미가용이면 숫자를 하나도 내지 않는다★ 사유만 낸다. 프론티어 엔진은 이
 *      환경에서 전부 미가용이고(torch 미설치 · 표본 60 < 240), `04 TAIL` 은 대체
 *      엔진까지 미가용이다(임계 초과 6 < 최소 8). 그 상태를 0 이나 빈 표로 그리면
 *      "계산했더니 0" 과 구분되지 않는다.
 *   2. ★`span` 을 항상 적는다★ 요청보다 짧으면 응답이 그 사실을 말하도록 서버가
 *      `truncated` 를 낸다(A8 규칙). 화면이 그것을 마저 말하지 않으면 규칙이 절반만
 *      지켜진 것이다.
 *   3. ★`note` 를 접지 않는다★ "그레인저 인과는 개입 인과가 아니다" 같은 문장은
 *      설명이 아니라 **한계**다. A5 가 그은 경계: 설명은 접고 한계는 접지 않는다.
 */

import { useQuery } from "@tanstack/react-query";
import { LoadingState, UnavailableState, ErrorState } from "@/shared/ui/States";
import {
  studiosApi, type StudioDescriptor, type StudioResult, type StudioSpan,
} from "@/entities/macro/studios";

// ─── 출력 렌더 ───────────────────────────────────────────────────────────────
// 스튜디오마다 outputs 의 키가 다르다(k_factors · level/slope/curvature · nodes/edges
// · xi/threshold …). 다섯 벌의 전용 렌더러를 짓는 대신 **값의 모양**으로 나눈다.
// 모르는 모양은 지어내지 않고 접힌 JSON 으로 그대로 보여 준다 — 못생겼지만 정직하다.

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const fmt = (n: number) => (Math.abs(n) >= 1000 || Number.isInteger(n)
  ? n.toLocaleString("ko-KR", { maximumFractionDigits: 3 })
  : n.toFixed(3));

/** 긴 수열은 값 대신 **모양**을 보여 준다. 텍스트가 없으므로 §56 하한과 무관하다. */
function Spark({ values }: { values: number[] }) {
  const n = values.length;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (n - 1)) * 100},${20 - ((v - min) / span) * 20}`);
  return (
    <svg className="ms-spark" viewBox="0 0 100 20" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={pts.join(" ")} fill="none" stroke="var(--t-accent)" strokeWidth="1" />
    </svg>
  );
}

function OutValue({ v }: { v: unknown }) {
  if (v === null || v === undefined) return <span className="ms-out-na">없음</span>;
  if (typeof v === "boolean") return <span className="ms-out-b">{v ? "예" : "아니오"}</span>;
  if (isNum(v)) return <span className="num">{fmt(v)}</span>;
  if (typeof v === "string") return <span>{v}</span>;

  if (Array.isArray(v)) {
    if (v.length === 0) return <span className="ms-out-na">0개</span>;
    if (v.every(isNum)) {
      const a = v as number[];
      if (a.length <= 8) return <span className="num">{a.map(fmt).join(" · ")}</span>;
      return (
        <span className="ms-out-seq">
          <span className="num">{a.length}개 · 마지막 {fmt(a[a.length - 1])}</span>
          <Spark values={a} />
        </span>
      );
    }
    if (v.every((x) => typeof x === "string")) {
      return <span>{(v as string[]).join(" · ")}</span>;
    }
    return (
      <details className="ms-out-more">
        <summary>{v.length}개 항목</summary>
        <pre className="ms-out-pre">{JSON.stringify(v, null, 1)}</pre>
      </details>
    );
  }

  if (typeof v === "object") {
    const e = Object.entries(v as Record<string, unknown>);
    if (e.length && e.every(([, x]) => isNum(x))) {
      return (
        <span className="ms-out-kv">
          {e.map(([k, x]) => (
            <span key={k} className="ms-out-kvi"><em>{k}</em> <b className="num">{fmt(x as number)}</b></span>
          ))}
        </span>
      );
    }
    return (
      <details className="ms-out-more">
        <summary>{e.length}개 필드</summary>
        <pre className="ms-out-pre">{JSON.stringify(v, null, 1)}</pre>
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
        ? `관측 ${span.n}개 / 요청 ${span.requested}개${range} — 요청보다 짧은 구간으로 계산했습니다.`
        : `관측 ${span.n}개 / 요청 ${span.requested}개${range}.`}
    </p>
  );
}

/** 대체 엔진 결과. ★`available` 로 좁히기 전에는 outputs 를 읽을 수 없다★ */
export function StudioOutcome({ res }: { res: StudioResult }) {
  if (!res.available) {
    return (
      <UnavailableState
        label={`${res.engine ?? "대체 엔진"} — 산출 불가`}
        reason={res.reason}
      />
    );
  }
  const rows = Object.entries(res.outputs);
  return (
    <div className="ms-outcome">
      <p className="ms-engine">엔진 <b>{res.engine}</b></p>
      <SpanLine span={res.span} />
      {/* ★한계는 접지 않는다★ */}
      {res.note && <p className="ms-note">{res.note}</p>}
      {rows.length === 0 ? (
        <p className="ms-out-na">이 엔진은 이번 실행에서 산출값을 내지 않았습니다.</p>
      ) : (
        <table className="ms-out">
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k} className="ms-out-row">
                <th scope="row" className="ms-out-k">{k}</th>
                <td className="ms-out-v"><OutValue v={v} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** 프론티어 엔진 — 이 저장소에는 **계약만** 있다. 왜 비어 있는지를 항상 말한다. */
export function FrontierCard({ d }: { d: StudioDescriptor }) {
  const f = d.frontier;
  return (
    <section className="ms-card ms-card-frontier">
      <h2 className="ms-card-t">프론티어 엔진 — {f.name}</h2>
      <p className="ms-card-s">{f.summary}</p>
      {f.available ? (
        <p className="ms-note">
          {f.note ?? "요건은 충족됐지만 이 엔진의 구현은 아직 없습니다 — 계약만 존재합니다."}
        </p>
      ) : (
        <UnavailableState label="이 엔진은 지금 쓸 수 없습니다" reason={f.reason} />
      )}
    </section>
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

  return (
    <div className="ms-studio tpage-fade">
      <header className="ms-head">
        <h1 className="ms-h1">{d ? `${d.label}` : id}</h1>
        {d && <p className="ms-q">{d.question}</p>}
        {d && d.inputs.length > 0 && (
          <p className="ms-inputs num">입력 계열 {d.inputs.join(" · ")}</p>
        )}
      </header>

      {listQ.isLoading && <LoadingState label="스튜디오 계약을 불러오는 중" />}
      {listQ.isError && (
        <ErrorState label="스튜디오 목록에 닿지 못했습니다"
          sub="서버가 미가용이라고 답한 것과 다릅니다 — 응답 자체를 받지 못했습니다." />
      )}
      {d && <FrontierCard d={d} />}

      <section className="ms-card ms-card-sub">
        <h2 className="ms-card-t">
          대체 엔진{d ? ` — ${d.substitute.name}` : ""}
        </h2>
        {d && <p className="ms-card-s">{d.substitute.summary}</p>}
        {runQ.isLoading && <LoadingState label="대체 엔진 실행 중" />}
        {runQ.isError && (
          <ErrorState label="스튜디오 실행에 닿지 못했습니다"
            sub="서버가 미가용이라고 답한 것과 다릅니다 — 응답 자체를 받지 못했습니다." />
        )}
        {runQ.data && <StudioOutcome res={runQ.data} />}
      </section>
    </div>
  );
}

export default StudioPanel;
