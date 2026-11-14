"use client";
/**
 * 분봉 백테스트 ①~④ 설정 — 데이터 · 규칙 · 포지션·위험 · 비용 가정
 * ==========================================================================
 * ★도구는 규칙을 추천하지 않는다★ — 틀·매개변수·종목·기간은 사용자가 고른다. 칸의 출발값은 서버의 틀 목록이 준 것이고
 * "좋은 값"이라는 뜻이 아니다. 종목 칸은 비어서 시작한다(도구가 종목을 고르지 않는다).
 * 적재 범위는 ★있는 그대로★ 보인다 — 어느 날 · 어떤 출처로 · 얼마나. 값이 없는 날(운영 게이트가 막은 합성 하루 · 읽지 못한 파일)은
 * 0 이 아니라 사유로 그린다.
 */
import type { Coverage, CoverageDay, FieldDef, Templates } from "@/entities/intraday";
import { num } from "@/shared/lib/krFormat";
import { Notice, RetryFail, Section, Segmented } from "@/shared/ui/tx";
import { GRID_POSITION, parseTickers, rangeText, readField, templateOf, withKind, type Form, type Texts } from "./form";

export type CoverageState =
  | { kind: "idle" } | { kind: "pending" } | { kind: "fail"; status: number; error: string } | { kind: "done"; value: Coverage };

const STATUS_KO: Record<CoverageDay["status"], string> = { loaded: "적재됨", blocked: "차단됨", unreadable: "읽기 실패", not_checked: "확인 전" };
const CHOICE_NONE = "미상으로 둠";

function Field({ def, value, onChange, required, emptyChoice }: {
  def: FieldDef; value: string; onChange: (v: string) => void; required: boolean; emptyChoice?: string;
}) {
  const read = readField(def, value);
  const invalid = read.error !== null || (required && value.trim() === "");
  const hint = def.type === "time" ? "HHMM" : def.type === "choice" ? "" : rangeText(def);
  return (
    <label className="tj-field itd-field" data-key={def.key}>
      <span className="tj-label">{def.label}{required ? <i className="tj-req">필수</i> : null}</span>
      {def.type === "choice" ? (
        <select className="tj-input" value={value} onChange={(e) => onChange(e.target.value)}>
          {emptyChoice ? <option value="">{emptyChoice}</option> : null}
          {def.choices?.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      ) : (
        <input className="tj-input" inputMode={def.type === "float" ? "decimal" : "numeric"} autoComplete="off" value={value}
               placeholder={required ? "" : "미사용"} aria-invalid={invalid} onChange={(e) => onChange(e.target.value)} />
      )}
      {hint ? <span className="itd-hint">{hint}</span> : null}
    </label>
  );
}

function CoverageView({ c, asked }: { c: Coverage; asked: string[] }) {
  const s = c.summary;
  const facts = [
    `달력 ${num(s.calendar_days)}일 가운데 적재된 날 ${num(s.loaded_days)}일`, `봉 ${num(s.bars)}개`,
    ...(s.blocked_days ? [`운영 게이트가 막은 날 ${num(s.blocked_days)}일`] : []),
    ...(s.unreadable_days ? [`읽지 못한 날 ${num(s.unreadable_days)}일`] : []),
    ...(s.not_checked_days ? [`아직 확인하지 않은 날 ${num(s.not_checked_days)}일`] : []),
    `결함 ${num(s.defect_total)}건`,
  ];
  return (
    <div className="itd-coverage">
      <p className="tj-read itd-coverage-read">{c.from} ~ {c.to} · {facts.join(" · ")}</p>
      <dl className="tj-cost-figs itd-sources">
        <div data-k="kis"><dt>실제 분봉(제공자 응답)</dt><dd>{num(s.sources.kis)}행</dd></div>
        <div data-k="synthetic"><dt>합성 분봉(모의 모드)</dt><dd>{num(s.sources.synthetic)}행</dd></div>
        <div data-k="unknown"><dt>출처 미상</dt><dd>{num(s.sources.unknown)}행</dd></div>
      </dl>
      {c.empty ? <Notice tone="warn" title="적재된 분봉 없음"><span data-server>{c.empty.message}</span></Notice> : (
        <div className="tj-scroll itd-days">
          <table className="tj-table">
            <thead><tr><th scope="col">날짜</th><th scope="col">상태</th><th scope="col" className="tj-num">종목</th><th scope="col" className="tj-num">봉</th>
              <th scope="col" className="tj-num">결함</th><th scope="col">고른 종목 가운데 없는 것</th></tr></thead>
            <tbody>
              {c.days.map((d) => (
                <tr key={d.date} data-status={d.status}>
                  <td data-mono>{d.date}</td>
                  <td>{STATUS_KO[d.status]}{d.message ? <span className="itd-why" data-server> · {d.message}</span> : null}{d.session_shifted ? <span className="itd-why"> · 장 운영 시간이 평소와 다름</span> : null}</td>
                  <td className="tj-num">{num(d.tickers)}</td>
                  <td className="tj-num">{num(d.bars)}</td>
                  <td className="tj-num">{num(d.defect_total)}</td>
                  <td data-mono>{asked.length ? (d.status === "loaded" ? (d.missing_tickers.join(" ") || "없음") : "") : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!c.session_rules.available && c.session_rules.message ? <p className="tj-note" data-server>{c.session_rules.message}</p> : null}
    </div>
  );
}

export function SetupForm({ templates: t, form, onChange, coverage, onCoverage, problems, pending, stale, onRun }: {
  templates: Templates; form: Form; onChange: (next: Form) => void;
  coverage: CoverageState; onCoverage: () => void;
  problems: string[]; pending: boolean; stale: boolean; onRun: () => void;
}) {
  const template = templateOf(t, form.kind);
  const tickers = parseTickers(form.tickers);
  const set = (scope: "params" | "position" | "costs", key: string, v: string) => onChange({ ...form, [scope]: { ...form[scope], [key]: v } as Texts });
  const periodOk = /^\d{4}-\d{2}-\d{2}$/.test(form.from) && /^\d{4}-\d{2}-\d{2}$/.test(form.to) && form.from <= form.to;
  return (
    <>
      <Section title="데이터" sub="적재된 분봉 가운데 돌릴 종목과 기간을 정합니다. 분봉이 없는 종목·일자는 사유와 함께 건너뜁니다.">
        <div className="tj-map itd-data">
          <label className="tj-field">
            <span className="tj-label">종목코드<i className="tj-req">필수</i></span>
            <textarea className="tj-input itd-tickers" rows={2} autoComplete="off" spellCheck={false} value={form.tickers}
                      placeholder="예: 005930, 000660" aria-describedby="itd-tickers-note" onChange={(e) => onChange({ ...form, tickers: e.target.value })} />
            <span className="itd-hint" id="itd-tickers-note">쉼표나 공백으로 구분 · {num(t.limits.tickers)}개까지 · 지금 {num(tickers.length)}개</span>
          </label>
          <div className="tj-fields tj-fields--pair">
            <label className="tj-field"><span className="tj-label">시작일<i className="tj-req">필수</i></span>
              <input className="tj-input itd-from" type="date" value={form.from} max={form.to || undefined} onChange={(e) => onChange({ ...form, from: e.target.value })} /></label>
            <label className="tj-field"><span className="tj-label">종료일<i className="tj-req">필수</i></span>
              <input className="tj-input itd-to" type="date" value={form.to} min={form.from || undefined} onChange={(e) => onChange({ ...form, to: e.target.value })} /></label>
          </div>
          <div className="tj-run-row itd-coverage-row">
            <button type="button" className="tx-btn tx-btn--sub itd-coverage-btn" disabled={!periodOk || coverage.kind === "pending"} onClick={onCoverage}>
              {coverage.kind === "pending" ? "조회 중" : "적재 범위 조회"}
            </button>
            <p className="tj-note">적재 범위는 한 번에 {num(31)}일까지 조회합니다. 종목을 넣으면 날짜마다 없는 종목을 함께 표시합니다.</p>
          </div>
          {coverage.kind === "fail" ? (
            coverage.status === 400 || coverage.status === 422
              ? <Notice tone="danger" title="적재 범위 조회 거절"><span data-server>{coverage.error}</span></Notice>
              : <RetryFail title="적재 범위 조회 실패" onRetry={onCoverage}><span data-server>{coverage.error}</span></RetryFail>
          ) : null}
          {coverage.kind === "done" ? <CoverageView c={coverage.value} asked={tickers} /> : null}
        </div>
      </Section>

      <Section title="규칙" sub="규칙 틀과 매개변수를 정합니다. 신호는 봉 종가까지의 값으로 계산하고 다음 봉 시가에 체결합니다.">
        <div className="tj-map itd-rule">
          <div className="itd-kinds">
            <Segmented label="규칙 틀" options={t.templates.map((x) => ({ value: x.kind, label: x.label }))} value={form.kind}
                       onChange={(kind) => onChange(withKind(form, t, kind))} />
          </div>
          <p className="tj-read itd-rule-summary" data-server>{template.summary}</p>
          <div className="tj-fields itd-params">
            {template.params.map((p) => <Field key={p.key} def={p} value={form.params[p.key] ?? ""} required onChange={(v) => set("params", p.key, v)} />)}
          </div>
          {template.notes.length ? <ul className="tj-plain-list itd-notes">{template.notes.map((n) => <li key={n} data-server>{n}</li>)}</ul> : null}
          {template.needs_prev ? <p className="tj-note itd-needs-prev">전일 값은 앞선 적재일의 분봉에서 얻습니다. 닷새 안에 적재된 날이 없는 종목·일자는 건너뜁니다.</p> : null}
        </div>
      </Section>

      <Section title="포지션과 위험" sub="모든 규칙 틀에 공통으로 적용합니다. 비워 둔 칸의 규칙은 사용하지 않습니다. 보유는 하루를 넘기지 않으며 마지막 봉에서 청산합니다.">
        <div className="tj-fields itd-position">
          {t.position.map((p) => <Field key={p.key} def={p} value={form.position[p.key] ?? ""} required={p.key === "amount"} onChange={(v) => set("position", p.key, v)} />)}
        </div>
      </Section>

      <Section title="비용 가정" sub="수수료율은 입력한 값으로 계산하는 가정이고, 매도세는 거래일·시장·상품별 세율표로 산출하는 추론입니다. 슬리피지와 참여율 상한도 가정입니다.">
        <div className="tj-map itd-costs">
          <div className="tj-fields">
            {t.costs.map((p) => <Field key={p.key} def={p} value={form.costs[p.key] ?? ""} required={p.key === "slippage_ticks"} emptyChoice={CHOICE_NONE}
                                       onChange={(v) => set("costs", p.key, v)} />)}
          </div>
          <ul className="tj-plain-list itd-cost-notes">
            <li>수수료율을 비워 두면 0 으로 보지 않고 미상으로 둡니다. 비용 후 통계는 N/A 로 표시됩니다.</li>
            <li>종목 마스터가 시장 구분을 모르는 종목은 매도세를 산출하지 못합니다. 시장과 상품을 지정하면 그 가정으로 산출하고 가정으로 표시합니다.</li>
            <li>참여율 상한은 그 봉 거래량 대비 체결 수량의 한도입니다. 시장충격과 호가 잔량은 반영하지 않습니다.</li>
          </ul>
        </div>
      </Section>

      <div className="tj-run-row itd-run-row">
        <button type="button" className="tx-btn tx-btn--main tj-run itd-run" disabled={problems.length > 0 || pending} onClick={onRun}>{pending ? "계산 중" : "실행"}</button>
        {problems.length ? <ul className="tj-map-miss itd-problems">{problems.map((p) => <li key={p}>{p}</li>)}</ul> : null}
        {!problems.length && stale ? <p className="tj-note tj-stale">설정이 변경됐습니다. 재계산이 필요합니다.</p> : null}
        {!problems.length && !stale ? <p className="tj-note">실행할 때마다 설정과 일별 손익을 시행으로 기록합니다. 주문은 내지 않습니다.</p> : null}
      </div>
    </>
  );
}

/** 워크포워드의 격자 선언 — 칸마다 쉼표로 나눈 값. 켜지 않으면 격자가 없다. */
export function GridForm({ templates: t, form, onChange, cells }: { templates: Templates; form: Form; onChange: (next: Form) => void; cells: number }) {
  const template = templateOf(t, form.kind);
  const g = form.grid;
  const set = (scope: "rule" | "position", key: string, v: string) => onChange({ ...form, grid: { ...g, [scope]: { ...g[scope], [key]: v } } });
  const numeric = template.params.filter((p) => p.type !== "choice");
  const position = t.position.filter((p) => GRID_POSITION.includes(p.key));
  return (
    <div className="itd-grid">
      <label className="itd-grid-on">
        <input type="checkbox" checked={g.on} onChange={(e) => onChange({ ...form, grid: { ...g, on: e.target.checked } })} />
        <span>워크포워드 포함(격자를 미리 선언)</span>
      </label>
      {g.on ? (
        <>
          <p className="tj-note">칸마다 볼 값을 쉼표로 나눠 입력합니다. 앞 구간에서 비용 후 거래당 기대값이 가장 큰 칸을 다음 구간에 적용합니다. 격자의 칸은 전부 시행 횟수에 더합니다.</p>
          <div className="tj-fields">
            <label className="tj-field"><span className="tj-label">구간 수<i className="tj-req">필수</i></span>
              <input className="tj-input itd-folds" inputMode="numeric" autoComplete="off" value={g.folds} onChange={(e) => onChange({ ...form, grid: { ...g, folds: e.target.value } })} />
              <span className="itd-hint">{t.limits.folds_min}~{t.limits.folds_max}</span></label>
            {numeric.map((p) => (
              <label key={p.key} className="tj-field" data-grid={`rule.${p.key}`}><span className="tj-label">{p.label}</span>
                <input className="tj-input" autoComplete="off" placeholder="예: 15, 30, 60" value={g.rule[p.key] ?? ""} onChange={(e) => set("rule", p.key, e.target.value)} />
                <span className="itd-hint">{rangeText(p)}</span></label>
            ))}
            {position.map((p) => (
              <label key={p.key} className="tj-field" data-grid={`position.${p.key}`}><span className="tj-label">{p.label}</span>
                <input className="tj-input" autoComplete="off" placeholder="예: 0.5, 1" value={g.position[p.key] ?? ""} onChange={(e) => set("position", p.key, e.target.value)} />
                <span className="itd-hint">{rangeText(p)}</span></label>
            ))}
          </div>
          <p className="tj-note itd-grid-count">격자 {num(cells)}칸 · 한 번에 {num(t.limits.grid_cells)}칸까지</p>
        </>
      ) : null}
    </div>
  );
}
