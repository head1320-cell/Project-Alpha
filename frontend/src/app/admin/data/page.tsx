import DbStatusPanel from "@/components/admin/DbStatusPanel";

export const metadata = {
  title: "Data Infra · DB Status",
  description: "전 도구 DB 적재 현황 + 적재 트리거",
};

export default function DataInfraPage() {
  return <DbStatusPanel />;
}
