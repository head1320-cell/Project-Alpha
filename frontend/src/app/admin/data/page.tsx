import FlowsAdminPanel from "@/components/admin/FlowsAdminPanel";

export const metadata = {
  title: "Data Infra · Investor Flows",
  description: "투자자 수급 적재 현황 + KRX 과거 백필",
};

export default function DataInfraPage() {
  return <FlowsAdminPanel />;
}
