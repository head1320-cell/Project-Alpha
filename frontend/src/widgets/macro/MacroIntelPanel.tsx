"use client";

/**
 * P4 매크로 지능 패널 — 국면 합의 · 예측 적중률 · 장기관계 · 데이터 출처 (→ BU5c 토스식)
 * ==========================================================================
 * D1~D5 와 M1~M3 가 만든 것을 **화면이 처음으로 보는 자리**다. 네 블록 전부 같은 규칙을 따른다:
 *
 *   1. 서버가 "미가용"이라고 답하면 숫자를 하나도 내지 않고 **사유만** 낸다(사유 배지).
 *   2. 결론 옆에 그 결론의 **전제**를 적는다(어느 모형·어느 기준·어느 도구).
 *   3. 경고와 한계는 접지 않는다 — A5 가 그은 경계 그대로다.
 *   4. (BU5c) ★서버에 닿지 못한 실패는 미가용과 가른다★ — 예전엔 둘 다 "산출 불가" 배지였다.
 *      실패는 그 블록 안 alert + [다시 시도].
 *
 * ★적중률과 집합 크기를 같이 낸다★ 집합을 키우면 적중률은 언제든 올라가므로,
 * 적중률만 보여 주면 화면이 "잘 맞힌다" 는 거짓 인상을 만든다.
 * (BU5c) 그림을 더했다 — 공적분 검정 통계량 막대(95% 임계 눈금) · 적중률 막대(목표 눈금). 표·숫자는 그대로다.
 */

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { EvidenceBadge } from "@/shared/ui/evidence";
import { macroIntelApi } from "@/entities/macro/studios";
import { regimeName } from "@/entities/macro/regimeKo";
import { IND_KR, TOOL_KO } from "./macroKo";
import { ReasonWhy, RetryFail } from "./studioBits";

/**
 * 미가용 — 서버가 답한 한계. 숫자 대신 오는 것.
 * `EvidenceBadge` 는 `kind="unavailable"` 일 때 `reason` 을 **필수**로 요구한다(판별 유니온) — 우회하지 않는다.
 */
function Reason({ text }: { text: string }) {
  return (
    <div className="mx-reason">
      <EvidenceBadge kind="unavailable" reason={<span data-server>{text}</span>}>지금은 못 재요</EvidenceBadge>
    </div>
  );
}

/** 블록 껍데기 — 제목은 늘 남고, 안이 불러오는 중 · 실패 · 값 셋 중 하나다. */
function Block({ title, q, loading, fail, children }: {
  title: string; q: { isLoading: boolean; isError: boolean; refetch: () => unknown };
  loading: string; fail: string; children: () => ReactNode;
}) {
  return (
    <section className="mx-card">
      <h3 className="mx-card-t">{title}</h3>
      {q.isLoading ? <div className="mx-loading">{loading}</div>
        : q.isError ? <RetryFail title={fail} onRetry={() => void q.refetch()} />
        : children()}
    </section>
  );
}

const varName = (k: string): ReactNode => (IND_KR[k] ? IND_KR[k] : <span data-mono>{k}</span>);

/** D5 — 데이터 출처 + 이 키를 넣으면 무엇이 열리는가 */
function CoverageBlock() {
  const q = useQuery({
    queryKey: ["macro", "source-coverage"],
    queryFn: () => macroIntelApi.sourceCoverage(true),
  });
  return (
    <Block title="데이터 출처가 어디까지 열렸는지" q={q} loading="데이터 출처를 확인하는 중이에요"
           fail="데이터 출처를 불러오지 못했어요">
      {() => {
        if (!q.data) return null;
        const { providers, keys, ladder } = q.data;
        return (
          <>
            {ladder && (
              <div className="mx-ladder">
                <p>지금 분석 단계는 <b>레벨 {ladder.level}</b>이에요. 레벨은 L0 이 가장 높아요.</p>
                {ladder.note && <p className="mx-why" data-server>{ladder.note}</p>}
                {ladder.blocked_level && ladder.blocked_reason && (
                  <div className="mx-ladder-why">
                    <p className="mx-sub">레벨 {ladder.blocked_level}로 올라가지 못한 이유</p>
                    <ReasonWhy raw={ladder.blocked_reason} rawClass="mx-raw" />
                  </div>
                )}
              </div>
            )}
            <div className="mx-tblwrap">
              <table className="mx-tbl">
                <thead>
                  <tr>
                    <th scope="col">제공자</th>
                    <th scope="col">선언한 계열</th>
                    <th scope="col">확인한 계열</th>
                    <th scope="col">과거 시험에 쓰기</th>
                  </tr>
                </thead>
                <tbody>
                  {providers.map((p) => (
                    <tr key={p.provider}>
                      <th scope="row">{p.provider}</th>
                      <td className="num">{p.declared}</td>
                      <td className="num">{p.verified}</td>
                      <td>
                        {p.backtest_eligible
                          ? <span className="mx-ok">쓸 수 있어요</span>
                          : <span className="mx-fwd">앞으로만 써요</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* ★개정 편향 사유는 접지 않는다★ 이걸 접으면 라벨만 남고 이유가 사라진다. */}
            {providers.filter((p) => p.revision_bias_note).map((p) => (
              <p className="mx-bias" key={p.provider} role="note">
                <b>{p.provider}</b> <span data-server>{p.revision_bias_note}</span>
              </p>
            ))}

            <h4 className="mx-sub">이 키를 넣으면 무엇이 열리나요</h4>
            <ul className="mx-keys">
              {keys.map((k) => (
                <li key={k.env_vars.join(",")} className={k.configured ? "on" : ""}>
                  <span className="mx-key-n">{k.label}</span>
                  <code className="mx-key-v" data-mono>{k.env_vars.join(", ")}</code>
                  <span className={k.configured ? "mx-ok" : "mx-off"}>{k.configured ? "설정됨" : "미설정"}</span>
                  <span className="mx-key-u" data-server>{k.unlocks}</span>
                </li>
              ))}
            </ul>
          </>
        );
      }}
    </Block>
  );
}

/** M1 — 공적분 → VECM / 차분 VAR, 선택 사유 포함 */
function LongRunBlock() {
  const q = useQuery({
    queryKey: ["macro", "long-run"],
    queryFn: () => macroIntelApi.longRun(240),
  });
  return (
    <Block title="지표 사이 장기 관계(공적분 검정)" q={q} loading="장기 관계를 검정하는 중이에요"
           fail="장기 관계 검정을 불러오지 못했어요">
      {() => {
        if (!q.data) return null;
        if (!q.data.available) return <Reason text={q.data.reason} />;
        const d = q.data;
        const ev = d.evidence;
        const top = Math.max(1e-9, ...ev.trace_stat, ...ev.crit_95);
        return (
          <>
            <dl className="mx-dl">
              <div><dt>고른 모형</dt><dd><b>{d.model === "vecm" ? "VECM(오차수정 모형)" : "차분 VAR"}</b></dd></div>
              <div><dt>공적분 개수(랭크)</dt><dd><b className="num">{d.coint_rank}</b></dd></div>
              <div><dt>변수 / 관측</dt><dd><b className="num">{d.span.k}</b>개 / <b className="num">{d.span.n}</b>개</dd></div>
            </dl>
            {d.used?.length ? (
              <p className="mx-vars">쓴 변수 {d.used.map((v, i) => <span key={v} className="mx-var">{varName(v)}{i < d.used!.length - 1 ? ", " : ""}</span>)}</p>
            ) : null}
            {/* 결론 옆에 전제를 적는다 — 왜 이 모형인지 모르면 숫자를 읽을 수 없다. */}
            <p className="mx-why" data-server>{d.reason}</p>
            {d.missing_note && <p className="mx-bias" role="note"><span data-server>{d.missing_note}</span></p>}
            <figure className="mx-trace">
              <figcaption>가설마다 검정 통계량과 95% 임계값(눈금). 막대가 눈금을 넘으면 그 가설을 기각해요.</figcaption>
              <ul>
                {ev.trace_stat.map((s, i) => (
                  <li key={i} className="mx-trace-row">
                    <span className="mx-trace-h">공적분 {i}개 이하</span>
                    <span className="mx-trace-track" aria-hidden>
                      <i className="mx-trace-bar" style={{ width: `${(s / top) * 100}%` }} />
                      <i className="mx-trace-crit" style={{ left: `${(ev.crit_95[i] / top) * 100}%` }} />
                    </span>
                    <span className="mx-trace-v">{s > ev.crit_95[i] ? "기각" : "채택"}</span>
                  </li>
                ))}
              </ul>
            </figure>
            <div className="mx-tblwrap">
              <table className="mx-tbl">
                <thead>
                  <tr>
                    <th scope="col">가설</th>
                    <th scope="col">검정 통계량(trace)</th>
                    <th scope="col">95% 임계값</th>
                    <th scope="col">판정</th>
                  </tr>
                </thead>
                <tbody>
                  {ev.trace_stat.map((s, i) => (
                    <tr key={i}>
                      <th scope="row">공적분 {i}개 이하</th>
                      <td className="num">{s.toFixed(2)}</td>
                      <td className="num">{ev.crit_95[i].toFixed(2)}</td>
                      <td>{s > ev.crit_95[i] ? "기각" : "채택"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        );
      }}
    </Block>
  );
}

/** M2 — 예측집합의 실측 적중률 */
function ForecastBlock() {
  const q = useQuery({
    queryKey: ["macro", "forecast-coverage"],
    queryFn: () => macroIntelApi.forecastCoverage(1, 0.1),
  });
  return (
    <Block title="국면 예측이 맞은 비율" q={q} loading="예측 적중률을 재는 중이에요"
           fail="예측 적중률을 불러오지 못했어요">
      {() => {
        if (!q.data) return null;
        if (!q.data.available) return <Reason text={q.data.reason} />;
        const d = q.data;
        return (
          <>
            <div className="mx-stats">
              <div>
                <span className="mx-stat-k">목표</span>
                <b className="num mx-stat-v">{(d.target * 100).toFixed(0)}%</b>
              </div>
              <div>
                {/* ★실측을 목표와 나란히★ 같은 자리에 넣으면 이론과 측정이 섞인다. */}
                <span className="mx-stat-k">실제로 맞은 비율</span>
                <b className="num mx-stat-v">{(d.coverage * 100).toFixed(1)}%</b>
                <span className="mx-stat-s num">{d.hits}/{d.n_eval}번</span>
              </div>
              <div>
                {/* ★집합 크기를 반드시 함께★ 키우면 적중률은 언제든 올라간다. */}
                <span className="mx-stat-k">평균 예측집합 크기</span>
                <b className="num mx-stat-v">{d.mean_set_size.toFixed(2)}</b>
                <span className="mx-stat-s">국면 4개 중</span>
              </div>
            </div>
            <div className="mx-cov-bar" role="img"
                 aria-label={`실제로 맞은 비율 ${(d.coverage * 100).toFixed(1)}%, 목표 ${(d.target * 100).toFixed(0)}%`}>
              <i className="mx-cov-fill" style={{ width: `${Math.min(100, d.coverage * 100)}%` }} />
              <i className="mx-cov-target" style={{ left: `${Math.min(100, d.target * 100)}%` }} />
            </div>
            <p className="mx-cov-cap">막대는 실제로 맞은 비율, 눈금은 목표예요.</p>
            <p className="mx-why" data-server>{d.note}</p>
          </>
        );
      }}
    </Block>
  );
}

/** M3 — 국면 도구의 합의/불일치 */
function ConsensusBlock() {
  const q = useQuery({
    queryKey: ["macro", "regime-consensus"],
    queryFn: () => macroIntelApi.regimeConsensus("kr", 60),
  });
  return (
    <Block title="국면 판정 도구끼리 맞는지" q={q} loading="국면 도구를 대조하는 중이에요"
           fail="국면 합의를 불러오지 못했어요">
      {() => {
        if (!q.data) return null;
        const d = q.data;
        return (
          <>
            <p className="mx-verdict">
              {d.verdict
                ? <>여럿이 고른 국면은 <b>{regimeName(d.verdict)}</b>이에요</>
                : <><b>판정 없음</b>{d.tie ? "(동수)" : ""}</>}
            </p>
            <p className="mx-verdict-s">
              {d.consensus
                ? <span className="mx-ok">쓸 수 있는 도구가 모두 같아요</span>
                : <span className="mx-split">도구끼리 갈렸어요</span>}
              <span>불일치 점수 <b className="num">{d.disagreement.score.toFixed(2)}</b></span>
            </p>
            {/* ★평균 옆에 원본이 남는다★ 남지 않으면 결론을 되짚을 수 없다. */}
            <ul className="mx-tools">
              {Object.entries(d.per_tool).map(([tool, verdict]) => (
                <li key={tool}>
                  <span className="mx-tool-n">{TOOL_KO[tool] ?? tool} <em data-mono>{tool}</em></span>
                  <b>{regimeName(verdict)}</b>
                </li>
              ))}
              {d.unavailable.map((tool) => (
                <li key={tool} className="off">
                  <span className="mx-tool-n">{TOOL_KO[tool] ?? tool} <em data-mono>{tool}</em></span>
                  {/* 사유를 배지가 직접 들고 있다 — 옆에 흘려 놓으면 떼어 낼 수 있다. */}
                  <EvidenceBadge kind="unavailable" reason={<span data-server>{d.reasons[tool]}</span>}>못 썼어요</EvidenceBadge>
                </li>
              ))}
            </ul>
            <p className="mx-why" data-server>{d.note}</p>
          </>
        );
      }}
    </Block>
  );
}

export default function MacroIntelPanel() {
  return (
    <div className="mx-panel">
      <ConsensusBlock />
      <ForecastBlock />
      <LongRunBlock />
      <CoverageBlock />
    </div>
  );
}
