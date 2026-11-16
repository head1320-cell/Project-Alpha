/**
 * 최적화 결과 판의 '국면 가중' 절(M3) — 요청한 방식 · 산출한 방식 · 열화 사유 · 국면 분포 · 점수 · 안정성.
 * ==========================================================================
 * 값과 이름은 서버의 것이다(`_regime_block`). 화면은 숫자를 다시 계산하지 않고 서식만 입힌다 — 점수 칸은 국면 예측 비교(M2)와 같은
 * 서식(`entities/macro/skill.ts`)이라 같은 점수가 두 화면에서 같게 읽힌다. ★고르지 않는다★ 이 절은 방식을 권하지 않는다.
 * 열화 사유는 서버 문장 그대로 · 읽을 글자로(색만으로 말하지 않는다). 재지 못한 칸은 "—".
 */
import type { ReactNode } from "react";
import { regimeName } from "@/entities/macro/regimeKo";
import { skillBrier, skillEvidence, skillGain, skillHit } from "@/entities/macro/skill";
import { distRows, gateRows, type GateBlock, type RegimeBlock, type RegimeSkill } from "@/entities/portfolio-graph/regimeWeighting";

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="pg-kv pg-rw-kv">{rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}</dl>;
}

function Skill({ sk }: { sk: RegimeSkill }) {
  const base = sk.baseline?.name ?? "오늘 국면 유지";
  return (
    <div className="pg-rw-skill">
      <h5 className="pg-rw-h5">같은 경로의 워크포워드 점수 <span className="pg-rw-sub">{sk.k}개월 앞 · 평가 시점 {sk.n_eval}개</span></h5>
      <KV rows={[
        ["적중", <span key="h" className="pg-td-num">{sk.hits ?? "—"}/{sk.n_eval}회 · {skillHit(sk)}</span>],
        ["브라이어", <span key="b" className="pg-td-num">{skillBrier(sk)}</span>],
        [`‘${base}’ 대비`, <span key="g" className="pg-td-num">{skillGain(sk)}</span>],
        ["순차 증거 최고", sk.evidence
          ? <span key="e" className="pg-td-num">{skillEvidence(sk)}</span>
          : <span key="e" className="pg-rw-why">{sk.evidence_reason ?? "—"}</span>],
      ]} />
      <p className="pg-note">브라이어는 0(확신하고 맞힘) ~ 2(확신하고 틀림)입니다. 유지 대비가 양이면 기준선보다 확률을 잘 맞혔습니다.</p>
      {sk.evidence?.passed && (
        <p className="pg-note pg-rw-pass">* 순차 증거가 기준({typeof sk.threshold === "number" ? sk.threshold.toFixed(0) : "—"})을 넘었습니다.</p>
      )}
      <p className="pg-note">{sk.note}</p>
    </div>
  );
}

/** 근거 관문(M4) — 견준 세 후보의 브라이어 · 관문의 선택(글자) · 서버의 사유와 낙관 줄. 견주지 못했으면 사유 하나. */
function Gate({ g }: { g: GateBlock }) {
  return (
    <div className="pg-rw-gate">
      <h5 className="pg-rw-h5">
        근거 관문{" "}
        <span className="pg-rw-sub">
          {g.k}개월 앞{g.available ? ` · 평가 시점 ${g.n_eval}개 · 견준 후보 ${g.n_compared}` : " · 견주지 못함"}
        </span>
      </h5>
      {g.available && (
        <table className="pg-table pg-rw-gate-table">
          <caption className="pg-rw-cap">같은 경로의 워크포워드 브라이어(낮을수록 잘 맞힘)</caption>
          <thead><tr><th scope="col">후보</th><th scope="col">브라이어</th><th scope="col">관문의 선택</th></tr></thead>
          <tbody>
            {gateRows(g).map((r) => (
              <tr key={r.key} data-key={r.key} data-chosen={r.chosen ? "true" : undefined}>
                <td className="pg-td-name">{r.name}</td>
                <td className="pg-td-num">{r.brier}</td>
                <td className="pg-rw-gate-pick">{r.chosen ? "고름" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="pg-note pg-rw-gate-why">{g.reason}</p>
      {g.note && <p className="pg-note pg-rw-gate-note">{g.note}</p>}
    </div>
  );
}

function Stability({ reg }: { reg: RegimeBlock }) {
  const st = reg.stability;
  const rb = reg.robustness;
  const rows: [string, ReactNode][] = [];
  if (st) rows.push(["난수 시드", `${st.seeds}개 가운데 ${st.agree}개가 ‘${regimeName(st.modal)}’${st.stable ? "" : " · 과반 미만"}`]);
  if (rb?.available) rows.push(["다시 뽑기", `${rb.resamples}번 가운데 ${rb.agree}번 ‘${regimeName(rb.label ?? "")}’`]);
  else if (rb) rows.push(["다시 뽑기", <span key="r" className="pg-rw-why">{rb.reason ?? "—"}</span>]);
  if (rows.length === 0) return null;
  return (
    <div className="pg-rw-stab">
      <h5 className="pg-rw-h5">시작 분포의 안정성 <span className="pg-rw-sub">관측 · 시작 분포를 바꾸지 않습니다</span></h5>
      <KV rows={rows} />
    </div>
  );
}

export function RegimeWeightingBlock({ reg }: { reg: RegimeBlock | null | undefined }) {
  if (!reg) return null;
  if (!reg.available) {
    return (
      <section className="pg-rw" aria-label="국면 가중">
        <h4 className="pg-h4">국면 가중</h4>
        <p className="pg-warn pg-rw-unavailable">경기 국면 조건부 추정을 쓰지 못해 과거 표본 기준으로 산출했습니다. {reg.reason}</p>
      </section>
    );
  }
  const rows: [string, ReactNode][] = [["요청한 방식", reg.requested_name], ["산출한 방식", reg.used_name ?? "—"]];
  if (reg.h_hold != null) rows.push(["보유 기간", `${reg.h_hold}개월`]);
  return (
    <section className="pg-rw" aria-label="국면 가중">
      <h4 className="pg-h4">국면 가중</h4>
      <KV rows={rows} />
      {reg.gate && <Gate g={reg.gate} />}
      {reg.fallbacks.length > 0 && (
        <ul className="pg-list pg-rw-fallbacks" aria-label="요청한 방식을 쓰지 못한 사유">
          {reg.fallbacks.map((t, i) => <li key={i} className="pg-rw-fallback">{t}</li>)}
        </ul>
      )}
      {!reg.applied && <p className="pg-note pg-rw-blocked">경기 국면 반영이 차단돼 이 추정은 비중에 쓰이지 않았습니다.</p>}
      {reg.pi_bar && (
        <table className="pg-table pg-rw-dist">
          <caption className="pg-rw-cap">국면 분포</caption>
          <thead><tr><th scope="col">국면</th>{reg.pi0 && <th scope="col">시작 분포</th>}<th scope="col">보유 기간 평균</th></tr></thead>
          <tbody>
            {distRows(reg, regimeName).map((r) => (
              <tr key={r.key} data-key={r.key} data-dropped={r.dropped ? "true" : undefined}>
                <td className="pg-td-name">{r.name}</td>
                {reg.pi0 && <td className="pg-td-num">{r.start}</td>}
                <td className={r.dropped ? "pg-td-num pg-rw-na" : "pg-td-num"}>{r.held}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {reg.dropped_notes.map((t, i) => <p key={i} className="pg-note pg-rw-dropped">{t}</p>)}
      {reg.used === "gmm" && reg.skill?.available && <Skill sk={reg.skill} />}
      {reg.used === "gmm" && <Stability reg={reg} />}
    </section>
  );
}
