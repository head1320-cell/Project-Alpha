"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// useFocusTrap — 모달 안에 키보드 포커스를 가둔다 (스펙 §8.1).
//
// 무엇이 없었나
// ─────────────────────────────────────────────────────────────────────────────
// 창들은 `role="dialog"`·`aria-modal`·Escape·autoFocus 를 갖췄지만 **Tab 을 막는 것이
// 아무것도 없었다.** 마지막 요소에서 Tab 을 누르면 포커스가 뒤쪽 페이지로 걸어 나가고,
// 화면에는 모달이 떠 있는데 키보드는 그 아래를 조작한다. 스크린리더 사용자에게는
// "닫히지 않은 창 밖으로 나갔다" 는 사실조차 보이지 않는다.
//
// 왜 Radix 가 아닌가
// ─────────────────────────────────────────────────────────────────────────────
// Phase 6c 에서 Radix `Dialog` 로 시도했다가 되돌렸다. 렌더 실패 진단은 이후 스테일 서버
// 문제로 밝혀져 **의심스럽지만**, 함께 측정된 **+20 kB/route** 는 `next build` 산출이라
// 그 버그와 무관하다. ADR 001 은 15 kB 초과를 마이그레이션 중단선으로 정해 두었으므로,
// 진단의 진위와 별개로 Radix Dialog 는 이 규칙에서 탈락한다. 손으로 짠 이 훅은 0 kB 다.
//
// ★포커스 가능한 요소를 캐시하지 않는다★
// 이 창들은 선택이 바뀌면 우측 패널을 통째로 교체한다(팩터를 고르면 파라미터 입력이 생긴다).
// 열릴 때 목록을 한 번 만들어 두면 그 목록은 곧 낡고, 이미 DOM 에서 떨어진 노드로 포커스를
// 보내려 하게 된다. 그래서 Tab 이 눌릴 때마다 다시 질의한다.
// ═══════════════════════════════════════════════════════════════════════════════
import { useEffect } from "react";

/** 탭 순서에 들어가는 요소들. `[hidden]`·`disabled`·`tabindex="-1"` 은 제외한다. */
const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function focusable(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE))
    // 화면에 없는 요소는 탭 순서에도 없다. offsetParent 는 display:none 조상까지 걸러낸다.
    .filter((el) => el.offsetParent !== null || el === document.activeElement);
}

/**
 * `active` 인 동안 `ref` 안에 포커스를 가둔다. 닫히면 **열기 전 요소로 되돌린다**.
 *
 * Escape·autoFocus·`role`/`aria-modal` 은 건드리지 않는다 — 이미 있고, E2E 계약이다.
 * 이 훅은 **가두기만** 추가한다.
 */
export function useFocusTrap(
  ref: React.RefObject<HTMLElement | null>,
  active: boolean,
): void {
  useEffect(() => {
    if (!active) return;
    const root = ref.current;
    if (!root) return;

    // 열기 전에 포커스가 있던 곳 — 닫을 때 여기로 돌려보낸다. 안 그러면 포커스가 문서
    // 처음으로 튕겨서, 키보드 사용자는 방금 누른 버튼을 다시 찾아가야 한다.
    const opener = document.activeElement as HTMLElement | null;

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;             // Escape 는 각 창이 이미 처리한다
      const items = focusable(root);
      if (items.length === 0) {
        e.preventDefault();                    // 가둘 대상이 없으면 밖으로 내보내지도 않는다
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const cur = document.activeElement as HTMLElement | null;

      // 포커스가 창 밖에 있으면(브라우저가 이미 내보냈거나 초기 상태) 안으로 끌어온다.
      if (!cur || !root.contains(cur)) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
        return;
      }
      if (!e.shiftKey && cur === last) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && cur === first) {
        e.preventDefault();
        last.focus();
      }
      // 그 사이는 브라우저 기본 동작에 맡긴다 — 순서를 우리가 다시 구현하지 않는다.
    };

    // ★capture 로 듣는다★ 안쪽 위젯(ToggleGroup 의 roving focus 등)이 Tab 을 먼저 처리해
    // 버리면 경계에서 가두지 못한다. 경계 밖으로 나가는 것만 막고 나머지는 통과시킨다.
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      // 닫힌 뒤 되돌리기. 그 사이 opener 가 사라졌으면 아무것도 하지 않는다(강제하지 않는다).
      if (opener && document.contains(opener)) opener.focus();
    };
  }, [ref, active]);
}
