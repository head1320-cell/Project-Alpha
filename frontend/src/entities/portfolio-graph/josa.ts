/**
 * 한국어 조사 — 마지막 한글 글자의 받침으로 고른다(따옴표·영문·숫자는 건너뛴다).
 * 서버(`design_procedure._obj`·`_subj`)와 같은 규칙. 한글이 없으면 받침 없음으로 본다.
 */
function lastHangul(word: string): number | null {
  const ch = [...word].reverse().find((c) => c >= "가" && c <= "힣");
  return ch ? (ch.charCodeAt(0) - 0xac00) % 28 : null;
}

/** `pair` = [받침 있을 때, 없을 때] — 예: `josa("비중", ["을", "를"])` → "비중을". */
export function josa(word: string, pair: [string, string]): string {
  const b = lastHangul(word);
  return word + (b ? pair[0] : pair[1]);
}

/** 으로/로 — ㄹ 받침(8)은 "로". */
export function euro(word: string): string {
  const b = lastHangul(word);
  return word + (b && b !== 8 ? "으로" : "로");
}
