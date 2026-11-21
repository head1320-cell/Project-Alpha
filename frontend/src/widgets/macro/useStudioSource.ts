/**
 * 스튜디오 머리에 넘길 데이터 출처 (U2-b) — 규칙은 `studioSource.ts`(순수), 여기는 게이트를 묻기만 한다.
 * ★계열을 쓸 때만 묻는다★(뷰 만들기는 요청이 늘지 않는다). ★계열을 쓰지 않으면 캐시에 게이트가 있어도 표지를 내지 않는다★
 * — 다른 화면(매크로 조종석 · 계열 스튜디오)에서 받은 게이트가 같은 열쇠의 캐시에 남아 있어도(화면 안 이동) 그렇다.
 */
import { useQuery } from "@tanstack/react-query";
import { macroApi } from "@/entities/macro/api";
import type { StudioDescriptor, StudioResult } from "@/entities/macro/studios";
import type { ProvSource } from "@/shared/ui/provenance";
import { studioSource, studioUsesSeries } from "./studioSource";

export function useStudioSource(d: StudioDescriptor | null, run: StudioResult | null | undefined): ProvSource | null {
  const uses = studioUsesSeries(d, run);
  const gate = useQuery({ queryKey: ["macro", "connection-status"], queryFn: () => macroApi.connectionStatus(), enabled: uses });
  return uses ? studioSource(gate) : null;
}
