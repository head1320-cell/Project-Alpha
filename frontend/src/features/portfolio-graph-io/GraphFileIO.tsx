"use client";
/**
 * 포트폴리오 그래프 내보내기·불러오기 (BI3 · 사용자 결정: 지금은 파일, 서버 저장은 나중)
 * ==========================================================================
 * 내보내기는 파라미터·위치만 담은 `*.portfolio-graph.json`. 불러오기는 파일 선택과 드래그앤드롭
 * 둘 다 `readGraphFile` 하나를 지난다 — 경로가 둘이면 검사가 갈라진다.
 * ★불러온 즉시 캔버스에 뜨게 하는 것★은 받는 쪽(`onLoad`)의 일이다.
 */
import { useRef } from "react";
import { Download, Upload } from "lucide-react";
import {
  exportFileName,
  parseFile,
  type GraphDoc,
  type ParseResult,
} from "@/entities/portfolio-graph";

export async function readGraphFile(file: File): Promise<ParseResult> {
  let text: string;
  try {
    text = await file.text();
  } catch (e) {
    return { doc: null, problems: [`파일을 읽지 못했습니다 — ${(e as Error).message}`] };
  }
  return parseFile(text);
}

export function downloadGraph(doc: GraphDoc): string {
  const name = exportFileName(doc.meta?.name);
  const blob = new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
  return name;
}

const BTN = "pg-btn";

export function ExportButton({ getDoc, disabled }: { getDoc: () => GraphDoc; disabled?: boolean }) {
  return (
    <button type="button" className={`pg-export ${BTN}`} disabled={disabled}
            onClick={() => downloadGraph(getDoc())}
            title="파라미터·위치만 저장합니다(실행 결과는 담지 않습니다 — 불러와서 다시 실행)">
      <Download size={13} /> 내보내기
    </button>
  );
}

export function ImportControl({ onLoad }: { onLoad: (r: ParseResult, fileName: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <button type="button" className={`pg-import ${BTN}`} onClick={() => input.current?.click()}>
        <Upload size={13} /> 불러오기
      </button>
      <input ref={input} type="file" accept=".json,application/json" className="pg-import-input" hidden
             onChange={async (e) => {
               const f = e.target.files?.[0];
               e.target.value = "";          // 같은 파일을 다시 골라도 onChange 가 오도록
               if (f) onLoad(await readGraphFile(f), f.name);
             }} />
    </>
  );
}
