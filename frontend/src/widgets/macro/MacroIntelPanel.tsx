"use client";

/**
 * P4 매크로 지능 패널 — 소스 커버리지 · 장기관계 · 예측 적중률 · 국면 불일치
 * ==========================================================================
 * D1~D5 와 M1~M3 가 만든 것을 **화면이 처음으로 보는 자리**다. 네 블록 전부
 * 같은 규칙을 따른다:
 *
 *   1. 미가용이면 숫자를 하나도 내지 않고 **사유만** 낸다.
 *   2. 결론 옆에 그 결론의 **전제**를 적는다(어느 모형·어느 기준일·어느 도구).
 *   3. 경고와 한계는 접지 않는다 — A5 가 그은 경계 그대로다.
 *
 * ★적중률과 집합 크기를 같이 낸다★ 집합을 키우면 적중률은 언제든 올라가므로,
 * 적중률만 보여 주면 화면이 "잘 맞힌다" 는 거짓 인상을 만든다.
 */

import { useQuery } from "@tanstack/react-query";
import { EvidenceBadge } from "@/shared/ui/evidence";
import { macroIntelApi } from "@/entities/macro/studios";

/**
 * 미가용 — 숫자 대신 오는 것.
 *
 * `EvidenceBadge` 는 `kind="unavailable"` 일 때 `reason` 을 **필수**로 요구한다
 * (evidence.tsx 의 판별 유니온). 사유 없는 미가용을 타입 단계에서 못 만들게 한
 * 계약이라, 여기서 우회하지 않고 그대로 태운다.
 */
function Reason({ text }: { text: string }) {
  return (
    <div className="mx-reason">
      <EvidenceBadge kind="unavailable" reason={text}>산출 불가</EvidenceBadge>
    </div>
  );
}

/** D5 — 소스 커버리지 + 이 키를 넣으면 무엇이 열리는가 */
function CoverageBlock() {
  const q = useQuery({
    queryKey: ["macro", "source-coverage"],
    queryFn: () => macroIntelApi.sourceCoverage(true),
  });

  if (q.isLoading) return <div className="mx-loading">소스 커버리지 확인 중…</div>;
  if (q.isError || !q.data) return <Reason text="소스 커버리지를 불러오지 못했습니다 — 네트워크 오류입니다." />;

  const { providers, keys, ladder } = q.data;
  return (
    <section className="mx-card">
      <h3 className="mx-card-t">데이터 소스 커버리지</h3>
      {ladder && (
        <p className="mx-ladder">
          현재 능력 레벨 <b className="num">{ladder.level}</b>
          {ladder.blocked_level && (
            <> · <b className="num">{ladder.blocked_level}</b> 가 막힌 이유: {ladder.blocked_reason}</>
          )}
        </p>
      )}
      <div className="mx-tblwrap">
        <table className="mx-tbl">
          <thead>
            <tr>
              <th scope="col">제공자</th>
              <th scope="col">선언</th>
              <th scope="col">검증</th>
              <th scope="col">백테스트 적격</th>
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
                    ? <span className="mx-ok">적격</span>
                    : <span className="mx-fwd">forward-only</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ★개정 편향 사유는 접지 않는다★ 이걸 접으면 라벨만 남고 이유가 사라진다. */}
      {providers.filter((p) => p.revision_bias_note).map((p) => (
        <p className="mx-bias" key={p.provider} role="note">
          <b>{p.provider}</b> {p.revision_bias_note}
        </p>
      ))}

      <h4 className="mx-sub">이 키를 넣으면 무엇이 열리는가</h4>
      <ul className="mx-keys">
        {keys.map((k) => (
          <li key={k.env_vars.join(",")} className={k.configured ? "on" : ""}>
            <span className="mx-key-n">{k.label}</span>
            <code className="mx-key-v">{k.env_vars.join(" · ")}</code>
            <span className={k.configured ? "mx-ok" : "mx-off"}>
              {k.configured ? "설정됨" : "미설정"}
            </span>
            <span className="mx-key-u">{k.unlocks}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** M1 — 공적분 → VECM / 차분 VAR, 선택 사유 포함 */
function LongRunBlock() {
  const q = useQuery({
    queryKey: ["macro", "long-run"],
    queryFn: () => macroIntelApi.longRun(240),
  });

  if (q.isLoading) return <div className="mx-loading">장기관계 검정 중…</div>;
  if (q.isError || !q.data) return <Reason text="장기관계 검정을 불러오지 못했습니다 — 네트워크 오류입니다." />;
  if (!q.data.available) return <Reason text={q.data.reason} />;

  const d = q.data;
  return (
    <section className="mx-card">
      <h3 className="mx-card-t">장기관계 — 공적분 검정</h3>
      <p className="mx-verdict">
        <b>{d.model === "vecm" ? "VECM (오차수정)" : "차분 VAR"}</b>
        {" · "}공적분 랭크 <b className="num">{d.coint_rank}</b>
        {" · "}변수 <b className="num">{d.span.k}</b>개 / 관측 <b className="num">{d.span.n}</b>
      </p>
      {/* 결론 옆에 전제를 적는다 — 왜 이 모형인지 모르면 숫자를 읽을 수 없다. */}
      <p className="mx-why">{d.reason}</p>
      {d.missing_note && <p className="mx-bias" role="note">{d.missing_note}</p>}
      <div className="mx-tblwrap">
        <table className="mx-tbl">
          <thead>
            <tr>
              <th scope="col">가설</th>
              <th scope="col">trace 통계량</th>
              <th scope="col">95% 임계값</th>
              <th scope="col">판정</th>
            </tr>
          </thead>
          <tbody>
            {d.evidence.trace_stat.map((s, i) => (
              <tr key={i}>
                <th scope="row">r ≤ {i}</th>
                <td className="num">{s.toFixed(2)}</td>
                <td className="num">{d.evidence.crit_95[i].toFixed(2)}</td>
                <td>{s > d.evidence.crit_95[i] ? "기각" : "채택"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** M2 — 예측집합의 실측 적중률 */
function ForecastBlock() {
  const q = useQuery({
    queryKey: ["macro", "forecast-coverage"],
    queryFn: () => macroIntelApi.forecastCoverage(1, 0.1),
  });

  if (q.isLoading) return <div className="mx-loading">예측 적중률 측정 중…</div>;
  if (q.isError || !q.data) return <Reason text="예측 적중률을 불러오지 못했습니다 — 네트워크 오류입니다." />;
  if (!q.data.available) return <Reason text={q.data.reason} />;

  const d = q.data;
  return (
    <section className="mx-card">
      <h3 className="mx-card-t">국면 예측 — 실측 적중률</h3>
      <div className="mx-stats">
        <div>
          <span className="mx-stat-k">목표</span>
          <b className="num mx-stat-v">{(d.target * 100).toFixed(0)}%</b>
        </div>
        <div>
          {/* ★실측을 목표와 나란히★ 같은 자리에 넣으면 이론과 측정이 섞인다. */}
          <span className="mx-stat-k">실측</span>
          <b className="num mx-stat-v">{(d.coverage * 100).toFixed(1)}%</b>
          <span className="mx-stat-s num">{d.hits}/{d.n_eval}</span>
        </div>
        <div>
          {/* ★집합 크기를 반드시 함께★ 키우면 적중률은 언제든 올라간다. */}
          <span className="mx-stat-k">평균 예측집합</span>
          <b className="num mx-stat-v">{d.mean_set_size.toFixed(2)}</b>
          <span className="mx-stat-s">4개 국면 중</span>
        </div>
      </div>
      <p className="mx-why">{d.note}</p>
    </section>
  );
}

/** M3 — 국면 도구의 합의/불일치 */
function ConsensusBlock() {
  const q = useQuery({
    queryKey: ["macro", "regime-consensus"],
    queryFn: () => macroIntelApi.regimeConsensus("kr", 60),
  });

  if (q.isLoading) return <div className="mx-loading">국면 도구 대조 중…</div>;
  if (q.isError || !q.data) return <Reason text="국면 합의를 불러오지 못했습니다 — 네트워크 오류입니다." />;

  const d = q.data;
  return (
    <section className="mx-card">
      <h3 className="mx-card-t">국면 도구 — 합의와 불일치</h3>
      <p className="mx-verdict">
        {d.verdict
          ? <>다수 판정 <b>{d.verdict}</b></>
          : <><b>판정 없음</b>{d.tie ? " — 동수" : ""}</>}
        {" · "}
        {d.consensus
          ? <span className="mx-ok">가용 도구 전부 일치</span>
          : <span className="mx-split">갈림</span>}
        {" · "}불일치 <b className="num">{d.disagreement.score.toFixed(2)}</b>
      </p>
      {/* ★평균 옆에 원본이 남는다★ 남지 않으면 결론을 되짚을 수 없다. */}
      <ul className="mx-tools">
        {Object.entries(d.per_tool).map(([tool, verdict]) => (
          <li key={tool}><span className="mx-tool-n">{tool}</span><b>{verdict}</b></li>
        ))}
        {d.unavailable.map((tool) => (
          <li key={tool} className="off">
            <span className="mx-tool-n">{tool}</span>
            {/* 사유를 배지가 직접 들고 있다 — 옆에 흘려 놓으면 떼어 낼 수 있다. */}
            <EvidenceBadge kind="unavailable" reason={d.reasons[tool]}>미가용</EvidenceBadge>
          </li>
        ))}
      </ul>
      <p className="mx-why">{d.note}</p>
    </section>
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
