"use client";
/**
 * 배치 관리 시트 — 이름 붙여 저장 · 이름 바꾸기 · 지우기 · 내보내기 · 가져오기 (G6 2a-1 · 계획 §9.1 · 용어집 §3.30)
 * ==========================================================================
 * 메뉴(role menu) 안에는 글 입력을 둘 수 없어 기존 `Sheet`(네이티브 dialog — 초점 가두기 · Escape)에 둔다. 부르는 쪽이 열려 있는 동안만 그린다
 * (판 배치를 끈 화면의 DOM 에 남지 않는다). 닫으면 초점은 그 화면의 '배치' 단추로 돌아간다.
 * ★결과는 문장으로★ — 남기지 못하면 저장했다고 말하지 않는다 · 가져오기는 엄격(사유가 하나라도 있으면 사유 목록 · 지금 배치 그대로).
 * 파일은 브라우저 안에서만 읽고 쓴다(서버 0줄). 적용은 '배치' 메뉴의 '이름 붙인 배치'에서 한다(폭 검사가 그 자리에 있다).
 */
import { useCallback, useId, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { Sheet } from "@/shared/ui/tx";
import { FILE_MAX, MAX_NAMED, NAME_MAX, TOO_BIG, ro } from "./layout";
import { refocusOpen } from "./LayoutMenu";
import type { WorkspaceState } from "./useWorkspace";

type Msg = { text: string; tone: "ok" | "err"; reasons?: string[] } | null;

const REFUSED = "가져오지 않았습니다. 지금 배치는 그대로입니다.";

/** 내려받을 파일 이름 — 화면 이름 + 이 브라우저의 오늘 날짜. */
function fileName(screen: string): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `workspace-${screen}-${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}.json`;
}

function download(text: string, name: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function LayoutSheet({ ws, onClose }: { ws: WorkspaceState; onClose: () => void }) {
  const [name, setName] = useState("");
  const [msg, setMsg] = useState<Msg>(null);
  const [renaming, setRenaming] = useState<{ from: string; to: string } | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const uid = useId();
  const close = () => { onClose(); refocusOpen(ws.spec.screen); };
  /** 이름 바꾸기 칸이 설 때 한 번 초점을 준다(안정된 콜백 ref — 글자를 칠 때마다 다시 부르지 않는다). */
  const focusOnce = useCallback((el: HTMLInputElement | null) => { el?.focus(); }, []);

  const save = (e: FormEvent) => {
    e.preventDefault();
    const t = name.trim();
    const existed = ws.saved.some((x) => x.name === t);
    const r = ws.saveAs(name);
    if (!r.ok) { setMsg({ text: r.reason, tone: "err" }); return; }
    setMsg({ text: existed ? `‘${t}’ 배치를 지금 배치로 바꿨습니다.` : `‘${t}’ 배치를 저장했습니다.`, tone: "ok" });
    setName("");
  };
  const rename = (e: FormEvent) => {
    e.preventDefault();
    if (!renaming) return;
    const to = renaming.to.trim();
    const r = ws.rename(renaming.from, renaming.to);
    if (!r.ok) { setMsg({ text: r.reason, tone: "err" }); return; }
    setMsg({ text: `‘${renaming.from}’ 배치의 이름을 ‘${to}’${ro(to)} 바꿨습니다.`, tone: "ok" });
    setRenaming(null);
  };
  const remove = (n: string) => {
    const r = ws.remove(n);
    setMsg(r.ok ? { text: `‘${n}’ 배치를 지웠습니다.`, tone: "ok" } : { text: r.reason, tone: "err" });
    if (renaming?.from === n) setRenaming(null);
  };
  const exportNow = () => {
    try {
      download(ws.exportText(), fileName(ws.spec.screen));
      setMsg({ text: `내보냈습니다(지금 배치와 이름 붙인 배치 ${ws.saved.length}개).`, tone: "ok" });
    } catch {
      setMsg({ text: "내보내지 못했습니다. 이 브라우저가 파일 내려받기를 막았을 수 있습니다.", tone: "err" });
    }
  };
  const importNow = async (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";                                   // 같은 파일을 다시 골라도 onChange 가 오도록
    if (!f) return;
    if (f.size > FILE_MAX) { setMsg({ text: REFUSED, tone: "err", reasons: [TOO_BIG] }); return; }
    let text: string;
    try { text = await f.text(); } catch { setMsg({ text: REFUSED, tone: "err", reasons: ["파일을 읽지 못했습니다."] }); return; }
    const r = ws.importText(text);
    if (!r.ok) { setMsg({ text: REFUSED, tone: "err", reasons: r.reasons }); return; }
    const n = (JSON.parse(text) as { saved: unknown[] }).saved.length;   // 통과한 파일이라 꼴이 맞다
    setMsg({ text: `가져왔습니다. 지금 배치와 이름 붙인 배치 ${n}개를 적용했습니다.`, tone: "ok" });
  };

  const noteId = `${uid}-note`;
  return (
    <Sheet open onClose={close} testId="ws" title="배치 관리" className="ws-sheet"
           sub="판 배치는 이 브라우저에만 남습니다. 파일로 내보내 다른 브라우저에서 가져올 수 있습니다.">
      <section className="ws-sheet-sec" aria-labelledby={`${uid}-save`}>
        <h3 className="ws-sheet-h" id={`${uid}-save`}>지금 배치에 이름 붙여 저장</h3>
        <form className="ws-save-row" onSubmit={save}>
          <label className="tx-sr" htmlFor={`${uid}-name`}>배치 이름</label>
          <input id={`${uid}-name`} className="tj-input ws-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="예: 관제용"
                 aria-describedby={noteId} autoComplete="off" />
          <button type="submit" className="tx-btn tx-btn--main ws-save">저장</button>
        </form>
        <p className="tj-note" id={noteId}>이름은 1 ~ {NAME_MAX}자 · {MAX_NAMED}개까지 · 같은 이름은 지금 배치로 바꿉니다.</p>
      </section>

      <section className="ws-sheet-sec" aria-labelledby={`${uid}-list`}>
        <h3 className="ws-sheet-h" id={`${uid}-list`}>이름 붙인 배치 <span className="ws-sheet-count">{ws.saved.length} / {MAX_NAMED}</span></h3>
        {ws.saved.length ? (
          <ul className="ws-saved">
            {ws.saved.map((x) => (
              <li key={x.name} className="ws-saved-item">
                {renaming?.from === x.name ? (
                  <form className="ws-rename-row" onSubmit={rename}>
                    <label className="tx-sr" htmlFor={`${uid}-rn`}>‘{x.name}’의 새 이름</label>
                    <input id={`${uid}-rn`} ref={focusOnce} className="tj-input ws-rename-input" value={renaming.to} autoComplete="off"
                           onChange={(e) => setRenaming({ from: x.name, to: e.target.value })} />
                    <button type="submit" className="tx-btn tx-btn--main ws-rename-ok">바꾸기</button>
                    <button type="button" className="tx-btn tx-btn--sub ws-rename-cancel" onClick={() => setRenaming(null)}>취소</button>
                  </form>
                ) : (
                  <>
                    <span className="ws-saved-name">{x.name}</span>
                    <span className="ws-saved-shape">열 {x.layout.cols.length} · 닫은 판 {x.layout.closed.length}</span>
                    <button type="button" className="tx-btn tx-btn--sub ws-saved-rename" aria-label={`‘${x.name}’ 이름 바꾸기`}
                            onClick={() => setRenaming({ from: x.name, to: x.name })}>이름 바꾸기</button>
                    <button type="button" className="tx-btn tx-btn--sub ws-saved-remove" aria-label={`‘${x.name}’ 지우기`}
                            onClick={() => remove(x.name)}>지우기</button>
                  </>
                )}
              </li>
            ))}
          </ul>
        ) : <p className="tj-note ws-saved-none">이름 붙인 배치가 없습니다.</p>}
        <p className="tj-note">적용은 ‘배치’ 메뉴의 ‘이름 붙인 배치’에서 합니다.</p>
      </section>

      <section className="ws-sheet-sec" aria-labelledby={`${uid}-file`}>
        <h3 className="ws-sheet-h" id={`${uid}-file`}>파일</h3>
        <div className="ws-file-row">
          <button type="button" className="tx-btn tx-btn--sub ws-export" onClick={exportNow}>내보내기</button>
          <button type="button" className="tx-btn tx-btn--sub ws-import" onClick={() => file.current?.click()}>가져오기</button>
          <input ref={file} type="file" accept=".json,application/json" className="ws-import-file" hidden onChange={(e) => void importNow(e)} />
        </div>
        <p className="tj-note">파일에는 판의 자리 · 열 폭 · 칸 높이 · 이름 붙인 배치의 이름만 있습니다(계좌 · 종목 · 설정은 싣지 않습니다). 가져오기는 꼴이 하나라도 틀리면 파일 전체를 거절합니다.</p>
      </section>

      <div className="ws-sheet-out" role="status">
        {msg ? <p className="ws-sheet-msg" data-tone={msg.tone}>{msg.text}</p> : null}
        {msg?.reasons?.length ? <ul className="ws-sheet-reasons">{msg.reasons.map((r) => <li key={r}>{r}</li>)}</ul> : null}
      </div>
    </Sheet>
  );
}
