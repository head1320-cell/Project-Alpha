"use client";
// 05 VIEWS — 입력이 필요하므로 POST 경로를 쓰는 전용 패널.
// 프론티어 카드와 결과 렌더는 StudioPanel 과 **공유**한다.
import { ViewsStudio } from "@/widgets/macro/ViewsStudio";

export default function Page() {
  return <ViewsStudio />;
}
