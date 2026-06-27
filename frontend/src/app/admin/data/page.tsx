import DbStatusPanel from "@/components/admin/DbStatusPanel";
import FlowsAdminPanel from "@/components/admin/FlowsAdminPanel";

export const metadata = {
  title: "Data Infra · DB Status",
  description: "전 도구 DB 적재 현황 + 적재 트리거 (지수/ETF/수급)",
};

export default function DataInfraPage() {
  return (
    <div className="pb-10">
      <DbStatusPanel />
      <FlowsAdminPanel />
    </div>
  );
}
