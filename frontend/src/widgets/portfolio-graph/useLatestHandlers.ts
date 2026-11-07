"use client";
/**
 * 늘 같은 손잡이 (CF 3부 R8 — 재서 찾음).
 * 그릴 때마다 새로 만든 함수를 React Flow 에 넘기면, React Flow 는 그것을 바뀐 설정으로 받아 카드·선 감싸개를 모두 다시 그린다
 * (200노드에서 끌기 한 걸음마다 감싸개 400개). 여기서 돌려주는 함수는 처음 한 번 만들어 그대로 두고, 부를 때마다 ★마지막으로 그린 때의★
 * 손잡이를 부른다 — 하는 일은 예전과 같다(예전에도 React Flow 는 마지막으로 받은 손잡이를 불렀다).
 * 열쇠(손잡이 이름)는 처음 그린 때의 것으로 고정된다 — 손잡이를 조건에 따라 넣었다 뺐다 하지 않는 곳에서만 쓴다.
 */
import { useMemo, useRef } from "react";

// 손잡이마다 인자가 다르다 — React Flow 의 타입 그대로 넘기려고 인자는 any 로 받는다.
type Handlers = Record<string, (...args: any[]) => unknown>;

export function useLatestHandlers<T extends Handlers>(handlers: T): T {
  const latest = useRef(handlers);
  latest.current = handlers;
  return useMemo(() => {
    const out: Handlers = {};
    for (const k of Object.keys(latest.current)) out[k] = (...args: unknown[]) => latest.current[k](...args);
    return out as T;
  }, []);
}
